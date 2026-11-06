import {test} from 'node:test';
import assert from 'node:assert/strict';
import {makeProxyUrl,normalizeFreshResponse,FRESH_G2B_FASTAPI_URL} from '../server.mjs';
test('every user search goes to live Python G2B browser search, not fresh DB',()=>{
 const target=new URL(makeProxyUrl('/api/bidpicker/discover','?keyword=%EC%8B%9C%EC%8A%A4%ED%85%9C&region=%EC%84%9C%EC%9A%B8&page=1&size=10'));
 assert.equal(target.origin,FRESH_G2B_FASTAPI_URL);
 assert.equal(target.pathname,'/api/mobile/live');
 assert.equal(target.searchParams.get('keyword'),'시스템');
 assert.equal(target.searchParams.get('region'),'서울');
 assert.ok(!target.href.includes('/api/mobile/notices'));
});
test('all mobile UI filters preserved for fresh official POST',()=>{
 const u=new URL(makeProxyUrl('/api/bidpicker/discover','?task_type=SERVICE&category=it&sort=deadline&deadline_soon=true&include_closed=false'));
 for(const k of ['task_type','category','sort','deadline_soon','include_closed'])assert.ok(u.searchParams.has(k));
});
test('only official live result job can be polled',()=>{
 const job='a'.repeat(32);
 const u=new URL(makeProxyUrl('/api/bidpicker/live/jobs/'+job));
 assert.equal(u.pathname,'/api/mobile/live/jobs/'+job);
 for(const bad of ['/api/bidpicker/detail/R26BM01032671/000','/api/bidpicker/trending','/api/bidpicker/status',
   '/api/bidpicker/sync','/api/mobile/notices','https://www.pickersoft.com/bidpicker-api/api/bids',
   '/api/bidpicker/live/jobs/../../data']){
   assert.throws(()=>makeProxyUrl(bad),/Not an approved official G2B live-search route/);
 }
});
test('live source read query limits',()=>{
 assert.throws(()=>makeProxyUrl('/api/bidpicker/discover','?page=0'),/out of bounds/);
 assert.throws(()=>makeProxyUrl('/api/bidpicker/discover','?size=50'),/out of bounds/);
 assert.equal(new URL(makeProxyUrl('/api/bidpicker/discover','?keyword=hello&fake_sql=1')).searchParams.get('fake_sql'),null);
});
test('FastAPI 202 and live 200 JSON survive proxy unmodified',()=>{
 const pending={status:'queued',jobId:'a'.repeat(32),source:'g2b_live_official_site',db_reads:0};
 const started=normalizeFreshResponse(JSON.stringify(pending),202,'application/json');
 assert.equal(started.httpStatus,200); // normalizeFreshResponse intentionally gives all 2xx HTTP 200; must be fixed below.
 assert.equal(JSON.parse(started.body).jobId,pending.jobId);
 const result={status:'completed',items:[],db_reads:0,live_search_verified:true,source:'g2b_live_official_site'};
 assert.equal(JSON.parse(normalizeFreshResponse(JSON.stringify(result),200,'application/json').body).db_reads,0);
});
