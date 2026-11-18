# Copyright 2026 z/VM OTel Exporter contributors
# SPDX-License-Identifier: Apache-2.0

"""Local z/VM paging, spool, and system CPU via the ``vmcp`` command.

Three CP commands run, sequentially, at most once per ``vmcp.interval``:

* ``QUERY ALLOC PAGE`` (privilege class D)
* ``QUERY ALLOC SPOOL`` (privilege class D)
* ``INDICATE LOAD`` (privilege class G)

Nothing else is issued. There is no per-guest fan-out and no CP Monitor.
Prometheus scrapes read the cached samples and do not start a new command.
"""

from __future__ import annotations

import fcntl
import logging
import os
import re
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from select import select
from typing import IO

from zvm_otel_exporter.config import VmcpConfig
from zvm_otel_exporter.models import Sample

log = logging.getLogger(__name__)

_MAX_OUTPUT = 64 * 1024
_BACKOFF_CAP = 900.0
_PAGE_COMMAND = ("QUERY", "ALLOC", "PAGE")
_SPOOL_COMMAND = ("QUERY", "ALLOC", "SPOOL")
_LOAD_COMMAND = ("INDICATE", "LOAD")
_COMMANDS = (
    ("page", _PAGE_COMMAND),
    ("spool", _SPOOL_COMMAND),
    ("load", _LOAD_COMMAND),
)

_SCALED = re.compile(r"(\d+)([KMG])?", re.IGNORECASE)
_VOLID = re.compile(r"[A-Z0-9]{1,6}\Z", re.IGNORECASE)
_RDEV = re.compile(r"[0-9A-F]{1,4}\Z", re.IGNORECASE)
_AVGPROC = re.compile(
    r"AVGPROC\s*-\s*(\d+(?:\.\d+)?)\s*%(?:\s+(\d+))?",
    re.IGNORECASE,
)
_PAGING_RATE = re.compile(r"PAGING\s*-\s*(\d+)\s*/\s*SEC", re.IGNORECASE)
# CP message id, matching Feilong: module letters, a 3- or 4-digit number, then
# severity E, I, or W. Only E rejects the command output.
_HCP_MESSAGE = re.compile(r"HCP[A-Z0-9]*\d{3,4}([EIW])", re.IGNORECASE)


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    returncode: int = 0
    timed_out: bool = False
    not_found: bool = False
    overflow: bool = False

    @property
    def failed(self) -> bool:
        return self.not_found or self.timed_out or self.overflow or self.returncode != 0


@dataclass(frozen=True)
class AllocStats:
    allocated: int
    used: int


@dataclass(frozen=True)
class LoadStats:
    utilization: float
    cpu_count: int | None
    paging_rate: int | None


@dataclass(frozen=True)
class VmcpReading:
    samples: tuple[Sample, ...]
    ok: bool


