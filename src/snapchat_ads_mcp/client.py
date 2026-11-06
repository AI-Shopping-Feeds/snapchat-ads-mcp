"""Thin HTTP client for the Snap Marketing API v1.

One request choke point (`SnapchatAdsClient.request`) adds the bearer token,
throttles to stay under Snap's per-token rate limit, retries throttled and
failed requests with backoff (honouring Retry-After), and sends every write
through dry-run and the audit log. It only talks to adsapi.snapchat.com, and,
for finished async report files, Snap's report download host.
"""

from __future__ import annotations

import csv
import io
import json
import random
import re
import threading
import time
from typing import Any
from urllib.parse import parse_qsl, urlparse

import httpx

from . import __version__
from ._logging import get_logger
from .audit import AuditLog
from .auth import Auth, redact
from .config import API_HOST, Config

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
IDEMPOTENT_METHODS = {"GET", "PUT", "PATCH", "DELETE"}
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 5
MAX_BACKOFF = 120.0  # cap on honouring a very long Retry-After
# Async report files are served from Snap's data-transfer host.
DOWNLOAD_HOST_SUFFIXES = (".snapads.com", ".snapchat.com")
JSON_PATCH = "application/json-patch+json"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-:.]{0,199}$")
_WRAPPER_KEYS = {"sub_request_status", "sub_request_error_reason", "sub_request_warnings"}

logger = get_logger("client")


class SnapchatAdsAPIError(Exception):
    def __init__(self, status: int, body: Any, message: str = ""):
        self.status = status
        self.body = redact(body)
        super().__init__(message or f"Snap Marketing API error {status}: {_summary(self.body)}")


def _summary(body: Any) -> str:
    if isinstance(body, dict):
        keep = {
            k: body[k]
            for k in (
                "request_status",
                "request_id",
                "error_code",
                "display_message",
                "debug_message",
                "error",
                "error_description",
                "_raw",
            )
            if k in body
        }
        errors = sub_request_errors(body)
        if errors:
            keep["sub_request_errors"] = errors[:10]
        if keep:
            return json.dumps(keep, ensure_ascii=False, default=str)[:2000]
    return str(body)[:2000]


def check_id(value: Any, what: str = "id") -> str:
    """Validate an ID before it goes into a URL path (no slashes, dots-only or queries)."""
    text = str(value).strip() if value is not None else ""
    if not text or not _ID_RE.match(text) or ".." in text:
        raise ValueError(f"{what} must be a Snap ID (letters, digits, '-'), got {text!r}.")
    return text


def sub_request_errors(payload: Any) -> list[dict[str, Any]]:
    """Collect per-item errors from a Snap response ({"campaigns": [{sub_request_status: ...}]})."""
    out: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return out
    for key, value in payload.items():
        if not isinstance(value, list):
            continue
        for i, el in enumerate(value):
            if isinstance(el, dict) and str(el.get("sub_request_status", "")).upper() == "ERROR":
                out.append(
                    {
                        "collection": key,
                        "index": i,
                        "reason": el.get("sub_request_error_reason"),
                    }
                )
    return out


def unwrap(payload: Any, key: str | None = None) -> list[dict[str, Any]]:
    """Return the entities from a Snap response, without the sub_request wrappers.

    Snap wraps each entity, e.g. {"campaigns": [{"sub_request_status": "SUCCESS",
    "campaign": {...}}]}. Items with an ERROR status are skipped (see
    `sub_request_errors`).
    """
    if not isinstance(payload, dict):
        return []
    lists = (
        [payload.get(key)]
        if key
        else [
            v
            for k, v in payload.items()
            if isinstance(v, list)
            and k not in {"paging", "sub_request_errors"}
            and not k.startswith("_")
        ]
    )
    out: list[dict[str, Any]] = []
    for value in lists:
        if not isinstance(value, list):
            continue
        for el in value:
            if not isinstance(el, dict):
                continue
            if str(el.get("sub_request_status", "")).upper() == "ERROR":
                continue
            inner = [v for k, v in el.items() if k not in _WRAPPER_KEYS and isinstance(v, dict)]
            if len(inner) == 1 and "sub_request_status" in el:
                entity = dict(inner[0])
                if el.get("sub_request_warnings"):
                    entity["_warnings"] = el["sub_request_warnings"]
                out.append(entity)
            elif "sub_request_status" not in el:
                out.append(el)
    return out


