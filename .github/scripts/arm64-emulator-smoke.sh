#!/usr/bin/env bash
set -euo pipefail
mkdir -p arm64-emulator-evidence
{
  echo "=== Guest CPU ABI ==="
  adb shell getprop ro.product.cpu.abi | tr -d '\r'
  echo "=== Guest ABI list ==="
  adb shell getprop ro.product.cpu.abilist | tr -d '\r'
  echo "=== Android version ==="
  adb shell getprop ro.build.version.release | tr -d '\r'
  echo "=== Device status ==="
  adb devices -l
  echo "=== Boot state ==="
  adb shell getprop sys.boot_completed | tr -d '\r'
} | tee arm64-emulator-evidence/device-info.txt
CPU_ABI="$(adb shell getprop ro.product.cpu.abi | tr -d '\r')"
test "$CPU_ABI" = 'arm64-v8a' || { echo "FAIL: $CPU_ABI is not ARM64"; exit 11; }
test "$(adb shell getprop sys.boot_completed | tr -d '\r')" = '1' || { echo "FAIL: emulator not booted"; exit 12; }
echo "ARM64_GUEST_BOOT_CONFIRMED" | tee arm64-emulator-evidence/result.txt
RELAY="chatgpt-android-relay/web/static/ChatGPT-Relay-Control.apk"
if [ -s "$RELAY" ]; then
  adb install -r "$RELAY" | tee arm64-emulator-evidence/relay-install.txt
  adb shell pm path com.hitel.chatrelay | tee arm64-emulator-evidence/relay-package.txt
else
  echo "RELAY_BINARY_NOT_IN_CHECKOUT" | tee arm64-emulator-evidence/relay-package.txt
fi
adb shell screencap -p /sdcard/arm64-device.png
adb pull /sdcard/arm64-device.png arm64-emulator-evidence/arm64-device.png
echo "OFFICIAL_CHATGPT_XAPK_INSTALL_NOT_PERFORMED: Uploaded XAPK is not yet accessible in GitHub Actions filesystem" | tee -a arm64-emulator-evidence/result.txt
