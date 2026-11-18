"""Configuration layering."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from zvm_otel_exporter.config import ConfigError, load_config, parse_headers


def _args(**kwargs: object) -> Namespace:
    return Namespace(**kwargs)


def test_env_overrides_file(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "feilong:\n  url: https://file.example:8080\n  admin_token: file-token-value\n",
        encoding="utf-8",
    )
    config = load_config(
        _args(config=str(path)),
        environ={
            "ZVM_EXPORTER_FEILONG_URL": "https://env.example:8080",
            "ZVM_EXPORTER_FEILONG_VERIFY_TLS": "false",
            "ZVM_EXPORTER_PORT": "9111",
            "ZVM_EXPORTER_OTLP_ENABLED": "true",
            "ZVM_EXPORTER_OTLP_ENDPOINT": "http://collector:4317",
            "ZVM_EXPORTER_OTLP_HEADERS": '{"Authorization":"Api-Token dt0c01.REPLACE_ME"}',
            "ZVM_EXPORTER_COLLECTOR_PCIF": "true",
        },
    )
    assert config.feilong.url == "https://env.example:8080"
    assert config.feilong.admin_token == "file-token-value"
    assert config.feilong.verify_tls is False
    assert config.server.port == 9111
    assert config.otlp.enabled is True
    assert config.otlp.endpoint == "http://collector:4317"
    assert config.otlp.headers["Authorization"] == "Api-Token dt0c01.REPLACE_ME"
    assert config.collectors.pcif is True


def test_cli_overrides_env(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "feilong:\n  url: https://file.example\n  admin_token: file-token-value\n",
        encoding="utf-8",
    )
    config = load_config(
        _args(
            config=str(path),
            feilong_url="https://cli.example",
            feilong_admin_token="cli-token-value",
            port=9120,
            otlp=True,
            otlp_endpoint="http://127.0.0.1:4318",
            otlp_protocol="http",
            otlp_header=["Authorization=Api-Token dt0c01.CLI"],
            prometheus=False,
            disk_pool=["ECKD:poola", "FBA:poolb"],
            verify_tls=False,
        ),
        environ={"ZVM_EXPORTER_FEILONG_URL": "https://env.example"},
    )
    assert config.feilong.url == "https://cli.example"
    assert config.feilong.admin_token == "cli-token-value"
    assert config.server.port == 9120
    assert config.prometheus_enabled is False
    assert config.otlp.enabled is True
    assert config.otlp.protocol == "http"
    assert config.otlp.headers == {"Authorization": "Api-Token dt0c01.CLI"}
    assert config.feilong.disk_pools == ("ECKD:poola", "FBA:poolb")
    assert "cli-token-value" not in repr(config)
    assert "dt0c01.CLI" not in repr(config)


def test_rejects_missing_token_and_unknown_key(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="admin_token"):
        load_config(
            _args(feilong_url="https://feilong.example"),
            environ={},
        )
    path = tmp_path / "bad.yaml"
    path.write_text(
        "feilong:\n  url: https://feilong.example\n  password: secret\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="unknown"):
        load_config(_args(config=str(path)), environ={})


def test_rejects_credentials_in_url() -> None:
    with pytest.raises(ConfigError, match="credentials"):
        load_config(
            _args(
                feilong_url="https://user:secret@feilong.example",
                feilong_admin_token="admin-token-value",
            ),
            environ={},
        )


def test_parse_headers_forms() -> None:
    assert parse_headers("A=1,B=2") == {"A": "1", "B": "2"}
    assert parse_headers('{"Authorization":"Api-Token abc"}') == {"Authorization": "Api-Token abc"}


def test_vmcp_only_does_not_require_feilong_and_interval_has_a_floor() -> None:
    config = load_config(
        _args(vmcp=True, feilong_enabled=False, prometheus=True),
        environ={},
    )
    assert config.vmcp.enabled is True
    assert config.feilong.enabled is False
    with pytest.raises(ConfigError, match="30 seconds"):
        load_config(
            _args(
                feilong_url="https://feilong.example",
                feilong_admin_token="admin-token-value",
                vmcp=True,
                vmcp_interval=10,
            ),
            environ={},
        )


def test_example_config_loads() -> None:
    config = load_config(_args(config="examples/config.yaml"), environ={})
    assert config.feilong.url.startswith("https://")
    assert config.server.port == 9110
    assert config.prometheus_enabled is True
    assert config.otlp.enabled is False
    assert config.feilong.disk_pools == ("ECKD:eckdpool1",)
