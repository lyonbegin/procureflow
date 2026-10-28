'use strict';
/**
 * Official n8n custom node — ONE Business Operation kind with 43 allowlisted
 * ProcureFlow operationId choices. This is an inspect-only adapter, not a
 * second DAG engine, bid executor, or fabricated G2B data generator.
 *
 * Distribution: N8N_CUSTOM_EXTENSIONS=/home/node/procureflow-custom-nodes
 * Source of truth: copied official n8n/operational_manifest.json.
 */
const {readFileSync}=require('node:fs');
const {join}=require('node:path');

const manifest=JSON.parse(readFileSync(join(__dirname,'operational_manifest.json'),'utf8'));
if(manifest.engine!=='n8n_only'||manifest.blocks.length!==43||manifest.flows.length!==15)
  throw Error('Business Operation: invalid manifest / engine');
const owners=new Map();
for(const flow of manifest.flows){
  for(const id of flow.owned_blocks||[]){
    if(owners.has(id))throw Error('Business Operation: duplicate block owner '+id);
    owners.set(id,flow.id);
  }
}
const byId=new Map(manifest.blocks.map(block=>[block.id,{...block,flowId:owners.get(block.id)}]));
if(byId.size!==43||[...byId.values()].some(x=>!x.flowId||!x.features?.length))
  throw Error('Business Operation: missing operationId owner or feature contract');

