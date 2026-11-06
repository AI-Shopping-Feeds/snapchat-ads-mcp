"""Configuration: environment variables, .env files and per-user paths.

Everything the server writes lives under a per-user folder,
`~/.snapchat-ads-mcp/` (or SNAPCHAT_ADS_HOME), never inside the install
location: `secrets/` (0700) holds the refresh-token file (0600) and `logs/`
(0700) holds the audit log (0600).
"""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

APP_NAME = "snapchat-ads-mcp"
ENV_PREFIX = "SNAPCHAT_ADS_"

# Snap Marketing API v1 and Snap's OAuth 2.0 endpoints (from Snap's
# "Authentication" and "API Patterns" guides).
API_HOST = "https://adsapi.snapchat.com"
API_VERSION = "v1"
AUTHORIZE_URL = "https://accounts.snapchat.com/login/oauth2/authorize"
TOKEN_URL = "https://accounts.snapchat.com/login/oauth2/access_token"
SCOPE = "snapchat-marketing-api"

# "sse" (HTTP+SSE) is deprecated by the MCP spec; prefer "streamable-http".
TRANSPORTS = ("stdio", "streamable-http", "sse")
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

TOKEN_FILE_NAME = "snapchat-ads-token.json"
AUDIT_LOG_NAME = "audit.jsonl"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def home_dir() -> Path:
    """The per-user data folder (SNAPCHAT_ADS_HOME, default ~/.snapchat-ads-mcp)."""
    raw = os.environ.get("SNAPCHAT_ADS_HOME", "").strip()
    return Path(raw).expanduser().resolve() if raw else Path.home() / f".{APP_NAME}"


def ensure_private_dir(path: Path) -> Path:
    """Create a folder (and parents) readable only by the owner (0700 where supported)."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    with contextlib.suppress(OSError):  # e.g. some Windows or network filesystems
        os.chmod(path, 0o700)
    return path


def _path_or_none(raw: str | None) -> Path | None:
    if not raw or not raw.strip():
        return None
    return Path(raw).expanduser().resolve()


def token_file_path() -> Path:
    """Where `snapchat-ads-mcp auth` stores the refresh token."""
    return _path_or_none(os.environ.get("SNAPCHAT_ADS_TOKEN_FILE")) or (
        home_dir() / "secrets" / TOKEN_FILE_NAME
    )


def audit_log_path() -> Path:
    """The audit log (SNAPCHAT_ADS_AUDIT_LOG, default ~/.snapchat-ads-mcp/logs/audit.jsonl)."""
    return _path_or_none(os.environ.get("SNAPCHAT_ADS_AUDIT_LOG")) or (
        home_dir() / "logs" / AUDIT_LOG_NAME
    )


def load_env_files(env_file: Path | None = None) -> None:
    """Load .env files without overriding variables that are already set.

    Order (first wins): the process environment, then `--env FILE` or ./.env,
    then ~/.snapchat-ads-mcp/.env.
    """
    if env_file is not None:
        load_dotenv(dotenv_path=env_file, override=False)
    else:
        load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
    user_env = home_dir() / ".env"
    if user_env.is_file():
        load_dotenv(dotenv_path=user_env, override=False)


def parse_tool_groups(raw: str | None) -> list[str]:
    """Split a comma-separated SNAPCHAT_ADS_TOOL_GROUPS value and check every name.

    Names are case-insensitive and may use '-' for '_'. Empty means all groups.
    """
    from .tools import resolve_tool_groups  # local: tools imports this module

    names = [p.strip().lower().replace("-", "_") for p in (raw or "").split(",")]
    names = [n for n in names if n]
    return resolve_tool_groups(names) if names else []


@dataclass
class Config:
    client_id: str
    client_secret: str
    refresh_token: str | None
    audit_log: Path
    token_file: Path | None = None
    ad_account_id: str | None = None
    organization_id: str | None = None
    upload_dir: Path | None = None
    page_size: int = 500
    timeout: float = 30.0
    dry_run: bool = False
    log_level: str = "INFO"
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000
    allow_remote: bool = False
    # Tool modules to register; empty means all (see snapchat_ads_mcp.tools.TOOL_GROUPS).
    tool_groups: list[str] = field(default_factory=list)
    # Register only tools annotated read-only (plus the meta tools).
    read_only: bool = False
    # Writes touching more than this many entities need confirm='APPLY'.
    bulk_threshold: int = 10
    # Bid or budget increases above this percentage need confirm='APPLY'.
    max_increase_pct: float = 20.0
    # Optional absolute caps in the ad account's currency (not micro); above them needs 'APPLY'.
    max_budget: float | None = None
    max_bid: float | None = None
    # Audit entries older than this are pruned at startup; 0 keeps them.
    audit_retention_days: int = 30
    # Client-side request rate; Snap allows about 10 requests/second per token.
    max_rps: float = 8.0
    # Largest async report file the server will download into memory.
    max_download_mb: int = 200

    @property
    def api_host(self) -> str:
        return API_HOST


def read_token_file(path: Path) -> str | None:
    """Return the refresh token stored by `snapchat-ads-mcp auth`, or None."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RuntimeError(f"Could not read the token file {path}: {e}") from e
    token = data.get("refresh_token") if isinstance(data, dict) else None
    return token or None


