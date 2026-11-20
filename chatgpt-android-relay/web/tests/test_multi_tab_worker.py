"""Synthetic room-tab isolation contract; no logged-in Chrome or AI writes."""
import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SCRIPT_DIR=Path(__file__).resolve().parents[3]/".github"/"scripts"
sys.path.insert(0,str(SCRIPT_DIR))
from hitel_room_tab_pool import RoomTabPool, TabIsolationError, _same_conversation_route

ROOM_A="room_"+"a"*32
ROOM_B="room_"+"b"*32
ROOM_C="room_"+"c"*32
ROOM_D="room_"+"d"*32

class FakeProcess:
    def __init__(self):
        self.returncode=None
        self.stopped=False
    def terminate(self):
        self.returncode=0
        self.stopped=True
    def kill(self):
        self.returncode=-9
        self.stopped=True
    async def wait(self):
        return self.returncode

class RoomTabIsolationTests(unittest.IsolatedAsyncioTestCase):
    def test_existing_room_exact_url_does_not_require_reload(self):
        a="https://chatgpt.com/c/"+"a"*32
        b="https://chatgpt.com/c/"+"b"*32
        self.assertTrue(_same_conversation_route(a,a))
        self.assertTrue(_same_conversation_route(a+"?model=auto",a))
        self.assertFalse(_same_conversation_route(b,a))
        self.assertFalse(_same_conversation_route("https://chatgpt.com.evil.example/c/"+"a"*32,a))
        self.assertFalse(_same_conversation_route("https://evil@chatgpt.com/c/"+"a"*32,a))
        self.assertFalse(_same_conversation_route("http://chatgpt.com/c/"+"a"*32,a))

    async def test_two_rooms_one_chrome_different_owned_cdp_targets(self):
        launched=[]
        async def spawn(*args,**kwargs):
            proc=FakeProcess()
            launched.append((args,kwargs,proc))
            return proc
        ports=iter([18311,18312,18313])
        pool=RoomTabPool(max_rooms=3)
        with patch("hitel_room_tab_pool._available_port",side_effect=lambda:next(ports)),\
             patch("hitel_room_tab_pool.asyncio.create_subprocess_exec",side_effect=spawn),\
             patch.object(RoomTabPool,"_boot_ready",new_callable=AsyncMock,return_value=True),\
             patch.object(RoomTabPool,"_ready",new_callable=AsyncMock,return_value=True):
            first,second=await asyncio.gather(
                pool.endpoint(ROOM_A,9222),pool.endpoint(ROOM_B,9222))
            self.assertNotEqual(first,second)
            self.assertIn(":18311/",first)
            self.assertIn(":18312/",second)
            self.assertEqual(len(launched),2)
            a,b=launched
            self.assertEqual(a[1]["env"]["W2A_TAB_MODE"],"owned")
            self.assertEqual(b[1]["env"]["W2A_PARALLEL_TABS"],"true")
            self.assertNotEqual(a[1]["env"]["W2A_INSTANCE_ID"],
                                b[1]["env"]["W2A_INSTANCE_ID"])
            self.assertEqual(a[0][-1],"9222")
            self.assertEqual(b[0][-1],"9222")
            # Same room must reuse the SAME vendor/CDP tab, not create another.
            self.assertEqual(await pool.endpoint(ROOM_A,9222),first)
            self.assertEqual(len(launched),2)
            await pool.close()
            self.assertTrue(all(p.stopped for _,_,p in launched))

    async def test_concurrent_busy_rooms_never_evict_or_share_tab(self):
        launched=[]
        async def spawn(*a,**k):
            p=FakeProcess();launched.append(p);return p
        pool=RoomTabPool(max_rooms=2)
        with patch("hitel_room_tab_pool._available_port",side_effect=[18321,18322,18323]),\
             patch("hitel_room_tab_pool.asyncio.create_subprocess_exec",side_effect=spawn),\
             patch.object(RoomTabPool,"_boot_ready",new_callable=AsyncMock,return_value=True),\
             patch.object(RoomTabPool,"_ready",new_callable=AsyncMock,return_value=True):
            pool.pin(ROOM_A);pool.pin(ROOM_B)
            await pool.endpoint(ROOM_A,9222)
            await pool.endpoint(ROOM_B,9222)
            with self.assertRaisesRegex(TabIsolationError,"CAPACITY_EXCEEDED"):
                await pool.endpoint(ROOM_C,9222)
            pool.unpin(ROOM_A)
            # An uncertain reply cannot be evicted even after its async task ends.
            pool.quarantine(ROOM_A)
            with self.assertRaisesRegex(TabIsolationError,"CAPACITY_EXCEEDED"):
                await pool.endpoint(ROOM_C,9222)
            pool.unpin(ROOM_B)
            new_url=await pool.endpoint(ROOM_C,9222)
            self.assertIn(":18323/",new_url)
            self.assertTrue(launched[1].stopped)
            self.assertFalse(launched[0].stopped)
            await pool.close()

    async def test_prelinked_research_rooms_are_never_evicted_by_new_room(self):
        import hitel_room_tab_pool as module
        created=[]
        async def spawn(*args, **kwargs):
            proc=FakeProcess();created.append(proc);return proc
        pool=RoomTabPool(max_rooms=2)
        with patch("hitel_room_tab_pool._available_port",side_effect=[18701,18702,18703]),\
             patch("hitel_room_tab_pool.asyncio.create_subprocess_exec",side_effect=spawn),\
             patch("hitel_room_tab_pool._navigate_owned_target",return_value="owned-cdp-target"),\
             patch.object(RoomTabPool,"_boot_ready",new_callable=AsyncMock,return_value=True),\
             patch.object(RoomTabPool,"_ready",new_callable=AsyncMock,return_value=True):
            await pool.prewarm(ROOM_A,9222,"https://chatgpt.com/c/"+"a"*32)
            await pool.prewarm(ROOM_B,9222,"https://chatgpt.com/c/"+"b"*32)
            self.assertEqual(pool._protected_rooms,{ROOM_A,ROOM_B})
            self.assertEqual(len(created),2)
            with self.assertRaisesRegex(TabIsolationError,"CAPACITY_EXCEEDED"):
                await pool.endpoint(ROOM_C,9222)
            self.assertFalse(any(p.stopped for p in created))
            await pool.close()

    def test_owned_target_already_on_exact_conversation_never_reloads(self):
        import io,json,tempfile
        from unittest.mock import MagicMock
        from hitel_room_tab_pool import RoomTab,_navigate_owned_target
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);(home/".chatgpt_web2api").mkdir()
            instance="hitel-room-synthetic-9222"; target="ABCDEF1234567890"
            (home/".chatgpt_web2api"/"owned_tabs.json").write_text(
                json.dumps({instance:{"target_id":target}}))
            tab={"id":target,"type":"page","url":"https://chatgpt.com/c/"+"a"*32,
                 "webSocketDebuggerUrl":"ws://127.0.0.1:9222/devtools/page/"+target}
            process=FakeProcess()
            slot=RoomTab(ROOM_A,9222,18321,instance,process,0)
            with patch("hitel_room_tab_pool.Path.home",return_value=home),\
                 patch("hitel_room_tab_pool.urllib.request.urlopen",
                       return_value=io.BytesIO(json.dumps([tab]).encode())) as urlopen,\
                 patch("websockets.sync.client.connect",
                       side_effect=AssertionError("MUST_NOT_NAVIGATE")):
                self.assertEqual(
                    _navigate_owned_target(slot,"https://chatgpt.com/c/"+"a"*32),target)
                urlopen.assert_called_once()

    def test_owned_target_wrong_conversation_navigates_exact_target_only(self):
        import io,json,tempfile
        from unittest.mock import MagicMock
        from hitel_room_tab_pool import RoomTab,_navigate_owned_target
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);(home/".chatgpt_web2api").mkdir()
            instance="hitel-room-test-9222"; target="FEDCBA9876543210"
            (home/".chatgpt_web2api"/"owned_tabs.json").write_text(
                json.dumps({instance:{"target_id":target}}))
            new_url="https://chatgpt.com/c/"+"a"*32
            old={"id":target,"type":"page","url":"https://chatgpt.com/c/"+"b"*32,
                 "webSocketDebuggerUrl":"ws://127.0.0.1:9222/devtools/page/"+target}
            new={**old,"url":new_url}
            responses=iter([io.BytesIO(json.dumps([old]).encode()),
                            io.BytesIO(json.dumps([new]).encode())])
            socket=MagicMock()
            socket.__enter__.return_value=socket
            socket.recv.return_value=json.dumps({"id":41,"result":{"frameId":"frame"}})
            slot=RoomTab(ROOM_A,9222,18322,instance,FakeProcess(),0)
            with patch("hitel_room_tab_pool.Path.home",return_value=home),\
                 patch("hitel_room_tab_pool.urllib.request.urlopen",side_effect=lambda *a,**k:next(responses)),\
                 patch("websockets.sync.client.connect",return_value=socket) as conn:
                self.assertEqual(_navigate_owned_target(slot,new_url),target)
            conn.assert_called_once()
            transmitted=json.loads(socket.send.call_args[0][0])
            self.assertEqual(transmitted["method"],"Page.navigate")
            self.assertEqual(transmitted["params"]["url"],new_url)

    async def test_health_must_confirm_real_usable_composer(self):
        healthy={"chrome_running":True,"driver_connected":True,"status":"healthy"}
        pool=RoomTabPool()
        with patch("hitel_room_tab_pool._health",return_value=healthy):
            self.assertFalse(await pool._ready(18080))
        with patch("hitel_room_tab_pool._health",return_value={**healthy,"composer_ready":False}):
            self.assertFalse(await pool._ready(18080))
        with patch("hitel_room_tab_pool._health",return_value={**healthy,"composer_ready":True}):
            self.assertTrue(await pool._ready(18080))

    async def test_real_startup_lifecycle_navigates_before_requiring_composer(self):
        import hitel_room_tab_pool as module
        launched=[]
        async def spawn(*a,**k):
            p=FakeProcess();launched.append(p);return p
        phase={"navigated":False}
        def navigate(slot,url):
            self.assertTrue(phase["started"])
            phase["navigated"]=True
            return "owned-target-after-cdp-navigation"
        async def startup(port):
            phase["started"]=True
            return True
        async def composer(port):
            self.assertTrue(phase["navigated"],
                            "composer must be checked AFTER room navigation")
            return True
        pool=RoomTabPool(max_rooms=4)
        with patch("hitel_room_tab_pool._available_port",return_value=18401),\
             patch("hitel_room_tab_pool.asyncio.create_subprocess_exec",side_effect=spawn),\
             patch("hitel_room_tab_pool._navigate_owned_target",side_effect=navigate),\
             patch.object(RoomTabPool,"_boot_ready",side_effect=startup),\
             patch.object(RoomTabPool,"_ready",side_effect=composer):
            tid=await pool.prewarm(ROOM_A,9222,"https://chatgpt.com/c/"+"a"*32)
            self.assertEqual(tid,"owned-target-after-cdp-navigation")
            self.assertTrue(phase["navigated"])
            self.assertEqual(pool._protected_rooms,{ROOM_A})
            await pool.close()
        print("PASS_PHASED_BOOTSTRAP_NAVIGATES_BEFORE_COMPOSER_HEALTH",flush=True)

    async def test_four_slots_preserve_two_research_and_two_qa_rooms(self):
        launched=[]
        async def spawn(*a,**k):
            p=FakeProcess();launched.append(p);return p
        pool=RoomTabPool(max_rooms=4)
        with patch("hitel_room_tab_pool._available_port",
                   side_effect=[18501,18502,18503,18504,18505]),\
             patch("hitel_room_tab_pool.asyncio.create_subprocess_exec",side_effect=spawn),\
             patch("hitel_room_tab_pool._navigate_owned_target",
                   return_value="owned-verified-target"),\
             patch.object(RoomTabPool,"_boot_ready",new_callable=AsyncMock,return_value=True),\
             patch.object(RoomTabPool,"_ready",new_callable=AsyncMock,return_value=True):
            await pool.prewarm(ROOM_A,9222,"https://chatgpt.com/c/"+"a"*32)
            await pool.prewarm(ROOM_B,9222,"https://chatgpt.com/c/"+"b"*32)
            c,d=await asyncio.gather(
                pool.endpoint(ROOM_C,9222),pool.endpoint(ROOM_D,9222))
            self.assertNotEqual(c,d)
            self.assertEqual(len(pool._rooms),4)
            self.assertEqual(pool._protected_rooms,{ROOM_A,ROOM_B})
            self.assertEqual(sum(int(x.stopped) for x in launched),0)
            await pool.close()
        print("PASS_FOUR_INDEPENDENT_TABS_TWO_PROTECTED_RESEARCH_PLUS_TWO_QA",flush=True)

    async def test_account_change_and_stale_driver_fail_closed(self):
        launched=[]
        async def spawn(*a,**k):
            p=FakeProcess();launched.append(p);return p
        pool=RoomTabPool(max_rooms=2)
        with patch("hitel_room_tab_pool._available_port",return_value=18331),\
             patch("hitel_room_tab_pool.asyncio.create_subprocess_exec",side_effect=spawn),\
             patch.object(RoomTabPool,"_boot_ready",new_callable=AsyncMock,return_value=True),\
             patch.object(RoomTabPool,"_ready",new_callable=AsyncMock,return_value=True):
            await pool.endpoint(ROOM_A,9222)
            with self.assertRaisesRegex(TabIsolationError,"ACCOUNT_CHANGED"):
                await pool.endpoint(ROOM_A,9223)
            launched[0].returncode=1
            with self.assertRaisesRegex(TabIsolationError,"NO_RETRY"):
                await pool.endpoint(ROOM_A,9222)
            self.assertEqual(len(launched),1)
            await pool.close()

if __name__=="__main__":
    unittest.main()
