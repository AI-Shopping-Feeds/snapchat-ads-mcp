"""CLI entrypoint exposed as the `snapchat-ads-mcp` console script.

Subcommands:

* `snapchat-ads-mcp run`       (default) start the MCP server.
* `snapchat-ads-mcp auth`      one-time Snap OAuth consent; saves the refresh token.
* `snapchat-ads-mcp purge`     delete the audit log and the stored refresh token.
* `snapchat-ads-mcp describe`  print the effective configuration (no secrets).
* `snapchat-ads-mcp version`   print the package version.
"""

from __future__ import annotations

import ipaddress
import json
import os
import secrets
import sys
import threading
import time
import webbrowser
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import click

from . import __version__
from ._logging import configure_default, get_logger
from .auth import authorization_url, exchange_code, redact, register_secret, save_token_file
from .config import (
    LOOPBACK_HOSTS,
    TRANSPORTS,
    Config,
    audit_log_path,
    home_dir,
    load_config,
    load_env_files,
    token_file_path,
)
from .server import build_server

logger = get_logger("cli")


def is_loopback(host: str) -> bool:
    host = host.strip().strip("[]")
    if host in LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_bind(config: Config) -> None:
    """Refuse to serve HTTP on a non-loopback address unless remote access is opted into."""
    if config.transport == "stdio" or is_loopback(config.host):
        return
    if not config.allow_remote:
        raise click.ClickException(
            f"Refusing to serve {config.transport} on {config.host}: the HTTP transports have "
            "no sign-in, so anyone who can reach that address could use your Snapchat Ads "
            "account. Bind to 127.0.0.1, or set SNAPCHAT_ADS_ALLOW_REMOTE=true (or pass "
            "--allow-remote) if you have put your own authentication in front of it."
        )
    logger.warning(
        "binding to %s with remote access allowed: the server has no authentication, so "
        "anyone who can reach this address can use your Snapchat Ads credentials",
        config.host,
    )


@click.group(invoke_without_command=True)
@click.option(
    "--env",
    "env_file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to a .env file. Defaults to ./.env, then ~/.snapchat-ads-mcp/.env.",
)
@click.option(
    "--transport",
    type=click.Choice(TRANSPORTS),
    default=None,
    help="Override SNAPCHAT_ADS_TRANSPORT. 'sse' is deprecated; use 'streamable-http'.",
)
@click.option("--host", default=None, help="Bind host for HTTP transports (default 127.0.0.1).")
@click.option(
    "--port", type=int, default=None, help="Bind port for HTTP transports (default 8000)."
)
@click.option(
    "--allow-remote",
    is_flag=True,
    help="Allow binding HTTP transports to a non-loopback address (same as "
    "SNAPCHAT_ADS_ALLOW_REMOTE=true). The server has no sign-in of its own.",
)
@click.pass_context
def cli(
    ctx: click.Context,
    env_file: Path | None,
    transport: str | None,
    host: str | None,
    port: int | None,
    allow_remote: bool,
) -> None:
    """Snapchat Ads MCP server (Snap Marketing API v1)."""
    ctx.ensure_object(dict)
    ctx.obj.update(
        env_file=env_file, transport=transport, host=host, port=port, allow_remote=allow_remote
    )
    if ctx.invoked_subcommand is None:
        ctx.invoke(run)


@cli.command()
@click.pass_context
def run(ctx: click.Context) -> None:
    """Start the MCP server (default subcommand)."""
    configure_default()
    config = load_config(env_file=ctx.obj.get("env_file"))
    if ctx.obj.get("transport"):
        config.transport = ctx.obj["transport"]
    if ctx.obj.get("host"):
        config.host = ctx.obj["host"]
    if ctx.obj.get("port"):
        config.port = ctx.obj["port"]
    if ctx.obj.get("allow_remote"):
        config.allow_remote = True
    check_bind(config)

    mcp = build_server(config=config)
    if config.transport == "stdio":
        mcp.run("stdio")
    elif config.transport == "streamable-http":
        logger.info("serving streamable HTTP on http://%s:%d/mcp", config.host, config.port)
        mcp.run("streamable-http", host=config.host, port=config.port)
    elif config.transport == "sse":
        logger.warning(
            "the sse transport (HTTP+SSE) is deprecated by the MCP spec; "
            "use --transport streamable-http instead"
        )
        mcp.run("sse", host=config.host, port=config.port)
    else:  # pragma: no cover - load_config validates the transport
        raise click.ClickException(f"Unknown transport: {config.transport}")


