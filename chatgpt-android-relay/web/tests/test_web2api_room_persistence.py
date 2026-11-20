"""Atomic original-room persistence tests, isolated from Railway and ChatGPT."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

_TEMP=tempfile.TemporaryDirectory()
os.environ["RELAY_DATA_DIR"]=_TEMP.name
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api_v1


class TestWeb2ApiScopedResults(unittest.TestCase):
    def setUp(self):
        import uuid
        self.uid="user_"+uuid.uuid4().hex[:12]
        self.room="room_"+uuid.uuid4().hex
        self.room2="room_"+uuid.uuid4().hex
        with api_v1.connection() as c:
            c.execute("INSERT INTO users(id,name,api_key_hash,created_at) VALUES(?,?,?,?)",
                      (self.uid,"test","digest_"+self.uid,api_v1.clock()))
            for rid in (self.room,self.room2):
                c.execute("INSERT INTO rooms(id,user_id,title,android_state,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                          (rid,self.uid,"Test","uncreated",api_v1.clock(),api_v1.clock()))

    def new_job(self, rid=None):
        rid=rid or self.room
        with api_v1.connection() as c:
            jid=api_v1.store_job(c,self.uid,rid,"chat.send","test prompt",[])
            c.execute("UPDATE jobs SET status='running' WHERE id=?", (jid,))
        return jid

    def test_first_turn_binds_original_room_and_only_one_answer(self):
        jid=self.new_job()
        url="https://chatgpt.com/c/12345678-1234-1234-1234-123456789abc"
        self.assertTrue(api_v1.complete_web2api_job(jid,self.room,"fixed reply",url))
        with api_v1.connection() as c:
            room=c.execute("SELECT chatgpt_url,android_state FROM rooms WHERE id=?",(self.room,)).fetchone()
            job=c.execute("SELECT status,stage,result_text FROM jobs WHERE id=?",(jid,)).fetchone()
            msgs=c.execute("SELECT role,text FROM messages WHERE job_id=?",(jid,)).fetchall()
        self.assertEqual(room["chatgpt_url"],url)
        self.assertEqual(room["android_state"],"active")
        self.assertEqual(job["status"],"completed")
        self.assertEqual(job["stage"],"assistant_reply_stable")
        self.assertEqual(job["result_text"],"fixed reply")
        self.assertEqual([(m["role"],m["text"]) for m in msgs],[("assistant","fixed reply")])
        self.assertFalse(api_v1.complete_web2api_job(jid,self.room,"duplicate",url))

    def test_wrong_room_and_invalid_url_rejected(self):
        jid=self.new_job()
        self.assertFalse(api_v1.complete_web2api_job(jid,self.room2,"reply","https://chatgpt.com/c/123456789abc"))
        self.assertFalse(api_v1.complete_web2api_job(jid,self.room,"reply","https://evil.example/c/123456789abc"))
        self.assertFalse(api_v1.complete_web2api_job(jid,self.room,"","https://chatgpt.com/c/123456789abc"))
        with api_v1.connection() as c:
            self.assertEqual(c.execute("SELECT status FROM jobs WHERE id=?",(jid,)).fetchone()["status"],"running")

    def test_existing_target_cannot_be_replaced(self):
        original="https://chatgpt.com/c/12345678-1234-1234-1234-123456789abc"
        with api_v1.connection() as c:
            c.execute("UPDATE rooms SET chatgpt_url=? WHERE id=?",(original,self.room))
        jid=self.new_job()
        self.assertFalse(api_v1.complete_web2api_job(jid,self.room,"reply","https://chatgpt.com/c/87654321-1234-1234-1234-123456789abc"))
        self.assertTrue(api_v1.complete_web2api_job(jid,self.room,"reply",original))

    def test_other_room_ownership_conflict(self):
        target="https://chatgpt.com/c/12345678-1234-1234-1234-123456789abc"
        with api_v1.connection() as c:
            c.execute("UPDATE rooms SET chatgpt_url=? WHERE id=?",(target,self.room2))
        jid=self.new_job()
        self.assertFalse(api_v1.complete_web2api_job(jid,self.room,"reply",target))


if __name__=="__main__":
    unittest.main()
