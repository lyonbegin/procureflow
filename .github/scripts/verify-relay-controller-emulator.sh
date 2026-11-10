#!/usr/bin/env bash
set -euo pipefail
mkdir -p controller-evidence
adb devices -l | tee controller-evidence/adb-devices.txt
adb shell getprop sys.boot_completed | tee controller-evidence/boot-completed.txt
adb shell getprop ro.product.cpu.abi | tee controller-evidence/abi.txt
test "$(tr -d '\r' < controller-evidence/boot-completed.txt)" = "1"
test "$(tr -d '\r' < controller-evidence/abi.txt)" = "x86_64"
adb install -r chatgpt-android-relay/android/app/build/outputs/apk/debug/app-debug.apk | tee controller-evidence/install.txt
grep -q Success controller-evidence/install.txt
adb shell pm path com.hitel.chatrelay | tee controller-evidence/package.txt
# Android 13+ rejects sideloaded accessibility services unless
# Restricted Settings access is explicitly allowed for this test app.
adb shell cmd appops set com.hitel.chatrelay ACCESS_RESTRICTED_SETTINGS allow
adb shell cmd appops get com.hitel.chatrelay ACCESS_RESTRICTED_SETTINGS | tee controller-evidence/restricted-settings-appop.txt
adb shell am start -n com.hitel.chatrelay/.MainActivity | tee controller-evidence/start.txt
sleep 5
adb shell dumpsys activity activities | grep -E 'topResumedActivity|mResumedActivity' | head -5 | tee controller-evidence/foreground.txt || true
EXISTING="$(adb shell settings get secure enabled_accessibility_services | tr -d '\r')"
[[ "$EXISTING" == "null" ]] && EXISTING=""
SERVICE='com.hitel.chatrelay/.ChatRelayService'
case ":$EXISTING:" in
  *":$SERVICE:"*) UPDATED="$EXISTING" ;;
  "::") UPDATED="$SERVICE" ;;
  *) UPDATED="$EXISTING:$SERVICE" ;;
esac
# Android 15 can revert secure settings before its accessibility manager
# finishes bootstrapping. Retry a bounded number of times and require actual
# manager binding rather than trusting a successful settings command.
ENABLED=0
: > controller-evidence/accessibility-attempts.txt
for attempt in 1 2 3 4 5; do
  adb shell cmd appops set com.hitel.chatrelay ACCESS_RESTRICTED_SETTINGS allow
  adb shell settings put secure enabled_accessibility_services "$UPDATED"
  adb shell settings put secure accessibility_enabled 1
  sleep 5
  ACTUAL="$(adb shell settings get secure enabled_accessibility_services | tr -d '\r')"
  adb shell dumpsys accessibility > controller-evidence/accessibility-attempt.txt
  printf 'attempt=%d enabled=%s bound=%s\n' "$attempt" "$ACTUAL" "$(
    grep -q 'Bound services:{Service\\[label=ChatGPT Relay Control' controller-evidence/accessibility-attempt.txt &&
    printf yes || printf no
  )" | tee -a controller-evidence/accessibility-attempts.txt
  if [[ "$ACTUAL" == *"com.hitel.chatrelay"* ]] &&
     grep -q 'Bound services:{Service\\[label=ChatGPT Relay Control' controller-evidence/accessibility-attempt.txt; then
    ENABLED=1
    break
  fi
done
adb shell settings get secure enabled_accessibility_services | tee controller-evidence/enabled-accessibility-services.txt
adb shell cmd appops get com.hitel.chatrelay ACCESS_RESTRICTED_SETTINGS | tee controller-evidence/post-enable-appop.txt
adb shell dumpsys accessibility > controller-evidence/accessibility.txt
adb shell dumpsys activity activities | grep -E 'topResumedActivity|mResumedActivity' | head -5 | tee controller-evidence/after-service-foreground.txt || true
adb shell uiautomator dump /sdcard/controller.xml >/dev/null 2>&1 || true
adb pull /sdcard/controller.xml controller-evidence/controller.xml || true
adb shell screencap -p /sdcard/controller.png
adb pull /sdcard/controller.png controller-evidence/controller.png
adb logcat -d -t 1500 | grep -E 'FATAL EXCEPTION|AndroidRuntime|com.hitel.chatrelay' | tail -120 > controller-evidence/logcat.txt || true
grep -q 'com.hitel.chatrelay' controller-evidence/package.txt
if grep -E 'FATAL EXCEPTION' controller-evidence/logcat.txt; then
  echo 'FAIL: Android crash detected' >&2
  exit 1
fi
if [[ "$ENABLED" != 1 ]] ||
   ! grep -q 'com.hitel.chatrelay' controller-evidence/enabled-accessibility-services.txt; then
  echo 'FAIL_ACCESSIBILITY_NOT_ENABLED_ANDROID_RESTRICTED_SETTINGS' | tee controller-evidence/result.txt
  exit 1
fi
echo 'PASS_CONTROLLER_INSTALL_LAUNCH_ACCESSIBILITY_SETTING_NO_FATAL_CRASH' | tee controller-evidence/result.txt
echo 'NOT_TESTED_OFFICIAL_CHATGPT_SIGNED_IN_ROOM_OR_FILE_UPLOAD' | tee -a controller-evidence/result.txt
