/**
 * Business Operation graft for the already-compiled official n8n PF graph.
 *
 * Run ONLY in an isolated official n8n candidate using its own installed
 * CUSTOM.procureFlowBusinessOperation node; do not change production
 * compiler or implement a second DAG engine.
 *
 * Every manifest business block remains represented by its original
 * read-only evidence Code inspector. The immediate successor is an official
 * n8n custom Business Operation node with two REAL output branches:
 * verified -> original downstream; HOLD -> terminal no-submission node.
 *
 * No official evidence is fabricated; no Worker jobs are enqueued.
 */
import {createHash} from 'node:crypto';
import {readFile,writeFile,rename} from 'node:fs/promises';
import path from 'node:path';

const source=process.env.PF_SOURCE||'/home/node';
const output=process.env.PF_OUTPUT||'/home/node/compiled-native';
const manifest=JSON.parse(await readFile(path.join(source,'procureflow-operational-manifest.json'),'utf8'));
if(manifest.engine!=='n8n_only'||manifest.blocks.length!==43||manifest.flows.length!==15)
  throw Error('Invalid ProcureFlow 43-block source manifest');
const operationIds=new Set(manifest.blocks.map(b=>b.id));
const idFor=x=>'bop'+createHash('sha256').update('shared-n8n-20261028|'+x).digest('hex').slice(0,30);
const ensure=(ok,msg)=>{if(!ok)throw Error('Shared business topology: '+msg);};
let count=0;
const report=[];
for(const flow of manifest.flows){
  const id=flow.id;
  const file=path.join(output,'operational',id+'.json');
  const w=JSON.parse(await readFile(file,'utf8'));
  const codes=[];
  if(flow.owned_blocks?.length){
    const holdName='HOLD · 공식 업무 증빙 미충족 — 입찰 제출 금지';
    ensure(!w.nodes.some(n=>n.name===holdName),id+': duplicate HOLD gate');
    // The terminal HOLD node must not spread untrusted input into persisted
    // n8n execution data. It may be reached by a future malformed graph or
    // a manually wired node, not just the sanitized Business Operation port.
    // Preserve only validated, manifest-owned identifiers; all decisions and
    // dispatch flags are generated as fixed fail-closed values.
    const holdCode=[
      'const v=$input.first()?.json??{};',
      'const allowed='+JSON.stringify(flow.owned_blocks)+';',
      "const operationId=allowed.includes(v.operation_id)?v.operation_id:null;",
      "const caseId=v.case_id==='R26BK01787028'?'R26BK01787028':null;",
      'return [{json:{',
      "schema_version:'procureflow.business-operation.hold.v1',",
      'case_id:caseId,bid_no:caseId,operation_id:operationId,flow_id:'+JSON.stringify(id)+',',
      "final_decision:'HOLD',workflow_status:'OFFICIAL_EVIDENCE_NOT_VERIFIED',",
      "inspection_status:'HOLD',evidence_verified:false,",
      "manual_review_required:true,read_only:true,",
      "automatic_bid_submission:false,automated_bid_submission:false,",
      "actual_job_executed:false,actual_business_handler_executed:false,",
      "job_enqueued:false,worker_job_enqueued:false,bid_submitted:false,output:null",
      '}}];'
    ].join('');
    const hold={
      id:idFor(id+'-hold'),
      name:holdName,
      type:'n8n-nodes-base.code',
      typeVersion:2,
      position:[8500,1150],
      parameters:{mode:'runOnceForAllItems',jsCode:holdCode},
      notes:'Unverified source is never an approved bid. Terminal branch; no automatic dispatch.',
      notesInFlow:true
    };
    w.nodes.push(hold);
    for(const operationId of flow.owned_blocks){
      ensure(operationIds.has(operationId),id+': unregistered '+operationId);
      const original=w.nodes.filter(n=>n.name.startsWith(operationId+' · ')&&n.type==='n8n-nodes-base.code');
      ensure(original.length===1,id+': missing unique original block '+operationId);
      const code=original[0];
      const outputs=w.connections[code.name]?.main?.[0];
      ensure(Array.isArray(outputs)&&outputs.length>0,id+': missing successor for '+operationId);
      const newName=operationId+' · Business Operation (공식 증빙 게이트)';
      ensure(!w.nodes.some(n=>n.name===newName),id+': duplicate native custom op');
      const custom={
        id:idFor(id+'-'+operationId),
        name:newName,
        type:'CUSTOM.procureFlowBusinessOperation',
        typeVersion:1,
        position:[code.position[0]+235,code.position[1]+165],
        parameters:{operationId,bidNo:'R26BK01787028',evidenceHandling:'hold'},
        notes:'Official n8n node; operationId from pinned 43-block manifest. Read-only by default; unavailable official evidence routes to HOLD. Real Worker execution is not claimed.',
        notesInFlow:true
      };
      w.nodes.push(custom);
      w.connections[code.name].main[0]=[{node:newName,type:'main',index:0}];
      w.connections[newName]={main:[
        outputs,
        [{node:holdName,type:'main',index:0}]
      ]};
      codes.push(operationId);
      count++;
    }
  }

  if(id==='PF05'){
    // The official custom Business Operation returns a sanitized verdict,
    // NOT its upstream workflow_trace. Restore a prior *native Code node*
    // output only after the custom gate has independently VERIFIED the exact
    // operation, flow and selected bid. Apply ONLY to the PF05 scope.
    const flowNodes=Object.fromEntries(flow.owned_blocks.map(blockId=>{
      const node=w.nodes.find(x=>x.name.startsWith(blockId+' · ')&&x.type==='n8n-nodes-base.code');
      if(!node)throw Error('PF05 missing business Code '+blockId);
      return [blockId,node];
    }));
    const upstreamOf={H02:'H01',H03:'H02',H04:'H03',H05:'H04',H06:'H04',H08:'H07'};
    for(const [blockId,prior] of Object.entries(upstreamOf)){
      const current=flowNodes[blockId],name=flowNodes[prior].name;
      const original=current.parameters.jsCode;
      ensure(original.startsWith('const prev=$input.first().json;'),'PF05 restore missing original '+blockId);
      current.parameters.jsCode=[
        "const gate=$input.first().json;",
        "if(gate.operation_id!=="+JSON.stringify(prior)+
          "||gate.flow_id!=='PF05'||gate.case_id!=='R26BK01787028'"+
          "||gate.inspection_status!=='VERIFIED'||gate.evidence_verified!==true"+
          ")throw Error('PF05_UPSTREAM_GATE_NOT_VERIFIED_"+blockId+"');",
        "const prev=$("+JSON.stringify(name)+").first().json;",
        "if(prev.case_id!==gate.case_id||prev.flow_id!==gate.flow_id||prev.last_block!=="+JSON.stringify(prior)+
          ")throw Error('PF05_UPSTREAM_TRACE_MISMATCH_"+blockId+"');",
        original.slice('const prev=$input.first().json;'.length)
      ].join('');
    }
    const joined=w.nodes.find(x=>x.name==='검증 H07 · 분기 결과 합치기');
    ensure(joined,'PF05 H07 verified native join not found');
    const h05=flowNodes.H05.name,h06=flowNodes.H06.name;
    joined.parameters.jsCode=[
      "const input=$input.all().map(x=>x.json);",
      "if(input.length!==2)throw Error('H07_GATE_MISSING_BRANCH');",
      "const gates=new Map();",
      "for(const g of input){",
      "if(!['H05','H06'].includes(g.operation_id)||gates.has(g.operation_id))throw Error('H07_GATE_DUPLICATE_OR_UNKNOWN');",
      "if(g.case_id!=='R26BK01787028'||g.flow_id!=='PF05'||g.inspection_status!=='VERIFIED'||g.evidence_verified!==true)throw Error('H07_GATE_NOT_VERIFIED');",
      "gates.set(g.operation_id,g);",
      "}",
      "if(!gates.has('H05')||!gates.has('H06'))throw Error('H07_GATE_MISSING_DEPENDENCY');",
      "const left=$("+JSON.stringify(h05)+").first().json;",
      "const right=$("+JSON.stringify(h06)+").first().json;",
      "if(left.case_id!=='R26BK01787028'||right.case_id!==left.case_id||left.flow_id!=='PF05'||right.flow_id!==left.flow_id||left.last_block!=='H05'||right.last_block!=='H06')throw Error('H07_ORIGINAL_OUTPUT_MISMATCH');",
      "if(!Array.isArray(left.workflow_trace)||!Array.isArray(right.workflow_trace))throw Error('H07_ORIGINAL_TRACE_MISSING');",
      "const records=new Map();",
      "for(const record of [...left.workflow_trace,...right.workflow_trace]){",
      "if(!record||typeof record.block_id!=='string')throw Error('H07_INVALID_TRACE');",
      "if(records.has(record.block_id)&&JSON.stringify(records.get(record.block_id))!==JSON.stringify(record))throw Error('H07_CONFLICTING_UPSTREAM_TRACE');",
      "records.set(record.block_id,record);",
      "}",
      "const ordered="+JSON.stringify(flow.owned_blocks)+";",
      "const trace=[...records.values()].sort((a,b)=>ordered.indexOf(a.block_id)-ordered.indexOf(b.block_id));",
      "const h05=records.get('H05'),h06=records.get('H06');",
      "if(!h05||!h06||!Object.prototype.hasOwnProperty.call(h05,'output')||!Object.prototype.hasOwnProperty.call(h06,'output'))throw Error('H07_SOURCE_OUTPUT_MISSING');",
      "return [{json:{...left,workflow_trace:trace,last_block:null,previous_block:null,dependency_inputs:{H05:h05.output,H06:h06.output},dependency_source_blocks:['H05','H06'],dependency_input_case_id:left.case_id,dependency_input_flow_id:'PF05',dependency_join_complete:true,dependency_evidence_verified:false}}];"
    ].join('');
    const terminal=w.nodes.find(x=>x.name.startsWith('최종 ·'));
    ensure(terminal&&terminal.parameters.jsCode.startsWith('const x=$input.first().json;'),'PF05 final gate missing');
    terminal.parameters.jsCode=[
      "const gate=$input.first().json;",
      "if(gate.operation_id!=='H08'||gate.flow_id!=='PF05'||gate.case_id!=='R26BK01787028'||gate.inspection_status!=='VERIFIED'||gate.evidence_verified!==true)throw Error('PF05_FINAL_H08_GATE_NOT_VERIFIED');",
      "const x=$("+JSON.stringify(flowNodes.H08.name)+").first().json;",
      "if(x.flow_id!==gate.flow_id||x.case_id!==gate.case_id||x.last_block!=='H08')throw Error('PF05_FINAL_SOURCE_MISMATCH');",
      terminal.parameters.jsCode.slice('const x=$input.first().json;'.length)
    ].join('');
  }
  const tmp=file+'.business.tmp';
  await writeFile(tmp,JSON.stringify(w,null,2)+'\n');
  await rename(tmp,file);
  report.push({flowId:id,operationIds:codes});
}
ensure(count===43,'must graft exactly 43 real native Business Operation nodes, got '+count);
const pf00=JSON.parse(await readFile(path.join(output,'operational','PF00.json'),'utf8'));
ensure(!pf00.nodes.some(n=>n.type==='CUSTOM.procureFlowBusinessOperation'),
  'PF00 coordinator must delegate through real native ExecuteWorkflow');
await writeFile(path.join(output,'business-operation-report.json'),
  JSON.stringify({source:'procureflow native n8n candidate',engine:'official-n8n',
    installedCustomNode:'CUSTOM.procureFlowBusinessOperation',
    operationIds:count,flows:report,readOnlyOnly:true,noBidSubmission:true},null,2)+'\n');
console.log('NATIVE_BUSINESS_OPERATION_43_GRAPH_PASS',JSON.stringify({count,flows:report.length}));
