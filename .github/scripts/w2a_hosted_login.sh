#!/usr/bin/env bash
# GitHub-hosted Ubuntu only. No token or profile is ever copied to the public repository.
set -Eeuo pipefail
ROOT="$RUNNER_TEMP/chatgpt-w2a"
PROFILE="$ROOT/chrome-profile"
ARCHIVE="$ROOT/encrypted-profile"
mkdir -p "$ROOT" "$PROFILE" "$ARCHIVE"
chmod 700 "$ROOT" "$PROFILE" "$ARCHIVE"
MODE="$1"
export W2A_MODE="$MODE"
if [ "$MODE" != "login" ] && [ "$MODE" != "verify" ] && [ "$MODE" != "smoke" ]; then
  echo "INVALID_MODE"; exit 2
fi

python3 - <<'PY'
import os
a=os.environ.get('W2A_LOGIN_PASSWORD','')
b=os.environ.get('W2A_PROFILE_KEY','')
if len(a)<24 or len(b)<32 or a==b:
    raise SystemExit('MISSING_PRIVATE_GITHUB_ACTIONS_SECRETS: Set W2A_LOGIN_PASSWORD (>=24 chars) and a different W2A_PROFILE_KEY (>=32 chars) in Settings > Secrets and variables > Actions. No browser session launched.')
print('PASS_PRIVATE_SECRETS_CONFIGURED_NO_SECRET_VALUES_PRINTED')
PY

# Restore previously encrypted browser session, if any.
if [ "$MODE" != "smoke" ] && [ -n "$GH_TOKEN" ]; then
  export GH_PROMPT_DISABLED=1
  PREVIOUS_RUN="$(gh api "repos/$GITHUB_REPOSITORY/actions/artifacts?name=chatgpt-web2api-encrypted-profile&per_page=50" --jq '.artifacts | map(select(.expired==false)) | .[0].workflow_run.id // ""' || true)"
  if [ -n "$PREVIOUS_RUN" ]; then
    mkdir -p "$ROOT/restore"
    if gh run download "$PREVIOUS_RUN" --repo "$GITHUB_REPOSITORY" --name chatgpt-web2api-encrypted-profile --dir "$ROOT/restore" >/dev/null 2>&1; then
      if [ -s "$ROOT/restore/chrome-profile.tar.gz.gpg" ]; then
        gpg --batch --yes --pinentry-mode loopback --passphrase-fd 3 \
          --decrypt -o "$ROOT/restored-profile.tar.gz" \
          "$ROOT/restore/chrome-profile.tar.gz.gpg" 3<<<"$W2A_PROFILE_KEY"
        tar -xzf "$ROOT/restored-profile.tar.gz" -C "$ROOT"
        rm -f "$ROOT/restored-profile.tar.gz"
        echo "PASS_ENCRYPTED_CHROME_PROFILE_RESTORED"
      fi
    fi
  else
    echo "NO_PREVIOUS_SESSION_FOUND_FIRST_LOGIN_REQUIRED"
  fi
fi

# All Chrome debugging and VNC backend ports are loopback ONLY.
Xvfb :99 -screen 0 1440x900x24 -nolisten tcp >"$ROOT/xvfb.log" 2>&1 &
echo $! > "$ROOT/xvfb.pid"
export DISPLAY=:99
sleep 2
"$CHROME_BINARY" --no-sandbox --disable-dev-shm-usage \
  --password-store=basic --no-first-run --no-default-browser-check \
  --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 \
  --user-data-dir="$PROFILE" https://chatgpt.com/ \
  >"$ROOT/chrome.log" 2>&1 &
echo $! > "$ROOT/chrome.pid"
python3 - <<'PY'
import json,time,urllib.request
for _ in range(60):
  try:
    with urllib.request.urlopen('http://127.0.0.1:9222/json/version',timeout=2) as r:
      j=json.load(r)
    assert j['Browser'].startswith('Chrome/')
    print('PASS_GITHUB_HOSTED_CHROME_CDP_RUNNING')
    break
  except Exception:
    time.sleep(1)
