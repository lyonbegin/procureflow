"""Headless Chromium collectors. No remote Chrome 9333. Real-site failures are errors, never 0-row successes."""
import json,math,datetime as dt,time,re
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright
from db import session,store

TARGET="https://www.g2b.go.kr/pr/prc/prca/OderReq/selectOderReqList.do"
TZ=dt.timezone(dt.timedelta(hours=9))
def today():return dt.datetime.now(TZ).date()
def stamp(v):return str(v or "").strip()
def progress(jid, page,checked,added,duplicates,message):
    with session() as db:
        db.execute("""UPDATE procureflow.jobs SET current_page=%s,checked=%s,added=%s,
        duplicates=%s,message=%s WHERE id=%s AND state='running'""",
        (page,checked,added,duplicates,message[:500],jid))
def cancelled(jid):
    with session() as db:
        row=db.execute("SELECT state FROM procureflow.jobs WHERE id=%s",(jid,)).fetchone()
    return not row or row['state']!='running'
def save_batch(rows):
    if not rows:return 0
    with session() as db:
        added=0
        for row in rows:added+=int(store(db,row))
    return added
def browser_context(playwright):
    browser=playwright.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
    context=browser.new_context(locale="ko-KR",timezone_id="Asia/Seoul")
    return browser,context
def kapt_url(kind,number,days,opts=None):
    opts=opts or {};end=today();start=end-dt.timedelta(days=days)
    typ,sub=('04','13') if kind=='goods' else ('03','')
    params={"pageSelect":"100","searchBidGb":"bid_gb_1","bidTitle":opts.get("bidTitle",""),
    "aptName":opts.get("aptName",""),"searchDateGb":"reg","dateStart":str(start),"dateEnd":str(end),
    "dateArea":"1","bidState":opts.get("bidState",""),"codeAuth":opts.get("codeAuth",""),
    "codeWay":opts.get("codeWay",""),"codeAuthSub":opts.get("codeAuthSub",""),
    "codeSucWay":"","codeClassifyType1":"02","codeClassifyType2":typ,
    "codeClassifyType3":sub,"pageNo":str(number),"type":"4","bidArea":"","bidNum":"",
    "bidNo":"","dTime":str(int(time.time()*1000)),"mainKaptCode":"","aptCode":""}
    return "https://www.k-apt.go.kr/bid/bidList.do?"+urlencode(params)
KAPT_JS="""() => {
const t=document.querySelector('#tblBidList');
if(!t)return {found:false,rows:[]};
const clean=x=>(x||'').replace(/\\s+/g,' ').trim();
return {found:true,rows:Array.from(t.querySelectorAll('tbody tr.notice-row[dataid]')).map(tr=>{
const td=Array.from(tr.querySelectorAll(':scope > td'));if(td.length<8)return null;
return {id:tr.getAttribute('dataid'),cells:td.map(x=>clean(x.textContent))};
}).filter(Boolean),text:clean(t.textContent).slice(0,350)}; }
"""
def kapt(jid,config):
    days=max(1,min(365,int(config.get('days',30))))
    pages=max(1,min(500,int(config.get('pages',2))))
    kinds={"goods":["goods"],"service":["service"],"both":["goods","service"]}[config.get("categories","both")]
    with sync_playwright() as p:
        browser,ctx=browser_context(p)
        try:
            page=ctx.new_page();tot=0;new=0;seen=set();page_number=0
            for kind in kinds:
                last=None
                for number in range(1,pages+1):
                    if cancelled(jid):return
                    url=kapt_url(kind,number,days,config)
                    response=page.goto(url,wait_until="domcontentloaded",timeout=40000)
                    if not response or response.status>=400:raise RuntimeError(f"K-apt HTTP {response.status if response else 'none'}")
                    page.locator("#tblBidList").wait_for(state="attached",timeout=18000)
                    sel=page.locator("#code_classify_type_2").input_value()
                    expected='04' if kind=='goods' else '03'
                    if sel!=expected:raise RuntimeError(f"K-apt filter mismatch: {sel} != {expected}")
                    result=page.evaluate(KAPT_JS)
                    if not result["found"]:raise RuntimeError("Missing #tblBidList")
                    items=result["rows"]
                    if not items:
                        if number==1 and not re.search("검색결과가 없습니다|자료가 없습니다|조회된.*없습니다",result.get('text','')):
                            raise RuntimeError("No dataid rows in first page")
                        break
                    ids=tuple(x["id"] for x in items)
                    if ids==last:raise RuntimeError("Repeated K-apt page: paging ignored")
                    last=ids
                    if len(ids)!=len(set(ids)):raise RuntimeError("Duplicated dataid on same page")
                    records=[]
                    for item in items:
                        cell=item["cells"];eid=item["id"]
                        if not eid:continue
                        records.append(dict(source="kapt",external_id=eid,title=cell[3],
                        agency=cell[6],category="물품" if kind=="goods" else "일반용역",
                        notice_date=cell[7],deadline=cell[4],status=cell[5],method=cell[2],
                        source_url=url,raw={"cells":cell,"source_platform":cell[1]}))
                    inserted=save_batch(records)
                    page_number+=1;tot+=len(records);new+=inserted
                    progress(jid,page_number,tot,new,tot-new,f"K-apt {kind} {number}페이지 / {len(records)}건")
                    if len(items)<100:break
                # other classification continues, even if first has no rows
            return {"checked":tot,"added":new,"duplicates":tot-new}
        finally:browser.close()
