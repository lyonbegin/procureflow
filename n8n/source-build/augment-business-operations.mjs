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
    const hold={
      id:idFor(id+'-hold'),
      name:holdName,
      type:'n8n-nodes-base.code',
      typeVersion:2,
      position:[8500,1150],
      parameters:{mode:'runOnceForAllItems',jsCode:
        "const v=$input.first().json;return [{json:{...v,final_decision:'HOLD',"+
        "workflow_status:'OFFICIAL_EVIDENCE_NOT_VERIFIED',"+
        "manual_review_required:true,bid_submitted:false,automated_bid_submission:false}}];"},
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
