#!/usr/bin/env node
/**
 * Audit 80 separate node-debugging requirements (IDs 81..160).
 * Existing report is the source of truth; a passing audit means the gap
 * inventory is accurate, NOT that the 80 requirements are implemented.
 */
import {readFile,writeFile} from 'node:fs/promises';
const source=process.argv[2]??'reports/workflow_81_160_implementation_20261025.md';
const target=process.argv[3]??'shared-debug-80-audit.json';
const raw=await readFile(source,'utf8');
const entries=[];
for(const line of raw.split(/\r?\n/)){
  const match=line.match(/^\|\s*(\d{2,3})\s*\|\s*(구현|부분|미구현)\s*\|\s*([^|]+)\|\s*([^|]+)\|/);
  if(!match)continue;
  const id=Number(match[1]);
  if(id<81||id>160)continue;
  entries.push({id,status:match[2],name:match[3].trim(),scopeAndGaps:match[4].trim()});
}
if(entries.length!==80)throw Error('Expected 80 requirements, found '+entries.length);
const ids=new Set(entries.map(x=>x.id));
for(let i=81;i<=160;i++)if(!ids.has(i))throw Error('Missing debug requirement '+i);
const counts={implemented:entries.filter(x=>x.status==='구현').length,partial:entries.filter(x=>x.status==='부분').length,notImplemented:entries.filter(x=>x.status==='미구현').length};

