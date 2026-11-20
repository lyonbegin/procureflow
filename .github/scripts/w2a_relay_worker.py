#!/usr/bin/env python3
"""GitHub Actions Chrome -> original ChatGPT-Web2API -> Railway relay.

No extra passwords, no local PC, no session or message contents in logs.
The original Web2API handles browser work; this only adapts the EXISTING
room-scoped websocket job/result protocol.

Designed to fail closed:
- only signed GitHub OIDC authentication;
- never auto-retry a chat send whose completion is uncertain;
- verify returned conversation ID matches the assigned room;
- refuse attachments until original-byte upload is verified;
- never claim unsupported actions were completed.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from typing import Any

import websockets
# The worker is also loaded with importlib.spec_from_file_location in existing
# API contract tests. Resolve the adjacent reviewed helper in both entry modes.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
from safe_worker_error import classify_web2api_failure
from hitel_room_tab_pool import RoomTabPool, TabIsolationError

from w2a_account_runtime import (AccountGateError, actual_chrome_account,
                                 canonical_email, verify_same_session,
                                 find_verified_cdp_port)

AUDIENCE = "urn:lyonbegin:procureflow:chatgpt-relay:device"
RELAY_HOST = "hitel-integration-api-production.up.railway.app"
CHAT_API = "http://127.0.0.1:18080/v1/chat/completions"
CHAT_API_B = "http://127.0.0.1:18081/v1/chat/completions"
CONVERSATION_ID = re.compile(r"^[a-zA-Z0-9_-]{8,128}$")
MAX_TEXT = 24000
MAX_WORKER_TABS = 3
# Bounded socket read, never an unbounded call that freezes worker dispatch.
UPSTREAM_SOCKET_TIMEOUT = max(60,min(14000,int(os.environ.get("W2A_REPLY_SOCKET_TIMEOUT","13800"))))
MAX_REPLY_BYTES = 2000000


def get_oidc_token() -> str:
    """Retrieve a short-lived identity token without printing or persisting it."""
    url = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL", "")
    bearer = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "")
    if not url.startswith("https://") or not bearer:
        raise RuntimeError("GITHUB_OIDC_UNAVAILABLE")
    separator = "&" if "?" in url else "?"
    request_url = url + separator + urllib.parse.urlencode({"audience": AUDIENCE})
    request = urllib.request.Request(
        request_url, headers={"Authorization": "Bearer " + bearer, "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        token = json.load(response).get("value", "")
    if not isinstance(token, str) or len(token) < 50:
        raise RuntimeError("GITHUB_OIDC_EMPTY")
    return token


def extract_conversation_id(job: dict[str, Any]) -> str | None:
    target = job.get("target_conversation_id")
    if not target:
        if job.get("target_chatgpt_url"):
            raise ValueError("UNVERIFIED_TARGET_CONVERSATION")
        return None
    if not isinstance(target, str) or not CONVERSATION_ID.fullmatch(target):
        raise ValueError("UNVERIFIED_TARGET_CONVERSATION")
    url = job.get("target_chatgpt_url")
    if url and (not isinstance(url, str) or not url.startswith("https://chatgpt.com/")):
        raise ValueError("UNVERIFIED_TARGET_URL")
    return target


def discard_verified_duplicate_json_tail(answer: str) -> str:
    """Remove only proven duplicate DOM fragments after a complete JSON answer.

    Do not truncate arbitrary answers or legitimate independent notes. A
    repeated JSON fragment must contain structural closing brackets and its
    first 60 compact characters must already occur in the parsed JSON.
    """
    clean=answer.strip()
    if not clean.startswith(("{","[")):
        return answer
    try:
        _,end=json.JSONDecoder().raw_decode(clean)
    except (ValueError,TypeError):
        return answer
    tail=clean[end:].strip()
    # 2026-11-20 live browser proof: a complete JSON response was followed
    # by an exact duplicate suffix and an HTML closing tag from the DIL DOM.
    # The old suffix-only rule missed this shape (and published invalid JSON).
    # Remove ONLY a verified, >=6-character identical suffix plus a closing
    # tag, never arbitrary prose, an independent JSON object, or HTML content.
    markup_tail=re.fullmatch(r"(.{6,})</[A-Za-z][A-Za-z0-9-]{0,31}>",
                             tail,flags=re.DOTALL)
    if markup_tail:
        duplicate=markup_tail.group(1)
        if ("<" not in duplicate and ">" not in duplicate
                and len(duplicate)<end and clean[:end].endswith(duplicate)):
            return clean[:end]
    if not tail or tail.startswith(("{","[")):
        return answer
    # Real browser DOM sometimes appends an exact short suffix fragment:
    # {"hitel_v4_smoke":"OK"}e":"OK"}
    # This is a proven duplicate only if EVERY trailing character is the
    # exact suffix of the fully decoded JSON, with a structural terminator.
    # Never trim natural language, distinct JSON, or merely similar fragments.
    if (len(tail)>=6 and tail.endswith(("}","]"))
        and clean[:end].endswith(tail)):
        return clean[:end]
    compact_tail=re.sub(r"\s+","",tail)
    compact_head=re.sub(r"\s+","",clean[:end])
    if (len(compact_tail)>=60 and
            any(ch in tail for ch in ("}","]")) and
            compact_tail[:60] in compact_head):
        return clean[:end]
    return answer


def parse_web2api_response(response: dict[str, Any], target: str | None) -> tuple[str, str]:
    if not isinstance(response, dict):
        raise ValueError("WEB2API_RESPONSE_INVALID")
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("WEB2API_CHOICES_MISSING")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    answer = message.get("content") if isinstance(message, dict) else None
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("WEB2API_ASSISTANT_REPLY_MISSING")
    if len(answer.encode("utf-8")) > MAX_REPLY_BYTES:
        raise ValueError("WEB2API_ASSISTANT_REPLY_TOO_LARGE")
    cid = response.get("conversation_id")
    if not isinstance(cid, str) or not CONVERSATION_ID.fullmatch(cid):
        raise ValueError("WEB2API_CONVERSATION_ID_MISSING")
    if target and cid != target:
        raise ValueError("ROOM_CONVERSATION_ID_MISMATCH")
    return discard_verified_duplicate_json_tail(answer), cid


def _safe_vendor_http_error(exc: urllib.error.HTTPError) -> str:
    """Parse a bounded local Web2API error for safe diagnostics only.

    Neither server-supplied message text nor URLs/conversation IDs appear in
    this return value. HTTP500 after SEND remains delivery-uncertain.
    """
    status=int(exc.code)
    try:
        payload=json.loads(exc.read(8192))
        detail=payload.get("error",{}) if isinstance(payload,dict) else {}
        code=detail.get("code","") if isinstance(detail,dict) else ""
        message=detail.get("message","") if isinstance(detail,dict) else ""
    except (ValueError,TypeError,UnicodeDecodeError):
        code=""
        message=""
    message=message if isinstance(message,str) else ""
    if "nav_displaced" in message:
        suffix="NAV_DISPLACED"
    elif "composer" in message.lower():
        suffix="COMPOSER_UNAVAILABLE"
    elif "stage:" in message and "url" in message.lower():
        suffix="NAV_URL_MISMATCH"
    elif "Navigation to " in message:
        suffix="NAV_UNVERIFIED"
    elif "auth" in message.lower():
        suffix="AUTH_UNAVAILABLE"
    elif isinstance(code,str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,35}",code):
        suffix="VENDOR_"+code.upper()
    else:
        suffix="UNCLASSIFIED"
    return f"WEB2API_ADAPTER_HTTP_{status}_{suffix}"


def post_chat_uri(text: str, cid: str | None, api_url: str,
                  *, internal_owned_room: bool = False) -> tuple[str, str]:
    trusted_legacy = api_url in (CHAT_API,CHAT_API_B)
    trusted_room = bool(
        internal_owned_room
        and re.fullmatch(r"http://127\.0\.0\.1:[1-9][0-9]{1,4}/v1/chat/completions",api_url)
    )
    if not trusted_legacy and not trusted_room:
        raise ValueError("REFUSE_UNTRUSTED_CHAT_API")
    body: dict[str, Any] = {
        "model": "auto",
        "stream": False,
        "messages": [{"role": "user", "content": text}],
    }
    if cid:
        body["conversation_id"] = cid
    else:
        # The pinned Web2API vendor *defaults to reusing the previous chat*
        # when conversation_id is omitted. The source-pinned DOM patch
        # provides an explicit opt-in to force a brand-new conversation.
        # Every new public/private HITEL room MUST use it; otherwise two
        # separate rooms can receive the same conversation URL and the
        # server correctly refuses to bind the second one.
        body["new_conversation"] = True
    raw = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        api_url, data=raw, method="POST",
        headers={"Content-Type": "application/json"},
    )
    # Wait for Web2API to report a verified reply or a definite upstream failure.
    # The persistent GitHub Actions worker supplies the outer lifecycle bound.
    try:
        with urllib.request.urlopen(request, timeout=UPSTREAM_SOCKET_TIMEOUT) as response:
            if response.status != 200:
                raise RuntimeError("WEB2API_HTTP_NOT_200")
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_safe_vendor_http_error(exc)) from None
    return parse_web2api_response(data, cid)


def post_chat(text: str, cid: str | None) -> tuple[str,str]:
    return post_chat_uri(text,cid,CHAT_API)


async def process_job(job: dict[str, Any], account_preflight=None,
                      adapter_pool: RoomTabPool | None = None) -> dict[str, Any]:
    """Return a server-protocol result, without leaking text into diagnostic logs."""
    jid = job.get("id")
    room_id = job.get("room_id")
    if not (isinstance(jid, str) and jid.startswith("job_")
            and isinstance(room_id, str) and room_id.startswith("room_")):
        raise ValueError("MALFORMED_RELAY_JOB")
    action = job.get("action")
    if action != "chat.send":
        raise ValueError("UNSUPPORTED_WEB_WORKER_ACTION")
    # Registered, server-verified identity and its email are supplied by the
    # authenticated Railway server over the signed GitHub worker WebSocket.
    # Never use an account_id string or a stale Chrome profile alone as proof.
    selected_id = job.get("account_id")
    expected_email = None
    if selected_id is not None:
        if not isinstance(selected_id,str) or not selected_id.startswith("oai_"):
            raise ValueError("ACCOUNT_ID_INVALID")
        expected_email = canonical_email(job.get("account_email"))
    if job.get("attachment_ids") or job.get("attachment_details") or job.get("drive_links"):
        # Never silently replace a native binary attachment with a URL or text.
        raise ValueError("WEB2API_BINARY_ATTACHMENT_NOT_VERIFIED")
    content = job.get("text")
    if not isinstance(content, str) or not content.strip() or len(content) > MAX_TEXT:
        raise ValueError("INVALID_CHAT_TEXT")
    target = extract_conversation_id(job)
    route_port = 9222
    if expected_email is not None:
        if os.environ.get("W2A_DUAL_PROFILES") == "1":
            # Never sign out A in an attempt to send B. Choose only a Chrome
            # profile that ALREADY has the correct live ChatGPT identity.
            route_port = await asyncio.to_thread(find_verified_cdp_port, expected_email)
            if not await asyncio.to_thread(
                    verify_same_session, expected_email, cdp_port=route_port):
                raise AccountGateError("ACCOUNT_EXECUTION_NOT_VERIFIED")
        else:
            # Multi-room workers must NEVER log out or switch the Chrome
            # profile: doing so invalidates every other active room tab.
            # Actual account identity is observed read-only in the existing
            # signed-in browser, before the account-bound send.
            if adapter_pool is not None:
                if not await asyncio.to_thread(
                    verify_same_session, expected_email, cdp_port=9222
                ):
                    raise AccountGateError("ACCOUNT_EXECUTION_NOT_VERIFIED")
            else:
                # Retain the legacy standalone test path, never used by the
                # protocol-v4 concurrent worker.
                await asyncio.to_thread(actual_chrome_account, expected_email)
                if not await asyncio.to_thread(verify_same_session, expected_email):
                    raise AccountGateError("ACCOUNT_EXECUTION_NOT_VERIFIED")
        # A previously dispatched job can have been revoked or deleted while
        # the user completed Chrome sign-in. Re-check with Railway immediately
        # before allowing Web2API to submit ANY message text.
        if account_preflight is None:
            raise AccountGateError("ACCOUNT_PREFLIGHT_UNAVAILABLE")
        await account_preflight(job,expected_email)
    if adapter_pool is not None:
        # A stable room-ID owns exactly one browser tab, via its own vendor
        # process and CDP target ID. Do not fall back to a shared tab on error.
        if target:
            # A new GitHub worker has no memory of the previous room tab.
            # Verify the saved target is visibly loaded before Web2API sends.
            await adapter_pool.navigate_existing(
                room_id,route_port,job.get("target_chatgpt_url") or "")
        api_url = await adapter_pool.endpoint(room_id, route_port)
        answer, cid = await asyncio.to_thread(
            post_chat_uri, content, target, api_url, internal_owned_room=True)
    elif route_port == 9223:
        answer, cid = await asyncio.to_thread(
            post_chat_uri, content, target, CHAT_API_B)
    else:
        answer, cid = await asyncio.to_thread(post_chat, content, target)
    if expected_email is not None:
        if route_port == 9223:
            still_same=await asyncio.to_thread(
                verify_same_session,expected_email,cdp_port=route_port)
        else:
            still_same=await asyncio.to_thread(verify_same_session,expected_email)
        if not still_same:
            raise AccountGateError("ACCOUNT_CHANGED_DURING_SEND")
    result = {
        "type": "job.result",
        "job_id": jid, "room_id": room_id,
        "verified": True, "stage": "assistant_reply_stable",
        "result_text": answer,
        "chatgpt_url": "https://chatgpt.com/c/" + cid,
        "room_state": "active",
    }
    if expected_email is not None:
        result["execution_account_id"] = selected_id
        result["execution_account_email"] = expected_email
        result["session_verified"] = True
    return result


def ws_destination() -> str:
    url = os.environ.get("RELAY_WS_URL", "wss://" + RELAY_HOST + "/ws")
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "wss" or parsed.hostname != RELAY_HOST or
            parsed.port not in (None, 443) or parsed.path != "/ws" or
            parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise RuntimeError("REFUSE_UNTRUSTED_RELAY_URL")
    return url


async def _periodic_app_heartbeat(socket,deadline:float):
    """Keep the Railway heartbeat alive while Chrome processes a long turn."""
    while time.monotonic()<deadline:
        await asyncio.sleep(15)
        try:
            await socket.send('{"type":"worker.heartbeat"}')
        except Exception:
            return


async def run(max_seconds: int = 1500) -> None:
    """One signed WebSocket, independent per-room browser tabs and reply tasks.

    ONLY this main loop reads socket.recv(). Worker preflight approvals are
    routed to the job-specific Future; no concurrent readers or shared-tab
    navigation are permitted.
    """
    address = ws_destination()
    deadline = time.monotonic() + max_seconds
    attempts = 0
    authenticated_once = False
    seen_jobs: set[str] = set()
    pool = RoomTabPool(MAX_WORKER_TABS)
    try:
        while time.monotonic() < deadline:
            attempts += 1
            active: dict[str, asyncio.Task] = {}
            preflight_waiters: dict[str, asyncio.Future] = {}
            try:
                token = await asyncio.to_thread(get_oidc_token)
                async with websockets.connect(
                    address, ping_interval=20, ping_timeout=20,
                    close_timeout=5, max_size=4 * 1024 * 1024,
                ) as socket:
                    await socket.send(json.dumps({
                        "role":"web2api","deviceId":"web2api-main",
                        "oidc_token":token,
                        "hitel_protocol_version":4,
                        "max_concurrent_jobs":MAX_WORKER_TABS,
                    }))
                    first = json.loads(await asyncio.wait_for(socket.recv(),timeout=20))
                    if first.get("type")!="auth.ok":
                        raise RuntimeError("RELAY_OIDC_AUTH_REJECTED")
                    authenticated_once = True
                    attempts = 0
                    print("PASS_GITHUB_OIDC_RELAY_WEBSOCKET_CONNECTED",flush=True)
                    hb=asyncio.create_task(_periodic_app_heartbeat(socket,deadline))
                    try:
                        async def account_preflight(job,expected_email):
                            jid=job["id"]
                            future=asyncio.get_running_loop().create_future()
                            preflight_waiters[jid]=future
                            try:
                                await socket.send(json.dumps({
                                    "type":"job.preflight",
                                    "job_id":jid,"room_id":job["room_id"],
                                    "account_id":job["account_id"],
                                    "execution_account_email":expected_email,
                                }))
                                approved=await asyncio.wait_for(future,timeout=45)
                                if approved is not True:
                                    raise AccountGateError("ACCOUNT_PREFLIGHT_DENIED")
                            finally:
                                preflight_waiters.pop(jid,None)

                        async def execute_one(job):
                            jid,rid=job["id"],job["room_id"]
                            pool.pin(rid)
                            try:
                                await socket.send(json.dumps({
                                    "type":"job.received","job_id":jid,
                                    "room_id":rid,"stage":"web2api_received",
                                }))
                                result=await process_job(
                                    job,account_preflight=account_preflight,
                                    adapter_pool=pool)
                            except asyncio.CancelledError:
                                raise
                            except Exception as exc:
                                code=classify_web2api_failure(exc)
                                if isinstance(exc,TabIsolationError):
                                    # Tab ownership could not be established.
                                    code=str(exc)[:100]
                                # Any HTTP timeout/5xx after submission may be a
                                # completed ChatGPT turn whose reply was lost.
                                # Do not label it model failure or retry SEND.
                                uncertain=(
                                    code in {"WEB2API_ADAPTER_TIMEOUT",
                                             "WEB2API_ADAPTER_TRANSPORT",
                                             "WEB2API_ADAPTER_HTTP_500",
                                             "WEB2API_ADAPTER_HTTP_502",
                                             "WEB2API_ADAPTER_HTTP_503",
                                             "WEB2API_ADAPTER_HTTP_504"}
                                    or code.startswith("ROOM_TAB_DISCONNECTED")
                                    or code.startswith("WEB2API_ADAPTER_HTTP_500")
                                )
                                if uncertain:
                                    pool.quarantine(rid)
                                await socket.send(json.dumps({
                                    "type":"job.uncertain" if uncertain else "job.error",
                                    "job_id":jid,"room_id":rid,
                                    "stage":"upstream_delivery_unknown" if uncertain else "web2api_failed",
                                    "reason":code,
                                }))
                                print("RELAY_ROOM_JOB_"+(
                                    "UNCERTAIN_" if uncertain else "ERROR_")+code,flush=True)
                            else:
                                await socket.send(json.dumps(result,ensure_ascii=False))
                                print("PASS_RELAY_WEB2API_JOB_RESULT_VERIFIED",flush=True)
                            finally:
                                pool.unpin(rid)
                                active.pop(jid,None)

                        while time.monotonic() < deadline:
                            raw=await asyncio.wait_for(
                                socket.recv(),timeout=max(1,deadline-time.monotonic()))
                            item=json.loads(raw)
                            typ=item.get("type")
                            if typ=="room.bootstrap":
                                # The signed Railway server provides actual saved
                                # conversation URLs, never user-supplied placeholders.
                                # Open both existing chats in separate vendor OWNED tabs,
                                # WITHOUT typing, clicking Send, or adding a new turn.
                                rooms=item.get("rooms",[])
                                ready=[]
                                if isinstance(rooms,list) and len(rooms)<=MAX_WORKER_TABS:
                                    for info in rooms:
                                        if not isinstance(info,dict):
                                            continue
                                        rid,url=info.get("room_id"),info.get("chatgpt_url")
                                        if not isinstance(rid,str) or not isinstance(url,str):
                                            continue
                                        try:
                                            target=await pool.prewarm(rid,9222,url)
                                        except Exception as exc:
                                            code=(str(exc) if isinstance(exc,TabIsolationError)
                                                  else type(exc).__name__)
                                            print("FAIL_ROOM_TAB_PREWARM_"+code[:70],flush=True)
                                            continue
                                        ready.append({"room_id":rid,"target_id":target})
                                await socket.send(json.dumps({
                                    "type":"room.bootstrap.done",
                                    "ready_rooms":ready,
                                }))
                                print("PASS_AUTHENTICATED_ROOM_TAB_PREWARM="
                                      +str(len(ready))+"/"+str(len(rooms))
                                      if isinstance(rooms,list) else
                                      "FAIL_INVALID_ROOM_TAB_BOOTSTRAP",flush=True)
                                continue
                            if typ=="ping":
                                await socket.send(json.dumps({"type":"pong"}))
                                continue
                            if typ in ("job.preflight.ok","job.preflight.denied"):
                                jid=item.get("job_id")
                                pending=preflight_waiters.get(jid)
                                if pending is not None and not pending.done():
                                    pending.set_result(typ=="job.preflight.ok")
                                continue
                            if typ!="job":
                                continue
                            job=item.get("job")
                            if not isinstance(job,dict):
                                continue
                            jid,rid=job.get("id"),job.get("room_id")
                            if not isinstance(jid,str) or not isinstance(rid,str):
                                continue
                            if jid in seen_jobs:
                                print("REFUSE_DUPLICATE_RELAY_JOB",flush=True)
                                continue
                            # This is a capacity guard, not a hidden backlog.
                            if len(active)>=MAX_WORKER_TABS:
                                await socket.send(json.dumps({
                                    "type":"job.error","job_id":jid,
                                    "room_id":rid,"stage":"capacity_mismatch",
                                    "reason":"WORKER_TAB_CAPACITY_EXCEEDED",
                                }))
                                continue
                            if any(
                                task.get_name()==rid for task in active.values()
                            ):
                                await socket.send(json.dumps({
                                    "type":"job.error","job_id":jid,
                                    "room_id":rid,"stage":"room_already_busy",
                                    "reason":"ROOM_ALREADY_RUNNING_NO_DUPLICATE_SEND",
                                }))
                                continue
                            seen_jobs.add(jid)
                            task=asyncio.create_task(
                                execute_one(job),name=rid)
                            active[jid]=task
                    finally:
                        hb.cancel()
                        try:
                            await hb
                        except asyncio.CancelledError:
                            pass
            except asyncio.TimeoutError:
                print("RELAY_WEBSOCKET_LIFETIME_EXPIRED",flush=True)
            except Exception as exc:
                print("RELAY_CONNECTION_INTERRUPTED_"+type(exc).__name__,flush=True)
            finally:
                if active:
                    # On socket loss the API marks all these jobs UNCERTAIN;
                    # do not reconnect and potentially accept overlapping sends.
                    for task in active.values():
                        task.cancel()
                    await asyncio.gather(*active.values(),return_exceptions=True)
                    break
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(min(30,max(2,2**min(attempts,4))))
    finally:
        await pool.close()
    print("RELAY_ACTIONS_WORKER_RUN_ENDED",flush=True)
    if not authenticated_once:
        raise RuntimeError("RELAY_OIDC_AUTH_NEVER_SUCCEEDED")


if __name__ == "__main__":
    duration = int(os.environ.get("W2A_WORKER_SECONDS", "600"))
    try:
        asyncio.run(run(max_seconds=max(60, min(14400, duration))))
    except Exception as exc:
        print("FAIL_RELAY_WORKER_"+type(exc).__name__,flush=True)
        sys.exit(1)
