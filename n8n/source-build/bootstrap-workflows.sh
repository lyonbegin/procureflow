#!/bin/sh
# ProcureFlow n8n native dependency compiler + import.
# Only real n8n CLI controls DB. No standalone DAG execution process.
set -eu
n8n_dir=/home/node/.n8n
mkdir -p "$n8n_dir"
echo "[procureflow] Compile 15 PF native DAGs (43 business blocks) and PF00 controller..."
node /usr/local/bin/procureflow-compile-topology.mjs
echo "[procureflow] Validate generated native n8n workflow edges..."
node /usr/local/bin/procureflow-test-topology.mjs
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
if [ "${PROCUREFLOW_SMOKE_S01:-0}" = 1 ]; then
  echo "[procureflow] S01 actual n8n execution smoke start (fictional, no bids)..."
  if n8n execute --id PFDEMO2026S01WF; then
    echo "[procureflow] S01 real n8n CLI execution passed."
  else
    echo "[procureflow] S01 real n8n execution FAILED; do not report full test completion."
  fi
fi
exec n8n start
