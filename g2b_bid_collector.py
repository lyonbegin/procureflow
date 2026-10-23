"""Official G2B opening/award result collector, separate from tender notices.

Uses PPS 나라장터 낙찰정보서비스 via the public data portal.
Authorization comes only from a Railway environment variable. Missing
credentials are errors, never zero-results or fabricated bidder records.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from db import session

BASE_URL = "https://apis.data.go.kr/1230000/as/ScsbidInfoService"
# Official award (A) and bid opening (B) operations, by goods and services.
OPERATIONS = {
    ("goods", "award"): "getScsbidListSttusThng",
    ("service", "award"): "getScsbidListSttusServc",
    ("goods", "opening"): "getOpengResultListInfoThng",
    ("service", "opening"): "getOpengResultListInfoServc",
}
# Other official series include preparatory prices and bidder-by-bidder
# rankings; introduce them as separate kinds after authenticated samples
# establish their actual composite keys and response structure.
SAFE_FIELDS = frozenset((
    "bidNtceNo","bidNtceOrd","bidClsfcNo","rbidNo","bidNtceNm",
    "dminsttNm","ntceInsttNm","opengDt","realOpengDt","opengRsltDivNm",
    "progrsDivCdNm","prtcptCnum","fnlSucsfbdCorpNm","fnlSucsfbdCorp",
    "fnlSucsfbdAmt","sucsfbidAmt","sucsfbidRate","fnlSucsfbdRate",
    "bidprcAmt","bidprcRate","bidprcRank","opengRank",
    "bidprcCorpNm","bidprcCorpBizno","prcbdrNm",
    "bidNtceDt","fnlSucsfbdDt","bsnsDivNm","opengSttusNm",
    "bidNtceNoOrd","bidNtceOrd","pblancNo","pblancOrd"
))


def configured() -> bool:
    return bool(os.environ.get("G2B_BID_API_KEY") or os.environ.get("DATA_GO_KR_SERVICE_KEY"))


def credentials() -> str:
    key = os.environ.get("G2B_BID_API_KEY") or os.environ.get("DATA_GO_KR_SERVICE_KEY")
    if not key:
        raise RuntimeError("g2b_bid_api_key_missing")
    return key


def parse_response(payload: dict) -> tuple[list[dict], int]:
    response = payload.get("response", payload)
    header = response.get("header") or {}
    code = str(header.get("resultCode", "00"))
    if code not in ("00", "0"):
        raise RuntimeError("g2b_bid_api_result_" + code[:16])
    body = response.get("body") or {}
    if not isinstance(body, dict):
        raise RuntimeError("g2b_bid_bad_body")
    node = body.get("items") or {}
    if isinstance(node, dict):
        items = node.get("item") or []
    elif isinstance(node, list):
        items = node
    else:
        items = []
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        raise RuntimeError("g2b_bid_unexpected_items")
    count = int(body.get("totalCount") or len(items))
    return [x for x in items if isinstance(x, dict)], count


def request_page(operation: str, start: str, end: str, page: int, page_size: int = 30) -> tuple[list[dict], int]:
    if operation not in OPERATIONS.values():
        raise ValueError("unsupported_g2b_bid_operation")
    if len(start) != 12 or len(end) != 12 or not (start.isdigit() and end.isdigit()):
        raise ValueError("invalid_g2b_date_range")
    parameters = {
        "serviceKey": credentials(), "type": "json", "inqryDiv": "1",
        "inqryBgnDt": start, "inqryEndDt": end,
        "numOfRows": min(100, max(1, int(page_size))), "pageNo": max(1, int(page))
    }
    url = BASE_URL + "/" + operation + "?" + urlencode(parameters)
    req = Request(url, headers={"User-Agent": "ProcureFlow/1.0", "Accept": "application/json"})
    try:
        with urlopen(req, timeout=25) as resp:
            data = resp.read(2_000_000)
            status = resp.status
    except HTTPError as exc:
        raise RuntimeError("g2b_bid_http_" + str(exc.code)) from None
    except (URLError, TimeoutError):
        raise RuntimeError("g2b_bid_network_error") from None
    if status != 200:
        raise RuntimeError("g2b_bid_http_" + str(status))
    try:
        parsed = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        # Error HTML/XML is not an empty dataset.
        raise RuntimeError("g2b_bid_non_json_response") from None
    return parse_response(parsed)


def normalize_item(record: dict, category: str, kind: str, operation: str, index: int):
    data = {k: v for k, v in record.items() if k in SAFE_FIELDS and v is not None}
    bid_no = str(data.get("bidNtceNo") or "").strip()
    if not bid_no:
        return None
    bid_ord = str(data.get("bidNtceOrd") or "").strip()
    clsfc = str(data.get("bidClsfcNo") or "").strip()
    rebid = str(data.get("rbidNo") or "").strip()
    rank = str(data.get("bidprcRank") or data.get("opengRank") or "").strip()
    participant = str(data.get("bidprcCorpBizno") or "").strip()
    # Index protects multiple data rows of the same execution. When a
    # participant identity is available, its ID is stable across pages.
    record_id = "|".join((category, kind, bid_no, bid_ord, clsfc, rebid,
                          rank, participant, "" if rank or participant else str(index)))
    key = hashlib.sha256(record_id.encode("utf-8")).hexdigest()[:40]
    company = str(data.get("fnlSucsfbdCorpNm") or data.get("bidprcCorpNm") or data.get("prcbdrNm") or "")
    amount = data.get("sucsfbidAmt") or data.get("fnlSucsfbdAmt") or data.get("bidprcAmt")
    return {
        "source": "g2b", "category": category, "result_kind": kind,
        "operation": operation, "record_key": key, "bid_ntce_no": bid_no,
        "bid_ntce_ord": bid_ord, "bid_clsfc_no": clsfc, "rbid_no": rebid,
        "title": str(data.get("bidNtceNm") or "")[:500],
        "agency": str(data.get("dminsttNm") or data.get("ntceInsttNm") or "")[:300],
        "company": company[:300],
        "amount": str(amount if amount is not None else "")[:70],
        "participation_count": str(data.get("prtcptCnum") or "")[:40],
        "rate": str(data.get("sucsfbidRate") or data.get("fnlSucsfbdRate") or data.get("bidprcRate") or "")[:45],
        "rank": rank[:25],
        "result_status": str(data.get("progrsDivCdNm") or data.get("opengRsltDivNm") or "")[:100],
        "raw": data,
    }


def save_batch(items: list[dict]) -> tuple[int, int]:
    if not items:
        return 0, 0
    saved, newly = 0, 0
    with session() as con:
        for item in items:
            payload = dict(item)
            payload["raw"] = json.dumps(payload["raw"], ensure_ascii=False)
            row = con.execute("""
                INSERT INTO procureflow.bid_results
                  (source,category,result_kind,operation,record_key,bid_ntce_no,
                   bid_ntce_ord,bid_clsfc_no,rbid_no,title,agency,company,amount,
                   participation_count,rate,rank,result_status,raw)
                VALUES (%(source)s,%(category)s,%(result_kind)s,%(operation)s,%(record_key)s,
                        %(bid_ntce_no)s,%(bid_ntce_ord)s,%(bid_clsfc_no)s,%(rbid_no)s,
                        %(title)s,%(agency)s,%(company)s,%(amount)s,
                        %(participation_count)s,%(rate)s,%(rank)s,%(result_status)s,%(raw)s::jsonb)
                ON CONFLICT(source,record_key) DO UPDATE SET
                  title=excluded.title,agency=excluded.agency,company=excluded.company,
                  amount=excluded.amount,participation_count=excluded.participation_count,
                  rate=excluded.rate,rank=excluded.rank,result_status=excluded.result_status,
                  raw=excluded.raw,last_seen=now()
                RETURNING (xmax=0) AS inserted
            """, payload).fetchone()
            saved += 1
            newly += int(bool(row["inserted"]))
    return saved, newly


def collect(days: int = 7, pages: int = 1, categories: list[str] | None = None,
            kinds: list[str] | None = None):
    """Collect bounded recent G2B bid *results*, not announcements.

    Verified API responses are necessary. Do not mix K-apt bid notices with
    the separate PPS G2B results, and never equate a missing award with loss.
    """
    if not configured():
        raise RuntimeError("g2b_bid_api_key_missing")
    days = max(1, min(int(days), 31))
    pages = max(1, min(int(pages), 10))
    categories = categories or ["goods", "service"]
    kinds = kinds or ["award", "opening"]
    if any(cat not in ("goods", "service") for cat in categories):
        raise ValueError("invalid_bid_category")
    if any(kind not in ("award", "opening") for kind in kinds):
        raise ValueError("invalid_bid_result_kind")
    now = datetime.now(timezone(timedelta(hours=9)))
    begin = now - timedelta(days=days)
    start = begin.strftime("%Y%m%d") + "0000"
    end = now.strftime("%Y%m%d") + "2359"
    result = {"source": "g2b", "status": "started", "period_days": days,
              "examined": 0, "saved": 0, "new": 0, "pages_checked": 0,
              "errors": [], "operations": []}
    for category in categories:
        for kind in kinds:
            operation = OPERATIONS[(category, kind)]
            op_meta = {"category":category,"kind":kind,"operation":operation,
                       "examined":0,"saved":0,"new":0}
            result["operations"].append(op_meta)
            for page in range(1, pages + 1):
                try:
                    records, total = request_page(operation,start,end,page,page_size=30)
                    normalized = [normalize_item(row,category,kind,operation,(page-1)*30+i)
                                  for i,row in enumerate(records)]
                    valid = [x for x in normalized if x is not None]
                    saved, newly = save_batch(valid)
                    op_meta["examined"] += len(records)
                    op_meta["saved"] += saved
                    op_meta["new"] += newly
                    result["examined"] += len(records)
                    result["saved"] += saved
                    result["new"] += newly
                    result["pages_checked"] += 1
                    logging.info("G2B_BID_PAGE kind=%s category=%s page=%s found=%s saved=%s new=%s",
                                 kind,category,page,len(records),saved,newly)
                    if page*30 >= total or not records:
                        break
                except Exception as exc:
                    reason = type(exc).__name__ + ":" + str(exc)[:95]
                    result["errors"].append(operation+":"+reason)
                    logging.warning("G2B_BID_ERROR operation=%s reason=%s",operation,reason)
                    break
    result["status"] = ("collected" if result["saved"] and not result["errors"]
                        else "partial" if result["saved"] else "error")
    return result
