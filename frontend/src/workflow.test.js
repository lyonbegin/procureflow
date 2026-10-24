import test from 'node:test';
import assert from 'node:assert/strict';
import {
  GROUPS, TOTAL_FEATURES, featureGroup, groupCounts, groupState,
  overviewGraph, detailGraph, parametersFromContract,
} from './workflow.js';

const makeItems = () => GROUPS.flatMap((group) => Array.from(
  { length: group.range[1] - group.range[0] + 1 }, (_, offset) => ({
    number: group.range[0] + offset, group: group.key,
    name: group.title + ' #' + (group.range[0] + offset),
    acceptance_state: 'missing', missing_evidence: ['original'],
  }),
));

test('all 104 functions in seven contiguous groups', () => {
  assert.equal(TOTAL_FEATURES, 104);
  assert.equal(makeItems().length, 104);
  assert.equal(new Set(makeItems().map((x) => x.number)).size, 104);
  assert.equal(featureGroup(49), 'matching');
  assert.equal(featureGroup(104), 'operations');
  assert.equal(featureGroup(105), null);
});

test('overview starts at the selected notice and routes through all seven groups', () => {
  const { nodes, edges } = overviewGraph(makeItems(), { bid_no: 'R26BK01787028' });
  assert.equal(nodes.length, 9);
  assert.equal(edges.length, 9);
  assert.ok(edges.some((x) => x.source === 'tender' && x.target === 'group:notice'));
  assert.ok(edges.some((x) => x.source === 'group:detail' && x.target === 'group:history'));
  assert.ok(edges.some((x) => x.source === 'group:detail' && x.target === 'group:eligibility'));
  assert.ok(edges.some((x) => x.source === 'group:operations' && x.target === 'finish'));
});

test('group drill-down maps every API function into a clickable independent node', () => {
  const items = makeItems();
  for (const group of GROUPS) {
    const { nodes, edges } = detailGraph(items, group.key, group.range[0]);
    const functionNodes = nodes.filter((x) => x.type === 'feature');
    assert.equal(functionNodes.length, group.range[1] - group.range[0] + 1);
    assert.equal(new Set(functionNodes.map((x) => x.id)).size, functionNodes.length);
    assert.equal(edges.length, functionNodes.length);
    assert.equal(nodes[0].id, 'tender');
    assert.equal(functionNodes.filter((x) => x.data.selected).length, 1);
  }
});

test('counts never assert a missing/unloaded function has been verified', () => {
  const all = makeItems();
  all[0].acceptance_state = 'verified';
  all[1].acceptance_state = 'partial';
  const count = groupCounts(all, GROUPS[0]);
  assert.equal(count.verified, 1);
  assert.equal(count.partial, 1);
  assert.equal(count.missing, 14);
  assert.equal(groupState(count), 'partial');
  assert.equal(groupState(groupCounts([], GROUPS[0])), 'unavailable');
});

test('input defaults never include selected tender identifier overrides', () => {
  const parsed = parametersFromContract({
    candidate_limit: { type: 'integer', default: 4 },
    file_id: { type: 'string' },
  });
  assert.deepEqual(parsed, { candidate_limit: 4 });
});
