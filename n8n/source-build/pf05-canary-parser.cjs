#!/usr/bin/env node
'use strict';
// CLI execution validator for isolated PF05 canary.
// Parses actual n8n CLI IRun.data.resultData.runData, NOT strings in workflow definitions.
// Never prints notice payloads or personal bidder information.
const fs=require('node:fs');
function jsonObjects(text){
  let depth=0,start=-1,inString=false,escaped=false;
  for(let i=0;i<text.length;i++){
    const c=text[i];
    if(!depth){
      if(c==='{'){depth=1;start=i;inString=false;escaped=false}
      continue;
    }
    if(inString){
      if(escaped)escaped=false;
      else if(c==='\\')escaped=true;
      else if(c==='"')inString=false;
    }else if(c==='"')inString=true;
    else if(c==='{')depth++;
    else if(c==='}'){
      depth--;
      if(!depth){
        try{yieldParsed.push(JSON.parse(text.slice(start,i+1)))}catch{}
        start=-1;
      }
    }
  }
  return yieldParsed;
}
const yieldParsed=[];
function findCliRun(raw){
  const candidates=jsonObjects(raw);
  return candidates.reverse().find(c=>c?.data?.resultData?.runData && typeof c.data.resultData.runData==='object')||null;
}
function nodeData(rd,name){
  const runs=rd[name];
  if(!Array.isArray(runs)||runs.length!==1)return {ok:false,reason:'NODE_NOT_RUN_EXACTLY_ONCE'};
  const run=runs[0];
  const items=run?.data?.main?.[0];
  if(run?.executionStatus!=='success'||!Array.isArray(items)||items.length!==1||!items[0]?.json)
    return {ok:false,reason:'NODE_OUTPUT_UNAVAILABLE'};
  return {ok:true,status:run.executionStatus,json:items[0].json};
}
function equal(a,b){return JSON.stringify(a)===JSON.stringify(b)}
function verdict(raw,workflowId,exitCode){
 const parsed=findCliRun(raw),rd=parsed?.data?.resultData?.runData;
 const names={H02:'H02 · 10년 기간 분할',H05:'H05 · 실제 개찰·투찰 상세',H06:'H06 · 확정 낙찰결과',H07:'H07 · 10년 개찰·낙찰 완전성'};
 const v=Object.fromEntries(Object.entries(names).map(([id,name])=>[id,rd?nodeData(rd,name):{ok:false,reason:'N8N_RUN_DATA_NOT_FOUND'}]));
 const h07=v.H07?.json,joined=h07?.previous_block?.input?.upstream;
 const h05record=v.H05?.json?.previous_block;
 const h06record=v.H06?.json?.previous_block;
 const h02record=v.H02?.json?.previous_block;
 const sameCase=!!(v.H05?.json?.case_id &&
    v.H05.json.case_id===v.H06?.json?.case_id &&
    v.H05.json.case_id===h07?.case_id);
 const summary={
   workflow_id:workflowId,execution_source:'n8n_cli_irun_resultdata_rundata',
   cli_exit:exitCode,run_status:parsed?.status||null,
   h02_executed:v.H02.ok,h05_executed:v.H05.ok,h06_executed:v.H06.ok,h07_executed:v.H07.ok,
   same_case_id:sameCase,
   h07_received_h05_output:!!(joined && h05record?.block_id==='H05' && equal(joined.opening_and_bidders,h05record.output)),
   h07_received_h06_output:!!(joined && h06record?.block_id==='H06' && equal(joined.awards,h06record.output)),
   h07_received_h02_output:!!(joined && h02record?.block_id==='H02' && equal(joined.search_windows,h02record.output)),
   structural_join_complete:h07?.dependency_join_complete===true,
   official_evidence_verified:h07?.dependency_evidence_verified===true,
   output_is_read_only:h07?.actual_job_executed===false,
   bid_submitted:false,worker_job_enqueued:false,
   execution_id:null, // CLI's IRun does not include workflowRunner.run() executionId.
   note:'No full 10-year collection or award validation is implied by a dataflow PASS.'
 };
 summary.pass=exitCode===0&&Object.values(v).every(x=>x.ok)&&
    sameCase&&summary.h07_received_h05_output&&summary.h07_received_h06_output&&
    summary.h07_received_h02_output&&summary.structural_join_complete&&
    !summary.official_evidence_verified&&summary.output_is_read_only&&
    parsed?.data?.resultData?.error==null;
 return summary;
}
function selfTest(){
 const common={case_id:'R26BK01787028',flow_id:'PF05',actual_job_executed:false,dependency_join_complete:true,dependency_evidence_verified:false};
 const blocks={
 H02:{block_id:'H02',output:{search_windows:[{id:'window1'}]}},
 H05:{block_id:'H05',output:{opening_records:[{id:'open1'}]}},
 H06:{block_id:'H06',output:{award_records:[{id:'award1'}]}}
 };
 const j={...common,previous_block:{block_id:'H07',input:{upstream:{
  opening_and_bidders:blocks.H05.output,awards:blocks.H06.output,search_windows:blocks.H02.output}}}};
 const mk=value=>[{executionStatus:'success',data:{main:[[{json:value}]]}}];
 const make=(overrides={})=>({data:{resultData:{runData:{
  'H02 · 10년 기간 분할':mk({...common,previous_block:blocks.H02}),
  'H05 · 실제 개찰·투찰 상세':mk({...common,previous_block:blocks.H05}),
  'H06 · 확정 낙찰결과':mk({...common,previous_block:blocks.H06}),
  'H07 · 10년 개찰·낙찰 완전성':mk(j),...overrides
 }}}});
 const realFixture=(obj)=>'n8n startup log\nExecution was successful:\n====================================\n'+JSON.stringify(obj,null,2)+'\n';
 const success=verdict(realFixture(make()),'CANARY',0);
 if(!success.pass)throw Error('PF05_PARSER_SELFTEST_GOOD_INPUT_FAILED '+JSON.stringify(success));
 const ghost=verdict(realFixture({nodes:[{name:'H05 · 실제 개찰·투찰 상세',parameters:{jsCode:'dependency_join_complete:true'}}]}),'CANARY',0);
 if(ghost.pass||ghost.h05_executed)throw Error('PF05_PARSER_SELFTEST_FALSE_POSITIVE');
 const missing=make({'H06 · 확정 낙찰결과':[]});
 if(verdict(realFixture(missing),'CANARY',0).pass)throw Error('PF05_PARSER_SELFTEST_MISSING_BRANCH');
 const crossed=make({'H06 · 확정 낙찰결과':mk({...common,case_id:'OTHER',previous_block:blocks.H06})});
 if(verdict(realFixture(crossed),'CANARY',0).pass)throw Error('PF05_PARSER_SELFTEST_CROSS_CASE');
 const wrong=make({'H07 · 10년 개찰·낙찰 완전성':mk({...j,previous_block:{block_id:'H07',input:{upstream:{...j.previous_block.input.upstream,awards:{award_records:[]}}}}})});
 if(verdict(realFixture(wrong),'CANARY',0).pass)throw Error('PF05_PARSER_SELFTEST_WRONG_JOIN');
 console.log('PF05_CANARY_N8N_RUNDATA_STRUCTURAL_PARSER_SELFTEST_PASS');
}
if(require.main===module){
 if(process.argv.includes('--self-test'))selfTest();
 else{
   const [file,id,exit]=process.argv.slice(2);
   if(!file||!id||exit===undefined)throw Error('usage: parser <file> <workflow_id> <exit>');
   const summary=verdict(fs.readFileSync(file,'utf8'),id,Number(exit));
   console.log('PF05_NATIVE_N8N_RUN_DATA '+JSON.stringify(summary));
   console.log(summary.pass?'PF05_NATIVE_H05_H06_H07_STRUCTURAL_IO_PASS':'PF05_NATIVE_H05_H06_H07_STRUCTURAL_IO_FAIL');
 }
}
module.exports={findCliRun,verdict};
