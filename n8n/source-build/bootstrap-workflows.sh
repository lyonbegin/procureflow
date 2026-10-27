#!/bin/sh
# Install real PF01-PF15 and S01-S10 workflows into the native n8n database.
# This is NOT a second workflow engine or graphic mock: CLI writes native n8n workflow entities.
set -eu
n8n_dir=/home/node/.n8n
mkdir -p "$n8n_dir"
if [ ! -f "$n8n_dir/.procureflow-workflows-imported-v1" ]; then
  echo "[procureflow] Importing 15 native PF workflows..."
  n8n import:workflow --separate --input=/home/node/procureflow-operational-workflows
  echo "[procureflow] Importing 10 native S workflows..."
  n8n import:workflow --separate --input=/home/node/procureflow-demo-workflows
  touch "$n8n_dir/.procureflow-workflows-imported-v1"
  echo "[procureflow] Native n8n workflow imports finished: 15 PF + 10 S (25 total)."
else
  echo "[procureflow] Native workflow import marker present; preserving existing workflow changes."
fi
exec n8n start
