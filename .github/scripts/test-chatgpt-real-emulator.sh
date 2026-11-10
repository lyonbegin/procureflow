#!/usr/bin/env bash
set -euo pipefail
mkdir -p emulator-evidence
log() { printf '%s\n' "$*" | tee -a emulator-evidence/verification.log; }
log "CHECKPOINT 1: genuine Android emulator boot"
adb devices -l | tee emulator-evidence/devices.txt
adb shell getprop ro.build.version.release | tr -d '\r' | tee emulator-evidence/android-version.txt
adb shell getprop sys.boot_completed | tr -d '\r' | tee emulator-evidence/boot.txt
test "$(cat emulator-evidence/boot.txt)" = "1" || { log "BLOCKED: emulator did not boot"; exit 31; }
log "CHECKPOINT 2: real relay APK installation"
RELAY=chatgpt-android-relay/web/static/ChatGPT-Relay-Control.apk
test -s "$RELAY" || { log "BLOCKED: relay APK missing from GitHub checkout"; exit 32; }
adb install -r "$RELAY" | tee emulator-evidence/relay-install.txt
adb shell pm path com.hitel.chatrelay | tee emulator-evidence/relay-package.txt
grep -q 'package:' emulator-evidence/relay-package.txt || { log "BLOCKED: relay package missing"; exit 33; }
log "CHECKPOINT 3: install genuine OpenAI-signed ChatGPT APK"
# Google Play account interaction is not scripted, and no test account login
# is fabricated. A downloaded APK is trusted ONLY after certificate pinning.
if [[ -n "${CHATGPT_TEST_APK_URL:-}" ]]; then
  URL="$CHATGPT_TEST_APK_URL"
  log "Official app source: supplied via GitHub Actions secret"
else
  URL="https://d.apkpure.com/b/XAPK/com.openai.chatgpt?version=latest"
  log "Official app source: APKPure public XAPK; signing certificate will be pinned"
fi
if ! curl --fail --location --retry 2 --connect-timeout 20 --max-time 240 \
  -o /tmp/chatgpt-download.pkg "$URL"; then
  log "BLOCKED_OFFICIAL_DOWNLOAD: could not obtain signed com.openai.chatgpt package"
  exit 34
fi
FILE_SIZE=$(stat -c%s /tmp/chatgpt-download.pkg)
log "Downloaded package size: $FILE_SIZE bytes"
if (( FILE_SIZE < 10000000 )); then
  log "BLOCKED_OFFICIAL_DOWNLOAD: suspiciously small download"
  exit 34
fi
mkdir -p /tmp/chatgpt-unpacked
if unzip -t /tmp/chatgpt-download.pkg >/dev/null 2>&1; then
  unzip -qq /tmp/chatgpt-download.pkg -d /tmp/chatgpt-unpacked
else
  cp /tmp/chatgpt-download.pkg /tmp/chatgpt-unpacked/base.apk
fi
mapfile -d '' APKS < <(find /tmp/chatgpt-unpacked -name '*.apk' -type f -print0)
if (("${#APKS[@]}" == 0)); then
  log "BLOCKED_OFFICIAL_BUNDLE: no APK found in source archive"
  exit 35
fi
APKSIGNER="$(find "$ANDROID_HOME/build-tools" -name apksigner -type f | sort -V | tail -1)"
AAPT="$(find "$ANDROID_HOME/build-tools" -name aapt -type f | sort -V | tail -1)"
EXPECTED_CERT="b24f4bfbb3cf293f938703b9d87027c1102cc36dc4fa206910e08927db40473c"
for APK in "${APKS[@]}"; do
  CERT=$("$APKSIGNER" verify --print-certs "$APK" 2>&1 |
    sed -n 's/^Signer #1 certificate SHA-256 digest: //p' | head -1)
  if [[ "$CERT" != "$EXPECTED_CERT" ]]; then
    log "BLOCKED_BAD_SIGNATURE: APK signer mismatch for $(basename "$APK")"
    exit 36
  fi
done
BASE=""
for APK in "${APKS[@]}"; do
  PKG=$("$AAPT" dump badging "$APK" 2>/dev/null | sed -n "s/^package: name='\([^']*\)'.*/\1/p" | head -1)
  if [[ "$PKG" == "com.openai.chatgpt" ]]; then BASE="$APK"; break; fi
done
if [[ -z "$BASE" ]]; then log "BLOCKED_WRONG_PACKAGE: no official com.openai.chatgpt base"; exit 37; fi
log "Validated signed official app: $(basename "$BASE")"
# Bundle splits can be in arbitrary filesystem order. Supply base first.
SPLITS=()
for APK in "${APKS[@]}"; do [[ "$APK" != "$BASE" ]] && SPLITS+=("$APK"); done
if (("${#SPLITS[@]}" > 0)); then
  adb install-multiple -r "$BASE" "${SPLITS[@]}" | tee emulator-evidence/chatgpt-install.txt
else
  adb install -r "$BASE" | tee emulator-evidence/chatgpt-install.txt
fi
adb shell pm path com.openai.chatgpt | tee emulator-evidence/chatgpt-package.txt
grep -q 'package:' emulator-evidence/chatgpt-package.txt || { log "BLOCKED: official ChatGPT not installed"; exit 38; }
log "CHECKPOINT 4: official ChatGPT ACTION_VIEW deep-link smoke test"
# This synthetic ID can only exercise app routing, never a user's real chat.
adb shell am start -a android.intent.action.VIEW \
  -d 'https://chatgpt.com/c/11111111-2222-3333-4444-555555555555' \
  -p com.openai.chatgpt | tee emulator-evidence/deeplink-activity.txt
sleep 8
adb shell dumpsys activity activities | grep -E 'mResumedActivity|topResumedActivity' |
  head -5 | tee emulator-evidence/foreground.txt || true
adb shell uiautomator dump /sdcard/window.xml >/dev/null || true
adb pull /sdcard/window.xml emulator-evidence/window.xml || true
adb shell screencap -p /sdcard/landing.png
adb pull /sdcard/landing.png emulator-evidence/landing.png
log "OFFICIAL_APP_INSTALLED: actual app launched; user chat auth not verified"
log "BLOCKED_AUTHENTICATED_CONVERSATIONS: cannot prove new-room ID capture, same-room send or switching until an actual signed-in ChatGPT session is available"
exit 43
