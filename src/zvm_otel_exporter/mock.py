# Copyright 2026 z/VM OTel Exporter contributors
# SPDX-License-Identifier: Apache-2.0

"""In-process Feilong stand-in for tests and local demos.

The routes and payloads follow the Feilong REST reference for the read-only
calls the exporter uses. Nothing here talks to a hypervisor.
"""

from __future__ import annotations

import argparse
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, unquote, urlparse

DEFAULT_ADMIN_TOKEN = "test-admin-token"
DEFAULT_AUTH_TOKEN = "test-auth-token"


def load_fixture() -> dict:
    raw = (
        files("zvm_otel_exporter.fixtures")
        .joinpath("mock_feilong.json")
        .read_text(encoding="utf-8")
    )
    return json.loads(raw)


def envelope(output: object, *, rc: int = 0, errmsg: str = "") -> dict:
    return {
        "rs": 0,
        "overallRC": rc,
        "modID": None,
        "rc": rc,
        "errmsg": errmsg,
        "output": output,
    }


class MockFeilong(ThreadingHTTPServer):
    """Feilong-shaped HTTP server backed by the packaged fixture."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int] = ("127.0.0.1", 0),
        *,
        admin_token: str = DEFAULT_ADMIN_TOKEN,
        auth_token: str = DEFAULT_AUTH_TOKEN,
        require_auth: bool = True,
    ) -> None:
        self.admin_token = admin_token
        self.auth_token = auth_token
        self.require_auth = require_auth
        self.fixture = load_fixture()
        self.fail_paths: set[str] = set()
        self.garbage_paths: set[str] = set()
        self.reject_data_once = False
        self.echo_bad_token = False
        self.token_mints = 0
        self.data_tokens: list[str] = []
        self.data_admin_headers = 0
        self.requests: list[str] = []
        self._state_lock = threading.Lock()
        super().__init__(address, _Handler)

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: MockFeilong

    def do_GET(self) -> None:  # noqa: N802
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self._handle("POST")

    def log_message(self, fmt: str, *args) -> None:
        return

    def _handle(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        if method == "POST" and path == "/token":
            self._token()
            return
        if not self._authorized():
            return
        with self.server._state_lock:
            self.server.requests.append(path)
        if path in self.server.garbage_paths:
            body = b"not-json"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in self.server.fail_paths:
            self._json(503, envelope(None, rc=1, errmsg="mock failure"))
            return
        output = self._route(path, query)
        if output is None:
            self._json(404, envelope(None, rc=404, errmsg="not found"))
            return
        self._json(200, envelope(output))

    def _token(self) -> None:
        presented = self.headers.get("X-Admin-Token") or ""
        expected = self.server.admin_token
        if expected and not _eq(presented, expected):
            message = "unauthorized"
            if self.server.echo_bad_token and presented:
                message = f"bad token: {presented}"
            self._json(401, envelope(None, rc=1, errmsg=message))
            return
        with self.server._state_lock:
            self.server.token_mints += 1
        body = json.dumps(envelope({})).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Auth-Token", self.server.auth_token)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if not self.server.require_auth:
            return True
        token = self.headers.get("X-Auth-Token") or ""
        if self.headers.get("X-Admin-Token"):
            with self.server._state_lock:
                self.server.data_admin_headers += 1
        with self.server._state_lock:
            self.server.data_tokens.append(token)
            reject = self.server.reject_data_once
            if reject:
                self.server.reject_data_once = False
        if reject or not _eq(token, self.server.auth_token):
            self._json(401, envelope(None, rc=1, errmsg="unauthorized"))
            return False
        return True

    def _route(self, path: str, query: dict[str, str]) -> object | None:
        fixture = self.server.fixture
        if path == "/":
            return fixture["version"]
        if path == "/smapi_health":
            return fixture["smapi_health"]
        if path == "/host":
            return fixture["host"]
        if path == "/host/diskpool":
            return _diskpool(fixture, query)
        if path == "/host/guests":
            return fixture["host_guests"]
        if path == "/host/ssi":
            return fixture["ssi"]
        if path == "/host/pcif":
            return fixture["pcif"]
        if path == "/guests":
            return fixture["guests"]
        if path == "/guests/stats":
            return _filter_userids(fixture["stats"], query.get("userid"))
        if path == "/guests/interfacestats":
            return _filter_userids(fixture["interfaces"], query.get("userid"))
        if path == "/vswitches":
            return list(fixture["vswitches"])
        parts = [part for part in path.split("/") if part]
        if len(parts) == 3 and parts[0] == "guests" and parts[2] == "power_state":
            return fixture["power"].get(parts[1])
        if len(parts) == 3 and parts[0] == "guests" and parts[2] == "disks":
            return fixture["disks"].get(parts[1])
        if len(parts) == 2 and parts[0] == "vswitches":
            return fixture["vswitches"].get(parts[1])
        return None

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _diskpool(fixture: dict, query: dict[str, str]) -> dict:
    output = dict(fixture["diskpool"]["summary"])
    if query.get("details", "false").lower() == "true":
        for name, volumes in fixture["diskpool"]["volumes"].items():
            output[name] = volumes
    return output


def _filter_userids(source: dict, raw: str | None) -> dict:
    if not raw:
        return dict(source)
    wanted = [part.strip() for part in raw.split(",") if part.strip()]
    return {userid: source[userid] for userid in wanted if userid in source}


def _eq(left: str, right: str) -> bool:
    left_b = left.encode()
    right_b = right.encode()
    if len(left_b) != len(right_b):
        return False
    return hmac.compare_digest(left_b, right_b)


def start_mock(**kwargs) -> MockFeilong:
    server = MockFeilong(**kwargs)
    thread = threading.Thread(target=server.serve_forever, name="mock-feilong", daemon=True)
    thread.start()
    server.serve_thread = thread  # type: ignore[attr-defined]
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="zvm-otel-exporter-mock",
        description="Serve the packaged Feilong fixture over HTTP.",
    )
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--admin-token", default=DEFAULT_ADMIN_TOKEN)
    parser.add_argument("--auth-token", default=DEFAULT_AUTH_TOKEN)
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="Accept data requests without an X-Auth-Token header",
    )
    args = parser.parse_args(argv)
    server = MockFeilong(
        (args.listen, args.port),
        admin_token=args.admin_token,
        auth_token=args.auth_token,
        require_auth=not args.no_auth,
    )
    print(f"mock Feilong listening on {server.url}", flush=True)
    print("fixture admin token is the --admin-token value (default test-admin-token)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