else:
  raise SystemExit('CHROME_CDP_FAILED')
PY

# Existing, pinned Web-to-API code; no own endpoint is publicly exposed.
git clone --quiet https://github.com/MartinezS8/chatgpt-web2api.git "$ROOT/web2api"
git -C "$ROOT/web2api" checkout --quiet 497527dceabfa3f95961e23c291e618c5570f1ac
python3 -m pip install -q "$ROOT/web2api"
DISPLAY=:99 chatgpt-web2api --port 18080 --cdp-port 9222 \
  > "$ROOT/web2api.log" 2>&1 &
echo $! > "$ROOT/web2api.pid"
echo "PASS_WEB2API_LAUNCHED_LOCALHOST_ONLY"

if [ "$MODE" = "login" ] || [ "$MODE" = "smoke" ]; then
  # Access to the live browser is protected by nginx HTTP Basic Auth
  # with a user-configured GitHub Action Secret. The VNC service is localhost only.
  x11vnc -display :99 -localhost -rfbport 5900 -forever \
    -shared -nopw -quiet >"$ROOT/x11vnc.log" 2>&1 &
  echo $! > "$ROOT/x11vnc.pid"
  websockify --web /usr/share/novnc 127.0.0.1:6080 127.0.0.1:5900 \
    >"$ROOT/novnc.log" 2>&1 &
  echo $! > "$ROOT/novnc.pid"
  htpasswd -nbB operator "$W2A_LOGIN_PASSWORD" > /tmp/w2a-login-htpasswd
  chmod 600 /tmp/w2a-login-htpasswd
  cat > "$ROOT/nginx.conf" <<'NGINX'
worker_processes 1;
error_log /dev/stderr warn;
pid /tmp/w2a-login-nginx.pid;
events { worker_connections 512; }
http {
  access_log off;
  server {
    listen 127.0.0.1:8088;
    server_tokens off;
    location / {
      auth_basic "Private GitHub-hosted ChatGPT browser";
      auth_basic_user_file /tmp/w2a-login-htpasswd;
      proxy_pass http://127.0.0.1:6080;
      proxy_http_version 1.1;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection "upgrade";
      proxy_read_timeout 1800s;
      proxy_send_timeout 1800s;
      proxy_buffering off;
    }
  }
}
NGINX
  nginx -t -c "$ROOT/nginx.conf"
  nginx -c "$ROOT/nginx.conf" -g "daemon off;" >"$ROOT/nginx.log" 2>&1 &
  echo $! > "$ROOT/nginx.pid"
  python3 - <<'PY'
import urllib.request,urllib.error,os,base64,time
url='http://127.0.0.1:8088/vnc.html'
for attempt in range(25):
  try:
    urllib.request.urlopen(url,timeout=2)
    raise SystemExit('SECURITY_FAILURE_REMOTE_DESKTOP_NOT_PASSWORD_PROTECTED')
  except urllib.error.HTTPError as e:
    if e.code==401: break
    raise
  except Exception:
    time.sleep(1)
else:
  raise SystemExit('NO_NGINX_401')
raw=('operator:'+os.environ['W2A_LOGIN_PASSWORD']).encode()
req=urllib.request.Request(url,headers={
    'Authorization':'Basic '+base64.b64encode(raw).decode()
})
for attempt in range(40):
  try:
    with urllib.request.urlopen(req,timeout=3) as response:
      assert response.status==200
      assert b'noVNC' in response.read(100000)
    break
  except urllib.error.HTTPError as exc:
    if exc.code not in (502,503,504):
      raise
    time.sleep(1)
  except (urllib.error.URLError,TimeoutError):
    time.sleep(1)
else:
  raise SystemExit('NOVNC_BACKEND_STILL_UNAVAILABLE_AFTER_40_SECONDS')
