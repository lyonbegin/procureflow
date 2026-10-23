"""Wishket public project, portfolio and partner *detail* collector.

Stores complete publicly rendered content + evidence-backed headings, project
sections, tools, media and links. Login-only partner profiles are reported
as restricted, not mislabeled as collected or fabricated from author names.
"""
import json,re,logging
from urllib.parse import urljoin,urlparse
from playwright.sync_api import sync_playwright
from db import session
from private_detail_utils import public_page_extract,parse_public_sections

ROOT="https://www.wishket.com"
KINDS={
 "projects":("/project/",r"^/project/\d+/$"),
 "partners":("/partners/",r"^/partners/p/[^/]+/$"),
 "portfolios":("/partners/wishket-portfolio/?tab=all",
               r"^/partners/wishket-portfolio/\d+/$")
}
CUSTOMER=re.compile(r"^(고객사|클라이언트|발주처)\s*[:：]\s*(\S[^\n]{1,90})$",re.M)
LOGIN_SIGNS=("로그인하고 위시켓","로그인 후 이용","로그인이 필요합니다")

def _links(page,pattern):
    hrefs=page.locator("a[href]").evaluate_all(
        "els=>els.map(e=>e.href).filter(x=>x.startsWith('https://www.wishket.com/'))")
    return list(dict.fromkeys(
        u for u in hrefs if re.match(pattern,urlparse(u).path)))

def _is_login(page,response,kind):
    if response and response.status in (401,403):return True
    url=page.url.lower()
    if "login" in url or urlparse(page.url).hostname=="auth.wishket.com":
        return True
    text=page.locator("body").inner_text(timeout=5000)[:1000]
    return (kind=="partners" and
            ("로그인" in text and len(text)<600 and "파트너" not in text))

def _real_portfolio_title(body,page):
    """Use the actual visible project heading, never the partner account name."""
    text=(body or "").replace("\r","")
    patterns=(
        r"(?:^|\n)플러스\s*\n([^\n]{7,230})\s*\n(?:URL 복사|개발|디자인|기획)",
        r"(?:^|\n)플러스\s*\n([^\n]{7,230})\s*\n"
    )
    for pat in patterns:
        m=re.search(pat,text,re.M)
        if m:
            name=m.group(1).strip()
            if name not in ("포트폴리오","위시켓") and "회원가입" not in name:
                return name[:280]
    try:
        og=page.locator('meta[property="og:title"]').first.get_attribute(
            "content",timeout=700)
        if og and "위시켓" in og:
            name=og.split("| 위시켓")[0].strip()
            if name and "파트너스" not in name:return name[:280]
    except Exception:pass
    return None


