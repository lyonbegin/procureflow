/** Standalone workflow-screen routing and workspace-only layout settings.
 * This intentionally does NOT make static React Flow edges executable/editable.
 * Actual graph-editor/engine support remains a separately verified feature.
 */
export const STANDALONE_FLOW_PATH = '/flow';

export function isStandaloneFlowPath(pathname = '') {
  return pathname === STANDALONE_FLOW_PATH || pathname === STANDALONE_FLOW_PATH + '/';
}

export function clampInspectorWidth(requested, viewportWidth) {
  const viewport = Number.isFinite(viewportWidth) ? viewportWidth : 1440;
  const maximum = Math.min(960, Math.max(360, viewport - 30));
  return Math.min(maximum, Math.max(360, requested));
}

export function visibleFlowFeatures(features, text) {
  const search = String(text || '').trim().toLocaleLowerCase();
  if (!search) return features;
  return features.filter((feature) =>
    (String(feature.number) + ' ' + String(feature.name || '')).toLocaleLowerCase().includes(search));
}
