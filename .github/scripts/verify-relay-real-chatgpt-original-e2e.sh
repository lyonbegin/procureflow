#!/usr/bin/env bash
set -euo pipefail
# Android 15 x86_64: actual ChatGPT 1.2026.300 (user's verified original)
# alongside the real AccessibilityService controller, both on one emulator.
# Do not use a production API token or claim a signed-in session exists.
mkdir -p real-chatgpt-evidence
export RELAY_DATA_DIR
RELAY_DATA_DIR="$(mktemp -d /tmp/relay-android-ws-XXXXXX)"
export CONSOLE_TOKEN="ci-only-console-token-20261111"
export DEVICE_TOKEN="ci-only-android-device-token-20261111"
export WEB_SESSION_SIGNING_KEY="ci-only-signing-key-longer-than-thirty-two-20261111"
SERVER_PID=""
cleanup() {
  if [[ -n "$SERVER_PID" ]]; then kill "$SERVER_PID" 2>/dev/null || true; fi
  rm -rf "$RELAY_DATA_DIR"
}
trap cleanup EXIT

python3 -m uvicorn app:app --app-dir chatgpt-android-relay/web \
  --host 0.0.0.0 --port 8765 > real-chatgpt-evidence/server.log 2>&1 &
SERVER_PID=$!
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8765/health > real-chatgpt-evidence/initial-health.json 2>/dev/null; then
    break
  fi
  sleep 1
done
curl -fsS http://127.0.0.1:8765/health > real-chatgpt-evidence/initial-health.json
adb shell getprop ro.product.cpu.abi | tee real-chatgpt-evidence/abi.txt
test "$(tr -d '\r' < real-chatgpt-evidence/abi.txt)" = "x86_64"
adb install -r chatgpt-android-relay/android/app/build/outputs/apk/debug/app-debug.apk \
  | tee real-chatgpt-evidence/install.txt
grep -q Success real-chatgpt-evidence/install.txt
# Install exact user-provided original APKM split set alongside the controller.
adb install-multiple -r \
  /tmp/chatgpt-original-splits/base.apk \
  /tmp/chatgpt-original-splits/split_config.x86_64.apk \
  /tmp/chatgpt-original-splits/split_config.xxhdpi.apk \
  /tmp/chatgpt-original-splits/split_config.en.apk \
  /tmp/chatgpt-original-splits/split_config.ko.apk \
  | tee real-chatgpt-evidence/install-original-chatgpt.txt
grep -q Success real-chatgpt-evidence/install-original-chatgpt.txt
adb shell pm path com.openai.chatgpt | tee real-chatgpt-evidence/original-package.txt
adb shell dumpsys package com.openai.chatgpt \
  | grep -E 'versionName=|versionCode=' | head -6 \
  | tee real-chatgpt-evidence/original-version.txt
grep -q 'versionName=1.2026.300' real-chatgpt-evidence/original-version.txt

# Android 15's emulator Pixel Launcher sometimes hangs and puts a system
# ANR modal over the genuine ChatGPT screen. Recover only after independently
# reading the EXACT system dialog/button from the device UI hierarchy.
# Never dismiss arbitrary app dialogs or tap unverified coordinates.
recover_emulator_frontend() {
  local phase="$1"
  for attempt in 1 2 3 4 5; do
    local xml="real-chatgpt-evidence/ui-recovery-$phase-$attempt.xml"
    timeout 30s adb shell uiautomator dump /sdcard/relay-recovery.xml >/dev/null 2>&1 || true
    adb pull /sdcard/relay-recovery.xml "$xml" >/dev/null 2>&1 || true
    [[ -f "$xml" ]] || break
    local decision
    decision="$(python3 - "$xml" <<'PY'
import sys,re,xml.etree.ElementTree as ET
try:
  nodes=list(ET.parse(sys.argv[1]).iter('node'))
except (ET.ParseError,OSError):
  nodes=[]
labels=[n.attrib.get('text','') or n.attrib.get('content-desc','') for n in nodes]
def center(n):
  m=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',n.attrib.get('bounds',''))
  if m:
    a,b,c,d=map(int,m.groups())
    return ((a+c)//2,(b+d)//2)
def find(label):
  for n in nodes:
    if label in (n.attrib.get('text',''),n.attrib.get('content-desc','')):
      if center(n):return center(n)
if any('Pixel Launcher isn' in x and 'responding' in x for x in labels):
  coords=find('Close app')
  if coords:print('launcher_anr',*coords)
elif any('Welcome to ChatGPT' in x for x in labels):
  coords=find('Continue')
  if coords:print('welcome_continue',*coords)
elif any(x=='Skip' for x in labels):
  coords=find('Skip')
  if coords:print('guest_skip',*coords)
PY
    )"
    if [[ -z "$decision" ]]; then break; fi
    read -r kind x y <<< "$decision"
    printf 'phase=%s attempt=%s action=%s x=%s y=%s\n' \
      "$phase" "$attempt" "$kind" "$x" "$y" \
      | tee -a real-chatgpt-evidence/ui-recovery-actions.txt
    adb shell input tap "$x" "$y"
    sleep 4
    if [[ "$kind" == launcher_anr ]]; then
      adb shell monkey -p com.openai.chatgpt -c android.intent.category.LAUNCHER 1 \
        > /dev/null || true
      sleep 6
    fi
  done
}

