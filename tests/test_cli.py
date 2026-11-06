"""CLI: HTTP bind refusal, OAuth redirect parsing, purge, describe and version."""

from __future__ import annotations

import json
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from snapchat_ads_mcp import __version__, cli
from snapchat_ads_mcp.auth import save_token_file
from snapchat_ads_mcp.config import Config


def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SNAPCHAT_ADS_CLIENT_ID", "client-id-123456")
    monkeypatch.setenv("SNAPCHAT_ADS_CLIENT_SECRET", "client-secret-value-xyz")
    monkeypatch.setenv("SNAPCHAT_ADS_REFRESH_TOKEN", "refresh-token-value-xyz")


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "[::1]", "127.0.0.2"])
def test_loopback_hosts(host: str) -> None:
    assert cli.is_loopback(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "example.com", "::"])
def test_non_loopback_hosts(host: str) -> None:
    assert not cli.is_loopback(host)


def test_check_bind_refuses_remote(config: Config) -> None:
    config.transport = "streamable-http"
    config.host = "0.0.0.0"
    with pytest.raises(click.ClickException, match="SNAPCHAT_ADS_ALLOW_REMOTE"):
        cli.check_bind(config)
    config.allow_remote = True
    cli.check_bind(config)  # allowed, with a warning
    config.allow_remote = False
    config.transport = "stdio"
    cli.check_bind(config)  # stdio never binds


def test_run_refuses_remote_http(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch)
    built: list[object] = []
    monkeypatch.setattr(cli, "build_server", lambda config: built.append(config))
    result = CliRunner().invoke(
        cli.cli, ["--transport", "streamable-http", "--host", "0.0.0.0", "run"], obj={}
    )
    assert result.exit_code != 0
    assert "Refusing to serve" in result.output
    assert not built


def test_run_env_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch)
    monkeypatch.setenv("SNAPCHAT_ADS_ALLOW_REMOTE", "true")

    class Fake:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        def run(self, *args, **kwargs):
            self.calls.append((args, kwargs))

    fake = Fake()
    monkeypatch.setattr(cli, "build_server", lambda config: fake)
    result = CliRunner().invoke(
        cli.cli,
        ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "9001", "run"],
        obj={},
    )
    assert result.exit_code == 0, result.output
    assert fake.calls == [(("streamable-http",), {"host": "0.0.0.0", "port": 9001})]


def test_parse_redirect_requires_matching_state() -> None:
    url = "https://example.com/cb?code=abc123&state=good"
    assert cli.parse_redirect(url, "good") == "abc123"
    with pytest.raises(click.ClickException, match="doesn't match"):
        cli.parse_redirect(url, "other")
    with pytest.raises(click.ClickException, match="no state"):
        cli.parse_redirect("https://example.com/cb?code=abc123", "good")
    with pytest.raises(click.ClickException, match="full address"):
        cli.parse_redirect("abc123", "good")
    with pytest.raises(click.ClickException, match="access_denied"):
        cli.parse_redirect("https://example.com/cb?error=access_denied&state=good", "good")
    with pytest.raises(click.ClickException, match="Nothing pasted"):
        cli.parse_redirect("  ", "good")


def test_auth_manual_needs_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch)
    result = CliRunner().invoke(cli.cli, ["auth", "--manual", "--no-browser"], obj={})
    assert result.exit_code != 0
    assert "--redirect-uri" in result.output


def test_auth_refuses_non_local_redirect_without_manual(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch)
    result = CliRunner().invoke(
        cli.cli, ["auth", "--redirect-uri", "https://example.com/cb", "--no-browser"], obj={}
    )
    assert result.exit_code != 0
    assert "--manual" in result.output


def test_auth_manual_flow(monkeypatch: pytest.MonkeyPatch, _isolated_env: Path) -> None:
    _env(monkeypatch)
    monkeypatch.delenv("SNAPCHAT_ADS_REFRESH_TOKEN")
    monkeypatch.setattr(cli.secrets, "token_urlsafe", lambda n: "fixed-state")
    seen: dict[str, str] = {}

    def fake_exchange(**kwargs):
        seen.update(kwargs)
        return {"refresh_token": "brand-new-refresh-token", "scope": "snapchat-marketing-api"}

    monkeypatch.setattr(cli, "exchange_code", fake_exchange)
    result = CliRunner().invoke(
        cli.cli,
        ["auth", "--manual", "--no-browser", "--redirect-uri", "https://example.com/cb"],
        input="https://example.com/cb?code=the-code&state=fixed-state\n",
        obj={},
    )
    assert result.exit_code == 0, result.output
    assert seen["code"] == "the-code"
    assert seen["redirect_uri"] == "https://example.com/cb"
    token_file = _isolated_env / "secrets" / "snapchat-ads-token.json"
    assert json.loads(token_file.read_text())["refresh_token"] == "brand-new-refresh-token"
    assert "brand-new-refresh-token" not in result.output


def test_purge(monkeypatch: pytest.MonkeyPatch, _isolated_env: Path) -> None:
    token = _isolated_env / "secrets" / "snapchat-ads-token.json"
    save_token_file(token, {"refresh_token": "x"})
    audit = _isolated_env / "logs" / "audit.jsonl"
    audit.parent.mkdir(parents=True)
    audit.write_text("{}\n")
    result = CliRunner().invoke(cli.cli, ["purge", "--keep-token", "--yes"], obj={})
    assert result.exit_code == 0
    assert not audit.exists() and token.exists()
    result = CliRunner().invoke(cli.cli, ["purge", "--yes"], obj={})
    assert not token.exists()
    assert "accounts.snapchat.com" in result.output
    result = CliRunner().invoke(cli.cli, ["purge", "--yes"], obj={})
    assert "Nothing to delete" in result.output


def test_describe_has_no_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch)
    result = CliRunner().invoke(cli.cli, ["describe"], obj={})
    assert result.exit_code == 0, result.output
    info = json.loads(result.output)
    assert info["refresh_token"] == "set"
    assert info["client_id"] == "...123456"
    assert "client-secret-value-xyz" not in result.output
    assert "refresh-token-value-xyz" not in result.output


def test_version() -> None:
    result = CliRunner().invoke(cli.cli, ["version"], obj={})
    assert result.output.strip() == __version__


def test_main_reports_config_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["snapchat-ads-mcp", "describe"])
    with pytest.raises(SystemExit) as exc_info:
        cli.main()
    assert exc_info.value.code == 2
    assert "SNAPCHAT_ADS_CLIENT_ID" in capsys.readouterr().err
