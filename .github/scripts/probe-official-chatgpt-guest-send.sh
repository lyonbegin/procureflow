#!/usr/bin/env bash
set -euo pipefail
# Runs ONLY in the isolated official ChatGPT 1.2026.300 Android emulator.
# Sends a real test question to the guest ChatGPT app via native UI,
# without the HITEL controller or any mocked ChatGPT responses.
mkdir -p real-chatgpt-evidence
adb shell dumpsys activity activities \
  | grep -E 'topResumedActivity|mResumedActivity' | head -5 \
  > real-chatgpt-evidence/guest-direct-foreground-before.txt || true
timeout 35s adb shell uiautomator dump /sdcard/guest-before.xml >/dev/null 2>&1 || true
adb pull /sdcard/guest-before.xml real-chatgpt-evidence/guest-before.xml >/dev/null 2>&1 || true
adb shell screencap -p /sdcard/guest-before.png
adb pull /sdcard/guest-before.png real-chatgpt-evidence/guest-before.png >/dev/null
cat > /tmp/guest-coordinates.py <<'PY'
from pathlib import Path
import re,sys,xml.etree.ElementTree as ET
source=Path(sys.argv[1])
mode=sys.argv[2]
try: nodes=list(ET.parse(source).iter('node'))
except (ET.ParseError,OSError):
  sys.exit(0)
def center(node):
  m=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',node.attrib.get('bounds',''))
  if m:
    x1,y1,x2,y2=map(int,m.groups())
    return str((x1+x2)//2)+' '+str((y1+y2)//2)
if mode=='input':
  for n in nodes:
    label=(n.attrib.get('text','')+' '+n.attrib.get('content-desc','')).lower()
    if ('edittext' in n.attrib.get('class','').lower() or
        'ask chatgpt' in label) and center(n):
      print(center(n)); break
elif mode=='send':
  for n in nodes:
    label=(n.attrib.get('text','')+' '+n.attrib.get('content-desc','')+
        ' '+n.attrib.get('resource-id','')).lower()
    if ('send' in label or 'submit' in label) and n.attrib.get('clickable')=='true' and center(n):
      print(center(n)); break
PY
COORDS="$(python3 /tmp/guest-coordinates.py real-chatgpt-evidence/guest-before.xml input)"
if [[ -z "$COORDS" ]]; then
  echo 'DIRECT_GUEST_INPUT_NOT_DISCOVERED' | tee real-chatgpt-evidence/guest-direct-result.txt
  exit 0
fi
read -r CX CY <<< "$COORDS"
adb shell input tap "$CX" "$CY"
adb shell input text 'What%sis%s18%splus%s24?%sReply%swith%sthe%snumeric%sanswer%sonly.'
sleep 2
timeout 35s adb shell uiautomator dump /sdcard/guest-typed.xml >/dev/null 2>&1 || true
adb pull /sdcard/guest-typed.xml real-chatgpt-evidence/guest-typed.xml >/dev/null 2>&1 || true
adb shell screencap -p /sdcard/guest-typed.png
adb pull /sdcard/guest-typed.png real-chatgpt-evidence/guest-typed.png >/dev/null
SEND="$(python3 /tmp/guest-coordinates.py real-chatgpt-evidence/guest-typed.xml send)"
if [[ -z "$SEND" ]]; then
  # The send-arrow control is located at the right of the real editable
  # composer on this official Android layout. Derive from screen size rather
  # than assuming the emulator's screenshot pixel dimensions.
  SIZE="$(adb shell wm size | tr -d '\r' | grep -oE '[0-9]+x[0-9]+' | tail -1)"
  WIDTH="${SIZE%x*}"
  SEND="$((WIDTH-110)) $CY"
  echo 'SEND_BUTTON_FALLBACK_DERIVED_FROM_COMPOSER_AND_SCREEN_WIDTH' \
    >> real-chatgpt-evidence/guest-direct-result.txt
fi
read -r SX SY <<< "$SEND"
adb shell input tap "$SX" "$SY"
echo "SENT_REAL_GUEST_QUESTION_TAP=$SX,$SY" \
  >> real-chatgpt-evidence/guest-direct-result.txt
sleep 30
adb shell dumpsys activity activities \
  | grep -E 'topResumedActivity|mResumedActivity' | head -5 \
  > real-chatgpt-evidence/guest-direct-foreground-after.txt || true
adb shell screencap -p /sdcard/guest-after-send.png
adb pull /sdcard/guest-after-send.png real-chatgpt-evidence/guest-after-send.png >/dev/null
timeout 35s adb shell uiautomator dump /sdcard/guest-after-send.xml >/dev/null 2>&1 || true
adb pull /sdcard/guest-after-send.xml real-chatgpt-evidence/guest-after-send.xml >/dev/null 2>&1 || true
python3 - <<'PY'
from pathlib import Path
import re,xml.etree.ElementTree as ET
folder=Path('real-chatgpt-evidence')
try: nodes=list(ET.parse(folder/'guest-after-send.xml').iter('node'))
except (ET.ParseError,OSError): nodes=[]
non_editable=[n.attrib.get('text','') for n in nodes
    if 'edittext' not in n.attrib.get('class','').lower() and
    n.attrib.get('text','').strip()]
prompt_visible=any('18 plus 24' in t.lower() for t in non_editable)
reply_visible=any(re.search(r'(?<!\d)42(?!\d)',t) for t in non_editable)
status='PASS_DIRECT_OFFICIAL_GUEST_TEXT_SEND_AND_REPLY_42' if (
    prompt_visible and reply_visible) else 'NOT_VERIFIED_DIRECT_GUEST_REPLY'
with (folder/'guest-direct-result.txt').open('a') as f:
  f.write('prompt_visible='+str(prompt_visible)+' reply_visible='+str(reply_visible)+'\n')
  f.write(status+'\n')
print(status)
print('NONEDITABLE_UI_TEXT',repr(non_editable[-22:]))
PY
