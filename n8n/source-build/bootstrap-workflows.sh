#!/bin/sh
# ProcureFlow n8n native dependency compiler + import.
# Only real n8n CLI controls DB. No standalone DAG execution process.
set -eu
n8n_dir=/home/node/.n8n
mkdir -p "$n8n_dir"
# Railway volume is root-owned on first mount; repair once, then run n8n as node.
if [ "$(id -u)" -eq 0 ]; then
  chown -R node:node "$n8n_dir"
  exec gosu node "$0" "$@"
fi
echo "[procureflow] Compile 15 PF native DAGs (43 business blocks) and PF00 controller..."
node /usr/local/bin/procureflow-compile-topology
echo "[procureflow] Validate generated native n8n workflow edges..."
node /usr/local/bin/procureflow-test-topology
version_marker="$n8n_dir/.procureflow-native-v2"
if [ ! -f "$version_marker" ]; then
  echo "[procureflow] Importing 16 native PF workflows with IF/Merge/ExecuteWorkflow dependencies..."
  n8n import:workflow --separate --input=/home/node/compiled-native/operational
  echo "[procureflow] Importing 10 n8n fictional safety scenarios..."
  n8n import:workflow --separate --input=/home/node/procureflow-demo-workflows
  touch "$version_marker"
  echo "[procureflow] Imported PF00-PF15 + S01-S10 (26 native workflows)."
else
  echo "[procureflow] Native v2 import marker present; keeping database edits."
fi
# n8n 2.x only allows Execute Workflow to call published sub-workflows.
# PF01-PF15 contain ONLY manual/sub-workflow triggers, never automatic tender submission.
publish_marker="$n8n_dir/.procureflow-published-subflows-v2"
if [ ! -f "$publish_marker" ]; then
  echo "[procureflow] Publishing 15 native PF sub-workflows (manual/called only)..."
  for n in 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15; do
    n8n publish:workflow --id="PFOP2026PF${n}WF"
  done
  touch "$publish_marker"
  echo "[procureflow] All 15 native PF sub-workflows published for ExecuteWorkflow calls."
fi
if [ "${PROCUREFLOW_SMOKE_S01:-0}" = 1 ]; then
  echo "[procureflow] S01 actual n8n execution smoke start (fictional, no bids)..."
  if n8n execute --id PFDEMO2026S01WF; then
    echo "[procureflow] S01 real n8n CLI execution passed."
  else
    echo "[procureflow] S01 real n8n execution FAILED; do not report full test completion."
  fi
fi
if [ "${PROCUREFLOW_SMOKE_PF00:-0}" = 1 ]; then
  echo "[procureflow] PF00 actual native ExecuteWorkflow/Merge/IF smoke start (read-only)..."
  if n8n execute --id PFORCH2026MAINWF; then
    echo "[procureflow] PF00 read-only n8n native execution passed."
  else
    echo "[procureflow] PF00 native execution FAILED; do not report full business workflow success."
  fi
fi
exec n8n start
