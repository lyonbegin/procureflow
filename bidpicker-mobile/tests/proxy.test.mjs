import {test} from 'node:test';
import assert from 'node:assert/strict';
import {makeProxyUrl} from '../server.mjs';

test('status endpoint stays read-only',()=>{
 assert.equal(makeProxyUrl('/api/bidpicker/status'),'https://bidpicker-discovery-bridge-production.up.railway.app/api/bidpicker/status');
});
test('search preserves safe filters',()=>{
 const url=new URL(makeProxyUrl('/api/bidpicker/discover','?keyword=%EC%B2%AD%EC%86%8C&region=%EC%84%9C%EC%9A%B8&page=1&size=10'));
 assert.equal(url.searchParams.get('keyword'),'청소');
 assert.equal(url.searchParams.get('region'),'서울');
 assert.equal(url.searchParams.get('size'),'10');
});
test('only two explicit GET endpoints allowed',()=>{
 assert.throws(()=>makeProxyUrl('/api/alert-conditions'),/Not an approved read route/);
 assert.throws(()=>makeProxyUrl('/api/bidpicker/sync'),/Not an approved read route/);
});
test('safe page limits are enforced',()=>{
 assert.throws(()=>makeProxyUrl('/api/bidpicker/discover','?size=1000'),/bounds exceeded/);
});
test('unknown filter keys stripped',()=>{
 const url=new URL(makeProxyUrl('/api/bidpicker/discover','?keyword=test&admin_token=secret&size=1'));
 assert.equal(url.searchParams.get('admin_token'),null);
});
