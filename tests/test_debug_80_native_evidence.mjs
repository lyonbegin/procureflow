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
    {name:'official-candidate-vue-canvas-rendered',result:'PASS'},
    {name:'real-chrome-35-unsupported-shared-kinds-not-advertised',result:'PASS',checked:35},
    {name:'real-chrome-custom-node-palette-add',result:'PASS'},
    {name:'real-chrome-business-operation-configuration-visible',result:'PASS'},
    {name:'real-chrome-operationId-dropdown-selection',result:'PASS',operationId:'N02'},
    {name:'real-chrome-evidence-handling-dropdown-selection',result:'PASS',evidenceHandling:'hold'},
    {name:'real-chrome-custom-node-server-save',result:'PASS',nodeId:'native-node-001',
      type:'CUSTOM.procureFlowBusinessOperation',operationId:'N02'},
    {name:'real-chrome-custom-node-pre-drag-server-persistence',result:'PASS',id:'native-node-001'},
    {name:'real-chrome-custom-node-drag-server-coordinate-save',result:'PASS',
      nodeId:'native-node-001',before:[0,9],after:[80,64]},
    {name:'real-chrome-custom-node-position-and-setting-reopen',result:'PASS',
      nodeId:'native-node-001',position:[80,64],operationId:'N02',evidenceHandling:'hold'},
    {name:'native-editability-after-reopen',result:'PASS',editMethod:'clicked-edit-here'},
    {name:'native-custom-node-post-reload-editability-diagnostic',result:'PASS',
      editMethod:'clicked-edit-here',plusVisible:true},
    {name:'real-chrome-custom-output-0-connected',result:'PASS',outputIndex:0,target:'Accepted Sink'},
    {name:'real-chrome-custom-output-1-connected',result:'PASS',outputIndex:1,target:'Hold Sink'},
    {name:'real-chrome-custom-dual-edge-reopen',result:'PASS',nodeId:'native-node-001',
      output0:[{node:'Accepted Sink',type:'main',index:0}],
      output1:[{node:'Hold Sink',type:'main',index:0}]},
    {name:'real-chrome-custom-node-delete-and-server-save',result:'PASS',id:'native-node-001',
      nodeAbsent:true,danglingEdges:false},
    {name:'real-chrome-native-business-operation-synthetic-hold-execution',
      result:'PASS',executionId:'1',status:'success',outputIndex:1,acceptedSinkExecuted:false,
      holdSinkExecuted:true,holdSinkItemCount:1,bidSubmitted:false,workerJobEnqueued:false,
      evidenceProvenance:'isolated_synthetic_test_evidence',inspectionStatus:'HOLD'},
    {name:'real-chrome-native-business-operation-fail-closed-debugging',
      result:'PASS',executionId:'3',status:'error',failedNode:'Business Operation',successOutputs:0,realBusinessHandlers:0,actualBidSubmitted:false,
      reason:'Business Operation N01 held: official evidence incomplete'},
    {name:'real-chrome-all-43-native-operations-synthetic-hold-execution',
      result:'PASS',executionId:'2',status:'success',nativeOperations:43,
      strictInspectionEnvelopesValidated:43,holdOutputs:43,successOutputs:0,
      realBusinessHandlers:0,actualBidSubmitted:false},
    {name:'no-real-business-handler-or-bid-submission',
      result:'PASS',syntheticNativeExecutionCount:44,realBusinessHandlerCount:0,productionApiRequests:0,
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
  ['post-reload diagnostic OBSERVED is not PASS',rows=>
    rows.find(x=>x.name==='native-custom-node-post-reload-editability-diagnostic').result='OBSERVED'],
  ['post-reload native creator must be visible',rows=>
    rows.find(x=>x.name==='native-custom-node-post-reload-editability-diagnostic').plusVisible=false],
  ['post-reload edit gesture must match actual Chrome action',rows=>
    rows.find(x=>x.name==='native-custom-node-post-reload-editability-diagnostic').editMethod='not-edited'],
  ['missing post-reload edit evidence cannot pass',rows=>
    rows.splice(rows.findIndex(x=>x.name==='native-editability-after-reopen'),1)],
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
    rows.splice(rows.findIndex(x=>x.name==='real-chrome-custom-dual-edge-reopen'),1)],
  ['pre-drag saved custom node identity must match actual Chrome node',rows=>
    rows.find(x=>x.name==='real-chrome-custom-node-pre-drag-server-persistence').id='different-node'],
  ['dragged coordinates must persist across reload',rows=>
    rows.find(x=>x.name==='real-chrome-custom-node-position-and-setting-reopen').position=[81,64]],
  ['custom node settings must persist across reload',rows=>
    rows.find(x=>x.name==='real-chrome-custom-node-position-and-setting-reopen').operationId='N03'],
  ['custom node must actually move',rows=>
    rows.find(x=>x.name==='real-chrome-custom-node-drag-server-coordinate-save').after=[0,9]],
  ['output handles cannot be swapped',rows=>
    rows.find(x=>x.name==='real-chrome-custom-output-0-connected').target='Hold Sink'],
  ['restored output-0 cannot be swapped',rows=>
    rows.find(x=>x.name==='real-chrome-custom-dual-edge-reopen').output0[0].node='Hold Sink'],
  ['restored output-1 cannot disappear',rows=>
    rows.find(x=>x.name==='real-chrome-custom-dual-edge-reopen').output1=[]],
  ['restored output cannot change destination index',rows=>
    rows.find(x=>x.name==='real-chrome-custom-dual-edge-reopen').output0[0].index=1],
  ['restored output cannot contain hidden extra edge',rows=>
    rows.find(x=>x.name==='real-chrome-custom-dual-edge-reopen').output1.push({node:'Other Sink',type:'main',index:0})],
  ['restored output cannot change n8n connection type',rows=>
    rows.find(x=>x.name==='real-chrome-custom-dual-edge-reopen').output0[0].type='ai_tool'],
  ['execution IDs must be distinct and numeric',rows=>
    rows.find(x=>x.name.includes('fail-closed-debugging')).executionId='2'],
  ['fake Chrome execution ID is rejected',rows=>
    rows.find(x=>x.name.includes('all-43')).executionId='not-an-execution'],
  ['missing actual HOLD sink item is rejected',rows=>
    rows.find(x=>x.name.includes('synthetic-hold-execution')).holdSinkItemCount=0],
  ['actual handler count cannot be concealed',rows=>
    rows.find(x=>x.name==='no-real-business-handler-or-bid-submission').realBusinessHandlerCount=1],
  ['unsupported node palette must remain excluded',rows=>
    rows.find(x=>x.name==='real-chrome-35-unsupported-shared-kinds-not-advertised').checked=34],
  ['fail-closed debugging must identify failed native node',rows=>
    rows.find(x=>x.name.includes('fail-closed-debugging')).failedNode='Unrelated Node'],
  ['palette creation must have actual Chrome evidence',rows=>
    rows.splice(rows.findIndex(x=>x.name==='real-chrome-custom-node-palette-add'),1)],
  ['operation dropdown selection must be N02',rows=>
    rows.find(x=>x.name==='real-chrome-operationId-dropdown-selection').operationId='N03'],
  ['evidence handling dropdown must be hold',rows=>
    rows.find(x=>x.name==='real-chrome-evidence-handling-dropdown-selection').evidenceHandling='stop'],
  ['saved deletion must remove the actual node',rows=>
    rows.find(x=>x.name==='real-chrome-custom-node-delete-and-server-save').nodeAbsent=false],
  ['saved deletion must remove inbound edges too',rows=>
    rows.find(x=>x.name==='real-chrome-custom-node-delete-and-server-save').danglingEdges=true]
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