def g2b(jid,config):
    """Replays observed browser search in same-origin Chrome, without port 9333."""
    days=max(1,min(365,int(config.get('days',30))))
    pages=max(1,min(500,int(config.get('pages',2))))
    begin=(today()-dt.timedelta(days=days)).strftime("%Y%m%d")
    end=today().strftime("%Y%m%d")
    with sync_playwright() as p:
        browser,ctx=browser_context(p)
        try:
            page=ctx.new_page();seen=[]
            def observe(request):
                if request.method=="POST" and request.url.split("?")[0]==TARGET and request.post_data:
                    seen.append({"url":request.url,"body":request.post_data,"headers":request.all_headers()})
            page.on("request",observe)
            page.goto("https://www.g2b.go.kr/",wait_until="domcontentloaded",timeout=45000)
            page.wait_for_timeout(3000)
            for key in ("mf_wfm_gnb_wfm_gnbMenu_genDepth1_0_btn_menuLvl1",
                        "mf_wfm_gnb_wfm_gnbMenu_genDepth1_0_genDepth2_0_btn_menuLvl2"):
                found=False
                for frame in page.frames:
                    try:
                        if frame.evaluate("(id)=>{let e=document.getElementById(id);if(!e)return false;e.click();return true}",key):
                            found=True;break
                    except Exception:pass
                if not found:raise RuntimeError("G2B menu DOM not found: "+key)
                page.wait_for_timeout(1400)
            for frame in page.frames:
                try:
                    candidates=frame.locator('input[type="button"][value="검색"]')
                    for idx in range(min(candidates.count(),15)):
                        try:
                            if candidates.nth(idx).is_visible():
                                candidates.nth(idx).click(timeout=1500)
                                break
                        except Exception:pass
                except Exception:pass
            deadline=time.monotonic()+25
            while not seen and time.monotonic()<deadline:page.wait_for_timeout(250)
            if not seen:raise RuntimeError("G2B original POST XHR not captured")
            seed=next((x for x in reversed(seen) if 'dlOderReqSrchM' in x['body']),None)
            if not seed:raise RuntimeError("G2B XHR missing dlOderReqSrchM")
            original=json.loads(seed["body"]);model=original.get("dlOderReqSrchM")
            if not isinstance(model,dict):raise RuntimeError("G2B search model missing")
            sender=next((fr for fr in page.frames if fr.url.startswith("https://www.g2b.go.kr")),page.main_frame)
            headers={k:v for k,v in seed["headers"].items() if k.lower() in
                     ("content-type","accept","menu-info","submissionid","usr-id","target-id","x-csrf-token","x-xsrf-token","x-requested-with")}
            total=None;new=0;checked=0
            for number in range(1,pages+1):
                if cancelled(jid):return
                model.update({"currentPage":number,"recordCountPerPage":"100",
                 "prcmBsneSeCd":"01 03","prgrsBgngYmd":begin,"prgrsEndYmd":end})
                payload=json.dumps(original,ensure_ascii=False,separators=(",",":"))
                response=sender.evaluate("""async ({url,payload,headers})=>await new Promise(resolve=>{
                    const x=new XMLHttpRequest();x.open('POST',url,true);x.withCredentials=true;x.timeout=35000;
                    for(const [k,v] of Object.entries(headers)){try{x.setRequestHeader(k,v)}catch(e){}}
                    x.onload=()=>resolve({status:x.status,body:x.responseText});
                    x.onerror=()=>resolve({status:0,error:'network'});x.ontimeout=()=>resolve({status:0,error:'timeout'});
                    x.send(payload);
                })""",{"url":seed["url"],"payload":payload,"headers":headers})
                if response.get("status")!=200:raise RuntimeError(f"G2B XHR HTTP {response.get('status')}: {response.get('error','')}")
                obj=json.loads(response["body"])
                if str(obj.get("ErrorCode")) not in ("0","00"):raise RuntimeError("G2B ErrorCode="+str(obj.get("ErrorCode")))
                items=obj.get("dlOderReqL")
                if not isinstance(items,list):raise RuntimeError("G2B JSON missing dlOderReqL")
                if total is None:total=int((items[0].get("totCnt") if items else 0) or 0)
                rows=[]
                for item in items:
                    code=stamp(item.get("prcmBsneSeCd"))
                    if code not in ("01","03"):continue
                    eid=stamp(item.get("oderPlanNo") or item.get("unikey"))
                    if not eid:continue
                    rows.append(dict(source="g2b",external_id=eid,title=stamp(item.get("bizNm")),
                    agency=stamp(item.get("oderInstUntyGrpNm")),category="물품" if code=="01" else "일반용역",
                    notice_date=stamp(item.get("prcsYmd")),deadline=stamp(item.get("oderYymm")),
                    status=stamp(item.get("oderPlanPgstCd")),method=stamp(item.get("stdCtrtMthdNm")),
                    source_url="https://www.g2b.go.kr/",raw=item))
                n=save_batch(rows);checked+=len(rows);new+=n
                progress(jid,number,checked,new,checked-new,f"G2B {number}페이지 / total {total}")
                if len(items)<100 or (total and number*100>=total):break
            return {"checked":checked,"added":new,"duplicates":checked-new}
        finally:browser.close()
