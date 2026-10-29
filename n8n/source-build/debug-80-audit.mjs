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
