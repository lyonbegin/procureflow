import { readFile, readdir } from 'node:fs/promises';
import { join } from 'node:path';
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
