#!/usr/bin/env python3
"""HITEL QA-only scenario runner. Never connects to Railway WebSocket or writes research rooms."""
from __future__ import annotations
import asyncio, hashlib, json, os, sys, time, uuid, urllib.request, urllib.error
from pathlib import Path

ROOT=Path(os.environ.get("RUNNER_TEMP","/tmp"))/"hitel-scenarios"
ROOT.mkdir(parents=True,exist_ok=True)
RESULTS=ROOT/"results.json"
CASES={
"C01":"기존 두 방과 별도 Chrome 탭/계정 연결",
"C02":"두 방 각각 동일 문맥 세 번 연속 질문",
"C03":"두 방의 질문 병렬 전송과 독립성",
"C04":"숨긴/비활성 편집창 및 실제 DOM 가용성",
"C05":"전송 중 연결 중단과 안전한 재개",
"A01":"단일 지정 원본 소스만 연구",
"A02":"Pine 원문 미확보 시 미검증 판정",
"A03":"외부 연구 자료 접근 불능",
"A04":"불완전한 연구 JSON 거부",
"A05":"같은 A방 연속 단계 및 문맥 보존",
"A06":"별도 방 블라인드 재구성",
"A07":"지식그래프 누락 검출",
"A08":"미완성 반복 복구 PASS 금지",
"A09":"중단 뒤 동일 체크포인트 및 ID",
"A10":"이전 원본 검증 전 다음 원본 진행 금지",
"S01":"18109 원본 행·ID·해시 보존",
"S02":"20개 제목 실제 분류 결과 ID 대응",
"S03":"누락·중복된 모델 출력 거부",
"S04":"이전·현재 JSON 혼합 방어",
"S05":"65536바이트 초과 완료 결과 회수",
"S06":"같은 Scribd방에서 20건 성공 후 다음 요청",
"S07":"Scribd 그룹별 방/탭 분리",
"S08":"HTTP500 편집창 장애 원인·복구",
"S09":"running/unknown/stalled 상태 관리",
"S10":"GitHub 체크포인트 복구 중복방지",
"S11":"검증 완료와 미검증 건수 분리",
"S12":"실제 완료 0건인데 성공 판정 방지",
}
results={}
def report(id, status, evidence, layer):
    assert id in CASES and status in ("PASS","FAIL","미검증")
    results[id]={"scenario":CASES[id],"status":status,"layer":layer,"evidence":str(evidence)[:450]}
    print(f"SCENARIO|{id}|{status}|{layer}|{str(evidence)[:200]}",flush=True)
    RESULTS.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
def check(id, fn, layer="code"):
    try:
        passed,evidence=fn()
        report(id,"PASS" if passed else "FAIL",evidence,layer)
    except Exception as e:
        report(id,"미검증",type(e).__name__+":"+str(e)[:130],layer)
def load(path):
    return Path(path).read_text(encoding="utf-8")
def public_get(path):
    with urllib.request.urlopen("https://hitel-integration-api-production.up.railway.app"+path,timeout=12) as r:
        return json.load(r)

