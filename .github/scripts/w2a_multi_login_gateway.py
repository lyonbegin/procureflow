#!/usr/bin/env python3
"""HITEL interactive multi-account ChatGPT login manager.

The operator signs into the REAL Google/OpenAI page via protected noVNC.
Each verified ChatGPT identity is saved into an INDEPENDENT AES-GCM encrypted
Chrome profile archive. A separately encrypted registry supports later runs.
Only encrypted archives are ever uploaded to GitHub Actions artifacts.

Does not automate passwords, collect recovery codes, or log session cookies.
"""
from __future__ import annotations

import hashlib
import hmac
import http.server
import json
import os
import pathlib
import re
import secrets
import subprocess
import threading
import time
import urllib.parse
from http.cookies import SimpleCookie

from w2a_account_runtime import read_browser_email, canonical_email
from w2a_profile_crypto import encrypt, decrypt

ROOT = pathlib.Path(os.environ.get(
    "W2A_MULTI_ROOT", os.environ.get("W2A_DUAL_ROOT", "/tmp/w2a-multi-login")))
ROOT.mkdir(parents=True, exist_ok=True)
ROOT.chmod(0o700)

EXPECTED = os.environ.get("W2A_ACCESS_SHA256", "")
CHROME_BINARY = os.environ.get("CHROME_BINARY", "google-chrome")
SESSION = secrets.token_urlsafe(42)
MAX_ACCOUNTS = 100  # Sequential isolated profiles; limited by temporary Actions runtime.
LOCK = threading.RLock()
ACCOUNTS: list[dict] = []
STATE = {"active": None, "phase": "initializing", "completed": False, "error": ""}
PROCESS: subprocess.Popen | None = None


def mask(email: str) -> str:
    name, _, domain = email.partition("@")
    return name[:2] + "•••@" + domain


def archive(idx: int) -> pathlib.Path:
    return ROOT / f"account-{idx:04d}.bin"


def profile(idx: int) -> pathlib.Path:
    return ROOT / f"profile-{idx:04d}"


def stop_chrome() -> None:
    global PROCESS
    if PROCESS is None:
        return
    if PROCESS.poll() is None:
        PROCESS.terminate()
        try:
            PROCESS.wait(timeout=10)
        except subprocess.TimeoutExpired:
            PROCESS.kill()
            PROCESS.wait(timeout=5)
    PROCESS = None


