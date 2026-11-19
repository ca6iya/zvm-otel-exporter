# Copyright 2026 z/VM OTel Exporter contributors
# SPDX-License-Identifier: Apache-2.0

"""Configuration from a YAML file, environment variables, and CLI flags.

Later layers win: file, then environment, then CLI. Secrets are accepted from
any layer and are omitted from ``repr``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

_COLLECTORS = (
    "host",
    "disk_pool",
    "guests",
    "interfaces",
    "power_state",
    "minidisks",
    "vswitches",
    "ssi",
    "pcif",
    "smapi",
    "version",
)
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class ConfigError(Exception):
    """The configuration is missing or contradictory."""


@dataclass
class FeilongConfig:
    url: str = ""
    admin_token: str = ""
    auth_token: str = ""
    auth: str = "token"
    verify_tls: bool = True
    ca_file: str = ""
    timeout: float = 30.0
    disk_pools: tuple[str, ...] = ()
    disk_pool_details: bool = True
    batch_size: int = 25
    concurrency: int = 8
    max_guests: int = 500
    max_vswitches: int = 50
    enabled: bool = True
    per_guest_limit: int = 32


@dataclass
class VmcpConfig:
    """Local CP queries. Disabled until an operator turns them on."""

    enabled: bool = False
    command: str = "vmcp"
    interval: float = 60.0
    timeout: float = 5.0
    host_name: str = ""


@dataclass
class IdentityConfig:
    """Optional labels. Empty strings mean 'use what was discovered'."""

    sysinfo_path: str = "/proc/sysinfo"
    interval: float = 600.0
    host_name: str = ""
    system_name: str = ""
    lpar_name: str = ""
    lpar_number: str = ""
    cpc_type: str = ""
    cpc_model: str = ""
    cpc_sequence: str = ""
    cpc_plant: str = ""
    site: str = ""
    environment: str = ""
    ssi_name: str = ""
    arch: str = ""
    hypervisor: str = ""
    exporter_guest: str = ""
    vm_level: str = ""


@dataclass
class ServerConfig:
    listen: str = "0.0.0.0"
    port: int = 9110


@dataclass
class OtlpConfig:
    enabled: bool = False
    endpoint: str = ""
    protocol: str = "grpc"
    headers: dict[str, str] = field(default_factory=dict)
    insecure: bool = False
    timeout: float = 10.0


@dataclass
class CollectorToggles:
    host: bool = True
    disk_pool: bool = True
    guests: bool = True
    interfaces: bool = True
    power_state: bool = True
    minidisks: bool = False
    vswitches: bool = True
    ssi: bool = True
    pcif: bool = False
    smapi: bool = True
    version: bool = True


@dataclass
class Config:
    feilong: FeilongConfig = field(default_factory=FeilongConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    scrape_interval: float = 60.0
    prometheus_enabled: bool = True
    otlp: OtlpConfig = field(default_factory=OtlpConfig)
    collectors: CollectorToggles = field(default_factory=CollectorToggles)
    vmcp: VmcpConfig = field(default_factory=VmcpConfig)
    identity: IdentityConfig = field(default_factory=IdentityConfig)
    log_level: str = "INFO"

    def secrets(self) -> list[str]:
        values = [
            self.feilong.admin_token,
            self.feilong.auth_token,
            *self.otlp.headers.values(),
        ]
        unique: list[str] = []
        for value in values:
            if value and value not in unique:
                unique.append(value)
        return unique

    def __repr__(self) -> str:
        return (
            f"Config(feilong_url={self.feilong.url!r}, auth={self.feilong.auth}, "
            f"admin_token={'set' if self.feilong.admin_token else 'unset'}, "
            f"auth_token={'set' if self.feilong.auth_token else 'unset'}, "
            f"prometheus={self.prometheus_enabled}, otlp={self.otlp.enabled}, "
            f"otlp_header_count={len(self.otlp.headers)})"
        )


def load_config(args: Any = None, environ: Mapping[str, str] | None = None) -> Config:
    """Build a validated config.

    ``environ`` defaults to ``os.environ``. Tests pass an explicit mapping so
    the developer environment cannot leak into the result.
    """

    env = os.environ if environ is None else environ
    config = Config()
    path = _arg(args, "config") or env.get("ZVM_EXPORTER_CONFIG")
    if path:
        config = _apply_file(config, Path(path))
    config = _apply_env(config, env)
    config = _apply_args(config, args)
    validate(config)
    return config


def validate(config: Config) -> None:
    errors: list[str] = []
    if config.feilong.enabled:
        url = config.feilong.url.strip()
        if not url:
            errors.append("Feilong URL is required")
        else:
            parts = urlsplit(url)
            if parts.scheme not in {"http", "https"} or not parts.netloc:
                errors.append("Feilong URL must be an absolute http or https URL")
            if parts.username or parts.password:
                errors.append("do not put credentials in the Feilong URL; set a token instead")
        if config.feilong.auth not in {"token", "none"}:
            errors.append("Feilong auth must be 'token' or 'none'")
        if config.feilong.auth == "token" and not (
            config.feilong.admin_token or config.feilong.auth_token
        ):
            errors.append("token auth requires feilong.admin_token or feilong.auth_token")
    if config.feilong.timeout <= 0:
        errors.append("Feilong timeout must be positive")
    if config.feilong.batch_size < 1:
        errors.append("Feilong batch_size must be at least 1")
    if config.feilong.concurrency < 1:
        errors.append("Feilong concurrency must be at least 1")
    if config.feilong.max_guests < 1:
        errors.append("Feilong max_guests must be at least 1")
    if config.feilong.per_guest_limit < 0:
        errors.append("Feilong per_guest_limit must be zero or positive")
    if config.feilong.ca_file and not Path(config.feilong.ca_file).is_file():
        errors.append(f"CA file not found: {config.feilong.ca_file}")
    if config.scrape_interval < 1:
        errors.append("scrape interval must be at least 1 second")
    if config.vmcp.interval < 30:
        errors.append("vmcp interval must be at least 30 seconds")
    if config.identity.interval < 600:
        errors.append("identity interval must be at least 600 seconds")
    if not 0 < config.vmcp.timeout <= 10:
        errors.append("vmcp timeout must be greater than 0 and at most 10 seconds")
    if _unsafe_command(config.vmcp.command):
        errors.append("vmcp command must be an executable path without shell syntax")
    if len(config.vmcp.host_name) > 64:
        errors.append("vmcp host_name must be at most 64 characters")
    if not (1 <= config.server.port <= 65535):
        errors.append("listen port must be between 1 and 65535")
    if not config.prometheus_enabled and not config.otlp.enabled:
        errors.append("enable the Prometheus endpoint, the OTLP exporter, or both")
    if config.otlp.enabled:
        if not config.otlp.endpoint.strip():
            errors.append("OTLP endpoint is required when the OTLP exporter is enabled")
        if config.otlp.protocol not in {"grpc", "http"}:
            errors.append("OTLP protocol must be grpc or http")
        if config.otlp.timeout <= 0:
            errors.append("OTLP timeout must be positive")
    if config.log_level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        errors.append("log level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
    enabled = [name for name in _COLLECTORS if getattr(config.collectors, name)]
    feilong_active = config.feilong.enabled and bool(enabled)
    if not feilong_active and not config.vmcp.enabled:
        errors.append("enable a Feilong collector or the vmcp collector")
    if errors:
        raise ConfigError("; ".join(errors))


def _unsafe_command(command: str) -> bool:
    if not command.strip():
        return True
    return any(character in command for character in " \t;|&$`<>\n\r\\")


def _apply_file(config: Config, path: Path) -> Config:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"could not parse {path}: {exc}") from exc
    if loaded is None:
        return config
    if not isinstance(loaded, dict):
        raise ConfigError("config file must be a mapping")
    _reject_unknown(
        loaded,
        {
            "feilong",
            "server",
            "scrape_interval",
            "exporters",
            "otlp",
            "collectors",
            "vmcp",
            "identity",
            "log_level",
        },
        "config",
    )
    feilong = dict(config.feilong.__dict__)
    if "feilong" in loaded:
        raw = _mapping(loaded["feilong"], "feilong")
        _reject_unknown(
            raw,
            {
                "url",
                "admin_token",
                "auth_token",
                "auth",
                "verify_tls",
                "ca_file",
                "timeout",
                "disk_pools",
                "disk_pool_details",
                "batch_size",
                "concurrency",
                "max_guests",
                "max_vswitches",
                "enabled",
                "per_guest_limit",
            },
            "feilong",
        )
        for key in (
            "url",
            "admin_token",
            "auth_token",
            "auth",
            "verify_tls",
            "ca_file",
            "timeout",
            "disk_pool_details",
            "batch_size",
            "concurrency",
            "max_guests",
            "max_vswitches",
            "enabled",
            "per_guest_limit",
        ):
            if key in raw and raw[key] is not None:
                feilong[key] = raw[key]
        if "disk_pools" in raw and raw["disk_pools"] is not None:
            feilong["disk_pools"] = _pool_tuple(raw["disk_pools"])
    server = dict(config.server.__dict__)
    if "server" in loaded:
        raw = _mapping(loaded["server"], "server")
        _reject_unknown(raw, {"listen", "port"}, "server")
        server.update({key: raw[key] for key in raw if raw[key] is not None})
    otlp = dict(config.otlp.__dict__)
    if "otlp" in loaded:
        raw = _mapping(loaded["otlp"], "otlp")
        _reject_unknown(
            raw, {"enabled", "endpoint", "protocol", "headers", "insecure", "timeout"}, "otlp"
        )
        for key in ("enabled", "endpoint", "protocol", "insecure", "timeout"):
            if key in raw and raw[key] is not None:
                otlp[key] = raw[key]
        if "headers" in raw and raw["headers"] is not None:
            otlp["headers"] = _header_map(raw["headers"])
    collectors = dict(config.collectors.__dict__)
    if "collectors" in loaded:
        raw = _mapping(loaded["collectors"], "collectors")
        _reject_unknown(raw, set(_COLLECTORS), "collectors")
        collectors.update(raw)
    prometheus_enabled = config.prometheus_enabled
    if "exporters" in loaded:
        raw = _mapping(loaded["exporters"], "exporters")
        _reject_unknown(raw, {"prometheus", "otlp"}, "exporters")
        if "prometheus" in raw:
            prometheus_enabled = bool(raw["prometheus"])
        if "otlp" in raw:
            otlp["enabled"] = bool(raw["otlp"])
    scrape = config.scrape_interval
    if "scrape_interval" in loaded and loaded["scrape_interval"] is not None:
        scrape = float(loaded["scrape_interval"])
    vmcp = _vmcp_from_mapping(loaded.get("vmcp"), config.vmcp)
    identity = _identity_from_mapping(loaded.get("identity"), config.identity)
    log_level = str(loaded.get("log_level", config.log_level))
    return Config(
        feilong=FeilongConfig(**_coerce_feilong(feilong)),
        server=ServerConfig(listen=str(server["listen"]), port=int(server["port"])),
        scrape_interval=float(scrape),
        prometheus_enabled=bool(prometheus_enabled),
        otlp=OtlpConfig(
            enabled=bool(otlp["enabled"]),
            endpoint=str(otlp["endpoint"] or ""),
            protocol=str(otlp["protocol"] or "grpc").lower(),
            headers=dict(otlp["headers"]),
            insecure=bool(otlp["insecure"]),
            timeout=float(otlp["timeout"]),
        ),
        collectors=CollectorToggles(**{key: bool(collectors[key]) for key in _COLLECTORS}),
        vmcp=vmcp,
        identity=identity,
        log_level=log_level.upper(),
    )


def _vmcp_from_mapping(raw: object, current: VmcpConfig) -> VmcpConfig:
    if raw is None:
        return current
    parsed = _mapping(raw, "vmcp")
    _reject_unknown(parsed, {"enabled", "command", "interval", "timeout", "host_name"}, "vmcp")
    values = dict(current.__dict__)
    for key in ("enabled", "command", "interval", "timeout", "host_name"):
        if key in parsed and parsed[key] is not None:
            values[key] = parsed[key]
    return VmcpConfig(
        enabled=bool(values["enabled"]),
        command=str(values["command"] or "vmcp"),
        interval=float(values["interval"]),
        timeout=float(values["timeout"]),
        host_name=str(values["host_name"] or ""),
    )


_IDENTITY_KEYS = (
    "sysinfo_path",
    "interval",
    "host_name",
    "system_name",
    "lpar_name",
    "lpar_number",
    "cpc_type",
    "cpc_model",
    "cpc_sequence",
    "cpc_plant",
    "site",
    "environment",
    "ssi_name",
    "arch",
    "hypervisor",
    "exporter_guest",
    "vm_level",
)


def _identity_from_mapping(raw: object, current: IdentityConfig) -> IdentityConfig:
    if raw is None:
        return current
    parsed = _mapping(raw, "identity")
    _reject_unknown(parsed, set(_IDENTITY_KEYS), "identity")
    values = dict(current.__dict__)
    for key in _IDENTITY_KEYS:
        if key in parsed and parsed[key] is not None:
            values[key] = parsed[key]
    values["interval"] = float(values["interval"])
    for key in _IDENTITY_KEYS:
        if key != "interval":
            values[key] = str(values[key] or "")
    return IdentityConfig(**values)


def _apply_env(config: Config, env: Mapping[str, str]) -> Config:
    feilong = config.feilong
    updates: dict[str, Any] = {}
    if "ZVM_EXPORTER_FEILONG_URL" in env:
        updates["url"] = env["ZVM_EXPORTER_FEILONG_URL"]
    if "ZVM_EXPORTER_FEILONG_ADMIN_TOKEN" in env:
        updates["admin_token"] = env["ZVM_EXPORTER_FEILONG_ADMIN_TOKEN"]
    if "ZVM_EXPORTER_FEILONG_AUTH_TOKEN" in env:
        updates["auth_token"] = env["ZVM_EXPORTER_FEILONG_AUTH_TOKEN"]
    if "ZVM_EXPORTER_FEILONG_AUTH" in env:
        updates["auth"] = env["ZVM_EXPORTER_FEILONG_AUTH"].strip().lower()
    if "ZVM_EXPORTER_FEILONG_VERIFY_TLS" in env:
        updates["verify_tls"] = _bool_value(
            env["ZVM_EXPORTER_FEILONG_VERIFY_TLS"], "ZVM_EXPORTER_FEILONG_VERIFY_TLS"
        )
    if "ZVM_EXPORTER_FEILONG_CA_FILE" in env:
        updates["ca_file"] = env["ZVM_EXPORTER_FEILONG_CA_FILE"]
    if "ZVM_EXPORTER_FEILONG_TIMEOUT" in env:
        updates["timeout"] = float(env["ZVM_EXPORTER_FEILONG_TIMEOUT"])
    if "ZVM_EXPORTER_FEILONG_DISK_POOLS" in env:
        updates["disk_pools"] = _pool_tuple(env["ZVM_EXPORTER_FEILONG_DISK_POOLS"])
    if "ZVM_EXPORTER_FEILONG_DISK_POOL_DETAILS" in env:
        updates["disk_pool_details"] = _bool_value(
            env["ZVM_EXPORTER_FEILONG_DISK_POOL_DETAILS"],
            "ZVM_EXPORTER_FEILONG_DISK_POOL_DETAILS",
        )
    for env_name, field_name in (
        ("ZVM_EXPORTER_FEILONG_BATCH_SIZE", "batch_size"),
        ("ZVM_EXPORTER_FEILONG_CONCURRENCY", "concurrency"),
        ("ZVM_EXPORTER_FEILONG_MAX_GUESTS", "max_guests"),
        ("ZVM_EXPORTER_FEILONG_MAX_VSWITCHES", "max_vswitches"),
        ("ZVM_EXPORTER_FEILONG_PER_GUEST_LIMIT", "per_guest_limit"),
    ):
        if env_name in env:
            updates[field_name] = int(env[env_name])
    if "ZVM_EXPORTER_FEILONG_ENABLED" in env:
        updates["enabled"] = _bool_value(
            env["ZVM_EXPORTER_FEILONG_ENABLED"], "ZVM_EXPORTER_FEILONG_ENABLED"
        )
    if updates:
        feilong = replace(feilong, **updates)

    vmcp = config.vmcp
    vmcp_updates: dict[str, Any] = {}
    if "ZVM_EXPORTER_VMCP_ENABLED" in env:
        vmcp_updates["enabled"] = _bool_value(
            env["ZVM_EXPORTER_VMCP_ENABLED"], "ZVM_EXPORTER_VMCP_ENABLED"
        )
    if "ZVM_EXPORTER_VMCP_COMMAND" in env:
        vmcp_updates["command"] = env["ZVM_EXPORTER_VMCP_COMMAND"]
    if "ZVM_EXPORTER_VMCP_INTERVAL" in env:
        vmcp_updates["interval"] = float(env["ZVM_EXPORTER_VMCP_INTERVAL"])
    if "ZVM_EXPORTER_VMCP_TIMEOUT" in env:
        vmcp_updates["timeout"] = float(env["ZVM_EXPORTER_VMCP_TIMEOUT"])
    if "ZVM_EXPORTER_VMCP_HOST_NAME" in env:
        vmcp_updates["host_name"] = env["ZVM_EXPORTER_VMCP_HOST_NAME"]
    if vmcp_updates:
        vmcp = replace(vmcp, **vmcp_updates)

    server = config.server
    server_updates: dict[str, Any] = {}
    if "ZVM_EXPORTER_LISTEN" in env:
        server_updates["listen"] = env["ZVM_EXPORTER_LISTEN"]
    if "ZVM_EXPORTER_PORT" in env:
        server_updates["port"] = int(env["ZVM_EXPORTER_PORT"])
    if server_updates:
        server = replace(server, **server_updates)

    otlp = config.otlp
    otlp_updates: dict[str, Any] = {}
    if "ZVM_EXPORTER_OTLP_ENABLED" in env:
        otlp_updates["enabled"] = _bool_value(
            env["ZVM_EXPORTER_OTLP_ENABLED"], "ZVM_EXPORTER_OTLP_ENABLED"
        )
    if "ZVM_EXPORTER_OTLP_ENDPOINT" in env:
        otlp_updates["endpoint"] = env["ZVM_EXPORTER_OTLP_ENDPOINT"]
    if "ZVM_EXPORTER_OTLP_PROTOCOL" in env:
        otlp_updates["protocol"] = env["ZVM_EXPORTER_OTLP_PROTOCOL"].strip().lower()
    if "ZVM_EXPORTER_OTLP_HEADERS" in env:
        otlp_updates["headers"] = parse_headers(env["ZVM_EXPORTER_OTLP_HEADERS"])
    if "ZVM_EXPORTER_OTLP_INSECURE" in env:
        otlp_updates["insecure"] = _bool_value(
            env["ZVM_EXPORTER_OTLP_INSECURE"], "ZVM_EXPORTER_OTLP_INSECURE"
        )
    if "ZVM_EXPORTER_OTLP_TIMEOUT" in env:
        otlp_updates["timeout"] = float(env["ZVM_EXPORTER_OTLP_TIMEOUT"])
    if otlp_updates:
        otlp = replace(otlp, **otlp_updates)

    collectors = config.collectors
    collector_updates: dict[str, bool] = {}
    for name in _COLLECTORS:
        env_name = "ZVM_EXPORTER_COLLECTOR_" + name.upper()
        if env_name in env:
            collector_updates[name] = _bool_value(env[env_name], env_name)
    if collector_updates:
        collectors = replace(collectors, **collector_updates)

    prometheus = config.prometheus_enabled
    if "ZVM_EXPORTER_PROMETHEUS_ENABLED" in env:
        prometheus = _bool_value(
            env["ZVM_EXPORTER_PROMETHEUS_ENABLED"], "ZVM_EXPORTER_PROMETHEUS_ENABLED"
        )
    scrape = config.scrape_interval
    if "ZVM_EXPORTER_SCRAPE_INTERVAL" in env:
        scrape = float(env["ZVM_EXPORTER_SCRAPE_INTERVAL"])
    log_level = config.log_level
    if "ZVM_EXPORTER_LOG_LEVEL" in env:
        log_level = env["ZVM_EXPORTER_LOG_LEVEL"].upper()
    identity = config.identity
    identity_updates: dict[str, Any] = {}
    env_identity = {
        "ZVM_EXPORTER_IDENTITY_SYSINFO": "sysinfo_path",
        "ZVM_EXPORTER_IDENTITY_INTERVAL": "interval",
        "ZVM_EXPORTER_IDENTITY_HOST_NAME": "host_name",
        "ZVM_EXPORTER_IDENTITY_SYSTEM_NAME": "system_name",
        "ZVM_EXPORTER_IDENTITY_LPAR_NAME": "lpar_name",
        "ZVM_EXPORTER_IDENTITY_LPAR_NUMBER": "lpar_number",
        "ZVM_EXPORTER_IDENTITY_CPC_TYPE": "cpc_type",
        "ZVM_EXPORTER_IDENTITY_CPC_MODEL": "cpc_model",
        "ZVM_EXPORTER_IDENTITY_CPC_SEQUENCE": "cpc_sequence",
        "ZVM_EXPORTER_IDENTITY_CPC_PLANT": "cpc_plant",
        "ZVM_EXPORTER_IDENTITY_SITE": "site",
        "ZVM_EXPORTER_IDENTITY_ENVIRONMENT": "environment",
        "ZVM_EXPORTER_IDENTITY_SSI_NAME": "ssi_name",
        "ZVM_EXPORTER_IDENTITY_ARCH": "arch",
        "ZVM_EXPORTER_IDENTITY_HYPERVISOR": "hypervisor",
        "ZVM_EXPORTER_IDENTITY_EXPORTER_GUEST": "exporter_guest",
        "ZVM_EXPORTER_IDENTITY_VM_LEVEL": "vm_level",
    }
    for env_name, field_name in env_identity.items():
        if env_name in env:
            identity_updates[field_name] = (
                float(env[env_name]) if field_name == "interval" else env[env_name]
            )
    if identity_updates:
        identity = replace(identity, **identity_updates)
    return Config(
        feilong=feilong,
        server=server,
        scrape_interval=scrape,
        prometheus_enabled=prometheus,
        otlp=otlp,
        collectors=collectors,
        vmcp=vmcp,
        identity=identity,
        log_level=log_level,
    )


def _apply_args(config: Config, args: Any) -> Config:
    if args is None:
        return config
    feilong_updates: dict[str, Any] = {}
    if _present(args, "feilong_url"):
        feilong_updates["url"] = args.feilong_url
    if _present(args, "feilong_admin_token"):
        feilong_updates["admin_token"] = args.feilong_admin_token
    if _present(args, "feilong_auth_token"):
        feilong_updates["auth_token"] = args.feilong_auth_token
    if _present(args, "auth"):
        feilong_updates["auth"] = str(args.auth).lower()
    if getattr(args, "verify_tls", None) is not None:
        feilong_updates["verify_tls"] = bool(args.verify_tls)
    if _present(args, "ca_file"):
        feilong_updates["ca_file"] = args.ca_file
    if _present(args, "timeout"):
        feilong_updates["timeout"] = float(args.timeout)
    pools = getattr(args, "disk_pool", None)
    if pools:
        feilong_updates["disk_pools"] = tuple(pools)
    feilong = replace(config.feilong, **feilong_updates) if feilong_updates else config.feilong

    server_updates: dict[str, Any] = {}
    if _present(args, "listen"):
        server_updates["listen"] = args.listen
    if _present(args, "port"):
        server_updates["port"] = int(args.port)
    server = replace(config.server, **server_updates) if server_updates else config.server

    otlp_updates: dict[str, Any] = {}
    if getattr(args, "otlp", None) is not None:
        otlp_updates["enabled"] = bool(args.otlp)
    if _present(args, "otlp_endpoint"):
        otlp_updates["endpoint"] = args.otlp_endpoint
    if _present(args, "otlp_protocol"):
        otlp_updates["protocol"] = str(args.otlp_protocol).lower()
    headers = getattr(args, "otlp_header", None)
    if headers:
        merged: dict[str, str] = {}
        for item in headers:
            merged.update(
                parse_headers(item) if item.strip().startswith("{") else _one_header(item)
            )
        otlp_updates["headers"] = merged
    if getattr(args, "otlp_insecure", None) is not None:
        otlp_updates["insecure"] = bool(args.otlp_insecure)
    if _present(args, "otlp_timeout"):
        otlp_updates["timeout"] = float(args.otlp_timeout)
    otlp = replace(config.otlp, **otlp_updates) if otlp_updates else config.otlp

    prometheus = config.prometheus_enabled
    if getattr(args, "prometheus", None) is not None:
        prometheus = bool(args.prometheus)
    scrape = config.scrape_interval
    if _present(args, "scrape_interval"):
        scrape = float(args.scrape_interval)
    log_level = config.log_level
    if _present(args, "log_level"):
        log_level = str(args.log_level).upper()
    vmcp_updates: dict[str, Any] = {}
    if getattr(args, "vmcp", None) is not None:
        vmcp_updates["enabled"] = bool(args.vmcp)
    if _present(args, "vmcp_command"):
        vmcp_updates["command"] = args.vmcp_command
    if _present(args, "vmcp_interval"):
        vmcp_updates["interval"] = float(args.vmcp_interval)
    if _present(args, "vmcp_timeout"):
        vmcp_updates["timeout"] = float(args.vmcp_timeout)
    if _present(args, "vmcp_host_name"):
        vmcp_updates["host_name"] = args.vmcp_host_name
    vmcp = replace(config.vmcp, **vmcp_updates) if vmcp_updates else config.vmcp
    if _present(args, "per_guest_limit"):
        feilong = replace(feilong, per_guest_limit=int(args.per_guest_limit))
    if getattr(args, "feilong_enabled", None) is not None:
        feilong = replace(feilong, enabled=bool(args.feilong_enabled))
    return Config(
        feilong=feilong,
        server=server,
        scrape_interval=scrape,
        prometheus_enabled=prometheus,
        otlp=otlp,
        collectors=config.collectors,
        vmcp=vmcp,
        identity=config.identity,
        log_level=log_level,
    )


def parse_headers(raw: str) -> dict[str, str]:
    """Parse OTLP headers from a JSON object or comma-separated key=value pairs."""

    text = raw.strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"OTLP headers are not valid JSON: {exc}") from exc
        return _header_map(loaded)
    headers: dict[str, str] = {}
    for part in text.split(","):
        if not part.strip():
            continue
        headers.update(_one_header(part))
    return headers


def _one_header(item: str) -> dict[str, str]:
    if "=" not in item:
        raise ConfigError("OTLP headers must be key=value pairs or a JSON object")
    key, value = item.split("=", 1)
    key = key.strip()
    if not key:
        raise ConfigError("OTLP header name is empty")
    return {key: value.strip()}


def _header_map(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ConfigError("OTLP headers must be a mapping")
    return {str(key): str(item) for key, item in value.items()}


def _pool_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, list):
        return tuple(str(part).strip() for part in value if str(part).strip())
    raise ConfigError("disk pools must be a list or a comma-separated string")


def _bool_value(value: str, name: str) -> bool:
    lowered = value.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ConfigError(f"{name} must be true or false")


def _coerce_feilong(raw: dict[str, Any]) -> dict[str, Any]:
    raw["url"] = str(raw.get("url") or "")
    raw["admin_token"] = str(raw.get("admin_token") or "")
    raw["auth_token"] = str(raw.get("auth_token") or "")
    raw["auth"] = str(raw.get("auth") or "token").lower()
    raw["verify_tls"] = bool(raw.get("verify_tls", True))
    raw["ca_file"] = str(raw.get("ca_file") or "")
    raw["timeout"] = float(raw.get("timeout", 30))
    pools = raw.get("disk_pools") or ()
    raw["disk_pools"] = pools if isinstance(pools, tuple) else _pool_tuple(pools)
    raw["disk_pool_details"] = bool(raw.get("disk_pool_details", True))
    raw["batch_size"] = int(raw.get("batch_size", 25))
    raw["concurrency"] = int(raw.get("concurrency", 8))
    raw["max_guests"] = int(raw.get("max_guests", 500))
    raw["max_vswitches"] = int(raw.get("max_vswitches", 50))
    raw["enabled"] = bool(raw.get("enabled", True))
    raw["per_guest_limit"] = int(raw.get("per_guest_limit", 32))
    return raw


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a mapping")
    return value


def _reject_unknown(raw: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ConfigError(f"unknown {name} setting: {', '.join(unknown)}")


def _arg(args: Any, name: str) -> Any:
    if args is None:
        return None
    value = getattr(args, name, None)
    if value is None or value == "":
        return None
    return value


def _present(args: Any, name: str) -> bool:
    return _arg(args, name) is not None
