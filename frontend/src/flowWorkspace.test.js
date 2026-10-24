import test from 'node:test';
import assert from 'node:assert/strict';
import { STANDALONE_FLOW_PATH, isStandaloneFlowPath, clampInspectorWidth, visibleFlowFeatures } from './flowWorkspace.js';
test('standalone route only /flow, not legacy dashboard', () => {
 assert.equal(STANDALONE_FLOW_PATH, '/flow');
 for (const path of ['/flow','/flow/']) assert.equal(isStandaloneFlowPath(path), true);
 for (const path of ['/','/legacy/workbench','/flow-anything','/operations']) assert.equal(isStandaloneFlowPath(path), false);
});
test('large inspection pane is viewport bounded and adjustable', () => {
 assert.equal(clampInspectorWidth(550, 1440),550);
 assert.equal(clampInspectorWidth(200, 1440),360);
 assert.equal(clampInspectorWidth(1200, 1440),960);
 assert.equal(clampInspectorWidth(1000, 700),670);
});
test('search can find function names and IDs, never modify registry', () => {
 const input=[{number:1,name:'입찰 공고'},{number:50,name:'세부 종목 10년 분석'},{number:104,name:'검증'}];
 assert.deepEqual(visibleFlowFeatures(input, '50'),[input[1]]);
 assert.deepEqual(visibleFlowFeatures(input, '입찰'),[input[0]]);
 assert.equal(visibleFlowFeatures(input,'').length,3);
 assert.equal(input.length,3);
});
