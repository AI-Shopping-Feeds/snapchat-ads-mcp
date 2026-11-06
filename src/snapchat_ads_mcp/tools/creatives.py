"""Creatives and media: the visual part of an ad.

Snap's API has no upload-by-URL: media files are uploaded as multipart form
data. `snapchat_ads_upload_media` reads files only from SNAPCHAT_ADS_UPLOAD_DIR,
sends files up to 32 MB in one request and larger ones (up to 1 GB) in 32 MB
parts, and never holds more than one part in memory.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import Context

from ..client import SnapchatAdsClient, check_id, unwrap
from ._common import (
    create_description,
    create_entities,
    fetch_by_ids,
    filter_entities,
    ids_to_strings,
    register_update_delete,
)
from ._progress import report, run_blocking
from ._specs import CREATIVE

SINGLE_UPLOAD_MAX = 32 * 1024 * 1024
PART_SIZE = 32 * 1024 * 1024
MAX_PARTS = 32
MEDIA_TYPES = {
    ".jpg": ("IMAGE", "image/jpeg"),
    ".jpeg": ("IMAGE", "image/jpeg"),
    ".png": ("IMAGE", "image/png"),
    ".mp4": ("VIDEO", "video/mp4"),
    ".mov": ("VIDEO", "video/quicktime"),
    ".zip": ("PLAYABLE", "application/zip"),
}


def _form(**fields: str) -> dict[str, Any]:
    """Plain multipart/form-data fields (Snap's chunked-upload calls expect multipart)."""
    return {k: (None, v) for k, v in fields.items()}


def resolve_upload(upload_dir: Path | None, source: str) -> Path:
    """Resolve a local file and make sure it sits inside SNAPCHAT_ADS_UPLOAD_DIR."""
    if upload_dir is None:
        raise PermissionError(
            "Uploads are off: set SNAPCHAT_ADS_UPLOAD_DIR to the folder media may be uploaded "
            "from, and put the file there."
        )
    if "://" in source:
        raise ValueError(
            "Snap's API doesn't upload media from a URL. Download the file into "
            "SNAPCHAT_ADS_UPLOAD_DIR first and pass its path."
        )
    root = upload_dir.resolve()
    path = Path(source).expanduser()
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to(root):
        raise PermissionError(f"{path} is outside SNAPCHAT_ADS_UPLOAD_DIR ({root}).")
    if not path.is_file():
        raise FileNotFoundError(f"No such file: {path}")
    return path


def register(mcp, client: SnapchatAdsClient) -> None:
    @mcp.tool()
    async def snapchat_ads_list_creatives(
        ad_account_id: str | None = None,
        ids: list[str] | None = None,
        creative_type: str | None = None,
        name_contains: str | None = None,
        max_results: int = 500,
    ) -> dict[str, Any]:
        """List creatives in an ad account, or fetch some by ids (up to 2,000).

        creative_type filters by type, e.g. SNAP_AD, WEB_VIEW, APP_INSTALL,
        DEEP_LINK, COMPOSITE (story), COLLECTION, LEAD_GENERATION.
        """
        aid = client.resolve_ad_account(ad_account_id)
        id_list = ids_to_strings(ids, "creative id")
        if id_list:
            items = await run_blocking(fetch_by_ids, client, CREATIVE, aid, id_list)
            truncated = False
        else:
            params = {"type": creative_type.upper()} if creative_type else None
            items, truncated = await run_blocking(
                client.paginate,
                f"/v1/adaccounts/{aid}/creatives",
                params,
                key="creatives",
                max_results=max_results,
            )
        if creative_type:
            items = [c for c in items if str(c.get("type", "")).upper() == creative_type.upper()]
        items = filter_entities(items, None, name_contains)
        return {"creatives": items, "count": len(items), "truncated": truncated}

    @mcp.tool(description=create_description(CREATIVE, "ad account"))
    async def snapchat_ads_create_creatives(
        items: list[dict[str, Any]],
        ad_account_id: str | None = None,
        confirm: str = "",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        aid = client.resolve_ad_account(ad_account_id)
        return await create_entities(
            client, CREATIVE, aid, items, confirm=confirm, ad_account_id=aid, ctx=ctx
        )

    register_update_delete(mcp, client, CREATIVE)

    @mcp.tool()
    def snapchat_ads_get_creative_preview(creative_id: str) -> dict[str, Any]:
        """Get Snap's preview data for a creative: media links, brand, CTA and attachment details."""
        cid = check_id(creative_id, "creative_id")
        return client.request("GET", f"/v1/creatives/{cid}/creative_preview")

    @mcp.tool()
    async def snapchat_ads_list_media(
        ad_account_id: str | None = None,
        ids: list[str] | None = None,
        max_results: int = 500,
    ) -> dict[str, Any]:
        """List media (uploaded images, videos, playables) in an ad account, or fetch some by ids.

        media_status READY means the file finished uploading and can be used in a creative.
        """
        aid = client.resolve_ad_account(ad_account_id)
        id_list = ids_to_strings(ids, "media id")
        if id_list:
            items = await run_blocking(client.get_by_ids, aid, "media", id_list)
            truncated = False
        else:
            items, truncated = await run_blocking(
                client.paginate,
                f"/v1/adaccounts/{aid}/media",
                None,
                key="media",
                max_results=max_results,
            )
        return {"media": items, "count": len(items), "truncated": truncated}

    @mcp.tool()
    async def snapchat_ads_upload_media(
        source: str,
        name: str | None = None,
        media_type: Literal["IMAGE", "VIDEO", "PLAYABLE"] | None = None,
        ai_generated: bool = False,
        ad_account_id: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Upload an image, video or playable from SNAPCHAT_ADS_UPLOAD_DIR and return its media ID.

        source: a path inside SNAPCHAT_ADS_UPLOAD_DIR (absolute or relative to
        it). Snap has no upload-by-URL. Type comes from the extension (.jpg,
        .png -> IMAGE; .mp4, .mov -> VIDEO; .zip -> PLAYABLE) unless media_type
        is set. Files over 32 MB go up in parts (max 1 GB) with progress.
        Set ai_generated=true for AI-generated or AI-modified content (Snap's
        ai_content_source self-declaration). Top Snap specs: 1080x1920, video
        mp4/mov of at least 3 s, images PNG/JPG up to 5 MB.
        """
        aid = client.resolve_ad_account(ad_account_id)
        path = await run_blocking(resolve_upload, client.config.upload_dir, source)
        size = path.stat().st_size
        if size == 0:
            raise ValueError(f"{path.name} is empty.")
        if size > PART_SIZE * MAX_PARTS:
            raise ValueError(f"{path.name} is over Snap's 1 GB media limit.")
        detected = MEDIA_TYPES.get(path.suffix.lower())
        mtype = (media_type or (detected[0] if detected else "")).upper()
        if not mtype:
            raise ValueError("Unknown file type; pass media_type (IMAGE, VIDEO or PLAYABLE).")
        mime = detected[1] if detected else "application/octet-stream"
        media: dict[str, Any] = {
            "name": name or path.stem,
            "type": mtype,
            "ad_account_id": aid,
        }
        if ai_generated:
            media["ai_content_source"] = "USER_AI_GEN"

        created = await run_blocking(
            client.request,
            "POST",
            f"/v1/adaccounts/{aid}/media",
            json_body={"media": [media]},
            op="create_media",
            ad_account_id=aid,
        )
        if created.get("_dry_run"):
            return {
                **created,
                "file": path.name,
                "size_bytes": size,
                "upload": "single" if size <= SINGLE_UPLOAD_MAX else "chunked",
            }
        entities = unwrap(created, "media")
        if not entities or not entities[0].get("id"):
            raise RuntimeError(f"Snap didn't return a media ID: {created}")
        media_id = check_id(entities[0]["id"], "media id")

        if size <= SINGLE_UPLOAD_MAX:

            def _single() -> Any:
                with path.open("rb") as fh:
                    return client.request(
                        "POST",
                        f"/v1/media/{media_id}/upload",
                        files={"file": (path.name, fh, mime)},
                        audit_body={"file_name": path.name, "size_bytes": size},
                        op="upload_media",
                        ad_account_id=aid,
                    )

            await report(ctx, 1, 2, f"Created media {media_id}; uploading {path.name}")
            out = await run_blocking(_single)
            await report(ctx, 2, 2, "Upload finished")
            return {"media_id": media_id, "upload": "single", "result": out.get("result", out)}

        parts = math.ceil(size / PART_SIZE)
        init = await run_blocking(
            client.request,
            "POST",
            f"/v1/media/{media_id}/multipart-upload-v2?action=INIT",
            files=_form(file_name=path.name, file_size=str(size), number_of_parts=str(parts)),
            audit_body={"file_name": path.name, "size_bytes": size, "number_of_parts": parts},
            op="upload_media_init",
            ad_account_id=aid,
        )
        upload_id = str(init.get("upload_id") or "")
        add_path = str(init.get("add_path") or "")
        finalize_path = str(init.get("finalize_path") or "")
        for p in (add_path, finalize_path):
            if not p.startswith("/") or f"/media/{media_id}/" not in p or "://" in p:
                raise RuntimeError(f"Unexpected chunked-upload path from Snap: {p!r}")
        if not upload_id:
            raise RuntimeError("Snap returned no upload_id for the chunked upload.")

        def _part(number: int) -> Any:
            with path.open("rb") as fh:
                fh.seek((number - 1) * PART_SIZE)
                chunk = fh.read(PART_SIZE)
            return client.request(
                "POST",
                add_path,
                data={"upload_id": upload_id, "part_number": str(number)},
                files={"file": (f"{path.name}.part{number}", chunk, "application/octet-stream")},
                audit_body={
                    "upload_id": upload_id,
                    "part_number": number,
                    "size_bytes": len(chunk),
                },
                op="upload_media_part",
                ad_account_id=aid,
            )

        for number in range(1, parts + 1):
            await run_blocking(_part, number)
            await report(ctx, number, parts + 1, f"Uploaded part {number} of {parts}")
        final = await run_blocking(
            client.request,
            "POST",
            finalize_path,
            files=_form(upload_id=upload_id),
            audit_body={"upload_id": upload_id},
            op="upload_media_finalize",
            ad_account_id=aid,
        )
        await report(ctx, parts + 1, parts + 1, "Upload finished")
        return {
            "media_id": media_id,
            "upload": "chunked",
            "parts": parts,
            "result": final.get("result", final),
        }
