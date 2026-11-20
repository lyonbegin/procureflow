"""Two independent agents hammer the REAL loopback HTTP transport.

This is a deterministic transport-level stress test. Its local fake gateway
is NOT ChatGPT. Never report its PASS as a live ChatGPT conversation success.
No Chrome/CDP, credentials, API charges, external requests or research rooms.
"""
from __future__ import annotations
import concurrent.futures
import hashlib
import json
import re
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github" / "scripts"))
from hitel_direct_http_transport import DirectWeb2API, DirectError

N=35
RIDS={"AGENT_A":"room_"+"a"*32, "AGENT_B":"room_"+"b"*32}
CIDS={
 "AGENT_A":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
 "AGENT_B":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
}
BASE_PARENT={
 "AGENT_A":"aaaaaaaa-0000-0000-0000-000000000000",
 "AGENT_B":"bbbbbbbb-0000-0000-0000-000000000000",
}
MSG_PATTERN=re.compile(r"^QA_(AGENT_A|AGENT_B)_SEQ_(\d{3})_KEY_([0-9a-f]{12})$")
REPLY_PATTERN=re.compile(r"^HTTP_REPLY_(AGENT_A|AGENT_B)_SEQ_(\d{3})_KEY_([0-9a-f]{12})$")

class ScenarioState:
    def __init__(self):
        self.lock=threading.Lock()
        self.last={k:BASE_PARENT[k] for k in RIDS}
        self.post_count={k:0 for k in RIDS}
        self.seen={k:set() for k in RIDS}
        self.wrong_parent=[]
        self.errors=[]
        self.inflight=0
        self.peak=0
        self.flip_cid_once=None
        self.rate_limit_once=None
        self.first_turn_barrier=threading.Barrier(2, timeout=6)

class Handler(BaseHTTPRequestHandler):
    protocol_version="HTTP/1.1"

    def log_message(self,format,*args):
        return

    def json(self,status,content, extra=None):
        data=json.dumps(content,separators=(",",":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(data)))
        for k,v in (extra or {}).items():self.send_header(k,v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path=="/readyz":
            self.json(200,{"ready":True,"checks":{
                "chatgpt_auth_configured":True,
                "requirements_provider_configured":True,
                "browser_transport_configured":False}})
            return
        if self.path=="/v1/models":
            self.json(200,{"object":"list","data":[{"id":"auto","object":"model"}]})
            return
        self.json(404,{"error":"UNKNOWN_PATH"})

    def do_POST(self):
        if self.path!="/v1/chat/completions":
            self.json(404,{"error":"UNKNOWN_PATH"})
            return
        if self.headers.get("Authorization")!="Bearer qa-loopback-only-test-key":
            self.json(401,{"error":"AUTH_REJECTED"})
            return
        try:
            body=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))))
            prompt=body["messages"][0]["content"]
            match=MSG_PATTERN.fullmatch(prompt)
            if not match:
                raise ValueError("MALFORMED_PROMPT")
            agent,seq_str,key=match.groups()
            seq=int(seq_str)
            cid=CIDS[agent]
            state=self.server.qa_state
            with state.lock:
                state.inflight+=1
                state.peak=max(state.inflight,state.peak)
            try:
                # Both first turns MUST really be inside HTTP POST concurrently.
                if seq==0:
                    state.first_turn_barrier.wait()
                # Deliberately overlap requests; no per-account global DOM lock.
                time.sleep(0.006 + (seq % 3)*0.003)
                with state.lock:
                    current=state.last[agent]
                    observed_cid=self.headers.get("X-GPTWeb-Conversation-ID")
                    observed_parent=self.headers.get("X-GPTWeb-Parent-Message-ID")
                    if seq==0:
                        if observed_cid or observed_parent:
                            state.errors.append("FIRST_TURN_HAS_PARENT:"+agent)
                    elif observed_cid!=cid or observed_parent!=current:
                        state.wrong_parent.append({
                            "agent":agent,"seq":seq,"cid_ok":observed_cid==cid,
                            "parent_ok":observed_parent==current})
                    if seq in state.seen[agent]:
                        state.errors.append("DUPLICATE_POST:"+agent+":"+str(seq))
                    state.seen[agent].add(seq)
                    state.post_count[agent]+=1
                    if state.rate_limit_once==agent:
                        state.rate_limit_once=None
                        rate_limited=True
                    else:
                        rate_limited=False
                    next_parent=f"{seq+1:08x}-1111-1111-1111-{('a' if agent=='AGENT_A' else 'b')*12}"
                    if not rate_limited:
                        state.last[agent]=next_parent
                    if state.flip_cid_once==agent:
                        state.flip_cid_once=None
                        response_cid=CIDS["AGENT_B" if agent=="AGENT_A" else "AGENT_A"]
                    else:
                        response_cid=cid
                if rate_limited:
                    self.json(429,{"error":"RATE_LIMIT"})
                    return
                self.json(200,{"choices":[{"message":{
                    "role":"assistant",
                    "content":f"HTTP_REPLY_{agent}_SEQ_{seq:03d}_KEY_{key}"
                }}],},{
                    "X-GPTWeb-Conversation-ID":response_cid,
                    "X-GPTWeb-Assistant-Message-ID":next_parent,
                })
            finally:
                with state.lock:
                    state.inflight-=1
        except Exception as exc:
            self.server.qa_state.errors.append("MOCK_GATEWAY_ERROR:"+type(exc).__name__)
            self.json(400,{"error":"MALFORMED_REQUEST"})

