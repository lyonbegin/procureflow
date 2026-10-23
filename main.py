import os,json,secrets
from pathlib import Path
from fastapi import FastAPI,Header,HTTPException,Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel,Field
from db import session,initialize
app=FastAPI(title="ProcureFlow",version="0.1")
@app.on_event("startup")
def startup(): initialize()
def guard(value):
    if os.getenv("TEST_MODE","0")=="1":
        return
    key=os.getenv("ADMIN_TOKEN","")
    if not key:raise HTTPException(503,"ADMIN_TOKEN not configured")
    if not secrets.compare_digest((value or "").removeprefix("Bearer ").strip(),key):
        raise HTTPException(401,"Access denied")
@app.get("/",response_class=HTMLResponse)
def home():
    raw=(Path(__file__).parent/"static/index.html").read_text(encoding="utf-8")
    return raw.replace("<main>","<main><section><a href='/bids'>나라장터 개찰·낙찰 결과 및 웹 수집 관리</a></section>",1)

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
    pages:int=Field(2,ge=1,le=500)
    limit:int=Field(30,ge=1,le=5000)
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
    queries:list[str]=Field(default_factory=list,max_length=12)

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
