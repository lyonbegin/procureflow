import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,writeFileSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';

// Synthetic *test of the evidence verifier*, not a claim that 80 requirements
// passed or that any business handler ran. Actual Chrome verdicts are produced
// only by the separate official n8n candidate workflow.
const script='n8n/source-build/debug-80-audit.mjs';
const inventory='reports/workflow_81_160_implementation_20261025.md';
const dir=mkdtempSync(join(tmpdir(),'procureflow-debug-verdict-'));
test.after(()=>rmSync(dir,{recursive:true,force:true}));

function fixture(){
  return [
    {name:'real-chrome-custom-output-0-connected',result:'PASS'},
    {name:'real-chrome-custom-output-1-connected',result:'PASS'},
    {name:'real-chrome-custom-dual-edge-reopen',result:'PASS'},
    {name:'real-chrome-native-business-operation-synthetic-hold-execution',
      result:'PASS',status:'success',outputIndex:1,acceptedSinkExecuted:false,
      holdSinkExecuted:true,bidSubmitted:false,workerJobEnqueued:false,
      evidenceProvenance:'isolated_synthetic_test_evidence',inspectionStatus:'HOLD'},
    {name:'real-chrome-native-business-operation-fail-closed-debugging',
      result:'PASS',status:'error',successOutputs:0,
      reason:'Business Operation N01 held: official evidence incomplete'},
    {name:'real-chrome-all-43-native-operations-synthetic-hold-execution',
      result:'PASS',status:'success',nativeOperations:43,
      strictInspectionEnvelopesValidated:43,holdOutputs:43,successOutputs:0,
      realBusinessHandlers:0,actualBidSubmitted:false},
    {name:'no-real-business-handler-or-bid-submission',
      result:'PASS',syntheticNativeExecutionCount:44,productionApiRequests:0,
      actualBidSubmitted:false}
  ];
}
let counter=0;
function audit(verdicts){
  const id=++counter;
  const input=join(dir,'chrome-'+id+'.json');
  const output=join(dir,'audit-'+id+'.json');
  writeFileSync(input,JSON.stringify(verdicts));
  const processResult=spawnSync(process.execPath,[script,inventory,output,input],
    {encoding:'utf8',timeout:20000});
  return {status:processResult.status,stdout:processResult.stdout,
    stderr:processResult.stderr,
    report:processResult.status===0?JSON.parse(readFileSync(output,'utf8')):null};
}

test('positive verifier fixture counts seven NARROW subchecks and accepts zero full requirements',()=>{
  const {status,report,stderr}=audit(fixture());
  assert.equal(status,0,stderr);
  assert.equal(report.total,80);
  assert.equal(report.runtimeVerified,0);
  assert.equal(report.nativeRuntimeSubchecksObserved,7);
  assert.deepEqual(report.nativeRuntimeSubcheckEvidence.map(x=>x.id),
    [127,128,135,144,146,147,150]);
  assert(report.nativeRuntimeSubcheckEvidence.every(x=>
    x.requirementFullyAccepted===false));
  assert.equal(report.status,'INCOMPLETE');
});

const attacks=[
  ['unrelated failed Chrome test cannot be ignored',rows=>
    rows.push({name:'test-run',result:'FAIL',error:'Chrome crashed'})],
  ['incomplete Chrome observation is not PASS',rows=>
    rows[0].result='SKIPPED'],
  ['duplicate verdicts cannot shadow real evidence',rows=>
    rows.push({...rows[0]})],
  ['missing HOLD branch must fail closed',rows=>
    rows.find(x=>x.name.includes('synthetic-hold-execution')).holdSinkExecuted=false],
  ['accepted branch execution cannot be approved',rows=>
    rows.find(x=>x.name.includes('synthetic-hold-execution')).acceptedSinkExecuted=true],
  ['fewer than 43 inspection envelopes cannot be approved',rows=>
    rows.find(x=>x.name.includes('all-43')).strictInspectionEnvelopesValidated=42],
  ['synthetic real business handler is forbidden',rows=>
    rows.find(x=>x.name.includes('all-43')).realBusinessHandlers=1],
  ['production API request is forbidden',rows=>
    rows.find(x=>x.name==='no-real-business-handler-or-bid-submission').productionApiRequests=1],
  ['actual bid submission is forbidden',rows=>
    rows.find(x=>x.name==='no-real-business-handler-or-bid-submission').actualBidSubmitted=true],
  ['untrusted synthetic evidence provenance is forbidden',rows=>
    rows.find(x=>x.name.includes('synthetic-hold-execution')).evidenceProvenance='live_procureflow_postgresql_verified_evidence'],
  ['native error must contain the fail-closed reason',rows=>
    rows.find(x=>x.name.includes('fail-closed-debugging')).reason='unexpected success'],
  ['missing runtime verdict cannot pass',rows=>
    rows.splice(rows.findIndex(x=>x.name==='real-chrome-custom-dual-edge-reopen'),1)]
];
for(const [name,mutate] of attacks){
  test(name,()=>{
    const rows=fixture();
    mutate(rows);
    const result=audit(rows);
    assert.notEqual(result.status,0,
      'Invalid Chrome evidence was accepted: '+name+'\n'+result.stdout);
  });
}
