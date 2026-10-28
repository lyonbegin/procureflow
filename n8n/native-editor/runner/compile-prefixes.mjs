// Compile immutable S01-S10 LINEAR prefix workflows for genuine n8n CLI
// run-to-node tests. Every step invocation runs ancestors again; NOT pause/resume.
// No arbitrary browser-provided workflow data ever enters the runner.
import {readFile,readdir,mkdir,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
const src='/opt/procureflow-scenarios',dest='/tmp/procureflow-native-step-fixtures';
await mkdir(dest,{recursive:true});
let count=0;
for(let n=1;n<=10;n++){
 const id='S'+String(n).padStart(2,'0');
 const w=JSON.parse(await readFile(join(src,id+'.json'),'utf8'));
 const byName=new Map(w.nodes.map(x=>[x.name,x]));
 const next=new Map(), incoming=new Map(w.nodes.map(x=>[x.name,0]));
 for(const [a,outputs] of Object.entries(w.connections||{})){
   const dests=Object.values(outputs).flat(2).filter(Boolean).map(x=>x.node);
   if(dests.length>1)throw Error('Partial run restricted to linear scenario: '+id);
   if(dests.length===1){next.set(a,dests[0]);incoming.set(dests[0],incoming.get(dests[0])+1)}
 }
 const roots=[...incoming].filter(([name,edges])=>!edges).map(([name])=>name);
 if(roots.length!==1)throw Error('Invalid scenario roots '+id);
 const order=[];let cur=roots[0];
 while(cur&&!order.includes(cur)){order.push(cur);cur=next.get(cur)}
 if(order.length!==w.nodes.length||cur)throw Error('Scenario graph non-linear '+id);
 for(let k=1;k<=order.length;k++){
   const chosen=new Set(order.slice(0,k));
   const c=JSON.parse(JSON.stringify(w));
   c.id='PFDEMO2026'+id+'P'+String(k).padStart(2,'0');
   c.name='['+id+'] n8n safe run-to-node '+k+'/'+order.length;
   c.active=false;
   c.nodes=w.nodes.filter(x=>chosen.has(x.name));
   c.connections={};
   for(const [a,o] of Object.entries(w.connections||{}))if(chosen.has(a)){
     const filtered=Object.fromEntries(Object.entries(o).map(([t,groups])=>
       [t,groups.map(g=>g.filter(e=>chosen.has(e.node)))]));
     if(Object.values(filtered).some(groups=>groups.some(g=>g.length)))c.connections[a]=filtered;
   }
   await writeFile(join(dest,id+'-'+String(k).padStart(2,'0')+'.json'),JSON.stringify(c));
   count++;
 }
 console.log('[native prefix fixture]',id,'totalNodes',order.length);
}
console.log('[native prefix fixture] COMPILED',count,'immutable n8n workflow prefixes');
