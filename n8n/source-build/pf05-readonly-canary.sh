#!/bin/sh
# Read-only PF05 native n8n integration canary in the ALREADY EXISTING isolated source-test service.
# Never touch production n8n/Worker or any selected-bid mutations.
set -eu
test "${PROCUREFLOW_SMOKE_PF05_CANARY:-0}" = 1 || exit 0
canary_id=PFOP2026PF05JOINQA20261104
src=/home/node/compiled-native/operational/PF05.json
canary=/tmp/pf05-native-join-qa.json
log=/tmp/pf05-native-join-qa-execution.log
test -s "$src"
node - "$src" "$canary" "$canary_id" <<'JS'
const fs=require('node:fs');
const [src,dest,id]=process.argv.slice(2);
const w=JSON.parse(fs.readFileSync(src,'utf8'));
if(w.id!=='PFOP2026PF05WF'||w.active!==false)throw Error('PF05 canary requires inactive compiled source');
const n=w.nodes.find(x=>x.name==='검증 H07 · 분기 결과 합치기');
const h=w.nodes.find(x=>x.name==='H07 · 10년 개찰·낙찰 완전성');
if(!n?.parameters?.jsCode?.includes('JOIN_DUPLICATE_OR_UNEXPECTED_BRANCH')||
   !h?.parameters?.jsCode?.includes('H07_REQUIRED_INPUTS_MISSING'))
  throw Error('PF05 canary requires current native H07 gate implementation');
w.id=id;
w.name='[검증용/읽기전용] PF05 H05+H06 합류 실제 n8n CLI 실행 20261104';
w.active=false;
w.tags=[];
w.meta={...w.meta,read_only_canary:true,isolated_existing_source_test:true,
  no_worker_enqueue:true,no_bid_submission:true,official_evidence_may_be_unverified:true};
fs.writeFileSync(dest,JSON.stringify(w,null,2)+'\n');
JS
echo "PF05_CANARY_IMPORT_STARTED id=$canary_id"
n8n import:workflow --input="$canary" > /tmp/pf05-native-join-qa-import.log 2>&1 || {
  echo 'PF05_CANARY_IMPORT_FAILED'
  tail -n 8 /tmp/pf05-native-join-qa-import.log | sed 's/https:\/\/[^ ]*/[redacted-url]/g'
  exit 0
}
echo "PF05_CANARY_IMPORT_SUCCESS id=$canary_id"
set +e
canary_start_sec=$(date -u +%s)
n8n execute --id "$canary_id" > "$log" 2>&1
status=$?
set -e
node /usr/local/bin/procureflow-pf05-canary-parser "$log" "$canary_id" "$status"
# n8n CLI stdout contains IRun but not necessarily its internal Execution ID.
# Look it up from the existing isolated SQLite, read-only, only if it was persisted.
if [ -f /home/node/.n8n/database.sqlite ]; then
 python3 - "$canary_id" "$canary_start_sec" <<'PY'
import sqlite3, json, sys, datetime
workflow_id, started=sys.argv[1],float(sys.argv[2])
out={"workflow_id":workflow_id,"execution_id":None,"status":None,
     "source":"isolated_n8n_sqlite_readonly","found":False}
try:
 con=sqlite3.connect("file:/home/node/.n8n/database.sqlite?mode=ro",uri=True)
 con.row_factory=sqlite3.Row
 rows=con.execute('SELECT id,status,startedAt FROM execution_entity WHERE workflowId=? ORDER BY CAST(id AS INTEGER) DESC LIMIT 5',(workflow_id,)).fetchall()
 for row in rows:
  stamp=row["startedAt"]
  if not stamp: continue
  if isinstance(stamp,(int,float)):
   epoch=float(stamp)/1000 if stamp>10**12 else float(stamp)
  else:
   epoch=datetime.datetime.fromisoformat(str(stamp).replace("Z","+00:00")).timestamp()
  if epoch>=started-15:
   out.update(execution_id=str(row["id"]),status=row["status"],found=True)
   break
except Exception as e:
 out["reason"]="read_only_execution_row_unavailable"
print("PF05_CANARY_SQLITE_EXECUTION_ROW "+json.dumps(out,separators=(",",":")))
PY
else
 echo 'PF05_CANARY_SQLITE_EXECUTION_ROW {"execution_id":null,"found":false,"reason":"sqlite_database_not_found"}'
fi
