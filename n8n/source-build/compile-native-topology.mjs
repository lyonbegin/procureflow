/**
 * ProcureFlow n8n native graph compiler.
 *  - Manifest is the source of block dependency truth.
 *  - Native n8n Merge, IF, Execute Sub-workflow; NO custom runtime / UI engine.
 *  - Input JSON is preserved and transformed deterministically at image build/startup.
 *  - Read-only by default; does not fake official collection or submit bids.
 */
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { createHash } from 'node:crypto';

const source = process.env.PF_SOURCE || '/home/node';
const target = process.env.PF_OUTPUT || '/home/node/compiled-native';
const manifest = JSON.parse(await readFile(join(source,'procureflow-operational-manifest.json'),'utf8'));
const idFor = x => 'pf'+createHash('sha256').update('procureflow-native-20261028|'+x).digest('hex').slice(0,30);
const link = (c,a,b,port=0,targetPort=0) => {
  (c[a] ??= {main:[]}).main[port] ??= [];
  c[a].main[port].push({node:b,type:'main',index:targetPort});
};
const codeNode = (name,js,x,y) => ({
  id:idFor(name),name,type:'n8n-nodes-base.code',typeVersion:2,
  position:[x,y],parameters:{mode:'runOnceForAllItems',jsCode:js}
});
const mergeNode = (name,inputs,x,y) => ({
  id:idFor(name),name,type:'n8n-nodes-base.merge',typeVersion:3.2,position:[x,y],
  parameters:{mode:'append',numberInputs:inputs}
});
const selector = (name,pf,x,y) => ({
  id:idFor(name),name,type:'n8n-nodes-base.executeWorkflow',typeVersion:1.3,position:[x,y],
  parameters:{source:'database',workflowId:{__rl:true,value:'PFOP2026'+pf+'WF',mode:'id'},
     mode:'once',options:{waitForSubWorkflow:true}}
});
const ifNode = (name,expr,x,y) => ({
  id:idFor(name),name,type:'n8n-nodes-base.if',typeVersion:2.2,position:[x,y],
  parameters:{conditions:{options:{caseSensitive:true,leftValue:'',typeValidation:'strict',version:2},
   combinator:'and',conditions:[{id:idFor(name+'-gate'),
       leftValue:'={{ '+expr+' }}',rightValue:true,
       operator:{type:'boolean',operation:'true',singleValue:true}}]},options:{}}
});
function pruneTransitive(ids,edges) {
  // Remove A->C only when an alternative A->...->C path already exists.
  return edges.filter(([a,b],index)=>{
    const other=edges.filter((_,i)=>i!==index);
    const found=new Set([a]);const stack=[a];
    while(stack.length){const k=stack.pop();for(const [x,y] of other)if(k===x&&!found.has(y)){found.add(y);stack.push(y)}}
    return !found.has(b);
  });
}
function sortedAcyclic(ids,edges,label) {
  const deg=Object.fromEntries(ids.map(x=>[x,0]));
  for(const [a,b] of edges){if(!(a in deg)||!(b in deg))throw Error(label+': invalid edge '+a+' -> '+b);deg[b]++}
  const queue=ids.filter(x=>!deg[x]),order=[];
  while(queue.length){const a=queue.shift();order.push(a);for(const [x,b] of edges)if(x===a&&!--deg[b])queue.push(b)}
  if(order.length!==ids.length)throw Error(label+': cyclic dependency');
  return order;
}
function combineCode(expectedIds) {
  const expected=JSON.stringify(expectedIds);
  return "const all=$input.all().map(x=>x.json);"
    +"if(all.length!=="+expectedIds.length+")throw Error('Missing required dependency branch');"
    +"const expected="+expected+";"
    +"const records=new Map();"
    +"for(const item of all){for(const rec of item.workflow_trace||[])records.set(rec.block_id,rec)}"
    +"const base=all[0];const trace=[...records.values()].sort((a,b)=>expected.indexOf(a.block_id)-expected.indexOf(b.block_id));"
    +"return [{json:{...base,workflow_trace:trace,previous_block:trace.at(-1)||null,dependency_join_verified:true}}];";
}
function enhanceFlow(w,f) {
  const ids=f.owned_blocks;
  if(!ids.length)return {workflow:w,stats:{id:f.id,blocks:0,parallel:0,merges:0}};
  const allBlocks=manifest.blocks.filter(b=>ids.includes(b.id));
  const internal=allBlocks.flatMap(b=>(b.to||[]).filter(t=>ids.includes(t)).map(t=>[b.id,t]));
  const edges=pruneTransitive(ids,internal);
  const order=sortedAcyclic(ids,edges,f.id);
  const nameOf=Object.fromEntries(ids.map(id=>[id,w.nodes.find(n=>n.name.startsWith(id+' · '))?.name]));
  for(const [id,name] of Object.entries(nameOf))if(!name)throw Error(f.id+': no actual n8n block '+id);
  const anchor=w.nodes.find(n=>n.name.startsWith('03 ·'))?.name;
  const final=w.nodes.find(n=>n.name.startsWith('최종 ·'))?.name;
  if(!anchor||!final)throw Error(f.id+': missing graph anchor/final');
  const old=w.connections;
  for(const name of Object.values(nameOf))delete old[name];
  delete old[anchor];
  const incoming=Object.fromEntries(ids.map(id=>[id,[]]));
  const outgoing=Object.fromEntries(ids.map(id=>[id,[]]));
  for(const [a,b] of edges){incoming[b].push(a);outgoing[a].push(b)}
  const roots=ids.filter(id=>!incoming[id].length);
  const terminals=ids.filter(id=>!outgoing[id].length);
  for(const id of roots)link(old,anchor,nameOf[id]);
  let joins=0;
  for(const id of ids) {
    if(incoming[id].length<=1) {
      if(incoming[id].length===1)link(old,nameOf[incoming[id][0]],nameOf[id]);
      continue;
    }
    joins++;
    const idx=order.indexOf(id);
    const mergeName='합류 '+id+' · 모든 선행 분기';
    const aggName='검증 '+id+' · 분기 결과 합치기';
    const merge=mergeNode(mergeName,incoming[id].length,1760+idx*450,670);
    const agg=codeNode(aggName,combineCode(ids),1920+idx*450,670);
    w.nodes.push(merge,agg);
    incoming[id].forEach((from,n)=>link(old,nameOf[from],mergeName,0,n));
    link(old,mergeName,aggName);
    link(old,aggName,nameOf[id]);
  }
  if(terminals.length===1)link(old,nameOf[terminals[0]],final);
  else {
    joins++;
    const m=mergeNode('합류 종료 · 모든 업무 블록 완료',terminals.length,4700,660);
    const a=codeNode('검증 종료 · 분기 기록 병합',combineCode(ids),4940,660);
    w.nodes.push(m,a);
    terminals.forEach((id,i)=>link(old,nameOf[id],m.name,0,i));
    link(old,m.name,a.name);
    link(old,a.name,final);
  }
  // Two entry points, manual and true n8n parent Execute Sub-workflow Trigger.
  const init=w.nodes.find(n=>n.name.startsWith('01 · 발주번호'));
  if(!init)throw Error(f.id+': missing case setup');
  init.parameters.jsCode="const incoming=$input.first()?.json??{};"
    +"const bid_no=incoming.bid_no||'R26BK01787028';"
    +"if(bid_no!=='R26BK01787028')throw Error('This instance is restricted to the selected bid until multi-case support is verified');"
    +"return [{json:{flow_id:'"+f.id+"',bid_no,mode:'inspect',"
    +"read_only:true,source:incoming.source||'n8n_native_entry',"
    +"root_execution_id:incoming.root_execution_id||null}}];";
  const trig={id:idFor(f.id+' subworkflow trigger'),name:'↳ 상위 PF 실행 호출',
    type:'n8n-nodes-base.executeWorkflowTrigger',typeVersion:1.1,
    position:[500,65],parameters:{inputSource:'passthrough'}};
  w.nodes.push(trig);link(old,trig.name,init.name);
  // Spread nodes vertically, with separate lanes for forks and proper join positions.
  const level=Object.fromEntries(roots.map(id=>[id,0]));
  for(const id of order)for(const next of outgoing[id])level[next]=Math.max(level[next]||0,(level[id]||0)+1);
  const lanes={};
  for(const id of order){const lev=level[id]||0;lanes[lev]??=[];lanes[lev].push(id)}
  for(const [str,group] of Object.entries(lanes)){
    const lev=Number(str);
    group.forEach((id,i)=>{
      const node=w.nodes.find(n=>n.name===nameOf[id]);
      node.position=[1760+lev*475,330+(i-(group.length-1)/2)*360];
    });
  }
  w.name=w.name.replace('· 실제 증빙 검사','· 병렬·선행조건 반영');
  w.tags=[];w.active=false;
  return {workflow:w,stats:{id:f.id,blocks:ids.length,branchPoints:Object.values(outgoing).filter(v=>v.length>1).length,merges:joins,roots:roots.length,terminals:terminals.length,edges:edges.length}};
}
const before=codeNode('01 · 선택 발주·실행 모드 검증',
  "const v=$input.first()?.json||{};"
   +"const bid_no=v.bid_no||'R26BK01787028';"
   +"if(bid_no!=='R26BK01787028')throw Error('Unsupported case');"
   +"return [{json:{bid_no,mode:'inspect',read_only:true,source:'PF00_coordinator',root_execution_id:$execution.id}}];",500,400);