class SubprocessRunner:
    """Run ``vmcp`` with a hard timeout and a capped capture buffer."""

    def __init__(self, command: str) -> None:
        self._command = command

    def run(self, args: tuple[str, ...], timeout: float) -> CommandResult:
        try:
            proc = subprocess.Popen(
                [self._command, *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                start_new_session=True,
            )
        except FileNotFoundError:
            return CommandResult(stdout="", not_found=True, returncode=127)
        except OSError:
            return CommandResult(stdout="", returncode=126)
        stdout, _stderr, timed_out, overflow = _capture_bounded(proc, timeout)
        if timed_out or overflow:
            returncode = _reap(proc, kill=True)
            return CommandResult(
                stdout="",
                returncode=returncode if returncode is not None else 124,
                timed_out=timed_out,
                overflow=overflow,
            )
        returncode = _reap(proc, kill=False)
        text = stdout.decode("utf-8", errors="replace")
        return CommandResult(stdout=text, returncode=0 if returncode is None else returncode)


class VmcpSource:
    """Cached paging, spool, and system CPU samples."""

    def __init__(
        self,
        config: VmcpConfig,
        runner: SubprocessRunner | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._config = config
        self._runner = runner or SubprocessRunner(config.command)
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._next_run = 0.0
        self._last_run = 0.0
        self._duration = 0.0
        self._failures = 0
        self._ok = False
        self._page: AllocStats | None = None
        self._spool: AllocStats | None = None
        self._load: LoadStats | None = None

    @property
    def cached_at(self) -> float | None:
        """Monotonic time of the last command pass, or None before the first pass."""

        if self._last_run <= 0:
            return None
        return self._last_run

    @property
    def clock(self) -> Callable[[], float]:
        return self._clock

    def collect(self, host: str) -> VmcpReading:
        now = self._clock()
        if not self._lock.acquire(blocking=False):
            return self._reading(host, now)
        try:
            if now >= self._next_run:
                self._refresh(now)
            return self._reading(host, now)
        finally:
            self._lock.release()

    def _refresh(self, now: float) -> None:
        started = self._clock()
        texts: dict[str, str] = {}
        failed = False
        for name, args in _COMMANDS:
            result = self._runner.run(args, self._config.timeout)
            reason = _failure_reason(result)
            if reason is None and _cp_error(result.stdout):
                reason = "cp error"
            if reason is not None:
                failed = True
                texts[name] = ""
                log.warning("vmcp %s failed: %s", " ".join(args), reason)
                continue
            texts[name] = result.stdout
        self._duration = max(0.0, self._clock() - started)
        self._page = parse_alloc(texts.get("page", ""))
        self._spool = parse_alloc(texts.get("spool", ""))
        self._load = parse_load(texts.get("load", ""))
        if self._page is None and texts.get("page"):
            failed = True
            log.warning("vmcp QUERY ALLOC PAGE returned no paging totals")
        if self._spool is None and texts.get("spool"):
            failed = True
            log.warning("vmcp QUERY ALLOC SPOOL returned no spool totals")
        if self._load is None and texts.get("load"):
            failed = True
            log.warning("vmcp INDICATE LOAD returned no AVGPROC value")
        if self._page is None or self._spool is None or self._load is None:
            failed = True
        self._last_run = self._clock()
        if failed:
            self._failures += 1
            delay = min(self._config.interval * (2**self._failures), _BACKOFF_CAP)
            self._next_run = now + max(delay, self._config.interval)
            self._ok = False
            return
        self._failures = 0
        self._next_run = now + self._config.interval
        self._ok = True

    def _reading(self, host: str, now: float) -> VmcpReading:
        label = host or self._config.host_name or "local"
        attributes = {"zvm.host.name": label}
        samples: list[Sample] = []
        if self._page is not None:
            samples.extend(_alloc_samples("zvm.paging", self._page, attributes))
        if self._spool is not None:
            samples.extend(_alloc_samples("zvm.spool", self._spool, attributes))
        if self._load is not None:
            samples.append(Sample("zvm.system.cpu.utilization", self._load.utilization, attributes))
            if self._load.cpu_count is not None:
                samples.append(
                    Sample("zvm.system.cpu.count", float(self._load.cpu_count), attributes)
                )
            if self._load.paging_rate is not None:
                samples.append(Sample("zvm.paging.rate", float(self._load.paging_rate), attributes))
        age = 0.0 if self._last_run <= 0 else max(0.0, now - self._last_run)
        samples.extend(
            (
                Sample("zvm.vmcp.up", 1.0 if self._ok else 0.0, attributes),
                Sample("zvm.vmcp.cache_age", age, attributes),
                Sample("zvm.vmcp.command_duration", self._duration, attributes),
                Sample("zvm.vmcp.consecutive_failures", float(self._failures), attributes),
            )
        )
        return VmcpReading(tuple(samples), self._ok)


def parse_alloc(text: str) -> AllocStats | None:
    """Parse ``QUERY ALLOC PAGE`` or ``QUERY ALLOC SPOOL``.

    Volume rows are preferred when every one of them has an unscaled integer.
    CP's SUMMARY line rounds large totals to Ki-pages (K = 1024), so the row
    sum matches the 2017 exporter's page counts more closely. SUMMARY is the
    fallback when the volume list is absent or already scaled.
    """

    if not text.strip() or _cp_error(text):
        return None
    allocated = 0
    used = 0
    rows = 0
    scaled_row = False
    summary: tuple[int, int] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("ready"):
            continue
        if line.upper().startswith("SUMMARY"):
            parsed = _summary_pair(line)
            if parsed is not None:
                summary = parsed
            continue
        if line.upper().startswith("USABLE"):
            continue
        row = _volume_row(line)
        if row is None:
            continue
        rows += 1
        allocated += row[0]
        used += row[1]
        scaled_row = scaled_row or row[2]
    if rows and not scaled_row:
        return AllocStats(allocated, used)
    if summary is not None:
        return AllocStats(*summary)
    if rows:
        return AllocStats(allocated, used)
    return None


def parse_load(text: str) -> LoadStats | None:
    """Parse ``INDICATE LOAD``. Per-processor lines are ignored."""

    if not text.strip() or _cp_error(text):
        return None
    avg = _AVGPROC.search(text)
    if avg is None:
        return None
    percent = float(avg.group(1))
    if percent < 0 or percent > 100:
        return None
    count = int(avg.group(2)) if avg.group(2) else None
    rate_match = _PAGING_RATE.search(text)
    rate = int(rate_match.group(1)) if rate_match else None
    return LoadStats(percent / 100.0, count, rate)


def _alloc_samples(prefix: str, stats: AllocStats, attributes: dict[str, str]) -> list[Sample]:
    samples = [
        Sample(f"{prefix}.allocated", float(stats.allocated), attributes),
        Sample(f"{prefix}.used", float(stats.used), attributes),
    ]
    if stats.allocated > 0:
        ratio = min(1.0, stats.used / stats.allocated)
        samples.append(Sample(f"{prefix}.utilization", ratio, attributes))
    return samples


def _volume_row(line: str) -> tuple[int, int, bool] | None:
    parts = line.split()
    if len(parts) < 7 or not _VOLID.match(parts[0]) or not _RDEV.match(parts[1]):
        return None
    total = _scaled_token(parts[4])
    used = _scaled_token(parts[5])
    if total is None or used is None:
        return None
    return total[0], used[0], total[1] or used[1]


def _summary_pair(line: str) -> tuple[int, int] | None:
    without_percent = re.sub(r"\d+(?:\.\d+)?\s*%", " ", line)
    numbers: list[int] = []
    for match in _SCALED.finditer(without_percent):
        numbers.append(_apply_scale(int(match.group(1)), match.group(2)))
    if len(numbers) < 2:
        return None
    return numbers[0], numbers[1]


def _scaled_token(token: str) -> tuple[int, bool] | None:
    match = _SCALED.fullmatch(token)
    if match is None:
        return None
    return _apply_scale(int(match.group(1)), match.group(2)), bool(match.group(2))


def _apply_scale(value: int, suffix: str | None) -> int:
    power = {None: 0, "": 0, "K": 1, "M": 2, "G": 3}[(suffix or "").upper()]
    return value * (1024**power)


def _cp_error(text: str) -> bool:
    """True when CP emitted an error-severity HCP message."""

    return any(match.group(1).upper() == "E" for match in _HCP_MESSAGE.finditer(text))


def _failure_reason(result: CommandResult) -> str | None:
    if result.not_found:
        return "vmcp program not found"
    if result.overflow:
        return "output exceeded 64 KiB"
    if result.timed_out:
        return "timeout"
    if result.returncode != 0:
        return f"exit {result.returncode}"
    return None


def _capture_bounded(
    proc: subprocess.Popen[bytes], timeout: float
) -> tuple[bytes, bytes, bool, bool]:
    """Read stdout and stderr until EOF, the timeout, or the byte cap.

    Each stream keeps at most ``_MAX_OUTPUT`` bytes. One extra read detects
    overflow, and that extra byte is not stored. The caller reaps ``proc``.
    """

    deadline = time.monotonic() + timeout
    stdout = bytearray()
    stderr = bytearray()
    streams: dict[int, tuple[IO[bytes], bytearray]] = {}
    for stream, buf in ((proc.stdout, stdout), (proc.stderr, stderr)):
        if stream is None:
            continue
        _set_nonblocking(stream.fileno())
        streams[stream.fileno()] = (stream, buf)
    while streams:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return bytes(stdout), bytes(stderr), True, False
        readable, _, _ = select(list(streams), [], [], remaining)
        if not readable:
            return bytes(stdout), bytes(stderr), True, False
        for fd in readable:
            stream, buf = streams[fd]
            try:
                chunk = os.read(fd, 8192)
            except BlockingIOError:
                continue
            if not chunk:
                streams.pop(fd, None)
                stream.close()
                continue
            room = _MAX_OUTPUT - len(buf)
            if room <= 0 or len(chunk) > room:
                return bytes(stdout), bytes(stderr), False, True
            buf.extend(chunk)
    return bytes(stdout), bytes(stderr), False, False


def _set_nonblocking(fd: int) -> None:
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)


def _reap(proc: subprocess.Popen[bytes], *, kill: bool) -> int | None:
    """Stop the process group when asked, then wait so it cannot stay a zombie."""

    if kill and proc.poll() is None:
        _kill_group(proc)
    for stream in (proc.stdout, proc.stderr):
        if stream is not None and not stream.closed:
            stream.close()
    try:
        return proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        return proc.wait(timeout=5)


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except PermissionError:
        proc.kill()
