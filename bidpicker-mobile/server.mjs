import http from 'node:http';
import path from 'node:path';
import {readFile,stat} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'dist');
const port=Number(process.env.PORT||8080);
// Python FastAPI is our existing independent fresh official-site G2B collector.
// Never contact pickersoft.com or use the unrelated, unauthorized BidPicker bridge.
export const FRESH_G2B_FASTAPI_URL=process.env.FRESH_G2B_FASTAPI_URL||
  'https://fresh-g2b-site-center-production.up.railway.app';
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8',
 '.css':'text/css; charset=utf-8','.svg':'image/svg+xml','.ico':'image/x-icon',
 '.png':'image/png','.woff2':'font/woff2'};
const allowed=new Set(['keyword','region','category','task_type','sort','page','size',
 'deadline_soon','include_closed']);
const validator=/^\/api\/bidpicker\/detail\/(R\d{2}[A-Z]{2}\d{8}|\d{11})\/(\d{3})$/;

export function makeProxyUrl(localPath,search=''){
 let endpoint;
 if(localPath==='/api/bidpicker/status'||localPath==='/api/bidpicker/diagnostics')
  endpoint='/health';
 else if(localPath==='/api/bidpicker/discover')endpoint='/api/mobile/notices';
 else{
   const match=localPath.match(validator);
   if(!match)throw Error('Not an approved official G2B read-only route');
   endpoint='/api/mobile/notices/'+match[1]+'/'+match[2];
 }
 const target=new URL(endpoint,FRESH_G2B_FASTAPI_URL);
 if(endpoint==='/api/mobile/notices'){
   for(const [key,val] of new URLSearchParams(search)){
     if(allowed.has(key)){
       if(val.length>160)throw Error('Search value too long');
       target.searchParams.set(key,val);
     }
   }
   const page=Number(target.searchParams.get('page')||1);
   const size=Number(target.searchParams.get('size')||10);
   if(!Number.isInteger(page)||page<1||page>200||!Number.isInteger(size)||size<1||size>50)
     throw Error('Search page/size out of bounds');
 }
 return target.toString();
}

export function normalizeFreshResponse(raw,httpStatus,contentType){
 if(httpStatus<200||httpStatus>=300){
   try{return {httpStatus,body:JSON.stringify(JSON.parse(raw))};}
   catch{return {httpStatus,body:JSON.stringify({
      detail:'우리 나라장터 FastAPI가 HTTP '+httpStatus+' 응답을 반환했습니다.',
      upstream_http_status:httpStatus,source:'fresh_g2b_fastapi'})};}
 }
 if(!String(contentType||'').toLowerCase().includes('json'))
   return {httpStatus:502,body:JSON.stringify({
     detail:'우리 나라장터 FastAPI의 JSON 응답 형식이 올바르지 않습니다.'})};
 try{
   const data=JSON.parse(raw);
   if(data===null||typeof data!=='object')throw Error('not object');
   return {httpStatus:200,body:JSON.stringify(data)};
 }catch{return {httpStatus:502,body:JSON.stringify({
    detail:'우리 나라장터 FastAPI의 응답을 해석할 수 없습니다.'})};}
}

async function handler(req,res){
 const requestUrl=new URL(req.url||'/','http://localhost:'+port);
 res.setHeader('X-Content-Type-Options','nosniff');
 res.setHeader('Referrer-Policy','no-referrer');
 if(requestUrl.pathname.startsWith('/api/')){
   if(req.method!=='GET'){res.writeHead(405,{'Content-Type':'application/json'});
     res.end(JSON.stringify({detail:'Only read-only GET requests allowed'}));return;}
   let target;
   try{target=makeProxyUrl(requestUrl.pathname,requestUrl.search);}
   catch(e){res.writeHead(400,{'Content-Type':'application/json'});
     res.end(JSON.stringify({detail:e.message}));return;}
   try{
     const response=await fetch(target,{
       method:'GET',headers:{Accept:'application/json'},
       redirect:'manual',signal:AbortSignal.timeout(14000)});
     if(response.status>=300&&response.status<400){
       res.writeHead(502,{'Content-Type':'application/json'});
       res.end(JSON.stringify({detail:'나라장터 FastAPI가 예상하지 못한 경로로 이동했습니다.'}));return;
     }
     const raw=(await response.text()).slice(0,1200000);
     const out=normalizeFreshResponse(raw,response.status,response.headers.get('content-type'));
     res.writeHead(out.httpStatus,{'Content-Type':'application/json; charset=utf-8',
       'Cache-Control':'no-store','X-Source':'fresh-g2b-fastapi'});
     res.end(out.body);
     console.log(JSON.stringify({event:'fresh_g2b_fastapi_request',
       route:requestUrl.pathname,status:out.httpStatus,bytes:out.body.length}));
   }catch(e){
     res.writeHead(502,{'Content-Type':'application/json; charset=utf-8',
       'Cache-Control':'no-store'});
     res.end(JSON.stringify({detail:'나라장터 수집 FastAPI에 연결할 수 없습니다.',
       error_type:e?.name||'NetworkError'}));
     console.log(JSON.stringify({event:'fresh_g2b_connection_failed',
       route:requestUrl.pathname,error_type:e?.name||'NetworkError'}));
   }
   return;
 }
 if(req.method!=='GET'&&req.method!=='HEAD'){res.writeHead(405);res.end();return;}
 const rel=requestUrl.pathname.replace(/^\/+/,'');
 const requested=path.resolve(root,rel);
 let file=requested.startsWith(root+path.sep)?requested:path.join(root,'index.html');
 try{if(!(await stat(file)).isFile())file=path.join(root,'index.html');}
 catch{file=path.join(root,'index.html');}
 try{const content=await readFile(file);res.writeHead(200,{
    'Content-Type':types[path.extname(file)]||'application/octet-stream',
    'Cache-Control':file.endsWith('index.html')?'no-store':'public,max-age=3600'});
    if(req.method==='HEAD')res.end();else res.end(content);
 }catch{res.writeHead(503);res.end('Build unavailable');}
}
if(process.env.NODE_ENV!=='test')
 http.createServer(handler).listen(port,'0.0.0.0',
  ()=>console.log('Mobile G2B FastAPI client listening on '+port));