class SnapchatAdsClient:
    """HTTP wrapper over the Snap Marketing API with dry-run, audit and retries."""

    def __init__(self, config: Config, auth: Auth, audit: AuditLog):
        self.config = config
        self.auth = auth
        self.audit = audit
        self._http = httpx.Client(
            timeout=config.timeout,
            headers={"User-Agent": f"snapchat-ads-mcp/{__version__}"},
            follow_redirects=False,
        )
        self._throttle_lock = threading.Lock()
        self._next_slot = 0.0

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> SnapchatAdsClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def base_url(self) -> str:
        return API_HOST

    # ------------------------------------------------------------- scoping

    def resolve_ad_account(self, ad_account_id: str | None) -> str:
        aid = (ad_account_id or "").strip() or self.config.ad_account_id
        if not aid:
            raise ValueError(
                "No ad_account_id. Pass ad_account_id (see snapchat_ads_list_ad_accounts) "
                "or set SNAPCHAT_ADS_AD_ACCOUNT_ID."
            )
        return check_id(aid, "ad_account_id")

    def resolve_organization(self, organization_id: str | None) -> str:
        oid = (organization_id or "").strip() or self.config.organization_id
        if not oid:
            raise ValueError(
                "No organization_id. Pass organization_id (see "
                "snapchat_ads_list_organizations) or set SNAPCHAT_ADS_ORGANIZATION_ID."
            )
        return check_id(oid, "organization_id")

    # ------------------------------------------------------------- requests

    def _throttle(self) -> None:
        if self.config.max_rps <= 0:
            return
        interval = 1.0 / self.config.max_rps
        with self._throttle_lock:
            now = time.monotonic()
            wait = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + interval
        if wait > 0:
            time.sleep(wait)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        content_type: str | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        audit_body: Any | None = None,
        op: str | None = None,
        before: Any | None = None,
        read_only: bool = False,
        ad_account_id: str | None = None,
    ) -> Any:
        """Perform one API request and return parsed JSON ({} for an empty body).

        path: relative to https://adsapi.snapchat.com, starting with '/'.
        read_only: set True for POST endpoints that don't change anything
            (get_*_by_ids, estimates, searches). They then bypass dry-run and
            are not written to the audit log.
        data/files: form fields and files for multipart uploads.
        audit_body: what to record in the audit log instead of the body (uploads).
        """
        method = method.upper()
        if not path.startswith("/") or "://" in path or ".." in path or "\\" in path:
            raise ValueError("path must be relative to https://adsapi.snapchat.com, e.g. '/v1/me'.")
        url = f"{self.base_url}{path}"
        is_write = method in WRITE_METHODS and not read_only
        recorded_body = audit_body if audit_body is not None else json_body

        if is_write and self.config.dry_run:
            audit_id = self.audit.record(
                op=op or f"{method} {path}",
                resource=path,
                method=method,
                url=url,
                ad_account_id=ad_account_id,
                request_body=recorded_body,
                dry_run=True,
                before=before,
            )
            logger.info("dry-run %s %s (audit=%s)", method, path, audit_id)
            return {
                "_dry_run": True,
                "method": method,
                "url": url,
                "body": recorded_body,
                "audit_id": audit_id,
            }

        retry_5xx = method in IDEMPOTENT_METHODS or read_only
        last_exc: Exception | None = None
        refreshed = False
        attempt = 0
        while attempt < MAX_ATTEMPTS:
            self._throttle()
            headers = {"Authorization": f"Bearer {self.auth.access_token()}"}
            content: str | None = None
            if json_body is not None:
                headers["Content-Type"] = content_type or "application/json"
                content = json.dumps(json_body)
            headers["Accept"] = "application/json"
            try:
                resp = self._http.request(
                    method,
                    url,
                    params=params,
                    content=content,
                    data=data,
                    files=files,
                    headers=headers,
                )
            except httpx.RequestError as e:
                last_exc = e
                not_sent = isinstance(e, httpx.ConnectError | httpx.ConnectTimeout)
                if not (retry_5xx or not_sent) or attempt >= MAX_ATTEMPTS - 1:
                    raise SnapchatAdsAPIError(
                        0,
                        redact(str(e)),
                        f"Network error on {method} {path}: {redact(str(e))}. A write may or "
                        "may not have been applied; check before retrying.",
                    ) from e
                logger.warning("transport error attempt=%d %s %s: %s", attempt + 1, method, path, e)
                self._sleep_backoff(attempt)
                attempt += 1
                if files:
                    _rewind(files)
                continue

            if resp.status_code == 401 and not refreshed:
                # The cached access token may have expired early; refresh once.
                refreshed = True
                self.auth.invalidate()
                if files:
                    _rewind(files)
                continue

            retryable = resp.status_code == 429 or (
                resp.status_code in RETRYABLE_STATUSES and retry_5xx
            )
            if retryable and attempt < MAX_ATTEMPTS - 1:
                logger.warning(
                    "retryable status=%d attempt=%d %s %s",
                    resp.status_code,
                    attempt + 1,
                    method,
                    path,
                )
                self._sleep_backoff(attempt, resp)
                attempt += 1
                if files:
                    _rewind(files)
                continue

            payload: Any = self._safe_json(resp)
            failed = not (200 <= resp.status_code < 300) or (
                isinstance(payload, dict)
                and str(payload.get("request_status", "")).upper() == "ERROR"
            )

            if failed:
                if is_write:
                    self.audit.record(
                        op=op or f"{method} {path}",
                        resource=path,
                        method=method,
                        url=url,
                        ad_account_id=ad_account_id,
                        request_body=recorded_body,
                        response_status=resp.status_code,
                        response_body=payload,
                        before=before,
                        error=f"HTTP {resp.status_code}",
                    )
                logger.error(
                    "api error %d %s %s: %s",
                    resp.status_code,
                    method,
                    path,
                    _summary(redact(payload)),
                )
                raise SnapchatAdsAPIError(resp.status_code, payload)

            errors = sub_request_errors(payload)
            if is_write:
                audit_id = self.audit.record(
                    op=op or f"{method} {path}",
                    resource=path,
                    method=method,
                    url=url,
                    ad_account_id=ad_account_id,
                    request_body=recorded_body,
                    response_status=resp.status_code,
                    response_body=payload,
                    before=before,
                    error="partial failure" if errors else None,
                )
                logger.info(
                    "write %s %s -> %d (audit=%s)", method, path, resp.status_code, audit_id
                )
                payload = (
                    {**payload, "audit_id": audit_id}
                    if isinstance(payload, dict)
                    else {"result": payload, "audit_id": audit_id}
                )
            else:
                logger.debug("read  %s %s -> %d", method, path, resp.status_code)
            if errors and isinstance(payload, dict):
                payload = {**payload, "sub_request_errors": errors}
            return payload

        raise SnapchatAdsAPIError(0, str(last_exc) if last_exc else "exhausted retries")

    # ------------------------------------------------------------- helpers

    def paginate(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        key: str | None = None,
        max_results: int = 1000,
    ) -> tuple[list[dict[str, Any]], bool]:
        """GET a list endpoint and follow paging.next_link. Returns (entities, truncated)."""
        max_results = max(1, max_results)
        query = dict(params or {})
        query["limit"] = max(50, min(self.config.page_size, 1000, max_results))
        items: list[dict[str, Any]] = []
        next_path: str | None = path
        while next_path:
            payload = self.request("GET", next_path, params=query)
            items.extend(unwrap(payload, key))
            paging = payload.get("paging") if isinstance(payload, dict) else None
            link = paging.get("next_link") if isinstance(paging, dict) else None
            if len(items) >= max_results:
                return items[:max_results], bool(link) or len(items) > max_results
            next_path, query = self.next_page(link)
        return items, False

    def next_page(self, link: Any) -> tuple[str | None, dict[str, Any]]:
        if not link or not isinstance(link, str):
            return None, {}
        parsed = urlparse(link)
        if parsed.scheme != "https" or f"https://{parsed.netloc}" != self.base_url:
            logger.warning("ignoring next_link on an unexpected host: %s", parsed.netloc)
            return None, {}
        return parsed.path, dict(parse_qsl(parsed.query, keep_blank_values=True))

    def get_entities(
        self, path: str, key: str | None = None, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """GET one entity endpoint and return its unwrapped entities."""
        return unwrap(self.request("GET", path, params=params), key)

    def get_by_ids(
        self, ad_account_id: str, collection: str, ids: list[str]
    ) -> list[dict[str, Any]]:
        """POST /v1/adaccounts/{id}/get_{collection}_by_ids for up to 2,000 entities."""
        out: list[dict[str, Any]] = []
        for start in range(0, len(ids), 2000):
            chunk = ids[start : start + 2000]
            payload = self.request(
                "POST",
                f"/v1/adaccounts/{ad_account_id}/get_{collection}_by_ids",
                json_body={"entity_ids": [{"id": check_id(i)} for i in chunk]},
                read_only=True,
            )
            out.extend(unwrap(payload))
        return out

    def snapshot(self, fn: Any, *args: Any, **kwargs: Any) -> Any | None:
        """Run a read for a `before` snapshot; returns None instead of raising."""
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            logger.warning("before-snapshot failed: %s", redact(str(e)))
            return None

    def download_report(self, url: str) -> list[dict[str, Any]]:
        """Fetch a finished async report (CSV) and return its rows, kept in memory only.

        Only https URLs on Snap's report hosts are fetched, and files larger than
        SNAPCHAT_ADS_MAX_DOWNLOAD_MB are refused.
        """
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or not host.endswith(DOWNLOAD_HOST_SUFFIXES):
            raise ValueError(f"Refusing to download a report from a non-Snap host: {host!r}")
        cap = self.config.max_download_mb * 1024 * 1024
        auth_needed = False
        last: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            headers = {"Authorization": f"Bearer {self.auth.access_token()}"} if auth_needed else {}
            try:
                with self._http.stream(
                    "GET", url, headers=headers, timeout=max(self.config.timeout, 120.0)
                ) as resp:
                    if resp.status_code in (401, 403) and not auth_needed:
                        auth_needed = True
                        continue
                    if resp.status_code in RETRYABLE_STATUSES and attempt < MAX_ATTEMPTS - 1:
                        self._sleep_backoff(attempt, resp)
                        continue
                    if resp.status_code != 200:
                        raise SnapchatAdsAPIError(
                            resp.status_code, resp.read()[:300].decode("utf-8", "replace")
                        )
                    declared = int(resp.headers.get("Content-Length") or 0)
                    if declared > cap:
                        raise ValueError(_too_big(declared, self.config.max_download_mb))
                    buf = bytearray()
                    for chunk in resp.iter_bytes():
                        buf.extend(chunk)
                        if len(buf) > cap:
                            raise ValueError(_too_big(len(buf), self.config.max_download_mb))
            except httpx.RequestError as e:
                last = e
                self._sleep_backoff(attempt)
                continue
            return parse_csv(bytes(buf))
        raise SnapchatAdsAPIError(0, str(last) if last else "report download failed")

    @staticmethod
    def _safe_json(resp: httpx.Response) -> Any:
        if resp.status_code == 204 or not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {"_raw": resp.text[:2000]}

    @staticmethod
    def _sleep_backoff(attempt: int, resp: httpx.Response | None = None) -> None:
        retry_after = 0.0
        if resp is not None and "Retry-After" in resp.headers:
            try:
                retry_after = float(resp.headers["Retry-After"])
            except ValueError:
                retry_after = 0.0
        base = min(max(retry_after, min(2**attempt, 30)), MAX_BACKOFF)
        time.sleep(base + random.uniform(0, 0.5))


def _too_big(size: int, cap_mb: int) -> str:
    return (
        f"Report file is larger than SNAPCHAT_ADS_MAX_DOWNLOAD_MB ({cap_mb} MB, got at least "
        f"{size // (1024 * 1024)} MB). Narrow the date range, fields or breakdown, or raise the limit."
    )


def _rewind(files: dict[str, Any]) -> None:
    for value in files.values():
        handle = value[1] if isinstance(value, tuple) else value
        if hasattr(handle, "seek"):
            handle.seek(0)


def parse_csv(raw: bytes) -> list[dict[str, Any]]:
    """Parse an async report CSV into rows (dicts keyed by the header row)."""
    if raw[:2] == b"PK":
        raise ValueError("The report is an Excel file; request it with async_format='csv'.")
    text = raw.decode("utf-8-sig", errors="replace")
    if not text.strip():
        return []
    return [dict(row) for row in csv.DictReader(io.StringIO(text))]