def _save(kind,detail_url,listing_page,page):
    detail=public_page_extract(page)
    parsed=parse_public_sections(page.locator("body").inner_text(timeout=6500))
    # Keep line breaks from the original visible page, not cloned text nodes.
    detail.update(parsed)
    raw_text=detail["text"]
    headings=detail["headings"]
    if len(raw_text)<260:raise RuntimeError("wishket_detail_insufficient")
    # The actual portfolio title is in the visible heading, not the
    # generic partner's browser tab text.
    title=(_real_portfolio_title(raw_text,page) if kind=="portfolios" else None)
    if not title:
        title=next((h for h in headings if len(h)>5 and
                    h not in ("포트폴리오","프로젝트 찾기","파트너스 찾기")),
                   page.title())[:350]
    customers=[m.group(2).strip() for m in CUSTOMER.finditer(raw_text)
               if "로그인" not in m.group(2)]
    author_urls=list(dict.fromkeys(
        x["url"] for x in detail["links"]
        if re.match(r"^/partners/p/[^/]+/$",urlparse(x["url"]).path)))
    portfolio_urls=list(dict.fromkeys(
        x["url"] for x in detail["links"]
        if re.match(r"^/partners/wishket-portfolio/\d+/$",
                    urlparse(x["url"]).path)))
    blocked=[f for f in ("계약 금액","프로젝트 기간","계약 일자")
             if re.search(re.escape(f)+r"\s*\n+\s*(?:\?\?\?|로그인)",raw_text)]
    evidence={
      "kind":kind,"origin":"public_detail","source_url":detail_url,
      "listing_page":listing_page,
      "heading":title,"headings":headings,
      "body_length":len(raw_text),"sections":detail["sections"],
      "technologies":detail["technologies"],
      "images":detail["images"][:40],
      "public_links":detail["links"][:70],
      "partner_profile_urls":author_urls,
      "related_portfolio_urls":portfolio_urls[:30],
      "login_restricted_fields":blocked,
      "public_customer_labels":customers
    }
    record_id=(re.search(r"/(\d+)/?$",urlparse(detail_url).path).group(1)
          if re.search(r"/(\d+)/?$",urlparse(detail_url).path)
          else urlparse(detail_url).path.strip("/").replace("/","_"))
    with session() as db:
        item=db.execute("""INSERT INTO procureflow.wishket_records
          (kind,source_id,title,url,body,customers,raw)
          VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
          ON CONFLICT(kind,source_id) DO UPDATE SET
            title=excluded.title,url=excluded.url,body=excluded.body,
            customers=excluded.customers,raw=excluded.raw,updated_at=now()
          RETURNING xmax=0 AS fresh""",
          (kind,record_id,title,detail_url,raw_text[:75000],
           json.dumps(customers,ensure_ascii=False),
           json.dumps(evidence,ensure_ascii=False))).fetchone()
    if kind=="portfolios" and author_urls:
        for author in author_urls:
            try:
                save_public_partner_reference(author,detail_url,raw_text,evidence)
            except Exception as exc:
                logging.warning("WISHKET_PUBLIC_AUTHOR_REFERENCE_FAILED %s %s",
                                author,type(exc).__name__)
    return {"title":title,"url":detail_url,"body_length":len(raw_text),
            "technologies":detail["technologies"][:12],
            "related_partner_count":len(author_urls),"fresh":bool(item["fresh"])}

def save_public_partner_reference(partner_url,portfolio_url,portfolio_body,portfolio_evidence):
    """Persist genuinely public work evidence without faking a private profile."""
    from urllib.parse import urlparse
    name=urlparse(partner_url).path.strip("/").split("/")[-1]
    if not name or not re.match(r"^[a-zA-Z0-9_-]+$",name):
        return False
    # A real publicly accessible portfolio proves this author/portfolio link;
    # profile description, ratings, CV and contact data remain login-restricted.
    with session() as db:
        existing=db.execute("""
            SELECT body,meta FROM procureflow.market_records
            WHERE source='wishket_partner_reference' AND kind='public_portfolio_evidence'
              AND source_id=%s
        """,(name,)).fetchone()
        old=existing["meta"] if existing else {}
        works=old.get("public_portfolios") or []
        existing_work=next((x for x in works if x.get("url")==portfolio_url),None)
        if existing_work:
            existing_work.update({
                "title":portfolio_evidence.get("heading","")[:300],
                "technologies":portfolio_evidence.get("technologies",[])[:25],
                "sections":portfolio_evidence.get("sections",{}),
                "portfolio_body_length":len(portfolio_body),
                "public_project_text":portfolio_body[:14000]})
        else:
            works.append({"url":portfolio_url,
                          "title":portfolio_evidence.get("heading","")[:300],
                          "technologies":portfolio_evidence.get("technologies",[])[:25],
                          "sections":portfolio_evidence.get("sections",{}),
                          "portfolio_body_length":len(portfolio_body),
                          "public_project_text":portfolio_body[:14000]})
        works=works[:250]
        # Keep independently extracted PUBLIC project content. Do not copy a
        # fictional partner biography or the site's login-placeholder labels.
        excerpts=[("[공개 수행 프로젝트] "+w.get("title","")+
                   "\\n"+w.get("public_project_text","")) for w in works]
        meta={"origin":"public_portfolio_author_reference",
              "public_profile_url":partner_url,
              "profile_access":"login_required",
              "profile_detail_verified":False,
              "public_portfolios":works,
              "public_portfolio_count":len(works)}
        row=db.execute("""
            INSERT INTO procureflow.market_records
                (source,kind,source_id,title,url,body,meta)
            VALUES ('wishket_partner_reference','public_portfolio_evidence',
                    %s,%s,%s,%s,%s::jsonb)
            ON CONFLICT(source,kind,source_id) DO UPDATE SET
                title=excluded.title,url=excluded.url,body=excluded.body,
                meta=excluded.meta,last_seen=now()
            RETURNING xmax=0 AS fresh
        """,(name,name,partner_url,"\n".join(excerpts)[:65000],
              json.dumps(meta,ensure_ascii=False))).fetchone()
    return bool(row["fresh"])


