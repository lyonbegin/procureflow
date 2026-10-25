import os,json,secrets
from datetime import datetime,timezone
from pathlib import Path
from fastapi import FastAPI,Header,HTTPException,Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from db import session,initialize
app=FastAPI(title="ProcureFlow",version="0.2")
from g2b_feature_api import router as g2b_feature_router
app.include_router(g2b_feature_router)
from g2b_workflow_ops import router as g2b_workflow_router
app.include_router(g2b_workflow_router)
from g2b_node_lab import router as g2b_node_lab_router
app.include_router(g2b_node_lab_router)
from g2b_dag_api import router as g2b_dag_router
app.include_router(g2b_dag_router)

# React Flow is the primary workbench; the preexisting FastAPI, DB and Worker
# retain ownership of every real operation. Built assets are shipped inside
# the same Railway Docker image (no new production service or Node server).
STUDIO_DIST = Path(__file__).resolve().parent / "static" / "studio"
if STUDIO_DIST.is_dir():
    app.mount("/studio", StaticFiles(directory=str(STUDIO_DIST), html=True), name="workflow-studio")

@app.on_event("startup")
def startup():
    initialize()
    from db import ensure_browser_diagnostics
    ensure_browser_diagnostics()
    from workbench import ensure_workbench
    ensure_workbench()
    from agent_orchestrator import ensure_agent_schema
    ensure_agent_schema()
    from g2b_categories import ensure_schema, recover_from_existing_raw
    ensure_schema()
    recover_from_existing_raw()
    from g2b_case_10y import ensure_schema as ensure_single_case_history
    ensure_single_case_history()
    from g2b_official_notices import ensure_notice_schema
    ensure_notice_schema()
    from g2b_documents import ensure_documents
    ensure_documents()
    from g2b_case_engine import ensure_engine
    ensure_engine()
    from g2b_node_lab import ensure_node_lab
    ensure_node_lab()
    from g2b_dag_api import ensure_dag_schema
    ensure_dag_schema()
    from g2b_exact_outcome_history import ensure_schema as ensure_exact_results
    ensure_exact_results()
    # One specific user-selected case only; import cited legacy notice evidence.
    with session() as db:
        observed=db.execute("""INSERT INTO procureflow.settings(key,value)
           VALUES ('g2b-case-81111599-old-notice-index-20261024-v1',
                   '{"provenance":"secondary_public_index_observed"}'::jsonb)
           ON CONFLICT(key) DO NOTHING RETURNING key""").fetchone()
    if observed:
        from g2b_case_10y import ingest_observed_secondary_sources
        ingest_observed_secondary_sources()
def guard(value):
    if os.getenv("TEST_MODE","0")=="1":
        return
    key=os.getenv("ADMIN_TOKEN","")
    if not key:raise HTTPException(503,"ADMIN_TOKEN not configured")
    if not secrets.compare_digest((value or "").removeprefix("Bearer ").strip(),key):
        raise HTTPException(401,"Access denied")
@app.get("/",response_class=HTMLResponse)
def home():
    """React Flow is the main UI; keep legacy UI available for operational continuity."""
    index=STUDIO_DIST/"index.html"
    if index.is_file():
        return FileResponse(index,media_type="text/html",headers={"Cache-Control":"no-cache"})
    # Non-Docker local Python development still serves the previous workbench.
    return (Path(__file__).parent/"static/workbench.html").read_text(encoding="utf-8")


