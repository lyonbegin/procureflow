#!/usr/bin/env python3
"""Two real ChatGPT logins in one password-protected GitHub Actions Chrome desktop.

A and B use different Chrome user-data-dir paths. Users type Google/OpenAI
credentials ONLY into their real sign-in page in noVNC. This gateway does not
receive or record account passwords, recovery codes, cookies or auth tokens.

The private access code is checked server-side (SHA-256), then an HttpOnly,
Secure, SameSite=Strict cookie gates all VNC and control routes via nginx.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import http.server
import json
import os
import pathlib
import secrets
import subprocess
import threading
import time
import urllib.parse
from http.cookies import SimpleCookie

from w2a_account_runtime import read_browser_email
from w2a_profile_crypto import encrypt

ROOT = pathlib.Path(os.environ.get("W2A_DUAL_ROOT", "/tmp/w2a-two-logins"))
ROOT.mkdir(parents=True, exist_ok=True)
EXPECTED = os.environ.get("W2A_ACCESS_SHA256", "")
CHROME_BINARY = os.environ.get("CHROME_BINARY", "google-chrome")
SESSION = secrets.token_urlsafe(40)
_lock = threading.RLock()
_state = {"active": "a", "a": "waiting", "b": "pending", "emails": {}, "error": ""}
_process: subprocess.Popen | None = None
LIMIT = 45 * 60


def _mask(email: str) -> str:
    name, _, domain = email.partition("@")
    return name[:2] + "•••@" + domain if domain else "인증됨"


def _profile(slot: str) -> pathlib.Path:
    assert slot in ("a", "b")
    return ROOT / ("chrome-" + slot)


def _archive(slot: str) -> pathlib.Path:
    return ROOT / ("account-" + slot + ".bin")


def _stop_chrome() -> None:
    global _process
    if _process is None:
        return
    if _process.poll() is None:
        _process.terminate()
        try:
            _process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            _process.kill()
            _process.wait(timeout=5)
    _process = None


def start_chrome(slot: str) -> None:
    global _process
    if slot not in ("a", "b"):
        raise ValueError("INVALID_SLOT")
    _stop_chrome()
    profile = _profile(slot)
    profile.mkdir(parents=True, exist_ok=True)
    profile.chmod(0o700)
    cmd = [
        CHROME_BINARY, "--no-sandbox", "--disable-dev-shm-usage",
        "--no-first-run", "--no-default-browser-check",
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=9222", "--user-data-dir=" + str(profile),
        "https://chatgpt.com/auth/login",
    ]
    _process = subprocess.Popen(
        cmd, env={**os.environ, "DISPLAY": ":99"},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    _state["active"] = slot
    _state[slot] = "waiting"
    print("CHROME_LOGIN_SLOT_" + slot.upper() + "_OPEN", flush=True)


def verify_browser_email() -> str | None:
    """Read the REAL ChatGPT HTTPS session; never trust a browser form label."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
        if not browser.contexts:
            return None
        context = browser.contexts[0]
        tabs = [p for p in context.pages if not p.is_closed()]
        page = next((p for p in tabs if p.url.startswith("https://chatgpt.com/")), None)
        if page is None:
            page = context.new_page()
        if not page.url.startswith("https://chatgpt.com/"):
            page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=30000)
        result = read_browser_email(page)
        if result:
            return result
        # Google may have opened a new tab and not returned to ChatGPT yet.
        for _ in range(3):
            time.sleep(2)
            try:
                result = read_browser_email(page)
                if result:
                    return result
            except Exception:
                pass
    return None


