"""Real nine-stage public procurement Worker on ONE existing G2B tender.

Uses existing production PostgreSQL/collectors for all input. The run, stage
IDs, output and generated review DOCX are persisted to the original operational
database, not a separate mock runtime or invented n8n Execution ID.
No real G2B bid participation/signing/submission.
"""
from __future__ import annotations

from hashlib import sha256
import json

from db import session
from g2b_case_10y import CASE_BID
from g2b_search_first import filters,single_case_material,search_stored
from g2b_real_strategy import analyze_competition,classify_public_preparation

STEPS={
  1:"selected_notice",2:"cached_original_documents",3:"eligibility",
  4:"filtered_historical_openings",5:"real_competition",
  6:"documented_cost",7:"documented_price",8:"source_backed_document",
  9:"manual_readiness"
}
DRAFT_MEDIA="application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def ensure_schema():
    # This pipeline does not initialise 104 feature rows or 121 monthly windows.
    # It only reuses the original per-stage run/audit tables and creates one
    # real prepared-document table in the existing procureflow schema.
    with session() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_case_runs(
             id bigserial PRIMARY KEY,bid_no text NOT NULL,
             phase text NOT NULL,state text NOT NULL DEFAULT 'queued',
             result jsonb NOT NULL DEFAULT '{}'::jsonb,
             error text NOT NULL DEFAULT '',
             started_at timestamptz,finished_at timestamptz,
             created_at timestamptz NOT NULL DEFAULT now())""")
        con.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_case_events(
             id bigserial PRIMARY KEY,bid_no text NOT NULL,
             action text NOT NULL,details jsonb NOT NULL DEFAULT '{}'::jsonb,
             created_at timestamptz NOT NULL DEFAULT now())""")
        con.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_public_case_drafts(
           job_id bigint PRIMARY KEY REFERENCES procureflow.jobs(id),
           case_bid_no text NOT NULL,
           original_sha256 text NOT NULL,
           media_type text NOT NULL,
           draft_status text NOT NULL DEFAULT 'review_draft_not_submitted',
           content bytea NOT NULL,
           created_at timestamptz NOT NULL DEFAULT now())""")


def _record_start(job_id,index):
    phase=f"public9:{job_id}:{index:02}:{STEPS[index]}"
    with session() as con:
        row=con.execute("""INSERT INTO procureflow.g2b_case_runs(
             bid_no,phase,state,started_at)
             VALUES(%s,%s,'running',now()) RETURNING id""",
             (CASE_BID,phase)).fetchone()
    return row["id"]


def _record_end(run_id,job_id,index,status,result):
    if status not in ("verified","partial","blocked","error"):
        raise ValueError("INVALID_REAL_STAGE_STATE")
    raw=json.dumps(result,ensure_ascii=False,default=str)
    with session() as con:
        con.execute("""UPDATE procureflow.g2b_case_runs
           SET state=%s,result=%s::jsonb,
               error=%s,finished_at=now() WHERE id=%s""",
           (status,raw,
            str(result.get("error") or "")[:300] if status=="error" else "",
            run_id))
        con.execute("""INSERT INTO procureflow.g2b_case_events(
           bid_no,action,details)
           VALUES(%s,'real_public9_stage_finished',%s::jsonb)""",
           (CASE_BID,json.dumps({"job_id":job_id,"run_id":run_id,
              "step_id":index,"step":STEPS[index],"state":status},ensure_ascii=False)))


def _stage(job_id,index,task):
    run_id=_record_start(job_id,index)
    try:
        value,state,summary=task()
        summary={"step":STEPS[index],"case":CASE_BID,
                 "provenance":("official_g2b_websquare_and_existing_postgresql" if index==4 else "existing_operational_g2b_db"),**summary}
        _record_end(run_id,job_id,index,state,summary)
        return value,state,run_id
    except Exception as exc:
        error=type(exc).__name__+":"+str(exc)[:180]
        _record_end(run_id,job_id,index,"error",{
            "step":STEPS[index],"source":"existing_operational_g2b_db",
            "error":error,"no_synthetic_fallback":True})
        return None,"error",run_id


def _save_draft(job_id,raw):
    if not isinstance(raw,bytes) or len(raw)<500:
        raise ValueError("ACTUAL_DOCX_NOT_GENERATED")
    digest=sha256(raw).hexdigest()
    with session() as con:
        con.execute("""INSERT INTO procureflow.g2b_public_case_drafts(
            job_id,case_bid_no,original_sha256,media_type,content)
            VALUES(%s,%s,%s,%s,%s)
            ON CONFLICT(job_id) DO UPDATE SET
             original_sha256=excluded.original_sha256,content=excluded.content,
             created_at=now()""",(job_id,CASE_BID,digest,DRAFT_MEDIA,raw))
    return {"job_id":job_id,"sha256":digest,"size_bytes":len(raw),
            "draft_only":True,"bid_submitted":False}


def run_actual_public_case(job_id,config):
    """Run all nine real processing stages with actual worker/job and run IDs."""
    if type(job_id) is not int or job_id<=0 or not isinstance(config,dict):
        raise ValueError("VALID_EXISTING_WORKER_JOB_REQUIRED")
    f=filters(bid_no=config.get("bid_no"),detail10=config.get("detail10"),
              start=config.get("start"),end=config.get("end"),
              agency=config.get("agency",""),kind="opening",limit=50)
    ensure_schema()
    with session() as con:
        job=con.execute("""SELECT id FROM procureflow.jobs
            WHERE id=%s AND source='g2b_public_prepare' AND state='running'
            LIMIT 1""",(job_id,)).fetchone()
    if not job:
        raise ValueError("EXISTING_RUNNING_PUBLIC_PREPARE_JOB_NOT_FOUND")
    ids=[]
    def run(index,callback):
        value,state,stage_id=_stage(job_id,index,callback)
        ids.append({"step":index,"run_id":stage_id,"state":state})
        return value
    case=run(1,lambda: _notice())
    docs=run(2,lambda: _docs(case))
    from g2b_bid_package import evaluate_eligibility,documented_price_scenarios,proposal_contents,draft_docx
    from g2b_case_engine import cost_summary
    elig=run(3,lambda: _elig(evaluate_eligibility()))
    hist=run(4,lambda: _history(_bounded_existing_websquare_search(f)))
    strategy=run(5,lambda: _strategy(analyze_competition(
          f.start,f.end,f.agency,case=case)))
    cost=run(6,lambda: _cost(cost_summary()))
    price=run(7,lambda: _price(documented_price_scenarios()))
    def package_task():
        if not case or not isinstance(strategy,dict):
            raise ValueError("REAL_SOURCE_CASE_OR_STRATEGY_MISSING")
        package=proposal_contents(readiness_override={"status":"public_source_review","phases":[]})
        binary,_=draft_docx(contents=package,strategy=strategy,
                            source_clauses=case.get("source_clauses",[]))
        artifact=_save_draft(job_id,binary)
        return package,"partial",{"status":package.get("stage"),
              "actual_source_documents":len(package.get("document_index") or []),
              "stored_draft":artifact}
    package=run(8,package_task)
    def manual_task():
        if not isinstance(strategy,dict) or not isinstance(elig,dict) or not isinstance(price,dict) or not isinstance(package,dict):
            raise ValueError("ACTUAL_SOURCE_STAGES_INCOMPLETE")
        decision=classify_public_preparation(strategy,elig,price,package)
        return decision,"partial",{"status":decision["status"],
             "required_blockers":decision.get("hard_blockers",[]),
             "analysis_warnings":decision.get("analysis_warnings",[]),
             "manual_review":True}
    decision=run(9,manual_task)
    errors=[x for x in ids if x["state"]=="error"]
    return {"source":"real_existing_procureflow_worker",
        "job_id":job_id,"case_bid_no":CASE_BID,
        "state":"error" if errors else "completed_partial",
        "steps":ids,"actual_worker_stages":len(ids),
        "actual_historical_opening_rows":(hist or {}).get("summary",{}).get("opening_rows",0),
        "confirmed_awards":(strategy or {}).get("confirmed_award_observed",{}).get("award_rows",0),
        "status":(decision or {}).get("status","ERROR_SOURCE_EVIDENCE"),
        "draft_generated":bool(package),
        "errors":len(errors),"no_mock_sources":True,
        "official_n8n_execution_id":None,
        "requires_human_approval":True,
        "bid_submitted":False}


def _notice():
    case=single_case_material()
    if case.get("status")!="found":
        raise ValueError("SELECTED_ORIGINAL_TENDER_NOT_FOUND")
    return case,"verified",{"actual_notice":case["case_bid_no"],
          "source_title":case["notice"].get("title"),
          "documents_cached":case.get("document_count",0)}


def _docs(case):
    if not isinstance(case,dict):
        raise ValueError("ORIGINAL_TENDER_REQUIRED")
    files=case.get("documents",[])
    parsed=sum(1 for d in files if d.get("source_verified") and
               d.get("sha256") and d.get("extraction_state")=="parsed")
    status="verified" if parsed and parsed==len(files) else "partial"
    return files,status,{"files_found":len(files),"parsed_from_original":parsed,
        "clauses_extracted":len(case.get("source_clauses",[])),
        "redownloaded":False}


def _elig(e):
    status="verified" if e.get("status")=="eligible" else ("blocked" if e.get("status")=="ineligible" else "partial")
    return e,status,{"real_qualification_status":e.get("status","unknown"),
                  "evidence_present":e.get("requirements_evidence_present",False)}


def _bounded_existing_websquare_search(f):
    """Real selected-bid 9-stage: original-proven exact10 -> G2B WebSquare.

    The existing worker calls the existing direct opening and explicit
    final-award adapters for at most two previously verified notice IDs.
    This is not an exhaustive website-wide 10-year category discovery.
    """
    from g2b_search_first import collect_filtered_gaps
    enriched=collect_filtered_gaps(f,max_notices=2)
    prior=search_stored(f)
    prior["websquare_enrichment"]={
        "status":enriched.get("status"),
        "exact_detail10":enriched.get("exact_detail10"),
        "verified_notice_ids_queried":enriched.get("selected",0),
        "opening_notice_ids_queried":enriched.get("opening_notice_ids_queried",0),
        "final_award_notice_ids_queried":enriched.get("final_award_notice_ids_queried",0),
        "explicit_final_awards":enriched.get("explicit_final_awards",0),
        "errors":enriched.get("errors",[]),
        "website_10digit_server_search_verified":False,
        "ten_year_history_complete":False,
        "source":enriched.get("source")}
    return prior


def _history(h):
    n=h.get("summary",{}).get("opening_rows",0)
    enrichment=h.get("websquare_enrichment") or {}
    # Some official records do not prove historical category completeness.
    # Never mark a ten-year stage verified just because one bidder row exists.
    return h,"partial",{
       "source":h.get("source"),"verified_detail10":h.get("exact_detail10"),
       "actual_opening_rows":n,
       "verified_notice_rounds":h.get("summary",{}).get("source_notice_rounds",0),
       "real_websquare_opening_lookups":enrichment.get("opening_notice_ids_queried",0),
       "real_websquare_final_award_lookups":enrichment.get("final_award_notice_ids_queried",0),
       "explicit_final_awards":enrichment.get("explicit_final_awards",0),
       "websquare_source":enrichment.get("source"),
       "websquare_status":enrichment.get("status","not_run"),
       "websquare_errors":enrichment.get("errors",[]),
       "official_10digit_website_search_verified":False,
       "ten_year_search_complete":False,
       "ten_year_full_collection_required":False,
       "reason":"10자리 원본 검증 공고만 WebSquare 조회. 전체 세부종목 사이트 검색과 10년 완전성은 별도 검증 필요"}


def _strategy(a):
    n=a.get("observed",{}).get("opening_rows",0)
    return a,"verified" if n else "partial",{
       "actual_openings":n,
       "unique_named_competitors":a.get("observed",{}).get("distinct_name_strings",0),
       "confirmed_awards":a.get("confirmed_award_observed",{}).get("award_rows",0),
       "statistical_caveats":a.get("analysis_limitations",[])}


def _cost(c):
    n=len(c.get("documented_cost_rows") or [])
    return c,"verified" if c.get("ready") and n else "partial",{
       "documented_cost_line_items":n,"approved_bid_amount":c.get("approved_bid_amount"),
       "reason":c.get("reason","")}


def _price(p):
    state="partial" if p.get("status")=="draft_computed_not_approved" else "blocked"
    return p,state,{"status":p.get("status"),"missing":p.get("missing",[]),
                   "eligibility":p.get("eligibility"),
                   "approved_bid_price":p.get("recommended_bid_price")}


def read_actual_job(job_id):
    if type(job_id) is not int or job_id<=0:raise ValueError("INVALID_JOB_ID")
    with session() as con:
        j=con.execute("""SELECT id,state,checked,added,created_at,started_at,finished_at,
                          message,last_error
             FROM procureflow.jobs WHERE id=%s AND source='g2b_public_prepare'""",
             (job_id,)).fetchone()
        if not j:
            raise LookupError("PUBLIC_REAL_JOB_NOT_FOUND")
        records=con.execute("""SELECT id,phase,state,result,error,started_at,finished_at
             FROM procureflow.g2b_case_runs
             WHERE bid_no=%s AND phase LIKE %s
             ORDER BY id""",
             (CASE_BID,f"public9:{job_id}:%")).fetchall()
        draft=con.execute("""SELECT original_sha256,octet_length(content) AS size_bytes,
                          draft_status
             FROM procureflow.g2b_public_case_drafts WHERE job_id=%s""",
             (job_id,)).fetchone()
    def public_record(r):
        return {"run_id":r["id"],"step":r["phase"].split(":")[-1],
            "state":r["state"],"summary":r["result"],"error":r["error"],
            "started_at":str(r["started_at"] or ""),
            "finished_at":str(r["finished_at"] or "")}
    return {"job_id":job_id,"case_bid_no":CASE_BID,"job_state":j["state"],
            "created_at":str(j["created_at"]),"started_at":str(j["started_at"] or ""),
            "finished_at":str(j["finished_at"] or ""),
            "steps":[public_record(x) for x in records],
            "actual_stages_recorded":len(records),
            "draft":{"sha256":draft["original_sha256"],"bytes":draft["size_bytes"],
                     "state":draft["draft_status"]} if draft else None,
            "worker_job_id_is_not_n8n_execution_id":True,
            "bid_submitted":False}


def latest_actual_job():
    """Resume real one-tender job monitoring after reloading public workbench."""
    with session() as con:
        row=con.execute("""SELECT id FROM procureflow.jobs
             WHERE source='g2b_public_prepare' ORDER BY id DESC LIMIT 1""").fetchone()
    if not row:
        return {"last_job_id":None,"case_bid_no":CASE_BID,
                "actual_stages_recorded":0,"job_state":"not_run",
                "bid_submitted":False}
    result=read_actual_job(int(row["id"]))
    result["resumed_after_page_reload"]=True
    return result


def read_saved_docx(job_id):
    if type(job_id) is not int or job_id<=0:raise ValueError("INVALID_JOB_ID")
    with session() as con:
        row=con.execute("""SELECT content,original_sha256 FROM
          procureflow.g2b_public_case_drafts WHERE job_id=%s AND case_bid_no=%s""",
          (job_id,CASE_BID)).fetchone()
    if not row:raise LookupError("NO_REAL_CASE_REVIEW_DRAFT")
    return bytes(row["content"]),row["original_sha256"]
