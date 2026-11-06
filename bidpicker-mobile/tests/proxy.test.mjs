import {test} from 'node:test';
import assert from 'node:assert/strict';
import {makeProxyUrl,normalizeUpstream,BIDPICKER_ORIGINAL_ROOT} from '../server.mjs';

test('source base URL matches original XAPK',()=>{
 assert.equal(BIDPICKER_ORIGINAL_ROOT,'https://www.pickersoft.com/bidpicker-api/');
});
test('search goes directly to the original BidPicker API not intermediary Bridge',()=>{
 const u=new URL(makeProxyUrl('/api/bidpicker/discover','?keyword=%EC%B2%AD%EC%86%8C&region=%EC%84%9C%EC%9A%B8&task_type=SERVICE&page=1&size=10'));
 assert.equal(u.origin,'https://www.pickersoft.com');
 assert.equal(u.pathname,'/bidpicker-api/api/bids');
 assert.equal(u.searchParams.get('keyword'),'청소');
 assert.equal(u.searchParams.get('region'),'서울');
 assert.equal(u.searchParams.get('taskType'),'SERVICE');
 assert.equal(u.searchParams.get('size'),'10');
});
test('retrofit Java query flags and status mapping',()=>{
 const u=new URL(makeProxyUrl('/api/bidpicker/discover','?status=OPEN&deadline_soon=true&include_closed=false'));
 assert.equal(u.searchParams.get('status'),'OPEN');
 assert.equal(u.searchParams.get('deadlineSoon'),'true');
 assert.equal(u.searchParams.get('includeClosed'),'false');
});
test('detail and trending use original GET routes',()=>{
 assert.equal(new URL(makeProxyUrl('/api/bidpicker/detail/abc123')).pathname,'/bidpicker-api/api/bids/abc123');
 assert.equal(new URL(makeProxyUrl('/api/bidpicker/trending','?category=it')).searchParams.get('category'),'it');
});
test('status monitoring is the only Bridge endpoint',()=>{
 assert.equal(makeProxyUrl('/api/bidpicker/status'),'https://bidpicker-discovery-bridge-production.up.railway.app/api/bidpicker/status');
});
test('only allowlisted read-only routes permitted',()=>{
 assert.throws(()=>makeProxyUrl('/api/alert-conditions'),/Not an approved GET source route/);
 assert.throws(()=>makeProxyUrl('/api/bidpicker/sync'),/Not an approved GET source route/);
 assert.throws(()=>makeProxyUrl('/api/bidpicker/detail/../../etc/passwd'),/Not an approved GET source route/);
});
test('bounded request and untrusted param stripping',()=>{
 assert.throws(()=>makeProxyUrl('/api/bidpicker/discover','?size=1000'),/bounds exceeded/);
 const u=new URL(makeProxyUrl('/api/bidpicker/discover','?keyword=test&admin_token=secret&size=1'));
 assert.equal(u.searchParams.get('admin_token'),null);
});
test('upstream HTTP 401 preserved as 401; never mask as artificial 503',()=>{
 const response=normalizeUpstream('Unauthorized',401,'text/html');
 assert.equal(response.httpStatus,401);
 assert.equal(JSON.parse(response.body).upstream_http_status,401);
});
test('real JSON BidPageDto kept intact',()=>{
 const data={items:[{id:'original-1',title:'real data only'}],page:1,size:1,total:1,hasMore:false};
 const response=normalizeUpstream(JSON.stringify(data),200,'application/json');
 assert.equal(response.httpStatus,200);
 assert.deepEqual(JSON.parse(response.body),data);
});
