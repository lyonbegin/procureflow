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
    if source in ("g2b","kapt","s2b"):where.append("source=%s");params.append(source)
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
