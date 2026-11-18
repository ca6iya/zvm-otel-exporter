# Copyright 2026 z/VM OTel Exporter contributors
# SPDX-License-Identifier: Apache-2.0

"""Small Feilong REST client.

Authentication follows Feilong's token flow: POST /token with the long-lived
admin token (the contents of ``/etc/zvmsdk/token.dat``) in ``X-Admin-Token``.
Feilong returns a session token in ``X-Auth-Token``. That session token is sent
on later calls and refreshed once after HTTP 401.

The client never logs headers or response bodies. Error text is passed through
the secret redactor before it is returned to the caller.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from zvm_otel_exporter.redact import redact

if TYPE_CHECKING:
    from zvm_otel_exporter.config import FeilongConfig


class FeilongError(Exception):
    """Base class for Feilong call failures."""


class FeilongUnavailable(FeilongError):
    """The TCP connection, TLS handshake, or timeout failed."""


class FeilongAuthError(FeilongError):
    """Token exchange or a session token was rejected."""


class FeilongNotFound(FeilongError):
    """Feilong returned HTTP 404 for this resource."""


class FeilongAPIError(FeilongError):
    """Feilong returned an error payload or a non-success status."""

    def __init__(self, message: str, *, status: int | None = None, overall_rc: int | None = None):
        super().__init__(message)
        self.status = status
        self.overall_rc = overall_rc


class FeilongClient:
    """HTTP client for the read-only Feilong routes this exporter uses."""

    def __init__(self, config: FeilongConfig, secrets: list[str] | None = None) -> None:
        self._config = config
        self.secrets = list(secrets or [])
        for token in (config.admin_token, config.auth_token):
            if token and token not in self.secrets:
                self.secrets.append(token)
        if config.verify_tls:
            verify: bool | str = config.ca_file or True
        else:
            verify = False
        self._http = httpx.Client(
            timeout=httpx.Timeout(config.timeout),
            verify=verify,
            trust_env=False,
            headers={
                "Accept": "application/json",
                "User-Agent": "zvm-otel-exporter",
            },
        )
        self._session_token = config.auth_token or ""

    def close(self) -> None:
        self._http.close()

    def __repr__(self) -> str:
        return f"FeilongClient(url={self._config.url!r}, auth={self._config.auth}, tokens=redacted)"

    def get_output(self, path: str, query: dict[str, str] | None = None) -> object:
        response = self._request("GET", path, query=query)
        if response.status_code == 404:
            raise FeilongNotFound(f"{path} was not found")
        payload = self._json(response, path)
        if response.status_code >= 400:
            raise FeilongAPIError(
                self._error_message(payload, response.status_code, path),
                status=response.status_code,
            )
        return unwrap(payload, self.secrets)

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        auth_retry: bool = True,
    ) -> httpx.Response:
        headers: dict[str, str] = {}
        if path != "/token" and self._config.auth == "token":
            headers["X-Auth-Token"] = self._ensure_token(force=not auth_retry)
        try:
            response = self._http.request(
                method,
                self._url(path),
                params=query,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise FeilongUnavailable(f"Feilong timed out calling {path}") from exc
        except httpx.TransportError as exc:
            raise FeilongUnavailable(f"Feilong unreachable calling {path}") from exc
        if (
            response.status_code == 401
            and path != "/token"
            and auth_retry
            and self._config.admin_token
        ):
            self._session_token = ""
            return self._request(method, path, query=query, auth_retry=False)
        if response.status_code == 401:
            raise self._auth_error(response, f"{path} rejected authentication (HTTP 401)")
        return response

    def _auth_error(self, response: httpx.Response, fallback: str) -> FeilongAuthError:
        message = fallback
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict) and payload.get("errmsg"):
            message = str(payload["errmsg"])
        return FeilongAuthError(redact(message, self.secrets))

    def _ensure_token(self, *, force: bool) -> str:
        if self._session_token and not force:
            return self._session_token
        if not self._config.admin_token:
            if self._session_token:
                return self._session_token
            raise FeilongAuthError(
                "token auth is enabled but no admin token or session token is set"
            )
        try:
            response = self._http.request(
                "POST",
                self._url("/token"),
                headers={"X-Admin-Token": self._config.admin_token},
            )
        except httpx.TimeoutException as exc:
            raise FeilongUnavailable("Feilong timed out calling /token") from exc
        except httpx.TransportError as exc:
            raise FeilongUnavailable("Feilong unreachable calling /token") from exc
        if response.status_code == 401:
            raise self._auth_error(response, "/token rejected the admin token (HTTP 401)")
        if response.status_code >= 400:
            raise self._auth_error(response, f"/token failed (HTTP {response.status_code})")
        token = response.headers.get("X-Auth-Token", "").strip()
        if not token:
            raise FeilongAuthError("/token did not return an X-Auth-Token header")
        if token not in self.secrets:
            self.secrets.append(token)
        self._session_token = token
        return token

    def _url(self, path: str) -> str:
        return self._config.url.rstrip("/") + "/" + path.lstrip("/")

    def _json(self, response: httpx.Response, path: str) -> dict[str, object]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise FeilongAPIError(
                f"{path} returned a non-JSON response (HTTP {response.status_code})"
            ) from exc
        if not isinstance(payload, dict):
            raise FeilongAPIError(f"{path} returned a JSON value that is not an object")
        return payload

    def _error_message(self, payload: dict[str, object], status: int, path: str) -> str:
        message = payload.get("errmsg")
        text = str(message).strip() if message else f"{path} failed (HTTP {status})"
        return redact(text, self.secrets)


def unwrap(payload: dict[str, object], secrets: list[str] | None = None) -> object:
    """Return the Feilong ``output`` field or raise when overallRC is set."""

    rc = payload.get("overallRC", 0)
    if rc is None:
        rc = 0
    if isinstance(rc, bool) or not isinstance(rc, (int, float)) or int(rc) != 0:
        message = payload.get("errmsg") or f"Feilong overallRC={rc}"
        text = redact(str(message), secrets or [])
        overall = int(rc) if isinstance(rc, (int, float)) and not isinstance(rc, bool) else None
        raise FeilongAPIError(text, overall_rc=overall)
    return payload.get("output")
