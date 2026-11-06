import http from 'node:http';
import path from 'node:path';
import {readFile,stat} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'dist');
const port=Number(process.env.PORT||8080);
// Original app's Retrofit baseUrl from the supplied XAPK.
// Do not make a separate Bridge's invented credential gate a prerequisite for the original GET.
export const BIDPICKER_ORIGINAL_ROOT='https://www.pickersoft.com/bidpicker-api/';
const bridge=process.env.BIDPICKER_BRIDGE_URL||'https://bidpicker-discovery-bridge-production.up.railway.app';
const queryMap={keyword:'keyword',category:'category',region:'region',task_type:'taskType',
  status:'status',deadline_soon:'deadlineSoon',include_closed:'includeClosed',
  sort:'sort',page:'page',size:'size'};
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml','.ico':'image/x-icon','.png':'image/png','.woff2':'font/woff2'};
export function makeProxyUrl(localPath,search=''){
 if(localPath==='/api/bidpicker/status') return new URL('/api/bidpicker/status',bridge).toString();
 let pathPart;
 if(localPath==='/api/bidpicker/discover')pathPart='api/bids';
 else if(localPath==='/api/bidpicker/trending')pathPart='api/trending-keywords';
 else if(/^\/api\/bidpicker\/detail\/[A-Za-z0-9_.-]{1,120}$/.test(localPath)){
   pathPart='api/bids/'+localPath.slice('/api/bidpicker/detail/'.length);
 }else throw new Error('Not an approved GET source route');
 const url=new URL(pathPart,BIDPICKER_ORIGINAL_ROOT);
 const params=new URLSearchParams(search);
 if(pathPart==='api/bids'){
   for(const [key,value] of params){
     const mapped=queryMap[key];
     if(mapped){ if(value.length>160)throw new Error('Search parameter too long');url.searchParams.set(mapped,value); }
   }
   const page=Number(url.searchParams.get('page')||1),size=Number(url.searchParams.get('size')||10);
   if(!Number.isInteger(page)||page<1||page>1000||!Number.isInteger(size)||size<1||size>10)throw new Error('Search bounds exceeded');
 }else if(pathPart==='api/trending-keywords'){
   const category=params.get('category');
   if(category){if(category.length>160)throw new Error('Category too long');url.searchParams.set('category',category);}
 }
 return url.toString();
}

export function buildUpstreamHeaders(target,credentials=process.env){
 const headers={Accept:'application/json','User-Agent':'BidPicker-Mobile-UI/1.0'};
 if(target.startsWith(BIDPICKER_ORIGINAL_ROOT)){
   const user=credentials.BIDPICKER_UPSTREAM_USERNAME;
   const password=credentials.BIDPICKER_UPSTREAM_PASSWORD;
   if(user && password && !/[\r\n]/.test(user+password)){
     headers.Authorization='Basic '+Buffer.from(user+':'+password,'utf8').toString('base64');
   }
 }
 return headers;
}

export function normalizeUpstream(raw,httpStatus,contentType){
 // Never turn upstream 401 into the invented "credentials not connected" 503.
 if(httpStatus<200||httpStatus>=300){
   return {httpStatus,body:JSON.stringify({detail:'원본 입찰공고 알리미 API가 HTTP '+httpStatus+' 응답을 반환했습니다.',upstream_http_status:httpStatus,source:'original_bidpicker_api'})};
 }
 if(!String(contentType||'').toLowerCase().includes('json'))
   return {httpStatus:502,body:JSON.stringify({detail:'원본 API가 JSON이 아닌 응답을 반환했습니다.',upstream_http_status:httpStatus})};
 try{
   const obj=JSON.parse(raw);
   if(obj===null||typeof obj!=='object')throw Error('not object');
   return {httpStatus,body:JSON.stringify(obj)};
 }catch{return {httpStatus:502,body:JSON.stringify({detail:'원본 API의 JSON 응답을 해석할 수 없습니다.',upstream_http_status:httpStatus})};}
}

async function handler(req,res){
 const requestUrl=new URL(req.url||'/','http://localhost:'+port);
 res.setHeader('X-Content-Type-Options','nosniff');
 res.setHeader('Referrer-Policy','no-referrer');
 if(requestUrl.pathname.startsWith('/api/')){
   if(req.method!=='GET'){res.writeHead(405,{'Content-Type':'application/json'});res.end(JSON.stringify({detail:'Only GET allowed'}));return;}
   let target;
   try{target=makeProxyUrl(requestUrl.pathname,requestUrl.search);}catch(e){
      res.writeHead(400,{'Content-Type':'application/json'});res.end(JSON.stringify({detail:e.message}));return;
   }
   try{
     const response=await fetch(target,{method:'GET',headers:buildUpstreamHeaders(target),
       redirect:'manual',signal:AbortSignal.timeout(14000)});
     if(response.status>=300&&response.status<400){
       res.writeHead(502,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});
       res.end(JSON.stringify({detail:'원본 API가 리다이렉트했습니다.',upstream_http_status:response.status}));return;
     }
     const raw=(await response.text()).slice(0,1200000);
     const normalized=normalizeUpstream(raw,response.status,response.headers.get('content-type'));
     res.writeHead(normalized.httpStatus,{'Content-Type':'application/json; charset=utf-8',
        'Cache-Control':'no-store','X-Source':'bidpicker-original-api'});
     res.end(normalized.body);
     console.log(JSON.stringify({event:'source_request',path:requestUrl.pathname,
       upstream_http_status:response.status,result_http_status:normalized.httpStatus,received_bytes:raw.length,auth_challenge:response.status===401?response.headers.get('www-authenticate')||'not_provided':undefined}));
   }catch(e){
     res.writeHead(502,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});
     res.end(JSON.stringify({detail:'원본 API 연결 중 네트워크 오류가 발생했습니다.',error_type:e?.name||'NetworkError'}));
     console.log(JSON.stringify({event:'source_request_failed',path:requestUrl.pathname,error_type:e?.name||'NetworkError'}));
   }
   return;
 }
 if(req.method!=='GET'&&req.method!=='HEAD'){res.writeHead(405);res.end();return;}
 const rel=requestUrl.pathname.replace(/^\/+/,'');
 const requested=path.resolve(root,rel);
 let file=requested.startsWith(root+path.sep)?requested:path.join(root,'index.html');
 try{if(!(await stat(file)).isFile())file=path.join(root,'index.html');}catch{file=path.join(root,'index.html');}
 try{const content=await readFile(file);res.writeHead(200,{'Content-Type':types[path.extname(file)]||'application/octet-stream',
    'Cache-Control':file.endsWith('index.html')?'no-store':'public,max-age=3600'});
    if(req.method==='HEAD')res.end();else res.end(content);
 }catch{res.writeHead(503);res.end('Build unavailable');}
}
if(process.env.NODE_ENV!=='test'){http.createServer(handler).listen(port,'0.0.0.0',()=>console.log('BidPicker original API mobile UI on '+port));}
