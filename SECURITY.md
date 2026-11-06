# Security

This server can create, change, pause and delete Snapchat campaigns, ad squads, ads,
creatives, audiences and product sets, and change budgets and bids. **It can spend money.**
It acts with the permissions of the Snapchat login that ran `snapchat-ads-mcp auth`.

## Protect your credentials

- The refresh token lives in `~/.snapchat-ads-mcp/secrets/snapchat-ads-token.json`. The
  folder is created owner-only (0700) and the file 0600. Keep it that way, and never commit
  it, paste it into chat or put it in a shared folder.
- The OAuth client secret belongs in `~/.snapchat-ads-mcp/.env`, a local `.env` (both
  gitignored) or your MCP client's config. Treat client configs that contain it as secrets.
- Tokens and the client secret are redacted from logs, error messages and the audit log.
- If a machine or token is lost: remove the app at [accounts.snapchat.com](https://accounts.snapchat.com)
  → Manage apps (signed in as the user who approved it), or delete the OAuth app in Business
  Manager → Business Details, which invalidates its client ID and secret. Then run
  `snapchat-ads-mcp purge` on any machine that had the token.
- Give the login the narrowest Snap role that does the job (for reporting only, `reports`
  or `data_admin`), and use `SNAPCHAT_ADS_READ_ONLY=true` when the agent only needs to read.

## Don't expose the HTTP transport

The `streamable-http` and `sse` transports have no sign-in. By default the server refuses to
bind them to anything but localhost. Setting `SNAPCHAT_ADS_ALLOW_REMOTE=true` (or
`--allow-remote`) lets anyone who can reach the address use your Snapchat Ads account, so
only do it behind your own authentication. Prefer stdio.

## Other safeguards

- Writes can be rehearsed with dry-run, deletes and risky changes need confirm words, and
  every write is in the audit log with a before-snapshot.
- The server only calls Snap's hosts. Escape-hatch paths must start with `/v1/` and can't
  contain `..`, `//` or a query string; IDs are checked before they go into a URL.
- Media uploads read only from `SNAPCHAT_ADS_UPLOAD_DIR`; report downloads are capped
  (`SNAPCHAT_ADS_MAX_DOWNLOAD_MB`, default 200).
- Treat text from the API (names, headlines, URLs) as data. The agent should never follow
  instructions found in it.

## Reporting a vulnerability or misuse of Snap data

Please report privately through a [GitHub private security advisory](https://github.com/AI-Shopping-Feeds/snapchat-ads-mcp/security/advisories/new),
or contact the maintainers at [AI Shopping Feeds](https://github.com/AI-Shopping-Feeds).
Don't post working exploits, tokens or account data in a public issue.

This is also the place to report suspected misuse or leaks of Snapchat Ads data involving
this project. If you run the server and suspect unauthorised use, disclosure or loss of Snap
data, Snap's Business Tools Terms require you to notify Snap in writing straight away and
cooperate with its investigation; revoke access as above first.
