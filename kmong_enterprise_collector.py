"""Kmong Enterprise request collector: real project IDs, list/detail separation.

Reads ordinary public Enterprise requests. Does not automate proposals, messages,
sign-in, account access, payments or bypass site access controls. Every saved
record is supported by a fetched actual /enterprise/requests/<ID> detail page.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, urlparse, parse_qs

from playwright.sync_api import sync_playwright
from db import session

BASE = "https://kmong.com"
CATEGORY = "6"  # IT / programming, verified on real browser
DETAIL_RE = re.compile(r"^/enterprise/requests/([0-9]{3,12})/?$")
STOP_WORDS = ("로그인이 필요합니다", "접근 권한이 없습니다", "페이지를 찾을 수 없습니다")
DEVELOPMENT_TAGS = {
    "ai": r"AI|인공지능|머신러닝|딥러닝|자연어|LLM|이미지\s*(?:검색|인식)",
    "search": r"검색|벡터|임베딩|추천|RAG",
    "web": r"웹\s*(?:사이트|앱|개발)|React|Next\.?js|Spring|홈페이지",
    "mobile": r"모바일|안드로이드|iOS|Flutter|React Native|앱\s*개발",
    "erp_mes": r"ERP|MES|스마트팩토리|재고관리|생산관리",
    "automation": r"자동화|크롤링|RPA|업무\s*효율|OCR",
    "data": r"데이터|분석|ETL|대시보드|DB|SQL",
}
WON = re.compile(r"(?:예산|프로젝트\s*금액|예상\s*금액)\s*[:：]?\s*([0-9][0-9,]*)\s*원")
DATES = re.compile(r"(20[0-9]{2})[.\-/]\s*([01]?[0-9])[.\-/]\s*([0-3]?[0-9])")
TECHNOLOGY = re.compile(
    r"\b(?:Python|JavaScript|TypeScript|React|Next\.?js|Node\.?js|Spring Boot|"
    r"Flutter|Java|PHP|Kotlin|Swift|FastAPI|PostgreSQL|MySQL|"
    r"OpenAI|AWS|Docker|Figma|MSSQL|PyTorch)\b", re.I
)


def listing_url(page: int) -> str:
    if not isinstance(page, int) or not 1 <= page <= 485:
        raise ValueError("page must be 1..485")
    return BASE + "/enterprise/requests?" + urlencode({
        "category_list": CATEGORY, "page": page, "q": "",
        "sort": "created_at",
    })


def detail_id(url: str) -> str | None:
    p = urlparse(url)
    if p.scheme != "https" or p.hostname not in ("kmong.com", "www.kmong.com"):
        return None
    match = DETAIL_RE.fullmatch(p.path)
    return match.group(1) if match else None


def parse_fields(body: str) -> dict:
    value: dict = {}
    found = WON.search(body)
    if found:
        value["budget_krw"] = int(found.group(1).replace(",", ""))
    found = re.search(r"(?:진행\s*방식|근무\s*형태|진행\s*유형)\s*[:：]?\s*(외주|상주|재택)", body)
    if found:
        value["work_format"] = found.group(1)
    matches = DATES.findall(body)
    if matches:
        value["dates_seen"] = [
            f"{y}-{int(m):02d}-{int(d):02d}" for y, m, d in matches[:10]
        ]
    found = re.search(r"(?:프로젝트\s*기간|예상\s*기간|진행\s*기간)\s*[:：]?\s*([0-9]{1,4})\s*일", body)
    if found:
        value["duration_days"] = int(found.group(1))
    value["tech_stack"] = list(dict.fromkeys(m.group(0) for m in TECHNOLOGY.finditer(body)))[:35]
    value["tags"] = [
        key for key, pattern in DEVELOPMENT_TAGS.items()
        if re.search(pattern, body, re.I)
    ]
    value["proposal_button_present"] = bool(
        re.search(r"제안하기|로그인\s*후\s*제안", body))
    value["detail_characters"] = len(body)
    return value


def cards_from_page(page) -> list[dict]:
    """Find exact project links in rendered anchors; use hydrated DOM fallback."""
    discovered = page.locator("a[href]").evaluate_all(
        """els => els.map(a => ({
           url:a.href,
           title:(a.innerText||a.getAttribute('aria-label')||'').trim().slice(0,350),
           snippet:(a.closest('article,li,[class*="card"],[class*="Card"]')||a)
                 .innerText?.trim().slice(0,1200)||''
        }))"""
    )
    result: dict[str,dict] = {}
    for candidate in discovered:
        identifier = detail_id(candidate.get("url", ""))
        if identifier and identifier not in result:
            result[identifier] = {
                "source_id": identifier,
                "url": BASE + "/enterprise/requests/" + identifier,
                "listing_title": candidate.get("title", ""),
                "listing_excerpt": candidate.get("snippet", ""),
            }
    if not result:
        # Next.js may embed routes in a hydration payload rather than anchors.
        html = page.content()
        for identifier in dict.fromkeys(re.findall(
            r"(?:\\/|/)enterprise(?:\\/|/)requests(?:\\/|/)([0-9]{3,12})",
            html,
        )):
            result[identifier] = {
                "source_id": identifier,
                "url": BASE + "/enterprise/requests/" + identifier,
                "listing_title": "",
                "listing_excerpt": "",
            }
    return list(result.values())



def clickable_cards(page):
    """Kmong's project cards are JS-driven LI buttons, NOT <a href> links.

    Verified real UI: LI with class css-x6apz0 ep8pv1p0; accessible name
    '프로젝트 카드'. Prefer accessibility selector; fall back to the observed
    class rather than guessing links or scraping anonymous API endpoints.
    """
    choices = (
        page.get_by_role("button", name="프로젝트 카드"),
        page.locator('li[role="button"][name="프로젝트 카드"]'),
        page.locator("li.css-x6apz0.ep8pv1p0"),
        page.locator('li[class*="ep8pv1p0"]'),
    )
    for locator in choices:
        try:
            if locator.count():
                return locator
        except Exception:
            continue
    return None


def discover_by_click(page, address: str, max_cards: int) -> list[dict]:
    """Follow the genuine project-card UI to obtain IDs, returning to listing.

    Each interaction requires the actual URL to become /enterprise/requests/ID;
    never infer an ID from card order or unrelated Next.js scripts.
    """
    found: dict[str,dict] = {}
    page.goto(address, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(1250)
    cards = clickable_cards(page)
    if cards is None:
        return []
    total = min(cards.count(), max_cards)
    logging.info("KMONG_ENTERPRISE_CLICKABLE_CARDS count=%s", total)
    for index in range(total):
        try:
            if index:
                page.goto(address, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(950)
            cards = clickable_cards(page)
            if cards is None or cards.count() <= index:
                logging.warning("KMONG_ENTERPRISE_CARD_DISAPPEARED index=%s", index)
                continue
            card = cards.nth(index)
            excerpt = card.inner_text(timeout=4500).strip()[:1200]
            if not excerpt:
                continue
            card.click(timeout=9000)
            try:
                page.wait_for_url(re.compile(r"^https://(?:www\.)?kmong\.com/enterprise/requests/[0-9]+/?(?:\?.*)?$"),
                                  timeout=14000)
            except Exception:
                pass
            identifier = detail_id(page.url)
            if not identifier:
                logging.warning(
                    "KMONG_ENTERPRISE_CLICK_NO_DETAIL index=%s path=%s",
                    index, urlparse(page.url).path,
                )
                continue
            found.setdefault(identifier, {
                "source_id": identifier,
                "url": BASE + "/enterprise/requests/" + identifier,
                "listing_title": excerpt.splitlines()[0][:280],
                "listing_excerpt": excerpt,
            })
        except Exception as exc:
            logging.warning(
                "KMONG_ENTERPRISE_CLICK_ERROR index=%s type=%s",
                index, type(exc).__name__,
            )
    return list(found.values())


def detail_title(page, listing: dict) -> str:
    heads = page.locator("h1,h2").all_inner_texts()
    for text in heads:
        title = text.strip()
        if len(title) >= 12 and not re.search(
            r"전체\s*프로젝트|프로젝트\s*찾기|크몽|엔터프라이즈", title
        ):
            return title[:280]
    title = listing.get("listing_title", "").strip()
    return title[:280] if title else page.title()[:280]


def read_one_detail(page, listing: dict, source_listing_url: str) -> dict:
    url = listing["url"]
    identifier = listing["source_id"]
    if detail_id(url) != identifier:
        raise ValueError("project_id_url_mismatch")
    resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
    if not resp or resp.status >= 400:
        raise RuntimeError(f"detail_http_{resp.status if resp else 'empty'}")
    page.wait_for_timeout(1000)
    final_id = detail_id(page.url)
    if final_id != identifier:
        raise RuntimeError("detail_redirected_outside_matching_project")
    body = page.locator("body").inner_text(timeout=7000).strip()[:80000]
    if len(body) < 350:
        raise RuntimeError("detail_text_too_short")
    if any(x in body[:800] for x in STOP_WORDS):
        raise RuntimeError("detail_access_restricted")
    title = detail_title(page, listing)
    if len(title) < 10:
        raise RuntimeError("detail_title_not_found")
    meta = parse_fields(body)
    meta.update({
        "demand_type": "project_request",
        "service_area": "development",
        "detail_verified": True,
        "listing_url": source_listing_url,
        "listing_title": listing.get("listing_title", ""),
        "listing_excerpt": listing.get("listing_excerpt", ""),
        "detail_url": page.url,
        "observed_at": datetime.now(timezone.utc).isoformat(),
    })
    return {
        "source_id": identifier, "title": title, "url": page.url,
        "body": body, "meta": meta,
    }


def save_detail(item: dict) -> bool:
    with session() as db:
        row = db.execute("""
          INSERT INTO procureflow.market_records
          (source,kind,source_id,title,url,body,meta)
          VALUES ('kmong_enterprise','development_demand',%s,%s,%s,%s,%s::jsonb)
          ON CONFLICT(source,kind,source_id) DO UPDATE SET
            title=EXCLUDED.title, url=EXCLUDED.url, body=EXCLUDED.body,
            meta=EXCLUDED.meta,last_seen=now()
          RETURNING (xmax=0) AS inserted
        """, (
            item["source_id"], item["title"], item["url"], item["body"],
            json.dumps(item["meta"], ensure_ascii=False),
        )).fetchone()
        return bool(row["inserted"])


def collect(pages: int = 1, limit: int = 10) -> dict:
    pages = max(1, min(int(pages), 20))
    limit = max(1, min(int(limit), 200))
    result = {
        "source": "kmong_enterprise",
        "role": "development_demand",
        "status": "started", "examined": 0, "saved": 0,
        "new": 0, "pages_checked": 0, "errors": [],
        "verified_ids": [], "failed_ids": [], "listings": [],
    }
    candidates: dict[str,dict] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(
            locale="ko-KR", viewport={"width": 1366, "height": 900},
            timezone_id="Asia/Seoul",
        )
        page = context.new_page()
        try:
            for number in range(1, pages + 1):
                address = listing_url(number)
                try:
                    resp = page.goto(address, wait_until="domcontentloaded",
                                     timeout=30000)
                    if not resp or resp.status >= 400:
                        raise RuntimeError(
                            f"listing_http_{resp.status if resp else 'empty'}"
                        )
                    page.wait_for_timeout(1250)
                    found = cards_from_page(page)
                    if not found:
                        # Real Kmong cards are clickable LI elements without href.
                        found = discover_by_click(page, address, max_cards=limit)
                    result["pages_checked"] += 1
                    result["listings"].append({
                        "page": number, "url": page.url,
                        "cards_found": len(found),
                    })
                    logging.info("KMONG_ENTERPRISE_LIST page=%s cards=%s", number, len(found))
                    for item in found:
                        candidates.setdefault(item["source_id"], item)
                    if not found:
                        result["errors"].append(f"page_{number}:no_detail_links")
                        break
                    if len(candidates) >= limit:
                        break
                except Exception as exc:
                    result["errors"].append(f"page_{number}:{type(exc).__name__}")
                    break
            result["examined"] = min(len(candidates), limit)
            for listing in list(candidates.values())[:limit]:
                identifier = listing["source_id"]
                try:
                    item = read_one_detail(page, listing, result["listings"][0]["url"])
                    was_new = save_detail(item)
                    result["saved"] += 1
                    result["new"] += int(was_new)
                    result["verified_ids"].append(identifier)
                    logging.info(
                        "KMONG_ENTERPRISE_DETAIL id=%s chars=%s new=%s",
                        identifier, item["meta"]["detail_characters"], was_new,
                    )
                except Exception as exc:
                    result["failed_ids"].append(identifier)
                    result["errors"].append(
                        f"project_{identifier}:{type(exc).__name__}"
                    )
                    logging.warning(
                        "KMONG_ENTERPRISE_DETAIL_ERROR id=%s type=%s",
                        identifier, type(exc).__name__,
                    )
                time.sleep(1)
            result["status"] = (
                "collected" if result["saved"] else
                "discovery_only" if candidates else "error"
            )
        except Exception as exc:
            result["status"] = "error"
            result["errors"].append(f"collector:{type(exc).__name__}")
        finally:
            context.close()
            browser.close()
    return result


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False))