def prepare_google_login() -> dict:
    """Mobile convenience: navigate/click real ChatGPT Google sign-in UI only.

    Does not collect a password or touch a Google input field. Reuses active
    CDP browser, and stops if the user already has an authenticated session.
    """
    import re
    from playwright.sync_api import sync_playwright
    with _lock:
        slot=_state.get("active")
        if slot not in ("a","b") or _state[slot] != "waiting":
            return {"ok":False,"error":"ACCOUNT_SLOT_NOT_READY"}
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
                if not browser.contexts:
                    return {"ok":False,"error":"CHROME_NOT_READY"}
                context=browser.contexts[0]
                pages=[p for p in context.pages if not p.is_closed()
                       and p.url.startswith("https://chatgpt.com/")]
                page=pages[0] if pages else context.new_page()
                if pages:
                    if read_browser_email(page):
                        return {"ok":True,"status":"already_authenticated"}
                page.goto("https://chatgpt.com/auth/login",
                          wait_until="domcontentloaded",timeout=30000)
                for label in (r"Continue with Google|Google로 계속|Google 계정으로 계속",
                              r"^Log in$|^로그인$"):
                    for kind in ("button","link"):
                        item=page.get_by_role(kind,name=re.compile(label,re.I))
                        try:
                            if item.count() and item.first.is_visible():
                                item.first.click(timeout=5000)
                                return {"ok":True,"status":"provider_clicked" if "Google" in label else "login_opened"}
                        except Exception:
                            pass
                return {"ok":True,"status":"login_opened"}
        except Exception:
            return {"ok":False,"error":"GOOGLE_LOGIN_PAGE_UNAVAILABLE"}


def finish(slot: str) -> dict:
    """Persist only a proved session. Different slots MUST differ in email."""
    if slot not in ("a", "b"):
        return {"ok": False, "error": "INVALID_SLOT"}
    with _lock:
        if _state["active"] != slot or _state[slot] != "waiting":
            return {"ok": False, "error": "WRONG_ACTIVE_SLOT"}
        _state[slot] = "checking"
    try:
        email = verify_browser_email()
        if not email:
            raise ValueError("CHATGPT_LOGIN_NOT_VERIFIED")
        if slot == "b" and email == _state["emails"].get("a"):
            raise ValueError("SAME_CHATGPT_ACCOUNT_FOR_BOTH_SLOTS")
        with _lock:
            _stop_chrome()  # Flush Chrome cookies/profile before encryption.
            encrypt(str(_profile(slot)), str(_archive(slot)))
            _state["emails"][slot] = email
            _state[slot] = "saved"
            if slot == "a":
                start_chrome("b")
            else:
                _state["active"] = None
                (ROOT / "both-verified.flag").touch(mode=0o600)
        print("PASS_REAL_ACCOUNT_" + slot.upper() + "_SESSION_ENCRYPTED", flush=True)
        return {"ok": True, "slot": slot, "next": "b" if slot == "a" else None}
    except Exception as exc:
        code = str(exc) if isinstance(exc, ValueError) else "CHATGPT_LOGIN_CHECK_FAILED"
        with _lock:
            _state[slot] = "waiting"
            _state["error"] = code
        print("ACCOUNT_" + slot.upper() + "_NOT_VERIFIED", flush=True)
        return {"ok": False, "error": code}


