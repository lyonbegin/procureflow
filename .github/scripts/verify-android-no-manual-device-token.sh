#!/usr/bin/env bash
set -euo pipefail
mkdir -p android-tokenless-evidence
APK=chatgpt-android-relay/android/app/build/outputs/apk/debug/app-debug.apk
adb wait-for-device
adb shell getprop ro.product.cpu.abi | tr -d '\r' | tee android-tokenless-evidence/abi.txt
test "$(cat android-tokenless-evidence/abi.txt)" = "x86_64"
adb install -r "$APK" | tee android-tokenless-evidence/install.txt
grep -q Success android-tokenless-evidence/install.txt
adb shell am start -n com.hitel.chatrelay/.MainActivity | tee android-tokenless-evidence/start.txt
sleep 6
adb shell uiautomator dump /sdcard/relay-main-ui.xml
adb pull /sdcard/relay-main-ui.xml android-tokenless-evidence/ui.xml >/dev/null
grep -q '접근성 서비스 설정 열기' android-tokenless-evidence/ui.xml
if grep -Eq 'DEVICE_TOKEN|Android 전용 DEVICE_TOKEN|설정 저장 및 다시 연결|WebSocket 주소' android-tokenless-evidence/ui.xml; then
  echo FAIL_ANDROID_MANUAL_TOKEN_OR_URL_FIELD_VISIBLE | tee android-tokenless-evidence/result.txt
  exit 1
fi
# Prevent the CI emulator from authenticating to the PRODUCTION Railway relay:
# set a deliberately unreachable sandbox-only WSS endpoint before enabling
# the AccessibilityService. Nothing is changed in the published APK.
cat > /tmp/ci-safe-relay.xml <<'XML'
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
<string name="url">wss://relay-ci-sandbox.invalid/ws</string>
<string name="token">ci-ephemeral-token-not-production</string>
</map>
XML
adb shell am force-stop com.hitel.chatrelay
adb push /tmp/ci-safe-relay.xml /data/local/tmp/ci-safe-relay.xml >/dev/null
adb shell chmod 644 /data/local/tmp/ci-safe-relay.xml
adb shell run-as com.hitel.chatrelay mkdir -p shared_prefs
adb shell run-as com.hitel.chatrelay cp /data/local/tmp/ci-safe-relay.xml shared_prefs/relay.xml
adb shell rm /data/local/tmp/ci-safe-relay.xml
adb shell cmd appops set com.hitel.chatrelay ACCESS_RESTRICTED_SETTINGS allow
adb shell am start -n com.hitel.chatrelay/.MainActivity
BOUND=0
for attempt in 1 2 3 4 5; do
  adb shell cmd appops set com.hitel.chatrelay ACCESS_RESTRICTED_SETTINGS allow
  adb shell settings put secure enabled_accessibility_services com.hitel.chatrelay/.ChatRelayService
  adb shell settings put secure accessibility_enabled 1
  sleep 6
  adb shell dumpsys accessibility > android-tokenless-evidence/accessibility.txt
  if grep -Fq 'Bound services:{Service[label=ChatGPT Relay Control' android-tokenless-evidence/accessibility.txt; then
    BOUND=1
    break
  fi
done
adb shell screencap -p /sdcard/relay-tokenless.png
adb pull /sdcard/relay-tokenless.png android-tokenless-evidence/relay-tokenless.png >/dev/null
if [[ "$BOUND" != 1 ]]; then
  echo FAIL_ACCESSIBILITY_SERVICE_NOT_BOUND | tee android-tokenless-evidence/result.txt
  exit 1
fi
echo PASS_ANDROID_NO_MANUAL_DEVICE_TOKEN_OR_URL_AND_ACCESSIBILITY_BOUND | tee android-tokenless-evidence/result.txt