@app.get("/flow", response_class=HTMLResponse)
def standalone_workflow_workspace():
    """Dedicated, viewport-filling React Flow editor/test workspace.

    Serve the same built client bundle as the main cockpit but independently
    at /flow; browser routing chooses its full-screen shell with NO side menus.
    Do not silently serve the legacy UI if the production bundle is absent.
    """
    index = STUDIO_DIST / "index.html"
    if not index.is_file():
        raise HTTPException(503, "React Flow studio build is not present")
    return FileResponse(
        index, media_type="text/html",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/legacy/workbench",response_class=HTMLResponse)
def legacy_procurement_workbench():
    """Preserve all existing browsing, collecting and tender-management controls."""
    return (Path(__file__).parent/"static/workbench.html").read_text(encoding="utf-8")


@app.get("/operations",response_class=HTMLResponse)
def operations_dashboard():
    raw=(Path(__file__).parent/"static/index.html").read_text(encoding="utf-8")
    return raw.replace("<main>","<main><section><a href='/'>입찰 통합관리</a> · <a href='/bids'>낙찰·개찰 결과</a> · <a href='/simulate'>입찰 사전검증</a> · <a href='/browser'>Headless 캡처</a></section>",1)

@app.get("/private-details",response_class=HTMLResponse)
def private_details_web():
    return (Path(__file__).parent/"static/private-details.html").read_text(encoding="utf-8")

@app.get("/bids",response_class=HTMLResponse)
def bid_results_web():
    return (Path(__file__).parent/"static/bids.html").read_text(encoding="utf-8")
@app.get("/health")
def health():
    try:
        with session() as c:c.execute("SELECT 1")
        return {"status":"ok","database":"connected","schema":"procureflow"}
    except Exception as e:raise HTTPException(503,{"status":"db_error","reason":type(e).__name__})
@app.get("/api/stats")
def stats(authorization:str|None=Header(None)):
    guard(authorization)
    with session() as c:
        t=c.execute("SELECT source,category,count(*) AS count FROM procureflow.tenders GROUP BY 1,2").fetchall()
        j=c.execute("SELECT state,count(*) AS count FROM procureflow.jobs GROUP BY 1").fetchall()
    return {"tenders":t,"jobs":j}
@app.get("/api/tenders")
def tenders(source:str="",q:str="",category:str="",limit:int=Query(100,ge=1,le=500),offset:int=Query(0,ge=0),authorization:str|None=Header(None)):
    guard(authorization)
    where=[];params=[]
    if source in ("g2b","kapt"):where.append("source=%s");params.append(source)
    if category:where.append("category=%s");params.append(category)
    if q:where.append("(title ILIKE %s OR agency ILIKE %s OR external_id ILIKE %s)");params += [f"%{q}%"]*3
    w=" WHERE "+" AND ".join(where) if where else ""
    with session() as c:
        n=c.execute("SELECT count(*) AS n FROM procureflow.tenders"+w,params).fetchone()["n"]
        rows=c.execute("SELECT source,external_id,title,agency,category,notice_date,deadline,status,method,source_url FROM procureflow.tenders"+w+" ORDER BY first_seen DESC LIMIT %s OFFSET %s",[*params,limit,offset]).fetchall()
    return {"total":n,"items":rows}
class RequestJob(BaseModel):
    source:str
    config:dict=Field(default_factory=dict)
@app.post("/api/jobs")
def create_job(job:RequestJob,authorization:str|None=Header(None)):
    guard(authorization)
    if job.source not in ("g2b","kapt"):raise HTTPException(400,"Unsupported source")
    if os.getenv("TEST_MODE","0")=="1":
        job.config["pages"]=min(max(1,int(job.config.get("pages",2))),2)
        job.config["days"]=min(max(1,int(job.config.get("days",30))),30)
    with session() as c:
        active=c.execute("SELECT id FROM procureflow.jobs WHERE source=%s AND state IN ('queued','running') LIMIT 1",(job.source,)).fetchone()
        if active:raise HTTPException(409,f"Job {active['id']} already active")
        jid=c.execute("INSERT INTO procureflow.jobs(source,config) VALUES (%s,%s::jsonb) RETURNING id",(job.source,json.dumps(job.config))).fetchone()["id"]
    return {"job_id":jid,"state":"queued"}
@app.get("/api/jobs")
def jobs(authorization:str|None=Header(None)):
    guard(authorization)
    with session() as c:items=c.execute("SELECT * FROM procureflow.jobs ORDER BY id DESC LIMIT 30").fetchall()
    return {"items":items}
@app.post("/api/jobs/{id}/cancel")
def cancel(id:int,authorization:str|None=Header(None)):
    guard(authorization)
    with session() as c:
        r=c.execute("UPDATE procureflow.jobs SET state='cancelled',finished_at=now() WHERE id=%s AND state IN ('queued','running') RETURNING id",(id,)).fetchone()
    return {"cancelled":bool(r)}

@app.get("/api/diagnostics")
def diagnostics():
    """Read-only aggregation for live deployment verification; no credentials or tender details."""
    with session() as conn:
        by_source=conn.execute("SELECT source,category, count(*) AS count FROM procureflow.tenders GROUP BY source,category ORDER BY source,category").fetchall()
        market=conn.execute("SELECT source,kind,count(*) AS count FROM procureflow.market_records GROUP BY source,kind ORDER BY source,kind").fetchall()
        recent=conn.execute("SELECT id,source,state,current_page,checked,added,duplicates FROM procureflow.jobs ORDER BY id DESC LIMIT 10").fetchall()
    return {"status":"ok","database":"connected","counts":by_source,"market_counts":market,"recent_jobs":recent}

@app.post("/api/diagnostics")
def diagnostics_probe():
    """Read-only database verification invoked by Railway test endpoint."""
    result=diagnostics()
    print("PROCUREFLOW_DIAGNOSTICS "+json.dumps(result,ensure_ascii=False,default=str),flush=True)
    return result

# Test operations use the same queue and original collector as the UI button.
TEST_SCENARIOS = {
    "g2b_smoke": {"source":"g2b","config":{"days":2,"pages":1,"categories":"both"},"title":"G2B one-page real collection"},
    "kapt_goods": {"source":"kapt","config":{"days":2,"pages":1,"categories":"goods"},"title":"K-apt goods only"},
    "kapt_service": {"source":"kapt","config":{"days":2,"pages":1,"categories":"service"},"title":"K-apt service only"},
    "kapt_repeat": {"source":"kapt","config":{"days":2,"pages":1,"categories":"both"},"title":"K-apt duplicate/idempotency retest"},
}
@app.get("/api/test/scenarios")
def test_scenarios():
    return {"items":[{"id":k,"title":v["title"],"source":v["source"],"config":v["config"]} for k,v in TEST_SCENARIOS.items()]}

@app.post("/api/test/run/{scenario_id}")
def test_run(scenario_id:str,authorization:str|None=Header(None)):
    guard(authorization)
    scenario=TEST_SCENARIOS.get(scenario_id)
    if not scenario: raise HTTPException(404,"Unknown test scenario")
    cfg={**scenario["config"],"test_scenario":scenario_id}
    with session() as c:
        active=c.execute("SELECT id FROM procureflow.jobs WHERE source=%s AND state IN ('queued','running') LIMIT 1",(scenario["source"],)).fetchone()
        if active:raise HTTPException(409,f"Source busy with job {active['id']}")
        jid=c.execute("INSERT INTO procureflow.jobs(source,config,message) VALUES (%s,%s::jsonb,%s) RETURNING id",(scenario["source"],json.dumps(cfg),scenario["title"])).fetchone()["id"]
    return {"job_id":jid,"scenario_id":scenario_id,"state":"queued"}

@app.get("/api/test/results")
def test_results(limit:int=Query(50,ge=1,le=200)):
    with session() as c:
        rows=c.execute("""SELECT id,source,config->>'test_scenario' AS scenario_id,
          state,checked,added,duplicates,current_page,message,last_error,created_at,started_at,finished_at
          FROM procureflow.jobs WHERE config ? 'test_scenario'
          ORDER BY id DESC LIMIT %s""",(limit,)).fetchall()
        counts=c.execute("SELECT source,count(*) AS count FROM procureflow.tenders GROUP BY source ORDER BY source").fetchall()
    return {"items":rows,"database_counts":counts}

@app.get("/api/site-probes")
def site_probes():
    """Read-only results from Railway Headless Chrome site reconnaissance."""
    with session() as c:
        rows=c.execute("SELECT key,value,updated_at FROM procureflow.settings WHERE key LIKE 'site-probe:%' ORDER BY key").fetchall()
    return {"items":[{"site":r["key"].split(":",1)[1],**r["value"],"saved_at":r["updated_at"]} for r in rows]}

class WishketRun(BaseModel):
    kind:str="portfolios"
    pages:int=Field(2,ge=1,le=40)
    limit:int=Field(30,ge=1,le=300)
    page_start:int=Field(1,ge=1,le=100000)
@app.post("/api/wishket/collect")
def wishket_collect(req:WishketRun,authorization:str|None=Header(None)):
    guard(authorization)
    if req.kind not in ("projects","partners","portfolios"):
        raise HTTPException(400,"Invalid kind")
    with session() as c:
        active=c.execute("SELECT id FROM procureflow.jobs WHERE source='wishket' AND state IN ('queued','running') LIMIT 1").fetchone()
        if active:raise HTTPException(409,"Wishket collector already running")
        jid=c.execute("INSERT INTO procureflow.jobs(source,config,message) VALUES ('wishket',%s::jsonb,'Wishket Chromium collection') RETURNING id",(json.dumps(req.model_dump()),)).fetchone()["id"]
    return {"job_id":jid,"state":"queued"}
@app.get("/api/wishket/records")
def wishket_records(kind:str="portfolios",q:str="",customer:str="",limit:int=Query(50,ge=1,le=500),offset:int=Query(0,ge=0)):
    if kind not in ("projects","partners","portfolios"):raise HTTPException(400,"Invalid kind")
    params=[kind];where="kind=%s"
    if q:where+=" AND (title ILIKE %s OR body ILIKE %s)";params.extend(["%"+q+"%"]*2)
    if customer:where+=" AND customers::text ILIKE %s";params.append("%"+customer+"%")
    with session() as c:
        total=c.execute("SELECT count(*) AS n FROM procureflow.wishket_records WHERE "+where,params).fetchone()["n"]
        items=c.execute("SELECT kind,source_id,title,url,customers,left(body,800) AS excerpt,updated_at FROM procureflow.wishket_records WHERE "+where+" ORDER BY updated_at DESC LIMIT %s OFFSET %s",params+[limit,offset]).fetchall()
    return {"total":total,"items":items}

# Additional private work sources. The source's own terms/access controls remain authoritative.
MARKET_SOURCES = {
 "freemoa":"development_demand",
 "freemoa_partners":"expert_supply",
 "freemoa_portfolios":"portfolio_reference",
 "wanted_gigs":"development_demand",
 "kmong_enterprise":"development_demand",
 "work24":"job_demand",
}
class MarketRun(BaseModel):
    source:str
    pages:int=Field(1,ge=1,le=20)
    limit:int=Field(8,ge=1,le=200)
    page_start:int=Field(1,ge=1,le=100000)
    queries:list[str]=Field(default_factory=list,max_length=12)

@app.get("/api/private/detail")
def private_full_detail(source:str,source_id:str="",kind:str="",
                        url:str="",authorization:str|None=Header(None)):
    """Return a single public record's full text and evidence metadata."""
    guard(authorization)
    if source=="wishket":
        if kind not in ("partners","portfolios","projects"):
            raise HTTPException(400,"Invalid Wishket kind")
        if not source_id:raise HTTPException(400,"source_id required")
        with session() as c:
            item=c.execute("""
                SELECT kind,source_id,title,url,body,customers,raw,updated_at
                FROM procureflow.wishket_records
                WHERE kind=%s AND source_id=%s
            """,(kind,source_id)).fetchone()
    elif source in ("freemoa","freemoa_partners","freemoa_portfolios",
                    "wishket_partner_reference",
                    "kmong_enterprise","work24","wanted_gigs"):
        if not source_id:raise HTTPException(400,"source_id required")
        with session() as c:
            item=c.execute("""
                SELECT source,kind,source_id,title,url,body,meta,last_seen
                FROM procureflow.market_records
                WHERE source=%s AND source_id=%s
            """,(source,source_id)).fetchone()
    else:
        raise HTTPException(400,"Unsupported private source")
    if not item:raise HTTPException(404,"No saved public detail for record")
    return {"record":item,"body_length":len(item["body"] or ""),
            "is_list_only":len((item["body"] or "").strip())<260}


@app.get("/api/private/linked-partners")
def publicly_linked_partners(q:str="",limit:int=Query(50,ge=1,le=200),
                             offset:int=Query(0,ge=0)):
    where="source='wishket_partner_reference' AND kind='public_portfolio_evidence'"
    vals=[]
    if q:
        where+=" AND (title ILIKE %s OR body ILIKE %s)"
        vals=[f"%{q}%",f"%{q}%"]
    with session() as c:
        total=c.execute("SELECT count(*) AS n FROM procureflow.market_records WHERE "+where,vals).fetchone()["n"]
        rows=c.execute("""
            SELECT source,kind,source_id,title,url,
                   LEFT(body,800) AS excerpt,meta,last_seen
            FROM procureflow.market_records
            WHERE """+where+" ORDER BY last_seen DESC LIMIT %s OFFSET %s",
            vals+[limit,offset]).fetchall()
    return {"total":total,"items":rows,
            "classification":"public portfolio-to-partner reference only; full partner profile requires login"}


@app.get("/api/private/schedule")
def private_supply_schedule_status():
    import private_supply_schedule
    return private_supply_schedule.status()


@app.get("/api/private/completeness")
def private_completeness():
    with session() as c:
        markets=c.execute("""
            SELECT source,kind,count(*) AS records,
                   count(*) FILTER (WHERE length(body)>=1000) AS detailed,
                   count(*) FILTER (WHERE source='freemoa_portfolios'
                       AND (coalesce(meta->>'verified_project_summary','false')='true'
                            OR body ILIKE '%%프로젝트 요약%%')
                       OR source<>'freemoa_portfolios' AND length(body)>=1000)
                       AS verified_public_details,
                   count(*) FILTER (WHERE source='freemoa_portfolios'
                       AND meta->>'origin'='public_javascript_portfolio_modal'
                       AND body NOT ILIKE '%%프로젝트 요약%%') AS list_only_artifacts,
                   count(*) FILTER (WHERE length(body)<260) AS sparse,
                   sum(length(body)) AS total_body_chars,
                   max(last_seen) AS latest
            FROM procureflow.market_records
            WHERE source IN ('freemoa_partners','freemoa_portfolios')
            GROUP BY source,kind
        """).fetchall()
        public_partner_links=c.execute("""
            SELECT count(*) AS linked_partners,
                   sum(coalesce(jsonb_array_length(meta->'public_portfolios'),0))
                       AS linked_portfolios,
                   count(*) FILTER (WHERE coalesce(meta->>'profile_access','')
                                        ='login_required') AS login_restricted
            FROM procureflow.market_records
            WHERE source='wishket_partner_reference'
              AND kind='public_portfolio_evidence'
        """).fetchone()
        wishket=c.execute("""
            SELECT kind,count(*) AS records,
                   count(*) FILTER (WHERE length(body)>=1000) AS detailed,
                   count(*) FILTER (WHERE length(body)<260) AS sparse,
                   sum(length(body)) AS total_body_chars,
                   max(updated_at) AS latest
            FROM procureflow.wishket_records
            WHERE kind IN ('partners','portfolios')
            GROUP BY kind
        """).fetchall()
    return {"freemoa":markets,"wishket":wishket,
            "wishket_public_partner_links":public_partner_links,
            "definition":"detailed means >=1000 saved public characters; Freemoa shorter records are publicly verified modal summaries, not complete project dossiers. Wishket partner profile bodies require login; linked public portfolios are separately counted and never represented as full profiles."}


@app.get("/api/market/sources")
def market_sources(authorization:str|None=Header(None)):
    guard(authorization)
    with session() as c:
        rows=c.execute("SELECT source,kind,count(*) AS count FROM procureflow.market_records GROUP BY 1,2").fetchall()
        probes=c.execute("SELECT key,value,updated_at FROM procureflow.settings WHERE key LIKE 'market-probe:%' ORDER BY key").fetchall()
    return {"sources":[{"id":key,"role":role,
       "records":sum(r['count'] for r in rows if r['source']==key),
       "probe":next((p['value'].get('status') for p in probes if p['key']=='market-probe:'+key),None)}
       for key,role in MARKET_SOURCES.items()]}

@app.get("/api/market/probes")
def market_probes(authorization:str|None=Header(None)):
    guard(authorization)
    with session() as c:
        rows=c.execute("SELECT key,value,updated_at FROM procureflow.settings WHERE key LIKE 'market-probe:%' AND key NOT IN ('market-probe:work24','market-probe:work24_jobs','market-probe:daangn','market-probe:daangn_cleaning','market-probe:kmong','market-probe:kmong_it','market-probe:soomgo','market-probe:soomgo_experts') ORDER BY key").fetchall()
    return {"items":[{"source":r['key'].split(':',1)[1],"diagnosis":r['value'],"saved_at":r['updated_at']} for r in rows]}

@app.post("/api/market/collect")
def market_collect(req:MarketRun,authorization:str|None=Header(None)):
    guard(authorization)
    if req.source not in MARKET_SOURCES:raise HTTPException(400,"Unsupported source")
    job_source="market_"+req.source
    with session() as c:
        active=c.execute("SELECT id FROM procureflow.jobs WHERE source=%s AND state IN ('queued','running') LIMIT 1",(job_source,)).fetchone()
        if active:raise HTTPException(409,"Source already has an active collection")
        jid=c.execute("INSERT INTO procureflow.jobs(source,config,message) VALUES (%s,%s::jsonb,%s) RETURNING id",
            (job_source,json.dumps(req.model_dump()),"Private source Headless Chromium collection")).fetchone()["id"]
    return {"job_id":jid,"source":req.source,"state":"queued"}

# Bid opening and award results are a separate lifecycle stage from notices.
# The official public-data service key is present only in Railway variables.
@app.get("/api/bids/status")
def bid_results_status():
    from g2b_bid_collector import configured
    with session() as c:
        rows=c.execute("""
            SELECT category,result_kind,count(*) AS count
            FROM procureflow.bid_results
            GROUP BY category,result_kind ORDER BY category,result_kind
        """).fetchall()
        summary=c.execute("""
            SELECT count(DISTINCT (bid_ntce_no,bid_ntce_ord)) AS distinct_executions,
                   count(*) FILTER (WHERE result_kind='opening_status') AS opening_status_rows,
                   count(*) FILTER (WHERE result_kind='opening') AS bidder_rows,
                   count(*) FILTER (WHERE result_kind='award') AS final_award_rows
            FROM procureflow.bid_results
        """).fetchone()
        last=c.execute("SELECT max(last_seen) AS latest FROM procureflow.bid_results").fetchone()
        jobs=c.execute("""
            SELECT id,source,state,checked,added,duplicates,
                   left(last_error,240) AS last_error,finished_at
            FROM procureflow.jobs WHERE source IN ('g2b_bid_results','g2b_final_awards')
            ORDER BY id DESC LIMIT 3
        """).fetchall()
    return {"status":"ok","api_key_configured":False,
            "api_key_required":False,
            "source":"나라장터 공개 개찰결과분류조회 웹 화면",
            "source_mode":"g2b_web_scrape",
            "source_page":"https://www.g2b.go.kr/",
            "counts":rows,"total":sum(x["count"] for x in rows),
            "distinct_executions":summary["distinct_executions"],
            "opening_status_rows":summary["opening_status_rows"],
            "bidder_rows":summary["bidder_rows"],
            "final_award_rows":summary["final_award_rows"],
            "last_updated":last["latest"],"recent_jobs":jobs,
            "bidder_ranks":"stored_when_publicly_available"}

@app.get("/api/bids")
def bid_results(category:str="",kind:str="",q:str="",bid_no:str="",
                limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0),
                authorization:str|None=Header(None)):
    guard(authorization)
    where=[];values=[]
    if category:
        if category not in ("goods","service","unspecified"):raise HTTPException(400,"Invalid category")
        where.append("category=%s");values.append(category)
    if kind:
        if kind not in ("award","opening","opening_status"):raise HTTPException(400,"Invalid kind")
        where.append("result_kind=%s");values.append(kind)
    if q:
        where.append("(title ILIKE %s OR company ILIKE %s OR agency ILIKE %s)")
        values.extend([f"%{q}%"]*3)
    if bid_no:
        where.append("bid_ntce_no=%s");values.append(bid_no)
    sql=(" WHERE "+" AND ".join(where)) if where else ""
    with session() as c:
        total=c.execute("SELECT count(*) AS n FROM procureflow.bid_results"+sql,values).fetchone()["n"]
        items=c.execute("""
            SELECT source,category,result_kind,operation,bid_ntce_no,bid_ntce_ord,
                   bid_clsfc_no,rbid_no,title,agency,company,amount,rate,rank,
                   participation_count,result_status,last_seen
            FROM procureflow.bid_results
        """+sql+" ORDER BY last_seen DESC LIMIT %s OFFSET %s",
            values+[limit,offset]).fetchall()
    return {"total":total,"items":items}

