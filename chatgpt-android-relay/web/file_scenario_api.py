"""Real API-roundtrip synthetic file scenarios; never touches private user files.

GitHub Actions OIDC authorizes only a pinned main-branch manual workflow.
The runner must upload synthetic bytes over HTTPS, fetch back those exact
bytes, and report actual Chrome UI results from the saved account.
Public reads expose status only; no login secrets, prompts or file contents.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import api_v1
from gh_oidc import verify_file_scenario_identity

router = APIRouter(prefix="/integrations/v1/scenarios/files",
                   tags=["HITEL API real-file scenario evidence"])
GUARD = threading.RLock()
RUN = re.compile(r"^frun_[a-f0-9]{32}$")
ALLOWED_CASES = ("S08","S09","S10","S15","S11")
ALLOWED_STATUS = ("PASS","FAIL","BLOCKED","UNSUPPORTED")
DETAIL = re.compile(r"^[A-Z0-9_]{3,110}$")
DATA_DIR = api_v1.BASE / "file_scenario_api"
DATA_DIR.mkdir(parents=True, exist_ok=True)
MAX_RUNS_PER_DAY = 8

with api_v1.connection() as db:
    db.executescript("""
    CREATE TABLE IF NOT EXISTS hitel_file_scenario_runs(
      id TEXT PRIMARY KEY,
      status TEXT NOT NULL DEFAULT 'preparing',
      token_marker TEXT NOT NULL,
      github_run_id TEXT,
      result_json TEXT,
      transport_json TEXT,
      created_at INTEGER NOT NULL,
      completed_at INTEGER
    );
    CREATE TABLE IF NOT EXISTS hitel_file_scenario_bytes(
      run_id TEXT NOT NULL,
      role TEXT NOT NULL,
      name TEXT NOT NULL,
      sha256 TEXT NOT NULL,
      size INTEGER NOT NULL,
      relative_path TEXT NOT NULL,
      PRIMARY KEY(run_id,role)
    );
    CREATE INDEX IF NOT EXISTS idx_hitel_file_scenario_created
      ON hitel_file_scenario_runs(created_at DESC);
    """)


def signed_workflow(authorization: Annotated[str | None,Header()] = None) -> bool:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401,"GitHub Actions OIDC authentication required")
    token=authorization[7:]
    if not verify_file_scenario_identity(token):
        raise HTTPException(403,"Untrusted workflow identity")
    return True


def _get_run(db, run_id):
    if not RUN.fullmatch(run_id):
        raise HTTPException(404,"Unknown synthetic scenario run")
    r=db.execute("SELECT * FROM hitel_file_scenario_runs WHERE id=?",
                 (run_id,)).fetchone()
    if not r:
        raise HTTPException(404,"Unknown synthetic scenario run")
    return r


def _manifest(run_id, marker):
    return {
        "txt":{"name":"hitel_trial_generated.txt",
               "body":"HITEL_TEST_KEY="+marker+
                      "\nThis note contains synthetic test data only.\n"},
        "csv":{"name":"hitel_trial_generated.csv",
               "body":"item,count\napple,3\npear,5\n"},
    }


def _status(r, with_marker=False):
    result=json.loads(r["result_json"]) if r["result_json"] else None
    proof=json.loads(r["transport_json"]) if r["transport_json"] else None
    names={
      "S08":"Upload synthetic TXT via API and show ChatGPT attachment",
      "S09":"Remove API-delivered unsent TXT attachment",
      "S10":"Ask ChatGPT to read API-delivered TXT",
      "S15":"Ask ChatGPT to analyze API-delivered CSV (sum 8)",
      "S11":"Download actual generated CSV from ChatGPT",
    }
    by_id={x["id"]:x for x in (result or {}).get("results",[])}
    cases=[{"id":k,"name":names[k],
            "status":by_id[k]["status"] if k in by_id else "PENDING",
            "detail":by_id[k]["detail"] if k in by_id else "AWAITING_ACTUAL_TEST"}
           for k in ALLOWED_CASES]
    data={
      "run_id":r["id"],"status":r["status"],
      "created_at":r["created_at"],"completed_at":r["completed_at"],
      "github_actions_url":(
          "https://github.com/lyonbegin/procureflow/actions/runs/"+r["github_run_id"]
          if r["github_run_id"] else None),
      "transport":proof,
      "cases":cases,
      "summary":{s:sum(x["status"]==s for x in cases)
                 for s in ("PASS","FAIL","BLOCKED","UNSUPPORTED","PENDING")},
      "all_pass":bool(result) and all(x["status"]=="PASS" for x in cases),
      "scope":"Isolated synthetic files. Native public ChatGPT file API is not yet supported.",
    }
    if with_marker:
        data["synthetic_test_marker"]=r["token_marker"]
    return data


@router.get("/latest")
def latest():
    """Public, sanitized result board with no actual user content."""
    with api_v1.connection() as db:
        r=db.execute("SELECT * FROM hitel_file_scenario_runs "
                     "ORDER BY created_at DESC LIMIT 1").fetchone()
    if not r:
        return {"status":"never_run","cases":[{"id":k,"status":"PENDING"} for k in ALLOWED_CASES]}
    return _status(r)


@router.get("/runs/{run_id}")
def get_run_status(run_id: str):
    with api_v1.connection() as db:
        r=_get_run(db,run_id)
    return _status(r)


@router.post("/runs",status_code=201)
def create_run(verified=Depends(signed_workflow)):
    """Only the real signed manual GitHub Actions job can create a run."""
    now=api_v1.clock()
    with GUARD:
        with api_v1.connection() as db:
            recent=db.execute(
              "SELECT COUNT(*) FROM hitel_file_scenario_runs WHERE created_at>?",
              (now-86400000,)).fetchone()[0]
            if recent>=MAX_RUNS_PER_DAY:
                raise HTTPException(429,"Synthetic browser test daily cap reached")
            active=db.execute(
                "SELECT id,status,created_at FROM hitel_file_scenario_runs "
                "WHERE status IN ('preparing','running') "
                "ORDER BY created_at DESC LIMIT 1").fetchone()
            if active:
                if active["status"]=="preparing" and active["created_at"]<now-60000:
                    # Previous workflow failed while uploading test bytes.
                    # Keep its history; never silently delete it.
                    db.execute(
                        "UPDATE hitel_file_scenario_runs "
                        "SET status='abandoned',completed_at=? WHERE id=?",
                        (now,active["id"]))
                elif active["status"]=="running" and active["created_at"]<now-1800000:
                    db.execute(
                        "UPDATE hitel_file_scenario_runs "
                        "SET status='timed_out',completed_at=? WHERE id=?",
                        (now,active["id"]))
                else:
                    raise HTTPException(409,"Synthetic file scenario already active")
            run_id="frun_"+api_v1.new_id()
            marker="HITEL_FILE_"+secrets.token_hex(4).upper()+"_795"
            db.execute(
                "INSERT INTO hitel_file_scenario_runs(id,status,token_marker,created_at) "
                "VALUES(?,?,?,?)",
                (run_id,"preparing",marker,now))
    return {"run_id":run_id,"status":"preparing",
            "manifest":_manifest(run_id,marker)}


@router.post("/runs/{run_id}/files/{role}")
def upload_synthetic_file(run_id: str, role: str,
                          file: UploadFile = File(...),
                          verified=Depends(signed_workflow)):
    """The real input bytes must cross HTTPS and be hashed on the server."""
    if role not in ("txt","csv"):
        raise HTTPException(422,"Only txt and csv synthetic tests allowed")
    with GUARD:
        with api_v1.connection() as db:
            r=_get_run(db,run_id)
            if r["status"]!="preparing":
                raise HTTPException(409,"Run is not accepting inputs")
            if db.execute(
               "SELECT 1 FROM hitel_file_scenario_bytes WHERE run_id=? AND role=?",
               (run_id,role)).fetchone():
                raise HTTPException(409,"Duplicate synthetic test upload")
            expected=_manifest(run_id,r["token_marker"])[role]
            if file.filename!=expected["name"]:
                raise HTTPException(422,"Unexpected synthetic filename")
            original=file.file.read(4097)
            if len(original)>4096 or original!=expected["body"].encode("utf-8"):
                raise HTTPException(422,"Input does not match synthetic test manifest")
            hashed=hashlib.sha256(original).hexdigest()
            target=DATA_DIR/(run_id+"_"+role+("."+"txt" if role=="txt" else ".csv"))
            target.write_bytes(original)
            db.execute(
              "INSERT INTO hitel_file_scenario_bytes VALUES(?,?,?,?,?,?)",
              (run_id,role,expected["name"],hashed,len(original),target.name))
    return {"run_id":run_id,"role":role,"size":len(original),
            "sha256":hashed,"stored":True}


@router.get("/runs/{run_id}/files/{role}/content")
def fetch_synthetic_file(run_id: str, role: str,
                         verified=Depends(signed_workflow)):
    """Download exact server-stored bytes; the browser must use THIS copy."""
    if role not in ("txt","csv"):
        raise HTTPException(404,"Synthetic role not found")
    with api_v1.connection() as db:
        _get_run(db,run_id)
        row=db.execute(
            "SELECT name,relative_path,sha256,size FROM hitel_file_scenario_bytes "
            "WHERE run_id=? AND role=?",(run_id,role)).fetchone()
    if not row or not (DATA_DIR/row["relative_path"]).is_file():
        raise HTTPException(404,"Synthetic file bytes missing")
    return FileResponse(DATA_DIR/row["relative_path"],filename=row["name"],
                        headers={"Cache-Control":"no-store",
                                 "X-Synthetic-SHA256":row["sha256"]})


class ResultItem(BaseModel):
    id: str = Field(max_length=5)
    name: str = Field(max_length=160)
    status: str = Field(max_length=12)
    detail: str = Field(max_length=110)


class TransportProof(BaseModel):
    uploaded_via_api: bool
    downloaded_via_api: bool
    sha256_match: bool
    saved_chatgpt_account_verified: bool


class ResultSubmission(BaseModel):
    github_run_id: str = Field(pattern=r"^\d{5,20}$")
    transport: TransportProof
    results: list[ResultItem] = Field(min_length=5,max_length=5)


@router.post("/runs/{run_id}/results")
def submit_results(run_id: str, data: ResultSubmission,
                   verified=Depends(signed_workflow)):
    """Persist verifiable per-case results; FAIL/BLOCKED remain visible."""
    ids=[x.id for x in data.results]
    if sorted(ids)!=sorted(ALLOWED_CASES):
        raise HTTPException(422,"Five unique known case IDs are required")
    if any(x.status not in ALLOWED_STATUS or not DETAIL.fullmatch(x.detail)
           for x in data.results):
        raise HTTPException(422,"Unsafe scenario result shape")
    check=data.transport
    proof={"uploaded_via_api":check.uploaded_via_api,
           "downloaded_via_api":check.downloaded_via_api,
           "sha256_match":check.sha256_match,
           "saved_chatgpt_account_verified":check.saved_chatgpt_account_verified}
    transport_ok=all(proof.values())
    with GUARD:
        with api_v1.connection() as db:
            r=_get_run(db,run_id)
            if r["result_json"]:
                raise HTTPException(409,"Run already has a finalized report")
            required=db.execute(
                "SELECT COUNT(*) FROM hitel_file_scenario_bytes WHERE run_id=?",
                (run_id,)).fetchone()[0]
            if required!=2:
                raise HTTPException(409,"Two API-uploaded synthetic files required")
            safe=[]
            for case in data.results:
                # Never report a PASS for a remote-API file case when
                # original bytes or real account verification failed.
                status=case.status if transport_ok else "BLOCKED"
                detail=case.detail if transport_ok else "API_OR_ACCOUNT_PROOF_MISSING"
                safe.append({"id":case.id,"name":case.name,
                             "status":status,"detail":detail})
            final={
                "results":safe,
                "summary":{status:sum(x["status"]==status for x in safe)
                           for status in ALLOWED_STATUS}}
            db.execute(
              "UPDATE hitel_file_scenario_runs "
              "SET status=?, github_run_id=?, result_json=?, transport_json=?, completed_at=? "
              "WHERE id=?",
              ("completed" if all(x["status"]=="PASS" for x in safe) else "incomplete",
               data.github_run_id,json.dumps(final),
               json.dumps(proof),api_v1.clock(),run_id))
            saved=_get_run(db,run_id)
    return _status(saved)


@router.get("/view",include_in_schema=False)
def public_file_scenario_dashboard():
    """Human-readable live API evidence, rendered server-side without JS."""
    from datetime import datetime, timedelta, timezone
    from html import escape
    from fastapi.responses import HTMLResponse
    with api_v1.connection() as db:
        row=db.execute("SELECT * FROM hitel_file_scenario_runs "
                       "ORDER BY created_at DESC LIMIT 1").fetchone()
    if row:
        data=_status(row)
        rows="".join(
          "<tr><td><code>"+escape(c["id"])+"</code></td>"
          "<td>"+escape(c["name"])+"</td>"
          "<td><strong class='"+("pass" if c["status"]=="PASS" else "blocked")+"'>"
          +escape(c["status"])+"</strong></td>"
          "<td><code>"+escape(c["detail"])+"</code></td></tr>"
          for c in data["cases"])
        proof=data["transport"] or {}
        def status(value):
            return "PASS" if value is True else "NOT VERIFIED"
        uploaded=status(proof.get("uploaded_via_api"))
        downloaded=status(proof.get("downloaded_via_api"))
        integrity=status(proof.get("sha256_match"))
        identity=status(proof.get("saved_chatgpt_account_verified"))
        tz=timezone(timedelta(hours=9))
        stamp=(datetime.fromtimestamp(row["created_at"]/1000,tz)
               .strftime("%Y-%m-%d %H:%M:%S KST"))
        total=len(data["cases"])
        passed=data["summary"]["PASS"]
        latest_state=escape(data["status"])
        action_link=data["github_actions_url"]
        if action_link:
            gh="<a href='"+escape(action_link,quote=True)+"' rel='noopener noreferrer'>실제 GitHub Actions 로그</a>"
        else:
            gh="GitHub 실행 ID 대기 중"
        report_href=("/integrations/v1/scenarios/files/runs/"
                     +escape(data["run_id"],quote=True))
        summary=f"""
        <p class="note">실제 GitHub Chrome을 사용한 HTTPS API 파일 왕복 시험 결과입니다.</p>
        <div class="score"><strong>{passed} / {total}</strong> 시나리오 PASS
          <span>상태: {latest_state}</span></div>
        <p>실행: <code>{escape(data["run_id"])}</code> · {stamp}</p>
        <div class="metrics">
          <div><b>HTTPS 업로드</b><span>{uploaded}</span></div>
          <div><b>HTTPS 원본 재다운로드</b><span>{downloaded}</span></div>
          <div><b>SHA-256 원본 일치</b><span>{integrity}</span></div>
          <div><b>실제 ChatGPT 계정 일치</b><span>{identity}</span></div>
        </div>
        <table><thead><tr><th>ID</th><th>실제 동작</th><th>결과</th><th>근거 코드</th></tr></thead>
        <tbody>{rows}</tbody></table>
        <p>{gh} · <a href="{report_href}">API JSON 원본 증거</a></p>
        """
    else:
        summary="<p>아직 실제 GitHub Actions API 파일 시험 결과가 없습니다.</p>"
    html=f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HITEL 외부 API 파일 시나리오 실측 결과</title>
<style>
:root{{font-family:system-ui,-apple-system,"Malgun Gothic",sans-serif;
color:#1b293c;background:#f4f7fa}}
body{{margin:0}}main{{max-width:1050px;margin:auto;padding:24px 18px 80px}}
h1{{font-size:clamp(24px,3.6vw,36px);margin-bottom:8px}}
.note{{color:#596b80}}a{{color:#1562a5}}
.panel{{background:white;border:1px solid #dce4ec;border-radius:10px;
padding:20px;margin-top:16px}}
.score{{border-top:1px solid #e4eaf1;border-bottom:1px solid #e4eaf1;
margin:18px 0;padding:14px 0;font-size:17px;display:flex;gap:20px;
flex-wrap:wrap;align-items:center}}
.score strong{{font-size:28px}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}}
.metrics div{{padding:12px;background:#f1f5f9;border-radius:6px}}
.metrics b,.metrics span{{display:block;font-size:13px}}
.metrics span{{font-weight:700;margin-top:5px}}
table{{width:100%;border-collapse:collapse;margin:20px 0;font-size:14px}}
th,td{{border-bottom:1px solid #dfe5ed;text-align:left;padding:12px 9px}}
th{{background:#eef3f7}}
.pass{{color:#0b7545}}.blocked{{color:#ad4c18}}
code{{word-break:break-word;font-size:12px}}
.warning{{border-left:4px solid #b37a18;background:#fff7e6;padding:14px}}
@media(max-width:650px){{table{{font-size:12px}}td,th{{padding:9px 5px}}}}
</style></head><body><main>
<h1>HITEL API 파일 시나리오 검증</h1>
<p class="note">다른 프로그램이 HTTPS API에서 조회하는 동일한 최신 시험 결과입니다.</p>
<div class="panel">{summary}</div>
<div class="panel warning"><strong>시험 범위 및 미지원</strong>
<p>여기 표시된 파일은 GitHub Actions가 직접 만든 합성 TXT/CSV이며,
HTTPS 업로드·재다운로드 후 실제 ChatGPT Chrome 계정에서 검사하였습니다.</p>
<p>일반 외부 프로그램의 <code>POST /integrations/v1/files</code>는 여전히 501 미지원입니다.
이 QA 경로의 파일 검증만으로 일반 사용자 파일 전송 API가 완성되었다고 해석하지 않습니다.</p>
<p>실제 다운로드 파일을 받지 못한 S11은 BLOCKED이고, 전체 CI 역시 통과하지 않습니다.</p></div>
<p><a href="/integrations/v1/scenarios/files/view">최신 결과 다시 조회</a>
 · <a href="/integrations/docs">전체 API 사용 설명서</a>
 · <a href="/integrations/v1/scenarios/files/latest">최신 결과 JSON</a></p>
</main></body></html>"""
    return HTMLResponse(html,headers={
        "Cache-Control":"no-store,max-age=0",
        "X-Content-Type-Options":"nosniff",
        "Referrer-Policy":"no-referrer",
        "Content-Security-Policy":"default-src 'none'; style-src 'unsafe-inline'; "
                                  "base-uri 'none'; frame-ancestors 'none'",
    })
