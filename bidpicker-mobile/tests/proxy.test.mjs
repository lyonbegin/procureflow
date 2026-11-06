import {test} from 'node:test';
import assert from 'node:assert/strict';
import {makeProxyUrl,normalizeFreshResponse,FRESH_G2B_FASTAPI_URL} from '../server.mjs';

test('all search results come from OUR Python FastAPI official site collector',()=>{
 assert.equal(FRESH_G2B_FASTAPI_URL,'https://fresh-g2b-site-center-production.up.railway.app');
 const target=new URL(makeProxyUrl('/api/bidpicker/discover','?keyword=%EC%8B%9C%EC%8A%A4%ED%85%9C&region=%EC%84%9C%EC%9A%B8&page=1&size=10'));
 assert.equal(target.origin,'https://fresh-g2b-site-center-production.up.railway.app');
 assert.equal(target.pathname,'/api/mobile/notices');
 assert.equal(target.searchParams.get('keyword'),'시스템');
 assert.equal(target.searchParams.get('region'),'서울');
 assert.equal(target.searchParams.get('size'),'10');
 assert.equal(target.href.includes('pickersoft.com'),false);
});
test('mobile filters are forwarded to our FastAPI with original query semantics',()=>{
 const u=new URL(makeProxyUrl('/api/bidpicker/discover','?task_type=SERVICE&category=it&sort=deadline&deadline_soon=true&include_closed=false'));
 assert.equal(u.searchParams.get('task_type'),'SERVICE');
 assert.equal(u.searchParams.get('category'),'it');
 assert.equal(u.searchParams.get('sort'),'deadline');
 assert.equal(u.searchParams.get('deadline_soon'),'true');
 assert.equal(u.searchParams.get('include_closed'),'false');
});
test('full source detail is a local official notice GET, not vendor BidPicker URL',()=>{
 const u=new URL(makeProxyUrl('/api/bidpicker/detail/R26BM01032642/000'));
 assert.equal(u.pathname,'/api/mobile/notices/R26BM01032642/000');
});
test('status and diagnostics inspect our FastAPI, not original vendor or bridge',()=>{
 const u=new URL(makeProxyUrl('/api/bidpicker/status'));
 assert.equal(u.pathname,'/health');
 assert.equal(new URL(makeProxyUrl('/api/bidpicker/diagnostics')).pathname,'/health');
});
test('do not proxy arbitrary URLs or mutating endpoints',()=>{
 for(const route of ['/api/bidpicker/sync','/api/bidpicker/trending','/api/bidpicker/detail/../../etc/passwd','/health','https://www.pickersoft.com/bidpicker-api/api/bids'])
   assert.throws(()=>makeProxyUrl(route),/Not an approved official G2B read-only route/);
});
test('pagination bounds prevent excessive public read traffic',()=>{
 assert.throws(()=>makeProxyUrl('/api/bidpicker/discover','?size=1000'),/out of bounds/);
 assert.throws(()=>makeProxyUrl('/api/bidpicker/discover','?page=0'),/out of bounds/);
});
test('user query cannot inject upstream host or private headers',()=>{
 const u=new URL(makeProxyUrl('/api/bidpicker/discover','?keyword=test&source_url=https://evil.example&admin_token=hi&page=1'));
 assert.equal(u.origin,'https://fresh-g2b-site-center-production.up.railway.app');
 assert.equal(u.searchParams.get('source_url'),null);
 assert.equal(u.searchParams.get('admin_token'),null);
});
test('valid actual FastAPI public rows survive response handling intact',()=>{
 const fresh={source:'fresh_g2b_official_site',total:1,
    items:[{id:'R26BM01032642-000',title:'업무망 DNS시스템외 1종 유지보수',agencyName:'한전KDN(주)'}]};
 const r=normalizeFreshResponse(JSON.stringify(fresh),200,'application/json;charset=utf-8');
 assert.equal(r.httpStatus,200);
 assert.deepEqual(JSON.parse(r.body),fresh);
});
test('real upstream 404 and failed JSON keep accurate status, not fabricated Basic 401',()=>{
 const r=normalizeFreshResponse('{"detail":"NOT_IN_FRESH_DB"}',404,'application/json');
 assert.equal(r.httpStatus,404);
 assert.deepEqual(JSON.parse(r.body),{detail:'NOT_IN_FRESH_DB'});
 assert.equal(normalizeFreshResponse('<html>error</html>',200,'text/html').httpStatus,502);
});