# The original app's first-run Welcome screen exposes a native "Skip" action.
# Exercise that real UI instead of incorrectly classifying onboarding as an
# absent New Chat control. Perform this BEFORE enabling AccessibilityService,
# because uiautomator dumps may cause service lifecycle churn on Android 15.
GUEST_SKIP=0
for onboard_attempt in 1 2 3; do
  adb shell monkey -p com.openai.chatgpt -c android.intent.category.LAUNCHER 1 \
    > real-chatgpt-evidence/onboarding-launch.txt || true
  sleep 12
  timeout 35s adb shell uiautomator dump /sdcard/chatgpt-first-run.xml >/dev/null 2>&1 || true
  adb pull /sdcard/chatgpt-first-run.xml real-chatgpt-evidence/chatgpt-first-run.xml >/dev/null 2>&1 || true
  if [[ -f real-chatgpt-evidence/chatgpt-first-run.xml ]]; then
    CENTER="$(python3 - <<'PY'
from pathlib import Path
import re
import xml.etree.ElementTree as ET
path=Path('real-chatgpt-evidence/chatgpt-first-run.xml')
try:
  tree=ET.parse(path)
  for n in tree.iter('node'):
    if n.attrib.get('text')=='Skip' or n.attrib.get('content-desc')=='Skip':
      m=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',n.attrib.get('bounds',''))
      if m:
        x1,y1,x2,y2=map(int,m.groups())
        print((x1+x2)//2,(y1+y2)//2)
        break
except (ET.ParseError,OSError):
  pass
PY
    )"
    if [[ -n "$CENTER" ]]; then
      read -r SX SY <<< "$CENTER"
      adb shell input tap "$SX" "$SY"
      GUEST_SKIP=1
      echo "OFFICIAL_FIRST_RUN_SKIP_CLICKED attempt=$onboard_attempt x=$SX y=$SY" \
        | tee real-chatgpt-evidence/guest-onboarding-result.txt
      sleep 14
      break
    fi
  fi
done
if [[ "$GUEST_SKIP" -ne 1 ]]; then
  echo 'OFFICIAL_FIRST_RUN_SKIP_NOT_FOUND' \
    | tee real-chatgpt-evidence/guest-onboarding-result.txt
fi
adb shell screencap -p /sdcard/chatgpt-after-official-skip.png
adb pull /sdcard/chatgpt-after-official-skip.png \
  real-chatgpt-evidence/chatgpt-after-official-skip.png >/dev/null
# A separate CI run already verified a direct guest prompt and genuine
# assistant reply ("42"). Do NOT send another prompt before this controller
# E2E run: it changes the guest home into an existing conversation and can
# invalidate the very first-chat room isolation this test is meant to prove.
echo 'DIRECT_GUEST_PROBE_SKIPPED_TO_PRESERVE_EMPTY_CHAT_FOR_RELAY' \
  | tee real-chatgpt-evidence/guest-direct-console.txt

recover_emulator_frontend "before-controller"