def start_chrome(idx: int) -> None:
    global PROCESS
    if not 1 <= idx <= MAX_ACCOUNTS:
        raise ValueError("ACCOUNT_LIMIT_REACHED")
    stop_chrome()
    path = profile(idx)
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    PROCESS = subprocess.Popen(
        [CHROME_BINARY, "--no-sandbox", "--disable-dev-shm-usage",
         "--no-first-run", "--no-default-browser-check",
         "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=9222",
         "--user-data-dir=" + str(path), "https://chatgpt.com/auth/login"],
        env={**os.environ, "DISPLAY": ":99"},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    STATE.update(active=idx, phase="login", error="")
    print("CHROME_ACCOUNT_REGISTRATION_WINDOW_OPEN", flush=True)


def verify_browser_email() -> str | None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(
            "http://127.0.0.1:9222", timeout=15000)
        if not browser.contexts:
            return None
        context = browser.contexts[0]
        pages = [p for p in context.pages if not p.is_closed()
                 and p.url.startswith("https://chatgpt.com/")]
        page = pages[0] if pages else context.new_page()
        if not page.url.startswith("https://chatgpt.com/"):
            page.goto("https://chatgpt.com/",
                      wait_until="domcontentloaded", timeout=25000)
        for _ in range(3):
            try:
                result = read_browser_email(page)
                if result:
                    return canonical_email(result)
            except Exception:
                pass
            time.sleep(1)
    return None


def store_registry() -> None:
    """Encrypt account emails/IDs. NEVER upload plaintext registry.json."""
    src = ROOT / "registry-source"
    src.mkdir(mode=0o700, exist_ok=True)
    filename = src / "registry.json"
    filename.write_text(json.dumps({"version": 1, "accounts": ACCOUNTS},
                                    ensure_ascii=False), encoding="utf-8")
    filename.chmod(0o600)
    encrypt(str(src), str(ROOT / "registry.bin"))
    filename.unlink(missing_ok=True)


def load_registry() -> None:
    encrypted = ROOT / "registry.bin"
    if not encrypted.is_file():
        return
    tmp = ROOT / "registry-restored"
    tmp.mkdir(mode=0o700, exist_ok=True)
    decrypt(str(encrypted), str(tmp))
    source = tmp / "chrome-profile" / "registry.json"
    raw = json.loads(source.read_text(encoding="utf-8"))
    if raw.get("version") != 1 or not isinstance(raw.get("accounts"), list):
        raise ValueError("INVALID_ENCRYPTED_ACCOUNT_REGISTRY")
    old = raw["accounts"]
    if len(old) > MAX_ACCOUNTS:
        raise ValueError("TOO_MANY_SAVED_ACCOUNTS")
    seen = set()
    for i, item in enumerate(old, 1):
        if not isinstance(item, dict) or item.get("id") != i:
            raise ValueError("INVALID_SAVED_ACCOUNT_ID")
        email = canonical_email(item.get("email"))
        if email in seen or not archive(i).is_file():
            raise ValueError("INCOMPLETE_SAVED_ACCOUNT_PROFILES")
        seen.add(email)
        ACCOUNTS.append({"id": i, "email": email})
    source.unlink(missing_ok=True)
    print("PASS_PRIOR_ENCRYPTED_ACCOUNTS_RESTORED_COUNT=" + str(len(ACCOUNTS)),
          flush=True)


def save_current() -> dict:
    with LOCK:
        idx = STATE["active"]
        if STATE["phase"] != "login" or idx is None or STATE["completed"]:
            return {"ok": False, "error": "LOGIN_NOT_READY"}
        STATE["phase"] = "checking"
        try:
            email = verify_browser_email()
            if not email:
                raise ValueError("CHATGPT_LOGIN_NOT_VERIFIED")
            if any(account["email"] == email for account in ACCOUNTS):
                raise ValueError("ACCOUNT_ALREADY_REGISTERED")
            stop_chrome()
            encrypt(str(profile(idx)), str(archive(idx)))
            ACCOUNTS.append({"id": idx, "email": email})
            store_registry()
            STATE.update(active=None, phase="ready", error="")
            print("PASS_REAL_CHATGPT_ACCOUNT_VERIFIED_AND_ENCRYPTED_SLOT="
                  + str(idx), flush=True)
            return {"ok": True, "count": len(ACCOUNTS)}
        except Exception as exc:
            if PROCESS is None:
                try:
                    start_chrome(idx)
                except Exception:
                    pass
            code = str(exc) if isinstance(exc, ValueError) else "ACCOUNT_SAVE_FAILED"
            STATE["phase"] = "login"
            STATE["error"] = code
            return {"ok": False, "error": code}


def add_account() -> dict:
    with LOCK:
        if STATE["phase"] != "ready" or STATE["completed"]:
            return {"ok": False, "error": "SAVE_CURRENT_ACCOUNT_FIRST"}
        idx = len(ACCOUNTS) + 1
        if idx > MAX_ACCOUNTS:
            return {"ok": False, "error": "ACCOUNT_LIMIT_REACHED"}
        try:
            start_chrome(idx)
            return {"ok": True, "active": idx}
        except Exception:
            STATE["phase"] = "ready"
            return {"ok": False, "error": "CHROME_COULD_NOT_START"}


def complete_registration() -> dict:
    with LOCK:
        if not ACCOUNTS:
            return {"ok": False, "error": "NO_VERIFIED_CHATGPT_ACCOUNT"}
        if STATE["phase"] == "checking":
            return {"ok": False, "error": "ACCOUNT_VERIFICATION_RUNNING"}
        stop_chrome()
        # Ensure every account's encrypted file exists before upload.
        if not all(archive(x["id"]).is_file() for x in ACCOUNTS):
            return {"ok": False, "error": "ACCOUNT_ARCHIVE_MISSING"}
        store_registry()
        STATE.update(active=None, phase="complete", completed=True)
        (ROOT / "registration-complete.flag").touch(mode=0o600)
        print("PASS_MULTI_CHATGPT_ACCOUNTS_READY_FOR_ENCRYPTED_ARTIFACT_UPLOAD_COUNT="
              + str(len(ACCOUNTS)), flush=True)
        return {"ok": True, "count": len(ACCOUNTS)}


LOGIN_HTML = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>HITEL 원격 Chrome 연결</title>
<style>body{font:16px system-ui,-apple-system,sans-serif;max-width:520px;
margin:13vh auto;padding:20px;color:#14314a}p{line-height:1.65;color:#66758a}
</style></head><body>
<h2>원격 Chrome에 연결 중입니다.</h2>
<p id="msg">개인 접속 권한을 확인하고 있습니다.</p>
<form id="f" method="post" action="/grant" hidden><input name="code" type="hidden"></form>
<script>
const t=new URLSearchParams(location.hash.slice(1)).get("access");
if(t && /^[A-Za-z0-9_-]{40,120}$/.test(t)){
 history.replaceState(null,"","/grant");
 const f=document.getElementById("f");f.elements.code.value=t;f.submit();
}else{document.getElementById("msg").textContent=
 "개인용 원격 Chrome 연결 링크가 필요합니다. GitHub Pages에서 새 링크로 접속해 주십시오.";}
</script></body></html>"""

DASH_HTML = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><title>HITEL · ChatGPT 계정 등록</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f5f7fb;
font:16px system-ui,-apple-system,"Noto Sans KR",sans-serif;color:#173049}
main{max-width:940px;margin:auto;padding:14px}h1{font-size:22px;margin:12px 0}
h2{font-size:17px;margin:0 0 9px}p{line-height:1.55;color:#61768a}
#state{padding:13px;background:white;border:1px solid #dde6ef;border-radius:12px}
#screen{height:57vh;min-height:340px;width:100%;border:0;background:#283746;border-radius:12px}
button,.open{display:block;border:0;text-align:center;font-size:16px;font-weight:700;
padding:14px 15px;width:100%;background:#195c8e;color:white;border-radius:12px;
cursor:pointer;text-decoration:none}
button:disabled{background:#adb9c6}
.open{background:#e4eef7;color:#195c8e;margin:9px 0}
aside{margin:13px 0;padding:15px;background:white;border:1px solid #dde6ef;
border-radius:12px}
#accounts{padding-left:23px;margin:6px 0;line-height:1.9}
.controls{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:10px 0}
#message{font-weight:650;min-height:24px}
@media(max-width:640px){#screen{height:56vh;min-height:300px}}
</style></head>
<body><main>
<h1>ChatGPT 계정 등록</h1>
<div id="state" role="status">원격 Chrome 연결 중입니다.</div>
<p>아래 Chrome에서 공식 Google·ChatGPT에 로그인하신 후 <b>이 계정 저장</b>을 누르십시오.</p>
<iframe id="screen" title="GitHub Actions Chrome noVNC"
src="/vnc.html?autoconnect=true&resize=remote"></iframe>
<a class="open" href="/vnc.html?autoconnect=true&resize=remote"
target="_blank" rel="noopener noreferrer">Chrome 전체 화면 열기</a>
<button id="save" onclick="saveCurrent()">이 계정 저장</button>
<div class="controls">
<button id="add" onclick="send('add')">+ 다른 계정 추가</button>
<button id="done" onclick="send('done')">등록 마침 · GitHub 저장</button>
</div>
<p id="message" role="status"></p>
<aside><h2>저장된 계정 <span id="count">0</span>개</h2>
<ol id="accounts"><li>아직 등록된 계정이 없습니다.</li></ol></aside>
<p style="font-size:13px">별도의 Google 비밀번호 입력란은 없습니다.
인증정보는 실제 Google·ChatGPT 화면에만 입력해 주십시오.
로그인된 각 Chrome 프로필은 암호화되며, 등록 마침을 누르면 GitHub Actions에 저장됩니다.</p>
</main>
<script>
let busy=false,current=null,phase='';
async function refresh(){
 try{
  const response=await fetch('/status',{cache:'no-store',credentials:'same-origin'});
  if(!response.ok)throw Error('원격 Chrome 접속이 만료되었습니다');
  const d=await response.json();
  current=d.active;phase=d.phase;
  document.getElementById('count').textContent=d.accounts.length;
  const list=document.getElementById('accounts');
  list.replaceChildren();
  for(const account of d.accounts){
   const li=document.createElement('li');
   li.textContent='계정 '+account.id+' · '+account.email+' · 저장됨';
   list.appendChild(li);
  }
  if(!d.accounts.length){
   const li=document.createElement('li');
   li.textContent='아직 등록된 계정이 없습니다.';
   list.appendChild(li);
  }
  document.getElementById('state').textContent=d.completed?
   '등록 완료 · 계정 '+d.accounts.length+'개 암호화 저장':
   d.phase==='login'?'현재 새 계정 로그인 중 · '+d.active+'번째 계정':
   d.phase==='checking'?'실제 ChatGPT 계정을 확인 중입니다.':
   '계정 '+d.accounts.length+'개 저장됨 · 추가하거나 등록을 마칠 수 있습니다.';
  document.getElementById('save').disabled=busy||d.phase!=='login';
  document.getElementById('add').disabled=busy||d.phase!=='ready';
  document.getElementById('done').disabled=busy||!d.accounts.length||d.completed||d.phase==='checking';
  if(d.completed)document.getElementById('message').textContent=
   '완료되었습니다. GitHub Actions의 암호화 보관 단계로 넘어갑니다.';
 }catch(e){document.getElementById('message').textContent=e.message}
}
async function send(action){
 if(busy)return;
 busy=true;
 const msg=document.getElementById('message');
 msg.textContent=action==='save'?'실제 로그인 확인 후 암호화하고 있습니다…':
  action==='add'?'다음 계정용 Chrome을 여는 중입니다…':'GitHub 저장을 완료하는 중입니다…';
 try{
  const r=await fetch('/'+action,{method:'POST',credentials:'same-origin',
   headers:{'Content-Type':'application/json'},body:'{}'});
  const d=await r.json();
  if(!r.ok||!d.ok)throw Error(d.error||'작업을 완료하지 못했습니다');
  msg.textContent=action==='save'?'계정이 저장되었습니다. 추가할 계정이 있으면 + 다른 계정 추가를 누르십시오.':
  action==='add'?'새 Chrome에서 다음 계정으로 로그인하십시오.':
  '등록 완료. GitHub Actions가 암호화 프로필을 보관합니다.';
 }catch(e){msg.textContent='처리되지 않았습니다: '+e.message}
 finally{busy=false;await refresh()}
}
function saveCurrent(){send('save')}
setInterval(refresh,4000);refresh();
</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass  # Never record passwords, cookies, full URLs or remote user agents.

    def send(self, status, body=b"", headers=()):
        self.send_response(status)
        for k, v in (
            ("Content-Length", str(len(body))),
            ("Cache-Control", "private, no-store"),
            ("Referrer-Policy", "no-referrer"),
            ("X-Content-Type-Options", "nosniff"),
        ) + tuple(headers):
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def json(self, status, data):
        self.send(status, json.dumps(data).encode(),
                  (("Content-Type", "application/json; charset=utf-8"),))

    def authorized(self):
        try:
            cookies = SimpleCookie()
            cookies.load(self.headers.get("Cookie", ""))
            stored = cookies.get("w2a_session")
            return bool(stored and hmac.compare_digest(stored.value, SESSION))
        except Exception:
            return False

    def safe_origin(self):
        host = self.headers.get("Host", "")
        return (self.headers.get("Origin", "") == "https://" + host and
                re.fullmatch(r"[a-z0-9-]+\.trycloudflare\.com", host) is not None)

    def read_body(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
            return self.rfile.read(n) if 1 <= n <= 1024 else None
        except (ValueError, OSError):
            return None

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/health":
            self.send(200, b"ok")
        elif path == "/verify":
            self.send(200 if self.authorized() else 401)
        elif path == "/grant":
            if self.authorized():
                self.send(303, headers=(("Location", "/"),))
            else:
                self.send(200, LOGIN_HTML.encode(),
                          (("Content-Type", "text/html; charset=utf-8"),))
        elif not self.authorized():
            self.send(401, b"Protected Chrome login requires a private link.")
        elif path == "/":
            self.send(200, DASH_HTML.encode(),
                      (("Content-Type", "text/html; charset=utf-8"),))
        elif path == "/status":
            with LOCK:
                data = {"phase": STATE["phase"], "active": STATE["active"],
                        "completed": STATE["completed"],
                        "accounts": [{"id": x["id"], "email": mask(x["email"])}
                                     for x in ACCOUNTS]}
            self.json(200, data)
        else:
            self.send(404)

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        raw = self.read_body()
        if not raw:
            self.json(400, {"ok": False, "error": "INVALID_REQUEST"})
            return
        if path == "/grant":
            try:
                form = urllib.parse.parse_qs(raw.decode(), max_num_fields=3)
                entered = form.get("code", [""])[0]
                valid = (len(EXPECTED) == 64 and hmac.compare_digest(
                    hashlib.sha256(entered.encode()).hexdigest(), EXPECTED))
            except Exception:
                valid = False
            if not valid:
                self.send(403, b"Private access link is invalid or expired.")
                return
            self.send(303, headers=(
                ("Set-Cookie", "w2a_session=" + SESSION +
                 "; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age=3200"),
                ("Location", "/")))
            return
        if (path not in ("/save", "/add", "/done") or
                not self.authorized() or not self.safe_origin()):
            self.json(403, {"ok": False, "error": "NOT_AUTHORIZED"})
            return
        try:
            json.loads(raw)
        except (ValueError, TypeError):
            self.json(400, {"ok": False, "error": "INVALID_JSON"})
            return
        result = {"/save": save_current, "/add": add_account,
                  "/done": complete_registration}[path]()
        self.json(200 if result["ok"] else 409, result)


def main():
    if len(EXPECTED) != 64 or not CHROME_BINARY:
        raise SystemExit("MISSING_PRIVATE_BROWSER_ACCESS_VERIFIER")
    load_registry()
    start_chrome(len(ACCOUNTS) + 1)
    print("PASS_MULTI_ACCOUNT_LOGIN_MANAGER_STARTED", flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", 8899), Handler).serve_forever()


if __name__ == "__main__":
    main()