const wf={id:'PFORCH2026MAINWF',name:'[운영 PF00] 실제 업무 의존성·병렬 합류 상위 오케스트레이터',
 active:false,settings:{executionOrder:'v1',saveManualExecutions:true,saveDataSuccessExecution:'all',saveDataErrorExecution:'all',timezone:'Asia/Seoul'},
 nodes:[{id:idFor('PF00 manual'),name:'▶ 선택 발주 전체 흐름 실행',type:'n8n-nodes-base.manualTrigger',typeVersion:1,
  position:[230,400],parameters:{}},
 {id:idFor('PF00 sub'),name:'↳ 다른 n8n 워크플로가 호출',type:'n8n-nodes-base.executeWorkflowTrigger',
  typeVersion:1.1,position:[230,160],parameters:{inputSource:'passthrough'}},before],connections:{}};
link(wf.connections,'▶ 선택 발주 전체 흐름 실행',before.name);
link(wf.connections,'↳ 다른 n8n 워크플로가 호출',before.name);
const calls=[
['PF01','02 · 신규 공고 이력 확인',800,390],
['PF04','03 · 공식 공고·첨부 증빙',1140,390],
['PF02','04 · 적합성·발주 조건 판단',1480,390],
['PF03','05 · 작업 배정',1820,390],
['PF05','06A · 10년 개찰·낙찰 전수',2250,20],
['PF06','07A · 기관·경쟁업체 분석',2670,20],
['PF07','06B · 입찰 자격 검증',2250,390],
['PF08','06C · 공급업체·인력 견적',2250,760],
['PF09','09 · 원가·가격전략',3930,390],
['PF10','10 · 입찰 제안서·서류',4290,390],
['PF11','11 · 독립 근거 감사',4650,390],
['PF12','12 · 사람의 참여 검토 대기',5020,390]];
const lookup=Object.fromEntries(calls.map(([id,n,x,y])=>[id,n]));
wf.nodes.push(...calls.map(([id,n,x,y])=>selector(n,id,x,y)));
for(const [a,b] of [['PF01','PF04'],['PF04','PF02'],['PF02','PF03'],
 ['PF03','PF05'],['PF05','PF06'],['PF03','PF07'],['PF03','PF08'],
 ['PF09','PF10'],['PF10','PF11'],['PF11','PF12']])
 link(wf.connections,lookup[a],lookup[b]);
