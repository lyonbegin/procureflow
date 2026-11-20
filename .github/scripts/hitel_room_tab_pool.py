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


def _live_owned_target_url(ws_uri: str) -> str | None:
    """Read only location.href on the SAME already-verified CDP page target.

    Chrome /json/list can report empty/stale URL metadata while Page.navigate
    commits. A read-only Runtime.evaluate checks the actual document instead.
    No sensitive URL is logged, returned to the public API, or transmitted
    outside the local worker. This never types, clicks, or submits a message.
    """
    from websockets.sync.client import connect as connect_cdp
    try:
        with connect_cdp(ws_uri,open_timeout=6,close_timeout=3,max_size=100000) as socket:
            socket.send(json.dumps({
                "id":7042,"method":"Runtime.evaluate",
                "params":{"expression":"location.href","returnByValue":True}
            }))
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                packet=json.loads(socket.recv(timeout=max(0.25,deadline-time.monotonic())))
                if packet.get("id")!=7042:
                    continue
                if packet.get("error") or packet.get("result",{}).get("exceptionDetails"):
                    return None
                result=packet.get("result",{}).get("result",{})
                value=result.get("value") if isinstance(result,dict) else None
                return value if isinstance(value,str) and len(value)<2048 else None
    except (OSError,TimeoutError,ValueError,KeyError):
        return None
    return None


