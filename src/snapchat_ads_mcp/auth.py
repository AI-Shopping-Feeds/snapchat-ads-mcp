"""Snap OAuth 2.0 tokens for the Snap Marketing API.

`SnapAuth` swaps the long-lived refresh token for one-hour access tokens and
caches each one until shortly before it expires. The refresh token comes from
`snapchat-ads-mcp auth` (stored in a 0600 file) or SNAPCHAT_ADS_REFRESH_TOKEN.

Secrets are never logged: pass anything that might contain one through `redact()`.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx

from .config import AUTHORIZE_URL, SCOPE, TOKEN_URL, Config, ensure_private_dir

# Refresh this many seconds before the access token's stated expiry.
EXPIRY_MARGIN = 120

_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=\-]+")
_SECRET_KEYS = {
    "access_token",
    "refresh_token",
    "client_secret",
    "authorization",
    "password",
    "id_token",
}
_extra_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    """Remember a secret value (client secret, tokens) so redact() hides it."""
    if value and len(value) >= 8:
        _extra_secrets.add(value)


def redact(value: Any) -> Any:
    """Return a copy of value with bearer tokens and known secrets replaced by '***'."""
    if isinstance(value, str):
        out = _BEARER_RE.sub("Bearer ***", value)
        for secret in _extra_secrets:
            if secret in out:
                out = out.replace(secret, "***")
        return out
    if isinstance(value, dict):
        return {
            k: ("***" if str(k).lower() in _SECRET_KEYS and v else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    return value


class Auth(Protocol):
    @property
    def account_label(self) -> str: ...

    def access_token(self) -> str: ...

    def invalidate(self) -> None: ...


class SnapAuthError(RuntimeError):
    """Snap's token endpoint refused the refresh (bad client, revoked access)."""


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return {"_raw": resp.text[:500]}


class SnapAuth:
    """Thread-safe refresh-token holder that caches access tokens until expiry."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        token_url: str = TOKEN_URL,
        token_file: Path | None = None,
        timeout: float = 30.0,
    ):
        self.client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self.token_url = token_url
        self.token_file = token_file
        self._timeout = timeout
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at = 0.0
        register_secret(client_secret)
        register_secret(refresh_token)

    @property
    def account_label(self) -> str:
        return f"oauth:{self.client_id[-6:]}"

    @property
    def expires_in(self) -> int:
        return max(0, int(self._expires_at - time.time()))

    def invalidate(self) -> None:
        with self._lock:
            self._token = None
            self._expires_at = 0.0

    def access_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._expires_at - EXPIRY_MARGIN:
                return self._token
            data = {
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": self.client_id,
                "client_secret": self._client_secret,
            }
            try:
                resp = httpx.post(self.token_url, data=data, timeout=self._timeout)
            except httpx.HTTPError as e:
                raise SnapAuthError(f"Could not reach Snap's token endpoint: {e}") from e
            payload = _safe_json(resp)
            if resp.status_code != 200:
                raise SnapAuthError(
                    f"Snap refused the token refresh (HTTP {resp.status_code}): "
                    f"{redact(payload)}. If the Snapchat user lost access or removed the app, "
                    "run `snapchat-ads-mcp auth` again."
                )
            token = payload.get("access_token") if isinstance(payload, dict) else None
            if not token:
                raise SnapAuthError("Snap returned no access token.")
            register_secret(token)
            self._token = token
            self._expires_at = time.time() + float(payload.get("expires_in", 3600))
            new_refresh = payload.get("refresh_token")
            if new_refresh and new_refresh != self._refresh_token:
                register_secret(new_refresh)
                self._refresh_token = new_refresh
                if self.token_file is not None and self.token_file.exists():
                    save_token_file(self.token_file, {"refresh_token": new_refresh})
            return token


def save_token_file(path: Path, data: dict[str, Any]) -> None:
    """Write (or merge into) the token file: owner-only folder (0700) and file (0600)."""
    ensure_private_dir(path.parent)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            existing = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            existing = {}
    existing.update(data)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)
    with contextlib.suppress(OSError):  # e.g. some Windows or network filesystems
        os.chmod(path, 0o600)


def authorization_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    """The consent page link for the authorization-code flow."""
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def exchange_code(
    *,
    code: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str,
    token_url: str = TOKEN_URL,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Swap a one-time authorization code for access and refresh tokens."""
    try:
        resp = httpx.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=timeout,
        )
    except httpx.HTTPError as e:
        raise SnapAuthError(f"Could not reach Snap's token endpoint: {e}") from e
    payload = _safe_json(resp)
    if resp.status_code != 200 or not isinstance(payload, dict) or "refresh_token" not in payload:
        raise SnapAuthError(
            f"Snap refused the authorization code (HTTP {resp.status_code}): "
            f"{redact(payload)}. Codes are single-use and expire quickly; run the command again."
        )
    register_secret(payload.get("access_token"))
    register_secret(payload.get("refresh_token"))
    return payload


def load_auth(config: Config) -> SnapAuth:
    if not config.refresh_token:
        raise RuntimeError("No refresh token configured. Run `snapchat-ads-mcp auth` first.")
    return SnapAuth(
        client_id=config.client_id,
        client_secret=config.client_secret,
        refresh_token=config.refresh_token,
        token_file=config.token_file,
        timeout=config.timeout,
    )
