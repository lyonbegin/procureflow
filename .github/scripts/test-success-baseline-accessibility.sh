#!/usr/bin/env bash
set -euo pipefail
mkdir -p original-baseline-evidence
adb wait-for-device
adb devices -l | tee original-baseline-evidence/devices.txt
adb shell getprop ro.product.cpu.abi | tr -d '\r' | tee original-baseline-evidence/abi.txt
test "$(cat original-baseline-evidence/abi.txt)" = "x86_64"
adb install -r chatgpt-android-relay/android/app/build/outputs/apk/debug/app-debug.apk | tee original-baseline-evidence/install.txt
grep -q Success original-baseline-evidence/install.txt
adb shell pm path com.hitel.chatrelay | tee original-baseline-evidence/package.txt
adb shell cmd appops set com.hitel.chatrelay ACCESS_RESTRICTED_SETTINGS allow
adb shell am start -n com.hitel.chatrelay/.MainActivity | tee original-baseline-evidence/start.txt
SERVICE='com.hitel.chatrelay/.ChatRelayService'
: > original-baseline-evidence/attempts.txt
BOUND=0
for attempt in 1 2 3 4 5; do
  adb shell cmd appops set com.hitel.chatrelay ACCESS_RESTRICTED_SETTINGS allow
  adb shell settings put secure enabled_accessibility_services "$SERVICE"
  adb shell settings put secure accessibility_enabled 1
  sleep 5
  adb shell dumpsys accessibility > original-baseline-evidence/accessibility.txt
  adb shell settings get secure enabled_accessibility_services | tr -d '\r' > original-baseline-evidence/enabled.txt
  grep -E 'Bound services|ChatGPT Relay Control|com.hitel.chatrelay' original-baseline-evidence/accessibility.txt | head -12 > original-baseline-evidence/summary.txt || true
  printf 'attempt=%s enabled=%s bound=' "$attempt" "$(cat original-baseline-evidence/enabled.txt)" | tee -a original-baseline-evidence/attempts.txt
  if grep -Fq 'Bound services:{Service[label=ChatGPT Relay Control' original-baseline-evidence/accessibility.txt; then
    BOUND=1; echo yes | tee -a original-baseline-evidence/attempts.txt; break
  fi
  echo no | tee -a original-baseline-evidence/attempts.txt
done
adb logcat -d -t 1000 > original-baseline-evidence/logcat.txt || true
adb shell screencap -p /sdcard/original-relay.png
adb pull /sdcard/original-relay.png original-baseline-evidence/original-relay.png
if [[ "$BOUND" != 1 ]]; then
  echo FAIL_BASELINE_ACCESSIBILITY_BIND | tee original-baseline-evidence/result.txt
  exit 1
fi
if grep -Fq 'FATAL EXCEPTION' original-baseline-evidence/logcat.txt; then
  echo FAIL_BASELINE_ANDROID_CRASH | tee original-baseline-evidence/result.txt
  exit 1
fi
echo PASS_ORIGINAL_RELAY_ACCESSIBILITY_BOUND_X86_64 | tee original-baseline-evidence/result.txt
echo NOT_TESTED_OFFICIAL_CHATGPT_SEND_REPLY_OR_FILE_ATTACH | tee -a original-baseline-evidence/result.txt