# Use Android run-as to configure ONLY the debuggable, isolated CI app.
# The test WebSocket targets the Android emulator's dedicated host gateway.
cat > real-chatgpt-evidence/ci-relay-config.xml <<'XML'
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="url">ws://10.0.2.2:8765/ws</string>
    <string name="token">ci-only-android-device-token-20261111</string>
</map>
XML
adb shell am force-stop com.hitel.chatrelay
adb push real-chatgpt-evidence/ci-relay-config.xml /data/local/tmp/ci-relay-config.xml >/dev/null
adb shell chmod 644 /data/local/tmp/ci-relay-config.xml
adb shell run-as com.hitel.chatrelay mkdir -p shared_prefs
adb shell run-as com.hitel.chatrelay cp /data/local/tmp/ci-relay-config.xml shared_prefs/relay.xml
adb shell run-as com.hitel.chatrelay ls -l shared_prefs/relay.xml \
  > real-chatgpt-evidence/config-presence.txt
# Keep ephemeral CI credentials out of the published artifact.
rm real-chatgpt-evidence/ci-relay-config.xml
adb shell rm /data/local/tmp/ci-relay-config.xml

adb shell am start -n com.hitel.chatrelay/.MainActivity \
  | tee real-chatgpt-evidence/start.txt
# Match the previously successful controller smoke test: Android 15 may
# revert secure accessibility settings before its manager is initialized.
sleep 10
EXISTING="$(adb shell settings get secure enabled_accessibility_services | tr -d '\r')"
[[ "$EXISTING" == "null" ]] && EXISTING=""
SERVICE='com.hitel.chatrelay/.ChatRelayService'
case ":$EXISTING:" in
  *":$SERVICE:"*) UPDATED="$EXISTING" ;;
  "::") UPDATED="$SERVICE" ;;
  *) UPDATED="$EXISTING:$SERVICE" ;;
esac
BOUND=0
: > real-chatgpt-evidence/accessibility-attempts.txt
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  adb shell cmd appops set com.hitel.chatrelay ACCESS_RESTRICTED_SETTINGS allow
  adb shell settings put secure enabled_accessibility_services "$UPDATED"
  adb shell settings put secure accessibility_enabled 1
  sleep 7
  ACTUAL="$(adb shell settings get secure enabled_accessibility_services | tr -d '\r')"
  adb shell dumpsys accessibility > real-chatgpt-evidence/manager.txt
  BOUND_NOW=no
  if grep -Fq 'Bound services:{Service[label=ChatGPT Relay Control' real-chatgpt-evidence/manager.txt; then
    BOUND_NOW=yes
  fi
  printf 'attempt=%d secure_enabled=%s manager_bound=%s\n' "$attempt" "$ACTUAL" "$BOUND_NOW" \
    | tee -a real-chatgpt-evidence/accessibility-attempts.txt
  if [[ "$ACTUAL" == *"com.hitel.chatrelay"* && "$BOUND_NOW" == yes ]]; then
    BOUND=1
    echo "bound_attempt=$attempt" > real-chatgpt-evidence/accessibility-result.txt
    break
  fi
done
adb shell cmd appops get com.hitel.chatrelay ACCESS_RESTRICTED_SETTINGS \
  > real-chatgpt-evidence/final-restricted-appop.txt
adb shell settings get secure enabled_accessibility_services \
  > real-chatgpt-evidence/final-secure-enabled.txt
if [[ "$BOUND" != 1 ]]; then
  adb logcat -d -v time -s AccessibilityManagerService:I HITELRelayLifecycle:I AndroidRuntime:E '*:S' \
    > real-chatgpt-evidence/accessibility-failure.log || true
  echo 'FAIL_ACCESSIBILITY_SERVICE_DID_NOT_BIND' | tee real-chatgpt-evidence/result.txt
  exit 1
fi