def parse_redirect(value: str, expected_state: str) -> str:
    """Pull the authorization code out of the pasted redirect URL.

    The full redirected address is required, and its `state` must match the one
    this run generated, so a code from someone else's consent can't be slipped in.
    """
    value = value.strip()
    if not value:
        raise click.ClickException("Nothing pasted.")
    if "code=" not in value and "error=" not in value:
        raise click.ClickException(
            "Paste the full address you were redirected to (it contains code= and state=), "
            "not just the code."
        )
    query = parse_qs(urlparse(value).query or value.split("?", 1)[-1])
    if "error" in query:
        raise click.ClickException(f"Snap returned an error: {query['error'][0]}")
    state = query.get("state", [None])[0]
    if state is None:
        raise click.ClickException("The pasted address has no state; start again.")
    if not secrets.compare_digest(state, expected_state):
        raise click.ClickException("The state in the redirect doesn't match; start again.")
    code = query.get("code", [""])[0]
    if not code:
        raise click.ClickException("No code in the redirect address.")
    return code


def _wait_for_code(port: int, path: str, expected_state: str, timeout: float) -> str:
    result: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path != path:
                self.send_response(404)
                self.end_headers()
                return
            state = query.get("state", [""])[0]
            if not secrets.compare_digest(state, expected_state):
                result["error"] = "state mismatch"
            elif "error" in query:
                result["error"] = query["error"][0]
            elif query.get("code"):
                result["code"] = query["code"][0]
            else:
                result["error"] = "no code in the redirect"
            ok = "code" in result
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            message = (
                "Authorised. You can close this window and return to the terminal."
                if ok
                else "Authorisation failed. Return to the terminal for details."
            )
            self.wfile.write(f"<html><body><p>{message}</p></body></html>".encode())

        def log_message(self, *args: Any, **kwargs: Any) -> None:  # never log the code
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 1
    deadline = time.monotonic() + timeout
    try:
        while not result and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if "code" in result:
        return result["code"]
    if "error" in result:
        raise click.ClickException(f"Authorisation failed: {result['error']}")
    raise click.ClickException("Timed out waiting for the browser redirect.")


