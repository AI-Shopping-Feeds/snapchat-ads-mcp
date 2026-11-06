# Tools

**58 tools**, all prefixed `snapchat_ads_`, in 12 groups plus 5 meta tools that are always
registered. `SNAPCHAT_ADS_TOOL_GROUPS` picks groups; `SNAPCHAT_ADS_READ_ONLY=true` keeps only
the tools marked read-only.

Kinds: **read** changes nothing; **report** starts a Snap report job (changes nothing in the
account); **write** creates something; **update** changes something in place; **delete** is
permanent; **raw** can do anything. Every write goes through dry-run and the audit log.

Money in the Snap Marketing API is **micro-currency**: 1.00 in the ad account's currency is
1,000,000. Entity tools return the raw `*_micro` fields plus an `amounts` map in whole units;
stats rows get `<metric>_amount` columns. `snapchat_ads_set_budgets` and
`snapchat_ads_set_bids` take whole units and convert for you.

Confirm words:

- `DELETE`: every delete (Snap deletes can't be undone).
- `APPLY`: more than `SNAPCHAT_ADS_BULK_THRESHOLD` items (10); a bid or budget rise above
  `SNAPCHAT_ADS_MAX_INCREASE_PCT` (20%); a rise whose current value couldn't be read;
  removing a spend cap; values above `SNAPCHAT_ADS_MAX_BUDGET` / `SNAPCHAT_ADS_MAX_BID`;
  every raw write through `snapchat_ads_request`.

In dry-run nothing is refused or sent: the result shows what would be sent and which confirm
word a real run needs.

## Meta (always registered)

| Tool | Kind | What it does |
|---|---|---|
| `snapchat_ads_describe_server` | read (local) | Default ad account and organisation, safety settings, limits and paths |
| `snapchat_ads_health_check` | read | Refreshes the access token, lists organisations and ad accounts, checks the default ad account is visible |
| `snapchat_ads_audit_tail` | read (local) | Most recent audit log entries (writes and dry-run rehearsals) |
| `snapchat_ads_audit_lookup` | read (local) | One audit entry: request, response and before-snapshot |
| `snapchat_ads_set_dry_run` | local setting | Turns dry-run on or off for the session |

## accounts

| Tool | Kind | What it does |
|---|---|---|
| `snapchat_ads_get_me` | read | The signed-in Snapchat user (no email address) |
| `snapchat_ads_list_organizations` | read | Organisations with their ad accounts (currency, timezone, status) |
| `snapchat_ads_list_ad_accounts` | read | Ad accounts in an organisation |
| `snapchat_ads_get_ad_account` | read | One ad account, including its lifetime spend cap |
| `snapchat_ads_list_funding_sources` | read | Funding sources (credit lines, cards, coupons) |

## campaigns

| Tool | Kind | What it does |
|---|---|---|
| `snapchat_ads_list_campaigns` | read | Campaigns in an ad account; filter by IDs, status or name |
| `snapchat_ads_create_campaigns` | write | Creates campaigns, **PAUSED** unless an item sets status; uses `objective_v2_properties` |
| `snapchat_ads_update_campaigns` | update | JSON Patch per campaign (name, status, dates, budgets, spend cap...) with a before-snapshot |
| `snapchat_ads_delete_campaigns` | delete | Deletes campaigns; needs `DELETE` |

## ad_squads

| Tool | Kind | What it does |
|---|---|---|
| `snapchat_ads_list_ad_squads` | read | Ad squads in a campaign or ad account |
| `snapchat_ads_create_ad_squads` | write | Creates ad squads under a campaign, **PAUSED** by default; Snap's `sub_request_warnings` come back as `_warnings` |
| `snapchat_ads_update_ad_squads` | update | JSON Patch per ad squad (targeting, bid, budgets, schedule, placement...) |
| `snapchat_ads_delete_ad_squads` | delete | Deletes ad squads; needs `DELETE` |

## ads

| Tool | Kind | What it does |
|---|---|---|
| `snapchat_ads_list_ads` | read | Ads in an ad squad, campaign or ad account; filter by review status |
| `snapchat_ads_create_ads` | write | Creates ads (creative + ad squad), **PAUSED** by default |
| `snapchat_ads_update_ads` | update | JSON Patch per ad (name, status, tracking URLs) |
| `snapchat_ads_delete_ads` | delete | Deletes ads; needs `DELETE` |

## bulk

| Tool | Kind | What it does |
|---|---|---|
| `snapchat_ads_set_status` | update | Pauses or activates many campaigns, ad squads or ads, with progress |
| `snapchat_ads_set_budgets` | update | Sets daily or lifetime budgets in whole currency units, or moves them by a percentage |
| `snapchat_ads_set_bids` | update | Sets ad squad bids in whole currency units, or moves them by a percentage; flags AUTO_BID squads |

## creatives

| Tool | Kind | What it does |
|---|---|---|
| `snapchat_ads_list_creatives` | read | Creatives in an ad account; filter by type or name |
| `snapchat_ads_create_creatives` | write | Creates creatives (Snap Ad, web view, app install, deep link, story, collection...) |
| `snapchat_ads_update_creatives` | update | JSON Patch per creative (headline, CTA, brand name...) |
| `snapchat_ads_get_creative_preview` | read | Snap's preview data for a creative |
| `snapchat_ads_list_media` | read | Uploaded images, videos and playables, with `media_status` |
| `snapchat_ads_upload_media` | write | Uploads a file from `SNAPCHAT_ADS_UPLOAD_DIR` (single request up to 32 MB, 32 MB parts up to 1 GB); optional AI-content self-declaration |

Snap's API has no delete for creatives and no upload-by-URL: download a file into the upload
folder first.

## audiences

| Tool | Kind | What it does |
|---|---|---|
| `snapchat_ads_list_segments` | read | Audience segments with size, upload and targetable status |
| `snapchat_ads_create_segments` | write | Creates empty customer lists or lookalikes (never uploads identifiers) |
| `snapchat_ads_update_segments` | update | Renames segments or changes description or retention (read, merge, PUT) |
| `snapchat_ads_delete_segments` | delete | Deletes segments; needs `DELETE` |

## targeting

| Tool | Kind | What it does |
|---|---|---|
| `snapchat_ads_get_targeting_options` | read | IDs and names for countries, regions, metros, postcodes, demographics, interests, devices; what a country supports |
| `snapchat_ads_estimate_audience_size` | read | Reach range for an ad squad or a targeting spec (`audience_size_v2`) |
| `snapchat_ads_get_bid_estimate` | read | Suggested bid range for an ad squad or goal + targeting |
| `snapchat_ads_get_bid_recommendation` | read | Recommended TARGET_COST bid and daily budget for a pixel and goal |
| `snapchat_ads_check_optimization_eligibility` | read | Goals and conversion windows a pixel or Snap App ID can use |

## pixels

| Tool | Kind | What it does |
|---|---|---|
| `snapchat_ads_list_pixels` | read | Snap Pixels for an ad account or organisation |
| `snapchat_ads_get_pixel_domains` | read | Domains that fired a pixel in the last 7 days |
| `snapchat_ads_get_pixel_stats` | read | Pixel events for one domain (up to 28 days back) |
| `snapchat_ads_list_snap_apps` | read | Snap App IDs for app campaigns |

## catalogs

| Tool | Kind | What it does |
|---|---|---|
| `snapchat_ads_list_catalogs` | read | Product catalogs in an organisation |
| `snapchat_ads_list_product_feeds` | read | A catalog's feeds |
| `snapchat_ads_list_feed_uploads` | read | A feed's recent uploads with counts and errors |
| `snapchat_ads_list_product_sets` | read | A catalog's product sets and filters |
| `snapchat_ads_search_products` | read | Products matching a filter, plus the total count |
| `snapchat_ads_create_product_sets` | write | Creates product sets from filters |

## reporting

| Tool | Kind | What it does |
|---|---|---|
| `snapchat_ads_get_stats` | read | Synchronous stats for an ad account, campaign, ad squad, ad, creative or media: TOTAL, DAY, HOUR or LIFETIME, breakdowns, insights (`report_dimension`), attribution windows; flat rows |
| `snapchat_ads_create_async_report` | report | Starts an async CSV report |
| `snapchat_ads_get_async_report` | read | Status of an async report |
| `snapchat_ads_download_async_report` | read | Downloads a finished report and returns its rows (in memory, size-capped) |
| `snapchat_ads_run_report` | report | Starts, polls (with progress) and downloads an async report in one call |
| `snapchat_ads_get_change_log` | read | Snap's change history for a campaign, ad squad, ad or creative (editors by user ID, no emails) |

Snap rejects synchronous stats responses that are too large (error `E9001`); use
`snapchat_ads_run_report` for wide breakdowns or long ranges. Synchronous HOUR stats cover at
most 7 days and DAY stats 31 days; async reports have no such cap.

## request

| Tool | Kind | What it does |
|---|---|---|
| `snapchat_ads_read_request` | read | GET, or a read-only POST (fetch by IDs, estimates, searches), on any `/v1/` path |
| `snapchat_ads_request` | raw | Any method on any `/v1/` path on adsapi.snapchat.com; writes need `APPLY` |