class BidCollectRun(BaseModel):
    days:int=Field(7,ge=1,le=31)
    pages:int=Field(1,ge=1,le=10)
    categories:list[str]=Field(default_factory=lambda:["goods","service"])
    kinds:list[str]=Field(default_factory=lambda:["award","opening"])
    bid_numbers:list[str]=Field(default_factory=list,max_length=60)

@app.post("/api/bids/collect")
def collect_bid_results(req:BidCollectRun,authorization:str|None=Header(None)):
    guard(authorization)
    # Uses public G2B WebSquare pages; no public-data OpenAPI key required.
    if not req.categories or any(x not in ("goods","service") for x in req.categories):
        raise HTTPException(400,"Invalid bid categories")
    if not req.kinds or any(x not in ("award","opening") for x in req.kinds):
        raise HTTPException(400,"Invalid bid result kinds")
    with session() as c:
        active=c.execute("""
            SELECT id FROM procureflow.jobs
            WHERE source='g2b_bid_results' AND state IN ('queued','running') LIMIT 1
        """).fetchone()
        if active:raise HTTPException(409,"Bid result collector already active")
        jid=c.execute("""
            INSERT INTO procureflow.jobs(source,config,message)
            VALUES ('g2b_bid_results',%s::jsonb,'Official G2B bid results: award and opening')
            RETURNING id
        """,(json.dumps(req.model_dump()),)).fetchone()["id"]
    return {"job_id":jid,"state":"queued","source":"g2b_bid_results"}

