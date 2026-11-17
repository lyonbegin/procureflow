/**
 * Legacy preview compatibility gateway.
 *
 * The separate Vue Flow viewer has been retired. There is exactly ONE
 * workflow editor: the official, access-controlled n8n studio.
 * This service does not load a graph, mutate workflows, or implement a DAG.
 */
import {createServer} from 'node:http';

const port=Number(process.env.PORT||3000);
const DEFAULT_EDITOR='https://procureflow-n8n-editor-gateway-production.up.railway.app';
const raw=(process.env.N8N_EDITOR_URL||DEFAULT_EDITOR).trim();
const ready=process.env.N8N_SHARED_EDITOR_VERIFIED==='1';
function editorUrl(){
  try{
    const u=new URL(raw);
    if(u.protocol!=='https:'&&!(u.protocol==='http:'&&['127.0.0.1','localhost'].includes(u.hostname)))return null;
    if(u.username||u.password||u.search||u.hash||u.pathname!=='/')return null;
    return u.origin;
  }catch{return null;}
}
const base=editorUrl();
const modes={
  operational:/^PF(?:0[1-9]|1[0-5])$/,
  scenarios:/^S(?:0[1-9]|10)$/
};
function pathFor(group,id) {
  if(!modes[group]?.test(id))return null;
  return group==='operational'?'/workflow/PFOP2026'+id+'WF':'/workflow/PFDEMO2026'+id+'WF';
}
function send(res,status,body,type='application/json; charset=utf-8',extra={}) {
  res.writeHead(status,{
    'Content-Type':type,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
    'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'",
    'X-Frame-Options':'DENY',...extra});
  res.end(typeof body==='string'?body:JSON.stringify(body));
}
function legacyLanding(){
  // The URL fragment is not visible to HTTP servers: only the one-time
  // browser redirector recognizes legacy #/operational/PF05 links.
  const encoded=JSON.stringify(base).replaceAll('<','\\u003c');
  return '<!doctype html><html lang="ko"><head><meta charset="utf-8">'+
    '<meta name="viewport" content="width=device-width,initial-scale=1">'+
    '<title>공식 n8n 편집기로 이동</title></head><body>'+
    '<p>별도 Vue Flow 미리보기는 종료되었습니다. 공식 n8n 편집기로 이동합니다.</p>'+
    '<p><a id="editor" rel="noopener noreferrer">공식 n8n 편집기 열기</a></p>'+
    '<script>const base='+encoded+';'+
    'let dest=base;const m=/^#\\/(operational|scenarios)\\/(PF(?:0[1-9]|1[0-5])|S(?:0[1-9]|10))$/.exec(location.hash);'+
    'if(m&&m[1]==="operational"&&m[2].startsWith("PF"))dest=base+"/workflow/PFOP2026"+m[2]+"WF";'+
    'else if(m&&m[1]==="scenarios"&&m[2].startsWith("S"))dest=base+"/workflow/PFDEMO2026"+m[2]+"WF";'+
    'document.getElementById("editor").href=dest;location.replace(dest);</script>'+
    '</body></html>';
}
createServer((req,res)=>{
  if(req.method!=='GET'&&req.method!=='HEAD')
    return send(res,405,{error:'READ_ONLY_EDITOR_REDIRECT'},'application/json; charset=utf-8',{'Allow':'GET, HEAD'});
  const pathname=new URL(req.url||'/','http://localhost').pathname;
  if(pathname==='/healthz')
    return send(res,200,{status:ready&&Boolean(base)?'official_editor_redirect_ready':'redirect_not_approved',
      engine:'official_n8n_only',retiredPreview:true,sharedEditorVerified:ready,configured:Boolean(base)});
  if(!ready||!base)
    return send(res,503,{error:'OFFICIAL_SHARED_N8N_EDITOR_NOT_VERIFIED',
      detail:'Do not expose an old Vue Flow editor or redirect to unverified n8n. Verify Pan patch and authenticated gateway first.'});
  if(pathname==='/api/catalog'||pathname.startsWith('/api/workflows/'))
    return send(res,410,{error:'RETIRED_DUPLICATE_VIEWER',editor:base});
  const m=/^\/(operational|scenarios)\/(PF(?:0[1-9]|1[0-5])|S(?:0[1-9]|10))$/.exec(pathname);
  if(m){
    const suffix=pathFor(m[1],m[2]);
    if(!suffix)return send(res,404,{error:'UNKNOWN_WORKFLOW'});
    return send(res,307,'','text/plain; charset=utf-8',{'Location':base+suffix});
  }
  if(pathname==='/')
    return send(res,200,legacyLanding(),'text/html; charset=utf-8');
  return send(res,307,'','text/plain; charset=utf-8',{'Location':base});
}).listen(port,'0.0.0.0',()=>console.log('ProcureFlow official n8n editor redirect on',port));
