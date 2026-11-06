import http from 'node:http';
import path from 'node:path';
import {readFile, stat} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'dist');
const port=Number(process.env.PORT||8080);
const upstream=process.env.BIDPICKER_BRIDGE_URL||'https://bidpicker-discovery-bridge-production.up.railway.app';
const allowed=new Set(['keyword','category','region','task_type','sort','page','size','deadline_soon','include_closed']);
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml','.ico':'image/x-icon','.png':'image/png','.woff2':'font/woff2'};
export function makeProxyUrl(localPath,search=''){
 if(!['/api/bidpicker/discover','/api/bidpicker/status'].includes(localPath))throw new Error('Not an approved read route');
 const url=new URL(localPath,upstream.endsWith('/')?upstream:upstream+'/');
 if(localPath==='/api/bidpicker/discover'){
  const params=new URLSearchParams(search);
  for(const [k,v] of params){if(allowed.has(k))url.searchParams.set(k,v.slice(0,160));}
  const page=Number(url.searchParams.get('page')||1),size=Number(url.searchParams.get('size')||10);
  if(!Number.isInteger(page)||page<1||page>1000||!Number.isInteger(size)||size<1||size>10)throw new Error('Search bounds exceeded');
 }
 return url.toString();
}
async function handler(req,res){
 const requestUrl=new URL(req.url||'/','http://localhost:'+port);
 res.setHeader('X-Content-Type-Options','nosniff');
 res.setHeader('Referrer-Policy','no-referrer');
 if(requestUrl.pathname.startsWith('/api/')){
  if(req.method!=='GET'){res.writeHead(405,{'Content-Type':'application/json'});res.end(JSON.stringify({detail:'Only GET allowed'}));return;}
  let target;
  try{target=makeProxyUrl(requestUrl.pathname,requestUrl.search);}catch(e){res.writeHead(400,{'Content-Type':'application/json'});res.end(JSON.stringify({detail:e.message}));return;}
  try{
   const r=await fetch(target,{method:'GET',headers:{Accept:'application/json'},signal:AbortSignal.timeout(12000)});
   const raw=(await r.text()).slice(0,400000);
   res.writeHead(r.status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});
   res.end(raw);
  }catch(e){res.writeHead(502,{'Content-Type':'application/json; charset=utf-8'});res.end(JSON.stringify({detail:'원본 수집 서비스 연결을 확인할 수 없습니다.'}));}
  return;
 }
 if(req.method!=='GET'&&req.method!=='HEAD'){res.writeHead(405);res.end();return;}
 const rel=requestUrl.pathname.replace(/^\/+/,'');
 const requested=path.resolve(root,rel);
 let file=requested.startsWith(root+path.sep) ? requested : path.join(root,'index.html');
 try{if(!(await stat(file)).isFile())file=path.join(root,'index.html');}catch(e){file=path.join(root,'index.html');}
 try{const content=await readFile(file);res.writeHead(200,{'Content-Type':types[path.extname(file)]||'application/octet-stream','Cache-Control':file.endsWith('index.html')?'no-store':'public,max-age=3600'});if(req.method==='HEAD')res.end();else res.end(content)}
 catch(e){res.writeHead(503);res.end('Build unavailable')}
}
if(process.env.NODE_ENV!=='test'){http.createServer(handler).listen(port,'0.0.0.0',()=>console.log('BidPicker mobile UI on '+port));}