print('PASS_REMOTE_CHROME_PASSWORD_GATE_401_UNAUTHORIZED_200_AUTHORIZED')
PY
  curl -fsSL --retry 3 \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    -o "$ROOT/cloudflared"
  chmod 700 "$ROOT/cloudflared"
  "$ROOT/cloudflared" tunnel --no-autoupdate \
    --url http://127.0.0.1:8088 >"$ROOT/tunnel.log" 2>&1 &
  echo $! > "$ROOT/tunnel.pid"
  python3 - <<'PY'
import re,os,time
path=os.environ['RUNNER_TEMP']+'/chatgpt-w2a/tunnel.log'
url=None
for attempt in range(90):
  if os.path.exists(path):
    data=open(path,encoding='utf-8',errors='replace').read()
    hits=re.findall(r'https://[a-z0-9-]+[.]trycloudflare[.]com',data)
    if hits: url=hits[-1]; break
  time.sleep(1)
if not url: raise SystemExit('CLOUDFLARE_TUNNEL_NOT_READY')
if os.environ.get('W2A_MODE')=='smoke':
  print('PASS_ENCRYPTED_TUNNEL_URL_RESOLVED_NO_REMOTE_LOGIN_URL_EXPOSED')
else:
  print('REMOTE_LOGIN_LINK='+url+'/vnc.html?autoconnect=true&resize=remote')
print('REMOTE_LOGIN_USERNAME=operator')
print('REMOTE_LOGIN_PASSWORD=the W2A_LOGIN_PASSWORD repository Action secret (never printed)')
print('LOGIN_INSTRUCTIONS=Use Google account on chatgpt.com in this remote Chrome window. The window closes at the end of this run.')
PY

  # An active GitHub-hosted job is deliberately kept alive for supervised login.
  # Session is NOT assumed valid until the user has actually logged in.
  if [ "$MODE" = "login" ]; then sleep 1200; fi
fi

python3 - <<'PY'
import json,urllib.request
try:
  with urllib.request.urlopen('http://127.0.0.1:18080/health',timeout=4) as r:
    data=json.load(r)
  safe={k:data.get(k) for k in ('status','chrome_status','driver_status') if k in data}
  print('WEB2API_HEALTH_SUMMARY='+json.dumps(safe))
except Exception as exc:
  print('WEB2API_HEALTH_UNAVAILABLE='+type(exc).__name__)
print('GOOGLE_LOGIN_NOT_CLAIMED_WITHOUT_VALID_SESSION_EVIDENCE')
PY

if [ "$MODE" = "login" ] || [ "$MODE" = "smoke" ]; then
  # Close Chrome cleanly before archiving its database files.
  kill "$(cat "$ROOT/web2api.pid")" 2>/dev/null || true
  kill "$(cat "$ROOT/chrome.pid")" 2>/dev/null || true
  sleep 4
  tar -C "$ROOT" --exclude='*/Cache/*' --exclude='*/Code Cache/*' \
    --exclude='Singleton*' --exclude='*/Singleton*' \
    -czf "$ROOT/chrome-profile.tar.gz" chrome-profile
  gpg --batch --yes --pinentry-mode loopback --passphrase-fd 3 \
    --cipher-algo AES256 --symmetric \
    -o "$ARCHIVE/chrome-profile.tar.gz.gpg" "$ROOT/chrome-profile.tar.gz" \
    3<<<"$W2A_PROFILE_KEY"
  rm -f "$ROOT/chrome-profile.tar.gz"
  test -s "$ARCHIVE/chrome-profile.tar.gz.gpg"
  if [ "$MODE" = "smoke" ]; then
    gpg --batch --yes --pinentry-mode loopback --passphrase-fd 3 --decrypt -o /dev/null "$ARCHIVE/chrome-profile.tar.gz.gpg" 3<<<"$W2A_PROFILE_KEY"
    echo "PASS_SMOKE_GPG_ENCRYPTION_AND_DECRYPTION"
    rm -f "$ARCHIVE/chrome-profile.tar.gz.gpg"
  fi
  echo "PASS_ONLY_ENCRYPTED_PROFILE_READY_FOR_UPLOAD"
  echo "PROFILE_ENCRYPTION_KEY_NEVER_LOGGED"
fi
