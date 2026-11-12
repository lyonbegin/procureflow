#!/bin/sh
set -eu
export N8N_DIAGNOSTICS_ENABLED=false
echo "[procureflow safe native runner] importing 10 immutable demonstration workflows"
n8n import:workflow --separate --input=/opt/procureflow-scenarios
node /opt/procureflow-prefixes.mjs
n8n import:workflow --separate --input=/tmp/procureflow-native-step-fixtures
echo "[procureflow safe native runner] native n8n CLI ready"
exec node /opt/procureflow-server.mjs