def collect(kind="portfolios",pages=2,limit=30,page_start=1):
    if kind not in KINDS:raise ValueError("unsupported kind")
    path,pattern=KINDS[kind]
    pages=max(1,min(40,int(pages)))
    page_start=max(1,min(100000,int(page_start)))
    limit=max(1,min(300,int(limit)))
    count=0
    new_count=0
    page_stats=[]
    seen_page_fingerprints=set()
    has_more=False
    examined=0
    errors=[]
    blocked=[]
    found=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        ctx=browser.new_context(locale="ko-KR",viewport={"width":1366,"height":900})
        page=ctx.new_page()
        try:
            for number in range(page_start,page_start+pages):
                url=ROOT+path
                if kind=="portfolios":
                    url=ROOT+"/partners/wishket-portfolio/?tab=all&page="+str(number)
                elif number>1:
                    url+=("&" if "?" in url else "?")+"page="+str(number)
                try:
                    response=page.goto(url,wait_until="domcontentloaded",timeout=30000)
                    if not response or response.status>=400:
                        errors.append("listing_http:"+str(response.status if response else "none"))
                        break
                    page.wait_for_timeout(1050)
                    items=_links(page,pattern)
                    if kind=="partners" and not items:
                        source=ROOT+"/partners/wishket-portfolio/?tab=all&page="+str(number)
                        page.goto(source,wait_until="domcontentloaded",timeout=25000)
                        page.wait_for_timeout(550)
                        portfolio_links=_links(page,KINDS["portfolios"][1])
                        for portfolio in portfolio_links[:min(30,limit+10)]:
                            try:
                                rr=page.goto(portfolio,wait_until="domcontentloaded",timeout=27000)
                                if rr and rr.status==200:
                                    page.wait_for_timeout(300)
                                    items+=_links(page,pattern)
                            except Exception as ex:
                                errors.append("partner_discovery:"+type(ex).__name__)
                        items=list(dict.fromkeys(items))
                    if items:
                        fingerprint="|".join(items[:20])
                        if fingerprint in seen_page_fingerprints:
                            page_stats.append({"page":number,"items":len(items),
                                               "repeated_listing":True})
                            has_more=False
                            break
                        seen_page_fingerprints.add(fingerprint)
                    found.extend(items)
                    page_stats.append({"page":number,"items":len(items)})
                    has_more=len(items)>=10
                    if not items:break
                    for url in items:
                        if count>=limit:break
                        examined+=1
                        try:
                            rr=page.goto(url,wait_until="domcontentloaded",timeout=27000)
                            if not rr or rr.status>=400 or _is_login(page,rr,kind):
                                blocked.append({"url":url,"reason":"login_required_or_http_restricted"})
                                continue
                            page.wait_for_timeout(350)
                            record=_save(kind,url,number,page)
                            count+=1
                            new_count+=int(record["fresh"])
                            logging.info("WISHKET_DETAIL kind=%s url=%s body_length=%s skills=%s partners=%s",
                                kind,url,record["body_length"],len(record["technologies"]),
                                record["related_partner_count"])
                        except Exception as ex:
                            errors.append(url+":"+type(ex).__name__+":"+str(ex)[:80])
                    if count>=limit:break
                except Exception as ex:
                    errors.append("listing:"+type(ex).__name__+":"+str(ex)[:110])
                    break
        finally:
            ctx.close()
            browser.close()
    result={"kind":kind,"status":"collected" if count and not errors else
            "partial" if count else "login_required" if blocked else
            "error" if errors else "empty",
            "saved":count,"new":new_count,"examined":examined,
            "discovered":len(set(found)),
            "page_start":page_start,
            "last_page":page_stats[-1]["page"] if page_stats else page_start,
            "has_more":bool(has_more),"pages":page_stats,
            "restricted":blocked[:25],"errors":errors[:20]}
    return result
