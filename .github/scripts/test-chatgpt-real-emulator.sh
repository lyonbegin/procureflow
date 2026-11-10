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
# Require the exact user-supplied 1.2026.300 variant. Never silently
# download a different 'latest' APK or mark it as equivalent.
EXPECTED_FILE_SHA256="695598014d4db8ef284a7171bf9f6382fff5629aba2c9960b710d539b4fe2b44"
if [[ -n "${CHATGPT_TEST_APK_LOCAL:-}" && -s "${CHATGPT_TEST_APK_LOCAL}" ]]; then
  cp "${CHATGPT_TEST_APK_LOCAL}" /tmp/chatgpt-download.pkg
  log "Official app source: local user-supplied .apkm"
elif [[ -n "${CHATGPT_TEST_APK_URL:-}" ]]; then
  log "Official app source: GitHub Actions secret download URL"
  if ! curl --fail --location --retry 2 --connect-timeout 20 --max-time 240 \
    -o /tmp/chatgpt-download.pkg "${CHATGPT_TEST_APK_URL}"; then
    log "BLOCKED_OFFICIAL_DOWNLOAD: requested user .apkm not downloaded"
    exit 34
  fi
else
  log "BLOCKED_APKM_TRANSFER: user .apkm is present only in ChatGPT sandbox; not accessible to this GitHub runner"
  exit 34
fi
ACTUAL_SHA256="$(sha256sum /tmp/chatgpt-download.pkg | cut -d' ' -f1)"
if [[ "$ACTUAL_SHA256" == "$EXPECTED_FILE_SHA256" ]]; then
  log "Exact user-provided APKM archive verified by SHA-256"
elif python3 .github/scripts/check-chatgpt-variant.py /tmp/chatgpt-download.pkg; then
  log "The same five signed APK splits were verified byte-for-byte against user-supplied APKM"
else
  log "BLOCKED_APKM_SHA256_MISMATCH: neither original archive nor its five signed splits match"
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
BASE="/tmp/chatgpt-unpacked/base.apk"
test -s "$BASE" || { log "BLOCKED_NO_BASE_APK"; exit 37; }
APP_PKG=$("$AAPT" dump badging "$BASE" | sed -n "s/^package: name='\\([^']*\\)'.*/\\1/p" | head -1)
APP_VERSION=$("$AAPT" dump badging "$BASE" | sed -n "s/^package:.* versionName='\\([^']*\\)'.*/\\1/p" | head -1)
if [[ "$APP_PKG" != "com.openai.chatgpt" || "$APP_VERSION" != "1.2026.300" ]]; then
  log "BLOCKED_WRONG_PACKAGE_OR_VERSION: $APP_PKG $APP_VERSION"
  exit 37
fi
EMULATOR_ABI="$(adb shell getprop ro.product.cpu.abi | tr -d '\\r')"
test "$EMULATOR_ABI" = "x86_64" || { log "BLOCKED_WRONG_EMULATOR_ABI: $EMULATOR_ABI"; exit 38; }
SPLITS=()
for split in split_config.x86_64.apk split_config.xxhdpi.apk split_config.ko.apk split_config.en.apk; do
  test -s "/tmp/chatgpt-unpacked/$split" || { log "BLOCKED_MISSING_SPLIT: $split"; exit 38; }
  SPLITS+=("/tmp/chatgpt-unpacked/$split")
done
log "Verified exact x86_64, XXHDPI, Korean and English splits"
adb install-multiple -r "$BASE" "${SPLITS[@]}" | tee emulator-evidence/chatgpt-install.txt
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
