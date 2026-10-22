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
def home():return (Path(__file__).parent/"static/index.html").read_text(encoding="utf-8")
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
        recent=conn.execute("SELECT id,source,state,current_page,checked,added,duplicates FROM procureflow.jobs ORDER BY id DESC LIMIT 10").fetchall()
    return {"status":"ok","database":"connected","counts":by_source,"recent_jobs":recent}

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
