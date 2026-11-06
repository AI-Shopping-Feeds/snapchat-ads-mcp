# Contributing

Thanks for helping improve Snapchat Ads MCP.

## Development setup

```bash
git clone https://github.com/AI-Shopping-Feeds/snapchat-ads-mcp.git
cd snapchat-ads-mcp
uv venv && uv pip install -e ".[test,dev]"
```

Or with plain venv: `python -m venv .venv && .venv/bin/pip install -e ".[test,dev]"`.
Python 3.11 or later.

To try it against a real account, create a Snap OAuth app (see
[docs/setup-snapchat-ads-api.md](docs/setup-snapchat-ads-api.md)), put the credentials in
`~/.snapchat-ads-mcp/.env`, run `.venv/bin/snapchat-ads-mcp auth`, and start with
`SNAPCHAT_ADS_DRY_RUN=true`. A test ad account (Snap's `test: true` accounts never serve
ads) is the safest place to try writes.

## Checks

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy src/snapchat_ads_mcp
.venv/bin/pytest
```

Tests run offline: HTTP is mocked with `respx`. They never touch a real account.
`pre-commit install` runs ruff and mypy before each commit.

## Pull requests

- Keep secrets, tokens, account IDs and ad data out of commits, tests and issues. Use
  placeholders.
- New tools go in the matching module under `src/snapchat_ads_mcp/tools/`, use the
  `snapchat_ads_` prefix, and **need an entry in `tool_catalog.py`** (title and
  annotations) **and a row in `docs/tools.md`**. The test suite fails without both.
- Writes go through `client.request` (dry-run and audit), use the guards in `safety.py`
  (`DELETE` for deletes, `APPLY` for bulk, money rises and anything unchecked), and take a
  before-snapshot where the API allows.
- Use PATCH (JSON Patch) for updates where Snap supports it: PUT resets omitted fields.
- Money is micro-currency; say so in descriptions and add whole-unit `amounts` to results.
- **Never paste Snap's API documentation, specifications or sample code into the repo.**
  Snap's Developer Terms forbid copying or making derivative works of them. Describe
  behaviour in your own words and link to Snap's docs.
- Update the README, docs and CHANGELOG when tools, settings or setup change.
