"""HITEL internal room-affine Web2API adapter pool.

ONE ChatGPT room -> ONE pinned vendor CDPDriver -> ONE Chrome-owned tab.
The vendor's REST API is singleton-driver; multiple HTTP requests to the same
vendor process do NOT create independent tabs.  Separate local vendor processes
per room, all attaching to the *same* authenticated Chrome CDP port, are the
minimal reliable isolation boundary.  W2A_PARALLEL_TABS ensures per-target
mutation locks instead of the legacy CDP-port-wide lock.

No Railway services, logins, Chrome profiles, or new browser processes created.
No shared-tab adoption, automatic retries, or cross-room fallback.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sys
import time
import urllib.request
from urllib.parse import urlsplit
from typing import Any

ROOM_PATTERN = re.compile(r"^room_[a-f0-9]{32}$")
CHROME_PORTS = frozenset((9222, 9223))
MAX_ROOMS = 4
STARTUP_SECONDS = 65


class TabIsolationError(RuntimeError):
    pass


@dataclass
class RoomTab:
    room_id: str
    cdp_port: int
    api_port: int
    instance_id: str
    process: Any
    assigned_at: float

    @property
    def chat_endpoint(self) -> str:
        return f"http://127.0.0.1:{self.api_port}/v1/chat/completions"


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _health(port: int) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/health",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=3) as response:
        return json.load(response)


CONVERSATION_URL = re.compile(
    r"^https://chatgpt\.com/(?:c|c2|uc)/[A-Za-z0-9_-]{8,128}$"
)


def _navigate_owned_target(slot: RoomTab, conversation_url: str) -> str:
    """Read own vendor instance registry; navigate ONLY its owned Chrome target.

    No send/typing/clicking. A valid URL is supplied by the authenticated HITEL
    server from that exact room's persisted ChatGPT conversation mapping.
    """
    from playwright.sync_api import sync_playwright

    registry = Path.home()/".chatgpt_web2api"/"owned_tabs.json"
    deadline=time.monotonic()+35
    target_id=None
    while time.monotonic()<deadline:
        try:
            data=json.loads(registry.read_text(encoding="utf-8"))
            info=data.get(slot.instance_id,{})
            if isinstance(info,dict) and isinstance(info.get("target_id"),str):
                target_id=info["target_id"]
                break
        except (FileNotFoundError,PermissionError,OSError,ValueError):
            pass
        time.sleep(0.5)
    if not target_id:
        raise TabIsolationError("ROOM_OWNED_TARGET_NOT_RECORDED")

    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp(
            f"http://127.0.0.1:{slot.cdp_port}",timeout=12000)
        for context in browser.contexts:
            for page in context.pages:
                if page.is_closed():
                    continue
                session=None
                try:
                    session=context.new_cdp_session(page)
                    target=session.send("Target.getTargetInfo")["targetInfo"]["targetId"]
                except (KeyError,ValueError,RuntimeError):
                    continue
                finally:
                    if session is not None:
                        try:
                            session.detach()
                        except Exception:
                            pass
                if target != target_id:
                    continue
                # Deliberate read-only navigation to a previously bound
                # conversation. NEVER send a new prompt or create a new chat.
                page.goto(conversation_url,wait_until="domcontentloaded",timeout=40000)
                expected=urlsplit(conversation_url)
                # ChatGPT may add a model/query parameter to an unchanged
                # conversation route. Verify hostname + exact conversation
                # path instead of rejecting harmless query-string changes.
                for _ in range(20):
                    observed=urlsplit(page.url)
                    if (observed.scheme=="https"
                        and observed.hostname=="chatgpt.com"
                        and observed.path.rstrip("/")==expected.path.rstrip("/")):
                        return target_id
                    page.wait_for_timeout(500)
                if observed.hostname!="chatgpt.com":
                    raise TabIsolationError("ROOM_PREWARM_LOGIN_OR_FOREIGN_HOST")
                if observed.path.rstrip("/") in ("","/","/auth/login","/login"):
                    raise TabIsolationError("ROOM_PREWARM_HOME_OR_LOGIN_REDIRECT")
                if observed.path.startswith(("/c/","/c2/","/uc/")):
                    raise TabIsolationError("ROOM_PREWARM_DIFFERENT_CONVERSATION")
                raise TabIsolationError("ROOM_PREWARM_UNEXPECTED_CHATGPT_ROUTE")
    raise TabIsolationError("ROOM_OWNED_TARGET_NOT_FOUND_IN_CHROME")


class RoomTabPool:
    """Bounded room-affine local vendor processes, never a shared DOM tab."""

    def __init__(self, max_rooms: int = 3) -> None:
        if not 1 <= max_rooms <= MAX_ROOMS:
            raise ValueError("ROOM_TAB_CAPACITY_INVALID")
        self.max_rooms = max_rooms
        self._rooms: dict[str, RoomTab] = {}
        self._busy_rooms: set[str] = set()
        self._uncertain_rooms: set[str] = set()
        self._lock = asyncio.Lock()

    def pin(self, room_id: str) -> None:
        if room_id in self._busy_rooms:
            raise TabIsolationError("ROOM_ALREADY_RUNNING")
        self._busy_rooms.add(room_id)

    def unpin(self, room_id: str) -> None:
        self._busy_rooms.discard(room_id)

    def quarantine(self, room_id: str) -> None:
        # A ChatGPT send may have succeeded despite the lost HTTP response.
        # Never replace its tab automatically; preserve for read-only review.
        self._uncertain_rooms.add(room_id)

    async def _evict_one_idle(self) -> bool:
        """Only an idle, confirmed-safe tab may be reclaimed for another room."""
        candidates = sorted(
            (item for key,item in self._rooms.items()
             if key not in self._busy_rooms and key not in self._uncertain_rooms),
            key=lambda item:item.assigned_at,
        )
        if not candidates:
            return False
        victim=candidates[0]
        if victim.process.returncode is None:
            victim.process.terminate()
            try:
                await asyncio.wait_for(victim.process.wait(),timeout=5)
            except asyncio.TimeoutError:
                victim.process.kill()
                await victim.process.wait()
        self._rooms.pop(victim.room_id,None)
        return True

    async def prewarm(self, room_id: str, cdp_port: int,
                      conversation_url: str) -> str:
        """Ensure a separate tab exists and points at the saved ChatGPT room."""
        if not isinstance(conversation_url,str) or not CONVERSATION_URL.fullmatch(
            conversation_url
        ):
            raise TabIsolationError("UNVERIFIED_SAVED_CONVERSATION_URL")
        self.pin(room_id)
        try:
            await self.endpoint(room_id,cdp_port)
            slot=self._rooms.get(room_id)
            if slot is None:
                raise TabIsolationError("ROOM_TAB_NOT_ALLOCATED")
            target_id=await asyncio.to_thread(
                _navigate_owned_target,slot,conversation_url)
            return target_id
        except TabIsolationError:
            # Failure to navigate does not authorize a replacement tab or a new SEND.
            self.quarantine(room_id)
            raise
        finally:
            self.unpin(room_id)

    def inspect(self) -> dict[str, tuple[int, int]]:
        # Internal diagnostics only. No room IDs or account identity in logs.
        return {key: (value.cdp_port, value.api_port)
                for key, value in self._rooms.items()}

    async def endpoint(self, room_id: str, cdp_port: int) -> str:
        if not ROOM_PATTERN.fullmatch(room_id):
            raise TabIsolationError("INVALID_ROOM_ID")
        if cdp_port not in CHROME_PORTS:
            raise TabIsolationError("UNVERIFIED_CHROME_CDP_PORT")

        async with self._lock:
            existing = self._rooms.get(room_id)
            if existing:
                if existing.cdp_port != cdp_port:
                    raise TabIsolationError("ROOM_CHROME_ACCOUNT_CHANGED")
                if existing.process.returncode is not None:
                    # The tab may still be generating an answer in Chrome.
                    # NEVER silently create a new tab and resend a question.
                    raise TabIsolationError("ROOM_TAB_PROCESS_EXITED_NO_RETRY")
                if not await self._ready(existing.api_port):
                    raise TabIsolationError("ROOM_TAB_DISCONNECTED_NO_RETRY")
                return existing.chat_endpoint

            if len(self._rooms) >= self.max_rooms:
                if not await self._evict_one_idle():
                    raise TabIsolationError("ROOM_TAB_CAPACITY_EXCEEDED")

            port = _available_port()
            instance_id = (
                "hitel-room-"
                + hashlib.sha256(room_id.encode("ascii")).hexdigest()[:24]
                + "-" + str(cdp_port)
            )
            env = os.environ.copy()
            env.update({
                "W2A_INSTANCE_ID": instance_id,
                "W2A_TAB_MODE": "owned",
                "W2A_PARALLEL_TABS": "true",
                "W2A_MCP_SESSION_POOL_ENABLED": "false",
            })
            # Adapter must only connect to an *already authenticated* Chrome.
            # Vendor process creates/owns one tab by CDP Target.createTarget.
            # Vendor CLI is installed in the existing GitHub Actions venv.
            command = ("chatgpt-web2api", "--port", str(port),
                       "--host", "127.0.0.1", "--cdp-port", str(cdp_port))
            try:
                process = await asyncio.create_subprocess_exec(
                    *command, env=env,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except (OSError, ValueError) as exc:
                raise TabIsolationError("ROOM_TAB_START_FAILED") from exc
            slot = RoomTab(room_id, cdp_port, port, instance_id,
                           process, time.monotonic())
            # Persist in this worker even when readiness fails; unknown delivery
            # is not an invitation to replace this room with another tab.
            self._rooms[room_id] = slot

            deadline = time.monotonic() + STARTUP_SECONDS
            while time.monotonic() < deadline:
                if process.returncode is not None:
                    raise TabIsolationError("ROOM_TAB_STARTUP_EXITED")
                if await self._ready(port):
                    return slot.chat_endpoint
                await asyncio.sleep(1)
            raise TabIsolationError("ROOM_TAB_NOT_READY_NO_FALLBACK")

    @staticmethod
    async def _ready(port: int) -> bool:
        try:
            data = await asyncio.to_thread(_health, port)
        except (OSError, ValueError, KeyError):
            return False
        return (
            isinstance(data, dict)
            and data.get("chrome_running") is True
            and data.get("driver_connected") is True
            and data.get("status") in ("healthy", "starting")
        )

    async def close(self) -> None:
        async with self._lock:
            procs = list(self._rooms.values())
            self._rooms.clear()
        for item in procs:
            if item.process.returncode is None:
                item.process.terminate()
        for item in procs:
            try:
                await asyncio.wait_for(item.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                item.process.kill()
                await item.process.wait()
