"""Product catalogs, feeds and product sets for Dynamic Product Ads.

Reads cover catalogs, feeds, feed upload history (to diagnose feed errors),
product sets and product search. The one write is creating product sets.
"""

from __future__ import annotations

from typing import Any

from .. import safety
from ..client import SnapchatAdsClient, check_id, unwrap
from ._common import check_items

PRODUCT_SET_BATCH = 30


def register(mcp, client: SnapchatAdsClient) -> None:
    @mcp.tool()
    def snapchat_ads_list_catalogs(organization_id: str | None = None) -> dict[str, Any]:
        """List an organisation's product catalogs (used for Dynamic Product Ads)."""
        oid = client.resolve_organization(organization_id)
        items, truncated = client.paginate(
            f"/v1/organizations/{oid}/catalogs", None, key="catalogs", max_results=1000
        )
        return {"catalogs": items, "count": len(items), "truncated": truncated}

    @mcp.tool()
    def snapchat_ads_list_product_feeds(catalog_id: str) -> dict[str, Any]:
        """List a catalog's product feeds: source URL schedule, status and last upload."""
        cid = check_id(catalog_id, "catalog_id")
        items, truncated = client.paginate(
            f"/v1/catalogs/{cid}/product_feeds", None, key="product_feeds", max_results=1000
        )
        return {"product_feeds": items, "count": len(items), "truncated": truncated}

    @mcp.tool()
    def snapchat_ads_list_feed_uploads(
        product_feed_id: str, max_results: int = 50
    ) -> dict[str, Any]:
        """List a product feed's recent uploads (newest 200 at most) with item counts and errors.

        Use it to find out why products are missing or rejected.
        """
        fid = check_id(product_feed_id, "product_feed_id")
        out = client.request("GET", f"/v1/product_feeds/{fid}/feed_uploads")
        items = unwrap(out, "feed_uploads")[: max(1, max_results)]
        return {"feed_uploads": items, "count": len(items)}

    @mcp.tool()
    def snapchat_ads_list_product_sets(catalog_id: str) -> dict[str, Any]:
        """List a catalog's product sets and their filters."""
        cid = check_id(catalog_id, "catalog_id")
        items, truncated = client.paginate(
            f"/v1/catalogs/{cid}/product_sets", None, key="product_sets", max_results=1000
        )
        return {"product_sets": items, "count": len(items), "truncated": truncated}

    @mcp.tool()
    def snapchat_ads_search_products(
        catalog_id: str,
        filter: dict[str, Any] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Search a catalog's products, e.g. to preview what a product set filter would match.

        filter uses Snap's product filter format, e.g. {"AVAILABILITY": {"EQ": "IN_STOCK"}}
        or {"AND": [{"BRAND": {"EQ": "Acme"}}, {"PRICE": {"LT": 50}}]}. Operators: EQ,
        NEQ, GT, GTE, LT, LTE, CONTAINS, I_CONTAINS, STARTS_WITH, IS_ANY and more.
        Returns one page (limit 50-1000) plus the total match count.
        """
        cid = check_id(catalog_id, "catalog_id")
        body: dict[str, Any] = {"limit": max(50, min(int(limit), 1000))}
        if filter:
            body["filter"] = filter
        out = client.request(
            "POST", f"/v1/catalogs/{cid}/products/search", json_body=body, read_only=True
        )
        items = unwrap(out, "products")
        return {
            "products": items,
            "count": len(items),
            "summary": out.get("summary"),
            "more": bool((out.get("paging") or {}).get("next_link")),
        }

    @mcp.tool()
    def snapchat_ads_create_product_sets(
        catalog_id: str,
        items: list[dict[str, Any]],
        confirm: str = "",
    ) -> dict[str, Any]:
        """Create product sets in a catalog (up to 30 per call). Changes the live account.

        items: [{"name": "In stock trainers", "filter": {"AND": [{"AVAILABILITY":
        {"EQ": "IN_STOCK"}}, {"PRODUCT_TYPE": {"I_CONTAINS": "trainers"}}]}}].
        Preview the filter with snapchat_ads_search_products first. Name 3-255 characters.
        """
        cid = check_id(catalog_id, "catalog_id")
        check_items(items, "items", max_items=PRODUCT_SET_BATCH)
        decision = safety.assess(client.config, count=len(items))
        refused = safety.refusal(client.config, decision, confirm, preview={"product_sets": items})
        if refused:
            return refused
        out = client.request(
            "POST",
            f"/v1/catalogs/{cid}/product_sets",
            json_body={"product_sets": items},
            op="create_product_sets",
        )
        result: dict[str, Any] = {
            "product_sets": unwrap(out, "product_sets"),
            "errors": out.get("sub_request_errors") or [],
            "audit_id": out.get("audit_id"),
        }
        if out.get("_dry_run"):
            result.update({"_dry_run": True, "would_send": {"product_sets": items}})
        return safety.annotate(result, decision)
