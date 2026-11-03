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
n8n execute --id "$canary_id" > "$log" 2>&1
status=$?
set -e
PF05_CANARY_CLI_EXIT="$status" node - "$log" "$canary_id" <<'JS'
const fs=require('node:fs');
const raw=fs.readFileSync(process.argv[2],'utf8');
const id=process.argv[3];
const statuses=[...raw.matchAll(/"executionStatus"\s*:\s*"([^"]+)"/g)].map(x=>x[1]);
const traces=[...raw.matchAll(/"executionId"\s*:\s*"([0-9]+)"/g)].map(x=>x[1]);
const names=['H05 · 실제 개찰·투찰 상세','H06 · 확정 낙찰결과','H07 · 10년 개찰·낙찰 완전성'];
const present=Object.fromEntries(names.map(n=>[n.slice(0,3),raw.includes(n)]));
const summary={
 workflow_id:id,cli_exit:Number(process.env.PF05_CANARY_CLI_EXIT),
 execution_id:traces.at(-1)||null,execution_status:statuses.at(-1)||null,
 h05_present:present.H05,h06_present:present.H06,h07_present:present.H07,
 actual_join_output_present:raw.includes('"dependency_join_complete": true')||raw.includes('"dependency_join_complete":true'),
 evidence_accepted:raw.includes('"dependency_evidence_verified": true')||raw.includes('"dependency_evidence_verified":true'),
 bid_submitted:false,worker_job_enqueued:false,
 raw_log_retained_only_in_test_container:true
};
console.log('PF05_NATIVE_N8N_CANARY_RESULT '+JSON.stringify(summary));
if(summary.cli_exit!==0||!summary.h05_present||!summary.h06_present||!summary.h07_present||
   !summary.actual_join_output_present||!statuses.includes('success'))
 console.log('PF05_NATIVE_N8N_CANARY_NOT_VERIFIED_NEEDS_DIAGNOSIS');
else console.log('PF05_NATIVE_N8N_CANARY_H07_DATA_FLOW_CONFIRMED');
JS
