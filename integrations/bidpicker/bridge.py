"""Isolated BidPicker discovery source; no legacy database import or bid submission."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, HTTPRedirectHandler, build_opener

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

ROOT = "https://www.pickersoft.com/bidpicker-api/"
MAX_BODY = 2_000_000


class SourceUnavailable(RuntimeError):
    pass


class DataContractError(ValueError):
    pass


class SameOriginRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        src, dest = urlparse(req.full_url), urlparse(newurl)
        if dest.scheme != "https" or dest.netloc != src.netloc:
            raise SourceUnavailable("Cross-origin or non-HTTPS redirect rejected")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass(frozen=True)
class Search:
    keyword: str = ""
    region: str = ""
    category: str = ""
    task_type: str = ""
    sort: str = "latest"
    page: int = 1
    size: int = 10
    deadline_soon: bool = False
    include_closed: bool = False

    def query(self) -> dict[str, str]:
        if not (1 <= self.page <= 100000 and 1 <= self.size <= 30):
            raise ValueError("Search page/size outside safe bounds")
        if self.sort not in ("latest", "deadline", "recommended"):
            raise ValueError("Unsupported sort")
        for value in (self.keyword, self.region, self.category, self.task_type):
            if len(value) > 160:
                raise ValueError("Search parameter too long")
        values = {
            "keyword": self.keyword.strip(), "region": self.region.strip(),
            "category": self.category.strip(), "taskType": self.task_type.strip(),
            "sort": self.sort, "page": self.page, "size": self.size,
            "deadlineSoon": str(self.deadline_soon).lower(),
            "includeClosed": str(self.include_closed).lower()
        }
        return {k: str(v) for k, v in values.items() if v != ""}


def fetch_json(path: str, query: dict[str, str] | None = None) -> Any:
    # This code supports documented APK-observed read routes only.
    if path not in ("api/bids", "api/trending-keywords") and not re.fullmatch(r"api/bids/[A-Za-z0-9_.-]{1,120}", path):
        raise ValueError("Read-only bid routes only")
    user = os.getenv("BIDPICKER_USERNAME", "")
    password = os.getenv("BIDPICKER_PASSWORD", "")
    if not user or not password:
        raise SourceUnavailable("Configured authorized source credentials required")
    auth = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    uri = ROOT + path + (("?" + urlencode(query)) if query else "")
    request = Request(uri, headers={
        "Accept": "application/json", "Authorization": "Basic " + auth
    }, method="GET")
    try:
        with build_opener(SameOriginRedirects()).open(request, timeout=15) as response:
            if "json" not in response.headers.get("Content-Type", "").lower():
                raise DataContractError("Source response is not JSON")
            data = response.read(MAX_BODY + 1)
            if len(data) > MAX_BODY:
                raise DataContractError("Source response over size limit")
            return json.loads(data.decode("utf-8"))
    except HTTPError as exc:
        raise SourceUnavailable(f"Source HTTP {exc.code}") from None
    except URLError:
        raise SourceUnavailable("Source network request failed") from None
    except (UnicodeError, json.JSONDecodeError):
        raise DataContractError("Invalid source JSON") from None


def extract_items(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = None
        for key in ("items", "bids", "results", "content", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                items = value
                break
            if isinstance(value, dict):
                for nested in ("items", "bids", "content", "results"):
                    if isinstance(value.get(nested), list):
                        items = value[nested]
                        break
            if items is not None:
                break
        if items is None:
            raise DataContractError("Unrecognized source list response; not an empty result")
    else:
        raise DataContractError("Unexpected source response type")
    if not all(isinstance(item, dict) for item in items):
        raise DataContractError("Source items must be objects")
    return items


def normalize_notice(item: dict) -> dict:
    bid_no = str(item.get("bidNo") or "").strip()
    bid_seq = str(item.get("bidSeq") or "").strip()
    title = str(item.get("title") or "").strip()
    if not bid_no or not bid_seq or not title or len(bid_no) > 90 or len(bid_seq) > 30:
        raise DataContractError("Missing bid identifier, sequence or title")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", bid_no) or not re.fullmatch(r"[A-Za-z0-9_-]+", bid_seq):
        raise DataContractError("Invalid bid identifier")
    original_url = str(item.get("originalUrl") or "")
    parsed = urlparse(original_url)
    host = (parsed.hostname or "").lower()
    valid_link = parsed.scheme == "https" and (host == "g2b.go.kr" or host.endswith(".g2b.go.kr"))
    canonical = json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return {
        "bid_no": bid_no, "bid_seq": bid_seq, "title": title,
        "agency": str(item.get("agencyName") or ""),
        "demand_agency": str(item.get("demandAgencyName") or ""),
        "posted_at": str(item.get("postedAt") or ""),
        "deadline_at": str(item.get("deadlineAt") or ""),
        "opening_at": str(item.get("openingAt") or ""),
        "budget": str(item.get("budgetAmount") or ""),
        "original_url": original_url if valid_link else "",
        "original_url_confirmed_format": valid_link,
        "raw": item,
        "hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "source": "bidpicker_third_party",
        "official_evidence_verified": False,
    }


def search_notices(criteria: Search) -> dict:
    items = extract_items(fetch_json("api/bids", criteria.query()))
    normalized, rejected = [], []
    for index, item in enumerate(items):
        try:
            normalized.append(normalize_notice(item))
        except DataContractError as exc:
            rejected.append({"index": index, "reason": str(exc)})
    return {
        "source": "bidpicker_third_party", "items": normalized,
        "rejected": rejected, "received": len(items),
        "official_evidence_verified": False, "source_url": ROOT + "api/bids",
    }


def connect_isolated():
    dsn = os.getenv("BIDPICKER_DATABASE_URL", "")
    if not dsn or (os.getenv("DATABASE_URL") and dsn == os.getenv("DATABASE_URL")):
        raise RuntimeError("Independent BIDPICKER_DATABASE_URL required (not legacy DATABASE_URL)")
    import psycopg
    return psycopg.connect(dsn, connect_timeout=8)


def ensure_schema(connection):
    connection.execute("CREATE SCHEMA IF NOT EXISTS bidpicker_feed")
    connection.execute("""CREATE TABLE IF NOT EXISTS bidpicker_feed.notices (
        bid_no text NOT NULL, bid_seq text NOT NULL, title text NOT NULL,
        agency text NOT NULL DEFAULT '', demand_agency text NOT NULL DEFAULT '',
        posted_at text NOT NULL DEFAULT '', deadline_at text NOT NULL DEFAULT '',
        opening_at text NOT NULL DEFAULT '', budget text NOT NULL DEFAULT '',
        original_url text NOT NULL DEFAULT '', original_url_confirmed_format boolean NOT NULL DEFAULT false,
        content_hash char(64) NOT NULL, source text NOT NULL DEFAULT 'bidpicker_third_party',
        raw jsonb NOT NULL, first_seen timestamptz NOT NULL DEFAULT now(),
        last_seen timestamptz NOT NULL DEFAULT now(),
        official_evidence_verified boolean NOT NULL DEFAULT false,
        PRIMARY KEY(bid_no, bid_seq))""")


def persist_notice(connection, record):
    values = (record["bid_no"], record["bid_seq"], record["title"], record["agency"],
              record["demand_agency"], record["posted_at"], record["deadline_at"],
              record["opening_at"], record["budget"], record["original_url"],
              record["original_url_confirmed_format"], record["hash"],
              json.dumps(record["raw"], ensure_ascii=False))
    inserted = connection.execute("""INSERT INTO bidpicker_feed.notices
       (bid_no,bid_seq,title,agency,demand_agency,posted_at,deadline_at,opening_at,
        budget,original_url,original_url_confirmed_format,content_hash,raw)
       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
       ON CONFLICT (bid_no,bid_seq) DO NOTHING RETURNING 1""", values).fetchone()
    if inserted:
        return "inserted"
    changed = connection.execute("""UPDATE bidpicker_feed.notices SET
        title=%s, agency=%s, demand_agency=%s, posted_at=%s, deadline_at=%s,
        opening_at=%s, budget=%s, original_url=%s, original_url_confirmed_format=%s,
        content_hash=%s, raw=%s::jsonb, last_seen=now()
        WHERE bid_no=%s AND bid_seq=%s AND content_hash IS DISTINCT FROM %s RETURNING 1""",
        (record["title"], record["agency"], record["demand_agency"], record["posted_at"],
         record["deadline_at"], record["opening_at"], record["budget"],
         record["original_url"], record["original_url_confirmed_format"], record["hash"],
         json.dumps(record["raw"], ensure_ascii=False),
         record["bid_no"], record["bid_seq"], record["hash"])).fetchone()
    if changed:
        return "updated"
    connection.execute(
        "UPDATE bidpicker_feed.notices SET last_seen=now() WHERE bid_no=%s AND bid_seq=%s",
        (record["bid_no"], record["bid_seq"]))
    return "duplicate"


def sync_notices(criteria: Search):
    output = search_notices(criteria)
    counts = {"inserted": 0, "updated": 0, "duplicate": 0}
    with connect_isolated() as connection:
        ensure_schema(connection)
        for record in output["items"]:
            counts[persist_notice(connection, record)] += 1
    return {
        "source": output["source"], "counts": counts,
        "received": output["received"], "rejected": output["rejected"],
        "official_evidence_verified": False, "bid_submitted": False
    }


class SyncRequest(BaseModel):
    keyword: str = Field(default="", max_length=160)
    region: str = Field(default="", max_length=160)
    category: str = Field(default="", max_length=160)
    task_type: str = Field(default="", max_length=160)
    sort: str = "latest"
    page: int = Field(default=1, ge=1, le=100000)
    size: int = Field(default=10, ge=1, le=30)
    deadline_soon: bool = False
    include_closed: bool = False

    def criteria(self):
        return Search(self.keyword, self.region, self.category, self.task_type,
                      self.sort, self.page, self.size, self.deadline_soon, self.include_closed)


app = FastAPI(title="BidPicker isolated discovery bridge", version="0.1")


def require_auth(authorization: str | None):
    expected = os.getenv("BIDPICKER_BRIDGE_TOKEN", "")
    if not expected or not authorization or not secrets.compare_digest(authorization, "Bearer " + expected):
        raise HTTPException(401, "Bridge authentication required")


@app.get("/health")
def health():
    return {"status": "ok", "source": "bidpicker_third_party",
            "integration_live_verified": False}


@app.get("/api/bidpicker/search")
def search(keyword: str = "", region: str = "", category: str = "", task_type: str = "",
           sort: str = "latest", page: int = Query(1, ge=1),
           size: int = Query(10, ge=1, le=30),
           deadline_soon: bool = False, include_closed: bool = False,
           authorization: str | None = Header(None)):
    require_auth(authorization)
    try:
        return search_notices(Search(keyword, region, category, task_type, sort, page, size,
                                     deadline_soon, include_closed))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except SourceUnavailable as exc:
        raise HTTPException(502, str(exc)) from None


@app.get("/api/bidpicker/detail/{bid_id}")
def detail(bid_id: str, authorization: str | None = Header(None)):
    require_auth(authorization)
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", bid_id):
        raise HTTPException(422, "Invalid bid ID")
    try:
        result = fetch_json("api/bids/" + bid_id)
        if isinstance(result, dict) and isinstance(result.get("data"), dict):
            result = result["data"]
        if not isinstance(result, dict):
            raise DataContractError("Unexpected detail response type")
        return {"source": "bidpicker_third_party", "item": normalize_notice(result),
                "official_evidence_verified": False}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except SourceUnavailable as exc:
        raise HTTPException(502, str(exc)) from None


@app.post("/api/bidpicker/sync")
def sync(request: SyncRequest, authorization: str | None = Header(None)):
    require_auth(authorization)
    if os.getenv("BIDPICKER_SYNC_ENABLED") != "1":
        raise HTTPException(409, "Sync disabled unless explicitly enabled")
    try:
        return sync_notices(request.criteria())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except SourceUnavailable as exc:
        raise HTTPException(502, str(exc)) from None
