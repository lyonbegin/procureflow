"""Real in-process ASGI WebSocket protocol test for two independent agents.

No browser, no Codex, no GitHub secrets, no ChatGPT sends, no new Railway.
The actual FastAPI WebSocket handler is exercised with two independent
full-duplex socket objects and simulated worker reply events.
"""
import asyncio
import base64
import hashlib
import importlib
import json
import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import WebSocketDisconnect, HTTPException

WEB=Path(__file__).resolve().parents[1]/"chatgpt-android-relay"/"web"
sys.path.insert(0,str(WEB))
api=types.ModuleType("api_v1")
public=types.ModuleType("integration_public")
events=types.ModuleType("long_job_events")
public.ROOM_ID=re.compile(r"^room_[a-f0-9]{32}$")
public.MAX_TEXT=24000
class PublicChat:
    def __init__(self,*,text,request_id,room_id):
        self.text=text
        self.request_id=request_id
        self.room_id=room_id
public.PublicChat=PublicChat
sys.modules["api_v1"]=api
sys.modules["integration_public"]=public
sys.modules["long_job_events"]=events
stream=importlib.import_module("integration_agent_stream")
stream.POLL_SECONDS=0.01


class SimulatedSocket:
    def __init__(self):
        self.incoming=asyncio.Queue()
        self.outgoing=asyncio.Queue()
        self.sent=[]
        self.accepted=False

    async def accept(self):
        self.accepted=True

    async def send_json(self,data):
        self.sent.append(data)
        await self.outgoing.put(data)

    async def receive_text(self):
        val=await self.incoming.get()
        if val is None:
            raise WebSocketDisconnect(code=1000)
        return val

    async def emit(self,content):
        await self.incoming.put(json.dumps(content,ensure_ascii=False))

    async def receive(self):
        return await asyncio.wait_for(self.outgoing.get(),timeout=4)

    async def disconnect(self):
        await self.incoming.put(None)


class FakeJobs:
    def __init__(self):
        self.jobs={}
        self.once=set()
        self.first_barrier=asyncio.Barrier(2)
        self.current=0
        self.highwater=0
        self.rooms={}
        self.stall_agent=None
        self.calls={}

    def open_room(self,name):
        digest=hashlib.sha256(name.encode()).hexdigest()[:32]
        rid="room_"+digest
        self.rooms[name]=rid
        return {"room_id":rid,"room_name":name,"created":True,
                "status":"active","conversation_linked":False}

    async def submit(self,request):
        rid,reqid=request.room_id,request.request_id
        if rid not in self.rooms.values():
            raise ValueError("NON_PUBLIC_ROOM")
        if reqid in self.jobs:
            j=self.jobs[reqid]
            if j["room_id"]!=rid or j["text"]!=request.text:
                raise ValueError("REQUEST_ID_REUSED_FOR_DIFFERENT_ROOM")
            return {"room_id":rid,"request_id":reqid,"job_id":j["job_id"]}
        if any(j["room_id"]==rid and not j.get("finished",False) for j in self.jobs.values()):
            raise ValueError("ROOM_BUSY")
        self.current+=1
        self.highwater=max(self.highwater,self.current)
        try:
            if len(self.jobs)<2:
                # Both distinct first turns must genuinely be submitted together.
                await asyncio.wait_for(self.first_barrier.wait(),timeout=3)
            await asyncio.sleep(0.003)
            jobid="job_"+hashlib.md5(reqid.encode()).hexdigest()
            reply="AGENT_REPLY_"+request.text
            agent="A" if rid==self.rooms["AGENT_A"] else "B"
            fail=self.stall_agent==agent and "_02" in reqid
            self.jobs[reqid]={"room_id":rid,"request_id":reqid,"job_id":jobid,
                               "text":request.text,"reply":reply,"failed":fail,
                               "finished":False}
            self.calls[reqid]=self.calls.get(reqid,0)+1
            return {"room_id":rid,"request_id":reqid,"job_id":jobid}
        finally:
            self.current-=1

    def _lookup(self,jobid):
        return next(item for item in self.jobs.values() if item["job_id"]==jobid)

    def read(self,jobid):
        item=self._lookup(jobid)
        item["finished"]=True
        result=item["reply"].encode("utf-8")
        status="stalled" if item["failed"] else "completed"
        return {"job_id":jobid,"room_id":item["room_id"],
                "request_id":item["request_id"],
                "status":status,"stage":"web2api_received" if item["failed"] else "completed",
                "error_code":"WEB2API_ADAPTER_HTTP_500_COMPOSER_UNAVAILABLE" if item["failed"] else None,
                "assistant_reply_observed":not item["failed"],
                "result_ready":not item["failed"],
                "result_length_bytes":len(result),
                "result_sha256":hashlib.sha256(result).hexdigest()}

    def bytes(self,jobid,offset,limit):
        item=self._lookup(jobid)
        data=item["reply"].encode("utf-8")
        chunk=data[offset:offset+limit]
        return {"job_id":jobid,"room_id":item["room_id"],
                "request_id":item["request_id"],
                "result_sha256":hashlib.sha256(data).hexdigest(),
                "content_base64":base64.b64encode(chunk).decode("ascii"),
                "bytes_returned":len(chunk)}


class PersistentTwoAgentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.jobs=FakeJobs()
        self.active=[]
        self.patchers=[
            patch.object(stream,"_open_public_room_once",self.jobs.open_room),
            patch.object(stream,"_existing_worker_preflight",lambda: None),
            patch.object(public,"submit_public_chat",self.jobs.submit,create=True),
            patch.object(public,"read_public_result",self.jobs.read,create=True),
            patch.object(public,"read_public_result_bytes",self.jobs.bytes,create=True),
        ]
        for p in self.patchers:p.start()
        self.addAsyncCleanup(self.cleanup)

    async def cleanup(self):
        for socket,task in self.active:
            await socket.disconnect()
            try:await asyncio.wait_for(task,timeout=3)
            except (WebSocketDisconnect,asyncio.TimeoutError):
                task.cancel()
        for p in reversed(self.patchers):p.stop()

    async def connect(self,name):
        ws=SimulatedSocket()
        task=asyncio.create_task(stream.agent_stream(ws))
        self.active.append((ws,task))
        ready=await ws.receive()
        self.assertEqual(ready["type"],"session.ready")
        await ws.emit({"type":"room.open","room_name":name})
        bound=await ws.receive()
        self.assertEqual(bound["type"],"room.bound")
        return ws,bound["room_id"]

    async def turn(self,ws,room,label,idx):
        marker=f"{label}_DIFFERENT_QUESTION_{idx:02d}"
        reqid=f"HI_WS_CONCURRENT_{label}_{idx:02d}"
        await ws.emit({"type":"chat.send","room_id":room,"seq":idx,
                       "request_id":reqid,"text":marker})
        events=[]
        while True:
            item=await ws.receive()
            events.append(item)
            self.assertEqual(item.get("room_id"),room)
            self.assertEqual(item.get("request_id"),reqid)
            self.assertEqual(item.get("seq"),idx)
            if item["type"] in ("reply.done","reply.unverified"):
                break
        self.assertEqual(events[0]["type"],"job.accepted")
        if events[-1]["type"]=="reply.done":
            chunks=[base64.b64decode(x["data_base64"]) for x in events if x["type"]=="reply.chunk"]
            answer=b"".join(chunks).decode("utf-8")
            self.assertEqual(answer,"AGENT_REPLY_"+marker)
            self.assertEqual(hashlib.sha256(answer.encode()).hexdigest(),events[-1]["sha256"])
            self.assertNotIn("AGENT_REPLY_"+("B" if label=="A" else "A")+"_DIFFERENT",answer)
        return events[-1]

    async def test_24_interleaved_websocket_messages_two_bound_agents(self):
        a,ar=await self.connect("AGENT_A")
        b,br=await self.connect("AGENT_B")
        self.assertNotEqual(ar,br)
        result=await asyncio.gather(*[
            self.parallel_agent(ws,rid,name)
            for ws,rid,name in [(a,ar,"A"),(b,br,"B")]
        ])
        self.assertEqual(result,[12,12])
        self.assertEqual(len(self.jobs.jobs),24)
        self.assertEqual(len(self.jobs.calls),24)
        self.assertTrue(all(x==1 for x in self.jobs.calls.values()))
        self.assertGreaterEqual(self.jobs.highwater,2)
        print("PASS_TWO_AGENT_PERSISTENT_WEBSOCKETS_REAL_HANDLER_24_TURNS_CROSSTALK_0_REPLAY_0",flush=True)

    async def parallel_agent(self,ws,room,label):
        for i in range(1,13):
            result=await self.turn(ws,room,label,i)
            self.assertEqual(result["type"],"reply.done")
        return 12

    async def test_one_agent_stalls_other_websocket_continues(self):
        self.jobs.stall_agent="A"
        a,ar=await self.connect("AGENT_A")
        b,br=await self.connect("AGENT_B")
        await asyncio.gather(self.turn(a,ar,"A",1),self.turn(b,br,"B",1))
        e,bresult=await asyncio.gather(self.turn(a,ar,"A",2),self.turn(b,br,"B",2))
        self.assertEqual(e["type"],"reply.unverified")
        self.assertTrue(e["never_auto_retry"])
        self.assertEqual(e["error_code"],"WEB2API_ADAPTER_HTTP_500_COMPOSER_UNAVAILABLE")
        self.assertEqual(bresult["type"],"reply.done")
        self.assertEqual(self.jobs.calls["HI_WS_CONCURRENT_A_02"],1)
        print("PASS_WS_AGENT_A_STALLED_AND_B_CONTINUED_WITHOUT_AUTOMATIC_REPOST",flush=True)

    async def test_socket_is_one_room_and_rejects_rebinding(self):
        a,rid=await self.connect("AGENT_A")
        await a.emit({"type":"room.open","room_name":"AGENT_B"})
        reply=await a.receive()
        self.assertEqual(reply["error_code"],"SESSION_ROOM_REBIND_FORBIDDEN")
        await a.emit({"type":"chat.send","room_id":"room_"+"0"*32,
                      "seq":1,"request_id":"HI_WS_OTHER_ROOM_01","text":"bad"})
        reply=await a.receive()
        self.assertEqual(reply["error_code"],"AGENT_NOT_BOUND_TO_MESSAGE_ROOM")
        self.assertEqual(len(self.jobs.jobs),0)
        print("PASS_WS_AGENT_BOUND_ROOM_CANNOT_SWITCH_OR_SEND_CROSS_ROOM",flush=True)

    async def test_reconnect_resumes_original_job_without_resending(self):
        self.jobs.first_barrier=asyncio.Barrier(1)
        a,ar=await self.connect("AGENT_A")
        rid=ar
        reqid="HI_WS_RESUME_SAME_JOB_01"
        await a.emit({"type":"chat.send","room_id":rid,"seq":1,
                      "request_id":reqid,"text":"ORIGINAL_QUESTION_ONLY"})
        accepted=await a.receive()
        self.assertEqual(accepted["type"],"job.accepted")
        old_job=accepted["job_id"]
        await a.disconnect()
        async def valid_room(roomid):
            return {"room_id":roomid,"room_name":"AGENT_A",
                    "status":"active","conversation_linked":True}
        def sync_room(roomid):
            if roomid!=rid:raise ValueError("OTHER_ROOM")
            return {"room_id":rid,"room_name":"AGENT_A",
                    "status":"active","conversation_linked":True}
        def existing_request(requestid):
            job=self.jobs.jobs[requestid]
            return {"job_id":job["job_id"],"room_id":job["room_id"],
                    "request_id":requestid}
        with patch.object(stream,"_confirmed_public_room",sync_room), \
             patch.object(public,"lookup_existing_request",existing_request,create=True):
            sock=SimulatedSocket()
            task=asyncio.create_task(stream.agent_stream(sock))
            self.active.append((sock,task))
            await sock.receive()
            await sock.emit({"type":"room.bind","room_id":rid})
            rebound=await sock.receive()
            self.assertEqual(rebound["type"],"room.bound")
            await sock.emit({"type":"job.resume","room_id":rid,"seq":1,
                             "request_id":reqid})
            reply=await sock.receive()
            self.assertEqual(reply["type"],"job.accepted")
            self.assertTrue(reply["replayed"])
            self.assertEqual(reply["job_id"],old_job)
            while True:
                nxt=await sock.receive()
                if nxt["type"] in ("reply.done","reply.unverified"):
                    break
            self.assertEqual(nxt["type"],"reply.done")
        self.assertEqual(self.jobs.calls[reqid],1)
        print("PASS_WS_RECONNECT_RESUME_READ_ONLY_JOB_ID_UNCHANGED_NO_NEW_POST",flush=True)

    async def test_same_agent_cannot_flood_two_jobs_before_reply(self):
        self.jobs.first_barrier=asyncio.Barrier(1)
        a,ar=await self.connect("AGENT_A")
        original_read=self.jobs.read
        def slow_read(job_id):
            import time
            time.sleep(0.09)
            return original_read(job_id)
        with patch.object(public,"read_public_result",slow_read,create=True):
            await a.emit({"type":"chat.send","room_id":ar,"seq":1,
                          "request_id":"HI_WS_BUSY_FIRST_JOB_01","text":"first"})
            accepted=await a.receive()
            self.assertEqual(accepted["type"],"job.accepted")
            await a.emit({"type":"chat.send","room_id":ar,"seq":2,
                          "request_id":"HI_WS_BUSY_SECOND_JOB_02","text":"second"})
            got_busy=False
            got_done=False
            for _ in range(8):
                item=await a.receive()
                if item["type"]=="request.error":
                    self.assertEqual(item["error_code"],"ROOM_JOB_BUSY")
                    got_busy=True
                if item["type"]=="reply.done":
                    got_done=True
                if got_busy and got_done:break
            self.assertTrue(got_busy)
            self.assertTrue(got_done)
        self.assertEqual(len(self.jobs.jobs),1)
        print("PASS_WS_AGENT_FLOOD_IS_BLOCKED_WHILE_EXISTING_JOB_PENDING",flush=True)


    async def test_worker_offline_fails_before_any_submission_and_reports_503(self):
        a,ar=await self.connect("AGENT_A")
        req="HI_WS_OFFLINE_PREFLIGHT_01"
        with patch.object(stream,"_existing_worker_preflight",
                          side_effect=HTTPException(status_code=503,detail="WORKER_NOT_CONNECTED")):
            await a.emit({"type":"chat.send","room_id":ar,"seq":1,"request_id":req,
                          "text":"do not send"})
            fail=await a.receive()
        self.assertEqual(fail["type"],"request.error")
        self.assertEqual(fail["http_status"],503)
        self.assertEqual(fail["error_code"],"WORKER_NOT_CONNECTED")
        self.assertEqual(fail["room_id"],ar)
        self.assertEqual(fail["request_id"],req)
        self.assertEqual(len(self.jobs.jobs),0)
        print("PASS_OFFLINE_WORKER_REFUSED_BEFORE_ANY_JOB_OR_NEW_WORKFLOW",flush=True)

    async def test_409_is_not_hidden_as_httpexception_and_never_submits(self):
        a,ar=await self.connect("AGENT_A")
        req="HI_WS_CONFLICT_PREFLIGHT_01"
        async def conflict(_):
            raise HTTPException(status_code=409,detail="different room")
        with patch.object(public,"submit_public_chat",conflict,create=True):
            await a.emit({"type":"chat.send","room_id":ar,"seq":1,
                          "request_id":req,"text":"do not send"})
            failed=await a.receive()
        self.assertEqual(failed["type"],"request.error")
        self.assertEqual(failed["http_status"],409)
        self.assertEqual(failed["error_code"],"ROOM_OR_REQUEST_CONFLICT")
        self.assertEqual(len(self.jobs.jobs),0)
        print("PASS_HTTP_409_TYPED_CONFLICT_WITHOUT_LEAKING_MESSAGE_TEXT",flush=True)

    async def test_job_notifications_are_exact_job_id_scoped(self):
        a=asyncio.Event()
        b=asyncio.Event()
        jid_a="job_"+"a"*32
        jid_b="job_"+"b"*32
        stream._JOB_NOTIFIERS[jid_a]={a}
        stream._JOB_NOTIFIERS[jid_b]={b}
        try:
            stream.notify_job_changed(jid_a)
            self.assertTrue(a.is_set())
            self.assertFalse(b.is_set())
            a.clear()
            stream.notify_job_changed("job_"+"c"*32)
            self.assertFalse(a.is_set())
            self.assertFalse(b.is_set())
            stream.notify_job_changed(jid_b)
            self.assertTrue(b.is_set())
        finally:
            stream._JOB_NOTIFIERS.pop(jid_a,None)
            stream._JOB_NOTIFIERS.pop(jid_b,None)
        print("PASS_JOB_EVENT_NOTIFICATIONS_DELIVER_ONLY_TO_OWNING_AGENT",flush=True)

    async def test_scope_validation_rejects_other_job_id(self):
        with self.assertRaisesRegex(ValueError,"REPLY_ROOM_REQUEST_JOB_MISMATCH"):
            stream._job_scope({"room_id":"room_"+"a"*32,
                               "request_id":"A_REQ","job_id":"job_"+"a"*32},
                               room_id="room_"+"b"*32,
                               request_id="A_REQ",job_id="job_"+"a"*32)


if __name__=="__main__":
    unittest.main(verbosity=2)
