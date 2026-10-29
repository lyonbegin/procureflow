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
  // A Railway suffix alone would permit reading from unrelated internal services.
  // An operator must explicitly pin the exact approved internal API DNS name.
  const approvedInternalHost=process.env.PROCUREFLOW_APPROVED_INTERNAL_API_HOST||'';
  // An exact hostname still has multiple TCP services. Never let an imported
  // workflow or environment URL select an arbitrary Railway internal port.
  // For non-default internal ports, require a second explicit operator pin.
  const approvedInternalPort=process.env.PROCUREFLOW_APPROVED_INTERNAL_API_PORT||'';
  // An approved internal hostname and TCP port are not a complete origin:
  // pin the scheme as well, defaulting to Railway's private HTTP transport.
  // HTTPS requires an explicit operator choice, never a workflow override.
  const approvedInternalScheme=process.env.PROCUREFLOW_APPROVED_INTERNAL_API_SCHEME||'http';
  const effectivePort=url.port||(url.protocol==='https:'?'443':'80');
  const internalPortAllowed=approvedInternalPort
    ? /^(?:[1-9][0-9]{0,4})$/.test(approvedInternalPort)&&
      Number(approvedInternalPort)<=65535&&
      effectivePort===approvedInternalPort
    : !url.port;
  const internal=process.env.PROCUREFLOW_ALLOW_INTERNAL_READONLY==='1'&&
    approvedInternalHost.endsWith('.railway.internal')&&
    url.hostname===approvedInternalHost&&internalPortAllowed&&
    ['http','https'].includes(approvedInternalScheme)&&
    url.protocol===approvedInternalScheme+':';
  // Use a numeric loopback address for the synthetic fixture. A hostname such
  // as localhost can be remapped by hosts/DNS in a runner or container and
  // would make a purportedly isolated test call leave the test boundary.
  // Even 127.0.0.1 has unrelated local services (including test DBs and
  // metadata proxies). Pin the synthetic HTTP fixture's exact TCP port;
  // a loopback hostname alone is not a safe read-only execution boundary.
  const approvedTestFixturePort=process.env.PROCUREFLOW_APPROVED_TEST_FIXTURE_PORT||'5855';
  const testPortAllowed=/^[1-9][0-9]{0,4}$/.test(approvedTestFixturePort)&&
    Number(approvedTestFixturePort)<=65535&&url.port===approvedTestFixturePort;
  const local=url.protocol==='http:'&&url.hostname==='127.0.0.1'&&
    process.env.PROCUREFLOW_OPERATION_TEST_MODE==='1'&&testPortAllowed;
  // The public read-only origin is HTTPS on its standard port only. A
  // hostname match on a caller-selected port is not the approved API origin.
  const publicHost=url.protocol==='https:'&&url.hostname==='procureflow-api-production.up.railway.app'&&!url.port;
  // Synthetic fixture mode is loopback-only: never allow a test-mode node to
  // contact a Railway production/internal API, even if its origin is allowlisted.
  if(process.env.PROCUREFLOW_OPERATION_TEST_MODE==='1'&&!local)
    throw Error('Business Operation test mode requires isolated loopback origin');
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
// Evidence key names are identifiers, not free-form upstream messages. Never
// echo untrusted URLs, request errors or credentials into execution output.
const SAFE_EVIDENCE_KEYS=new Set([
  'official_source','official_notice','official_detail10',
  'official_opening','official_award','official_bid_no',
  'official_evidence','official_10_digit_code'
]);
function safeMissingEvidenceKeys(value){
  if(!Array.isArray(value))return ['invalid_evidence_keys'];
  // Even a syntactically valid upstream identifier can be a secret. Only
  // explicitly reviewed diagnostic codes may be copied into n8n run logs.
  const keys=value.map(x=>SAFE_EVIDENCE_KEYS.has(x)?x:'redacted_evidence_key');
  return [...new Set(keys)].slice(0,100);
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
      // Imported workflows can bypass the editor's options dropdown. Reject
      // unknown modes before contacting even the read-only evidence API.
      if(evidenceHandling!=='stop'&&evidenceHandling!=='hold')
        throw Error('Business Operation evidence handling mode blocked');
      const block=byId.get(operationId);
      if(!block)throw Error('Unregistered Business Operation ID');
      if(bidNo!=='R26BK01787028'||(upstream.bid_no&&upstream.bid_no!==bidNo))throw Error('Unsupported tender: official single-case gate');
      let response;
      try{
        response=await this.helpers.httpRequest({
          method:'GET',
          // Never follow a 3xx off the allowlisted read-only origin.
          // n8n's HTTP helper otherwise follows redirects by default.
          disableFollowRedirect:true,
          url:base+'/api/n8n/operational/flows/'+block.flowId+'/inspect',
          qs:{bid_no:bidNo},
          timeout:30000,
          json:true
        });
      }catch{
        // Provider error bodies can contain serviceKey and request headers.
        // A generic fail-closed error keeps secrets out of native n8n logs.
        throw Error('Business Operation '+operationId+': read-only evidence request failed');
      }
      const inspected=validateProvenance(response,block.flowId,bidNo,operationId);
      // Match the exact manifest feature IDs, not merely the number of rows:
      // a foreign feature with the same row count must never be approved.
      const features=Array.isArray(inspected.features)?inspected.features:[];
      const expectedFeatures=new Set(block.features);
      const verified=process.env.PROCUREFLOW_OPERATION_TEST_MODE!=='1'&&
         response.source_provenance==='live_procureflow_postgresql_verified_evidence'&&
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
        // Deliberately do not spread upstream JSON into native execution
        // results: arbitrary input can contain credentials, private bidder
        // data, or unknown approval flags. Only the selected case identifier
        // crosses this read-only evidence-inspection boundary.
        bid_no:bidNo,
        // All decision/dispatch fields are generated here, never inherited.
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
        missing_evidence:safeMissingEvidenceKeys(inspected.output_value?.missing_evidence_keys),
        // Even a verified read-only API response is untrusted for n8n logs:
        // never propagate arbitrary output_value keys (credentials, bidder
        // details, or forged submission/approval flags) to downstream nodes.
        // The inspection adapter exposes only a fixed evidence verdict.
        output:verified?{
          evidence_verified:true,
          real_api_result_state:'verified',
          missing_evidence_keys:[]
        }:null,
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