# Do not assume monkey's "Events injected: 1" proves the official app
# is foreground: previous evidence had com.hitel.chatrelay still resumed.
# Require the actual Android ActivityManager to report com.openai.chatgpt.
OFFICIAL_FOREGROUND=0
: > real-chatgpt-evidence/official-foreground-retries.txt
for launch_attempt in 1 2 3 4 5; do
  # The package-only MAIN/LAUNCHER command is not resolved on this
  # emulator despite an installed official app. This exact Activity was
  # independently observed in the earlier guest-screen evidence.
  adb shell am start -W -n com.openai.chatgpt/.MainActivity \
    > real-chatgpt-evidence/original-chatgpt-launch.txt 2>&1 || true
  sleep 5
  adb shell dumpsys activity activities \
    | grep -E 'topResumedActivity|mResumedActivity' | head -4 \
    > real-chatgpt-evidence/original-foreground-before-jobs.txt || true
  printf 'attempt=%d foreground=%s\n' "$launch_attempt" \
    "$(tr '\n' ' ' < real-chatgpt-evidence/original-foreground-before-jobs.txt)" \
    | tee -a real-chatgpt-evidence/official-foreground-retries.txt
  if grep -q 'topResumedActivity=.*com.openai.chatgpt/' \
      real-chatgpt-evidence/original-foreground-before-jobs.txt; then
    OFFICIAL_FOREGROUND=1
    break
  fi
done
if [[ "$OFFICIAL_FOREGROUND" != 1 ]]; then
  echo 'FAIL_OFFICIAL_CHATGPT_NOT_FOREGROUND' \
    | tee real-chatgpt-evidence/foreground-result.txt
  adb shell screencap -p /sdcard/real-chatgpt-not-foreground.png
  adb pull /sdcard/real-chatgpt-not-foreground.png \
    real-chatgpt-evidence/real-chatgpt-not-foreground.png >/dev/null
  exit 1
fi
echo 'PASS_OFFICIAL_CHATGPT_FOREGROUND_BEFORE_JOBS' \
  | tee real-chatgpt-evidence/foreground-result.txt
adb shell screencap -p /sdcard/real-chatgpt-before.png
adb pull /sdcard/real-chatgpt-before.png real-chatgpt-evidence/real-chatgpt-before.png >/dev/null
# NEVER invoke uiautomator after the AccessibilityService is bound:
# on this Android 15 emulator the dump itself brings the controller Activity
# to foreground and can destroy the service. Use a non-invasive screenshot.
adb shell screencap -p /sdcard/real-chatgpt-ready.png
adb pull /sdcard/real-chatgpt-ready.png real-chatgpt-evidence/real-chatgpt-ready.png >/dev/null

ONLINE=0
for attempt in $(seq 1 45); do
  if python3 .github/scripts/relay-live-android-api.py online \
        > real-chatgpt-evidence/socket-online.txt 2>/dev/null; then
    ONLINE=1
    break
  fi
  sleep 1
done
test "$ONLINE" = 1
ROOM_ID="$(python3 .github/scripts/relay-live-android-api.py init)"
JOB_TEXT="$(python3 .github/scripts/relay-live-android-api.py text "$ROOM_ID")"
python3 .github/scripts/relay-live-android-api.py observe "$JOB_TEXT" \
  | tee real-chatgpt-evidence/actual-text-job.json
adb shell screencap -p /sdcard/real-chatgpt-after-text.png
adb pull /sdcard/real-chatgpt-after-text.png real-chatgpt-evidence/real-chatgpt-after-text.png >/dev/null

# Multipart files are downloaded by the actual Android service over HTTP,
# staged under its private filesDir, and SHA-256 checked against the server.
FILE_META="$(python3 .github/scripts/relay-live-android-api.py files "$ROOM_ID")"
printf '%s\n' "$FILE_META" > real-chatgpt-evidence/file-job-metadata.json
JOB_FILES="$(printf '%s' "$FILE_META" | python3 -c 'import json,sys;print(json.load(sys.stdin)["job_id"])')"
python3 .github/scripts/relay-live-android-api.py observe "$JOB_FILES" \
  | tee real-chatgpt-evidence/actual-file-attachment-job.json
adb shell screencap -p /sdcard/real-chatgpt-after-attachments.png
adb pull /sdcard/real-chatgpt-after-attachments.png real-chatgpt-evidence/real-chatgpt-after-attachments.png >/dev/null

python3 -c 'import json,sys; d=json.load(sys.stdin);[print(f["id"]+" "+f["name"]+" "+f["sha256"]) for f in d["files"]]' \
  < real-chatgpt-evidence/file-job-metadata.json > real-chatgpt-evidence/file-checks.txt