function safeApiBase(){
  const raw=process.env.PROCUREFLOW_OPERATION_API_BASE||'';
  if(!raw)throw Error('Business Operation is disabled: explicit read-only API base required');
  let url;
  try{url=new URL(raw)}catch{throw Error('Business Operation API base invalid')}
  const internal=url.hostname.endsWith('.railway.internal')&&process.env.PROCUREFLOW_ALLOW_INTERNAL_READONLY==='1';
  const local=['localhost','127.0.0.1'].includes(url.hostname)&&process.env.PROCUREFLOW_OPERATION_TEST_MODE==='1';
  const publicHost=url.protocol==='https:'&&url.hostname==='procureflow-api-production.up.railway.app';
  if(!(publicHost||internal||local)||url.username||url.password||url.search||url.hash||url.pathname!=='/')
    throw Error('Business Operation read-only API origin blocked');
  if(!['https:','http:'].includes(url.protocol)||url.protocol==='http:'&&!(internal||local))
    throw Error('Business Operation TLS or private-network policy blocked');
  return url.origin;
}
function validateProvenance(body,flowId,bidNo,operationId){
  // A synthetic HTTP fixture is allowed ONLY in an explicitly isolated test
  // runtime. It must declare itself synthetic and can never become VERIFIED.
  const synthetic=process.env.PROCUREFLOW_OPERATION_TEST_MODE==='1'&&
    body?.source_provenance==='isolated_synthetic_test_evidence';
  if(!body||typeof body!=='object'||Array.isArray(body)||
     body.flow_id!==flowId||body.case_id!==bidNo||body.read_only!==true||
     body.simulation_only!==synthetic||body.actual_job_executed!==false||
     body.automatic_bid_submission!==false||
     body.workflow_execution_engine!=='native_n8n_only'||
     (!synthetic&&body.source_provenance!=='live_procureflow_postgresql_verified_evidence'))
    throw Error('Business Operation official evidence response contract mismatch');
  const matches=Array.isArray(body.blocks)?
    body.blocks.filter(x=>x&&x.id===operationId):[];
  const expected=byId.get(operationId);
  if(matches.length!==1||!expected)throw Error('Business Operation unique block contract mismatch');
  const block=matches[0];
  if(block.real_data!==(synthetic?false:true)||block.simulation_only!==synthetic||
     block.job_enqueued!==false||block.input!==expected.input||
     block.output!==expected.output)
    throw Error('Business Operation block/official evidence contract mismatch');
  return block;
}
class ProcureFlowBusinessOperation {
  description={
    displayName:'Business Operation · ProcureFlow',
    name:'procureFlowBusinessOperation',
    group:['transform'],
    version:1,
    description:'One of 43 allowlisted procurement operations. Read-only evidence gate; never automatically submits bids.',
    defaults:{name:'Business Operation',color:'#177d83'},
    inputs:['main'],outputs:['main','main'],outputNames:['success','hold_or_error'],
    properties:[
      {displayName:'Operation ID',name:'operationId',type:'options',
       options:[...byId.values()].map(x=>({name:x.id+' · '+x.label,value:x.id})),
       default:'N01',required:true,
       description:'Fixed operationId from n8n/operational_manifest.json; no arbitrary URLs or code'},
      {displayName:'Selected Official Tender',name:'bidNo',type:'string',
       default:'R26BK01787028',required:true,
       description:'Only the existing single selected G2B tender is currently supported'},
      {displayName:'Evidence Handling',name:'evidenceHandling',type:'options',
       options:[{name:'Stop workflow when unverified (recommended)',value:'stop'},
                {name:'Return HOLD status, never mark complete',value:'hold'}],
       default:'stop',
       description:'n8n execution success does not imply official business evidence acceptance'}
    ]
  };
  async execute(){
    if(process.env.PROCUREFLOW_BUSINESS_READONLY_ENABLED!=='1')
      throw Error('Business Operation disabled until authenticated official n8n rollout is approved');
    const base=safeApiBase();
    const input=this.getInputData();
    const passed=[],held=[];
    for(let i=0;i<input.length;i++){
      const upstream=input[i]?.json||{};
      const operationId=this.getNodeParameter('operationId',i);
      const bidNo=this.getNodeParameter('bidNo',i);
      const evidenceHandling=this.getNodeParameter('evidenceHandling',i);
      const block=byId.get(operationId);
      if(!block)throw Error('Unregistered Business Operation ID '+String(operationId));
      if(bidNo!=='R26BK01787028'||(upstream.bid_no&&upstream.bid_no!==bidNo))throw Error('Unsupported tender: official single-case gate');
      const response=await this.helpers.httpRequest({
        method:'GET',
        url:base+'/api/n8n/operational/flows/'+block.flowId+'/inspect',
        qs:{bid_no:bidNo},
        timeout:30000,
        json:true
      });
      const inspected=validateProvenance(response,block.flowId,bidNo,operationId);
      // Match the exact manifest feature IDs, not merely the number of rows:
      // a foreign feature with the same row count must never be approved.
      const features=Array.isArray(inspected.features)?inspected.features:[];
      const expectedFeatures=new Set(block.features);
      const verified=response.source_provenance==='live_procureflow_postgresql_verified_evidence'&&
         response.official_notice_verified===true&&
         (!['PF05','PF06'].includes(block.flowId) ||
           (response.business_state==='VERIFIED'&&Array.isArray(response.official_detail10)&&response.official_detail10.length>0))&&
         inspected.status==='verified'&&
         inspected.output_value?.evidence_verified===true&&
         inspected.output_value?.real_api_result_state==='verified'&&
         Array.isArray(inspected.output_value?.missing_evidence_keys)&&
         inspected.output_value.missing_evidence_keys.length===0&&
         features.length===expectedFeatures.size&&
         new Set(features.map(x=>x.feature_no)).size===expectedFeatures.size&&
         features.every(x=>expectedFeatures.has(x.feature_no)&&
           x.acceptance==='verified'&&Array.isArray(x.missing_gates)&&
           x.missing_gates.length===0);
      const item={json:{
        ...upstream,
        // Upstream payloads are untrusted. Never let an earlier node's
        // approval/dispatch flags survive this inspection-only boundary.
        final_decision:'HOLD',
        manual_review_required:true,
        workflow_status:'OFFICIAL_EVIDENCE_INSPECTION_ONLY',
        read_only:true,
        automatic_bid_submission:false,
        automated_bid_submission:false,
        actual_job_executed:false,
        job_enqueued:false,
        schema_version:'procureflow.business-operation.v1',
        adapter:'procureflow',operation_id:operationId,
        flow_id:block.flowId,case_id:bidNo,
        feature_ids:block.features,
        input_contract:block.input,output_contract:block.output,
        execution_engine:'official_n8n',
        operation_kind:'read_only_evidence_inspection',
        actual_business_handler_executed:false,
        inspection_status:verified?'VERIFIED':'HOLD',
        evidence_provenance:response.source_provenance,
        evidence_verified:verified,
        missing_evidence:inspected.output_value?.missing_evidence_keys||[],
        output:verified?inspected.output_value:null,
        bid_submitted:false,
        worker_job_enqueued:false
      },pairedItem:{item:i}};
      if(!verified&&evidenceHandling!=='hold')
        throw Error('Business Operation '+operationId+' held: official evidence incomplete');
      if(verified)passed.push(item);
      else held.push(item);
    }
    return [passed,held];
  }
}
module.exports={ProcureFlowBusinessOperation,validateProvenance,safeApiBase};
