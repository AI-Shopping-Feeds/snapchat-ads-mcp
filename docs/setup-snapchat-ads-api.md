# Getting Snap Marketing API access

This walks through everything the server needs, in plain steps. It takes about 15 minutes
and there is no application or approval queue: Snap's Marketing API is self-service once you
accept its terms.

You need:

- A Snapchat **business account** in [Snap Business Manager](https://business.snapchat.com)
  with at least one ad account.
- Someone with the **Organization Admin** role, to create the OAuth app.
- The **Snapchat login** the server will act as. It needs access to the ad accounts you want
  to manage. Snap suggests a dedicated login your company keeps, so access doesn't stop when
  an employee leaves.

## 1. Pick the login the server will use

The server acts as one Snapchat user, with exactly that user's permissions. Snap roles
decide what it can do:

| Role | What the server can do with it |
|---|---|
| Organization `admin` | Everything in every ad account of the organisation |
| Organization `data_admin` | Reporting only, across all ad accounts (good for read-only use) |
| Ad account `general` | Campaigns, ad squads and ads in that ad account |
| Ad account `creative` | Creatives and media; read access to the rest |
| Ad account `audience` | Audience segments |
| Ad account `reports` | Read-only reporting |
| `agency_admin` / `agency_member` | Agency access to assigned client ad accounts |

Give the login the narrowest role that covers what you want the agent to do. Roles are set
in Business Manager → Members.

## 2. Create the OAuth app

1. Sign in to Ads Manager as an Organization Admin. Open the menu (top left) → **Business
   Dashboard** → **Business Details**.
2. The first time, click **+ OAuth App** and **accept the Snap Developer Terms and the Snap
   Business Tools Terms**. This activates API access. Read
   [docs/terms-and-data.md](terms-and-data.md) first.
3. Click **+ OAuth app**, give it a name (for example "Snapchat Ads MCP"), and under **Snap
   redirect URIs** enter:

   ```text
   http://localhost:8765/callback
   ```

   You can list up to 10 redirect URIs, one per line, and edit them later.
4. Click **Create OAuth app**. Copy the **Snap Client ID** and the **Snap Client Secret
   Key**. The secret is shown only once: store it in a password manager.

If the app dashboard is missing, the login you used isn't an Organization Admin. You can
also open `https://business.snapchat.com/<your organisation ID>/settings/business-details`
directly.

**If Business Manager won't accept the localhost address**, add an `https://` address on a
website you control instead (for example `https://www.example.com/snap-callback`; the page
doesn't need to exist), and use `--manual` in step 3.

## 3. Sign in once

Put the credentials somewhere the server reads them. The simplest is a file at
`~/.snapchat-ads-mcp/.env` (create the folder if needed; keep the file private):

```shell
SNAPCHAT_ADS_CLIENT_ID=your-client-id
SNAPCHAT_ADS_CLIENT_SECRET=your-client-secret
```

Then run:

```shell
uvx --from git+https://github.com/AI-Shopping-Feeds/snapchat-ads-mcp.git snapchat-ads-mcp auth
```

Your browser opens Snap's consent page. Sign in with the login from step 1 and approve. The
server receives the redirect on `localhost:8765`, swaps the one-time code for tokens, and
saves the **refresh token** to `~/.snapchat-ads-mcp/secrets/snapchat-ads-token.json` with
owner-only permissions. It never prints the token.

With an `https://` redirect URI instead:

```shell
uvx --from git+https://github.com/AI-Shopping-Feeds/snapchat-ads-mcp.git snapchat-ads-mcp auth \
  --manual --redirect-uri https://www.example.com/snap-callback
```

After approving, your browser lands on that address. Copy the whole address from the
address bar (it contains `code=` and `state=`) and paste it into the terminal. The server
checks the `state` matches the one it generated before using the code.

About the tokens:

- **Access tokens** last one hour. The server refreshes them automatically.
- **The refresh token doesn't expire**, but stops working if that Snapchat user loses access
  to the organisation, or removes the app. Run `auth` again if that happens.

Check the setup (no secrets are printed):

```shell
uvx --from git+https://github.com/AI-Shopping-Feeds/snapchat-ads-mcp.git snapchat-ads-mcp describe
```

## 4. Find your IDs

Snap IDs look like `8adc3db7-8148-4fbf-999c-8d2266369d74`.

- Once the server is connected, ask your agent to list your organisations:
  `snapchat_ads_list_organizations` returns each organisation with its ad accounts, their
  currency and timezone.
- In Ads Manager, the ad account ID is in the address bar and under ad account settings.

Set `SNAPCHAT_ADS_AD_ACCOUNT_ID` (and `SNAPCHAT_ADS_ORGANIZATION_ID` for catalogs, pixels
and funding sources) so tools use them by default. Every tool also takes them as arguments.

## 5. Optional: a folder for media uploads

To let the agent upload images and videos, create a folder for them and set
`SNAPCHAT_ADS_UPLOAD_DIR` to it. The server reads files only from that folder. Snap's
specs: 1080 × 1920 px; images PNG or JPG up to 5 MB; videos MP4 or MOV, at least 3 seconds,
up to 1 GB.

## Agencies

- Clients share their ad accounts with your organisation in Business Manager (or add your
  people as members). The server then sees them like your own ad accounts.
- Use **your own** OAuth app and a login inside your organisation. Snap's terms forbid
  sharing keys or tokens outside your organisation.
- Keep each client's data to work for that client. See
  [terms-and-data.md](terms-and-data.md#agencies-and-acting-for-clients).

## Revoking access

- The user: [accounts.snapchat.com](https://accounts.snapchat.com) → **Manage apps** → remove
  the app.
- The organisation: delete the OAuth app in Business Details. Its client ID and secret stop
  working at once and can't be restored.
- Locally: `snapchat-ads-mcp purge` deletes the stored token and the audit log.

## Limits

- Snap allows about 20 requests per second per app and 10 per access token. The server
  stays under 8 per second (`SNAPCHAT_ADS_MAX_RPS`) and waits and retries on HTTP 429.
- Stats refresh about every 15 minutes and are final about 48 hours after the end of a day
  in the ad account's timezone.

## Troubleshooting

| Problem | What to do |
|---|---|
| `SNAPCHAT_ADS_CLIENT_ID and SNAPCHAT_ADS_CLIENT_SECRET must be set` | Put them in `~/.snapchat-ads-mcp/.env`, `./.env` or the client config |
| `invalid_client` during `auth` | Wrong client ID or secret, or the OAuth app was deleted |
| `redirect_uri` mismatch | The address must match one of the app's Snap redirect URIs exactly, including the port and path |
| `Timed out waiting for the browser redirect` | Something else is using port 8765 (`auth --port 8766`, and register that URI), or use `--manual` |
| `Snap refused the token refresh` | The user lost access or removed the app; run `auth` again |
| Health check shows no organisations | The signed-in user isn't a member of the organisation, or hasn't accepted the invitation email |
| HTTP 403 on an ad account | The user's role doesn't cover it; see step 1 |