class AwardCollectRun(BaseModel):
    days:int=Field(21,ge=1,le=60)
    pages:int=Field(2,ge=1,le=5)
    limit:int=Field(30,ge=1,le=100)

@app.post("/api/bids/awards/collect")
def start_verified_final_award_collection(req:AwardCollectRun,
                                          authorization:str|None=Header(None)):
    guard(authorization)
    with session() as c:
        active=c.execute("""
          SELECT id FROM procureflow.jobs
          WHERE source='g2b_final_awards' AND state IN ('queued','running')
          LIMIT 1
        """).fetchone()
        if active:raise HTTPException(409,"Final-award web crawl already active")
        jid=c.execute("""
          INSERT INTO procureflow.jobs(source,config,message)
          VALUES ('g2b_final_awards',%s::jsonb,'Verified final award public web crawl')
          RETURNING id
        """,(json.dumps(req.model_dump()),)).fetchone()["id"]
    return {"job_id":jid,"state":"queued","source":"g2b_final_awards"}


@app.get("/api/bids/schedule")
def g2b_schedule_status():
    import g2b_schedule
    return {"enabled":os.getenv("G2B_AUTO_COLLECT","1")=="1",
            "recent_refresh_hours":g2b_schedule.REFRESH_HOURS,
            "archive_backfill_minutes":g2b_schedule.BACKFILL_MINUTES,
            "oldest_date":g2b_schedule.EARLIEST.isoformat(),
            "states":g2b_schedule.status(session)}


