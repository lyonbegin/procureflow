/** Pure graph layout for the selected 104-feature procurement case.
 * The connections express the configured review order, not fabricated
 * evidence dependencies or permission to submit a bid.
 */
export const GROUPS = [
  { key: 'notice', title: '신규 발주 감지', subtitle: '공식 입찰공고 · 변경 이력', range: [1, 16], icon: 'radar', x: 324, y: 325 },
  { key: 'detail', title: '발주 상세 · 첨부', subtitle: '원본 문서 · 분류코드 · 조건', range: [17, 32], icon: 'file-search', x: 642, y: 325 },
  { key: 'history', title: '과거 개찰 · 낙찰', subtitle: '공개 원본 · 개찰 · 확정낙찰', range: [33, 48], icon: 'history', x: 960, y: 95 },
  { key: 'matching', title: '세부종목 10년 분석', subtitle: '10자리 코드 · 업체 · 결과', range: [49, 60], icon: 'chart', x: 1268, y: 95 },
  { key: 'eligibility', title: '참가자격 · 공급업체', subtitle: '자격증빙 · 견적 · 수행능력', range: [61, 76], icon: 'shield', x: 960, y: 555 },
  { key: 'pricing', title: '가격 · 제안서', subtitle: '원가 · 가격 · 제출서류', range: [77, 94], icon: 'calculator', x: 1576, y: 325 },
  { key: 'operations', title: '실행 · 최종검증', subtitle: 'Worker · 재시도 · 승인대기', range: [95, 104], icon: 'check', x: 1884, y: 325 },
];

export const GROUP_BY_ID = Object.fromEntries(GROUPS.map((group) => [group.key, group]));
export const TOTAL_FEATURES = GROUPS.reduce((sum, group) => sum + group.range[1] - group.range[0] + 1, 0);
if (TOTAL_FEATURES !== 104) throw new Error('The workflow registry must contain exactly 104 functions');

export function featureGroup(number) {
  return GROUPS.find((group) => group.range[0] <= number && number <= group.range[1])?.key || null;
}

export function groupCounts(features, group) {
  const within = features.filter((f) => f.group === group.key);
  const counts = { total: group.range[1] - group.range[0] + 1, verified: 0, partial: 0, missing: 0, blocked: 0, error: 0 };
  within.forEach((feature) => {
    const state = feature.acceptance_state;
    if (state in counts && state !== 'total') counts[state] += 1;
    else counts.missing += 1;
  });
  counts.loaded = within.length;
  counts.unverified = counts.total - counts.verified;
  return counts;
}

export function groupState(counts) {
  if (counts.loaded === 0) return 'unavailable';
  if (counts.verified === counts.total) return 'verified';
  if (counts.error) return 'error';
  if (counts.partial || counts.verified) return 'partial';
  return 'missing';
}

const edge = (id, source, target, extras = {}) => ({
  id, source, target, type: 'smoothstep', selectable: false,
  style: { stroke: '#9fb1c4', strokeWidth: 2.1 },
  ...extras,
});

export function overviewGraph(features, context = {}) {
  const nodes = [{
    id: 'tender', type: 'tender', position: { x: 4, y: 327 },
    draggable: false, data: { title: context.title || '발주 원본 확인 중', bidNo: context.bid_no || '', context },
  }];
  for (const group of GROUPS) {
    const counts = groupCounts(features, group);
    nodes.push({
      id: 'group:' + group.key, type: 'group',
      position: { x: group.x, y: group.y }, draggable: false,
      data: { ...group, counts, status: groupState(counts) },
    });
  }
  nodes.push({
    id: 'finish', type: 'finish', position: { x: 2189, y: 336 },
    draggable: false, data: { label: '입찰참가 직전', subtitle: '사람의 최종 승인 단계' },
  });
  const pairs = [
    ['tender', 'group:notice'],
    ['group:notice', 'group:detail'],
    ['group:detail', 'group:history'],
    ['group:detail', 'group:eligibility'],
    ['group:history', 'group:matching'],
    ['group:matching', 'group:pricing'],
    ['group:eligibility', 'group:pricing'],
    ['group:pricing', 'group:operations'],
    ['group:operations', 'finish'],
  ];
  return { nodes, edges: pairs.map(([source, target]) => edge(source + '=>' + target, source, target)) };
}

export function detailGraph(features, groupKey, selectedNumber, context = {}) {
  const group = GROUP_BY_ID[groupKey];
  if (!group) return { nodes: [], edges: [] };
  const within = features.filter((feature) => feature.group === groupKey)
    .sort((a, b) => a.number - b.number);
  const columns = 4;
  const nodes = [{
    id: 'tender', type: 'tender', position: { x: -304, y: 180 },
    draggable: false, data: { title: context.title || '선택 발주', bidNo: context.bid_no || '' },
  }];
  const edges = [];
  for (let idx = 0; idx < within.length; idx++) {
    const f = within[idx];
    const row = Math.floor(idx / columns);
    const offset = idx % columns;
    const col = row % 2 === 0 ? offset : columns - offset - 1;
    nodes.push({
      id: 'feature:' + f.number, type: 'feature',
      position: { x: 20 + col * 284, y: row * 144 },
      selected: f.number === selectedNumber, draggable: false,
      data: {
        number: f.number, title: f.name, status: f.acceptance_state,
        missing: f.missing_evidence?.length ?? 0,
        selected: f.number === selectedNumber,
      },
    });
    if (idx === 0) {
      edges.push(edge('tender=>feature:' + f.number, 'tender', 'feature:' + f.number));
    } else {
      const previous = within[idx - 1];
      const previousRow = Math.floor((idx - 1) / columns);
      const previousCol = previousRow % 2 === 0 ? (idx - 1) % columns : columns - ((idx - 1) % columns) - 1;
      const sameRow = previousRow === row;
      const leftToRight = col > previousCol;
      edges.push(edge('feature:' + previous.number + '=>feature:' + f.number,
        'feature:' + previous.number, 'feature:' + f.number, {
          sourceHandle: sameRow ? (leftToRight ? 'right' : 'left-source') : 'bottom',
          targetHandle: sameRow ? (leftToRight ? 'left' : 'right-target') : 'top',
        }));
    }
  }
  return { nodes, edges };
}

export function graphCounts(features) {
  const c = { total: TOTAL_FEATURES, loaded: features.length, verified: 0, partial: 0, missing: 0 };
  for (const g of GROUPS) {
    const count = groupCounts(features, g);
    c.verified += count.verified;
    c.partial += count.partial;
    c.missing += count.missing + count.blocked + count.error;
  }
  return c;
}

export function parametersFromContract(spec = {}) {
  return Object.fromEntries(Object.entries(spec)
    .filter(([, def]) => Object.prototype.hasOwnProperty.call(def, 'default'))
    .map(([name, def]) => [name, def.default]));
}
