#!/usr/bin/env python3
"""Actual ChatGPT Web2API two-agent cross-room stress verification.

ONLY explicit isolated QA conversations, never A/Scribd research rooms.
No Chrome/Playwright/CDP or DOM. No arbitrary secret logging.
Requires a valid, user-provided Codex OAuth auth.json and actual Go gateway
configured for GPTWEB_TRANSPORT_MODE=direct, with browser fallback disabled.

This script must never silently degrade to synthetic replies. No SEND retries
after any error, including HTTP 429; first failure stops the other agent.
"""
from __future__ import annotations
import concurrent.futures
import os
import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from hitel_direct_http_transport import DirectError,DirectWeb2API

NUM_TURNS=12
BARRIER=threading.Barrier(2,timeout=90)

def _agent(client,name,run_tag,stop,rooms,records):
    room="room_"+uuid.uuid4().hex
    rooms[name]=room
    target_url=None
    conversation_id=None
    for number in range(1,NUM_TURNS+1):
        if stop.is_set():
            return
        if number == 1:
            BARRIER.wait()
        marker=f"HITEL_QA_{name}_{run_tag}_{number:02d}"
        prompt=("격리된 API 병렬성 검증용 질문입니다. "
                f"다른 문장을 추가하지 말고 정확히 {marker} 만 출력하십시오.")
        try:
            answer,cid=client.send(room,prompt,target_url)
            if not isinstance(cid,str) or not cid:
                raise DirectError("LIVE_CHATGPT_CONVERSATION_ID_MISSING",after_post=True)
            if conversation_id is not None and cid!=conversation_id:
                raise DirectError("LIVE_CHATGPT_CONVERSATION_CHANGED",after_post=True)
            if answer.strip()!=marker:
                raise DirectError("LIVE_CHATGPT_EXACT_ECHO_MISMATCH",after_post=True)
            other="B" if name=="A" else "A"
            if f"HITEL_QA_{other}_{run_tag}_" in answer:
                raise DirectError("LIVE_CHATGPT_CROSS_ROOM_LEAK",after_post=True)
            conversation_id=cid
            target_url="https://chatgpt.com/c/"+cid
            expected_parent=client.binding(room,target_url).parent_message_id
            records[name].append((number,cid,expected_parent))
            print("LIVE_QA_AGENT="+name+" TURN="+str(number)+
                  " ANSWER_EXACT=true CONVERSATION_STABLE=true PARENT_VERIFIED=true",
                  flush=True)
        except DirectError:
            stop.set()
            raise
        except Exception:
            stop.set()
            raise DirectError("LIVE_CHATGPT_UNCLASSIFIED_FAILURE_NO_RETRY",after_post=True) from None
    if not stop.is_set():
        final_parent=client.fetch_remote_parent(conversation_id)
        if final_parent!=records[name][-1][2]:
            stop.set()
            raise DirectError("LIVE_CHATGPT_REMOTE_PARENT_NOT_MATCHING",after_post=True)
    return conversation_id

def main():
    if os.getenv("GPTWEB_TRANSPORT_MODE") != "direct" or os.getenv("GPTWEB_BROWSER_RELAY_URL"):
        raise DirectError("LIVE_BROWSERLESS_TRANSPORT_GUARD")
    client=DirectWeb2API(oauth_file=os.environ.get("GPTWEB_OAUTH_TOKEN_FILE",""),
                         api_key=os.environ.get("GPTWEB_API_KEY",""),
                         timeout=600)
    client.ready()
    run_tag=uuid.uuid4().hex[:12].upper()
    rooms={}
    records={"A":[],"B":[]}
    stop=threading.Event()
    errors=[]
    cids={}
    started=time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2,thread_name_prefix="HITEL_QA") as executor:
        futures={name:executor.submit(_agent,client,name,run_tag,stop,rooms,records)
                 for name in ("A","B")}
        for name,future in futures.items():
            try:
                cids[name]=future.result(timeout=NUM_TURNS*650)
            except (DirectError,TimeoutError,threading.BrokenBarrierError) as err:
                stop.set()
                errors.append((name,err.code if isinstance(err,DirectError) else type(err).__name__))
            except Exception as err:
                stop.set()
                errors.append((name,type(err).__name__))
    count=sum(map(len,records.values()))
    print("LIVE_QA_FINAL_COUNTS="+str(count)+"/"+str(NUM_TURNS*2)+
          " A="+str(len(records["A"]))+" B="+str(len(records["B"]))+
          " FAILED_AGENT_COUNT="+str(len(errors))+
          " ELAPSED_SECONDS="+str(round(time.monotonic()-started,2)),flush=True)
    for name,kind in errors:
        print("LIVE_QA_FAILED_AGENT="+name+" ERROR_CATEGORY="+kind,flush=True)
    if errors:
        raise SystemExit("FAIL_REAL_TWO_AGENT_CHATGPT_UNVERIFIED_NO_AUTORETRY")
    if (len(records["A"]) != NUM_TURNS or len(records["B"]) != NUM_TURNS
            or len(set(cids.values())) != 2
            or cids["A"] == cids["B"]
            or set(rooms.values()) & {
                "room_e43054eed81d46fba991b946ede92d1b",
                "room_e31b6755688748f6a9ddb5a0f6b3cdaf",
            }):
        raise SystemExit("FAIL_REAL_TWO_AGENT_CHATGPT_ROOM_ISOLATION")
    print("PASS_REAL_TWO_AGENT_CHATGPT_24_POSTS_DISTINCT_ROOMS_NO_CROSSTALK",
          flush=True)

if __name__=="__main__":
    main()