class BidHistoricalWindow(BaseModel):
    kind:str=Field("award",pattern="^(award|opening)$")
    start_date:str=Field(...,pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    end_date:str=Field(...,pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    page_start:int=Field(1,ge=1,le=10000)
    pages:int=Field(2,ge=1,le=10)


@app.post("/api/bids/history/collect")
def queue_historical_bid_window(req:BidHistoricalWindow,
                                 authorization:str|None=Header(None)):
    guard(authorization)
    from g2b_date_windows import window
    try:
        window(1,req.start_date,req.end_date,
               max_span_days=31 if req.kind=="opening" else 60)
    except (ValueError,TypeError) as ex:
        raise HTTPException(400,str(ex)) from None
    source=("g2b_bid_results" if req.kind=="opening"
            else "g2b_final_awards")
    cfg={"start_date":req.start_date,"end_date":req.end_date,
         "days":1,"page_start":req.page_start,
         "pages":min(req.pages,10 if req.kind=="opening" else 5)}
    if req.kind=="award":
        cfg["limit"]=min(100,cfg["pages"]*20)
    else:
        cfg["categories"]=["goods","service"]
        cfg["kinds"]=["opening","award"]
    with session() as c:
        busy=c.execute("""
            SELECT id FROM procureflow.jobs
            WHERE source=%s AND state IN ('queued','running')
            LIMIT 1
        """,(source,)).fetchone()
        if busy:raise HTTPException(409,"Source already collecting")
        jid=c.execute("""
            INSERT INTO procureflow.jobs(source,config,message)
            VALUES (%s,%s::jsonb,'Manual historical G2B web collection')
            RETURNING id
        """,(source,json.dumps(cfg))).fetchone()["id"]
    return {"job_id":jid,"source":source,"state":"queued","config":cfg}


@app.get("/api/analysis/summary")
def analysis_summary():
    """Aggregated live counts for the existing FastAPI dashboard.

    Public procurement, explicit development requests and hiring leads are
    kept separate. The sector labels describe the collected sample only;
    they are not national procurement statistics.
    """
    with session() as conn:
        public=conn.execute("""
            SELECT source,category,count(*) AS count
            FROM procureflow.tenders
            WHERE source IN ('g2b','kapt') AND category IN ('물품','일반용역')
            GROUP BY source,category ORDER BY source,category
        """).fetchall()
        market=conn.execute("""
            SELECT source,kind,count(*) AS count
            FROM procureflow.market_records
            WHERE source IN ('freemoa','freemoa_partners','freemoa_portfolios',
                             'wanted_gigs','kmong_enterprise','work24')
            GROUP BY source,kind ORDER BY source,kind
        """).fetchall()
        sectors=conn.execute("""
            SELECT kind,
                   COALESCE(NULLIF(meta->>'service_area',''),'unclassified') AS service_area,
                   count(*) AS count
            FROM procureflow.market_records
            WHERE source IN ('freemoa','kmong_enterprise','wanted_gigs','work24')
              AND kind IN ('development_demand','job_demand')
            GROUP BY kind,service_area ORDER BY count DESC,service_area
        """).fetchall()
        providers=conn.execute("""
            SELECT COALESCE(NULLIF(meta->>'information_provider',''),'unknown')
                       AS provider,count(*) AS count
            FROM procureflow.market_records
            WHERE source='work24' AND kind='job_demand'
            GROUP BY provider ORDER BY count DESC,provider
        """).fetchall()
        recent=conn.execute("""
            SELECT id,source,state,checked,added,duplicates,created_at
            FROM procureflow.jobs
            ORDER BY id DESC LIMIT 8
        """).fetchall()
    return {"status":"ok","public":public,"market":market,
            "service_areas":sectors,"work24_providers":providers,
            "recent_jobs":recent,
            "scope":"stored_records_not_national_statistics"}


@app.get("/api/market/records")
def market_records(source:str="",kind:str="",q:str="",demand_type:str="",service_area:str="",limit:int=Query(50,ge=1,le=200),
                   offset:int=Query(0,ge=0),authorization:str|None=Header(None)):
    guard(authorization)
    if source and source not in MARKET_SOURCES:raise HTTPException(400,"Unsupported source")
    where=["source NOT IN ('daangn','kmong','soomgo')"];args=[]
    if source:where.append("source=%s");args.append(source)
    if source=="freemoa_portfolios":
        where.append("(coalesce(meta->>'origin','')<>'public_javascript_portfolio_modal' "
                     "OR coalesce(meta->>'verified_project_summary','false')='true' "
                     "OR body ILIKE '%%프로젝트 요약%%')")
    if kind:where.append("kind=%s");args.append(kind)
    if q:where.append("(title ILIKE %s OR body ILIKE %s)");args.extend([f"%{q}%"]*2)
    if demand_type:where.append("meta->>'demand_type'=%s");args.append(demand_type)
    if service_area:where.append("meta->>'service_area'=%s");args.append(service_area)
    condition=" WHERE "+" AND ".join(where) if where else ""
    with session() as c:
        n=c.execute("SELECT count(*) AS n FROM procureflow.market_records"+condition,args).fetchone()['n']
        records=c.execute("SELECT source,kind,source_id,title,url,LEFT(body,1000) AS excerpt,meta,first_seen,last_seen FROM procureflow.market_records"+
            condition+" ORDER BY last_seen DESC LIMIT %s OFFSET %s",args+[limit,offset]).fetchall()
    return {"total":n,"items":records}


@app.get("/simulate",response_class=HTMLResponse)
def simulation_web():
    """Read-only case evaluation. Never redirects to a bid submission form."""
    return (Path(__file__).parent/"static/simulate.html").read_text(encoding="utf-8")


@app.get("/api/simulation/preview")
def bid_simulation_preview(source:str=Query(...,pattern="^(g2b|kapt)$"),
                           external_id:str=Query(...,min_length=1,max_length=120),
                           authorization:str|None=Header(None)):
    guard(authorization)
    from bid_simulation import preview
    try:
        result=preview(session,source,external_id)
        if source=="kapt" and external_id=="20261020165014951":
            from bid_price_engine import build_price_model
            cost=build_price_model()
            result["preliminary_price_model"]={
               "monthly_krw":cost["totals"]["monthly_total_krw"],
               "annual_krw":cost["totals"]["annual_total_krw"],
               "status":cost["validity"],
               "submission_ready":False,
               "model_url":"/api/simulation/price-preview",
               "proposal_url":"/api/simulation/proposal-draft",
               "editor_url":"/prepare"
            }
            for step in result["stages"]:
                if step["id"]=="cost_and_price":
                    step["state"]="partial"
                    step["observation"]="공고 OCR 원가 시나리오 계산 완료: 연 "+str(
                        cost["totals"]["annual_total_krw"])+"원 (비확정, 원본·실비 미검증)"
                    step["required_next"]="원본 지정 산출서, 직책수당, 보험·VAT, 대체인력 및 협력사 원가 검증"
                if step["id"]=="final_documents":
                    step["observation"]="8개 사업제안서 구간 작성 초안; 업체명·자격·인력·장비·서류 원본 미확정"
        return result
    except LookupError as exc:
        raise HTTPException(404,str(exc))
    except ValueError as exc:
        raise HTTPException(400,str(exc))


@app.get("/browser",response_class=HTMLResponse)
def browser_diagnostics_dashboard():
    return (Path(__file__).parent/"static/browser.html").read_text(encoding="utf-8")


class BrowserProbeRun(BaseModel):
    source:str=Field("kapt",pattern="^kapt$")
    external_id:str=Field(...,min_length=14,max_length=20)


@app.post("/api/browser/probes")
def request_browser_probe(req:BrowserProbeRun,authorization:str|None=Header(None)):
    """Bounded official K-apt public-only browser, no free-form URL or actions."""
    # Keep browser execution privileged even when legacy TEST_MODE=1.
    admin=os.getenv("ADMIN_TOKEN","")
    supplied=(authorization or "").removeprefix("Bearer ").strip()
    if not admin:raise HTTPException(503,"ADMIN_TOKEN not configured")
    if not secrets.compare_digest(supplied,admin):
        raise HTTPException(401,"Administrator authorization required")
    from db import ensure_browser_diagnostics
    from browser_diagnostics import validate_id
    try:validate_id(req.external_id)
    except ValueError as exc:raise HTTPException(400,str(exc))
    ensure_browser_diagnostics()
    with session() as db:
        active=db.execute("SELECT id FROM procureflow.jobs WHERE source='browser_probe' AND state IN ('queued','running') LIMIT 1").fetchone()
        if active:raise HTTPException(409,"Browser diagnostic job already active: "+str(active["id"]))
        jid=db.execute("""
          INSERT INTO procureflow.jobs(source,config,message)
          VALUES ('browser_probe',%s::jsonb,'Public K-apt readonly screenshot/DOM/network probe')
          RETURNING id
        """,(json.dumps(req.model_dump(),ensure_ascii=False),)).fetchone()["id"]
    return {"job_id":jid,"state":"queued","mode":"READ_ONLY_NO_BID_ACTIONS"}


@app.get("/api/browser/probes")
def browser_probe_list():
    with session() as db:
        rows=db.execute("""
          SELECT j.id,j.state,j.config->>'external_id' AS notice_id,j.checked,
                 j.added,j.created_at,j.started_at,j.finished_at,
                 left(j.last_error,400) AS last_error,
                 coalesce(r.report->>'status','') AS browser_status,
                 coalesce(r.report->>'participation_gate','') AS gate
          FROM procureflow.jobs j
          LEFT JOIN procureflow.browser_reports r ON r.job_id=j.id
          WHERE j.source='browser_probe'
          ORDER BY j.id DESC LIMIT 20
        """).fetchall()
    return {"items":rows,"engine":"internal_playwright","public_only":True,
            "submission_actions_allowed":False}


@app.get("/api/browser/probes/{job_id}")
def browser_probe_detail(job_id:int):
    with session() as db:
        job=db.execute("""
          SELECT id,state,config->>'external_id' AS notice_id,
                 checked,added,created_at,started_at,finished_at,
                 message,left(last_error,600) AS last_error
          FROM procureflow.jobs WHERE id=%s AND source='browser_probe'
        """,(job_id,)).fetchone()
        if not job:raise HTTPException(404,"Browser diagnostic job not found")
        report=db.execute("SELECT report FROM procureflow.browser_reports WHERE job_id=%s",(job_id,)).fetchone()
        captures=db.execute("""
          SELECT stage,created_at,octet_length(image) AS bytes,snapshot
          FROM procureflow.browser_captures
          WHERE job_id=%s ORDER BY created_at,stage
        """,(job_id,)).fetchall()
    return {
        "job":job, "report": report["report"] if report else None,
        "captures":[{**r,"screenshot_url":f"/api/browser/images/{job_id}/{r['stage']}"}
                    for r in captures],
        "unsafe_actions_executed":False
    }


@app.get("/api/browser/images/{job_id}/{stage}")
def browser_screenshot(job_id:int,stage:str):
    from fastapi.responses import Response
    if stage not in ("public_list","notice_detail","attachments_area","before_participation"):
        raise HTTPException(404,"Unknown capture stage")
    with session() as db:
        r=db.execute("""
          SELECT image,content_type FROM procureflow.browser_captures
          WHERE job_id=%s AND stage=%s
        """,(job_id,stage)).fetchone()
    if not r or not r["image"]:raise HTTPException(404,"Screenshot not available")
    return Response(content=bytes(r["image"]),media_type=r["content_type"],
                    headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})


@app.get("/api/browser/probes/{job_id}/summary")
def browser_probe_summary(job_id:int):
    """Compact JSON intended for direct automated QA and AI analysis."""
    with session() as db:
        j=db.execute("""
          SELECT id,state,config->>'external_id' AS notice_id,
                 checked,added,last_error,finished_at
          FROM procureflow.jobs
          WHERE id=%s AND source='browser_probe'
        """,(job_id,)).fetchone()
        if not j:raise HTTPException(404,"Browser probe not found")
        rr=db.execute("SELECT report FROM procureflow.browser_reports WHERE job_id=%s",(job_id,)).fetchone()
        captures=db.execute("""
          SELECT stage,octet_length(image) AS image_bytes,snapshot
          FROM procureflow.browser_captures WHERE job_id=%s
          ORDER BY created_at,stage
        """,(job_id,)).fetchall()
    report=rr["report"] if rr else {}
    return {
      "job":j, "status":report.get("status"),
      "unsafe_actions_executed":False,
      "blocked_network":report.get("blocked_network",[])[:50],
      "errors":report.get("errors",[])[:25],
      "screens":[
        {"step":c["stage"],"image_bytes":c["image_bytes"],
         "image_url":f"/api/browser/images/{job_id}/{c['stage']}",
         "title":c["snapshot"].get("title"),
         "content_length":c["snapshot"].get("content_length"),
         "text_excerpt":c["snapshot"].get("text","")[:1600],
         "attachment_links":c["snapshot"].get("link_candidates",[])[:20],
         "controls":c["snapshot"].get("controls",[])[:35],
         "tables":c["snapshot"].get("tables",[])[:3]}
        for c in captures
      ]
    }


@app.get("/api/browser/image-chunk/{job_id}/{stage}")
def browser_image_chunk(job_id:int,stage:str,
                        offset:int=Query(0,ge=0,le=2000000),
                        size:int=Query(22000,ge=1,le=30000)):
    """Base64 image chunks for AI clients that can read JSON but not binary URLs.

    Only public K-apt screenshots, bounded chunks. Never runs a new browser.
    """
    import base64
    if stage not in ("public_list","notice_detail","attachments_area","before_participation"):
        raise HTTPException(404,"Unknown screenshot stage")
    with session() as db:
        row=db.execute("""
          SELECT image FROM procureflow.browser_captures
          WHERE job_id=%s AND stage=%s
        """,(job_id,stage)).fetchone()
    if not row or not row["image"]:raise HTTPException(404,"Screenshot not stored")
    b64=base64.b64encode(bytes(row["image"])).decode("ascii")
    return {"job_id":job_id,"stage":stage,
            "offset":offset,"total":len(b64),
            "base64_chunk":b64[offset:offset+size],
            "has_more":offset+size<len(b64),
            "content_type":"image/jpeg"}


@app.get("/prepare",response_class=HTMLResponse)
def proposal_and_price_simulator_web():
    """Standalone staged pricing and written technical proposal review."""
    return (Path(__file__).parent/"static/bid_prepare.html").read_text(encoding="utf-8")


@app.get("/api/simulation/price-preview")
def tender_evidence_price_preview(
    external_id:str="20261020165014951",
    role_allowance_krw:int=Query(0,ge=0,le=1000000),
    relief_staff_monthly_krw:int=Query(0,ge=0,le=3000000),
    admin_pct:str=Query("3",min_length=1,max_length=8),
    profit_pct:str=Query("3",min_length=1,max_length=8),
    common_cost_scope:str=Query("site",pattern="^(site|each_worker)$"),
):
    from bid_price_engine import NOTICE_ID,build_price_model
    if external_id != NOTICE_ID:
        raise HTTPException(404,"No verified cost schedule for this notice")
    try:
        return build_price_model(
            role_allowance_krw=role_allowance_krw,
            relief_staff_monthly_krw=relief_staff_monthly_krw,
            admin_pct=admin_pct,profit_pct=profit_pct,
            common_cost_scope=common_cost_scope)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from None


@app.get("/api/simulation/price-scenarios")
def tender_pricing_scenarios(external_id:str="20261020165014951"):
    from bid_price_engine import NOTICE_ID,price_scenarios
    if external_id != NOTICE_ID:
        raise HTTPException(404,"No verified cost schedule for this notice")
    return {"notice_id":NOTICE_ID, "scenarios":price_scenarios(),
            "bid_ready":False,"submitted":False}


@app.get("/api/simulation/proposal-draft")
def tender_proposal_draft(external_id:str="20261020165014951"):
    from bid_price_engine import NOTICE_ID,proposal_draft
    if external_id != NOTICE_ID:
        raise HTTPException(404,"No verified requirements for this notice")
    return proposal_draft()


@app.get("/api/workbench/overview")
def procurement_workbench_overview(
    q:str=Query("",max_length=200),source:str=Query("",max_length=10),
    category:str=Query("",max_length=15),
    filter_state:str=Query("all",max_length=24),
    limit:int=Query(50,ge=1,le=100),
    offset:int=Query(0,ge=0,le=1000000)):
    """Public tender metadata and evidence counts. R..DD orders are excluded."""
    from workbench import overview
    return overview(q=q,source=source,category=category,
                    filter_state=filter_state,limit=limit,offset=offset)


@app.get("/api/workbench/case")
def procurement_workbench_case(
    source:str=Query(...,pattern="^(kapt|g2b)$"),
    external_id:str=Query(...,min_length=3,max_length=120)):
    """Actual stored evidence and outstanding requirements for one bid."""
    from workbench import case_detail
    try:
        return case_detail(source,external_id)
    except LookupError as exc:
        raise HTTPException(404,str(exc)) from None


class WorkbenchAction(BaseModel):
    source:str=Field(...,pattern="^(kapt|g2b)$")
    external_id:str=Field(...,min_length=3,max_length=120)
    action:str=Field(...,pattern="^(start|pause|resume)$")


@app.post("/api/workbench/cases/action")
def procurement_workbench_action(req:WorkbenchAction,
                               authorization:str|None=Header(None)):
    """Explicitly authorized workflow tracking and read-only K-apt capture."""
    token=os.getenv("ADMIN_TOKEN","")
    candidate=(authorization or "").removeprefix("Bearer ").strip()
    if not token:raise HTTPException(503,"ADMIN_TOKEN is not configured")
    if not secrets.compare_digest(candidate,token):
        raise HTTPException(401,"Administrator authorization required")
    from workbench import change_workflow
    try:
        return change_workflow(req.source,req.external_id,req.action)
    except LookupError as exc:
        raise HTTPException(404,str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from None


@app.get("/agents",response_class=HTMLResponse)
def autonomous_agent_monitor():
    """Live autonomous three-agent operations display (no user clicks needed)."""
    return (Path(__file__).parent/"static/agents.html").read_text(encoding="utf-8")


@app.get("/api/agents/live")
def autonomous_agents_live(
    event_limit:int=Query(90,ge=1,le=200),
):
    """PostgreSQL-backed near-real-time agent status, cases, and event log."""
    from agent_orchestrator import AGENT_COUNT,PHASES
    with session() as db:
        slots=db.execute("""
            SELECT a.slot_id,a.enabled,a.status,a.source,a.external_id,
              a.owner_id,a.phase,a.phase_label,a.progress,a.phase_total,
              a.current_action,a.last_error,a.started_at,a.heartbeat_at,
              a.lease_until,a.finished_cases,a.updated_at,
              t.title,t.agency,t.category,t.deadline,t.notice_date,
              c.state AS case_state,c.attempt AS case_attempt,
              c.verified AS case_verified,c.partial AS case_partial,
              c.missing AS case_missing,c.next_attempt_at,
              c.notes AS case_notes
            FROM procureflow.agent_slots a
            LEFT JOIN procureflow.tenders t
              ON t.source=a.source AND t.external_id=a.external_id
            LEFT JOIN procureflow.agent_cases c
              ON c.source=a.source AND c.external_id=a.external_id
            ORDER BY a.slot_id
        """).fetchall()
        events=db.execute("""
            SELECT id,slot_id,source,external_id,level,step,message,
                   meta,created_at
            FROM procureflow.agent_events
            ORDER BY id DESC LIMIT %s
        """,(event_limit,)).fetchall()
        case_counts=db.execute("""
            SELECT state,count(*) AS total FROM procureflow.agent_cases
            GROUP BY state ORDER BY state
        """).fetchall()
        recent_cases=db.execute("""
            SELECT c.source,c.external_id,t.title,t.agency,c.state,c.attempt,
                   c.verified,c.partial,c.missing,c.last_step,
                   c.last_finished_at,c.next_attempt_at,c.last_error
            FROM procureflow.agent_cases c
            JOIN procureflow.tenders t
              ON t.source=c.source AND t.external_id=c.external_id
            ORDER BY COALESCE(c.last_started_at,c.first_assigned_at) DESC
            LIMIT 35
        """).fetchall()
    return {
        "service":"procureflow-agents",
        "maximum_agents":AGENT_COUNT,
        "desired_concurrency":sum(1 for x in slots if x["enabled"]),
        "activated_agents":sum(1 for x in slots if x["enabled"]),
        "available_additions":sum(1 for x in slots if not x["enabled"]),
        "actual_running":sum(x["status"]=="running" for x in slots),
        "current_time_utc":datetime.now(timezone.utc).isoformat(),
        "refresh_interval_seconds":3,
        "slots":slots,
        "steps":[{"id":key,"label":label,"index":i+1}
                 for i,(key,label) in enumerate(PHASES)],
        "event_items":events,
        "case_counts":case_counts,
        "recent_cases":recent_cases,
        "AI_called":False,
        "proposal_submitted":False,
        "bid_participation_clicked":False,
        "read_only_public_browser":True,
        "case_done_means":"one_acquisition_pass_not_final_submission",
    }


@app.post("/api/agents/add")
def add_autonomous_tender_agent(authorization:str|None=Header(None)):
    """Only this explicit authorized user gesture activates ONE agent."""
    token=os.getenv("ADMIN_TOKEN","")
    candidate=(authorization or "").removeprefix("Bearer ").strip()
    if not token:raise HTTPException(503,"ADMIN_TOKEN is not configured")
    if not secrets.compare_digest(candidate,token):
        raise HTTPException(401,"Administrator authorization required")
    from agent_orchestrator import activate_one
    try:
        return activate_one()
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from None


@app.post("/api/agents/{slot_id}/stop")
def stop_autonomous_tender_agent(slot_id:int,authorization:str|None=Header(None)):
    """User can disable one slot; current read-only case finishes safely."""
    token=os.getenv("ADMIN_TOKEN","")
    candidate=(authorization or "").removeprefix("Bearer ").strip()
    if not token:raise HTTPException(503,"ADMIN_TOKEN is not configured")
    if not secrets.compare_digest(candidate,token):
        raise HTTPException(401,"Administrator authorization required")
    from agent_orchestrator import deactivate_one
    try:
        return deactivate_one(slot_id)
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from None


@app.get("/api/g2b/similarity/backtest")
def g2b_similarity_backtest():
    """Read-only historical walk-forward benchmark on real G2B PostgreSQL.

    Official opening dates only; no synthetic tender data, no background agent,
    no database mutations, and no auth-required write operation.
    """
    from g2b_similarity import run_postgres_backtest
    return run_postgres_backtest()



@app.get("/api/g2b/similarity/notice")
def g2b_historical_similarity_notice(
    bid_no:str=Query(...,min_length=12,max_length=16),
    bid_ord:str=Query("000",min_length=3,max_length=3)):
    """Explain one real historical G2B execution; strictly prior opening data."""
    from g2b_similarity import analyze_one_historical_bid
    try:
        return analyze_one_historical_bid(bid_no,bid_ord)
    except LookupError as exc:
        raise HTTPException(404,str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from None



@app.get("/api/g2b/categories/source-probe")
def g2b_category_source_probe(limit:int=Query(2,ge=1,le=5)):
    """Read-only verification of explicit classification fields in official G2B response."""
    from g2b_category_probe import probe_categories
    return probe_categories(limit)


@app.get("/api/g2b/categories/coverage")
def g2b_categories_coverage():
    from g2b_categories import coverage
    return coverage()


@app.get("/api/g2b/categories/similar")
def g2b_categories_similar(
    bid_no:str|None=None,bid_ord:str="000",
    detail_code:str|None=None,limit:int=Query(50,ge=1,le=200)):
    from g2b_categories import exact_matches
    try:
        return exact_matches(bid_no,bid_ord,detail_code,limit)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from None


@app.get("/api/g2b/categories/official-notice-probe")
def g2b_official_notice_probe():
    """Read-only official notice page field diagnostics."""
    from g2b_category_probe import probe_official_notice_detail
    return probe_official_notice_detail()


@app.get("/api/g2b/cases/R26BK01787028/history10y")
def g2b_selected_bid_history_10y(limit:int=Query(100,ge=1,le=1000)):
    """Selected tender only. Exact category 81111599, nationwide 2016-2026."""
    from g2b_case_10y import status
    return status(limit)


# ---- G2B 104-feature, one-case evidence-gated procurement workbench ----
@app.get("/api/g2b/full/status")
def full_g2b_feature_status():
    from g2b_feature_registry import FEATURES,features_by_group
    from g2b_official_notices import sync_status
    from g2b_case_engine import dashboard
    x=dashboard()
    return {"catalog_size":len(FEATURES),"case":x["case"]["bid_no"],
            "notice_ingestion":sync_status(),"phases":x["phases"],
            "counts":{
              "verified":sum(t["acceptance_state"]=="verified" for t in x["feature_acceptance"]),
              "partial":sum(t["acceptance_state"]=="partial" for t in x["feature_acceptance"]),
              "missing":sum(t["acceptance_state"]=="missing" for t in x["feature_acceptance"])
            },"complete":x["all_104_verified"],
            "submitted":False}

@app.get("/api/g2b/full/case")
def full_g2b_selected_case():
    from g2b_case_engine import dashboard
    return dashboard()

@app.get("/api/g2b/full/notices/status")
def full_g2b_notice_status():
    from g2b_official_notices import sync_status
    return sync_status()

@app.get("/api/g2b/full/documents")
def full_g2b_doc_status():
    from g2b_documents import list_documents
    return list_documents("R26BK01787028","000")

@app.get("/api/g2b/full/readiness")
def full_g2b_readiness():
    from g2b_case_engine import readiness_check
    return readiness_check()

@app.get("/api/g2b/full/price")
def full_g2b_price():
    from g2b_bid_package import documented_price_scenarios
    return documented_price_scenarios()

@app.get("/api/g2b/full/proposal")
def full_g2b_proposal():
    from g2b_bid_package import proposal_contents
    return proposal_contents()

@app.get("/api/g2b/full/proposal.docx")
def full_g2b_proposal_docx():
    from g2b_bid_package import draft_docx
    from fastapi.responses import Response
    binary,data=draft_docx()
    return Response(content=binary,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition":"attachment; filename=ProcureFlow-G2B-Draft.docx",
                 "X-ProcureFlow-Draft-Only":"true"})

class FullBidAction(BaseModel):
    phase:str=Field("all",pattern="^(all|discover|notice|ten_year|opening_details|exact_outcomes|documents|evidence|readiness)$")

@app.post("/api/g2b/full/run")
def full_g2b_run(req:FullBidAction,authorization:str|None=Header(None)):
    guard(authorization)
    with session() as db:
        active=db.execute("""SELECT id FROM procureflow.jobs
              WHERE source='g2b_full_case'
              AND state IN ('queued','running') LIMIT 1""").fetchone()
        if active:raise HTTPException(409,"G2B selected case already processing")
        config={"bid_no":"R26BK01787028","phase":req.phase}
        jid=db.execute("""INSERT INTO procureflow.jobs(source,config,message)
              VALUES('g2b_full_case',%s::jsonb,%s) RETURNING id""",
              (json.dumps(config,ensure_ascii=False),
               "G2B 104-stage selected tender workflow")).fetchone()["id"]
    return {"job_id":jid,"queued":True,"bid_no":"R26BK01787028","submitted":False}

class FullEvidenceInput(BaseModel):
    kind:str=Field(...,min_length=3,max_length=60)
    reference:str=Field(...,min_length=1,max_length=150)
    source_url:str=""
    structured:dict=Field(default_factory=dict)

@app.post("/api/g2b/full/evidence")
def full_case_evidence_input(req:FullEvidenceInput,authorization:str|None=Header(None)):
    guard(authorization)
    from g2b_case_engine import add_evidence
    try:
        # Manual content is recorded as received, not falsely 'official verified'.
        return add_evidence("R26BK01787028",req.kind,req.reference,
                            req.source_url,req.structured,False)
    except ValueError as exc:raise HTTPException(400,str(exc)) from None

class FullDecisionInput(BaseModel):
    kind:str=Field(...,min_length=3,max_length=60)
    key:str=Field(...,min_length=1,max_length=100)
    value:dict=Field(default_factory=dict)

@app.post("/api/g2b/full/decision")
def full_case_decision_input(req:FullDecisionInput,authorization:str|None=Header(None)):
    guard(authorization)
    from g2b_case_engine import put_decision
    try:return put_decision("R26BK01787028",req.kind,req.key,req.value)
    except ValueError as exc:raise HTTPException(400,str(exc)) from None


@app.get("/g2b-104-api",response_class=HTMLResponse)
def g2b_individual_feature_api_inspector():
    """Inspect the inputs, evidence and independently queued run of each function."""
    return (Path(__file__).parent/"static/g2b-feature-api.html").read_text(encoding="utf-8")


@app.get("/g2b-104",response_class=HTMLResponse)
def g2b_full_104_dashboard():
    """Actual 104-feature progress, never a fake completed bid."""
    return (Path(__file__).parent/"static/g2b-104.html").read_text(encoding="utf-8")


@app.get("/api/g2b/full/schedule")
def g2b_full_g2b_scheduled_status():
    from g2b_full_schedule import KEY
    from g2b_official_notices import api_key
    with session() as c:
        row=c.execute("SELECT value,updated_at FROM procureflow.settings WHERE key=%s",(KEY,)).fetchone()
    return {"enabled":True,"official_api_key_present":bool(api_key()),
            "secondary_public_category_crawler_active":False,
            "ten_year_exact_outcome_collector_active":True,
            "target_detail_product_code":"8111159901",
            "case":"R26BK01787028",
            "state":dict(row) if row else {},
            "official_10_year_complete":False,
            "ready_for_bid_submission":False}


@app.get("/api/g2b/full/category-index")
def g2b_full_category_index_progress():
    """Read the actual selected bid's public category search cursor and last jobs."""
    with session() as con:
        cursor=con.execute("""SELECT value,updated_at FROM procureflow.settings
              WHERE key='g2b:single:81111599:secondary_index_cursor'""").fetchone()
        jobs=con.execute("""SELECT id,state,added,checked,last_error,finished_at
              FROM procureflow.jobs WHERE source='g2b_full_case'
              AND config->>'phase'='ten_year'
              ORDER BY id DESC LIMIT 6""").fetchall()
        count=con.execute("""SELECT count(*) AS n FROM
              procureflow.g2b_case_10yr_history
              WHERE case_bid_no='R26BK01787028'
                AND classification8='81111599'""").fetchone()["n"]
    return {"selected_bid":"R26BK01787028","category8":"81111599",
            "historical_notices_stored":count,
            "cursor":dict(cursor) if cursor else None,
            "last_ten_year_jobs":jobs,
            "official_ten_year_coverage_complete":False,
            "secondary_index_not_full_official_coverage":True}


@app.get("/api/g2b/full/original-text")
def g2b_full_original_text(file_id:str=Query(...,pattern="^official_attached_[1-4]$")):
    """Actual publicly issued selected notice attachment, extracted from stored bytes."""
    with session() as c:
        x=c.execute("""SELECT file_id,filename,sha256,extraction_state,
                       extracted_text,url FROM procureflow.g2b_case_documents
                       WHERE bid_no='R26BK01787028' AND file_id=%s""",
                       (file_id,)).fetchone()
    if not x:raise HTTPException(404,"Original document not in database")
    return {"bid_no":"R26BK01787028","file_id":x["file_id"],
            "filename":x["filename"],"source_url":x["url"],
            "sha256":x["sha256"],"state":x["extraction_state"],
            "text":x["extracted_text"][:22000],
            "truncated":len(x["extracted_text"])>22000}


@app.get("/api/g2b/full/scope")
def g2b_full_actual_scope():
    """Two real HWP+XLSX workstreams; allocated budgets are NOT supplier quotes."""
    with session() as con:
        row=con.execute("""SELECT state,structured,source_url,content_sha,recorded_at
             FROM procureflow.g2b_case_evidence
             WHERE bid_no='R26BK01787028'
             AND evidence_type='scope_requirements'
             AND reference='hwp_real_scope'""").fetchone()
    if not row:
        return {"status":"waiting_for_original_scope_analysis",
                "bid_no":"R26BK01787028","actual_costs_known":False}
    return {"status":"source_verified","case":"R26BK01787028",
            "scope":row["structured"],"source_url":row["source_url"],
            "content_sha":row["content_sha"],"recorded_at":row["recorded_at"],
            "actual_supplier_costs_verified":False,"submitted":False}


@app.get("/api/g2b/full/historical-opening-matches")
def g2b_case_exact_verified_historical_bids(limit:int=Query(100,ge=1,le=500)):
    """Backward-compatible path returns only real 8111159901 results."""
    from g2b_exact_outcome_history import actual_result_status
    return actual_result_status(limit)

@app.get("/api/g2b/full/historical-opening-enrichment")
def g2b_full_official_opening_enrichment_status():
    """Actual official Nuri per-notice read outcomes, including no-result/error."""
    from g2b_historical_detail_enrich import ensure_schema
    ensure_schema()
    with session() as con:
        totals=con.execute("""SELECT status,count(*) AS notices,
                 sum(bidders) AS bidder_rows,
                 count(*) FILTER(WHERE winner_verified) AS winners
               FROM procureflow.g2b_case_opening_enrich_audit
               GROUP BY status ORDER BY status""").fetchall()
        examples=con.execute("""SELECT bid_no,status,attempt_count,bidders,
                   winner_verified,error,updated_at
               FROM procureflow.g2b_case_opening_enrich_audit
               ORDER BY updated_at DESC LIMIT 20""").fetchall()
    return {"case":"R26BK01787028","official_nuri_detail":True,
            "results":totals,"recent_checked":examples,
            "rank_1_not_confirmed_winner":True}


@app.get("/api/g2b/full/exact-outcomes")
def g2b_10_year_actual_opening_and_final_awards(
        limit:int=Query(150,ge=1,le=1000)):
    """Actual bid/award evidence ONLY for official-original verified 8111159901."""
    from g2b_exact_outcome_history import actual_result_status
    return actual_result_status(limit)
