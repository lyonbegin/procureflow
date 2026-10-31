/**
 * Strict JSON Schema 2020-12 contracts for the ONLY currently implemented
 * ProcureFlow n8n adapter: read-only evidence inspection.
 *
 * These schemas DO NOT describe 43 real procurement business handlers.
 * They cannot authorize Worker jobs, bids, or production rollout.
 */
import {readFile,writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';

const K='https://json-schema.org/draft/2020-12/schema';
const literal=(value)=>({const:value});
const flag=(value)=>({type:'boolean',const:value});
const text=(value)=>({type:'string',const:value});
const SAFE_KEYS=[
  'official_source','official_notice','official_detail10','official_opening',
  'official_award','official_bid_no','official_evidence',
  'official_10_digit_code','invalid_evidence_keys','redacted_evidence_key'
];
const BID='R26BK01787028';
const object=(properties)=>({
  type:'object',additionalProperties:false,
  required:Object.keys(properties),properties
});
const heldOutput={type:'null'};
const verifiedOutput=object({
  evidence_verified:flag(true),
  real_api_result_state:text('verified'),
  missing_evidence_keys:{type:'array',maxItems:0}
});
export function createInspectionEnvelopeSchemas(manifest){
  if(manifest?.engine!=='n8n_only'||manifest?.flows?.length!==15||
     manifest?.blocks?.length!==43)
    throw Error('inspection schema requires the official 15-flow/43-block manifest');
  const owners=new Map();
  for(const flow of manifest.flows){
    if(!/^PF(0[1-9]|1[0-5])$/.test(flow.id))throw Error('invalid flow');
    for(const id of flow.owned_blocks??[]){
      if(owners.has(id))throw Error('duplicate owner: '+id);
      owners.set(id,flow.id);
    }
  }
  const seen=new Set();
  const schemas=manifest.blocks.map(block=>{
    if(seen.has(block.id)||!owners.has(block.id)||
       !/^(N(0[1-9]|10)|H(0[1-9]|1[01])|Q0[1-5]|S0[1-4]|P0[1-7]|R0[1-2]|O0[1-4])$/.test(block.id)||
       !Array.isArray(block.features)||block.features.length===0||
       !block.features.every(Number.isInteger)||
       typeof block.input!=='string'||!block.input||
       typeof block.output!=='string'||!block.output)
      throw Error('invalid inspection operation contract: '+block.id);
    seen.add(block.id);
    const flowId=owners.get(block.id);
    const params=object({
      operationId:text(block.id),
      bidNo:text(BID),
      evidenceHandling:{type:'string',enum:['stop','hold']}
    });
    const result=object({
      bid_no:text(BID),
      final_decision:text('HOLD'),
      manual_review_required:flag(true),
      workflow_status:text('OFFICIAL_EVIDENCE_INSPECTION_ONLY'),
      read_only:flag(true),
      automatic_bid_submission:flag(false),
      automated_bid_submission:flag(false),
      actual_job_executed:flag(false),
      job_enqueued:flag(false),
      schema_version:text('procureflow.business-operation.v1'),
      adapter:text('procureflow'),
      operation_id:text(block.id),
      flow_id:text(flowId),
      case_id:text(BID),
      feature_ids:literal(block.features),
      input_contract:text(block.input),
      output_contract:text(block.output),
      execution_engine:text('official_n8n'),
      operation_kind:text('read_only_evidence_inspection'),
      actual_business_handler_executed:flag(false),
      inspection_status:{type:'string',enum:['HOLD','VERIFIED']},
      evidence_provenance:{type:'string',enum:[
        'isolated_synthetic_test_evidence',
        'live_procureflow_postgresql_verified_evidence'
      ]},
      evidence_verified:{type:'boolean'},
      missing_evidence:{
        type:'array',maxItems:100,uniqueItems:true,
        items:{type:'string',enum:SAFE_KEYS}
      },
      output:{oneOf:[heldOutput,verifiedOutput]},
      bid_submitted:flag(false),
      worker_job_enqueued:flag(false)
    });
    result.allOf=[
      {if:{properties:{inspection_status:literal('HOLD')}},
       then:{properties:{evidence_verified:flag(false),output:heldOutput}}},
      {if:{properties:{inspection_status:literal('VERIFIED')}},
       then:{properties:{
         evidence_verified:flag(true),
         evidence_provenance:text('live_procureflow_postgresql_verified_evidence'),
         missing_evidence:{type:'array',maxItems:0},
         output:verifiedOutput
       }}}
    ];
    return {
      operationId:block.id,flowId,
      inputParameters:{$schema:K,$id:'urn:procureflow:inspection:params:'+block.id,...params},
      outputItem:{$schema:K,$id:'urn:procureflow:inspection:result:'+block.id,...result},
      actualBusinessHandler:false,
      status:'INSPECTION_ENVELOPE_ONLY'
    };
  });
  if(seen.size!==43||owners.size!==43)throw Error('incomplete inspection schema coverage');
  return {
    schemaVersion:'procureflow.inspection-envelope-schemas.v1',
    scope:'READ_ONLY_INSPECTION_NOT_BUSINESS_HANDLER',
    actualBusinessHandlersWithStrictPayloadSchemas:0,
    count:schemas.length,schemas
  };
}
if(process.argv[1]&&import.meta.url===pathToFileURL(resolve(process.argv[1])).href){
  const [manifestPath,outPath='shared-inspection-envelope-schemas.json']=process.argv.slice(2);
  if(!manifestPath)throw Error('usage: inspection-envelope-schemas.mjs <manifest.json> [output.json]');
  const manifest=JSON.parse(await readFile(manifestPath,'utf8'));
  const result=createInspectionEnvelopeSchemas(manifest);
  await writeFile(outPath,JSON.stringify(result,null,2)+'\n');
  console.log('INSPECTION_ENVELOPE_SCHEMA_PASS '+JSON.stringify({
    count:result.count,actualBusinessHandlersWithStrictPayloadSchemas:0,
    scope:result.scope
  }));
}