def _int(name: str, default: str) -> int:
    try:
        return int(os.environ.get(name, default).strip() or default)
    except ValueError as e:
        raise RuntimeError(f"{name} must be an integer") from e


def _float(name: str, default: str) -> float:
    try:
        return float(os.environ.get(name, default).strip() or default)
    except ValueError as e:
        raise RuntimeError(f"{name} must be a number") from e


def _float_or_none(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError as e:
        raise RuntimeError(f"{name} must be a number, got '{raw}'") from e


def load_config(env_file: Path | None = None, *, require_refresh_token: bool = True) -> Config:
    """Read configuration from the environment and .env files.

    Raises RuntimeError with an actionable message on misconfiguration.
    """
    load_env_files(env_file)

    client_id = os.environ.get("SNAPCHAT_ADS_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SNAPCHAT_ADS_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError(
            "SNAPCHAT_ADS_CLIENT_ID and SNAPCHAT_ADS_CLIENT_SECRET must be set.\n"
            "  - Create an OAuth app in Snap Business Manager -> Business Details ->\n"
            "    OAuth apps (you need the Organization Admin role).\n"
            "  - The client secret is shown only once, when the app is created.\n"
            "  - See docs/setup-snapchat-ads-api.md."
        )

    token_file = token_file_path()
    refresh_token = os.environ.get("SNAPCHAT_ADS_REFRESH_TOKEN", "").strip() or None
    if refresh_token is None:
        refresh_token = read_token_file(token_file)
    if refresh_token is None and require_refresh_token:
        raise RuntimeError(
            "No refresh token configured. Either:\n"
            f"  - run `snapchat-ads-mcp auth` once (saves it to {token_file}), or\n"
            "  - set SNAPCHAT_ADS_REFRESH_TOKEN, or\n"
            "  - set SNAPCHAT_ADS_TOKEN_FILE to the file `snapchat-ads-mcp auth` wrote."
        )

    transport = os.environ.get("SNAPCHAT_ADS_TRANSPORT", "stdio").strip().lower() or "stdio"
    if transport not in TRANSPORTS:
        raise RuntimeError(
            f"SNAPCHAT_ADS_TRANSPORT must be one of {', '.join(TRANSPORTS)}, got '{transport}'."
        )

    upload_dir = _path_or_none(os.environ.get("SNAPCHAT_ADS_UPLOAD_DIR"))
    if upload_dir is not None and not upload_dir.is_dir():
        raise RuntimeError(f"SNAPCHAT_ADS_UPLOAD_DIR is not a folder: {upload_dir}")

    page_size = _int("SNAPCHAT_ADS_PAGE_SIZE", "500")
    if not 50 <= page_size <= 1000:
        raise RuntimeError("SNAPCHAT_ADS_PAGE_SIZE must be between 50 and 1000 (Snap's limits).")

    return Config(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        audit_log=audit_log_path(),
        token_file=token_file,
        ad_account_id=os.environ.get("SNAPCHAT_ADS_AD_ACCOUNT_ID", "").strip() or None,
        organization_id=os.environ.get("SNAPCHAT_ADS_ORGANIZATION_ID", "").strip() or None,
        upload_dir=upload_dir,
        page_size=page_size,
        timeout=_float("SNAPCHAT_ADS_TIMEOUT", "30"),
        dry_run=_truthy(os.environ.get("SNAPCHAT_ADS_DRY_RUN")),
        log_level=os.environ.get("SNAPCHAT_ADS_LOG_LEVEL", "INFO").strip().upper() or "INFO",
        transport=transport,
        host=os.environ.get("SNAPCHAT_ADS_HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=_int("SNAPCHAT_ADS_PORT", "8000"),
        allow_remote=_truthy(os.environ.get("SNAPCHAT_ADS_ALLOW_REMOTE")),
        tool_groups=parse_tool_groups(os.environ.get("SNAPCHAT_ADS_TOOL_GROUPS")),
        read_only=_truthy(os.environ.get("SNAPCHAT_ADS_READ_ONLY")),
        bulk_threshold=_int("SNAPCHAT_ADS_BULK_THRESHOLD", "10"),
        max_increase_pct=_float("SNAPCHAT_ADS_MAX_INCREASE_PCT", "20"),
        max_budget=_float_or_none("SNAPCHAT_ADS_MAX_BUDGET"),
        max_bid=_float_or_none("SNAPCHAT_ADS_MAX_BID"),
        audit_retention_days=_int("SNAPCHAT_ADS_AUDIT_RETENTION_DAYS", "30"),
        max_rps=_float("SNAPCHAT_ADS_MAX_RPS", "8"),
        max_download_mb=_int("SNAPCHAT_ADS_MAX_DOWNLOAD_MB", "200"),
    )
