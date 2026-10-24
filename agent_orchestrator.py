"""Three independent continuous per-notice procurement agents.

This process is separate from the legacy collector Worker. Each fixed agent slot
owns one bid case at a time; case identity and evidence persist in PostgreSQL.
External actions are strictly read-only and there is NO bid submission or AI
call. Missing primary documents stay unverified; agents rotate automatically.
"""
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

from db import connect, session, initialize, ensure_browser_diagnostics
from bid_simulation import deadline_state

logger=logging.getLogger("procureflow.agents")
KST=ZoneInfo("Asia/Seoul")
AGENT_COUNT=3
RUN_ID=str(uuid.uuid4())
ASSIGN_LOCK=2026102403
PHASES=(
    ("identify","실제 입찰공고 식별"),
    ("notice","공고·발주처 기본정보 검증"),
    ("browser","공식 Headless 상세·첨부영역 수집"),
    ("attachments","첨부 원본·파일목록 검증"),
    ("competition","발주처·경쟁·낙찰이력 결합"),
    ("qualification","회사 자격·인허가·실적 대조"),
    ("partners","공급·협력사·수행인력 근거 조사"),
    ("cost","실제 견적과 원가증빙 검증"),
    ("ai_package","ChatGPT API 전달자료 완전성 검사"),
    ("release","완료·누락사항 기록 후 다음 공고"),
)
STOP=threading.Event()


