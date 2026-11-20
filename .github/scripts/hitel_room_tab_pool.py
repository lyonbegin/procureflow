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


def _same_conversation_route(observed: str, expected: str) -> bool:
    """Exact authenticated ChatGPT conversation path, ignoring query only."""
    actual = urlsplit(observed)
    wanted = urlsplit(expected)
    return (
        actual.scheme == wanted.scheme == "https"
        and actual.hostname == wanted.hostname == "chatgpt.com"
        and actual.username is None and actual.password is None
        and actual.port in (None, 443)
        and actual.path.rstrip("/") == wanted.path.rstrip("/")
    )


def _navigate_owned_target(slot: RoomTab, conversation_url: str) -> str:
    """Verify/recover ONLY the CDP target actually owned by this vendor instance.

    Direct CDP avoids Playwright sync_api's event-loop AssertionError observed
    in real QA at the third message. An already-correct URL is NEVER reloaded.
    Nothing here sends a ChatGPT message, clicks or changes the active account.
    """
    from websockets.sync.client import connect as connect_cdp

    if not CONVERSATION_URL.fullmatch(conversation_url):
        raise TabIsolationError("UNVERIFIED_SAVED_CONVERSATION_URL")
    registry=Path.home()/".chatgpt_web2api"/"owned_tabs.json"
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
    if not target_id or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}",target_id):
        raise TabIsolationError("ROOM_OWNED_TARGET_NOT_RECORDED")

    def owned_tab():
        req=urllib.request.Request(
            f"http://127.0.0.1:{slot.cdp_port}/json/list",
            headers={"Accept":"application/json"},
        )
        with urllib.request.urlopen(req,timeout=5) as response:
            tabs=json.load(response)
        if not isinstance(tabs,list):
            raise TabIsolationError("CHROME_TARGET_LIST_INVALID")
        matches=[t for t in tabs if isinstance(t,dict)
                 and t.get("id")==target_id and t.get("type")=="page"]
        if len(matches)!=1:
            raise TabIsolationError("ROOM_OWNED_TARGET_NOT_FOUND_IN_CHROME")
        return matches[0]

    tab=owned_tab()
    if _same_conversation_route(str(tab.get("url","")),conversation_url):
        return target_id

    # A displaced tab may be recovered, but ONLY the exact persisted CDP
    # target. Never adopt an arbitrary tab or restart the vendor process.
    address=urlsplit(str(tab.get("url","")))
    if address.scheme not in ("https","about") or (
        address.scheme=="https" and address.hostname!="chatgpt.com"
    ):
        raise TabIsolationError("ROOM_OWNED_TARGET_FOREIGN_HOST_NO_NAVIGATION")
    ws_uri=tab.get("webSocketDebuggerUrl")
    parsed=urlsplit(ws_uri) if isinstance(ws_uri,str) else None
    if (parsed is None or parsed.scheme!="ws"
            or parsed.hostname not in ("127.0.0.1","localhost")
            or parsed.port!=slot.cdp_port
            or not parsed.path.endswith("/"+target_id)
            or not parsed.path.startswith("/devtools/page/")):
        raise TabIsolationError("ROOM_OWNED_TARGET_CDP_URL_UNVERIFIED")
    try:
        with connect_cdp(ws_uri,open_timeout=12,close_timeout=4,max_size=100000) as socket:
            socket.send(json.dumps({
                "id":41,"method":"Page.navigate","params":{"url":conversation_url}
            }))
            response_deadline=time.monotonic()+15
            while time.monotonic()<response_deadline:
                packet=json.loads(socket.recv(timeout=max(0.5,response_deadline-time.monotonic())))
                if packet.get("id")!=41:
                    continue
                if (packet.get("error") or
                        packet.get("result",{}).get("errorText")):
                    raise TabIsolationError("ROOM_OWNED_TARGET_NAVIGATION_REJECTED")
                break
            else:
                raise TabIsolationError("ROOM_OWNED_TARGET_NAVIGATION_TIMEOUT")
    except (OSError,TimeoutError,ValueError,KeyError) as exc:
        raise TabIsolationError("ROOM_OWNED_TARGET_CDP_NAVIGATION_FAILED") from exc

    for _ in range(40):
        current=str(owned_tab().get("url",""))
        if _same_conversation_route(current,conversation_url):
            return target_id
        observed=urlsplit(current)
        if observed.hostname!="chatgpt.com":
            raise TabIsolationError("ROOM_PREWARM_LOGIN_OR_FOREIGN_HOST")
        if observed.path.rstrip("/") in ("","/","/auth/login","/login"):
            # Allow client-side navigation to settle, without submitting text.
            time.sleep(0.5)
            continue
        if observed.path.startswith(("/c/","/c2/","/uc/")):
            raise TabIsolationError("ROOM_PREWARM_DIFFERENT_CONVERSATION")
        time.sleep(0.5)
    raise TabIsolationError("ROOM_PREWARM_HOME_OR_LOGIN_REDIRECT")


