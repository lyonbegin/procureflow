"""Synthetic room-tab isolation contract; no logged-in Chrome or AI writes."""
import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SCRIPT_DIR=Path(__file__).resolve().parents[3]/".github"/"scripts"
sys.path.insert(0,str(SCRIPT_DIR))
from hitel_room_tab_pool import RoomTabPool, TabIsolationError

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

    async def test_account_change_and_stale_driver_fail_closed(self):
        launched=[]
        async def spawn(*a,**k):
            p=FakeProcess();launched.append(p);return p
        pool=RoomTabPool(max_rooms=2)
        with patch("hitel_room_tab_pool._available_port",return_value=18331),\
             patch("hitel_room_tab_pool.asyncio.create_subprocess_exec",side_effect=spawn),\
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
