"""Live, on-demand, no-DB, no-Worker public G2B nine-stage TEST executor.

Runs only after an explicit Studio button click. Official public G2B endpoints
are contacted afresh; no API/Worker/PG or cron, and no automatic browser scheduling,
no bidding, signing, submissions or server-side persistence. Stage results
are held in bounded session-scoped process memory for the browser UI.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from hashlib import sha256
from http.cookiejar import CookieJar
from io import BytesIO
from pathlib import Path
from threading import Lock, Thread
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPCookieProcessor, HTTPRedirectHandler
from zoneinfo import ZoneInfo
import json
import logging
import re
import struct
import time
import uuid
import zipfile
import zlib

CASE="R26BK01787028"
DETAIL="8111159901"
FLOW="operations/PF00-public-nine-real.json"
OFFICIAL="https://www.g2b.go.kr"
OPENINGS=OFFICIAL+"/pb/pbo/pboc/OnbsRslt/selectOnbsRsltClsfList.do"
ATTACH=OFFICIAL+"/pn/pnp/pnpe/UntyAtchFile/downloadFile.do"
MAX_BODY=8*1024*1024
MAX_TEXT=18000
RUNS={}
GUARD=Lock()
ACTIVE=None
log=logging.getLogger("procureflow.live9")
STAGES=["최신 공고 직접 조회","공고 첨부 원본 직접 수집","참가자격·원문 조건 분석",
        "개찰 원본 직접 조회","경쟁 결과 원본 분석","수행·원가 근거 확인",
        "가격전략 검증","원문 근거 검토 DOCX 작성","전체 단계 독립 검증"]
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise ValueError("OFFICIAL_REDIRECT_BLOCKED")
def _client():
    return build_opener(HTTPCookieProcessor(CookieJar()),NoRedirect())
def _fetch(opener,url,body=None,headers=None,timeout=12):
    if not url.startswith(OFFICIAL+"/"):
        raise ValueError("OFFICIAL_HOST_REQUIRED")
    req=Request(url,data=body,headers=headers or {},method="POST" if body is not None else "GET")
    with opener.open(req,timeout=timeout) as response:
        if response.status!=200:raise ValueError("OFFICIAL_HTTP_"+str(response.status))
        ctype=response.headers.get("Content-Type","").lower()
        raw=response.read(MAX_BODY+1)
        if len(raw)>MAX_BODY:raise ValueError("OFFICIAL_FILE_TOO_LARGE")
        return raw,ctype
def _json_post(opener,url,data,headers):
    raw,ctype=_fetch(opener,url,json.dumps(data,ensure_ascii=False).encode("utf-8"),
        {"Content-Type":"application/json;charset=UTF-8","Accept":"application/json",
         "User-Agent":"ProcureFlow-Live-Test/1.0",**headers})
    if not (raw.startswith(b"{") or raw.startswith(b"[")):
        raise ValueError("OFFICIAL_RESPONSE_NOT_JSON")
    answer=json.loads(raw)
    if not isinstance(answer,dict) or not isinstance(answer.get("result"),(dict,list)):
        raise ValueError("OFFICIAL_RESPONSE_SCHEMA_INVALID")
    if answer.get("ErrorCode") not in (None,0,"0"):
        raise ValueError("OFFICIAL_ERROR_"+str(answer["ErrorCode"])[:18])
    return answer["result"]
def _hwp_text(raw):
    """Parse HWP5 OLE BodyText/Section records; never claim unknown text parsed."""
    import olefile
    if not olefile.isOleFile(BytesIO(raw)):
        raise ValueError("NOT_HWP5_OLE")
    texts=[]
    with olefile.OleFileIO(BytesIO(raw)) as ole:
        if not ole.exists("FileHeader"):raise ValueError("HWP_FILE_HEADER_ABSENT")
        flags=struct.unpack("<I",ole.openstream("FileHeader").read(40)[36:40])[0]
        streams=sorted((p for p in ole.listdir() if len(p)==2 and p[0]=="BodyText" and p[1].startswith("Section")),key=lambda x:x[-1])
        for path in streams[:12]:
            buf=ole.openstream(path).read(MAX_BODY)
            if flags&1:
                # Cap HWP decompression to avoid high memory spikes.
                inflater=zlib.decompressobj(-15)
                buf=inflater.decompress(buf,MAX_TEXT*32)
                if not inflater.eof:
                    raise ValueError("HWP_SECTION_DECOMPRESSED_SIZE_LIMIT")
            i=0
            while i+4<=len(buf):
                head=struct.unpack_from("<I",buf,i)[0];i+=4
                tag=head&1023;size=head>>20
                if size==4095:
                    if i+4>len(buf):break
                    size=struct.unpack_from("<I",buf,i)[0];i+=4
                if size>MAX_BODY or i+size>len(buf):break
                if tag==67:
                    v=buf[i:i+size].decode("utf-16-le",errors="ignore")
                    v=re.sub(r"[\x00-\x08\x0b-\x1f]"," ",v)
                    if v.strip():texts.append(v)
                i+=size
                if sum(map(len,texts))>MAX_TEXT:break
    return "\n".join(texts)[:MAX_TEXT]
def _extract(raw,ctype):
    if raw.startswith(b"\xd0\xcf\x11\xe0"):return _hwp_text(raw),"hwp5_ole"
    if raw.startswith(b"%PDF"):
        from pypdf import PdfReader
        text="\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(raw)).pages[:20])
        return text[:MAX_TEXT],"pdf"
    if raw.startswith(b"PK\x03\x04"):
        with zipfile.ZipFile(BytesIO(raw)) as z:
            if "word/document.xml" in z.namelist():
                from xml.etree import ElementTree
                root=ElementTree.fromstring(z.read("word/document.xml"))
                return " ".join(n.text for n in root.iter() if n.tag.endswith("}t") and n.text)[:MAX_TEXT],"docx"
            for n in z.namelist():
                if n.startswith("Contents/") and n.endswith(".xml"):
                    text=re.sub(r"<[^>]*>"," ",z.read(n).decode("utf-8",errors="replace"))
                    if text.strip():return text[:MAX_TEXT],"hwpx"
    raise ValueError("UNSUPPORTED_OFFICIAL_ATTACHMENT_FORMAT")
def _now():
    return datetime.now(ZoneInfo("Asia/Seoul"))
def _once(opener):
    # Establish an HTTPS session for official attachments and opening results.
    try:_fetch(opener,OFFICIAL+"/",timeout=3)
    except Exception:pass
# These expected terms are a consistency CHECK for the current pinned test tender.
# They are never used as output values. Actual fields must come from the file.
TEST_TITLE_TOKENS=("철강·금속","인공지능전환","모니터링","소프트웨어 개발","용역")
TEST_AGENCY_TOKEN="전남테크노파크"

def _official_notice_fields(raw,ctype):
    """Require title and issuing authority actually inside downloaded G2B original."""
    doc,kind=_extract(raw,ctype)
    flattened=re.sub(r"\s+"," ",doc).strip()
    if not flattened or len(flattened)<100:
        raise ValueError("ORIGINAL_NOTICE_EXTRACTED_TEXT_UNAVAILABLE")
    def squish(x):
        return re.sub(r"\s+","",x)
    # Do not mistake the generic header '소액 수의 전자견적서 제출 공고'
    # for the title enclosed by <...> in the original notice.
    candidates=[x.strip(" \t\r\n<>〈〉") for x in re.findall(
        r"[<〈]\s*([^<>〈〉]{15,300}?)\s*[>〉]",flattened)]
    candidates.extend(x.strip() for x in re.findall(
        r"(?:사\s*업\s*명|공\s*고\s*명)\s*[:：]\s*(.{15,220}?)(?=\s+(?:나[.]|내\s*역\s*[:：]|장\s*소\s*[:：]|기초금액\s*[:：]))",
        flattened))
    title=next((x for x in candidates
                if all(squish(token) in squish(x) for token in TEST_TITLE_TOKENS)),None)
    agency_match=re.search(
        r"(?:수\s*요\s*기\s*관|발\s*주\s*기\s*관)\s*[:：]\s*"
        r"((?:\(\s*재\s*\)|재단법인)\s*전남\s*테크노파크)",
        flattened)
    # Some HWP document authors omit the separate '수요기관:' label and
    # print the issuer next to the official account signature.
    if agency_match:
        agency=agency_match.group(1).strip()
    else:
        name=re.search(r"((?:\(\s*재\s*\)|재단법인)\s*전남\s*테크노파크)",flattened)
        agency=name.group(1).strip() if name else None
    if not title or not agency or TEST_AGENCY_TOKEN not in squish(agency):
        raise ValueError("ORIGINAL_NOTICE_TITLE_OR_AGENCY_NOT_VERIFIED")
    budget_match=re.search(
        r"(?:기\s*초\s*금\s*액|예\s*산)\s*[:：]?\s*(?:일\s*금)?\s*"
        r"([\d,]{4,})\s*원",flattened)
    budget=budget_match.group(1).replace(",","") if budget_match else None
    return {"title":title,"agency":agency,"budget":budget,
            "official_fields_verified":True,
            "extracted_from":kind,
            "source_text_sha256":sha256(doc.encode("utf-8")).hexdigest()}

def _official_g2b_search():
    """Search the *actual* public G2B bid notices, not NURI's different list.

    The browser runs only for a user-started N01 execution. Verify the exact
    filtered POST and the response before accepting any listing evidence.
    """
    from g2b_bid_notice_site_search import run_search
    end=_now().date()
    start=end-timedelta(days=30)
    result=run_search(DETAIL,start.isoformat(),end.isoformat(),page=1)
    if result.get("status")!="partial_filtered_result" or result.get("search_request_verified") is not True:
        reason=str(result.get("reason") or result.get("status") or "unknown")
        raise ValueError("G2B_BID_NOTICE_LIVE_SEARCH_UNVERIFIED:"+reason[:130])
    explicit=list(result.get("matched_explicit_detail10") or [])
    pending=list(result.get("pending_original_detail10_verification") or [])
    all_rows=explicit+pending
    matched=next((r for r in all_rows
                  if r.get("bid_no")==CASE and r.get("bid_ord")=="000"),None)
    if matched is None:
        raise ValueError("TARGET_NOT_IN_G2B_VERIFIED_SEARCH_PAGE_1:"
                         +"returned="+str(len(all_rows))
                         +":official_total="+str(result.get("official_total")))
    title=str(matched.get("title") or "").strip()
    agency=str(matched.get("agency") or "").strip()
    if not title or not agency:
        raise ValueError("G2B_SEARCH_TARGET_TITLE_OR_AGENCY_MISSING")
    return {"bid_no":CASE,"bid_ord":"000","title":title,"agency":agency,
            "source":OFFICIAL+"/","verified_by":"official_g2b_bid_notice_search",
            "notice_list":"AVAILABLE","official_fields_verified":True,
            "search_request_verified":True,
            "search_request_window":result.get("request_window"),
            "search_page":result.get("page"),
            "live_search_endpoint":result.get("live_search_endpoint"),
            "returned_bid_ids":len(all_rows),
            "official_total":result.get("official_total"),
            "exact10_in_list_row_verified":matched in explicit,
            "source_notice_rows":all_rows[:20]}

def _live_notice(opener,preload=None):
    """Official G2B site listing first; HWP is only a *partial* fallback.

    NURI is a different procurement portal. A file for one pinned tender must
    never be presented as proof that the latest G2B notices were searched.
    """
    try:
        return _official_g2b_search()
    except Exception as source_error:
        log.warning("N01_G2B_LIST_UNVERIFIED reason=%s",
                    type(source_error).__name__+":"+str(source_error)[:170])
        for seq in (1,2):
            qs=urlencode({"bidPbancNo":CASE,"bidPbancOrd":"000","fileType":"",
                          "fileSeq":seq,"prcmBsneSeCd":"03"})
            url=ATTACH+"?"+qs
            try:
                raw,ctype=_fetch(opener,url,None,{"Referer":OFFICIAL+"/"})
                if not raw.startswith((b"\xd0\xcf\x11\xe0",b"%PDF",b"PK\x03\x04")):
                    raise ValueError("OFFICIAL_ORIGINAL_FILE_SIGNATURE_INVALID")
                fields=_official_notice_fields(raw,ctype)
                if preload is not None:preload[seq]=(raw,ctype)
                return {"bid_no":CASE,"bid_ord":"000",
                    "source":url,"verified_by":"official_original_text",
                    "source_file_sha256":sha256(raw).hexdigest(),
                    "source_file_bytes":len(raw),"source_file_seq":seq,
                    "notice_list":"UNAVAILABLE",
                    "notice_list_error":type(source_error).__name__+":"+str(source_error)[:170],
                    "warning":"G2B_CURRENT_LIST_UNVERIFIED_HWP_CASE_ONLY",
                    **fields}
            except Exception:
                continue
        raise ValueError("G2B_LIST_UNVERIFIED_AND_CASE_ORIGINAL_UNAVAILABLE:"
                         +type(source_error).__name__+":"+str(source_error)[:115])
def _live_attachments(opener,preload=None):
    out=[];texts=[]
    for seq in (1,2):
        qs=urlencode({"bidPbancNo":CASE,"bidPbancOrd":"000","fileType":"",
                      "fileSeq":seq,"prcmBsneSeCd":"03"})
        address=ATTACH+"?"+qs
        try:
            if preload and seq in preload:
                raw,ctype=preload[seq]
            else:
                raw,ctype=_fetch(opener,address,None,
                     {"Accept":"application/octet-stream,*/*","Referer":OFFICIAL+"/"})
            if raw[:20].lower().lstrip().startswith((b"<html",b"<!doctype")):
                raise ValueError("OFFICIAL_RETURNED_HTML_NOT_DOCUMENT")
            digest=sha256(raw).hexdigest()
            item={"file_seq":seq,"source":address,"sha256":digest,
                  "bytes":len(raw),"content_type":ctype}
            try:
                value,kind=_extract(raw,ctype)
                if not value.strip():raise ValueError("EXTRACTED_TEXT_EMPTY")
                item["format"]=kind;item["text_chars"]=len(value)
                texts.append(value)
            except Exception as exc:
                item["extraction_error"]=type(exc).__name__+":"+str(exc)[:100]
            out.append(item)
        except Exception as exc:
            out.append({"file_seq":seq,"source":address,"error":type(exc).__name__+":"+str(exc)[:110]})
    return out,texts
def _live_openings(opener):
    # Time-boxed selected-day live example. WebSquare server offers dates, not
    # a verified original-exact10 category filter: NEVER claim category match.
    today=_now()
    start=(today-timedelta(days=14)).strftime("%Y%m%d")
    end=today.strftime("%Y%m%d")
    payload={"dlSrchOnbsRsltClsfListInM":{
        "bidPbancNo":"","bidPbancOrd":"","bidPbancNm":"",
        "onbsYmdStr":start,"onbsYmdEnd":end,
        "prcmBsneSeCd":"0000 조070001 조070002 조070003 조070004 조070005",
        "frcpYn":"Y","rsrvYn":"Y","laseYn":"Y","chkBsneAllYn":"Y",
        "lastIndex":10,"firstIndex":1,"inqEnd":"","stepBarYn":"",
        "pbancKndCd":"공440002"}}
    headers={"Menu-Info":'{"menuNo":"01522","menuCangVal":"PBOC006_01","bsneClsfCd":"%EC%97%85130028","scrnNo":"02117"}',
             "submissionid":"mf_wfm_container_selectOnbsRsltClsfList",
             "Usr-Id":"null","Referer":OFFICIAL+"/"}
    result=_json_post(opener,OPENINGS,payload,headers)
    rows=result.get("onbsRsltClsfList") if isinstance(result,dict) else None
    if not isinstance(rows,list):raise ValueError("OFFICIAL_OPENING_LIST_SCHEMA_INVALID")
    return {"window":[start,end],"official_rows":len(rows),
            "sample":[{"bid_no":str(r.get("bidPbancNo") or "")[:24],
                       "bid_ord":str(r.get("bidPbancOrd") or "")[:8],
                       "title":str(r.get("bidPbancNm") or "")[:180],
                       "agency":str(r.get("dmstGrpNm") or r.get("dmstNm") or "")[:100]}
                      for r in rows[:10] if isinstance(r,dict)],
            "exact_detail10_verified":False,"complete_ten_year_history":False,
            "source":OPENINGS}
def _document(notice,files,assessment,openings,competition,cost,price):
    from docx import Document
    document=Document()
    document.add_heading("실제 나라장터 수집 · 9단계 검토 테스트",0)
    document.add_paragraph("자동 투찰·전자서명·입찰참가 없음. 직접 외부 수집한 원본 결과만 사용.")
    for label,value in (("공고번호",CASE),("공고명",(notice or {}).get("title")),
        ("기관",(notice or {}).get("agency")),("실행 시각",_now().isoformat())):
        document.add_paragraph(label+": "+str(value or "미확인"))
    for title,item in (("공식 첨부 확보",files),("자격·원문 조건",assessment),
        ("개찰 정보",openings),("경쟁 분석",competition),
        ("원가 증빙",cost),("가격 검증",price)):
        document.add_heading(title,level=1)
        document.add_paragraph(json.dumps(item,ensure_ascii=False,default=str)[:4200])
    buf=BytesIO();document.save(buf)
    return buf.getvalue()
def _begin_stage(run,index):
    with GUARD:
        run["active_node"]=f"N{index:02d}"
        run["active_title"]=STAGES[index-1]
        run["active_since"]=_now().isoformat()
        run["last_activity"]=_now().isoformat()
    log.info("LIVE9_STAGE_START run_id=%s node=N%02d",run["run_id"],index)

def _record(run,index,status,inp,output):
    with GUARD:
        run["steps"].append({"node":f"N{index:02d}","title":STAGES[index-1],
            "status":status,"input":inp,"output":output,"at":_now().isoformat()})
        run["completed_steps"]=index
        run["active_node"]=None
        run["active_title"]=""
        run["active_since"]=None
        run["last_activity"]=_now().isoformat()
        if status!="verified":run["partial_steps"]+=1
    log.info("LIVE9_STAGE_END run_id=%s node=N%02d status=%s",run["run_id"],index,status)
def _execute(run):
    global ACTIVE
    state={}
    try:
        opener=_client()
        _once(opener)
        preload={}
        _begin_stage(run,1)
        with GUARD:run["g2b_site_browser_search_attempted"]=True
        try:
            state["notice"]=_live_notice(opener,preload)
            if (not state["notice"].get("official_fields_verified")
                or not state["notice"].get("title")
                or not state["notice"].get("agency")):
                raise ValueError("N01_TITLE_AND_AGENCY_REQUIRED")
            status=("partial" if state["notice"].get("notice_list")=="UNAVAILABLE"
                    else "verified")
            _record(run,1,status,{"bid_no":CASE,"source":"official_g2b_live_site"},
                    state["notice"])
        except Exception as exc:
            state["notice"]=None
            _record(run,1,"source_error",{"bid_no":CASE},
                    {"error":type(exc).__name__+":"+str(exc)[:180],
                     "source":OFFICIAL+"/",
                     "continue_to":"N02"})
        _begin_stage(run,2)
        try:
            docs,texts=_live_attachments(opener,preload)
            state["docs"]=docs
            _record(run,2,"verified" if any("sha256" in v for v in docs)
                    else "source_error",
                    {"bid_no":CASE,"request":"official_attachments_1_2"},
                    {"files":docs,"downloaded":sum("sha256" in v for v in docs),
                     "text_extracted_files":len(texts)})
        except Exception as exc:
            docs,texts=[],[]
            state["docs"]=docs
            _record(run,2,"source_error",{"bid_no":CASE},
                    {"error":type(exc).__name__+":"+str(exc)[:180],
                     "continue_to":"N03"})
        _begin_stage(run,3)
        try:
            joined="\n".join(texts)
            found=[x for x in ("소프트웨어사업자","직접생산확인",
                "입찰참가자격","중소기업","소기업","지역제한") if x in joined]
            state["elig"]={"source":"downloaded_official_attachment_text_only",
                "requirement_keywords":found,
                "company_eligibility":"NOT_VERIFIED_NO_COMPANY_ORIGINAL",
                "document_text_chars":len(joined)}
            _record(run,3,"partial" if found else "blocked",
                    {"N02_downloaded_files":len(docs)},state["elig"])
        except Exception as exc:
            state["elig"]={"error":type(exc).__name__+":"+str(exc)[:180]}
            _record(run,3,"source_error",{"source":"N02"},
                    {**state["elig"],"continue_to":"N04"})
        _begin_stage(run,4)
        try:
            state["history"]=_live_openings(opener)
            _record(run,4,"partial",
                    {"source":"live_official_opening_only","detail10":DETAIL},
                    state["history"])
        except Exception as exc:
            state["history"]=None
            _record(run,4,"source_error",{"detail10":DETAIL},
                    {"error":type(exc).__name__+":"+str(exc)[:180],
                     "source":OPENINGS,"continue_to":"N05"})
        _begin_stage(run,5)
        try:
            state["competition"]={"source":"N04_live_official_opening",
                "raw_opening_rows":(state["history"] or {}).get("official_rows"),
                "exact10_matched_competitors":None,
                "confirmed_awards":None,
                "status":"HOLD_ORIGINAL_10DIGIT_MATCH_UNVERIFIED"}
            _record(run,5,"blocked",{"N04_status":"official_live_unfiltered"},
                    state["competition"])
        except Exception as exc:
            state["competition"]={"error":type(exc).__name__+":"+str(exc)[:180]}
            _record(run,5,"source_error",{"source":"N04"},state["competition"])
        _begin_stage(run,6)
        try:
            state["cost"]={"status":"MISSING_COMPANY_COST_EVIDENCE",
                "source":"official_tender_attachment_only",
                "bid_budget":(state["notice"] or {}).get("budget"),
                "verified_company_cost":None}
            _record(run,6,"blocked",{"N02_docs":len(docs)},state["cost"])
        except Exception as exc:
            state["cost"]={"error":type(exc).__name__+":"+str(exc)[:180]}
            _record(run,6,"source_error",{"source":"N02"},state["cost"])
        _begin_stage(run,7)
        try:
            state["price"]={"status":"NO_PRICE_RECOMMENDATION",
                "bid_budget":(state["notice"] or {}).get("budget"),
                "eligibility_verified":False,"cost_verified":False,
                "recommended_bid":None}
            _record(run,7,"blocked",
                    {"N03":state.get("elig"),"N06":state.get("cost")},
                    state["price"])
        except Exception as exc:
            state["price"]={"error":type(exc).__name__+":"+str(exc)[:180]}
            _record(run,7,"source_error",{"source":"N03+N06"},state["price"])
        _begin_stage(run,8)
        try:
            raw=_document(state.get("notice"),docs,state.get("elig"),
                          state.get("history"),state.get("competition"),
                          state.get("cost"),state.get("price"))
            with GUARD:run["_docx"]=raw
            _record(run,8,"partial",{"source":"N01-N07 live results"},
                    {"draft_generated":True,"bytes":len(raw),
                     "sha256":sha256(raw).hexdigest(),"draft_only":True})
        except Exception as exc:
            _record(run,8,"source_error",{"source":"N01-N07 live results"},
                    {"error":type(exc).__name__+":"+str(exc)[:180],
                     "draft_generated":False,"continue_to":"N09"})
        _begin_stage(run,9)
        _record(run,9,"partial",{"stage_count":8},
                {"verified_steps":sum(s["status"]=="verified" for s in run["steps"]),
                 "blocked_steps":sum(s["status"]=="blocked" for s in run["steps"]),
                 "source_errors":sum(s["status"]=="source_error" for s in run["steps"]),
                 "live_official_sources":[OFFICIAL+"/",ATTACH,OPENINGS],
                 "db_reads":0,"worker_calls":0,"g2b_site_browser_search_attempted":True,
                 "bid_submitted":False,"final_bid_approval":False})
        with GUARD:run["status"]="completed_with_missing_evidence"
    except Exception as exc:
        log.exception("LIVE_9_STAGE_UNEXPECTED_FAILURE run_id=%s",run["run_id"])
        # Ensure an interrupted stage has an explicit failure and the remaining
        # stages have explicit skipped entries, never an indefinite RUNNING state.
        msg=type(exc).__name__+":"+str(exc)[:180]
        first_failed=run["completed_steps"]+1
        for index in range(first_failed,10):
            _record(run,index,"source_error" if index==first_failed
                    else "not_executed",
                    {"reason":"UNEXPECTED_EXECUTOR_EXCEPTION"},
                    {"error":msg if index==first_failed
                     else "PRIOR_STAGE_FAILED_UNEXPECTEDLY"})
        with GUARD:
            run["status"]="failed"
            run["error"]=msg
    finally:
        with GUARD:
            run["active_node"]=None
            run["active_title"]=""
            run["active_since"]=None
            run["finished_at"]=_now().isoformat()
            ACTIVE=None
        log.info("LIVE9_FINISHED run_id=%s status=%s completed=%d",
                 run["run_id"],run["status"],run["completed_steps"])
def begin(sid,payload):
    global ACTIVE
    if not isinstance(payload,dict) or payload!={"bid_no":CASE,"detail10":DETAIL}:
        raise ValueError("EXACT_TEST_CASE_REQUIRED")
    with GUARD:
        if ACTIVE is not None:raise ValueError("LIVE_RUN_ALREADY_ACTIVE")
        rid=uuid.uuid4().hex
        state={"run_id":rid,"status":"running","mode":"on_demand_live_no_database",
            "case_bid_no":CASE,"detail10":DETAIL,"started_at":_now().isoformat(),
            "completed_steps":0,"partial_steps":0,"steps":[],
            "db_reads":0,"worker_calls":0,"g2b_site_browser_search_attempted":False,
            "bid_submitted":False}
        # Preserve all other sessions while this one runs. Prior RUNS.clear()
        # erased previous users' progress when a new test started.
        if len(RUNS)>=24:
            for key in list(RUNS):
                if key!=sid and RUNS[key].get("status")!="running":
                    del RUNS[key]
                    if len(RUNS)<24:break
        RUNS[sid]=state
        ACTIVE=rid
        worker=Thread(target=_execute,args=(state,),daemon=True,name="one_shot_live9")
        worker.start()
    return public(state)
def public(state):
    return {k:v for k,v in state.items() if k!="_docx"}
def current(sid):
    with GUARD:
        run=RUNS.get(sid)
        if not run:return {"status":"not_run","mode":"on_demand_live_no_database",
                           "completed_steps":0,"steps":[]}
        return public(run)
def document(sid,run_id):
    with GUARD:
        r=RUNS.get(sid)
        if not r or r["run_id"]!=run_id or "_docx" not in r:
            raise LookupError("LIVE_DRAFT_NOT_AVAILABLE")
        return r["_docx"]