def _owned_editor_diagnostic(slot: RoomTab, target_id: str) -> str:
    """Observe ONLY bounded, non-content DOM flags on the exact owned CDP tab."""
    from websockets.sync.client import connect as connect_cdp
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}",target_id):
        return "TARGET_INVALID"
    try:
        req=urllib.request.Request(f"http://127.0.0.1:{slot.cdp_port}/json/list",
                                   headers={"Accept":"application/json"})
        with urllib.request.urlopen(req,timeout=5) as response:
            tabs=json.load(response)
        matches=[t for t in tabs if isinstance(t,dict)
                 and t.get("id")==target_id and t.get("type")=="page"]
        if len(matches)!=1:return "TARGET_NOT_OWNED"
        uri=matches[0].get("webSocketDebuggerUrl")
        parsed=urlsplit(uri) if isinstance(uri,str) else None
        if (parsed is None or parsed.scheme!="ws"
            or parsed.hostname not in ("127.0.0.1","localhost")
            or parsed.port!=slot.cdp_port
            or parsed.path!="/devtools/page/"+target_id):
            return "TARGET_CDP_INVALID"
        # Only counts and booleans. Never read content, cookies, tokens or URLs.
        expression=(
            "(function(){"
            "var e=Array.from(document.querySelectorAll('textarea,[contenteditable],[role=textbox]'));"
            "var v=e.filter(x=>x.isConnected&&x.getClientRects().length>0"
            "&&!x.closest('[aria-hidden=true],[inert]'));"
            "var path=location.pathname;"
            "return JSON.stringify({"
            "b:!!document.body,e:v.filter(x=>x.isContentEditable).length,"
            "t:v.filter(x=>x.tagName==='TEXTAREA').length,"
            "r:v.filter(x=>x.getAttribute('role')==='textbox').length,"
            "p:document.querySelectorAll('#prompt-textarea').length,"
            "h:location.hostname==='chatgpt.com',"
            "c:path.startsWith('/c/')||path.startsWith('/c2/')||path.startsWith('/uc/'),"
            "s:document.readyState});"
            "})()"
        )
        with connect_cdp(uri,open_timeout=7,close_timeout=4,max_size=100000) as socket:
            socket.send(json.dumps({"id":7113,"method":"Runtime.evaluate",
                 "params":{"expression":expression,"returnByValue":True}}))
            deadline=time.monotonic()+6
            while time.monotonic()<deadline:
                packet=json.loads(socket.recv(timeout=max(.25,deadline-time.monotonic())))
                if packet.get("id")!=7113:continue
                obj=packet.get("result",{}).get("result",{})
                raw=obj.get("value") if isinstance(obj,dict) else None
                if not isinstance(raw,str):return "DOM_NO_RESULT"
                flags=json.loads(raw)
                if not isinstance(flags,dict):return "DOM_INVALID"
                def n(k):
                    try:return min(9,max(0,int(flags.get(k,0))))
                    except (TypeError,ValueError):return 0
                ready={"complete":"C","interactive":"I","loading":"L"}.get(flags.get("s"),"U")
                return ("DOM_B"+str(int(flags.get("b") is True))
                        +"_E"+str(n("e"))+"_T"+str(n("t"))+"_R"+str(n("r"))
                        +"_P"+str(n("p"))+"_H"+str(int(flags.get("h") is True))
                        +"_C"+str(int(flags.get("c") is True))+"_S"+ready)
    except (OSError,TimeoutError,ValueError,KeyError):
        return "DOM_PROBE_UNAVAILABLE"
    return "DOM_PROBE_TIMEOUT"


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

    # Page.navigate acknowledges the command BEFORE Chrome's /json/list
    # reflects the destination. During that brief gap a new owned target may
    # still report about:blank (no host) or its previous ChatGPT route.
    # These are transitional states, not evidence of login or a foreign site.
    # Never treat an actual auth redirect as transitional or navigate a foreign
    # target. The expected target ID remains immutable throughout.
    for attempt in range(40):
        current=str(owned_tab().get("url",""))
        if _same_conversation_route(current,conversation_url):
            return target_id
        # On a hostless/transient Chrome target, metadata can be stale.
        # Prefer a read-only document location from this SAME verified CDP
        # socket (never another tab) before classifying a navigation failure.
        if attempt>=2 and attempt%4==2:
            metadata=urlsplit(current)
            if (not current.strip() or metadata.hostname is None or
                    metadata.scheme in ("about","chrome","chrome-search")):
                live=_live_owned_target_url(ws_uri)
                if live and _same_conversation_route(live,conversation_url):
                    return target_id
                if live:
                    current=live
        # CDP /json/list can briefly omit a URL while Page.navigate commits.
        # Only the exactly-empty URL is treated as a bounded transition.
        if not current.strip():
            if attempt>=8:
                raise TabIsolationError("ROOM_PREWARM_EMPTY_URL_STUCK_AFTER_NAVIGATION")
            time.sleep(0.5)
            continue
        observed=urlsplit(current)
        if observed.scheme=="about" and observed.path=="blank":
            time.sleep(0.5)
            continue
        # During a real Chrome target navigation, a new-tab shell can
        # briefly surface in /json/list. Allow only these exact internal
        # transient pages, and only for the first four seconds. Every other
        # foreign page fails closed with a redacted, finite error code.
        if (observed.scheme=="chrome" and observed.hostname=="newtab"
                or observed.scheme=="chrome-search" and observed.hostname=="local-ntp"):
            if attempt>=8:
                raise TabIsolationError("ROOM_PREWARM_INTERNAL_NEWTAB_STUCK")
            time.sleep(0.5)
            continue
        if observed.scheme=="chrome-error":
            raise TabIsolationError("ROOM_PREWARM_CHROME_NETWORK_ERROR_PAGE")
        if observed.scheme=="data":
            raise TabIsolationError("ROOM_PREWARM_UNEXPECTED_DATA_PAGE")
        if observed.scheme=="chrome-extension":
            raise TabIsolationError("ROOM_PREWARM_EXTENSION_PAGE")
        if observed.hostname=="auth.openai.com":
            raise TabIsolationError("ROOM_PREWARM_LOGIN_REDIRECT")
        if observed.hostname!="chatgpt.com":
            if observed.scheme=="https":
                raise TabIsolationError("ROOM_PREWARM_UNEXPECTED_HTTPS_HOST")
            if observed.scheme=="http":
                raise TabIsolationError("ROOM_PREWARM_INSECURE_HTTP_HOST")
            if observed.scheme=="about":
                raise TabIsolationError("ROOM_PREWARM_UNKNOWN_ABOUT_PAGE")
            if observed.scheme=="":
                raise TabIsolationError("ROOM_PREWARM_MALFORMED_URL_AFTER_NAVIGATION")
            if observed.scheme in ("blob","javascript","file"):
                raise TabIsolationError("ROOM_PREWARM_UNEXPECTED_LOCAL_SCHEME")
            if observed.hostname is None:
                raise TabIsolationError("ROOM_PREWARM_UNKNOWN_NO_HOST_SCHEME")
            raise TabIsolationError("ROOM_PREWARM_UNEXPECTED_BROWSER_SCHEME")
        if observed.path.rstrip("/") in ("/auth/login","/login"):
            raise TabIsolationError("ROOM_PREWARM_CHATGPT_LOGIN_REDIRECT")
        if observed.path.rstrip("/") in ("","/"):
            time.sleep(0.5)
            continue
        if observed.path.startswith(("/c/","/c2/","/uc/")):
            if attempt>=8:
                raise TabIsolationError("ROOM_PREWARM_DIFFERENT_CONVERSATION")
            time.sleep(0.5)
            continue
        time.sleep(0.5)
    raise TabIsolationError("ROOM_PREWARM_EXPECTED_CONVERSATION_NOT_REACHED")