def contracts():
    root=Path.cwd()
    worker=load(root/"qa/.github/scripts/w2a_relay_worker.py")
    pool=load(root/"qa/.github/scripts/hitel_room_tab_pool.py")
    patch=load(root/".github/scripts/w2a_patch_vendor_dom.py")
    public=load(root/"source-api/chatgpt-android-relay/web/integration_public.py")
    app=load(root/"source-api/chatgpt-android-relay/web/app.py")
    a=load(root/"stock/research/hitel_a_one_source.py")
    recovery=load(root/"stock/research/hitel_a_recover_discovery.py")
    scribd=load(root/"scribd/tools/zocbo/hitel_public_named_rooms_corpus.py")
    sw=load(root/"scribd/.github/workflows/hitel-public-ai-corpus.yml")
    report("C01","미검증","독립 Chrome 실제 탭 검증은 browser 단계 수행","browser")
    report("C02","미검증","실제 연속 3회 질문은 browser 단계 수행","browser")
    report("C03","미검증","실제 병렬 2방 전송은 browser 단계 수행","browser")
    check("C04",lambda:(("composer_present" in pool or "send_ready" in pool) and "healthy" not in pool.split("async def _ready(port: int) -> bool:")[-1][:350],"현재 _ready는 Chrome/driver/healthy만 확인하며 입력창 검증 없음"))
    check("C05",lambda:("job.uncertain" in worker and "upstream_delivery_unknown" in app and "unknown" not in public[public.index('def submit_public_chat'):public.index('@router.get("/requests/')],"중복전송 회피는 있으나 unknown/stalled 고착 후 자동 회복 보장 없음"))
    check("A01",lambda:("ONLY_CONFIRMED_A_PILOT_0LJUxO7T" in recovery,"단일 원본 제한은 존재하나 실제 연구 요청의 검증 완료를 의미하지 않음"),"code")
    check("A02",lambda:("pine_source_status" in recovery and "NOT_VERIFIED" in recovery,"Pine 원문 미확보시 NOT_VERIFIED로 보존"),"code")
    report("A03","미검증","외부 원문/논문 접근 장애의 실제 브라우저 복구 시험은 수행하지 않음","external")
    check("A04",lambda:("CHATGPT_JSON_PARSE_FAILED" in a and "CHATGPT_OBJECT_REQUIRED" in a,"불완전한 JSON 및 비객체 거부 분기 확인"),"code")
    report("A05","미검증","격리된 A 시험방에서 실제 3회 전송으로 검증 예정","browser")
    report("A06","미검증","원본을 가린 독립 블라인드 연구의 실제 연구 전송 금지","research")
    check("A07",lambda:("def validate_graph" in a and "STRUCTURAL_GRAPH_CHECK_PASS" in a,"지식그래프 구조 확인 함수 존재; 의미 검증 통과와 다름"),"code")
    check("A08",lambda:("MODEL_REPORTED_REVERSIBLE_NOT_PINE_VERIFIED" in recovery and "next_source_allowed" in recovery,"모델 평가와 Pine 실원본 검증을 구분"),"code")
    check("A09",lambda:("ORIGINAL_JOB_CHECKPOINT_MISSING_REFUSE_NEW_SEND" in recovery and "ORIGINAL_JOB_IDENTITY_MISMATCH" in recovery,"중단된 A 원본 job_id 검증 가드 존재"),"code")
    check("A10",lambda:("next_source_allowed" in recovery and '"next_source_allowed": False' in recovery,"원본 미검증 때 다음 원본 진입 금지"),"code")
    def corpus():
        import csv
        base=root/"scribd/data/raw_18109"
        pieces=sorted(base.glob("part_*.csv"))
        if len(pieces)!=20:
            return False,"원본 파트 수="+str(len(pieces))
        raw=b"\xef\xbb\xbf"+"".join(p.read_text("utf-8") for p in pieces).replace("\n","\r\n").encode("utf-8")
        digest=hashlib.sha256(raw).hexdigest()
        rows=list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
        return len(rows)==18109 and len(set(r["문서 ID"] for r in rows))==18109 and digest=="c9ac45f833dd30a002cffac64cb3ced763ed4eb18b0e121c4ab00b935a9b82e3",f"rows={len(rows)} unique_ids={len(set(r['문서 ID'] for r in rows))} digest={digest}"
    check("S01",corpus,"real_file")
    report("S02","미검증","독립 QA Chrome에서 20개의 합성 교재명을 실제 모델 분류 예정","browser")
    def check_s03():
        import importlib.util
        spec=importlib.util.spec_from_file_location("hitel_scribd_test",root/"scribd/tools/zocbo/hitel_public_named_rooms_corpus.py")
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        batch=[{"번호":i,"문서 ID":f"QAID{i:03d}","원문 제목":"가상 중1 수학"} for i in range(1,21)]
        valid=[{"no":i,"id":f"QAID{i:03d}","school":"중등","grade":"1","semester":"1","subject":"수학","edition":"해당없음","download":"대상","reason":"가상 표제"} for i in range(1,21)]
        bads=[valid[:-1],valid[:-1]+[dict(valid[-2])],valid[:-1]+[{**valid[-1],"id":"OTHER"}]]
        rejected=0
        for b in bads:
            try: mod.validated_rows(json.dumps({"rows":b},ensure_ascii=False),batch)
            except ValueError:rejected+=1
        return rejected==3, f"invalid_rejected={rejected}/3"
    check("S03",check_s03,"unit")
    def check_s04():
        import importlib.util
        spec=importlib.util.spec_from_file_location("hitel_scribd_test2",root/"scribd/tools/zocbo/hitel_public_named_rooms_corpus.py")
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        batch=[{"번호":i,"문서 ID":f"QAID{i:03d}","원문 제목":"가상 중1 수학"} for i in range(21,41)]
        def rows(n):
            return [{"no":i,"id":f"QAID{i:03d}","school":"중등","grade":"1","semester":"1","subject":"수학","edition":"해당없음","download":"대상","reason":"가상 표제"} for i in n]
        content=json.dumps({"rows":rows(range(1,21))},ensure_ascii=False)+json.dumps({"rows":rows(range(21,41))},ensure_ascii=False)
        out=mod.validated_rows(content,batch)
        return len(out)==20 and out[0]["no"]==21,"현재 batch와 이전 batch JSON 구분"
    check("S04",check_s04,"unit")
    check("S05",lambda:('"/result"' in scribd or "'/result'" in scribd,"현재 분류기는 /jobs/{id}/result 경로를 호출하지 않음: 65536바이트 초과시 결과 누락"),"code")
    report("S06","미검증","독립 QA Chrome에서 2회 연속 같은 분류방 전송 예정","browser")
    report("S07","미검증","독립 QA Chrome에서 두 개의 별도 탭 ID 검증 예정","browser")
    def check_s08():
        v=public_get("/integrations/v1/public/jobs/job_0071fe1a14384bb28fab2ea500a95c02")
        return v.get("error_code")!="WEB2API_ADAPTER_HTTP_500_COMPOSER_UNAVAILABLE" and v.get("result_ready") is True,"known_actual_failure="+str(v.get("error_code"))
    check("S08",check_s08,"read_only_live")
    def check_s09():
        v=public_get("/integrations/v1/public/jobs/job_157ccae7532c428fa4ffb9133fa7cf71")
        return v.get("result_ready") is True or v.get("status") in ("failed","stalled"),"old_running_job="+str(v.get("status"))+" reply="+str(v.get("result_ready"))
    check("S09",check_s09,"read_only_live")
    check("S10",lambda:("PASS_RESTORED_AI_COMPLETIONS" in sw and "Duplicate verified original" in sw and "SOURCE_VERIFIED" in sw,"체크포인트 및 원본 중복 검증 코드 존재"),"code")
    check("S11",lambda:("unverified_skipped" in scribd and "verified_ai_completed" in scribd and "never_count_as_completed" in scribd,"검증 건수와 미검증 건수 별도 기록"),"code")
    check("S12",lambda:("if: ${{ false }}" in sw and "NEW_VERIFIED" in sw,"현행 main에서 후속 분류 강제 중단은 정상; 과거 workflow는 NEW_VERIFIED=0이더라도 success"),"code")
    print("CONTRACT_PHASE_DONE",flush=True)

