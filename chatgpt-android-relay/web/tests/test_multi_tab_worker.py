"""Synthetic room-tab isolation contract; no logged-in Chrome or AI writes."""
import asyncio
import ast
import tempfile
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

class VendorEditorCompatibilityTest(unittest.TestCase):
    def test_pinned_vendor_live_role_textbox_selector_patch(self):
        # Extract the helper alone to avoid installed browser dependencies.
        worker=SCRIPT_DIR/"w2a_relay_worker.py"
        tree=ast.parse(worker.read_text(encoding="utf-8"))
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef)
                and n.name=="ensure_live_vendor_composer_selector")
        scope={"Path":Path}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),str(worker),"exec"),scope)
        patcher=scope[fn.name]
        old="""COMPOSER_SELECTOR = 'div[role="textbox"]#prompt-textarea, div[role="textbox"].ProseMirror'"""
        with tempfile.TemporaryDirectory() as work:
            path=Path(work)/"chatgpt_dom.py"
            path.write_text(old+"\n",encoding="utf-8")
            patcher(path)
            changed=path.read_text(encoding="utf-8")
            self.assertIn('[role="textbox"][contenteditable]',changed)
            self.assertNotEqual(changed,old+"\n")
            patcher(path)  # idempotent
            self.assertEqual(path.read_text(encoding="utf-8"),changed)
            path.write_text("COMPOSER_SELECTOR = 'unreviewed'\n",encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError,"REFUSE_UNKNOWN"):
                patcher(path)
        print("PASS_VENDOR_LIVE_EDITOR_FALLBACK_PATCH_IDEMPOTENT_FAIL_CLOSED",flush=True)


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

    def test_owned_tab_about_blank_during_navigation_is_not_login_failure(self):
        import io,json,tempfile
        from unittest.mock import MagicMock
        from hitel_room_tab_pool import RoomTab,_navigate_owned_target
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);(home/".chatgpt_web2api").mkdir()
            instance="hitel-room-transition-9222"
            target="TRANSIENTTARGET12345"
            (home/".chatgpt_web2api"/"owned_tabs.json").write_text(
                json.dumps({instance:{"target_id":target}}))
            dest="https://chatgpt.com/c/"+"a"*32
            initial={"id":target,"type":"page","url":"https://chatgpt.com/",
                     "webSocketDebuggerUrl":"ws://127.0.0.1:9222/devtools/page/"+target}
            transitioning={**initial,"url":"about:blank"}
            internal_newtab={**initial,"url":"chrome://newtab/"}
            empty_url={**initial,"url":""}
            arrived={**initial,"url":dest}
            sequence=iter([initial,transitioning,internal_newtab,empty_url,arrived])
            sock=MagicMock()
            sock.__enter__.return_value=sock
            sock.recv.return_value=json.dumps({"id":41,"result":{"frameId":"frame"}})
            def get(*a,**k):
                return io.BytesIO(json.dumps([next(sequence)]).encode())
            slot=RoomTab(ROOM_A,9222,18581,instance,FakeProcess(),0)
            with patch("hitel_room_tab_pool.Path.home",return_value=home),\
                 patch("hitel_room_tab_pool.urllib.request.urlopen",side_effect=get),\
                 patch("hitel_room_tab_pool.time.sleep"),\
                 patch("websockets.sync.client.connect",return_value=sock):
                self.assertEqual(_navigate_owned_target(slot,dest),target)
            print("PASS_CDPTARGET_ABOUT_BLANK_INTERNAL_NEWTAB_EMPTY_URL_TRANSITIONS",flush=True)

    def test_cdp_runtime_url_resolves_stale_empty_target_metadata(self):
        import io,json,tempfile
        from unittest.mock import MagicMock
        from hitel_room_tab_pool import RoomTab,_navigate_owned_target
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);(home/".chatgpt_web2api").mkdir()
            instance="hitel-room-cdp-read-9222";target="READONLYTARGET123456"
            (home/".chatgpt_web2api"/"owned_tabs.json").write_text(
                json.dumps({instance:{"target_id":target}}))
            dest="https://chatgpt.com/c/"+"a"*32
            initial={"id":target,"type":"page","url":"https://chatgpt.com/",
                     "webSocketDebuggerUrl":"ws://127.0.0.1:9222/devtools/page/"+target}
            blank={**initial,"url":""}
            observations=iter([initial,blank,blank,blank])
            cdpsock=MagicMock();cdpsock.__enter__.return_value=cdpsock
            cdpsock.recv.return_value=json.dumps({"id":41,"result":{}})
            slot=RoomTab(ROOM_A,9222,18585,instance,FakeProcess(),0)
            with patch("hitel_room_tab_pool.Path.home",return_value=home),\
                 patch("hitel_room_tab_pool.urllib.request.urlopen",
                       side_effect=lambda *a,**k:io.BytesIO(json.dumps([next(observations)]).encode())),\
                 patch("hitel_room_tab_pool.time.sleep"),\
                 patch("hitel_room_tab_pool._live_owned_target_url",return_value=dest) as actual,\
                 patch("websockets.sync.client.connect",return_value=cdpsock):
                self.assertEqual(_navigate_owned_target(slot,dest),target)
            actual.assert_called_once()
            print("PASS_READONLY_CDP_DOCUMENT_LOCATION_OVERRIDES_STALE_EMPTY_TARGET_METADATA",flush=True)

    def test_live_cdp_location_probe_only_reads_location_no_mutations(self):
        import json
        from unittest.mock import MagicMock
        from hitel_room_tab_pool import _live_owned_target_url
        target_url="https://chatgpt.com/c/"+"c"*32
        sock=MagicMock();sock.__enter__.return_value=sock
        sock.recv.return_value=json.dumps({
            "id":7042,"result":{"result":{"type":"string","value":target_url}}})
        with patch("websockets.sync.client.connect",return_value=sock):
            self.assertEqual(_live_owned_target_url(
                "ws://127.0.0.1:9222/devtools/page/READONLYTARGET123456"),target_url)
        packet=json.loads(sock.send.call_args.args[0])
        self.assertEqual(packet["method"],"Runtime.evaluate")
        self.assertEqual(packet["params"]["expression"],"location.href")
        print("PASS_CDP_LOCATION_PROBE_IS_READONLY_EXACT_TARGET_ONLY",flush=True)

    def test_owned_tab_chrome_error_page_detected_without_url_leak(self):
        import io,json,tempfile
        from unittest.mock import MagicMock
        from hitel_room_tab_pool import RoomTab,_navigate_owned_target
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);(home/".chatgpt_web2api").mkdir()
            instance="hitel-room-error-9222";target="CHROMEERRORTARGET1234"
            (home/".chatgpt_web2api"/"owned_tabs.json").write_text(
                json.dumps({instance:{"target_id":target}}))
            dest="https://chatgpt.com/c/"+"b"*32
            initial={"id":target,"type":"page","url":"https://chatgpt.com/",
                     "webSocketDebuggerUrl":"ws://127.0.0.1:9222/devtools/page/"+target}
            chrome_error={**initial,"url":"chrome-error://chromewebdata/"}
            sequence=iter([initial,chrome_error])
            sock=MagicMock();sock.__enter__.return_value=sock
            sock.recv.return_value=json.dumps({"id":41,"result":{}})
            slot=RoomTab(ROOM_A,9222,18583,instance,FakeProcess(),0)
            with patch("hitel_room_tab_pool.Path.home",return_value=home),\
                 patch("hitel_room_tab_pool.urllib.request.urlopen",
                       side_effect=lambda *a,**k:io.BytesIO(json.dumps([next(sequence)]).encode())),\
                 patch("websockets.sync.client.connect",return_value=sock):
                with self.assertRaisesRegex(TabIsolationError,
                                            "ROOM_PREWARM_CHROME_NETWORK_ERROR_PAGE"):
                    _navigate_owned_target(slot,dest)
            print("PASS_CHROME_NETWORK_ERROR_IS_NOT_SILENTLY_TREATED_AS_AUTH_OR_LOGIN",flush=True)

    def test_owned_tab_real_auth_redirect_fails_closed_without_retry(self):
        import io,json,tempfile
        from unittest.mock import MagicMock
        from hitel_room_tab_pool import RoomTab,_navigate_owned_target
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);(home/".chatgpt_web2api").mkdir()
            instance="hitel-room-login-9222";target="AUTHREDIRECTTARGET123"
            (home/".chatgpt_web2api"/"owned_tabs.json").write_text(
                json.dumps({instance:{"target_id":target}}))
            dest="https://chatgpt.com/c/"+"b"*32
            first={"id":target,"type":"page","url":"https://chatgpt.com/",
                   "webSocketDebuggerUrl":"ws://127.0.0.1:9222/devtools/page/"+target}
            second={**first,"url":"https://auth.openai.com/login"}
            sequence=iter([first,second])
            sock=MagicMock()
            sock.__enter__.return_value=sock
            sock.recv.return_value=json.dumps({"id":41,"result":{}})
            slot=RoomTab(ROOM_A,9222,18582,instance,FakeProcess(),0)
            with patch("hitel_room_tab_pool.Path.home",return_value=home),\
                 patch("hitel_room_tab_pool.urllib.request.urlopen",
                       side_effect=lambda *a,**k:io.BytesIO(json.dumps([next(sequence)]).encode())),\
                 patch("websockets.sync.client.connect",return_value=sock):
                with self.assertRaisesRegex(TabIsolationError,"ROOM_PREWARM_LOGIN_REDIRECT"):
                    _navigate_owned_target(slot,dest)
            print("PASS_AUTH_REDIRECT_NOT_MISTAKEN_FOR_TRANSIENT_CDPTARGET",flush=True)

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

    def test_owned_cdp_editor_diagnostic_exposes_counts_not_content(self):
        import io,json
        from unittest.mock import MagicMock
        from hitel_room_tab_pool import RoomTab,_owned_editor_diagnostic
        target="DOMPROBE123456789"
        wsuri="ws://127.0.0.1:9222/devtools/page/"+target
        tabs=[{"id":target,"type":"page","webSocketDebuggerUrl":wsuri}]
        payload={"b":True,"e":1,"t":0,"r":1,"p":1,
                 "h":True,"c":True,"s":"complete"}
        sock=MagicMock();sock.__enter__.return_value=sock
        sock.recv.return_value=json.dumps({
            "id":7113,"result":{"result":{"type":"string","value":json.dumps(payload)}}})
        slot=RoomTab(ROOM_A,9222,18588,"hitel-room-test",FakeProcess(),0)
        with patch("hitel_room_tab_pool.urllib.request.urlopen",
                   return_value=io.BytesIO(json.dumps(tabs).encode())),\
             patch("websockets.sync.client.connect",return_value=sock):
            result=_owned_editor_diagnostic(slot,target)
        self.assertEqual(result,"DOM_B1_E1_T0_R1_P1_H1_C1_SC")
        packet=json.loads(sock.send.call_args.args[0])
        self.assertEqual(packet["method"],"Runtime.evaluate")
        expression=packet["params"]["expression"].lower()
        for forbidden in ("innertext","textcontent","cookie","accesstoken","fetch("):
            self.assertNotIn(forbidden,expression)
        print("PASS_OWNED_CDP_EDITOR_DIAG_SAFE_BOOLEAN_COUNTS_NO_CONTENT",flush=True)

    async def test_exact_owned_cdp_visible_textbox_overrides_stale_vendor_health(self):
        from hitel_room_tab_pool import RoomTab
        pool=RoomTabPool(max_rooms=2)
        owned=RoomTab(ROOM_A,9222,19001,"known-owned",FakeProcess(),0)
        healthy={"chrome_running":True,"driver_connected":True,
                 "composer_ready":False,"status":"healthy"}
        with patch.object(RoomTabPool,"_ready",new_callable=AsyncMock,return_value=False), \
             patch("hitel_room_tab_pool._health",return_value=healthy), \
             patch("hitel_room_tab_pool._owned_editor_diagnostic",
                   return_value="DOM_B1_E1_T0_R1_P0_H1_C1_SC"):
            await pool._wait_composer(19001,timeout_s=0,
                                      slot=owned,target_id="a"*32)
        with patch.object(RoomTabPool,"_ready",new_callable=AsyncMock,return_value=False), \
             patch("hitel_room_tab_pool._health",return_value=healthy), \
             patch("hitel_room_tab_pool._owned_editor_diagnostic",
                   return_value="DOM_B1_E1_T0_R1_P0_H0_C0_SC"):
            with self.assertRaisesRegex(TabIsolationError,"GUARD_FAILED"):
                await pool._wait_composer(19001,timeout_s=0,
                                          slot=owned,target_id="a"*32)
        print("PASS_EXACT_OWNED_VISIBLE_EDITOR_OVERRIDES_STALE_HEALTH_ONLY",flush=True)

    async def test_composer_failure_reports_only_safe_health_flags(self):
        pool=RoomTabPool()
        data={"status":"degraded","chrome_running":True,
              "driver_connected":True,"composer_ready":False,
              "last_error":"PRIVATE_DO_NOT_LOG_OR_REPEAT",
              "chatgpt_url":"https://chatgpt.com/c/PRIVATE"}
        with patch("hitel_room_tab_pool._health",return_value=data):
            with self.assertRaisesRegex(TabIsolationError,
                                        "ROOM_OWNED_COMPOSER_GUARD_FAILED_C1_D1_E0_SD") as cm:
                await pool._wait_composer(19001,timeout_s=0)
        self.assertNotIn("PRIVATE",str(cm.exception))
        print("PASS_COMPOSER_HEALTH_FAILURE_SAFE_FLAGS_NO_SECRET_OR_URL",flush=True)

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
