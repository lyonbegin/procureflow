"""Probe *public* G2B bid-list POST agency & geographic search fields.

No database, login, credential, saved data, or bid submission.
Logs only field names, result counts and public bid numbers/titles for validation.
"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from g2b_bid_notice_site_search import (
 G2B_HOME,G2B_HOST,_frames,_navigate,_wait_for_site_rendered,_fill_search_fields,
 _dismiss_public_notices,_dismiss_obstructing_public_popups,_click_notice_search,
 _verified_date_replay,_response_records)
today=datetime.now(ZoneInfo("Asia/Seoul")).date()
first=today.replace(day=1).isoformat()
last=today.isoformat()
with sync_playwright() as pw:
 browser=pw.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
 ctx=browser.new_context(locale="ko-KR",timezone_id="Asia/Seoul",viewport={"width":1440,"height":900})
 page=ctx.new_page(); requests=[]
 def record(req):
  parsed=urlparse(req.url)
  if req.method=="POST" and parsed.hostname==G2B_HOST and parsed.path.endswith("/BidPbac/selectBidPbacScrollTypeList.do"):
   requests.append(req)
 ctx.on("request",record)
 page.goto(G2B_HOME,wait_until="domcontentloaded",timeout=30000)
 if not _wait_for_site_rendered(page):page.reload(wait_until="domcontentloaded",timeout=30000)
 if not _wait_for_site_rendered(page):raise RuntimeError("G2B_PAGE_EMPTY")
 _navigate(page)
 _fill_search_fields(page,{"detail10":"","start":first,"end":last})
 _dismiss_public_notices(page)
 _dismiss_obstructing_public_popups(page)
 _click_notice_search(page)
 for _ in range(16):
  if requests:break
  page.wait_for_timeout(500)
 if not requests:raise RuntimeError("NO_PUBLIC_G2B_SEARCH_POST")
 original=requests[-1]
 body=json.loads(_verified_date_replay(original,"",first,last))
 fields=body["dlBidPbancLstM"]
 allowed={"accept","content-type","menu-info","submissionid","usr-id","referer","x-requested-with","target-id"}
 headers={k:v for k,v in original.headers.items() if k.lower() in allowed}
 headers["Content-Type"]="application/json;charset=UTF-8"
 print("G2B_FIELDS",json.dumps({"related":[k for k in fields if any(x in k.lower() for x in
     ("inst","grp","dmst","area","region","lgdng","oder","nm","lmt","pbanc"))],
   "total":len(fields)},ensure_ascii=False),flush=True)
 endpoint=original.url.split("?")[0]
 def probe(name,patch):
  p=json.loads(json.dumps(body))
  for key,val in patch.items():
   if key not in p["dlBidPbancLstM"]:
    print("G2B_PROBE",json.dumps({"name":name,"missing":key},ensure_ascii=False),flush=True)
    return
   p["dlBidPbancLstM"][key]=val
  reply=ctx.request.post(endpoint,data=json.dumps(p,ensure_ascii=False,separators=(",",":")),
       headers=headers,timeout=35000)
  try:
   records,total=_response_records(reply.json())
   ids=[x["bid_no"] for x in (records or [])]
   agencies=[x["agency"] for x in (records or [])]
   titles=[x["title"] for x in (records or [])]
   print("G2B_PROBE",json.dumps({"name":name,"http":reply.status,
    "n":len(records) if records is not None else None,
    "total":total,"ids":ids[:10],"agency_contains_seoul":sum("서울" in v for v in agencies),
    "title_contains_seoul":sum("서울" in v for v in titles),
    "examples":[{"agency":x["agency"][:65],"title":x["title"][:100]} for x in (records or [])[:4]]},ensure_ascii=False),flush=True)
  except Exception as e:print("G2B_PROBE",json.dumps({"name":name,"error_type":type(e).__name__}),flush=True)
 print("G2B_FIELD_DEFAULTS",json.dumps({k:fields.get(k) for k in
   ("dmstNm","instSearchRangeYn","bidPbancNm","odnLmtLgdngCd","odnLmtLgdngNm")},
   ensure_ascii=False),flush=True)
 probe("baseline",{})
 for name,key in [
    ("agency_name1","oderInstUntyGrpNm"),
    ("agency_name2","dmstNm"),
    ("agency_group_number","oderInstUntyGrpNo"),
    ("agency_name3","oderInstNm"),
    ("notice_keyword","bidPbancNm")
 ]:
  if key in fields:probe(name,{key:"서울"})
 if "dmstNm" in fields and "instSearchRangeYn" in fields:
  for value in ("Y","N","1"):
   probe("agency_name_range_"+value,{"dmstNm":"서울","instSearchRangeYn":value})
 # Test a completely new official public HTTP session directly, without
 # opening G2B search UI or clicking a login modal.
 safe_form={k:v for k,v in fields.items() if isinstance(v,(str,int,bool)) and
     len(str(v))<=120 and not any(secret in k.lower() for secret in
      ("token","secret","passwd","password","session","auth","user","apikey"))}
 print("G2B_PUBLIC_FORM_TEMPLATE",json.dumps(safe_form,ensure_ascii=False),flush=True)
 direct_context=pw.request.new_context(timeout=18000)
 direct_body=json.dumps(body,ensure_ascii=False,separators=(",",":"))
 def direct_probe(tag):
  try:
   response=direct_context.post(endpoint,data=direct_body,
      headers={"Content-Type":"application/json;charset=UTF-8",
               "Accept":"application/json"},timeout=20000)
   try:
    rows,total=_response_records(response.json())
    count=len(rows) if rows is not None else None
    first=[x["bid_no"] for x in (rows or [])[:3]]
   except Exception:count=None;first=[]
   print("G2B_DIRECT_POST",json.dumps({"name":tag,
     "http":response.status,"content_type":response.headers.get("content-type","")[:70],
     "count":count,"first_public_bid_ids":first},ensure_ascii=False),flush=True)
  except Exception as e:
   print("G2B_DIRECT_POST",json.dumps({"name":tag,
      "error_type":type(e).__name__},ensure_ascii=False),flush=True)
 direct_probe("no_cookies")
 try:
  root=direct_context.get("https://www.g2b.go.kr/",timeout=18000)
  print("G2B_DIRECT_HOME",json.dumps({"status":root.status,
    "content_type":root.headers.get("content-type","")[:55]}),flush=True)
 except Exception as e:print("G2B_DIRECT_HOME",type(e).__name__,flush=True)
 direct_probe("public_home_initialized")
 direct_context.dispose()
 ctx.close();browser.close()