// Optional real-Chrome runtime subchecks: pass candidate-business.mjs verdicts
// as the third CLI argument. These are NARROW isolated n8n observations, not
// acceptance of the full legacy Node Lab / live G2B Worker requirements.
const chromeVerdictPath=process.argv[4];
const runtimeSubcheckEvidence=[];
if(chromeVerdictPath){
  const verdicts=JSON.parse(await readFile(chromeVerdictPath,'utf8'));
  if(!Array.isArray(verdicts))throw Error('Real Chrome verdicts must be an array');
  const by=new Map();
  for(const v of verdicts){
    if(!v||typeof v.name!=='string'||by.has(v.name))
      throw Error('Duplicate or invalid real Chrome verdict');
    // A test-run FAIL must never be hidden by seven other PASS records.
    // Fail closed on ANY failed/incomplete native Chrome observation before
    // attributing debugging evidence to the actual n8n execution.
    if(v.result!=='PASS')
      throw Error('Real Chrome verdict failed or incomplete: '+v.name);
    by.set(v.name,v);
  }
  // A PASS label alone is not enough: bind the seven narrow debugging
  // observations to the SAME native Chrome node and to distinct n8n executions.
  // This validates evidence consistency, not cryptographic origin or the
  // remaining 80 full business-debugging requirements.
  const requiredUi=[
    'official-candidate-vue-canvas-rendered',
    'real-chrome-35-unsupported-shared-kinds-not-advertised',
    'real-chrome-custom-node-palette-add',
    'real-chrome-business-operation-configuration-visible',
    'real-chrome-operationId-dropdown-selection',
    'real-chrome-evidence-handling-dropdown-selection',
    'real-chrome-custom-node-server-save',
    'real-chrome-custom-node-reopen-persistence',
    'real-chrome-custom-node-drag-server-coordinate-save',
    'real-chrome-custom-node-position-and-setting-reopen',
    'native-editability-after-reopen',
    'native-custom-node-post-reload-editability-diagnostic',
    'real-chrome-custom-output-0-connected',
    'real-chrome-custom-output-1-connected',
    'real-chrome-custom-dual-edge-reopen',
    'real-chrome-custom-node-delete-and-server-save'
  ];
  for(const name of requiredUi)if(by.get(name)?.result!=='PASS')
    throw Error('Native Chrome UI persistence evidence missing: '+name);
  // Do not silently treat a post-reload diagnostic as success. A genuine
  // Chrome user must have the native creator visible after re-entering edit
  // mode; later deletion independently proves the workflow stayed writable.
  const editability=by.get('native-editability-after-reopen');
  const diagnostic=by.get('native-custom-node-post-reload-editability-diagnostic');
  if(!['already-editable','clicked-edit-here'].includes(editability?.editMethod)||
     diagnostic?.editMethod!==editability.editMethod||
     diagnostic.plusVisible!==true)
    throw Error('Native Chrome post-reload editability evidence mismatch');
  const save=by.get('real-chrome-custom-node-server-save');
  const reopen=by.get('real-chrome-custom-node-reopen-persistence');
  const drag=by.get('real-chrome-custom-node-drag-server-coordinate-save');
  const restored=by.get('real-chrome-custom-node-position-and-setting-reopen');
  const dual=by.get('real-chrome-custom-dual-edge-reopen');
  const removed=by.get('real-chrome-custom-node-delete-and-server-save');
  // The official Chrome editor must actually create a palette node and
  // select BOTH dropdown values, not merely import a preconfigured JSON.
  // The two selections are independently reported by candidate-business.mjs.
  if(by.get('real-chrome-operationId-dropdown-selection')?.operationId!=='N02'||
     by.get('real-chrome-evidence-handling-dropdown-selection')?.evidenceHandling!=='hold')
    throw Error('Native Chrome palette/settings selection evidence mismatch');
  const id=save?.nodeId;
  if(typeof id!=='string'||id.length<8||save.type!=='CUSTOM.procureFlowBusinessOperation'||
     save.operationId!=='N02'||reopen.id!==id||drag.nodeId!==id||
     restored.nodeId!==id||dual.nodeId!==id||removed.id!==id)
    throw Error('Native Chrome custom node identity/persistence mismatch');
  const validPoint=p=>Array.isArray(p)&&p.length===2&&
    p.every(x=>typeof x==='number'&&Number.isFinite(x));
  if(!validPoint(drag.before)||!validPoint(drag.after)||
     !validPoint(restored.position)||
     drag.before.every((v,i)=>v===drag.after[i])||
     !drag.after.every((v,i)=>v===restored.position[i])||
     restored.operationId!=='N02'||restored.evidenceHandling!=='hold')
    throw Error('Native Chrome coordinate/settings save and reload mismatch');
  const edge0=by.get('real-chrome-custom-output-0-connected');
  const edge1=by.get('real-chrome-custom-output-1-connected');
  if(edge0.outputIndex!==0||edge0.target!=='Accepted Sink'||
     edge1.outputIndex!==1||edge1.target!=='Hold Sink')
    throw Error('Native Chrome two-output handle mapping mismatch');
  // Deletion must be persisted by the server AND leave no dangling edges.
  // PASS alone is insufficient; require the deletion postconditions recorded
  // by the actual n8n /rest/workflows reload after Chrome clicked Delete.
  if(removed.nodeAbsent!==true||removed.danglingEdges!==false)
    throw Error('Native Chrome node deletion persistence evidence mismatch');
  if(by.get('real-chrome-35-unsupported-shared-kinds-not-advertised').checked!==35)
    throw Error('Unsupported shared kinds must remain absent from executable palette');
  const executionNames=[
    'real-chrome-native-business-operation-synthetic-hold-execution',
    'real-chrome-all-43-native-operations-synthetic-hold-execution',
    'real-chrome-native-business-operation-fail-closed-debugging'
  ];
  const executions=executionNames.map(name=>by.get(name));
  if(executions.some(v=>typeof v?.executionId!=='string'||!/^\d+$/.test(v.executionId))||
     new Set(executions.map(v=>v.executionId)).size!==3||
     executions[0].holdSinkItemCount!==1||
     executions[1].actualBidSubmitted!==false||
     executions[2].failedNode!=='Business Operation'||
     executions[2].realBusinessHandlers!==0||
     executions[2].actualBidSubmitted!==false||
     by.get('no-real-business-handler-or-bid-submission')?.realBusinessHandlerCount!==0)
    throw Error('Native Chrome execution ID / fail-closed safety evidence mismatch');
  const checks=[
    {id:127,scope:'native two-output edge tracing and reload persistence',
      names:['real-chrome-custom-output-0-connected',
        'real-chrome-custom-output-1-connected',
        'real-chrome-custom-dual-edge-reopen',
        'real-chrome-native-business-operation-synthetic-hold-execution'],
      valid:()=>by.get('real-chrome-native-business-operation-synthetic-hold-execution')?.holdSinkExecuted===true},
    {id:128,scope:'native fail-closed node error and execution log',
      names:['real-chrome-native-business-operation-fail-closed-debugging'],
      valid:()=>{
        const v=by.get('real-chrome-native-business-operation-fail-closed-debugging');
        return v?.status==='error'&&v.successOutputs===0&&
          typeof v.reason==='string'&&v.reason.includes('official evidence incomplete');
      }},
    {id:135,scope:'43 native synthetic inspection outputs checked against strict read-only envelope schemas (not real business payload schemas)',
      names:['real-chrome-all-43-native-operations-synthetic-hold-execution'],
      valid:()=>{
        const v=by.get('real-chrome-all-43-native-operations-synthetic-hold-execution');
        return v?.status==='success'&&v.nativeOperations===43&&
          v.strictInspectionEnvelopesValidated===43&&v.holdOutputs===43&&
          v.successOutputs===0&&v.realBusinessHandlers===0;
      }},
    {id:144,scope:'native conditional HOLD branch, no accepted branch',
      names:['real-chrome-native-business-operation-synthetic-hold-execution'],
      valid:()=>{
        const v=by.get('real-chrome-native-business-operation-synthetic-hold-execution');
        return v?.status==='success'&&v.outputIndex===1&&
          v.acceptedSinkExecuted===false&&v.holdSinkExecuted===true&&
          v.bidSubmitted===false&&v.workerJobEnqueued===false;
      }},
    {id:146,scope:'isolated 43-operation native synthetic dry-run',
      names:['real-chrome-all-43-native-operations-synthetic-hold-execution',
        'no-real-business-handler-or-bid-submission'],
      valid:()=>{
        const v=by.get('real-chrome-all-43-native-operations-synthetic-hold-execution');
        const s=by.get('no-real-business-handler-or-bid-submission');
        return v?.status==='success'&&v.nativeOperations===43&&
          v.holdOutputs===43&&v.successOutputs===0&&
          v.strictInspectionEnvelopesValidated===43&&v.realBusinessHandlers===0&&
          v.actualBidSubmitted===false&&s?.actualBidSubmitted===false&&
          s.productionApiRequests===0;
      }},
    {id:147,scope:'isolated loopback HTTP mock evidence consumed by official native n8n (not a generic Mock API service)',
      names:['real-chrome-native-business-operation-synthetic-hold-execution',
        'no-real-business-handler-or-bid-submission'],
      valid:()=>{
        const v=by.get('real-chrome-native-business-operation-synthetic-hold-execution');
        const s=by.get('no-real-business-handler-or-bid-submission');
        return v?.status==='success'&&v.evidenceProvenance==='isolated_synthetic_test_evidence'&&
          v.inspectionStatus==='HOLD'&&v.bidSubmitted===false&&
          s?.syntheticNativeExecutionCount===44&&s.productionApiRequests===0&&
          s.actualBidSubmitted===false;
      }},
    {id:150,scope:'native success/error execution-state evidence',
      names:['real-chrome-native-business-operation-synthetic-hold-execution',
        'real-chrome-native-business-operation-fail-closed-debugging'],
      valid:()=>by.get('real-chrome-native-business-operation-synthetic-hold-execution')?.status==='success'&&
        by.get('real-chrome-native-business-operation-fail-closed-debugging')?.status==='error'}
  ];
  for(const check of checks){
    const missing=check.names.filter(name=>by.get(name)?.result!=='PASS');
    if(missing.length)throw Error('Native debug #'+check.id+' missing Chrome PASS: '+missing.join(', '));
    if(!check.valid())throw Error('Native debug #'+check.id+' runtime invariant failed');
    runtimeSubcheckEvidence.push({
      id:check.id,scope:check.scope,
      verdict:'OBSERVED_IN_OFFICIAL_N8N_SYNTHETIC_RUNTIME',
      sourceVerdicts:check.names,
      requirementFullyAccepted:false
    });
  }
}