@cli.command()
@click.option("--port", type=int, default=8765, help="Local callback port (default 8765).")
@click.option(
    "--manual",
    is_flag=True,
    help="Don't start a local server: paste the address you were redirected to instead.",
)
@click.option(
    "--redirect-uri",
    default=None,
    help="Redirect URI registered on your Snap OAuth app. Default "
    "SNAPCHAT_ADS_REDIRECT_URI, else http://localhost:PORT/callback (not with --manual).",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Where to save the refresh token (default SNAPCHAT_ADS_TOKEN_FILE or "
    "~/.snapchat-ads-mcp/secrets/snapchat-ads-token.json).",
)
@click.option("--no-browser", is_flag=True, help="Print the consent link instead of opening it.")
@click.option("--timeout", type=float, default=300, help="Seconds to wait for the redirect.")
@click.pass_context
def auth(
    ctx: click.Context,
    port: int,
    manual: bool,
    redirect_uri: str | None,
    output_path: Path | None,
    no_browser: bool,
    timeout: float,
) -> None:
    """One-time Snap OAuth consent: get a refresh token for this server.

    Sign in with the Snapchat business login that can see the ad accounts. The
    redirect URI must be one of the "Snap redirect URIs" on your OAuth app
    (Business Manager -> Business Details -> OAuth apps).
    """
    configure_default()
    config = load_config(env_file=ctx.obj.get("env_file"), require_refresh_token=False)
    register_secret(config.client_secret)
    redirect = redirect_uri or os.environ.get("SNAPCHAT_ADS_REDIRECT_URI", "").strip() or None
    if redirect is None:
        if manual:
            raise click.ClickException(
                "--manual needs the redirect URI registered on your OAuth app: pass "
                "--redirect-uri https://... or set SNAPCHAT_ADS_REDIRECT_URI."
            )
        redirect = f"http://localhost:{port}/callback"
    parsed = urlparse(redirect)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise click.ClickException(f"Redirect URI must be an http(s) address, got {redirect!r}.")
    local = parsed.scheme == "http" and is_loopback(parsed.hostname or "")
    if not manual and not local:
        raise click.ClickException(
            f"{redirect} isn't a local address, so this command can't receive the redirect. "
            "Use --manual and paste the address you land on."
        )
    state = secrets.token_urlsafe(24)
    url = authorization_url(client_id=config.client_id, redirect_uri=redirect, state=state)
    click.echo(f"Redirect URI (must be listed on your Snap OAuth app): {redirect}")
    click.echo("Open this link, sign in with the Snapchat business login, and approve access:")
    click.echo(url)

    if manual:
        if not no_browser:
            webbrowser.open(url)
        pasted = click.prompt("Paste the full address you were redirected to", hide_input=True)
        code = parse_redirect(pasted, state)
    else:
        if not no_browser:
            threading.Timer(0.5, webbrowser.open, args=(url,)).start()
        click.echo(f"Waiting for the redirect on {redirect} ...")
        code = _wait_for_code(parsed.port or port, parsed.path or "/callback", state, timeout)

    tokens = exchange_code(
        code=code,
        redirect_uri=redirect,
        client_id=config.client_id,
        client_secret=config.client_secret,
    )
    refresh = tokens["refresh_token"]
    target = output_path or config.token_file or token_file_path()
    save_token_file(
        target,
        {
            "refresh_token": refresh,
            "client_id_suffix": config.client_id[-6:],
            "scope": tokens.get("scope"),
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
    )
    click.echo(f"Saved the refresh token to {target} (owner-only permissions).")
    if target.resolve() != token_file_path().resolve():
        click.echo(f"Set SNAPCHAT_ADS_TOKEN_FILE={target.resolve()} so the server finds it.")
    click.echo(
        "Next: run `snapchat-ads-mcp describe`, then add the server to your MCP client. "
        "Never paste the token file into chat or commit it."
    )


@cli.command()
@click.option("--yes", is_flag=True, help="Don't ask for confirmation.")
@click.option("--keep-token", is_flag=True, help="Delete only the audit log.")
@click.pass_context
def purge(ctx: click.Context, yes: bool, keep_token: bool) -> None:
    """Delete locally stored Snapchat Ads data: the audit log and the refresh-token file."""
    load_env_files(ctx.obj.get("env_file"))
    audit = audit_log_path()
    targets = [audit, audit.with_suffix(audit.suffix + ".tmp")]
    if not keep_token:
        targets.append(token_file_path())
    existing = [p for p in targets if p.exists()]
    if not existing:
        click.echo("Nothing to delete.")
        return
    click.echo("Will delete:\n" + "\n".join(f"  {p}" for p in existing))
    if not yes and not click.confirm("Delete these files?", default=False):
        click.echo("Cancelled.")
        return
    for p in existing:
        p.unlink()
    click.echo(f"Deleted {len(existing)} file(s).")
    if not keep_token:
        click.echo(
            "If you also set SNAPCHAT_ADS_REFRESH_TOKEN in a client config, remove it there. "
            "To revoke the app's access, remove it at https://accounts.snapchat.com "
            "(Manage apps) while signed in as the user who approved it."
        )


@cli.command()
def version() -> None:
    """Print the snapchat-ads-mcp version."""
    click.echo(__version__)


@cli.command("describe")
@click.pass_context
def describe(ctx: click.Context) -> None:
    """Print the effective configuration (paths, defaults, limits) and exit. No secrets."""
    configure_default()
    config = load_config(env_file=ctx.obj.get("env_file"), require_refresh_token=False)
    info = {
        "version": __version__,
        "api_host": config.api_host,
        "client_id": f"...{config.client_id[-6:]}",
        "refresh_token": "set" if config.refresh_token else "missing (run `snapchat-ads-mcp auth`)",
        "home": str(home_dir()),
        "token_file": str(config.token_file) if config.token_file else None,
        "default_ad_account_id": config.ad_account_id,
        "default_organization_id": config.organization_id,
        "upload_dir": str(config.upload_dir) if config.upload_dir else None,
        "audit_log": str(config.audit_log),
        "audit_retention_days": config.audit_retention_days,
        "dry_run": config.dry_run,
        "read_only": config.read_only,
        "tool_groups": config.tool_groups or "all",
        "bulk_threshold": config.bulk_threshold,
        "max_increase_pct": config.max_increase_pct,
        "max_budget": config.max_budget,
        "max_bid": config.max_bid,
        "transport": config.transport,
        "host": config.host,
        "port": config.port,
        "allow_remote": config.allow_remote,
    }
    click.echo(json.dumps(info, indent=2, ensure_ascii=False))


def main() -> None:
    try:
        cli(obj={})
    except RuntimeError as e:
        # Surface config errors cleanly instead of a Python traceback.
        click.echo(f"Error: {redact(str(e))}", err=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
