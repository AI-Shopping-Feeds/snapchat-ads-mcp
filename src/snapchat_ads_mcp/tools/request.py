"""Escape hatches: call any Snap Marketing API v1 endpoint on adsapi.snapchat.com."""

from __future__ import annotations

import re
from typing import Any

from .. import safety
from ..client import SnapchatAdsClient

# POST endpoints that only read: fetch-by-IDs, estimates, forecasts and searches.
_READ_POST = re.compile(
    r"(/get_[a-z_]+_by_ids$|/audience_size(_v2)?$|/bid_estimate$|/products/search$"
    r"|/product_search$|/facets$|/flights/search$|/hotels/search$|/targeting_insights$"
    r"|/ad_squad_outcome_estimates_v2$|/reserved_forecasting$)",
    re.IGNORECASE,
)
_PATH_RE = re.compile(r"^/v1/[A-Za-z0-9_\-/.:]+$")
JSON_PATCH = "application/json-patch+json"


def classify(method: str, path: str) -> tuple[str, str, bool]:
    """Validate method and path; return (method, path, is_read)."""
    method = method.upper()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise ValueError("method must be GET, POST, PUT, PATCH or DELETE.")
    path = path.strip()
    if "?" in path:
        raise ValueError("Put query parameters in `query`, not in the path.")
    if not _PATH_RE.match(path) or ".." in path or "//" in path:
        raise ValueError(
            "path must be a Snap Marketing API v1 path on adsapi.snapchat.com, e.g. "
            "'/v1/adaccounts/<id>/campaigns'."
        )
    is_read = method == "GET" or (method == "POST" and bool(_READ_POST.search(path)))
    return method, path, is_read


def register(mcp, client: SnapchatAdsClient) -> None:
    @mcp.tool()
    def snapchat_ads_read_request(
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        body: Any | None = None,
    ) -> Any:
        """Read from any Snap Marketing API v1 endpoint the other tools don't cover.

        Only GET, and POSTs that just read (get_*_by_ids, audience_size,
        bid_estimate, product and facet searches, forecasts), are allowed; use
        snapchat_ads_request for writes. path starts with '/v1/', e.g.
        '/v1/adaccounts/<id>/invoices'. Money fields are micro-currency.
        """
        method, path, is_read = classify(method, path)
        if not is_read:
            raise ValueError(f"{method} {path} may change the account; use snapchat_ads_request.")
        return client.request(method, path, params=query, json_body=body, read_only=True)

    @mcp.tool()
    def snapchat_ads_request(
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        body: Any | None = None,
        confirm: str = "",
    ) -> Any:
        """Call any Snap Marketing API v1 endpoint the other tools don't cover.

        path starts with '/v1/' and is called on https://adsapi.snapchat.com only.
        PATCH bodies are sent as JSON Patch (a list of {"op", "path", "value"}).
        Remember PUT replaces the whole entity: omitted fields reset to defaults.
        GET and read-only POSTs are reads. Every other call is a write: it is
        audited, follows dry-run, and needs confirm='APPLY' because this tool
        can't check what it changes.
        """
        method, path, is_read = classify(method, path)
        if not is_read:
            decision = safety.Decision(
                required=safety.APPLY,
                reasons=["raw write through snapchat_ads_request; its effect isn't checked"],
            )
            refused = safety.refusal(
                client.config,
                decision,
                confirm,
                preview={"method": method, "path": path, "query": query, "body": body},
            )
            if refused:
                return refused
        return client.request(
            method,
            path,
            params=query,
            json_body=body,
            content_type=JSON_PATCH if method == "PATCH" else None,
            read_only=is_read,
            op=f"request {method} {path}",
        )