def ensure_agent_schema():
    with connect() as c:
        c.execute("CREATE SCHEMA IF NOT EXISTS procureflow")
        c.execute("""CREATE TABLE IF NOT EXISTS procureflow.agent_slots(
          slot_id smallint PRIMARY KEY CHECK(slot_id BETWEEN 1 AND 3),
          status text NOT NULL DEFAULT 'idle',
          source text NOT NULL DEFAULT '',
          external_id text NOT NULL DEFAULT '',
          owner_id text NOT NULL DEFAULT '',
          phase text NOT NULL DEFAULT 'idle',
          phase_label text NOT NULL DEFAULT '대기',
          progress int NOT NULL DEFAULT 0,
          phase_total int NOT NULL DEFAULT 10,
          current_action text NOT NULL DEFAULT '',
          last_error text NOT NULL DEFAULT '',
          started_at timestamptz,
          heartbeat_at timestamptz,
          lease_until timestamptz,
          finished_cases int NOT NULL DEFAULT 0,
          updated_at timestamptz NOT NULL DEFAULT now()
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS procureflow.agent_cases(
          source text NOT NULL,
          external_id text NOT NULL,
          state text NOT NULL DEFAULT 'queued',
          last_agent smallint,
          attempt int NOT NULL DEFAULT 0,
          verified int NOT NULL DEFAULT 0,
          partial int NOT NULL DEFAULT 0,
          missing int NOT NULL DEFAULT 0,
          last_step text NOT NULL DEFAULT '',
          next_attempt_at timestamptz NOT NULL DEFAULT now(),
          first_assigned_at timestamptz NOT NULL DEFAULT now(),
          last_started_at timestamptz,
          last_finished_at timestamptz,
          last_error text NOT NULL DEFAULT '',
          notes jsonb NOT NULL DEFAULT '{}'::jsonb,
          PRIMARY KEY(source,external_id),
          FOREIGN KEY(source,external_id)
            REFERENCES procureflow.tenders(source,external_id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS procureflow.agent_events(
          id bigserial PRIMARY KEY,
          slot_id smallint NOT NULL,
          source text NOT NULL DEFAULT '',
          external_id text NOT NULL DEFAULT '',
          level text NOT NULL DEFAULT 'info',
          step text NOT NULL DEFAULT '',
          message text NOT NULL,
          meta jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now()
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS ix_pf_agent_events_recent ON procureflow.agent_events(id DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS ix_pf_agent_retry ON procureflow.agent_cases(state,next_attempt_at)")
        # Operator starts an agent explicitly. An idle process is not an active agent.
        c.execute("""ALTER TABLE procureflow.agent_slots
              ADD COLUMN IF NOT EXISTS enabled boolean NOT NULL DEFAULT false""")
        c.execute("CREATE INDEX IF NOT EXISTS ix_pf_agent_slots_lease ON procureflow.agent_slots(lease_until)")
        for n in range(1,AGENT_COUNT+1):
            c.execute("INSERT INTO procureflow.agent_slots(slot_id) VALUES (%s) ON CONFLICT DO NOTHING",(n,))


def _log(db,slot,source,external_id,step,message,level="info",meta=None):
    db.execute("""INSERT INTO procureflow.agent_events
       (slot_id,source,external_id,level,step,message,meta)
       VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)
       """,(slot,source,external_id,level,step,message,json.dumps(meta or {},ensure_ascii=False)))
    logger.info("AGENT_%s %s %s %s: %s",slot,source,external_id,step,message[:350])


def _touch(slot,source,external_id,phase,label,progress,action):
    with session() as db:
        r=db.execute("""UPDATE procureflow.agent_slots
          SET phase=%s,phase_label=%s,progress=%s,current_action=%s,
              heartbeat_at=now(),lease_until=now()+interval '5 minutes',updated_at=now()
          WHERE slot_id=%s AND owner_id=%s AND source=%s AND external_id=%s
          RETURNING slot_id
        """,(phase,label,progress,action[:450],slot,RUN_ID,source,external_id)).fetchone()
        if not r:raise RuntimeError("Agent slot lease ownership lost")
        db.execute("""UPDATE procureflow.agent_cases SET last_step=%s
          WHERE source=%s AND external_id=%s""",(phase,source,external_id))
        _log(db,slot,source,external_id,phase,action[:400])


def _deadline_at(text):
    """Parse confirmed Korean-local deadline; never prioritize malformed deadlines."""
    value=str(text or "").strip()
    try:
        if re.fullmatch(r"\d{12}",value):
            dt=datetime.strptime(value,"%Y%m%d%H%M")
        elif re.fullmatch(r"\d{14}",value):
            dt=datetime.strptime(value,"%Y%m%d%H%M%S")
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?",value):
            dt=datetime.fromisoformat(value)
        else:
            return None
        return dt.replace(tzinfo=KST) if dt.tzinfo is None else dt.astimezone(KST)
    except (ValueError,TypeError,OverflowError):
        return None


def _get_candidate(db,slot):
    # All eligible open bids, ordered by the CLOSEST deadline, not by
    # most recently posted announcement. Different agents never share a
    # claimed bid, and completed cases are retried only when due.
    rows=db.execute("""SELECT t.source,t.external_id,t.title,t.agency,
                            t.category,t.deadline,t.notice_date,t.last_seen,
                            ac.state AS agent_state,ac.next_attempt_at,
                            coalesce(ac.attempt,0) AS attempts
        FROM procureflow.tenders t
        LEFT JOIN procureflow.agent_cases ac
          ON ac.source=t.source AND ac.external_id=t.external_id
        WHERE t.category IN ('물품','일반용역')
          AND ((t.source='kapt' AND t.external_id ~ '^[0-9]{14,20}$')
               OR (t.source='g2b' AND t.external_id ~ '^R[0-9]{2}BK[0-9]+$'))
          AND (ac.state IS NULL OR (
                ac.state IN ('needs_evidence','retryable')
                AND ac.next_attempt_at<=now()))
        ORDER BY regexp_replace(t.notice_date,'[^0-9]','','g') DESC,
                 t.first_seen DESC
        LIMIT 10000""").fetchall()
    candidates=[]
    now=datetime.now(KST)
    for row in rows:
        deadline=_deadline_at(row["deadline"])
        if deadline and deadline>now:
            candidates.append((deadline,row["attempts"],row["source"],
                               row["external_id"],row))
    candidates.sort(key=lambda p:p[:4])
    for _,__,___,____,row in candidates:
        # Claim atomically using the same PG transaction and unique case key.
        res=db.execute("""INSERT INTO procureflow.agent_cases
           (source,external_id,state,last_agent,attempt,last_started_at)
           VALUES (%s,%s,'running',%s,1,now())
           ON CONFLICT(source,external_id) DO UPDATE
              SET state='running',last_agent=EXCLUDED.last_agent,
                  attempt=procureflow.agent_cases.attempt+1,
                  last_started_at=now()
           WHERE procureflow.agent_cases.state IN ('needs_evidence','retryable')
             AND procureflow.agent_cases.next_attempt_at<=now()
           RETURNING attempt""",(row["source"],row["external_id"],slot)).fetchone()
        if res:
            return dict(row),res["attempt"]
    return None,None


def claim(slot):
    with session() as db:
        locked=db.execute("SELECT pg_try_advisory_xact_lock(%s) AS ok",(ASSIGN_LOCK,)).fetchone()
        if not locked["ok"]:return None
        owned=db.execute("""SELECT * FROM procureflow.agent_slots
          WHERE slot_id=%s FOR UPDATE""",(slot,)).fetchone()
        if not owned:return None
        if not owned["enabled"]:
            return None
        if owned["owner_id"] and owned["owner_id"]!=RUN_ID and owned["lease_until"] and owned["lease_until"]>datetime.now(timezone.utc):
            return None
        if owned["source"] and owned["external_id"] and owned["status"]=="running":
            db.execute("""UPDATE procureflow.agent_cases
                SET state='retryable',
                    next_attempt_at=now()+interval '5 minutes',
                    last_error='Recovered from expired agent lease'
                WHERE source=%s AND external_id=%s AND state='running'
                """,(owned["source"],owned["external_id"]))
        row,attempt=_get_candidate(db,slot)
        if not row:
            db.execute("""UPDATE procureflow.agent_slots
             SET status='waiting',source='',external_id='',owner_id='',
                 phase='waiting',phase_label='마감 임박 공고 대기',progress=0,
                 heartbeat_at=now(),
                 current_action='추가 배정 가능한 미처리 공고 또는 보완 시점 대기',
                 updated_at=now()
             WHERE slot_id=%s""",(slot,))
            return None
        db.execute("""UPDATE procureflow.agent_slots SET
            status='running',source=%s,external_id=%s,owner_id=%s,
            phase='identify',phase_label='공고 배정',progress=0,phase_total=%s,
            current_action='공고 고유번호 검증',last_error='',started_at=now(),
            heartbeat_at=now(),lease_until=now()+interval '5 minutes',
            updated_at=now()
            WHERE slot_id=%s""",(row["source"],row["external_id"],RUN_ID,len(PHASES),slot))
        _log(db,slot,row["source"],row["external_id"],"claim",
             "신규 공고 독립 배정 · 반복 "+str(attempt)+"회차",
             meta={"attempt":attempt,"title":row["title"]})
        return row


def _linked_awards(row):
    from bid_simulation import topic_for
    topic=topic_for(row["title"])
    with session() as db:
        awards=db.execute("""
         SELECT bid_ntce_no,title,agency,company,amount,last_seen
         FROM procureflow.bid_results
         WHERE source='g2b' AND result_kind='award'
           AND category=%s
           AND (agency=%s OR (%s<>'' AND title ILIKE %s))
         ORDER BY last_seen DESC LIMIT 15
        """,("goods" if row["category"]=="물품" else "service",
             row["agency"],topic,"%"+topic+"%")).fetchall()
    return [{"bid_no":x["bid_ntce_no"],"title":x["title"],
             "company":x["company"],"agency":x["agency"],"amount":x["amount"]}
            for x in awards]


def _public_detail(slot,row):
    """Read-only local browser, not a paid automation service."""
    source,eid=row["source"],row["external_id"]
    if source!="kapt":
        return {"ok":False,"reason":"G2B actual BidPbanc read-only detail adapter required"}
    # The original collector worker exclusively claims queued jobs, so create
    # our autonomous-browser evidence job as RUNNING in the same transaction.
    with session() as db:
        jid=db.execute("""INSERT INTO procureflow.jobs
            (source,state,config,started_at,message)
            VALUES ('browser_probe','running',%s::jsonb,now(),
                    'Autonomous case agent read-only K-apt browser')
            RETURNING id""",(json.dumps({"external_id":eid,"source":source,
                "agent_slot":slot,"agent_owner":RUN_ID}),)).fetchone()["id"]
    try:
        from browser_diagnostics import collect
        result=collect(jid,eid)
        captures=result.get("screenshots_saved",[])
        complete=all(x.get("bytes",0)>0 for x in captures) and len(captures)==4
        with session() as db:
            db.execute("""UPDATE procureflow.jobs SET
                state=%s,checked=%s,added=%s,finished_at=now(),message=%s
                WHERE id=%s""",
                ("completed" if complete else "completed_partial",
                 len(captures),sum(1 for x in captures if x["bytes"]>0),
                 "Autonomous public-only browser capture: "+result["status"],jid))
            if complete:
                raw=next(x for x in captures if x["stage"]=="notice_detail")
                db.execute("""INSERT INTO procureflow.case_evidence(
                     source,external_id,kind,record_id,state,label,source_uri,sha256,meta)
                     VALUES(%s,%s,'detail',%s,'verified',%s,%s,%s,%s::jsonb)
                     ON CONFLICT(source,external_id,kind,record_id)
                     DO UPDATE SET state=excluded.state,label=excluded.label,
                          source_uri=excluded.source_uri,sha256=excluded.sha256,
                          meta=excluded.meta,updated_at=now()
                  """,(source,eid,f"agent-browser-{jid}",
                       "공식 K-apt 상세 캡처 Job "+str(jid),
                       f"/api/browser/images/{jid}/notice_detail",
                       raw["sha256"],
                       json.dumps({"job_id":jid,"read_only":True,"captures":4})))
                _log(db,slot,source,eid,"browser",
                     f"공식 사이트 4개 화면·원본 해시 확보: Job {jid}")
            else:
                _log(db,slot,source,eid,"browser",
                     "공식 캡처 일부 확보. 완료되지 않은 화면 있음","warn")
        return {"ok":complete,"job_id":jid,"status":result["status"],
                "captures":captures,
                "attachment_xhr_request":result.get("attachment_xhr_request",[]),
                "attachment_xhr_response":result.get("attachment_xhr_response",[])}
    except Exception as exc:
        with session() as db:
            db.execute("""UPDATE procureflow.jobs SET state='failed',
                         finished_at=now(),last_error=%s,message='Agent browser error'
                         WHERE id=%s""",(type(exc).__name__+": "+str(exc)[:300],jid))
        raise


def _mark_attachment(slot,row,browser):
    req=browser.get("attachment_xhr_request",[])
    res=browser.get("attachment_xhr_response",[])
    state="partial" if req or res else "missing"
    with session() as db:
        if req or res:
            db.execute("""INSERT INTO procureflow.case_evidence(
                source,external_id,kind,record_id,state,label,source_uri,meta)
                VALUES(%s,%s,'attachment_index','official-xhr','partial',
                       '첨부파일 조회 요청/응답 관찰',%s,%s::jsonb)
                ON CONFLICT(source,external_id,kind,record_id)
                DO UPDATE SET state='partial',label=excluded.label,
                     source_uri=excluded.source_uri,meta=excluded.meta,updated_at=now()
            """,(row["source"],row["external_id"],
                 f"/api/browser/probes/{browser.get('job_id',0)}",
                 json.dumps({"requests":len(req),"responses":len(res),
                             "file_bytes_downloaded":0})))
        _log(db,slot,row["source"],row["external_id"],"attachments",
             f"첨부목록 요청 {len(req)}건·응답 {len(res)}건, 실제 원본 다운로드 0건; "
             "원본 첨부수·해시 검증 미완료","warn")
    return state


def _mark_competition(slot,row):
    winners=_linked_awards(row)
    with session() as db:
        if winners:
            db.execute("""INSERT INTO procureflow.case_evidence
                 (source,external_id,kind,record_id,state,label,meta)
                 VALUES(%s,%s,'competition','historical-g2b-awards','partial',
                        'G2B 유사업무 공개 낙찰이력',%s::jsonb)
                 ON CONFLICT(source,external_id,kind,record_id)
                 DO UPDATE SET meta=excluded.meta,updated_at=now()
            """,(row["source"],row["external_id"],json.dumps({"winners":winners},ensure_ascii=False)))
        _log(db,slot,row["source"],row["external_id"],"competition",
             f"기록된 유사 낙찰 {len(winners)}건 연결(실제 이번 참가자로 확정 아님)")
    return len(winners)


def run_case(slot,row):
    source,eid=row["source"],row["external_id"]
    state={"detail":False,"attachments":"missing","competition":0,"blocked":[]}
    try:
        _touch(slot,source,eid,"identify","실제 입찰공고 식별",1,
               "공고 유효성·마감시각·고유 ID 확인")
        if deadline_state(row["deadline"])!="open_by_recorded_deadline":
            raise ValueError("공고 마감 또는 유효하지 않은 마감시각")
        _touch(slot,source,eid,"notice","발주처·공고 원천",2,
               f"원천 {source}, 발주처 {row['agency']}, 분야 {row['category']}")
        _touch(slot,source,eid,"browser","실제 공개화면 수집",3,
               "자체 Headless Chromium으로 공고 상세·첨부영역 캡처")
        browser=_public_detail(slot,row)
        state["detail"]=browser.get("ok",False)
        _touch(slot,source,eid,"attachments","첨부 원본 검증",4,
               "공고 파일목록 요청·응답·원본 다운로드 충족 여부 대조")
        state["attachments"]=_mark_attachment(slot,row,browser)
        state["blocked"].append("원본 첨부파일 전체 다운로드·해시 검증 미완료")
        _touch(slot,source,eid,"competition","발주처·경쟁이력 결합",5,
               "공개 G2B 실제 낙찰이력만 연결·이번 참가업체와 구분")
        state["competition"]=_mark_competition(slot,row)
        _touch(slot,source,eid,"qualification","자사 참가자격",6,
               "실제 회사별 면허·실적·신용·장비증명 대조")
        state["blocked"].append("업체별 실제 인허가·실적·신용서류 미연결")
        with session() as db:_log(db,slot,source,eid,"qualification",
             "회사의 인허가·실적·신용증빙 미연결: 충족한 것으로 표시하지 않음","warn")
        _touch(slot,source,eid,"partners","실제 공급·수행자원",7,
               "공급업체·인력·장비·견적 실증빙 확보 여부")
        state["blocked"].append("공급·협력·인력 실견적과 확보확약 미연결")
        with session() as db:_log(db,slot,source,eid,"partners",
             "일반 공급업체 DB와 실제 해당 공고 공급확약은 별개: 근거 미확보","warn")
        _touch(slot,source,eid,"cost","원가 검산",8,
               "실제 견적과 지정 공고 산출표 비교")
        state["blocked"].append("지정 원가산출서·실비·세금 검증 미완료")
        _touch(slot,source,eid,"ai_package","AI 입력 전 검증",9,
               "원본·업체증빙·견적 누락으로 최종 API 전달 차단")
        with session() as db:_log(db,slot,source,eid,"ai_package",
             "필수 자료 부족. ChatGPT API 호출하지 않음. 후속 수집 대상으로 기록","warn")
        _touch(slot,source,eid,"release","기록 후 다음 공고",10,
               "1차 독립 자료 확보 회차 마침·미확보 항목 남긴 채 다음 공고 자동 전환")
        with session() as db:
            db.execute("""UPDATE procureflow.agent_cases SET state='needs_evidence',
               verified=%s,partial=%s,missing=%s,last_step='release',
               next_attempt_at=now()+interval '6 hours',last_finished_at=now(),
               last_error='',notes=%s::jsonb
               WHERE source=%s AND external_id=%s
            """,(1+int(state["detail"]),
                 int(state["attachments"]=="partial")+int(state["competition"]>0),
                 len(state["blocked"]),json.dumps(state,ensure_ascii=False),source,eid))
            _log(db,slot,source,eid,"complete",
                 "자료수집 회차 종료. 누락자료 보완 대상으로 보관하고 다음 공고 선택",
                 meta={"verified":1+int(state["detail"]),
                       "missing":state["blocked"],"next_retry_hours":6})
        logger.info("AGENT_%s_CASE_COMPLETE source=%s id=%s",slot,source,eid)
    except Exception as exc:
        msg=type(exc).__name__+": "+str(exc)[:250]
        with session() as db:
            db.execute("""UPDATE procureflow.agent_cases SET state='retryable',
               last_step='error',next_attempt_at=now()+interval '30 minutes',
               last_finished_at=now(),last_error=%s WHERE source=%s AND external_id=%s
            """,(msg,source,eid))
            _log(db,slot,source,eid,"error",msg,"error")
        logger.exception("AGENT_%s_CASE_ERROR %s %s",slot,source,eid)
    finally:
        with session() as db:
            db.execute("""UPDATE procureflow.agent_slots SET
                status=CASE WHEN enabled THEN 'waiting' ELSE 'disabled' END,
                source='',external_id='',owner_id='',
                phase='waiting',
                phase_label=CASE WHEN enabled THEN '다음 마감 임박 공고 배정'
                                 ELSE '사용자에 의해 중지' END,
                progress=0,
                current_action=CASE WHEN enabled THEN '다음 미처리 공고 검색 중'
                                    ELSE '사용자 요청으로 다음 공고 자동배정 중지' END,
                heartbeat_at=now(),lease_until=NULL,
                finished_cases=finished_cases+1,updated_at=now()
                WHERE slot_id=%s AND owner_id=%s""",(slot,RUN_ID))


def slot_main(slot):
    logger.info("AGENT_SLOT_LISTENER_READY slot=%d instance=%s - NOT ACTIVE",slot,RUN_ID[:8])
    while not STOP.is_set():
        try:
            # Idle listener does nothing until the user presses [에이전트 추가].
            with session() as db:
                active=db.execute("SELECT enabled FROM procureflow.agent_slots WHERE slot_id=%s",(slot,)).fetchone()
            if not active or not active["enabled"]:
                STOP.wait(3)
                continue
            case=claim(slot)
            if case:
                run_case(slot,case)
            else:
                STOP.wait(5)
        except Exception:
            logger.exception("AGENT_SLOT_FAILURE slot=%s",slot)
            STOP.wait(8)


def activate_one():
    """Operator-triggered creation of exactly one active autonomous agent."""
    with session() as db:
        db.execute("SELECT pg_advisory_xact_lock(%s)",(ASSIGN_LOCK,))
        row=db.execute("""SELECT slot_id FROM procureflow.agent_slots
             WHERE enabled=false ORDER BY slot_id FOR UPDATE SKIP LOCKED LIMIT 1""").fetchone()
        if not row:
            raise ValueError("최대 3개 에이전트가 이미 활성화되어 있습니다")
        slot=row["slot_id"]
        db.execute("""UPDATE procureflow.agent_slots SET
           enabled=true,status='waiting',source='',external_id='',owner_id='',
           phase='waiting',phase_label='마감 임박 공고 배정 대기',
           current_action='사용자 추가 명령 수락 · 마감일 빠른 순으로 배정 예정',
           progress=0,last_error='',started_at=NULL,lease_until=NULL,
           updated_at=now()
           WHERE slot_id=%s AND enabled=false""",(slot,))
        _log(db,slot,"","","activate","사용자 [에이전트 추가] 명령으로 에이전트 활성화")
        return {"slot_id":slot,"enabled":True,"active_count":db.execute(
              "SELECT count(*) AS n FROM procureflow.agent_slots WHERE enabled"
            ).fetchone()["n"],"message":f"에이전트 {slot} 활성화. 마감 임박 공고부터 자동 배정"}


def deactivate_one(slot):
    """Stop AFTER the current case; never spawn a replacement for this slot."""
    if slot not in range(1,AGENT_COUNT+1):
        raise ValueError("에이전트 번호가 잘못되었습니다")
    with session() as db:
        db.execute("SELECT pg_advisory_xact_lock(%s)",(ASSIGN_LOCK,))
        found=db.execute("SELECT enabled,status,source,external_id FROM procureflow.agent_slots WHERE slot_id=%s FOR UPDATE",(slot,)).fetchone()
        if not found or not found["enabled"]:
            raise ValueError("이 에이전트는 비활성 상태입니다")
        in_progress=found["status"]=="running"
        db.execute("""UPDATE procureflow.agent_slots SET
          enabled=false,updated_at=now(),
          current_action=%s,
          status=CASE WHEN status='running' THEN status ELSE 'disabled' END
          WHERE slot_id=%s""",(
             "현재 공고 수집 회차 종료 후 중지" if in_progress else "사용자가 에이전트 중지",slot))
        _log(db,slot,found["source"],found["external_id"],
             "deactivate","사용자 요청: "+("현재 회차 완료 후 자동배정 중지" if in_progress else "즉시 대기 중지"))
        return {"slot_id":slot,"enabled":False,
                "finishing_current_case":in_progress,"message":
                "현재 공고 처리 후 추가 배정 없이 종료" if in_progress else "에이전트 비활성화"}


def run():
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    initialize()
    ensure_browser_diagnostics()
    from workbench import ensure_workbench
    ensure_workbench()
    ensure_agent_schema()
    logger.info("PROCUREFLOW_AGENTS_BOOT count=%d run=%s",AGENT_COUNT,RUN_ID)
    with ThreadPoolExecutor(max_workers=AGENT_COUNT,thread_name_prefix="pf-agent") as pool:
        pending=[pool.submit(slot_main,slot) for slot in range(1,AGENT_COUNT+1)]
        try:
            for future in pending:future.result()
        except KeyboardInterrupt:
            STOP.set()


if __name__=="__main__":
    run()