const summary={
  schemaVersion:'procureflow.debug-80-audit.v1',
  source,
  status:counts.partial+counts.notImplemented===0?'ALL_REPORTED_IMPLEMENTED_REQUIRES_RUNTIME_VALIDATION':'INCOMPLETE',
  ...counts,
  total:entries.length,
  runtimeVerified:0, // Full 80-item acceptance remains ZERO.
  nativeRuntimeSubchecksObserved:runtimeSubcheckEvidence.length,
  nativeRuntimeSubcheckEvidence:runtimeSubcheckEvidence,
  runtimeEvidenceSource:chromeVerdictPath||null,
  githubRunId:chromeVerdictPath?(process.env.GITHUB_RUN_ID||null):null,
  notYetFullyImplemented:entries.filter(x=>x.status!=='구현'),
  allRequirements:entries
};
await writeFile(target,JSON.stringify(summary,null,2)+'\n');
console.log('DEBUG_80_AUDIT '+JSON.stringify({status:summary.status,counts,total:summary.total,runtimeVerified:summary.runtimeVerified,nativeRuntimeSubchecksObserved:summary.nativeRuntimeSubchecksObserved}));
if(counts.implemented!==19||counts.partial!==47||counts.notImplemented!==14){
  console.log('DEBUG_80_BASELINE_CHANGED: update source report and inspect whether implementation evidence changed');
}