class RoomTabPool:
    """Bounded room-affine local vendor processes, never a shared DOM tab."""

    def __init__(self, max_rooms: int = 3) -> None:
        if not 1 <= max_rooms <= MAX_ROOMS:
            raise ValueError("ROOM_TAB_CAPACITY_INVALID")
        self.max_rooms = max_rooms
        self._rooms: dict[str, RoomTab] = {}
        self._busy_rooms: set[str] = set()
        self._uncertain_rooms: set[str] = set()
        # Linked, prewarmed research rooms cannot be displaced by new QA/temporary rooms.
        self._protected_rooms: set[str] = set()
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
             if key not in self._busy_rooms and key not in self._uncertain_rooms
             and key not in self._protected_rooms),
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
            # The vendor-owned tab may have been blank while the adapter
            # process started. Require a real editable composer only AFTER
            # navigating this exact owned target to the saved conversation.
            await self._wait_composer(slot.api_port)
            self._protected_rooms.add(room_id)
            return target_id
        except TabIsolationError:
            # Failure to navigate does not authorize a replacement tab or a new SEND.
            self.quarantine(room_id)
            raise
        finally:
            self.unpin(room_id)

    async def navigate_existing(self, room_id: str, cdp_port: int,
                                conversation_url: str) -> str:
        """Verify the exact existing conversation BEFORE a follow-up send.

        The room has already been pinned by execute_one. No other room's
        tabs are touched, and no new ChatGPT message is emitted here.
        """
        if room_id not in self._busy_rooms:
            raise TabIsolationError("ROOM_TAB_NOT_LOCKED")
        if (not isinstance(conversation_url, str)
                or not CONVERSATION_URL.fullmatch(conversation_url)):
            raise TabIsolationError("UNVERIFIED_SAVED_CONVERSATION_URL")
        await self.endpoint(room_id,cdp_port)
        slot=self._rooms.get(room_id)
        if slot is None:
            raise TabIsolationError("ROOM_TAB_NOT_ALLOCATED")
        target_id=await asyncio.to_thread(_navigate_owned_target,slot,conversation_url)
        await self._wait_composer(slot.api_port)
        return target_id

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
                if not await self._boot_ready(existing.api_port):
                    raise TabIsolationError("ROOM_TAB_DRIVER_DISCONNECTED_NO_RETRY")
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
                # Startup verifies only the CDP driver. An owned tab cannot
                # be expected to display a ChatGPT composer BEFORE navigation
                # to its saved room; the old check caused a 0/2 prewarm loop.
                if await self._boot_ready(port):
                    return slot.chat_endpoint
                await asyncio.sleep(1)
            raise TabIsolationError("ROOM_TAB_DRIVER_NOT_READY_NO_FALLBACK")

    @staticmethod
    async def _boot_ready(port: int) -> bool:
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

    @staticmethod
    async def _ready(port: int) -> bool:
        """Ready for a SEND, not merely a connected driver."""
        try:
            data = await asyncio.to_thread(_health, port)
        except (OSError, ValueError, KeyError):
            return False
        return (
            isinstance(data, dict)
            and data.get("chrome_running") is True
            and data.get("driver_connected") is True
            and data.get("composer_ready") is True
            and data.get("status") in ("healthy", "starting")
        )

    async def _wait_composer(self, port: int) -> None:
        """Fail-closed after navigation if the owned ChatGPT editor is absent.

        Never retry a send or navigate another tab. No prompt text is logged.
        """
        deadline=time.monotonic()+50
        while time.monotonic()<deadline:
            if await self._ready(port):
                return
            await asyncio.sleep(1)
        raise TabIsolationError("ROOM_OWNED_COMPOSER_NOT_READY_AFTER_NAVIGATION")

    async def close(self) -> None:
        async with self._lock:
            procs = list(self._rooms.values())
            self._rooms.clear()
            self._protected_rooms.clear()
        for item in procs:
            if item.process.returncode is None:
                item.process.terminate()
        for item in procs:
            try:
                await asyncio.wait_for(item.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                item.process.kill()
                await item.process.wait()
