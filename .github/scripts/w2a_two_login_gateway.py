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
<title>HITEL · 원격 Chrome 로그인</title>
<style>body{font-family:system-ui,sans-serif;background:#f6f8fb;color:#15283f;
max-width:560px;margin:6vh auto;padding:20px}main{background:white;padding:25px;
border-radius:18px;box-shadow:0 8px 36px #1a2c4214}h1{font-size:23px}
label{display:block;margin:18px 0 6px}input{box-sizing:border-box;width:100%;
font-size:17px;padding:14px;border:1px solid #c2cfdf;border-radius:9px}
button{margin-top:18px;background:#1d466e;border:0;color:white;border-radius:9px;
padding:14px 20px;font-size:16px;width:100%}p{line-height:1.7;color:#54657a}</style>
</head><body><main><h1>HITEL · 계정 A/B 원격 Chrome</h1>
<p id="auto-status">보안 연결을 확인하고 있습니다. 전용 접속 링크를 여셨다면
접속 코드를 입력하실 필요가 없습니다.</p>
<form id="grant-form" method="post" action="/grant"><label>예비 접속 코드 (직접 입력은 필요하지 않습니다)</label>
<input name="code" type="password" autocomplete="off" required maxlength="200"/>
<button type="submit">보호된 원격 화면 열기</button></form>
<p>Google 이메일·비밀번호·추가 인증은 이어지는 실제 Chrome의
공식 Google·ChatGPT 로그인 페이지에서 직접 처리합니다.</p>
<script>
(function(){
  // Link fragment stays local to the user's browser: never sent in the GET
  // request, CDN edge logs, or referrer. Browser performs one HTTPS POST to
  // local access-control gateway, receiving an HttpOnly session cookie.
  const p=new URLSearchParams(location.hash.startsWith('#')?
    location.hash.slice(1):'');
  const access=p.get('access');
  if(!access || !/^[A-Za-z0-9_-]{40,120}$/.test(access)){
    document.getElementById('auto-status').textContent=
      '이 주소는 보호된 연결을 요청합니다. 새로 발급된 원클릭 링크를 사용해 주십시오.';
    return;
  }
  history.replaceState(null,'','/grant');
  const form=document.getElementById('grant-form');
  form.querySelector('[name=code]').value=access;
  document.getElementById('auto-status').textContent=
    '자동으로 인증하고 원격 Chrome을 열고 있습니다.';
  form.submit();
})();
</script></main></body></html>"""

DASH_HTML = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><title>HITEL · 계정 두 개 로그인</title>
<style>*{box-sizing:border-box}body{font-family:system-ui,Arial,sans-serif;margin:0;
background:#f3f6fb;color:#19324d}header{padding:16px 20px;background:#123450;color:white}
header h1{font-size:20px;margin:0}main{max-width:1160px;margin:auto;padding:16px}
.steps{display:grid;grid-template-columns:1fr 1fr;gap:12px}.step{background:white;
padding:15px;border-radius:12px;border:1px solid #dbe5ef}h2{font-size:16px;margin:0 0 8px}
p{line-height:1.55}small{color:#526578}button,.open{border:0;background:#185d91;
padding:12px 16px;border-radius:9px;color:white;cursor:pointer;text-decoration:none;
font-weight:600}button:disabled{opacity:.5;cursor:not-allowed}#result{padding:11px}
#screen{height:61vh;min-height:400px;width:100%;background:#1b2431;border:0;
border-radius:12px;margin-top:12px}footer{font-size:12px;color:#55697d;padding:14px}
@media(max-width:640px){.steps{grid-template-columns:1fr}#screen{height:56vh;min-height:320px}}</style>
</head><body><header><h1>HITEL · 실제 ChatGPT 계정 2개 로그인</h1></header>
<main><p>아래 원격 Chrome에서 <strong>Google/ChatGPT 공식 로그인</strong>을 직접 완료하신 뒤
해당 계정의 <strong>인증 확인·암호화 저장</strong>을 누르십시오.
비밀번호·2단계 인증번호를 이 관리 페이지에 입력하실 필요가 없습니다.</p>
<div class="steps"><section class="step"><h2>① 계정 A</h2><p id="sa">대기 중</p>
<button id="savea" onclick="save('a')">A 로그인 확인·저장</button></section>
<section class="step"><h2>② 계정 B</h2><p id="sb">A 완료 후 진행</p>
<button id="saveb" onclick="save('b')" disabled>B 로그인 확인·저장</button></section></div>
<p><button id="google-start" onclick="openGoogle()">Google 공식 로그인 화면 자동 열기</button></p>
<p id="result" role="status">원격 브라우저를 연결하고 있습니다.</p>
<a class="open" href="/vnc.html?autoconnect=true&resize=remote" target="_blank"
rel="noopener noreferrer">원격 Chrome 전체 화면</a>
<iframe id="screen" title="GitHub Actions 원격 Chrome"
src="/vnc.html?autoconnect=true&resize=remote" allow="clipboard-read;clipboard-write"></iframe>
<footer>두 계정은 서로 다른 Chrome 프로필에 저장됩니다. 실제 계정이 확인되어야 저장되며,
GitHub Actions가 종료되면 이 원격 화면도 종료됩니다.</footer></main>
<script>
let busy=false;
async function refresh(){
try{
 const r=await fetch('/status',{cache:'no-store',credentials:'same-origin'});
 if(!r.ok)throw Error('원격 연결 만료');
 const d=await r.json();
 const labels={waiting:'Chrome에서 로그인해 주십시오',checking:'실제 세션 확인 중',
 saved:'실제 로그인 확인 및 암호화 저장 완료',pending:'이전 계정 저장 후 진행'};
 for(const s of ['a','b']){
  document.getElementById('s'+s).textContent=
   (labels[d.slots[s]]||d.slots[s])+(d.masked[s]?' · '+d.masked[s]:'');
  document.getElementById('save'+s).disabled=busy||d.active!==s||d.slots[s]!=='waiting';
 }
 if(d.complete)document.getElementById('result').textContent=
 '두 계정의 실제 로그인을 확인했습니다. 암호화된 Chrome 프로필을 GitHub에 보관합니다.';
}catch(e){document.getElementById('result').textContent=e.message}
}
async function openGoogle(){
 if(busy)return;
 const status=document.getElementById('result');
 status.textContent='원격 Chrome에서 공식 Google 로그인을 준비하고 있습니다.';
 try{
  const r=await fetch('/prepare-google',{method:'POST',credentials:'same-origin'});
  const d=await r.json();
  if(!r.ok||!d.ok)throw Error(d.error||'공식 로그인 화면을 열지 못했습니다');
  status.textContent=d.status==='already_authenticated'?
    '현재 원격 Chrome에 ChatGPT 로그인이 확인됩니다. 해당 계정 저장 버튼을 누르십시오.':
    '원격 Chrome에서 Google/ChatGPT 로그인 화면을 확인하시고 직접 로그인해 주십시오.';
 }catch(e){status.textContent=e.message}
}
async function save(slot){
 busy=true;document.getElementById('savea').disabled=true;
 document.getElementById('saveb').disabled=true;
 document.getElementById('result').textContent='ChatGPT 실제 로그인 여부를 확인하고 있습니다.';
 try{
  const r=await fetch('/finish',{method:'POST',credentials:'same-origin',
   headers:{'Content-Type':'application/json'},body:JSON.stringify({slot})});
  const j=await r.json();
  if(!r.ok||!j.ok)throw Error(j.error||'실제 로그인을 확인하지 못했습니다');
  document.getElementById('result').textContent=
   slot==='a'?'A 저장 완료. 이제 B 계정으로 로그인해 주십시오.':'A와 B 모두 확인 완료';
 }catch(e){document.getElementById('result').textContent=e.message}
 finally{busy=false;await refresh()}
}
setInterval(refresh,3500);refresh();
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
