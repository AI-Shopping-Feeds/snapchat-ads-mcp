"""OAuth token refresh, caching, rotation, code exchange and redaction."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import httpx
import pytest
import respx

from snapchat_ads_mcp import auth
from snapchat_ads_mcp.auth import SnapAuth, SnapAuthError, authorization_url, redact
from snapchat_ads_mcp.config import AUTHORIZE_URL, SCOPE, TOKEN_URL


def _auth(tmp_path: Path, refresh: str = "refresh-token-one") -> SnapAuth:
    return SnapAuth(
        client_id="client-id-123456",
        client_secret="client-secret-value",
        refresh_token=refresh,
        token_file=tmp_path / "secrets" / "token.json",
    )


@respx.mock
def test_refresh_is_cached_until_expiry(tmp_path: Path) -> None:
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "0.access-one", "expires_in": 3600})
    )
    a = _auth(tmp_path)
    assert a.access_token() == "0.access-one"
    assert a.access_token() == "0.access-one"
    assert route.call_count == 1
    sent = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert sent["grant_type"] == "refresh_token"
    assert sent["refresh_token"] == "refresh-token-one"
    assert sent["client_id"] == "client-id-123456"
    a.invalidate()
    a.access_token()
    assert route.call_count == 2


@respx.mock
def test_short_lived_token_is_refreshed(tmp_path: Path) -> None:
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "0.short", "expires_in": 30})
    )
    a = _auth(tmp_path)
    a.access_token()
    a.access_token()  # inside the expiry margin, so it refreshes again
    assert route.call_count == 2


@respx.mock
def test_rotated_refresh_token_is_saved(tmp_path: Path) -> None:
    a = _auth(tmp_path)
    auth.save_token_file(a.token_file, {"refresh_token": "refresh-token-one"})
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "0.a", "expires_in": 3600, "refresh_token": "refresh-token-two"},
        )
    )
    a.access_token()
    saved = json.loads(a.token_file.read_text())
    assert saved["refresh_token"] == "refresh-token-two"


@respx.mock
def test_refresh_failure_is_redacted(tmp_path: Path) -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            400, json={"error": "invalid_grant", "refresh_token": "refresh-token-one"}
        )
    )
    a = _auth(tmp_path)
    with pytest.raises(SnapAuthError) as exc_info:
        a.access_token()
    message = str(exc_info.value)
    assert "invalid_grant" in message
    assert "refresh-token-one" not in message
    assert "client-secret-value" not in message
    assert "snapchat-ads-mcp auth" in message


@respx.mock
def test_exchange_code(tmp_path: Path) -> None:
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "0.x", "refresh_token": "new-refresh-token", "expires_in": 3600},
        )
    )
    out = auth.exchange_code(
        code="one-time-code",
        redirect_uri="http://localhost:8765/callback",
        client_id="cid",
        client_secret="client-secret-value",
    )
    assert out["refresh_token"] == "new-refresh-token"
    sent = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert sent["grant_type"] == "authorization_code"
    assert sent["redirect_uri"] == "http://localhost:8765/callback"
    assert redact("token new-refresh-token here") == "token *** here"


@respx.mock
def test_exchange_code_failure() -> None:
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(SnapAuthError, match="single-use"):
        auth.exchange_code(
            code="c", redirect_uri="http://localhost/cb", client_id="i", client_secret="s"
        )


def test_authorization_url() -> None:
    url = authorization_url(
        client_id="cid", redirect_uri="http://localhost:8765/callback", state="st"
    )
    assert url.startswith(AUTHORIZE_URL + "?")
    q = dict(httpx.URL(url).params)
    assert q == {
        "client_id": "cid",
        "redirect_uri": "http://localhost:8765/callback",
        "response_type": "code",
        "scope": SCOPE,
        "state": "st",
    }


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_token_file_is_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "secrets" / "token.json"
    auth.save_token_file(path, {"refresh_token": "abc"})
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
    auth.save_token_file(path, {"other": 1})
    assert json.loads(path.read_text()) == {"refresh_token": "abc", "other": 1}


def test_redact_keys_bearer_and_registered_secrets() -> None:
    auth.register_secret("super-secret-value-123")
    data = {
        "Authorization": "Bearer abc.def",
        "nested": {"refresh_token": "x", "note": "has super-secret-value-123 inside"},
        "list": ["Bearer zzz", 5],
        "client_secret": "",
    }
    out = redact(data)
    assert out["Authorization"] == "***"
    assert out["nested"]["refresh_token"] == "***"
    assert out["nested"]["note"] == "has *** inside"
    assert out["list"] == ["Bearer ***", 5]
    assert out["client_secret"] == ""
