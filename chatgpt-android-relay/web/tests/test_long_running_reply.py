"""Regression for the premature 150-second HITEL ChatGPT failure.

A delayed assistant response is not a verified terminal failure. At >=10 min
the relay only updates a visible progress stage, and must preserve the job,
room, WebSocket worker and next-job ordering. No external network requests.
"""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

_data=tempfile.TemporaryDirectory(prefix="hitel-long-reply-")
os.environ["RELAY_DATA_DIR"]=_data.name
os.environ["PUBLIC_SMOKE_ONLY"]="1"
os.environ["WEB_SESSION_SIGNING_KEY"]="test-only-long-reply-contract-20261119"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import api_v1
import app


class LongReplyWaitTests(unittest.TestCase):
    def test_slow_job_remains_running_after_ten_minutes(self):
        self.assertGreaterEqual(app.JOB_SLOW_NOTICE_SECONDS,600)
        uid="usr_long_reply_regression"
        rid="room_"+api_v1.new_id()
        now=api_v1.clock()
        with api_v1.connection() as db:
            db.execute("INSERT INTO users(id,name,api_key_hash,created_at) VALUES(?,?,?,?)",
                       (uid,"Synthetic only","synthetic-never-valid",now))
            db.execute("""INSERT INTO rooms
                    (id,user_id,title,android_state,created_at,updated_at)
                    VALUES(?,?,?,?,?,?)""",
                    (rid,uid,"Long reasoning room","active",now,now))
            job=api_v1.store_job(db,uid,rid,"chat.send","Synthetic long answer",[])
            db.execute("UPDATE jobs SET status='running',stage='dispatched' WHERE id=?",(job,))
        prev_job,prev_transport=app.active_job_id,app.active_job_transport
        try:
            app.active_job_id=job
            app.active_job_transport="web2api"
            with patch.object(app.asyncio,"sleep",new_callable=AsyncMock) as sleeper:
                with patch.object(app,"broadcast",new_callable=AsyncMock) as publish:
                    asyncio.run(app.job_timeout(job))
                    sleeper.assert_awaited_once_with(app.JOB_SLOW_NOTICE_SECONDS)
                    publish.assert_awaited_once()
            with api_v1.connection() as db:
                state=db.execute("SELECT status,stage,error,room_id FROM jobs WHERE id=?",(job,)).fetchone()
            self.assertEqual(state["status"],"running")
            self.assertEqual(state["stage"],"waiting_for_verified_reply")
            self.assertIsNone(state["error"])
            self.assertEqual(state["room_id"],rid)
            self.assertEqual(app.active_job_id,job)
            self.assertEqual(app.active_job_transport,"web2api")
        finally:
            app.active_job_id,app.active_job_transport=prev_job,prev_transport


if __name__=="__main__":
    unittest.main()