def _close_verified_owned_target(slot: RoomTab, conversation_url: str) -> bool:
    """Close ONLY the exact verified vendor-owned Chrome tab after DB commit.

    Never inspect or close arbitrary browser tabs; a missing registry, mismatched
    conversation, or failed CDP probe leaves the original tab intact.
    """
    if not isinstance(conversation_url, str) or not CONVERSATION_URL.fullmatch(
            conversation_url):
        return False
    try:
        registry = Path.home() / ".chatgpt_web2api" / "owned_tabs.json"
        data = json.loads(registry.read_text(encoding="utf-8"))
        info = data.get(slot.instance_id, {})
        target_id = info.get("target_id") if isinstance(info, dict) else None
        if not isinstance(target_id, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{8,128}", target_id):
            return False
        with urllib.request.urlopen(
                f"http://127.0.0.1:{slot.cdp_port}/json/list", timeout=5) as rsp:
            tabs = json.load(rsp)
        matching = [tab for tab in tabs if isinstance(tab, dict)
                    and tab.get("id") == target_id and tab.get("type") == "page"]
        if len(matching) != 1:
            return False
        tab = matching[0]
        uri = tab.get("webSocketDebuggerUrl")
        address = urlsplit(uri) if isinstance(uri, str) else None
        if (address is None or address.scheme != "ws"
                or address.hostname not in ("127.0.0.1", "localhost")
                or address.port != slot.cdp_port
                or address.path != "/devtools/page/" + target_id):
            return False
        live_url = _live_owned_target_url(uri)
        if not live_url or not _same_conversation_route(
                live_url, conversation_url):
            return False
        close_url = f"http://127.0.0.1:{slot.cdp_port}/json/close/{target_id}"
        with urllib.request.urlopen(close_url, timeout=5) as rsp:
            return rsp.status == 200
    except (OSError, TimeoutError, ValueError, TypeError, KeyError):
        return False


class RoomTabPool:
    """Bounded room-affine local vendor processes, never a shared DOM tab."""

    def __init__(self) -> None:
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
            await self._wait_composer(slot.api_port,slot=slot,target_id=target_id)
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
        await self._wait_composer(slot.api_port,slot=slot,target_id=target_id)
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

    async def _wait_composer(self, port: int, timeout_s: float = 50.0,
                             *,slot: RoomTab | None = None,
                             target_id: str | None = None) -> None:
        """Fail-closed after navigation if the owned ChatGPT editor is absent.

        Never retry a send or navigate another tab. No prompt text is logged.
        """
        deadline=time.monotonic()+timeout_s
        while time.monotonic()<deadline:
            if await self._ready(port):
                return
            await asyncio.sleep(1)
        # The previous generic COMPOSER_NOT_READY hid whether Chrome, its
        # CDP driver, the DOM selector, or a degraded vendor breaker failed.
        # Emit ONLY finite boolean/enum fields (never URLs, cookies or text).
        try:
            probe=await asyncio.to_thread(_health,port)
        except (OSError,ValueError,KeyError):
            probe={}
        if not isinstance(probe,dict):
            probe={}
        status=probe.get("status")
        state={"healthy":"H","starting":"S","degraded":"D","broken":"B"}.get(status,"U")
        flags="C"+str(int(probe.get("chrome_running") is True))
        flags+="_D"+str(int(probe.get("driver_connected") is True))
        flags+="_E"+str(int(probe.get("composer_ready") is True))
        flags+="_S"+state
        if slot is not None and target_id is not None:
            direct=await asyncio.to_thread(_owned_editor_diagnostic,slot,target_id)
            flags+="_"+direct
            # Vendor /health has returned composer_ready=False for an actual
            # tab with a verified visible contenteditable textbox in both
            # authenticated research conversations. Only accept the *exact*
            # CDP target this vendor process owns, already navigated to its
            # saved /c/<id>, with an observed editable/role=textbox, ready DOM,
            # and a healthy connected vendor CDP. Never probe or adopt a
            # different tab; never pretend any assistant reply succeeded.
            if (probe.get("chrome_running") is True
                    and probe.get("driver_connected") is True
                    and status in ("healthy","starting")
                    and re.fullmatch(
                        r"DOM_B1_E[1-9]_T[0-9]_R[1-9]_P[0-9]_H1_C1_S[CI]",
                        direct
                    )):
                print("PASS_OWNED_TAB_VISIBLE_EDITOR_CONFIRMED_BY_DIRECT_CDP",flush=True)
                return
        raise TabIsolationError("ROOM_OWNED_COMPOSER_GUARD_FAILED_"+flags)

    async def release_verified(self, room_id: str, conversation_url: str) -> bool:
        """Retire only an idle, server-committed, non-protected room's own CDP tab.

        The Railway server must acknowledge durable result storage BEFORE this
        method is called. Without the acknowledgment, keep the tab untouched.
        """
        async with self._lock:
            slot = self._rooms.get(room_id)
            if (slot is None or room_id in self._busy_rooms
                    or room_id in self._uncertain_rooms
                    or room_id in self._protected_rooms):
                return False
            if not await asyncio.to_thread(
                    _close_verified_owned_target, slot, conversation_url):
                return False
            if slot.process.returncode is None:
                slot.process.terminate()
                try:
                    await asyncio.wait_for(slot.process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    slot.process.kill()
                    await slot.process.wait()
            self._rooms.pop(room_id, None)
            return True

    async def close(self) -> None:
        async with self._lock:
            procs = list(self._rooms.values())
            self._rooms.clear()
            self._protected_rooms.clear()
            self._busy_rooms.clear()
            self._uncertain_rooms.clear()
        for item in procs:
            if item.process.returncode is None:
                item.process.terminate()
        for item in procs:
            try:
                await asyncio.wait_for(item.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                item.process.kill()
                await item.process.wait()
