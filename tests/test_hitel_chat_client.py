import asyncio
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("hitel_chat", Path(__file__).resolve().parents[1] / "tools/hitel_chat.py")
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)

ROOM = "room_" + "a" * 32
REQUEST = "hitel-client-saved-request-001"
JOB = "job_" + "b" * 32
SESSION = "hws_test"
BODY = "한글 답변".encode("utf-8")

class Socket:
    def __init__(self, packets):
        self.packets = iter(packets)
        self.sent = []
    async def send(self, packet):
        self.sent.append(json.loads(packet))
    async def recv(self):
        return json.dumps(next(self.packets))

def packets():
    scope = dict(session_id=SESSION, room_id=ROOM, request_id=REQUEST, job_id=JOB, seq=1)
    return [
        dict(type="session.ready", session_id=SESSION),
        dict(type="room.bound", session_id=SESSION, room_id=ROOM),
        dict(type="job.accepted", **scope),
        dict(type="reply.chunk", offset=0, data_base64=base64.b64encode(BODY).decode(), **scope),
        dict(type="reply.done", verified=True, bytes=len(BODY),
             sha256=hashlib.sha256(BODY).hexdigest(), **scope)
    ]

class ClientTests(unittest.IsolatedAsyncioTestCase):
    def checkpoint(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return Path(temp.name) / "state.json"

    def pending(self):
        return dict(room_name="A", room_id=ROOM, request_id=REQUEST, job_id=JOB,
                    seq=1, status="running", text_sha256=hashlib.sha256(b"old").hexdigest())

    async def test_resume_only_observes_saved_job_and_verifies_utf8(self):
        path = self.checkpoint()
        ws = Socket(packets())
        state = self.pending()
        result = await client.exchange(ws, path, state, resume=True)
        self.assertEqual(result, BODY.decode())
        self.assertEqual([p["type"] for p in ws.sent], ["room.bind", "job.resume"])
        self.assertEqual(ws.sent[-1]["request_id"], REQUEST)
        self.assertEqual(json.loads(path.read_text("utf-8"))["status"], "completed")

    async def test_hash_mismatch_never_marks_completed(self):
        path = self.checkpoint()
        items = packets()
        items[-1]["sha256"] = "0" * 64
        state = self.pending()
        with self.assertRaisesRegex(RuntimeError, "INTEGRITY"):
            await client.exchange(Socket(items), path, state, resume=True)
        self.assertEqual(json.loads(path.read_text("utf-8"))["status"], "running")

    async def test_cross_room_chunk_rejected(self):
        items = packets()
        items[-2]["room_id"] = "room_" + "c" * 32
        with self.assertRaisesRegex(RuntimeError, "SCOPE"):
            await client.exchange(Socket(items), self.checkpoint(), self.pending(), resume=True)

    async def test_out_of_order_chunk_rejected(self):
        items = packets()
        items[-2]["offset"] = 1
        with self.assertRaisesRegex(RuntimeError, "OFFSET"):
            await client.exchange(Socket(items), self.checkpoint(), self.pending(), resume=True)

    async def test_pending_request_blocks_new_question(self):
        ws = Socket(packets())
        with self.assertRaisesRegex(RuntimeError, "PENDING_REQUEST"):
            await client.exchange(ws, self.checkpoint(), self.pending(), text="different")
        self.assertEqual([p["type"] for p in ws.sent], ["room.bind"])

    async def test_new_request_checkpoint_exists_before_first_send(self):
        path = self.checkpoint()
        state = dict(room_name="A")
        sent = []
        class FreshSocket:
            async def send(self, raw):
                p = json.loads(raw)
                sent.append(p)
                if p["type"] == "chat.send":
                    saved = json.loads(path.read_text("utf-8"))
                    self.request = saved["request_id"]
                    assert saved["status"] == "sending"
                    assert saved["request_id"] == p["request_id"]
                    assert saved["room_id"] == p["room_id"]
            async def recv(self):
                if not sent:
                    return json.dumps(dict(type="session.ready", session_id=SESSION))
                if len(sent) == 1:
                    return json.dumps(dict(type="room.bound", session_id=SESSION, room_id=ROOM))
                raise ConnectionError("connection lost after send")
        with self.assertRaises(ConnectionError):
            await client.exchange(FreshSocket(), path, state, text="새 질문")
        self.assertEqual(json.loads(path.read_text("utf-8"))["status"], "sending")
        self.assertEqual([p["type"] for p in sent], ["room.open", "chat.send"])

if __name__ == "__main__":
    unittest.main()
