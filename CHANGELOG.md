# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-06

### Added
- First version, on the Snap Marketing API v1: 58 tools in 12 groups (accounts, campaigns,
  ad_squads, ads, bulk, creatives, audiences, targeting, pixels, catalogs, reporting,
  request), plus 5 meta tools that are always registered.
- Snap OAuth 2.0: `snapchat-ads-mcp auth` runs the consent flow with a localhost callback or
  `--manual` paste mode (the pasted address must carry the matching `state`), and saves the
  refresh token owner-only. Access tokens refresh automatically and are cached; a 401
  triggers one refresh.
- One request choke point with client-side throttling (8 requests/s), retries that honour
  `Retry-After`, no automatic retry of non-idempotent creates on 5xx, cursor paging that
  only follows Snap links, and fetch-by-IDs for up to 2,000 entities.
- Updates send JSON Patch (PATCH) so omitted fields are never reset, with before-snapshots
  in the audit log. Bulk status, budget and bid tools take whole currency units or
  percentages and convert to micro-currency; entity reads add whole-unit `amounts`.
- Media uploads from `SNAPCHAT_ADS_UPLOAD_DIR`, single or chunked (multipart-upload-v2, up
  to 1 GB), with the AI-content self-declaration.
- Stats with TOTAL/DAY/HOUR/LIFETIME granularity, breakdowns, insights and attribution
  windows, flattened to rows; async CSV reports with `snapchat_ads_run_report` (polls with
  progress, downloads into memory, size-capped).
- Safety: dry-run, confirm words (`DELETE`, `APPLY`), spend guards
  (`SNAPCHAT_ADS_MAX_INCREASE_PCT` 20%, optional caps), paused-by-default creates, read-only
  mode, tool groups, audit log with 30-day retention and `purge`.
- Hardening: per-user `~/.snapchat-ads-mcp/` folders (0700/0600), HTTP transports refuse
  non-loopback binds unless `SNAPCHAT_ADS_ALLOW_REMOTE=true`, redaction of tokens and
  secrets, ID and path checks, only Snap hosts contacted, no customer-identifier uploads,
  emails dropped from user and change-log output.
