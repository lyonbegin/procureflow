#!/usr/bin/env bash
set -euo pipefail
# Android 15 x86_64 real controller + ephemeral FastAPI host process.
# This deliberately does not use production Railway credentials or mock
# a signed-in ChatGPT conversation.
mkdir -p android-socket-evidence
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
  --host 0.0.0.0 --port 8765 > android-socket-evidence/server.log 2>&1 &
SERVER_PID=$!
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8765/health > android-socket-evidence/initial-health.json 2>/dev/null; then
    break
  fi
  sleep 1
done
curl -fsS http://127.0.0.1:8765/health > android-socket-evidence/initial-health.json
adb shell getprop ro.product.cpu.abi | tee android-socket-evidence/abi.txt
test "$(tr -d '\r' < android-socket-evidence/abi.txt)" = "x86_64"
adb install -r chatgpt-android-relay/android/app/build/outputs/apk/debug/app-debug.apk \
  | tee android-socket-evidence/install.txt
grep -q Success android-socket-evidence/install.txt

# Use Android run-as to configure ONLY the debuggable, isolated CI app.
# The test WebSocket targets the Android emulator's dedicated host gateway.
cat > android-socket-evidence/ci-relay-config.xml <<'XML'
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="url">ws://10.0.2.2:8765/ws</string>
    <string name="token">ci-only-android-device-token-20261111</string>
</map>
XML
adb shell am force-stop com.hitel.chatrelay
adb push android-socket-evidence/ci-relay-config.xml /data/local/tmp/ci-relay-config.xml >/dev/null
adb shell chmod 644 /data/local/tmp/ci-relay-config.xml
adb shell run-as com.hitel.chatrelay mkdir -p shared_prefs
adb shell run-as com.hitel.chatrelay cp /data/local/tmp/ci-relay-config.xml shared_prefs/relay.xml
adb shell run-as com.hitel.chatrelay ls -l shared_prefs/relay.xml \
  > android-socket-evidence/config-presence.txt
# Keep ephemeral CI credentials out of the published artifact.
rm android-socket-evidence/ci-relay-config.xml
adb shell rm /data/local/tmp/ci-relay-config.xml

adb shell am start -n com.hitel.chatrelay/.MainActivity \
  | tee android-socket-evidence/start.txt
adb shell cmd appops set com.hitel.chatrelay ACCESS_RESTRICTED_SETTINGS allow

BOUND=0
for attempt in 1 2 3 4 5; do
  adb shell cmd appops set com.hitel.chatrelay ACCESS_RESTRICTED_SETTINGS allow
  adb shell settings put secure enabled_accessibility_services "com.hitel.chatrelay/.ChatRelayService"
  adb shell settings put secure accessibility_enabled 1
  sleep 5
  adb shell dumpsys accessibility > android-socket-evidence/manager.txt
  if grep -Fq 'Bound services:{Service[label=ChatGPT Relay Control' android-socket-evidence/manager.txt; then
    BOUND=1
    echo "bound_attempt=$attempt" > android-socket-evidence/accessibility-result.txt
    break
  fi
done
test "$BOUND" = 1

ONLINE=0
for attempt in $(seq 1 45); do
  if python3 .github/scripts/relay-live-android-api.py online \
        > android-socket-evidence/socket-online.txt 2>/dev/null; then
    ONLINE=1
    break
  fi
  sleep 1
done
test "$ONLINE" = 1
ROOM_ID="$(python3 .github/scripts/relay-live-android-api.py init)"
JOB_TEXT="$(python3 .github/scripts/relay-live-android-api.py text "$ROOM_ID")"
python3 .github/scripts/relay-live-android-api.py assert-failed "$JOB_TEXT" \
  | tee android-socket-evidence/real-text-negative-result.json

# Multipart files are downloaded by the actual Android service over HTTP,
# staged under its private filesDir, and SHA-256 checked against the server.
FILE_META="$(python3 .github/scripts/relay-live-android-api.py files "$ROOM_ID")"
printf '%s\n' "$FILE_META" > android-socket-evidence/file-job-metadata.json
JOB_FILES="$(printf '%s' "$FILE_META" | python3 -c 'import json,sys;print(json.load(sys.stdin)["job_id"])')"
python3 .github/scripts/relay-live-android-api.py assert-failed "$JOB_FILES" \
  | tee android-socket-evidence/real-files-negative-result.json

python3 -c 'import json,sys; d=json.load(sys.stdin);[print(f["id"]+" "+f["name"]+" "+f["sha256"]) for f in d["files"]]' \
  < android-socket-evidence/file-job-metadata.json > android-socket-evidence/file-checks.txt
while read -r FID FNAME FSHA; do
  DEVICE_FILE="files/relay-attachments/$JOB_FILES/$FID/$FNAME"
  DEVICE_SHA="$(adb shell run-as com.hitel.chatrelay sha256sum "$DEVICE_FILE" | tr -d '\r' | awk '{print $1}')"
  printf '%s file=%s expected=%s actual=%s\n' "$FID" "$FNAME" "$FSHA" "$DEVICE_SHA" \
    | tee -a android-socket-evidence/verified-file-sha256.txt
  test "$DEVICE_SHA" = "$FSHA"
done < android-socket-evidence/file-checks.txt

adb shell dumpsys accessibility > android-socket-evidence/final-accessibility.txt
adb shell screencap -p /sdcard/relay-live-ws.png
adb pull /sdcard/relay-live-ws.png android-socket-evidence/controller-live-ws.png >/dev/null
adb logcat -d -v time -s HITELRelayLifecycle:I HITELRelayStatus:I '*:S' \
  > android-socket-evidence/lifecycle.log || true
adb logcat -d -t 1500 | grep -E 'FATAL EXCEPTION|AndroidRuntime|com.hitel.chatrelay' \
  > android-socket-evidence/android-runtime.log || true
if grep -q 'FATAL EXCEPTION' android-socket-evidence/android-runtime.log; then
  echo 'FAIL_ANDROID_RUNTIME_EXCEPTION' | tee android-socket-evidence/result.txt
  exit 1
fi
echo 'PASS_ACTUAL_ANDROID_WS_AUTH_JOB_DISPATCH_AND_FILE_SHA256' \
  | tee android-socket-evidence/result.txt
echo 'EXPECTED_FAILURE_OFFICIAL_CHATGPT_NOT_INSTALLED_IN_THIS_CI_TEST' \
  | tee -a android-socket-evidence/result.txt
echo 'NOT_TESTED_AUTHENTICATED_CHATGPT_SEND_OR_COMPOSER_ATTACHMENT' \
  | tee -a android-socket-evidence/result.txt