async def browser():
    # Runs on a completely separate GitHub-hosted Chrome profile copy.
    # There is NO connection to the existing Railway worker, no old research room write.
    import importlib.util
    import sys
    tools=Path.cwd()/"qa/.github/scripts"
    sys.path.insert(0,str(tools))
    from hitel_room_tab_pool import RoomTabPool
    from w2a_relay_worker import post_chat_uri
    from playwright.sync_api import sync_playwright
    def find_target(registry,instance):
        return registry[instance]["target_id"]
    # QA-only subprocess diagnostics: capture the local vendor logs on this
    # disposable GitHub VM. Never publish raw text, tokens, or conversation IDs.
    _orig_spawn=asyncio.create_subprocess_exec
    async def _qa_spawn(*args,**kwargs):
        safe_port=str(args[2]) if len(args)>2 and str(args[2]).isdigit() else "unknown"
        logfile=open(ROOT/("vendor-"+safe_port+".log"),"wb")
        try:
            kwargs["stdout"]=logfile
            kwargs["stderr"]=asyncio.subprocess.STDOUT
            return await _orig_spawn(*args,**kwargs)
        finally:
            logfile.close()
    asyncio.create_subprocess_exec=_qa_spawn
    pool=RoomTabPool(max_rooms=3)
    ra="room_"+uuid.uuid4().hex;rs="room_"+uuid.uuid4().hex
    seed=os.getenv("GITHUB_RUN_ID","QA")
    ids={ra:"A",rs:"S"}
    sessions={}
    def cdp_probe(rid):
        with sync_playwright() as pw:
            chrome=pw.chromium.connect_over_cdp("http://127.0.0.1:9222",timeout=12000)
            # Exact QA conversation route identifies the page without
            # opening an extra page-level CDP Target session. Playwright's
            # Target.getTargetInfo on this external-owned target raises
            # AssertionError on the current Chrome build.
            cid=sessions.get(rid,"")
            for ctx in chrome.contexts:
                for page in ctx.pages:
                    if not cid or page.url.split("?",1)[0].rstrip("/") != "https://chatgpt.com/c/"+cid:
                        continue
                    return page.evaluate("""() => {
                      let nodes=[...document.querySelectorAll('div[role="textbox"]#prompt-textarea, div[role="textbox"].ProseMirror')];
                      let fb=[...document.querySelectorAll('textarea#prompt-textarea')];
                      let visible=e=>!!(e.getClientRects().length>0 && getComputedStyle(e).visibility!=='hidden');
                      return {
                        route: location.pathname.startsWith('/c/'),
                        readyState: document.readyState,
                        named_textboxes: nodes.length,
                        named_visible: nodes.filter(visible).length,
                        named_editable: nodes.filter(e=>visible(e)&&e.isContentEditable).length,
                        fallback_count: fb.length,
                        fallback_visible: fb.filter(visible).length,
                        form_count: document.querySelectorAll('form').length,
                        submit_button_count: document.querySelectorAll('button[type="submit"]').length,
                        app_has_nav: !!document.querySelector('nav')
                      };
                    }""")
        return {"error":"NO_OWNED_TARGET"}
    def safe_vendor_error_kinds():
        patterns=("No composer found","Navigation to","send_baseline_unavailable",
                  "Send not acknowledged","send-readiness not established","CDP disconnected",
                  "Page ready","Cannot establish","does not match",
                  "SendReadinessError","CDPJSError","Chat error:")
        summary={}
        for log in ROOT.glob("vendor-*.log"):
            content=log.read_text("utf-8",errors="replace")
            for token in patterns:
                if token.lower() in content.lower():
                    summary[token]=summary.get(token,0)+content.lower().count(token.lower())
        print("VENDOR_QA_SAFE_ERROR_CATEGORIES="+json.dumps(summary,sort_keys=True),flush=True)
        # Vendor already captures its own live DOM selector diagnostics when
        # type_message fails. Publish only booleans and counts, never URL,
        # page title, messages, body preview, or any account identifier.
        import re
        allow=("button_count","textarea_count","composer_found","composer_text_length",
               "composer_enabled","send_candidates_count",
               "enabled_send_candidates_count","stop_button_present",
               "generating_indicator_present")
        safe=[]
        for log in ROOT.glob("vendor-*.log"):
            for line in log.read_text("utf-8",errors="replace").splitlines():
                if "Selector drift diagnostic" not in line:continue
                match=re.search(r"([{][^{}]*[}])\s*$",line)
                if not match:
                    safe.append({"diagnostic":"missing_json"})
                    continue
                try:
                    body=json.loads(match.group(1))
                    safe.append({k:body.get(k) for k in allow if k in body})
                except Exception:
                    safe.append({"diagnostic":"json_parse_failed"})
        print("VENDOR_QA_SANITIZED_COMPOSER_SNAPSHOTS="+json.dumps(safe[-6:],sort_keys=True),flush=True)
        # These are synthetic QA conversations only. Redact all URL, IDs,
        # emails and QA marker tokens before exposing bounded vendor errors.
        safe_errors=[]
        for log in ROOT.glob("vendor-*.log"):
            for line in log.read_text("utf-8",errors="replace").splitlines():
                if "Chat error:" not in line and "SendReadinessError:" not in line:
                    continue
                msg=line.split("Chat error:",1)[-1] if "Chat error:" in line else line.split("SendReadinessError:",1)[-1]
                msg=re.sub(r"https?://[^\s]+","<URL>",msg)
                msg=re.sub(r"[A-Za-z0-9_.%+-]+@[A-Za-z0-9.-]+","<EMAIL>",msg)
                msg=re.sub(r"room_[a-f0-9]{32}","<ROOM>",msg)
                msg=re.sub(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b","<CID>",msg,re.I)
                msg=re.sub(r"HITEL_QA_[A-Z0-9_]+","<QA_TOKEN>",msg)
                msg=re.sub(r"[^\x20-\x7e가-힣]","?",msg)
                safe_errors.append(msg.strip()[:230])
        print("VENDOR_QA_SANITIZED_FAILURE_REASONS="+json.dumps(safe_errors[-8:],ensure_ascii=False),flush=True)
    try:
        ea,es=await asyncio.gather(pool.endpoint(ra,9222),pool.endpoint(rs,9222))
        reg=json.loads((Path.home()/".chatgpt_web2api"/"owned_tabs.json").read_text("utf-8"))
        slots=pool.inspect()
        ta=find_target(reg,pool._rooms[ra].instance_id)
        ts=find_target(reg,pool._rooms[rs].instance_id)
        report("C01","PASS" if (ea!=es and ta!=ts and len({ra,rs})==2) else "FAIL",
            f"separate_api_ports={ea!=es}; distinct_cdp_target_ids={ta!=ts}; registry_owned=2","real_chrome")
        report("S07","PASS" if ta!=ts else "FAIL","두 개 독립 ChatGPT CDP Target.createTarget 소유권","real_chrome")

        def send(room,endpoint,turn,cid=None,text=None):
            label=ids[room];marker=f"HITEL_QA_{label}_{seed}_{turn}"
            prompt=text if text is not None else f"이것은 기능 검증용 격리 대화입니다. 다른 내용 없이 정확히 {marker} 만 출력하십시오."
            return post_chat_uri(prompt,cid,endpoint,internal_owned_room=True),marker

        # First two requests run truly concurrently to test independent browser tabs.
        (a1,ma),(s1,ms)=await asyncio.gather(
            asyncio.to_thread(send,ra,ea,1),
            asyncio.to_thread(send,rs,es,1),
        )
        a_answer,a_cid=a1;s_answer,s_cid=s1
        own=(ma in a_answer and ms not in a_answer and ms in s_answer and ma not in s_answer and a_cid!=s_cid)
        report("C03","PASS" if own else "FAIL",f"parallel_first_turn; correct_response_isolation={own}; cid_distinct={a_cid!=s_cid}","real_chrome")
        sessions[ra]=a_cid;sessions[rs]=s_cid
        for rid in (ra,rs):
            try:
                print("REAL_CHROME_POST_FIRST_TURN_DOM_"+ids[rid]+"="+json.dumps(
                    await asyncio.to_thread(cdp_probe,rid),sort_keys=True),flush=True)
            except Exception as e:
                print("REAL_CHROME_DOM_PROBE_ERROR_"+ids[rid]+"="+type(e).__name__,flush=True)
        print("QA_DIFFERENTIAL_DIRECT_VENDOR_FOLLOWUP_NO_POOL_NAVIGATION",flush=True)
        # S2: exact 20 synthetic source titles, never a user's research dataset.
        synthetic=[{"no":i,"id":f"SIM{i:03d}","title":f"중학교 {1+(i%3)}학년 수학 가상 교재 {i}"} for i in range(1,21)]
        prompt="실제 서비스 연동을 시험하는 합성 가상 제목 20개입니다. 원본 사용자 자료가 아닙니다. 반드시 JSON 객체 하나만 출력하십시오. 구조는 "+'{"rows":[{"no":1,"id":"SIM001","school":"중등","grade":"1","semester":"1","subject":"수학","edition":"해당없음","download":"대상","reason":"중학교 수학 가상 교재"}]}'+" 와 같으며 전체 20개 모든 no/id를 정확히 포함하십시오. 제목에 따라 grade를 판단하십시오. "+json.dumps(synthetic,ensure_ascii=False)
        async def follow(rid,endpoint,turn,text=None,verify_pool_route=False):
            cid=sessions[rid]
            pool.pin(rid)
            try:
                if verify_pool_route:
                    await pool.navigate_existing(rid,9222,f"https://chatgpt.com/c/{cid}")
                (answer,new_cid),marker=await asyncio.to_thread(send,rid,endpoint,turn,cid,text)
                if cid!=new_cid:
                    raise AssertionError("ROOM_CONVERSATION_CHANGED")
                return answer,marker
            except Exception as err:
                print(f"REAL_CHROME_TURN_ERROR_ROOM={ids[rid]} TURN={turn} POOL_NAV={verify_pool_route} CLASS={type(err).__name__} MESSAGE={str(err)[:110]}",flush=True)
                raise
            finally:
                pool.unpin(rid)
        (a2,ma2),(s2,ms2)=await asyncio.gather(follow(ra,ea,2),follow(rs,es,2,prompt))
        print("REAL_CHROME_A_SECOND_REPLY_MARKER_OK="+str(ma2 in a2),flush=True)
        try:
            raw=s2.strip()
            if raw.startswith("```"):
                raw=raw.split("\n",1)[-1].rsplit("```",1)[0].strip()
            obj=json.loads(raw);found=obj.get("rows",[])
            good=len(found)==20 and {(int(x["no"]),str(x["id"])) for x in found}=={(i,f"SIM{i:03d}") for i in range(1,21)}
            report("S02","PASS" if good else "FAIL",f"synthetic_20_titles; returned_rows={len(found)}; exact_ids={good}","real_chrome")
        except Exception as e:
            report("S02","FAIL",f"synthetic_20_title_json_invalid; reason={type(e).__name__}; reply_chars={len(s2)}","real_chrome")
        print("QA_DIFFERENTIAL_FULL_POOL_NAVIGATION_FOLLOWUP",flush=True)
        (a3,ma3),(s3,ms3)=await asyncio.gather(
            follow(ra,ea,3,verify_pool_route=True),
            follow(rs,es,3,verify_pool_route=True))
        good_a=ma in a_answer and ma2 in a2 and ma3 in a3
        good_s=ms in s_answer and ms3 in s3
        report("C02","PASS" if good_a and good_s else "FAIL",f"three_turns_each; A={good_a},S={good_s},distinct={a_cid!=s_cid}","real_chrome")
        report("A05","PASS" if good_a else "FAIL","합성 A 연구방 3연속 회신 및 동일 cid 유지; 실원본 연구 아님","real_chrome")
        report("S06","PASS" if good_s and "S02" in results and results["S02"]["status"]=="PASS" else "FAIL","Scribd 합성 20건 후 같은 방 후속 전송 완료","real_chrome")
        # Visibility probe on real tab, then negative-control on separate throwaway page.
        def dom_probe():
            with sync_playwright() as pw:
                browser=pw.chromium.connect_over_cdp("http://127.0.0.1:9222",timeout=15000)
                ctx=browser.contexts[0]
                pages=list(ctx.pages)
                live_count=0
                for page in pages:
                    if page.url.startswith(("https://chatgpt.com/c/","https://chatgpt.com/")):
                        try:
                            textbox=page.locator('div[role="textbox"].ProseMirror, div[role="textbox"]#prompt-textarea')
                            if textbox.count() and textbox.first.is_visible() and textbox.first.is_enabled():
                                live_count+=1
                        except Exception:pass
                scratch=ctx.new_page()
                try:
                    scratch.goto("about:blank")
                    scratch.set_content('<html><body><textarea id="prompt-textarea" style="display:none"></textarea></body></html>')
                    false_positive=scratch.evaluate('Boolean(document.querySelector(\'div[role="textbox"]#prompt-textarea, div[role="textbox"].ProseMirror\') || document.querySelector(\'textarea#prompt-textarea\'))')
                    visible=scratch.locator('textarea#prompt-textarea').is_visible()
                finally:
                    scratch.close()
                return live_count,false_positive,visible
        count,false_positive,is_visible=await asyncio.to_thread(dom_probe)
        report("C04","FAIL" if false_positive and not is_visible else "PASS",f"real_tab_editors_visible={count}; hidden_textarea_wrongly_accepted={false_positive}; scratch_visible={is_visible}","real_chrome")
    except Exception as e:
        import traceback
        stack=[(Path(t.filename).name,t.lineno,t.name) for t in traceback.extract_tb(e.__traceback__)]
        print("REAL_CHROME_QA_EXCEPTION="+type(e).__name__+":"+str(e)[:300],flush=True)
        print("REAL_CHROME_SAFE_ERROR_STACK="+json.dumps(stack[-12:]),flush=True)
        try:
            for rid in (ra,rs):
                if rid in pool._rooms:
                    print("REAL_CHROME_FAILURE_DOM_"+ids[rid]+"="+json.dumps(
                        await asyncio.to_thread(cdp_probe,rid),sort_keys=True),flush=True)
        except Exception as probe_error:
            print("REAL_CHROME_FAILURE_PROBE_ERROR="+type(probe_error).__name__,flush=True)
        safe_vendor_error_kinds()
        for key in ("C01","C02","C03","C04","A05","S02","S06","S07"):
            if key not in results or results[key]["status"]=="미검증":
                report(key,"FAIL",type(e).__name__+":"+str(e)[:150],"real_chrome")
    finally:
        await pool.close()
    print("BROWSER_PHASE_DONE",flush=True)

if __name__=="__main__":
    mode=sys.argv[1] if len(sys.argv)>1 else "contracts"
    if mode=="contracts":contracts()
    elif mode=="browser":
        if RESULTS.exists():results.update(json.loads(RESULTS.read_text("utf-8")))
        asyncio.run(browser())
    else:raise SystemExit("mode must be contracts or browser")
    counts={k:sum(1 for x in results.values() if x["status"]==k) for k in ("PASS","FAIL","미검증")}
    print("FINAL_27_SCENARIO_COUNTS="+json.dumps(counts,ensure_ascii=False),flush=True)
