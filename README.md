# Snapchat Ads MCP Server (read + write)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) [![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/downloads/)

An [MCP](https://modelcontextprotocol.io) server for Snapchat advertising, using the
[Snap Marketing API](https://developers.snap.com/marketing-api/Ads-API/introduction) (v1).
Use it from Claude, ChatGPT, Cursor, Codex or any MCP client to report on campaigns, build
and change campaigns, ad squads, ads and creatives, upload media, manage audiences and
product sets, and move budgets and bids.

Maintained by [AI Shopping Feeds](https://github.com/AI-Shopping-Feeds). It offers:

- **The advertiser workflow on Snap's current API**: organisations and ad accounts,
  campaigns, ad squads, ads, creatives and media uploads, audience segments, targeting and
  estimates, pixels and Snap App IDs, catalogs and product sets, stats and async reports
- **Safety**: dry-run, confirm words, spend guards, before-snapshots, an audit log,
  read-only mode and tool groups, with new campaigns, ad squads and ads created paused
- **Everything else** through a read-only and a confirm-gated raw request tool

Snap runs its own [hosted Snapchat Ads MCP server](https://forbusiness.snapchat.com/blog/snapchat-ads-mcp),
which is read-only at launch and needs no developer app. This one runs on your own machine
with your own Snap OAuth app, and adds writes with the safety layer above. Details in
[docs/terms-and-data.md](docs/terms-and-data.md#snaps-official-ads-mcp-server).

Not affiliated with or endorsed by Snap Inc. "Snapchat" and "Snap" are used only to say
what the server works with.

Part of the AI Shopping Feeds MCP family: [Google Ads](https://github.com/AI-Shopping-Feeds/google-ads-mcp) · [Google Merchant Centre](https://github.com/AI-Shopping-Feeds/google-merchant-centre-mcp) · [Google Analytics](https://github.com/AI-Shopping-Feeds/google-analytics-mcp) · [YouTube Studio](https://github.com/AI-Shopping-Feeds/youtube-studio-mcp) · [Amazon Ads](https://github.com/AI-Shopping-Feeds/amazon-ads-mcp) · [Apple Ads](https://github.com/AI-Shopping-Feeds/apple-ads-mcp) · [Microsoft Ads](https://github.com/AI-Shopping-Feeds/microsoft-ads-mcp) · [TikTok Ads](https://github.com/AI-Shopping-Feeds/tiktok-ads-mcp) · [Pinterest Ads](https://github.com/AI-Shopping-Feeds/pinterest-ads-mcp) · **[Snapchat Ads](https://github.com/AI-Shopping-Feeds/snapchat-ads-mcp)** · [OpenAI Ads](https://github.com/AI-Shopping-Feeds/openai-ads-mcp) · [AppLovin](https://github.com/AI-Shopping-Feeds/applovin-mcp).

## Let your agent set it up

Paste this into Claude Code, Codex, Cursor or any agent that can read web pages and edit files:

```text
Set up the Snapchat Ads MCP server for me by following https://raw.githubusercontent.com/AI-Shopping-Feeds/snapchat-ads-mcp/main/skills/snapchat-ads-mcp/SKILL.md
```

The agent checks whether it's already connected, installs the runner if you agree, walks
you through creating a Snap OAuth app and signing in, adds the server to your client's
config without touching your other servers, and checks it works by calling
`snapchat_ads_health_check`.

The same file is an [Agent Skill](https://agentskills.io), so your agent can keep it as a guide to using the tools well. For Claude Code, copy the folder into your skills:

```bash
git clone --depth 1 https://github.com/AI-Shopping-Feeds/snapchat-ads-mcp.git /tmp/snapchat-ads-mcp
cp -r /tmp/snapchat-ads-mcp/skills/snapchat-ads-mcp ~/.claude/skills/
```

Other agents that support skills load the same `skills/snapchat-ads-mcp` folder from their own skills directory.

## What it can do

58 tools, all prefixed `snapchat_ads_`. The full list is in [docs/tools.md](docs/tools.md).

### Read

| Area | Tools |
|---|---|
| Accounts | `get_me`, `list_organizations`, `list_ad_accounts`, `get_ad_account`, `list_funding_sources` |
| Campaign structure | `list_campaigns`, `list_ad_squads`, `list_ads` (with delivery and review status), `get_change_log` |
| Creatives | `list_creatives`, `get_creative_preview`, `list_media` |
| Audiences and targeting | `list_segments`, `get_targeting_options`, `estimate_audience_size`, `get_bid_estimate`, `get_bid_recommendation`, `check_optimization_eligibility` |
| Pixels and apps | `list_pixels`, `get_pixel_domains`, `get_pixel_stats`, `list_snap_apps` |
| Catalogs | `list_catalogs`, `list_product_feeds`, `list_feed_uploads`, `list_product_sets`, `search_products` |
| Reporting | `get_stats` (TOTAL/DAY/HOUR/LIFETIME, breakdowns, insights, attribution windows), `run_report` (async CSV with progress), `create_async_report`, `get_async_report`, `download_async_report` |
| Anything else | `read_request` |

### Write

| Area | Tools |
|---|---|
| Campaigns, ad squads, ads | `create_*`, `update_*` (JSON Patch, so untouched fields stay as they are), `delete_*` |
| Budgets, bids, status | `set_budgets`, `set_bids` (whole currency units or a percentage), `set_status` |
| Creatives and media | `create_creatives`, `update_creatives`, `upload_media` (up to 1 GB, chunked) |
| Audiences and catalogs | `create_segments`, `update_segments`, `delete_segments`, `create_product_sets` |
| Any endpoint | `request` |

### Safety

- **Dry-run** (`SNAPCHAT_ADS_DRY_RUN=true` or `snapchat_ads_set_dry_run`): writes are logged
  and previewed but not sent.
- **Confirm words**: deletes need `DELETE`; more than 10 items, bid or budget rises above
  20%, rises whose current value can't be read, removing a spend cap, values above your caps
  and raw writes need `APPLY`.
- **Spend guards**: Snap money is micro-currency (1.00 = 1,000,000). Updates read current
  values first and compare them; `SNAPCHAT_ADS_MAX_BUDGET` and `SNAPCHAT_ADS_MAX_BID` set
  absolute caps in whole units.
- **Paused by default**: new campaigns, ad squads and ads are created PAUSED unless you set
  a status.
- **Audit log** of every write with a before-snapshot, at `~/.snapchat-ads-mcp/logs/audit.jsonl`
  (0600). Entries older than 30 days are pruned; `snapchat-ads-mcp purge` deletes the log
  and the stored token.
- **Read-only mode** (`SNAPCHAT_ADS_READ_ONLY=true`) and **tool groups**
  (`SNAPCHAT_ADS_TOOL_GROUPS`).
- **Local only by default**: HTTP transports refuse to bind to anything but localhost
  unless `SNAPCHAT_ADS_ALLOW_REMOTE=true`. Uploads are limited to `SNAPCHAT_ADS_UPLOAD_DIR`.
- Snap's terms and how the server follows them: [docs/terms-and-data.md](docs/terms-and-data.md).

## Supported clients

| Client | Works? | How |
|---|---|---|
| Claude Code | ✅ | Local server, `claude mcp add` (below) |
| Claude Desktop | ✅ | Local server, `claude_desktop_config.json` |
| Cursor | ✅ | Local server, `~/.cursor/mcp.json` |
| VS Code (Copilot) | ✅ | Local server, `.vscode/mcp.json` (uses `servers` instead of `mcpServers`) |
| Codex | ✅ | Local server, `~/.codex/config.toml` |
| Gemini CLI | ✅ | Local server, `~/.gemini/settings.json` |
| Windsurf and other local clients | ✅ | Local server, same JSON entry |
| Claude.ai and ChatGPT | ❌ not yet | These need a remote server with sign-in. This server's HTTP transports have no sign-in, so don't expose them publicly. Use a local client, or Snap's hosted read-only server for these. |

## Setup

### 1. Install uv

The server runs with `uvx` from [uv](https://docs.astral.sh/uv/getting-started/installation/)
(`brew install uv` on macOS) and needs Python 3.11 or later. It installs straight from this
repository:

```shell
uvx --from git+https://github.com/AI-Shopping-Feeds/snapchat-ads-mcp.git snapchat-ads-mcp version
```

Pin a release by adding `@vX.Y.Z` to the URL.

### 2. Get credentials

1. **Snap OAuth app:** an Organization Admin opens Snap Business Manager → Business
   Details → **+ OAuth app**, accepts the Snap Developer Terms and Business Tools Terms,
   adds the redirect URI `http://localhost:8765/callback`, and copies the client ID and
   the client secret (shown only once). No approval wait. Step by step, including what to
   do if a localhost redirect isn't accepted:
   [docs/setup-snapchat-ads-api.md](docs/setup-snapchat-ads-api.md).
2. **Sign in** with the Snapchat business login that can see the ad accounts:

   ```shell
   SNAPCHAT_ADS_CLIENT_ID=your-client-id SNAPCHAT_ADS_CLIENT_SECRET=your-client-secret \
     uvx --from git+https://github.com/AI-Shopping-Feeds/snapchat-ads-mcp.git snapchat-ads-mcp auth
   ```

   The refresh token is saved to `~/.snapchat-ads-mcp/secrets/snapchat-ads-token.json`
   (owner-only). It doesn't expire, but stops working if that user loses access.
3. **Find your ad account ID** with `snapchat_ads_list_organizations` once connected, or in
   Ads Manager.

### 3. Add it to your client

Replace the placeholders. Keep your other servers in each file.

**Claude Code**

```bash
claude mcp add --scope user snapchat-ads \
  --env SNAPCHAT_ADS_CLIENT_ID=your-client-id \
  --env SNAPCHAT_ADS_CLIENT_SECRET=your-client-secret \
  --env SNAPCHAT_ADS_AD_ACCOUNT_ID=your-ad-account-id \
  --env SNAPCHAT_ADS_DRY_RUN=true \
  -- uvx --from git+https://github.com/AI-Shopping-Feeds/snapchat-ads-mcp.git snapchat-ads-mcp
```

**Claude Desktop, Cursor, Gemini CLI, Windsurf** (and VS Code under `servers`)

```json
{
  "mcpServers": {
    "snapchat-ads": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/AI-Shopping-Feeds/snapchat-ads-mcp.git", "snapchat-ads-mcp"],
      "env": {
        "SNAPCHAT_ADS_CLIENT_ID": "your-client-id",
        "SNAPCHAT_ADS_CLIENT_SECRET": "your-client-secret",
        "SNAPCHAT_ADS_AD_ACCOUNT_ID": "your-ad-account-id",
        "SNAPCHAT_ADS_UPLOAD_DIR": "/abs/path/snap-media",
        "SNAPCHAT_ADS_DRY_RUN": "true"
      }
    }
  }
}
```

Desktop apps often can't find `uvx` on the PATH; if the server doesn't start, use the full
path from `which uvx` as the `command`. To keep secrets out of client configs, put them in
`~/.snapchat-ads-mcp/.env` instead (see [.env.example](.env.example)).

**Codex** (`~/.codex/config.toml`)

```toml
[mcp_servers.snapchat-ads]
command = "uvx"
args = ["--from", "git+https://github.com/AI-Shopping-Feeds/snapchat-ads-mcp.git", "snapchat-ads-mcp"]
env = { SNAPCHAT_ADS_CLIENT_ID = "your-client-id", SNAPCHAT_ADS_CLIENT_SECRET = "your-client-secret", SNAPCHAT_ADS_AD_ACCOUNT_ID = "your-ad-account-id", SNAPCHAT_ADS_DRY_RUN = "true" }
```

### 4. Check it works

Restart or reload the client, then ask it to "check my Snapchat Ads connection". It should
call `snapchat_ads_health_check` and list your organisations and ad accounts. Turn dry-run
off (`SNAPCHAT_ADS_DRY_RUN=false`) once you're happy with what it would send.

## Configuration

| Variable | Required | What it does |
|---|---|---|
| `SNAPCHAT_ADS_CLIENT_ID`, `SNAPCHAT_ADS_CLIENT_SECRET` | yes | Snap OAuth app credentials |
| `SNAPCHAT_ADS_TOKEN_FILE` | no | Refresh-token file written by `auth` (default `~/.snapchat-ads-mcp/secrets/snapchat-ads-token.json`) |
| `SNAPCHAT_ADS_REFRESH_TOKEN` | no | The refresh token itself, instead of the file |
| `SNAPCHAT_ADS_REDIRECT_URI` | no | Redirect URI for `auth` if not `http://localhost:8765/callback` |
| `SNAPCHAT_ADS_AD_ACCOUNT_ID`, `SNAPCHAT_ADS_ORGANIZATION_ID` | no | Defaults for tools that take `ad_account_id` / `organization_id` |
| `SNAPCHAT_ADS_UPLOAD_DIR` | for uploads | Folder media may be uploaded from; unset means uploads are off |
| `SNAPCHAT_ADS_DRY_RUN` | no | `true` previews writes without sending them |
| `SNAPCHAT_ADS_READ_ONLY` | no | `true` registers only read-only tools |
| `SNAPCHAT_ADS_TOOL_GROUPS` | no | Comma-separated groups: `accounts`, `campaigns`, `ad_squads`, `ads`, `bulk`, `creatives`, `audiences`, `targeting`, `pixels`, `catalogs`, `reporting`, `request`. Unknown names stop the server at startup |
| `SNAPCHAT_ADS_BULK_THRESHOLD` | no | Items per write before `confirm="APPLY"` is needed (default 10) |
| `SNAPCHAT_ADS_MAX_INCREASE_PCT` | no | Bid/budget rise that needs `confirm="APPLY"` (default 20) |
| `SNAPCHAT_ADS_MAX_BUDGET`, `SNAPCHAT_ADS_MAX_BID` | no | Optional caps in whole units of the account currency |
| `SNAPCHAT_ADS_AUDIT_LOG` | no | Audit log path (default `~/.snapchat-ads-mcp/logs/audit.jsonl`) |
| `SNAPCHAT_ADS_AUDIT_RETENTION_DAYS` | no | Days to keep audit entries, pruned at startup (default 30; 0 keeps them) |
| `SNAPCHAT_ADS_HOME` | no | Per-user data folder (default `~/.snapchat-ads-mcp`) |
| `SNAPCHAT_ADS_PAGE_SIZE`, `SNAPCHAT_ADS_TIMEOUT` | no | List page size (50-1000, default 500) and request timeout in seconds (30) |
| `SNAPCHAT_ADS_MAX_RPS` | no | Requests per second (default 8; Snap allows about 10 per token) |
| `SNAPCHAT_ADS_MAX_DOWNLOAD_MB` | no | Largest async report the server downloads into memory (default 200) |
| `SNAPCHAT_ADS_TRANSPORT`, `SNAPCHAT_ADS_HOST`, `SNAPCHAT_ADS_PORT` | no | `stdio` (default), `streamable-http` (served at `/mcp`) or `sse` (deprecated), and the bind address (default `127.0.0.1:8000`) |
| `SNAPCHAT_ADS_ALLOW_REMOTE` | no | `true` (or `--allow-remote`) lets HTTP transports bind to a non-loopback address. The server has no sign-in of its own |
| `SNAPCHAT_ADS_LOG_LEVEL` | no | `DEBUG`, `INFO`, `WARNING` or `ERROR` (logs go to stderr) |

Settings are read from the environment, then `--env FILE` or `./.env`, then
`~/.snapchat-ads-mcp/.env`. CLI: `snapchat-ads-mcp run` (default), `auth`, `purge`,
`describe`, `version`.

## Example prompts

```text
How did my Snapchat campaigns do last week? Show spend, swipes, purchases and cost per purchase by campaign.
```

```text
Pause every ad that Snap rejected in the "Spring sale" campaign and tell me the rejection reasons.
```

```text
Raise the daily budget by 15% on ad squads with a cost per purchase under 10. Dry-run first and show me a table.
```

```text
Upload hero-9x16.mp4 from my media folder, make a web view creative pointing at https://example.com/sale, and add a paused ad to the "UK 18-34" ad squad.
```

## More docs

- [All tools and confirm words](docs/tools.md)
- [Getting Snap Marketing API access](docs/setup-snapchat-ads-api.md)
- [Snap's terms, data handling and the official MCP server](docs/terms-and-data.md)
- [Agent skill](skills/snapchat-ads-mcp/SKILL.md): setup and usage guide for agents
- [Changelog](CHANGELOG.md) and [security policy](SECURITY.md)

## Contributing and licence

Issues and pull requests are welcome on [this repository](https://github.com/AI-Shopping-Feeds/snapchat-ads-mcp). See
[CONTRIBUTING.md](CONTRIBUTING.md).

Licensed under the [MIT License](LICENSE).

---

Try out [AI Shopping Feeds](https://aishoppingfeeds.com/), our shopping feed management tool (including Google Shopping feeds).
