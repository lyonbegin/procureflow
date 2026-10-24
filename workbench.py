"""ProcureFlow operator workbench: real tenders, per-tender acquisition status.

No fabricated completed bids: a passed deadline is not evidence of submission.
Only K-apt (including partner-notice IDs) and genuine R..BK G2B numbers appear.
Evidence stages distinguish official browser render from original document download.
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from db import session,connect
from bid_simulation import deadline_state,topic_for

KST=ZoneInfo("Asia/Seoul")
CATEGORIES=("물품","일반용역")
STAGE_CATALOG=[
 ("notice","공고 원천·식별","실제 공고번호, 분야, 공개 원천"),
 ("agency","발주처 정보","발주처 식별·연락처·사업 특성"),
 ("detail","공식 상세화면","Headless Chromium 공식 상세 캡처"),
 ("attachment_index","원본 첨부목록","공식 파일목록 조회 결과·파일 수 대조"),
 ("attachment_files","첨부 원본파일","원본 바이너리 전부 다운로드 및 SHA-256"),
 ("attachment_parse","첨부 텍스트·표","HWP/PDF/엑셀 표와 조항 추출 검증"),
 ("requirements","입찰요건·평가기준","자격·평가·무효사유·납품조건"),
 ("agency_history","발주처 과거 이력","동일 발주처 입찰·낙찰·계약"),
 ("competition","경쟁업체·낙찰 이력","실제 참가/낙찰과 잠재 후보 구분"),
 ("company","자사 자격·증빙","등록·면허·세금·실적·신용증빙"),
 ("partners","공급·협력업체","실제 공급·수행 가능 업체"),
 ("staffing","인력·장비 계획","실제 배치·보유·대체인력 증빙"),
 ("quotes","원가·견적 증빙","실제 공급·외주견적·납기"),
 ("cost","가격 산출 데이터","공고 산식과 원본·실견적 검산"),
 ("ai_package","AI 입력 패키지","출처·버전·누락검증 완료 JSON"),
 ("final_proposal","최종 제안서·투찰가격","AI 결과와 문서·가격 최종검증"),
]
CODES={x[0] for x in STAGE_CATALOG}
VALID_STATES={"collecting","paused"}

def eligible(t):
    source=t["source"]
    external_id=t["external_id"]
    if t["category"] not in CATEGORIES:return False
    if source=="kapt":return True
    return source=="g2b" and re.fullmatch(r"R\d{2}BK\d+",external_id) is not None

def ensure_workbench():
    with connect() as c:
        c.execute("CREATE SCHEMA IF NOT EXISTS procureflow")
        c.execute("""CREATE TABLE IF NOT EXISTS procureflow.case_workflows(
          source text NOT NULL,external_id text NOT NULL,
          state text NOT NULL DEFAULT 'collecting',
          started_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          note text NOT NULL DEFAULT '',
          PRIMARY KEY(source,external_id),
          FOREIGN KEY(source,external_id) REFERENCES procureflow.tenders(source,external_id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS procureflow.case_evidence(
          source text NOT NULL,external_id text NOT NULL,
          kind text NOT NULL,record_id text NOT NULL,
          state text NOT NULL DEFAULT 'partial',
          label text NOT NULL DEFAULT '',source_uri text NOT NULL DEFAULT '',
          sha256 text NOT NULL DEFAULT '',
          meta jsonb NOT NULL DEFAULT '{}'::jsonb,
          updated_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY(source,external_id,kind,record_id),
          FOREIGN KEY(source,external_id) REFERENCES procureflow.tenders(source,external_id)
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS ix_pf_case_ev_kind ON procureflow.case_evidence(source,external_id,kind,state)")
        c.execute("CREATE INDEX IF NOT EXISTS ix_pf_case_jobs ON procureflow.jobs(source,state,created_at DESC)")


def _deadline(t):
    return deadline_state(t["deadline"])

def _date_string(v):
    return v.isoformat() if hasattr(v,"isoformat") else v

def _stage(kind, status="missing", description="", evidence=None):
    title,goal=next((title,goal) for k,title,goal in STAGE_CATALOG if k==kind)
    return {"id":kind,"title":title,"goal":goal,"status":status,
            "description":description or "자료가 등록되지 않았습니다",
            "evidence":evidence or []}

def _evidence_index(rows):
    out={}
    for row in rows:
        if row["kind"] in CODES:
            out.setdefault(row["kind"],[]).append(row)
    return out

def _state(t,c=None,has_browser=False,ready=False,final=False,submitted=False):
    deadline=_deadline(t)
    if submitted:return "submitted"
    if deadline=="past_recorded_deadline":return "closed"
    if ready:return "ai_ready"
    if final:return "proposal_complete"
    if c and c["state"]=="paused":return "paused"
    if c or has_browser:return "collecting"
    return "unstarted"

def _preview_row(t,case,latest_capture,evidence):
    is_captured=bool(latest_capture and latest_capture.get("has_detail"))
    complete={"notice"}
    if is_captured:complete.add("detail")
    confirmed={row["kind"] for row in evidence if row["state"]=="verified"
               and row["kind"] in CODES and row.get("source_uri") and row.get("sha256")}
    complete.update(confirmed)
    draft= t["source"]=="kapt" and t["external_id"]=="20261020165014951"
    ready="ai_package" in confirmed
    final="final_proposal" in confirmed
    submitted=any(x["kind"]=="submission_receipt" and x["state"]=="verified"
                  and x.get("source_uri") and x.get("sha256") for x in evidence)
    state=_state(t,case,is_captured,ready,final,submitted)
    return {
        "source":t["source"],"external_id":t["external_id"],"title":t["title"],
        "agency":t["agency"],"category":t["category"],"notice_date":t["notice_date"],
        "deadline":t["deadline"],"source_status":t["status"],"method":t["method"],
        "source_url": ("https://www.k-apt.go.kr/bid/bidDetail.do?bidNum="+t["external_id"]
            if t["source"]=="kapt" and t["external_id"].isdigit()
            else t["source_url"]),
        "last_seen":_date_string(t["last_seen"]),
        "source_stale":(datetime.now(KST)-t["last_seen"].astimezone(KST)).total_seconds()>48*3600,
        "deadline_state":_deadline(t),"work_state":state,
        "workflow_started":bool(case),
        "capture_job":latest_capture.get("id") if latest_capture else None,
        "capture_job_state":latest_capture.get("state") if latest_capture else None,
        "evidence_verified":len(complete),
        "evidence_total":len(STAGE_CATALOG),
        "evidence_partial":int(bool(t["agency"]))+int(draft),
        "proposal_status":"최종본 검증됨" if final else ("검토 초안만 있음" if draft else "최종 제안서 미작성"),
        "submission_verified":submitted,
    }

def _latest_probes(db):
    # Historical jobs are evidence ONLY if actual screenshot data exists.
    rows=db.execute("""
      SELECT DISTINCT ON (j.config->>'external_id')
          j.id,j.config->>'external_id' AS external_id,j.state,
          EXISTS(SELECT 1 FROM procureflow.browser_captures bc
                  WHERE bc.job_id=j.id AND bc.stage='notice_detail'
                    AND octet_length(bc.image)>0
                    AND position((j.config->>'external_id')
                                 IN COALESCE(bc.snapshot->>'text',''))>0
                ) AS has_detail,
          j.started_at,j.finished_at
      FROM procureflow.jobs j
      WHERE j.source='browser_probe'
        AND j.config->>'external_id' IS NOT NULL
      ORDER BY j.config->>'external_id',j.id DESC
    """).fetchall()
    return {r["external_id"]:r for r in rows}


def overview(q="",source="",category="",filter_state="all",limit=50,offset=0):
    limit=min(max(int(limit),1),100)
    offset=max(int(offset),0)
    q=q.strip().lower()[:200]
    with session() as db:
        rows=db.execute("""
          SELECT source,external_id,title,agency,category,notice_date,deadline,
                 status,method,source_url,first_seen,last_seen
          FROM procureflow.tenders
          WHERE category IN ('물품','일반용역')
            AND (source='kapt' OR (source='g2b' AND external_id ~ '^R[0-9]{2}BK[0-9]+$'))
          ORDER BY regexp_replace(notice_date,'[^0-9]','','g') DESC,first_seen DESC
          LIMIT 5001
        """).fetchall()
        cases=db.execute("SELECT source,external_id,state,started_at,updated_at FROM procureflow.case_workflows").fetchall()
        evidence=db.execute("""SELECT source,external_id,kind,record_id,state,label,source_uri,sha256
                            FROM procureflow.case_evidence""").fetchall()
        probes=_latest_probes(db)
    cm={(x["source"],x["external_id"]):x for x in cases}
    em={}
    for x in evidence:em.setdefault((x["source"],x["external_id"]),[]).append(x)
    all_rows=[_preview_row(t,cm.get((t["source"],t["external_id"])),
               probes.get(t["external_id"]) if t["source"]=="kapt" else None,
               em.get((t["source"],t["external_id"]),[]))
              for t in rows[:5000] if eligible(t)]
    counts={k:0 for k in ("all","unstarted","collecting","paused","ai_ready","proposal_complete","closed","submitted","proposal_missing")}
    for x in all_rows:
        counts["all"]+=1
        counts[x["work_state"]]+=1
        if x["proposal_status"]!="최종본 검증됨":counts["proposal_missing"]+=1
    result=all_rows
    if source in ("kapt","g2b"):result=[r for r in result if r["source"]==source]
    if category in CATEGORIES:result=[r for r in result if r["category"]==category]
    if q:result=[r for r in result if q in
                  (r["title"]+" "+r["agency"]+" "+r["external_id"]).lower()]
    if filter_state=="proposal_missing":
        result=[r for r in result if r["proposal_status"]!="최종본 검증됨"]
    elif filter_state in counts and filter_state!="all":
        result=[r for r in result if r["work_state"]==filter_state]
    result_len=len(result)
    return {"items":result[offset:offset+limit],"total":result_len,
            "totals":counts,"limit":limit,"offset":offset,
            "stored_cap":5000,"truncated":len(rows)>5000,
            "freshness_note":"최신 저장순. 외부 입찰사이트와 실시간 동기화 완료를 의미하지 않음",
            "g2b_order_requests_excluded":True,
            "submitted_means_receipt_verified":True}


def case_detail(source,external_id):
    with session() as db:
        t=db.execute("""SELECT source,external_id,title,agency,category,notice_date,deadline,
                        status,method,source_url,raw,first_seen,last_seen
                        FROM procureflow.tenders
                        WHERE source=%s AND external_id=%s""",(source,external_id)).fetchone()
        if not t or not eligible(t):raise LookupError("Actual bid notice not found")
        cw=db.execute("""SELECT source,external_id,state,started_at,updated_at,note
                         FROM procureflow.case_workflows
                         WHERE source=%s AND external_id=%s""",(source,external_id)).fetchone()
        ev=db.execute("""SELECT kind,record_id,state,label,source_uri,sha256,meta,updated_at
                         FROM procureflow.case_evidence WHERE source=%s AND external_id=%s
                         ORDER BY kind,updated_at DESC""",(source,external_id)).fetchall()
        jobs=(db.execute("""
             SELECT id,source,state,checked,added,current_page,created_at,started_at,
                    finished_at,left(message,500) AS message,left(last_error,700) AS last_error
             FROM procureflow.jobs WHERE source='browser_probe'
               AND config->>'external_id'=%s
             ORDER BY id DESC LIMIT 12
             """,(external_id,)).fetchall() if source=="kapt" else [])
        captures=(db.execute("""
             SELECT bc.stage,bc.created_at,octet_length(bc.image) AS bytes,
                    bc.snapshot->>'title' AS page_title,
                    bc.snapshot->>'text' AS page_text,
                    bc.job_id
             FROM procureflow.browser_captures bc
             JOIN procureflow.jobs j ON j.id=bc.job_id
             WHERE j.source='browser_probe'
               AND j.config->>'external_id'=%s AND bc.job_id=%s
             ORDER BY bc.created_at
             """,(external_id,jobs[0]["id"])).fetchall() if jobs else [])
        from bid_simulation import topic_for
        topic=topic_for(t["title"])
        matches=db.execute("""
             SELECT bid_ntce_no,title,agency,company,amount,last_seen
             FROM procureflow.bid_results
             WHERE result_kind='award' AND source='g2b'
               AND category=%s
               AND (agency=%s OR (%s<>'' AND title ILIKE %s))
             ORDER BY last_seen DESC LIMIT 15
             """,("goods" if t["category"]=="물품" else "service",
                  t["agency"],topic,"%"+topic+"%")).fetchall()
    latest=(jobs[0] if jobs else None)
    captured=any(c["stage"]=="notice_detail" and c["bytes"]>0 and
                 external_id in (c["page_text"] or "") for c in captures)
    idx=_evidence_index(ev)
    stages=[]
    for kind,title,goal in STAGE_CATALOG:
        reg=idx.get(kind,[])
        backed=[x for x in reg if x["state"]=="verified" and x["source_uri"] and x["sha256"]]
        if backed:
            stages.append(_stage(kind,"verified",
                   str(len(backed))+"건의 원본 증빙·해시 등록됨",
                   [{"record_id":x["record_id"],"label":x["label"],"url":x["source_uri"],
                     "sha256":x["sha256"]} for x in backed[:12]]))
        elif kind=="notice":
            stages.append(_stage(kind,"verified","입찰공고번호·공고 제목·일정 수집됨",
                        [{"label":"공개 공고", "url":t["source_url"]}]))
        elif kind=="agency" and t["agency"]:
            stages.append(_stage(kind,"partial",
                        "발주처명 확보: "+t["agency"]+" / 식별코드·과거 계약 연결 전"))
        elif kind=="detail" and captured:
            stages.append(_stage(kind,"verified","공식 K-apt 상세화면 이미지·DOM 저장",
                   [{"label":c["stage"]+" 캡처",
                     "url":f"/api/browser/images/{c['job_id']}/{c['stage']}",
                     "bytes":c["bytes"]} for c in captures if c["stage"]=="notice_detail"]))
        elif kind=="attachment_index" and latest and captured:
            stages.append(_stage(kind,"partial",
                   "첨부파일 UI 조회 확인. 원본 첨부 건수/목록 대조 미완료"))
        elif kind=="competition" and matches:
            stages.append(_stage(kind,"partial",
                f"동일 발주처 또는 유사업무 G2B 낙찰 {len(matches)}건. 실제 이 공고 참가자는 미확정",
                [{"label":m["company"]+" / "+m["bid_ntce_no"],"url":""} for m in matches[:6]]))
        elif kind=="cost" and source=="kapt" and external_id=="20261020165014951":
            stages.append(_stage(kind,"partial",
              "공개 공고 OCR 기반 원가 시나리오 있음. 원본 산출서·실견적 검증 전",
              [{"label":"가격 산출 검토","url":"/prepare"}]))
        elif reg:
            stages.append(_stage(kind,"partial",
                       "자료 등록됨. 원본 증빙·검증 기준 미충족",
                       [{"record_id":x["record_id"],"label":x["label"],"url":x["source_uri"]} for x in reg[:8]]))
        else:
            stages.append(_stage(kind,"missing","원본 자료 및 검증 기록 미확보"))
    verified=sum(s["status"]=="verified" for s in stages)
    partial=sum(s["status"]=="partial" for s in stages)
    map_evidence=[{k:v for k,v in c.items() if k!="page_text"} for c in captures]
    summary=_preview_row(t,cw,{"id":latest["id"],"has_detail":captured,
                             "state":latest["state"]} if latest else None,ev)
    return {"tender":summary,"workflow":cw,
           "progress":{"verified":verified,"partial":partial,
                       "missing":len(STAGE_CATALOG)-verified-partial,
                       "total":len(STAGE_CATALOG),
                       "evidence_percent":round(100*verified/len(STAGE_CATALOG))},
           "stages":stages,"jobs":jobs,"screenshots":map_evidence,
           "historical_awards":[{"notice_no":x["bid_ntce_no"],"title":x["title"],
                                "agency":x["agency"],"company":x["company"],
                                "amount":x["amount"],
                                "match_rule":"same_agency" if x["agency"]==t["agency"]
                                else "shared_service_topic"} for x in matches],
           "company_documents":[],
           "attachment_verified_count":sum(s["id"]=="attachment_files" and
                                              s["status"]=="verified" for s in stages),
           "final_bid_amount_krw":None,
           "final_proposal_ready":any(s["id"]=="final_proposal" and
                                      s["status"]=="verified" for s in stages),
           "real_submission_receipt_verified":summary["submission_verified"],
           "ai_called":False,
           "source_freshness_warning":summary["source_stale"]}


def change_workflow(source,external_id,action):
    if action not in ("start","pause","resume"):raise ValueError("Unsupported workflow action")
    with session() as db:
        t=db.execute("""SELECT source,external_id,title,category
             FROM procureflow.tenders WHERE source=%s AND external_id=%s""",
             (source,external_id)).fetchone()
        if not t or not eligible(t):raise LookupError("Actual bid notice not found")
        if action=="pause":
            exists=db.execute("""UPDATE procureflow.case_workflows
                SET state='paused',updated_at=now() WHERE source=%s AND external_id=%s
                RETURNING state""",(source,external_id)).fetchone()
            if not exists:raise ValueError("Start the tender case before pausing")
            cancelled=db.execute("""UPDATE procureflow.jobs
                   SET state='cancelled',message='Cancelled by workbench pause',
                       finished_at=now()
                   WHERE source='browser_probe'
                     AND config->>'external_id'=%s AND state='queued'
                   RETURNING id""",(external_id,)).fetchall()
            return {"state":"paused","job_id":None,"collection_started":False,
                    "message":("수집 보류. 대기 작업 "+str(len(cancelled))+
                               "건 취소. 이미 실행 중인 수집은 현재 단계까지 진행됩니다")}
        record=db.execute("""INSERT INTO procureflow.case_workflows
            (source,external_id,state) VALUES (%s,%s,'collecting')
            ON CONFLICT(source,external_id) DO UPDATE
              SET state='collecting',updated_at=now() RETURNING state""",
              (source,external_id)).fetchone()
        job_id=None
        message="공고 관리 시작. 해당 사이트의 실제 첨부파일 수집 파이프라인은 별도."
        if source=="kapt" and re.fullmatch(r"\d{14,20}",external_id):
            active=db.execute("""SELECT id FROM procureflow.jobs
                       WHERE source='browser_probe' AND state IN ('queued','running')
                       ORDER BY id DESC LIMIT 1""").fetchone()
            if active:
                message=f"브라우저 수집기가 다른 작업 {active['id']} 처리 중. 공고 관리 시작됨"
            else:
                job_id=db.execute("""INSERT INTO procureflow.jobs(source,config,message)
                    VALUES ('browser_probe',%s::jsonb,'Workbench public K-apt screenshot/DOM/XHR inspection')
                    RETURNING id""",
                    (__import__("json").dumps({"source":"kapt","external_id":external_id}),)).fetchone()["id"]
                message="공식 K-apt 상세·첨부 UI 수집 작업 등록"
        elif source=="kapt":
            message="공고 관리 시작. 제휴형 KG2B 공고는 별도 원천 수집 연결 필요"
        elif source=="g2b":
            message="공고 관리 시작. 실제 G2B 입찰공고 상세 수집 연결 필요"
        return {"state":record["state"],"job_id":job_id,
                "collection_started":job_id is not None,"message":message}
