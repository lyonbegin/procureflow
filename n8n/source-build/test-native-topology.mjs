import { readFile, readdir } from 'node:fs/promises';
import { join } from 'node:path';
import { runInNewContext } from 'node:vm';
const base=process.env.PF_OUTPUT||'/home/node/compiled-native';
const manifest=JSON.parse(await readFile(join(process.env.PF_SOURCE||'/home/node','procureflow-operational-manifest.json'),'utf8'));
const dir=join(base,'operational');
const files=(await readdir(dir)).filter(x=>/^PF(?:0[0-9]|1[0-5])\.json$/.test(x)).sort();
const check=(x,msg)=>{if(!x)throw Error('Topology invalid: '+msg)};
check(files.length===16,'need PF00-PF15, got '+files.length);
const collected=[];
for(const file of files){
  const w=JSON.parse(await readFile(join(dir,file),'utf8'));
  const known=new Set(w.nodes.map(n=>n.name));
  const id=file.slice(0,4);
  check(w.active===false,id+': unexpected automatic activation');
  for(const [from,o] of Object.entries(w.connections||{})){
    check(known.has(from),id+': invalid edge source '+from);
    for(const routes of Object.values(o))for(const port of routes)for(const dest of port)
      check(known.has(dest.node),id+': invalid edge destination '+dest.node);
  }
  const merge=w.nodes.filter(n=>n.type==='n8n-nodes-base.merge');
  const sub=w.nodes.filter(n=>n.type==='n8n-nodes-base.executeWorkflow');
  if(id!=='PF00'){
    const f=manifest.flows.find(f=>f.id===id);
    const blocks=w.nodes.filter(n=>f.owned_blocks.some(b=>n.name.startsWith(b+' ·')));
    check(blocks.length===f.owned_blocks.length,id+': missing/duplicate block');
    check(w.nodes.some(n=>n.type==='n8n-nodes-base.executeWorkflowTrigger'),id+': subflow entry absent');
    if(id==='PF05'){
      const h04=w.nodes.find(n=>n.name.startsWith('H04 ·'));
      const edges=w.connections[h04.name].main[0].map(x=>x.node);
      check(edges.some(e=>e.startsWith('H05 ·'))&&edges.some(e=>e.startsWith('H06 ·')),
        'PF05 H04 must branch to H05 and H06');
      check(merge.length>0,'PF05 requires native Merge');
      // Evaluate the EXACT generated n8n Code node using the n8n $input
      // contract. This test runs locally at build time, NOT in production n8n.
      const hJoin=w.nodes.find(n=>n.name==='검증 H07 · 분기 결과 합치기');
      const hMerge=w.nodes.find(n=>n.name==='합류 H07 · 모든 선행 분기');
      const h07node=w.nodes.find(n=>n.name.startsWith('H07 · '));
      check(hJoin&&hMerge&&h07node,'PF05 H07 requires merge + join check + business node');
      check(hMerge.parameters.numberInputs===2,'H07 Merge must have exactly two n8n inputs');
      const fromH05=w.connections['H05 · 실제 개찰·투찰 상세']?.main?.[0]||[];
      const fromH06=w.connections['H06 · 확정 낙찰결과']?.main?.[0]||[];
      check(fromH05.some(x=>x.node===hMerge.name&&x.index===0),'H05 must feed H07 merge port 0');
      check(fromH06.some(x=>x.node===hMerge.name&&x.index===1),'H06 must feed H07 merge port 1');
      check(w.connections[hJoin.name]?.main?.[0]?.some(x=>x.node===h07node.name),'H07 must receive checked joined data');
      const runCode=(js,items)=>runInNewContext(
        '(function(){'+js+'})()',{$input:{all:()=>items.map(json=>({json})),first:()=>({json:items[0]})}},
        {timeout:1000})[0].json;
      const prefix=[
        {block_id:'H01',output:{detail10:'8111159901'}},
        {block_id:'H02',output:{search_windows:[{from:'2016-10-24',to:'2026-10-22'}]}},
        {block_id:'H03',output:{}},
        {block_id:'H04',output:{verified_historical_notices:[]}}
      ];
      const make=(id,caseId='R26BK01787028')=>({
        case_id:caseId,bid_no:caseId,flow_id:'PF05',source_provenance:'live_procureflow_postgresql_verified_evidence',
        last_block:id,previous_block:{block_id:id},
        workflow_trace:[...prefix,{block_id:id,output:id==='H05'?{opening_records:[{notice:'A'}],bidder_records:[]}:{award_records:[{notice:'A'}]}}],
        blocks:[{id:'H07',name:'10년 개찰·낙찰 완전성',input:'opening+award+windows',output_value:null,next_blocks:['H08'],features:[],status:'blocked'}]
      });
      const verified=runCode(hJoin.parameters.jsCode,[make('H05'),make('H06')]);
      check(verified.dependency_join_complete===true&&verified.dependency_evidence_verified===false,'structural join may not imply evidence verification');
      check(verified.dependency_inputs.H05.opening_records.length===1&&verified.dependency_inputs.H06.award_records.length===1,'joined outputs lost');
      const h07result=runCode(h07node.parameters.jsCode,[verified]);
      const h07last=h07result.previous_block;
      check(h07last.block_id==='H07','H07 stage identity missing');
      check(h07last.input.upstream.opening_and_bidders.opening_records.length===1,'H05 actual output missing from H07');
      check(h07last.input.upstream.awards.award_records.length===1,'H06 actual output missing from H07');
      check(h07last.input.upstream.search_windows.search_windows.length===1,'H02 windows missing from H07');
      check(h07last.actual_job_executed===false&&h07result.dependency_evidence_verified===false,'evidence incorrectly verified');
      const mustFail=(items,reason)=>{
        let failed=false;
        try{runCode(hJoin.parameters.jsCode,items)}
        catch(e){failed=String(e).includes(reason)}
        check(failed,'PF05 join must reject '+reason);
      };
      mustFail([make('H05')],'JOIN_MISSING_DEPENDENCY_ITEM');
      mustFail([make('H05'),make('H05')],'JOIN_DUPLICATE_OR_UNEXPECTED_BRANCH');
      mustFail([make('H05'),make('H06','R26BK00000000')],'JOIN_CROSS_CASE');
      const inconsistent=make('H06');inconsistent.workflow_trace[0]={block_id:'H01',output:{detail10:'wrong'}};
      mustFail([make('H05'),inconsistent],'JOIN_INCONSISTENT_SHARED_ANCESTRY');
      let noWindows={...verified,workflow_trace:verified.workflow_trace.filter(x=>x.block_id!=='H02')};
      let missingRejected=false;
      try{runCode(h07node.parameters.jsCode,[noWindows])}catch(e){missingRejected=String(e).includes('H07_SEARCH_WINDOWS_MISSING')}
      check(missingRejected,'H07 must reject missing H02 windows');
      console.log('PF05_H05_H06_H07_NATIVE_MERGE_INPUT_OUTPUT_GATE_PASS');

    }
    if(id==='PF07'||id==='PF09')check(merge.length>0,id+': missing parallel join');
  } else {
    check(sub.length===12,'PF00 missing native Execute Workflow calls');
    check(merge.some(m=>m.parameters.numberInputs===3),'PF00 missing 3-way join');
    check(w.nodes.some(n=>n.type==='n8n-nodes-base.if'),'PF00 missing evidence gate');
  }
  collected.push({id,nodes:w.nodes.length,merges:merge.length,executeWorkflow:sub.length});
}
const report={passed:true,compiledWorkflows:collected.length,
  totalNodes:collected.reduce((s,x)=>s+x.nodes,0),
  mergeNodes:collected.reduce((s,x)=>s+x.merges,0),
  nativeSubworkflowCalls:collected.reduce((s,x)=>s+x.executeWorkflow,0),
  audit:collected};
console.log('[procureflow native topology smoke]',JSON.stringify(report));