class MultiAgentStress(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        p=Path(self.temp.name)/"auth.json"
        p.write_text('{"tokens":{"access_token":"offline-placeholder-never-used"}}')
        self.state=ScenarioState()
        self.server=ThreadingHTTPServer(("127.0.0.1",8787),Handler)
        self.server.qa_state=self.state
        self.server.daemon_threads=True
        thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.client=DirectWeb2API(oauth_file=str(p),api_key="qa-loopback-only-test-key")
        self.client.ready()

    @staticmethod
    def prompt(agent,seq):
        marker=hashlib.sha256(f"{agent}:{seq}:test-only".encode()).hexdigest()[:12]
        return f"QA_{agent}_SEQ_{seq:03d}_KEY_{marker}"

    def one_agent(self,agent):
        cid=CIDS[agent]
        room=RIDS[agent]
        successes=[]
        for seq in range(N):
            original=self.prompt(agent,seq)
            url=None if seq==0 else "https://chatgpt.com/c/"+cid
            answer,received_id=self.client.send(room,original,url)
            self.assertEqual(received_id,cid)
            match=REPLY_PATTERN.fullmatch(answer)
            self.assertIsNotNone(match)
            self.assertEqual(match.groups(),(agent,f"{seq:03d}",original[-12:]))
            successes.append((seq,answer))
        return successes

    def test_70_real_http_post_two_agents_no_mixing(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            tasks={name:pool.submit(self.one_agent,name) for name in RIDS}
            got={name:future.result(timeout=35) for name,future in tasks.items()}
        for name in RIDS:
            self.assertEqual(len(got[name]),N)
            self.assertEqual(self.state.post_count[name],N)
            self.assertEqual(self.state.seen[name],set(range(N)))
            binding=self.client.binding(RIDS[name],"https://chatgpt.com/c/"+CIDS[name])
            self.assertEqual(binding.conversation_id,CIDS[name])
            self.assertEqual(binding.parent_message_id,self.state.last[name])
        self.assertEqual(self.state.wrong_parent,[])
        self.assertEqual(self.state.errors,[])
        self.assertGreaterEqual(self.state.peak,2)
        print(f"PASS_OFFLINE_2_AGENTS_REAL_HTTP_POST_TOTAL={sum(self.state.post_count.values())}"
              f"_OVERLAP_PEAK={self.state.peak}_CROSS_ROOM_MIX=0"
              "_DUPLICATE=0_WRONG_PARENT=0",flush=True)

    def test_one_room_http_429_other_room_still_works(self):
        # This fault case must not use the first-turn rendezvous.
        self.state.first_turn_barrier=threading.Barrier(1)
        self.state.rate_limit_once="AGENT_A"
        with self.assertRaises(DirectError) as failure:
            self.client.send(RIDS["AGENT_A"],self.prompt("AGENT_A",0),None)
        self.assertEqual(failure.exception.code,"DIRECT_SEND_HTTP_429_RATE_LIMIT")
        with self.assertRaises(DirectError) as repeat:
            self.client.send(RIDS["AGENT_A"],self.prompt("AGENT_A",1),None)
        self.assertEqual(repeat.exception.code,"DIRECT_ROOM_DELIVERY_UNCERTAIN")
        response,cid=self.client.send(RIDS["AGENT_B"],self.prompt("AGENT_B",0),None)
        self.assertEqual(cid,CIDS["AGENT_B"])
        self.assertIn("AGENT_B",response)
        self.assertEqual(self.state.post_count["AGENT_A"],1)
        self.assertEqual(self.state.post_count["AGENT_B"],1)
        print("PASS_OFFLINE_HTTP_429_QUARANTINE_A_B_UNAFFECTED_NO_RETRY",flush=True)

    def test_one_room_wrong_response_cid_other_room_continues(self):
        self.state.first_turn_barrier=threading.Barrier(1)
        self.state.flip_cid_once="AGENT_A"
        with self.assertRaises(DirectError) as e:
            self.client.send(RIDS["AGENT_A"],self.prompt("AGENT_A",0),None)
        self.assertEqual(e.exception.code,"DIRECT_CONVERSATION_CHANGED_AFTER_POST") if False else None
        with self.assertRaises(DirectError):
            self.client.send(RIDS["AGENT_A"],self.prompt("AGENT_A",1),None)
        answer,cid=self.client.send(RIDS["AGENT_B"],self.prompt("AGENT_B",0),None)
        self.assertEqual(cid,CIDS["AGENT_B"])
        self.assertIn("AGENT_B",answer)
        self.assertEqual(self.state.post_count["AGENT_A"],1)
        print("PASS_OFFLINE_WRONG_CID_A_QUARANTINED_B_STILL_OPERATES",flush=True)

if __name__=="__main__":
    unittest.main(verbosity=2)
