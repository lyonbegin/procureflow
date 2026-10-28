/**
 * ProcureFlow shared-n8n-studio 50-kind / 43-block integration contract.
 * This is an explicit SAFE adapter registry, NOT a replacement DAG engine.
 * No network, credentials, Worker mutation, bids, or automatic approvals.
 * Run: node n8n/source-build/shared-adapter-contracts.mjs \
 *   n8n/operational_manifest.json /tmp/shared-n8n-studio/playground/src/node-catalog.js
 */
import {readFile, writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';

const EXPECTED_PREFIX_COUNTS = {N:10,H:11,Q:5,S:4,P:7,R:2,O:4};
const EXPECTED_KIND_COUNTS = {native:14,composite:7,extension:29};
const REQUIRED_FEATURES = Array.from({length:104},(_,i)=>i+1);
const fail = (message) => {throw Error('shared-n8n-contract: '+message);};
const assert = (v,message) => {if(!v)fail(message);};
export function createAdapterRegistry(manifest,catalog) {
  assert(manifest?.engine==='n8n_only','official n8n engine required');
  assert(manifest?.blocks?.length===43,'expected 43 business blocks');
  assert(manifest?.flows?.length===15,'expected 15 PF flows');
  assert(catalog?.length===50,'expected 50 shared node kinds');
  const kinds=new Set(catalog.map(x=>x.kind));
  assert(kinds.size===50,'duplicate catalog kinds');
  assert(kinds.has('business-operation'),'business-operation kind absent');
  for(const [implementation,count] of Object.entries(EXPECTED_KIND_COUNTS)){
    assert(catalog.filter(n=>n.implementation===implementation).length===count,'incorrect '+implementation+' kind count');
  }
  for(const n of catalog){
    assert(Array.isArray(n.outputs)&&n.outputs.length>0,'no outputs for '+n.kind);
    assert(Array.isArray(n.fields),'no fields for '+n.kind);
    assert(n.implementation!=='native'||(typeof n.nativeType==='string'&&n.nativeType.startsWith('n8n-nodes-base.')),
      'unresolved native n8n type: '+n.kind);
    assert(n.implementation!=='extension'||n.nativeType===null,
      'extension must not masquerade as a native executable: '+n.kind);
  }
  const seen=new Set(),prefixes={},features=new Set();
  const ownership=new Map();
  for(const flow of manifest.flows){
    assert(/^PF(0[1-9]|1[0-5])$/.test(flow.id),'invalid PF flow '+flow.id);
    for(const id of flow.owned_blocks??[]){
      assert(!ownership.has(id),'multiple owners for '+id);
      ownership.set(id,flow.id);
    }
  }
  const adapters=manifest.blocks.map(block=>{
    assert(/^(N(0[1-9]|10)|H(0[1-9]|1[01])|Q0[1-5]|S0[1-4]|P0[1-7]|R0[1-2]|O0[1-4])$/.test(block.id),'invalid block ID '+block.id);
    assert(!seen.has(block.id),'duplicate block ID '+block.id);
    seen.add(block.id);
    prefixes[block.id[0]]=(prefixes[block.id[0]]??0)+1;
    const flowId=ownership.get(block.id);
    assert(flowId,'missing owning PF flow for '+block.id);
    assert(typeof block.input==='string'&&block.input.length>0,'missing input contract '+block.id);
    assert(typeof block.output==='string'&&block.output.length>0,'missing output contract '+block.id);
    assert(Array.isArray(block.features)&&block.features.length>0,'missing feature IDs '+block.id);
    for(const f of block.features){assert(Number.isInteger(f)&&f>=1&&f<=104,'invalid feature '+f);features.add(f);}
    // Strictly read-only evidence inspection; not equivalent to a block execution.
    return Object.freeze({
      kind:'business-operation',
      adapter:'procureflow',
      operationId:block.id,
      flowId,
      label:block.label,
      inputContract:block.input,
      outputContract:block.output,
      featureIds:block.features,
      successors:block.to??[],
      capability:'read_only_evidence_inspection',
      method:'GET',
      path:'/api/n8n/operational/flows/'+flowId+'/inspect',
      executionStatus:'BLOCKED_PENDING_VERIFIED_HANDLER',
      officialEvidenceVerified:false,
      syntheticTestOnly:true,
      canDispatch:false,
      canBid:false
    });
  });
  for(const [prefix,count] of Object.entries(EXPECTED_PREFIX_COUNTS))assert(prefixes[prefix]===count,'incorrect '+prefix+' block count');
  assert(features.size===104&&REQUIRED_FEATURES.every(n=>features.has(n)),'missing one or more of 104 feature contracts');
  for(const b of adapters)for(const successor of b.successors)assert(seen.has(successor),'unknown successor '+b.operationId+' -> '+successor);
  assert(ownership.size===43,'orphan ownership entries');
  const native=catalog.filter(n=>n.implementation==='native').map(n=>({kind:n.kind,type:n.nativeType}));
  const unimplemented=catalog.filter(n=>n.implementation!=='native').map(n=>({
    kind:n.kind,implementation:n.implementation,executable:false,requires:'project verified n8n composite/extension adapter'
  }));
  return Object.freeze({
    schemaVersion:'procureflow.shared-n8n-contract.v1',
    engine:'official-n8n',
    source:'n8n/operational_manifest.json + pinned shared-n8n-studio catalog',
    native,
    unimplemented,
    adapters,
    verification:{
      kindCount:catalog.length,
      nativeCount:native.length,
      compositeCount:catalog.filter(n=>n.implementation==='composite').length,
      extensionCount:catalog.filter(n=>n.implementation==='extension').length,
      businessBlockCount:adapters.length,
      featureContractCount:features.size,
      runnableBusinessHandlers:0,
      realEvidenceRuns:0,
      status:'CONTRACT_ONLY_NOT_EXECUTION_VERIFIED'
    }
  });
}
if(process.argv[1] && import.meta.url===pathToFileURL(resolve(process.argv[1])).href) {
  const [manifestPath,catalogPath,outPath='shared-adapter-contracts.json']=process.argv.slice(2);
  assert(manifestPath&&catalogPath,'usage: node shared-adapter-contracts.mjs <manifest.json> <catalog.js> [output.json]');
  const manifest=JSON.parse(await readFile(manifestPath,'utf8'));
  const {NODE_CATALOG,validateCatalog}=await import(pathToFileURL(resolve(catalogPath)).href);
  validateCatalog();
  const registry=createAdapterRegistry(manifest,NODE_CATALOG);
  await writeFile(outPath,JSON.stringify(registry,null,2)+'\n');
  console.log('CONTRACT_CHECK_PASS '+JSON.stringify(registry.verification));
  console.log('CONTRACT_ARTIFACT '+outPath);
}