link(wf.connections,before.name,lookup.PF01);
const merge3=mergeNode('08 · 병렬 결과 3계열 합류',3,3090,390);
wf.nodes.push(merge3);
[lookup.PF06,lookup.PF07,lookup.PF08].forEach((n,i)=>link(wf.connections,n,merge3.name,0,i));
const judge=codeNode('08A · 10년·자격·견적 증빙 게이트',
"const items=$input.all().map(i=>i.json);"
+"const expected=['PF06','PF07','PF08'];"
+"const seen=new Set(items.map(x=>x.flow_id));"
+"const missing=expected.filter(x=>!seen.has(x));"
+"const pending=items.filter(x=>!(x.business_state==='VERIFIED'||x.workflow_status==='ALL_OFFICIAL_EVIDENCE_VERIFIED'));"
+"const pass=!missing.length&&!pending.length;"
+"return [{json:{bid_no:'R26BK01787028',root_execution_id:$execution.id,eligible_for_downstream:pass,"
+"read_only:true,missing_flows:missing,pending_flows:pending.map(x=>({flow_id:x.flow_id,status:x.business_state||x.plan_status||'PENDING'})),"
+"completed_parallel_flows:[...seen],bid_submitted:false}}];",3350,390);
wf.nodes.push(judge);link(wf.connections,merge3.name,judge.name);
const gate=ifNode('08B · 실제 선행 증빙 모두 충족?','$json.eligible_for_downstream === true',3590,390);
wf.nodes.push(gate);link(wf.connections,judge.name,gate.name);
link(wf.connections,gate.name,lookup.PF09,0);
const hold=codeNode('보류 · 근거 미충족 또는 검토 대기',
 "const d=$input.first().json;return [{json:{...d,state:'HOLD',reason:'REQUIRED_EVIDENCE_NOT_VERIFIED',manual_review_required:true,bid_submitted:false}}];",4000,750);
wf.nodes.push(hold);link(wf.connections,gate.name,hold.name,1);
const finish=codeNode('최종 · 입찰 자동 제출 금지',
"const x=$input.first().json;return [{json:{...x,automation_status:'READY_FOR_HUMAN_REVIEW_ONLY',bid_submitted:false}}];",5480,390);
wf.nodes.push(finish);link(wf.connections,lookup.PF12,finish.name);
const resultDir=join(target,'operational');
await mkdir(resultDir,{recursive:true});
const stats=[];
for(let n=1;n<=15;n++){
 const id='PF'+String(n).padStart(2,'0');
 const f=manifest.flows.find(x=>x.id===id);
 const w=JSON.parse(await readFile(join(source,'procureflow-operational-workflows',id+'.json'),'utf8'));
 const changed=enhanceFlow(w,f);stats.push(changed.stats);
 await writeFile(join(resultDir,id+'.json'),JSON.stringify(changed.workflow,null,2));
}
await writeFile(join(resultDir,'PF00.json'),JSON.stringify(wf,null,2));
const diag={generatedAt:'2026-10-28',compiler:'procureflow-native-topology-v2',
 operationalWorkflows:16,featureContracts:104,blocks:43,
 controller:{id:wf.id,nodes:wf.nodes.length,branches:['PF05+PF07+PF08'],waitForAll:true,missingGate:'HOLD'},
 stats};
await writeFile(join(target,'topology-report.json'),JSON.stringify(diag,null,2));
console.log('[procureflow topology]',JSON.stringify(diag));