VERIFY_COUNT=0
while read -r FID FNAME FSHA; do
  DEVICE_FILE="files/relay-attachments/$JOB_FILES/$FID/$FNAME"
  # adb shell reads stdin by default; without /dev/null it steals the next
  # record from the while-read input stream and silently skips documents.
  DEVICE_SHA="$(adb shell run-as com.hitel.chatrelay sha256sum "$DEVICE_FILE" </dev/null | tr -d '\r' | awk '{print $1}')"
  printf '%s file=%s expected=%s actual=%s\n' "$FID" "$FNAME" "$FSHA" "$DEVICE_SHA" \
    | tee -a real-chatgpt-evidence/verified-file-sha256.txt
  test "$DEVICE_SHA" = "$FSHA"
  VERIFY_COUNT=$((VERIFY_COUNT+1))
done < real-chatgpt-evidence/file-checks.txt
# Both independently supplied original files MUST be checked on Android.
test "$VERIFY_COUNT" -eq 2
test "$(wc -l < real-chatgpt-evidence/verified-file-sha256.txt)" -eq 2

adb shell dumpsys accessibility > real-chatgpt-evidence/final-accessibility.txt
adb shell screencap -p /sdcard/relay-live-ws.png
adb pull /sdcard/relay-live-ws.png real-chatgpt-evidence/controller-live-ws.png >/dev/null
adb logcat -d -v time -s HITELRelayLifecycle:I HITELRelayStatus:I '*:S' \
  > real-chatgpt-evidence/lifecycle.log || true
adb logcat -d -t 1500 | grep -E 'FATAL EXCEPTION|AndroidRuntime|com.hitel.chatrelay' \
  > real-chatgpt-evidence/android-runtime.log || true
if grep -q 'FATAL EXCEPTION' real-chatgpt-evidence/android-runtime.log; then
  echo 'FAIL_ANDROID_RUNTIME_EXCEPTION' | tee real-chatgpt-evidence/result.txt
  exit 1
fi
# Also retain the official app's final UI hierarchy and accessibility logs,
# after controller-side result reporting (uiautomator may change lifecycle).
timeout 30s adb shell uiautomator dump /sdcard/real-chatgpt-end.xml > /dev/null 2>&1 || true
adb pull /sdcard/real-chatgpt-end.xml real-chatgpt-evidence/real-chatgpt-end.xml >/dev/null 2>&1 || true
adb logcat -d -v time -s HITELRelayLifecycle:I HITELRelayStatus:I AndroidRuntime:E '*:S' \
  > real-chatgpt-evidence/real-runtime.log || true
python3 - <<'PY'
import json
from pathlib import Path
folder=Path('real-chatgpt-evidence')
text=json.loads((folder/'actual-text-job.json').read_text())
file=json.loads((folder/'actual-file-attachment-job.json').read_text())
report={
    'original_app_version':'1.2026.300',
    'real_android_transport_verified': True,
    'direct_official_guest_reply_verified':
        'PASS_DIRECT_OFFICIAL_GUEST_TEXT_SEND_AND_REPLY_42' in
        (folder/'guest-direct-result.txt').read_text()
        if (folder/'guest-direct-result.txt').exists() else False,
    'real_text_job':text,
    'real_file_attachment_job':file,
    'text_send_answer_verified': text['status']=='completed'
        and text.get('stage')=='assistant_reply_stable'
        and bool(text.get('result_text')),
    'file_attachment_answer_verified': file['status']=='completed'
        and file.get('stage')=='assistant_reply_stable'
        and bool(file.get('result_text')),
    'private_original_file_hashes_verified':True
}
report['full_real_app_e2e_success']=report['text_send_answer_verified'] and report['file_attachment_answer_verified']
(folder/'official-e2e-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
if not report['full_real_app_e2e_success']:
    print('FAIL_REAL_CHATGPT_SEND_ANSWER_OR_COMPOSER_ATTACHMENT_UNVERIFIED')
    raise SystemExit(2)
print('PASS_REAL_CHATGPT_SEND_REPLY_AND_ATTACHMENT_VERIFIED')
PY