LOGIN_HTML = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><title>HITEL 원격 Chrome 연결</title>
<style>body{font:16px system-ui,-apple-system,sans-serif;max-width:540px;
margin:12vh auto;padding:20px;color:#14314a}h1{font-size:22px}
p{color:#5c6e7c;line-height:1.6}</style></head>
<body><h1>원격 Chrome에 연결 중입니다</h1>
<p id="auto-status">접속 권한을 확인하고 있습니다.</p>
<form id="grant-form" method="post" action="/grant" hidden>
<input name="code" type="hidden"></form>
<script>
(function(){
const p=new URLSearchParams(location.hash.replace(/^#/,''));
const code=p.get('access');
if(!code || !/^[A-Za-z0-9_-]{40,120}$/.test(code)){
 document.getElementById('auto-status').textContent =
 '이전 연결이 만료되었거나 개인용 접속 링크가 아닙니다. GitHub Pages의 새로운 링크로 열어 주십시오.';
 return;
}
history.replaceState(null,'','/grant');
const form=document.getElementById('grant-form');
form.querySelector('[name=code]').value=code;
document.getElementById('auto-status').textContent =
 '인증 중입니다. Chrome 화면으로 연결합니다.';
form.submit();
})();
</script></body></html>"""

DASH_HTML = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>HITEL · Chrome 계정 로그인</title>
<style>*{box-sizing:border-box}
body{font:16px system-ui,-apple-system,"Noto Sans KR",sans-serif;margin:0;
background:#f5f7fa;color:#172c40}
main{max-width:850px;margin:0 auto;padding:12px}
h1{font-size:20px;margin:0}
header{background:white;border-bottom:1px solid #dce4eb;padding:15px}
p{line-height:1.5;margin:8px 0;color:#526478}
.status{font-weight:650;padding:13px;margin:12px 0;background:white;border-radius:10px}
button,.btn{display:block;width:100%;text-align:center;border:0;border-radius:11px;
padding:14px;font-size:16px;font-weight:700;cursor:pointer;text-decoration:none}
button{background:#185b90;color:white}
button:disabled{background:#b1c0cd;cursor:default}
.btn{background:#e6f0f9;color:#185b90;margin:10px 0}
#screen{display:block;width:100%;height:65vh;min-height:330px;border:0;
border-radius:12px;background:#263745}
.help{font-size:13px}
@media(max-width:600px){#screen{height:58vh;min-height:320px}}
</style></head>
<body><header><h1>HITEL · ChatGPT 계정 로그인</h1></header>
<main>
<div class="status" id="state" role="status">원격 Chrome을 연결하고 있습니다.</div>
<p>아래 실제 Chrome에서 Google/ChatGPT에 로그인해 주십시오.</p>
<iframe id="screen" title="GitHub Actions 원격 Chrome"
src="/vnc.html?autoconnect=true&resize=remote"></iframe>
<a class="btn" href="/vnc.html?autoconnect=true&resize=remote"
target="_blank" rel="noopener noreferrer">Chrome 화면 크게 열기</a>
<button id="save" onclick="saveCurrent()">로그인 확인 · 저장</button>
<p id="notice" role="status">로그인하신 뒤 위 버튼을 한 번만 누르십시오.</p>
<p class="help">계정 A 저장이 끝나면 자동으로 계정 B용 새 Chrome이 열립니다.
Google 비밀번호나 인증번호는 이 관리 페이지에 입력하지 않습니다.</p>
</main>
<script>
let busy=false,active=null;
async function update(){
 try{
  const r=await fetch('/status',{cache:'no-store',credentials:'same-origin'});
  if(!r.ok)throw Error('원격 브라우저 연결이 만료되었습니다');
  const d=await r.json();active=d.active;
  const doneA=d.slots.a==='saved',doneB=d.slots.b==='saved';
  const btn=document.getElementById('save');
  btn.disabled=busy||d.complete||!(active==='a'||active==='b');
  btn.textContent=d.complete?'두 계정 저장 완료':
    active==='b'?'계정 B 로그인 확인 · 저장':'계정 A 로그인 확인 · 저장';
  document.getElementById('state').textContent=d.complete?
    '계정 A·B 두 개 모두 실제 로그인 확인 및 암호화 저장 완료':
    active==='b'?'계정 A 저장 완료 · 현재 계정 B 로그인':
    '현재 계정 A 로그인';
  if(d.complete)document.getElementById('notice').textContent=
    '두 계정을 암호화 저장했습니다. GitHub Actions에서 작업을 마칩니다.';
 }catch(e){document.getElementById('notice').textContent=e.message}
}
async function saveCurrent(){
 if(busy||!active)return;
 busy=true;document.getElementById('save').disabled=true;
 document.getElementById('notice').textContent='실제 ChatGPT 로그인 확인 중…';
 try{
  const r=await fetch('/finish',{method:'POST',
    credentials:'same-origin',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({slot:active})});
  const result=await r.json();
  if(!r.ok||!result.ok)throw Error(result.error||'로그인을 확인하지 못했습니다');
  document.getElementById('notice').textContent=
    result.next==='b'?'A 저장 완료. 아래 새 Chrome에서 계정 B로 로그인해 주십시오.':
    'A와 B 두 계정을 모두 저장했습니다.';
 }catch(e){document.getElementById('notice').textContent=
   '저장되지 않았습니다: '+e.message}
 finally{busy=false;await update()}
}
setInterval(update,4000);update();
</script></body></html>"""

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log URLs, session cookies or anything typed by user.

    def reply(self, code, body=b"", headers=()):
        self.send_response(code)
        for k, v in (
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("Referrer-Policy", "no-referrer"),
            ("X-Content-Type-Options", "nosniff"),
        ) + tuple(headers):
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _cookie_ok(self) -> bool:
        try:
            c = SimpleCookie()
            c.load(self.headers.get("Cookie", ""))
            token = c.get("w2a_session")
            return bool(token and hmac.compare_digest(token.value, SESSION))
        except Exception:
            return False

    def _origin_ok(self) -> bool:
        origin=self.headers.get("Origin", "")
        host=self.headers.get("Host", "")
        return origin == "https://" + host

    def _json(self, status, obj):
        self.reply(status, json.dumps(obj).encode("utf-8"),
                   (("Content-Type", "application/json; charset=utf-8"),))

    def _read(self, limit=1024):
        try:
            size=int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > limit:
                return None
            return self.rfile.read(size)
        except (ValueError, OSError):
            return None

    def do_GET(self):
        path=urllib.parse.urlsplit(self.path).path
        if path=="/health":
            self.reply(200,b"ok")
        elif path=="/verify":
            self.reply(200 if self._cookie_ok() else 401)
        elif path=="/grant":
            if self._cookie_ok():
                self.reply(303,headers=(("Location","/"),))
            else:
                self.reply(200,LOGIN_HTML.encode(),
                           (("Content-Type","text/html; charset=utf-8"),))
        elif not self._cookie_ok():
            self.reply(401,b"Protected Chrome login requires access code.")
        elif path=="/":
            self.reply(200,DASH_HTML.encode(),
                       (("Content-Type","text/html; charset=utf-8"),))
        elif path=="/status":
            with _lock:
                result={"active":_state["active"],
                        "slots":{s:_state[s] for s in ("a","b")},
                        "masked":{s:_mask(v) for s,v in _state["emails"].items()},
                        "complete":(ROOT/"both-verified.flag").exists()}
            self._json(200,result)
        else:
            self.reply(404)

    def do_POST(self):
        path=urllib.parse.urlsplit(self.path).path
        raw=self._read()
        if raw is None:
            self._json(400,{"ok":False,"error":"INVALID_REQUEST"})
            return
        if path=="/grant":
            try:
                d=urllib.parse.parse_qs(raw.decode(),max_num_fields=3)
                code=d.get("code",[""])[0]
                correct=(len(EXPECTED)==64
                         and hmac.compare_digest(
                             hashlib.sha256(code.encode()).hexdigest(), EXPECTED))
            except Exception:
                correct=False
            if not correct:
                self.reply(403,b"Invalid private Chrome access code")
                return
            self.reply(303,headers=(
                ("Set-Cookie","w2a_session="+SESSION+
                 "; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age=2700"),
                ("Location","/"),
            ))
            return
        if path not in ("/finish","/prepare-google") or not self._cookie_ok() or not self._origin_ok():
            self._json(403,{"ok":False,"error":"UNAUTHORIZED"})
            return
        if path == "/prepare-google":
            result=prepare_google_login()
            self._json(200 if result["ok"] else 409,result)
            return
        try:
            slot=json.loads(raw).get("slot")
        except (TypeError,ValueError):
            slot=None
        if slot not in ("a","b"):
            self._json(422,{"ok":False,"error":"INVALID_SLOT"})
            return
        outcome=finish(slot)
        self._json(200 if outcome["ok"] else 409,outcome)


def main():
    if not (EXPECTED and CHROME_BINARY):
        raise SystemExit("CONFIG_MISSING")
    start_chrome("a")
    print("TWO_ACCOUNT_GATEWAY_STARTED",flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", 8899),Handler).serve_forever()


if __name__=="__main__":
    main()
