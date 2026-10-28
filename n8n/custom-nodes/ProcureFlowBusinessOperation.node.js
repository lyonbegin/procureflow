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
  if(body.flow_id!==flowId||body.case_id!==bidNo||body.read_only!==true||
     body.simulation_only!==false||body.actual_job_executed!==false||
     body.source_provenance!=='live_procureflow_postgresql_verified_evidence')
    throw Error('Business Operation official evidence response contract mismatch');
  const block=body.blocks?.find(x=>x.id===operationId);
  if(!block||block.real_data!==true||block.simulation_only!==false||
     block.job_enqueued!==false)
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
    inputs:['main'],outputs:['main'],
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
    const result=[];
    for(let i=0;i<input.length;i++){
      const operationId=this.getNodeParameter('operationId',i);
      const bidNo=this.getNodeParameter('bidNo',i);
      const evidenceHandling=this.getNodeParameter('evidenceHandling',i);
      const block=byId.get(operationId);
      if(!block)throw Error('Unregistered Business Operation ID '+String(operationId));
      if(bidNo!=='R26BK01787028')throw Error('Unsupported tender: official single-case gate');
      const response=await this.helpers.httpRequest({
        method:'GET',
        url:base+'/api/n8n/operational/flows/'+block.flowId+'/inspect',
        qs:{bid_no:bidNo},
        timeout:30000,
        json:true
      });
      const inspected=validateProvenance(response,block.flowId,bidNo,operationId);
      const verified=inspected.status==='verified'&&
         inspected.output_value?.evidence_verified===true&&
         inspected.features?.length===block.features.length&&
         inspected.features.every(x=>x.acceptance==='verified'&&x.missing_gates?.length===0);
      const item={json:{
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
      result.push(item);
    }
    return [result];
  }
}
module.exports={ProcureFlowBusinessOperation,validateProvenance,safeApiBase};
