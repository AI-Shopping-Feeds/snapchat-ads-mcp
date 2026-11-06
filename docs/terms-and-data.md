# Snap's terms, data handling and the official MCP server

This is a summary to help you use the server within Snap's rules, written from the terms as
published on 6 November 2026. It isn't legal advice, and Snap's own documents always win.
You (whoever runs the server) are the developer under Snap's terms: you create the OAuth
app, you accept the terms, and you are responsible for how the server and the AI client you
connect to it use Snap data.

Not affiliated with or endorsed by Snap Inc.

## Which terms apply

| Document | Effective | Why it applies |
|---|---|---|
| [Snap Developer Terms](https://www.snap.com/terms/developer) | 31 January 2025 | Accepted when you activate API access in Business Manager |
| [Snap Business Tools Terms](https://www.snap.com/terms/snap-business-tools) | 1 November 2021 | Accepted with the Developer Terms; covers API access to the ad platform |
| [Business Services Terms](https://www.snap.com/terms/business-services) | 30 September 2024 | Incorporates the two above; restrictions on Business Services Data |
| Snap Audience Match Terms, Snap Controller Data Processing Agreement | | Customer-list data and personal data (this server avoids both) |
| [Snap Brand Guidelines](https://snap.com/brand-guidelines), Advertising Policies | | Use of Snap's names, and what ads may contain. The brand guidelines are a PDF we haven't reviewed in detail |

Snap's [Ads MCP documentation](https://developers.snap.com/marketing-api/Ads-MCP/Introduction)
says the same Developer Terms bind anyone using an MCP server with Snap data, "and any agent
acting on your behalf", and that keeping the agent within them, including retention and
deletion limits, is your job: "Compliance is your responsibility."

## What the terms require, and what the server does

| Requirement | How the server handles it |
|---|---|
| Don't copy, translate or make derivative works of Snap's developer materials (Developer Terms §5(h)) | The repo contains only its own code and descriptions. No Snap specs, SDKs, sample code or documentation text. Contributors must not paste them in (CONTRIBUTING.md) |
| Don't share keys, credentials or access tokens outside your organisation (§5(a)) | Each user creates their own OAuth app. The refresh token is stored owner-only (0600) in `~/.snapchat-ads-mcp/secrets/`, never printed, and redacted from logs, errors and the audit log |
| Keep request volume reasonable (§5(c)); Snap's limits are about 20 requests/s per app and 10 per token | Throttles to 8 requests/s by default and backs off on HTTP 429, honouring `Retry-After` |
| Security programme and incident notice (§4(c); Business Tools Terms §3) | Owner-only files, no telemetry, loopback-only HTTP by default, capped downloads, path checks on the escape hatch and uploads. If you suspect a leak of Snap data, you must tell Snap in writing straight away; see [SECURITY.md](../SECURITY.md) |
| Keep Business Services Data only as long as needed, and never longer than 36 months (Business Tools Terms §3) | The audit log holds writes only (request, before-snapshot, response), pruned after `SNAPCHAT_ADS_AUDIT_RETENTION_DAYS` (30). Stats, report rows and other reads are kept in memory and returned to the client, never written to disk |
| Delete Business Services Data on Snap's request or when the terms end (Developer Terms §6(b), §8(b)) | `snapchat-ads-mcp purge` deletes the audit log and the stored token. Also delete anything your AI client kept (chat history, files) |
| Don't commingle Business Services Data with other data or across other platforms (Business Services Terms §2(b)(ii)) | The server instructions tell the agent not to combine Snap data with other ad platforms' or third-party data unless you confirm Snap allows it |
| Don't use the Services or their data "for the purposes of training any AI or machine learning model" (§2(a)(v)) | The instructions say so too. Use an AI provider whose business or API terms don't train on your inputs |
| No personal data processing without Snap's written consent (§2(a)(ii)); customer lists fall under the Audience Match Terms | The server never uploads customer identifiers. `get_me` drops the user's email and change logs drop editors' emails |
| Don't build segments or profiles of users from the data, or de-anonymise it (Developer Terms §5(m); Business Services Terms §2(b)) | Nothing in the server does this; don't ask the agent to |
| Only Snap's systems | The server calls only `adsapi.snapchat.com`, `accounts.snapchat.com` (sign-in) and Snap's report download host (`*.snapads.com`). The raw request tools can't reach any other host. Media uploads read local files only |
| Implement Snap's API changes promptly (Developer Terms §2(b)) | Keep the server updated; see [API version and deprecations](#api-version-and-deprecations) |
| Don't imply Snap made or endorses your tool (§5(f), §5(g)) | Descriptive use of "Snapchat" and "Snap" only, a "not affiliated" line, no logos |

## Three things to check before you rely on it

### (a) Using it with AI clients such as Claude

Allowed in principle, with care. Snap's own Ads MCP server works with Claude, ChatGPT,
Codex and Gemini, so Snap expects Snap Ads data to reach AI agents. But the data you read
goes to whichever model provider your client uses, and Business Services Terms §2(b)(iii)
forbids disclosing Business Services Data to third parties except as the terms allow.

- Use the AI provider under business or API terms where it processes data on your behalf,
  doesn't train on it (§2(a)(v)) and lets you delete it.
- Keep chat history no longer than you need (the 36-month cap and "legitimate business need"
  apply to copies in your AI client too).
- Don't ask the agent to mix Snap data with other platforms' data (§2(b)(ii)).

### (b) Making this repo public under a name containing "Snapchat"

This is the main risk. Three clauses deserve a careful read before the repo goes public:

- Developer Terms §8(a): you "must not make any public statement regarding your access to,
  or use of" the Snap Developer Program without Snap's prior written approval. A public
  README describing an integration could be read as such a statement.
- Developer Terms §5(i) forbids using the program to "compete with or replicate any Snap
  applications, products, or services", and Business Services Terms §2(a)(v) forbids using
  the Services to build a competing product. Snap now ships its own Ads MCP server; this
  project does more (writes) and is free and self-hosted, but the overlap is real.
- Trademark: the repo, package and command names contain "snapchat". Use is descriptive and
  carries a "not affiliated" line, but Snap's brand guidelines (a PDF we didn't review in
  detail) may restrict using its marks in product names.

Recommendation: ask Snap (through a Snap account manager or partner contact) for written
approval of the public repo and its name before publishing, or publish under a neutral name
that mentions Snap only in the description.

### (c) Agencies using it for clients

Possible, within limits:

- An agency running the server for its own staff, on client ad accounts shared to the
  agency's organisation in Business Manager, works like any other user. Business Services
  Terms §3(c): you must be authorised to act for the client and bind it to the terms.
- Use the agency's own OAuth app and login. Never share tokens or credentials with clients
  or across organisations (Developer Terms §5(a)).
- Use each client's data only for that client, and don't mix clients' data in one
  analysis (§2(b)(ii) on commingling; Business Tools Terms §2(h) sets the same rule for
  partners).
- Giving clients access to the server, or offering it to advertisers as your product, makes
  you a "Partner" under Business Tools Terms §2: that needs Snap's authorisation and prior
  written approval of the application, a contract with each customer, and support duties.
  Developer Terms §5(o) also forbids charging for access to the program, and §4(b) requires
  a published privacy policy for an application others use.

## Snap's official Ads MCP server

Snap [launched](https://forbusiness.snapchat.com/blog/snapchat-ads-mcp) a hosted Snapchat Ads
MCP server on 3 August 2026 ([docs](https://developers.snap.com/marketing-api/Ads-MCP/Introduction)).

| | Snap's Ads MCP | This server |
|---|---|---|
| Where it runs | Hosted by Snap at `https://mcp.snapchat.com/ads` | On your machine (stdio, or localhost HTTP) |
| Reads | Yes | Yes: entities, stats, async reports, targeting, pixels, catalogs, change logs |
| Writes | Not at launch; planned, with per-agent write approval by org admins | Yes: create, update (JSON Patch), delete, budgets, bids, status, media uploads, segments, product sets |
| Safety | Org-level approval per agent, user-level consent, read-only | Dry-run, confirm words, spend guards, before-snapshots, audit log, read-only mode, tool groups, paused-by-default creates |
| Auth | Snap-registered client IDs per agent (`claude-snap-ads` and others), scope `snapads.read`; an Admin or Business Admin approves each agent for the organisation, then each member authorises | Your own OAuth app from Business Manager, scope `snapchat-marketing-api`; the server acts as the login that ran `auth` |
| Clients | Claude Code, Claude Desktop and web, Codex, ChatGPT (web connector), Antigravity, Gemini CLI | Any client that runs local MCP servers; not Claude.ai or ChatGPT web |
| Setup | Add the URL and client ID in the client, sign in | Create an OAuth app, run `auth`, add to the client |
| Availability | Self-service, no allowlist for read-only access; no regional limits stated | Wherever you can reach the Marketing API |

Use Snap's server if you want read-only analysis from Claude.ai or ChatGPT with no setup.
Use this one if you want the agent to make changes, need dry-run and an audit trail, or
want everything to stay on your machine.

## API version and deprecations

- **Snap Marketing API v1** at `https://adsapi.snapchat.com/v1/` is the current and only
  version. Snap hasn't announced a v2. OAuth: `https://accounts.snapchat.com/login/oauth2/authorize`
  and `.../access_token`, scope `snapchat-marketing-api`, one-hour access tokens and
  non-expiring refresh tokens.
- Snap's announcements and change log (checked 6 November 2026) list **no deprecation or
  sunset between now and mid-2027**. Snap has historically given 90 days' notice for
  breaking changes.
- Built around changes already announced:
  - Updates use **PATCH with JSON Patch** (added May 2026), never PUT, which resets omitted
    fields. Segments still use PUT, after reading and merging the current values.
  - Campaigns use **`objective_v2_properties`**; the old `objective` field is phased out.
  - Bidding uses **`bid_strategy`**; `MIN_ROAS` and `roas_value_micro` (deprecated
    February 2025) aren't offered, nor `auto_bid` / `target_bid`.
  - **Oracle (DLX) interest targeting**, removed in September 2024, isn't offered.
  - Audience estimates use **`audience_size_v2`**; Snap says the older endpoint will go.
  - Reporting uses **`report_dimension`**, not the retired `dimension` / `pivot`; the 28-day
    view attribution window isn't offered; the **35+ age bucket** stopped on 15 October 2026
    (use 35-44, 45-54 and 55+).
  - Chunked media uploads use **`multipart-upload-v2`**; media can carry the
    **`ai_content_source`** self-declaration (August 2026).
  - Ad squad **`sub_request_warnings`** (September 2026) are returned as `_warnings`.
  - Async reports support HOUR granularity (September 2026) and stay downloadable for 7 days.

## Data the server keeps

| Data | Where | How long |
|---|---|---|
| Refresh token, client ID suffix, scope, created date | `~/.snapchat-ads-mcp/secrets/snapchat-ads-token.json` (0600, folder 0700) | Until `purge` or you delete it |
| Write requests, before-snapshots and responses (redacted) | `~/.snapchat-ads-mcp/logs/audit.jsonl` (0600, folder 0700) | 30 days by default (`SNAPCHAT_ADS_AUDIT_RETENTION_DAYS`) |
| Stats, report rows, entity reads | Memory only, returned to your MCP client | The length of the tool call |

Nothing else is written. There's no telemetry. Your MCP client and AI provider keep their
own copies of whatever the tools return.
