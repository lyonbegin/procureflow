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
import time
import urllib.parse
import urllib.request
from typing import Any

import websockets

from w2a_account_runtime import (AccountGateError, actual_chrome_account,
                                 canonical_email, verify_same_session)
from w2a_google_signin import (new_runner_key, decrypt_login_envelope,
                               perform_google_login, recheck_google_session,
                               RemoteGoogleLoginError)

AUDIENCE = "urn:lyonbegin:procureflow:chatgpt-relay:device"
RELAY_HOST = "chatgpt-relay-web-production.up.railway.app"
CHAT_API = "http://127.0.0.1:18080/v1/chat/completions"
CONVERSATION_ID = re.compile(r"^[a-zA-Z0-9_-]{8,128}$")
MAX_TEXT = 24000


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


def parse_web2api_response(response: dict[str, Any], target: str | None) -> tuple[str, str]:
    if not isinstance(response, dict):
        raise ValueError("WEB2API_RESPONSE_INVALID")
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("WEB2API_CHOICES_MISSING")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    answer = message.get("content") if isinstance(message, dict) else None
    if not isinstance(answer, str) or not answer.strip() or len(answer) > 100000:
        raise ValueError("WEB2API_ASSISTANT_REPLY_MISSING")
    cid = response.get("conversation_id")
    if not isinstance(cid, str) or not CONVERSATION_ID.fullmatch(cid):
        raise ValueError("WEB2API_CONVERSATION_ID_MISSING")
    if target and cid != target:
        raise ValueError("ROOM_CONVERSATION_ID_MISMATCH")
    return answer, cid


def post_chat(text: str, cid: str | None) -> tuple[str, str]:
    body: dict[str, Any] = {
        "model": "auto",
        "stream": False,
        "messages": [{"role": "user", "content": text}],
    }
    if cid:
        body["conversation_id"] = cid
    raw = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        CHAT_API, data=raw, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=138) as response:
        if response.status != 200:
            raise RuntimeError("WEB2API_HTTP_NOT_200")
        data = json.load(response)
    return parse_web2api_response(data, cid)


async def process_job(job: dict[str, Any], account_preflight=None) -> dict[str, Any]:
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
    if expected_email is not None:
        # Inspect real ChatGPT HTTPS session before any message bytes are sent.
        await asyncio.to_thread(actual_chrome_account, expected_email)
        if not await asyncio.to_thread(verify_same_session, expected_email):
            raise AccountGateError("ACCOUNT_EXECUTION_NOT_VERIFIED")
        # A previously dispatched job can have been revoked or deleted while
        # the user completed Chrome sign-in. Re-check with Railway immediately
        # before allowing Web2API to submit ANY message text.
        if account_preflight is None:
            raise AccountGateError("ACCOUNT_PREFLIGHT_UNAVAILABLE")
        await account_preflight(job,expected_email)
    answer, cid = await asyncio.to_thread(post_chat, content, target)
    if expected_email is not None:
        if not await asyncio.to_thread(verify_same_session, expected_email):
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


