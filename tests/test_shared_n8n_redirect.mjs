import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';

const FILE='n8n/native-preview/server.mjs';
const BASE='http://127.0.0.1:18756';
async function launch(extra={}) {
  const child=spawn(process.execPath,[FILE],{
    env:{...process.env,PORT:'18756',
      N8N_EDITOR_URL:'https://procureflow-n8n-editor-gateway-production.up.railway.app',
      ...extra}, stdio:['ignore','pipe','pipe']
  });
  let failed='';
  child.stderr.on('data',c=>{failed+=String(c)});
  for(let n=0;n<60;n++){
    if(child.exitCode!==null)throw Error('server stopped '+failed);
    try{const response=await fetch(BASE+'/healthz',{signal:AbortSignal.timeout(500)});
      if(response.ok)return child;
    }catch{}
    await new Promise(r=>setTimeout(r,100));
  }
  child.kill('SIGKILL');
  throw Error('healthz timeout '+failed);
}
async function close(child){
  child.kill('SIGTERM');
  await once(child,'exit').catch(()=>{});
}
async function req(path) {
  const r=await fetch(BASE+path,{redirect:'manual'});
  return {r,content:await r.text()};
}
test('legacy Vue Flow disabled until the shared official n8n image is verified',async()=>{
 const child=await launch({N8N_SHARED_EDITOR_VERIFIED:'0'});
 try{
   const h=await req('/healthz');const j=JSON.parse(h.content);
   assert.equal(j.retiredPreview,true);assert.equal(j.sharedEditorVerified,false);
   for(const url of ['/','/operational/PF05','/api/catalog','/api/workflows/operational/PF05']){
     assert.equal((await req(url)).r.status,503,url);
   }
 }finally{await close(child);}
});
test('official n8n only: no duplicate graph renderer; safe workflow deep links',async()=>{
 const child=await launch({N8N_SHARED_EDITOR_VERIFIED:'1'});
 try{
   const h=JSON.parse((await req('/healthz')).content);
   assert.equal(h.sharedEditorVerified,true);
   assert.equal(h.engine,'official_n8n_only');
   const old=await req('/api/catalog');
   assert.equal(old.r.status,410);assert.equal(JSON.parse(old.content).error,'RETIRED_DUPLICATE_VIEWER');
   const oldNode=await req('/api/workflows/operational/PF05');assert.equal(oldNode.r.status,410);
   for(const [route,target] of [
     ['/operational/PF05','/workflow/PFOP2026PF05WF'],
     ['/operational/PF15','/workflow/PFOP2026PF15WF'],
     ['/scenarios/S01','/workflow/PFDEMO2026S01WF'],
     ['/scenarios/S10','/workflow/PFDEMO2026S10WF'],
   ]){
     const x=await req(route);
     assert.equal(x.r.status,307,route);
     assert.equal(x.r.headers.get('location'),'https://procureflow-n8n-editor-gateway-production.up.railway.app'+target);
   }
   assert.equal((await req('/operational/PF99')).r.status,307);
   const root=await req('/');assert.equal(root.r.status,200);
   assert.match(root.content,/location\.replace\(dest\)/);
   assert.doesNotMatch(root.content,/vue-flow|VueFlow|react-flow|dagre|d3/i);
 }finally{await close(child);}
});
test('reject invalid editor origins: no open redirects through env or query',async()=>{
 const child=await launch({N8N_SHARED_EDITOR_VERIFIED:'1',N8N_EDITOR_URL:'https://attacker.example/?next=https://valid.example'});
 try{assert.equal((await req('/')).r.status,503);}finally{await close(child);}
});