async def run(max_seconds: int = 1500) -> None:
    address = ws_destination()
    deadline = time.monotonic() + max_seconds
    attempts = 0
    authenticated_once = False
    seen_jobs: set[str] = set()
    while time.monotonic() < deadline:
        attempts += 1
        try:
            token = await asyncio.to_thread(get_oidc_token)
            async with websockets.connect(
                address, ping_interval=20, ping_timeout=20,
                close_timeout=5, max_size=3 * 1024 * 1024,
            ) as socket:
                await socket.send(json.dumps({
                    "role": "web2api", "deviceId": "web2api-main",
                    "oidc_token": token,
                }))
                first = json.loads(await asyncio.wait_for(socket.recv(), timeout=20))
                if first.get("type") != "auth.ok":
                    raise RuntimeError("RELAY_OIDC_AUTH_REJECTED")
                print("PASS_GITHUB_OIDC_RELAY_WEBSOCKET_CONNECTED", flush=True)
                # Fresh key on each authenticated GitHub Actions Chrome socket.
                # Only its private half can decrypt login credentials; Railway
                # receives ciphertext without seeing the original password.
                login_private,login_public=new_runner_key()
                waiting_google_verification={}
                await socket.send(json.dumps({
                    "type":"auth.worker.key","public_key":login_public,
                }))
                # A previously queued guest job might arrive immediately
                # after auth.ok. Preserve it rather than discarding work while
                # waiting for the encryption-key acknowledgement.
                buffered=[]
                for _ in range(8):
                    ready=json.loads(await asyncio.wait_for(socket.recv(),timeout=12))
                    if ready.get("type")=="auth.worker.key.ok":
                        break
                    if ready.get("type")=="job":
                        buffered.append(ready)
                    elif ready.get("type")=="ping":
                        await socket.send(json.dumps({"type":"pong"}))
                    else:
                        raise RuntimeError("CHROME_LOGIN_KEY_NOT_ACCEPTED")
                else:
                    raise RuntimeError("CHROME_LOGIN_KEY_NOT_ACCEPTED")
                print("PASS_EPHEMERAL_CHROME_LOGIN_PUBLIC_KEY_REGISTERED",flush=True)
                authenticated_once = True
                attempts = 0
                while time.monotonic() < deadline:
                    if buffered:
                        item=buffered.pop(0)
                    else:
                        raw = await asyncio.wait_for(
                            socket.recv(), timeout=max(1, deadline - time.monotonic())
                        )
                        item = json.loads(raw)
                    typ = item.get("type")
                    if typ == "ping":
                        await socket.send(json.dumps({"type": "pong"}))
                    elif typ == "auth.login.request":
                        rid=item.get("request_id")
                        if not isinstance(rid,str) or not 16<=len(rid)<=80:
                            continue
                        await socket.send(json.dumps({
                            "type":"auth.login.result","request_id":rid,
                            "status":"running",
                        }))
                        email=None
                        password=None
                        try:
                            email,password=decrypt_login_envelope(login_private,item)
                            # Playwright fills email/password ONLY on the
                            # official accounts.google.com domain. Never
                            # print either credential or any page content.
                            verified=await asyncio.to_thread(
                                perform_google_login,email,password)
                            await socket.send(json.dumps({
                                "type":"auth.login.result","request_id":rid,
                                "status":"verified","verified_email":verified,
                            }))
                            print("PASS_REAL_GOOGLE_CHATGPT_LOGIN_VERIFIED",flush=True)
                        except RemoteGoogleLoginError as exc:
                            code=str(exc)
                            if code=="GOOGLE_ADDITIONAL_VERIFICATION_REQUIRED" and email:
                                waiting_google_verification[rid]=email
                                state="requires_verification"
                            else:
                                state="failed"
                            await socket.send(json.dumps({
                                "type":"auth.login.result","request_id":rid,
                                "status":state,"reason":code,
                            }))
                            print("CHROME_LOGIN_STATUS_"+state.upper(),flush=True)
                        except Exception:
                            await socket.send(json.dumps({
                                "type":"auth.login.result","request_id":rid,
                                "status":"failed","reason":"CHROME_LOGIN_UNEXPECTED",
                            }))
                            print("FAIL_CHROME_LOGIN_UNVERIFIED",flush=True)
                        finally:
                            del password
                    elif typ == "auth.login.recheck":
                        rid=item.get("request_id")
                        expected=waiting_google_verification.get(rid)
                        if not expected:
                            continue
                        checked=await asyncio.to_thread(recheck_google_session,expected)
                        if checked:
                            waiting_google_verification.pop(rid,None)
                            await socket.send(json.dumps({
                                "type":"auth.login.result","request_id":rid,
                                "status":"verified","verified_email":checked,
                            }))
                        else:
                            await socket.send(json.dumps({
                                "type":"auth.login.result","request_id":rid,
                                "status":"requires_verification",
                                "reason":"GOOGLE_ADDITIONAL_VERIFICATION_REQUIRED",
                            }))
                    elif typ == "job":
                        job = item.get("job")
                        if not isinstance(job, dict):
                            continue
                        jid, rid = job.get("id"), job.get("room_id")
                        if not isinstance(jid, str) or not isinstance(rid, str):
                            continue
                        if jid in seen_jobs:
                            print("REFUSE_DUPLICATE_RELAY_JOB", flush=True)
                            continue
                        seen_jobs.add(jid)
                        await socket.send(json.dumps({
                            "type": "job.received", "job_id": jid,
                            "room_id": rid, "stage": "web2api_received",
                        }))
                        print("RELAY_WEB2API_JOB_RECEIVED", flush=True)
                        async def account_preflight(job,expected_email):
                            await socket.send(json.dumps({
                                "type":"job.preflight",
                                "job_id":job["id"],
                                "room_id":job["room_id"],
                                "account_id":job["account_id"],
                                "execution_account_email":expected_email,
                            }))
                            for _ in range(4):
                                response=json.loads(await asyncio.wait_for(
                                    socket.recv(),timeout=12))
                                if response.get("type")=="ping":
                                    await socket.send(json.dumps({"type":"pong"}))
                                    continue
                                if response.get("job_id")!=job["id"] or response.get("room_id")!=job["room_id"]:
                                    raise AccountGateError("ACCOUNT_PREFLIGHT_DENIED")
                                if response.get("type")!="job.preflight.ok":
                                    raise AccountGateError("ACCOUNT_PREFLIGHT_DENIED")
                                return
                            raise AccountGateError("ACCOUNT_PREFLIGHT_DENIED")
                        try:
                            result = await process_job(job,account_preflight=account_preflight)
                        except Exception as exc:
                            # Never repeat an uncertain chat send; signal failure
                            # and leave the server's original job state intact.
                            reason = str(exc)
                            if reason not in {
                                "UNSUPPORTED_WEB_WORKER_ACTION",
                                "WEB2API_BINARY_ATTACHMENT_NOT_VERIFIED",
                                "INVALID_CHAT_TEXT", "UNVERIFIED_TARGET_CONVERSATION",
                                "UNVERIFIED_TARGET_URL", "WEB2API_RESPONSE_INVALID",
                                "WEB2API_CHOICES_MISSING", "WEB2API_ASSISTANT_REPLY_MISSING",
                                "WEB2API_CONVERSATION_ID_MISSING", "ROOM_CONVERSATION_ID_MISMATCH",
                                "MALFORMED_RELAY_JOB", "ACCOUNT_EXECUTION_NOT_VERIFIED",
                                "ACCOUNT_ID_INVALID", "ACCOUNT_EMAIL_INVALID",
                                "ACCOUNT_LOGOUT_UI_UNAVAILABLE", "ACCOUNT_LOGOUT_NOT_VERIFIED",
                                "ACCOUNT_LOGIN_WRONG_IDENTITY", "ACCOUNT_INTERACTIVE_LOGIN_REQUIRED",
                                "ACCOUNT_CHANGED_DURING_SEND", "CHROME_CONTEXT_MISSING",
                                "ACCOUNT_PREFLIGHT_UNAVAILABLE","ACCOUNT_PREFLIGHT_DENIED",
                            }:
                                reason = "WEB2API_SEND_OR_VERIFY_FAILED"
                            await socket.send(json.dumps({
                                "type": "job.error", "job_id": jid, "room_id": rid,
                                "stage": "web2api_failed", "reason": reason,
                            }))
                            print("FAIL_RELAY_WEB2API_JOB_" + reason, flush=True)
                        else:
                            await socket.send(json.dumps(result, ensure_ascii=False))
                            print("PASS_RELAY_WEB2API_JOB_RESULT_VERIFIED", flush=True)
        except asyncio.TimeoutError:
            print("RELAY_WEBSOCKET_IDLE_TIMEOUT", flush=True)
        except Exception as exc:
            # Never include network exception text: it can contain signed URLs.
            print("RELAY_CONNECTION_INTERRUPTED_" + type(exc).__name__, flush=True)
        if time.monotonic() >= deadline:
            break
        await asyncio.sleep(min(30, max(2, 2 ** min(attempts, 4))))
    print("RELAY_ACTIONS_WORKER_RUN_ENDED", flush=True)
    if not authenticated_once:
        raise RuntimeError("RELAY_OIDC_AUTH_NEVER_SUCCEEDED")


if __name__ == "__main__":
    duration = int(os.environ.get("W2A_WORKER_SECONDS", "600"))
    try:
        asyncio.run(run(max_seconds=max(60, min(1500, duration))))
    except Exception as exc:
        print("FAIL_RELAY_WORKER_"+type(exc).__name__,flush=True)
        sys.exit(1)
