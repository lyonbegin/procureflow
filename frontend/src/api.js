export const SELECTED_BID = 'R26BK01787028';
export const CASE_API = '/api/g2b/cases/' + SELECTED_BID;

export async function readJson(path, { method = 'GET', token = '', body, signal } = {}) {
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (token.trim()) headers.Authorization = 'Bearer ' + token.trim().replace(/^Bearer\s+/i, '');
  const response = await fetch(path, {
    method, headers, credentials: 'same-origin', cache: 'no-store',
    body: body === undefined ? undefined : JSON.stringify(body), signal,
  });
  let result;
  try { result = await response.json(); } catch { result = null; }
  if (!response.ok) {
    const detail = result?.detail;
    const message = typeof detail === 'string' ? detail
      : typeof detail === 'object' ? JSON.stringify(detail)
      : response.statusText;
    const error = new Error('HTTP ' + response.status + ': ' + message);
    error.status = response.status;
    throw error;
  }
  return result;
}

export async function uploadNodeTestFile(featureNo, file, token) {
  const form = new FormData();
  form.append('file', file, file.name);
  const response = await fetch(CASE_API + '/features/' + featureNo + '/test/files', {
    method: 'POST', credentials: 'same-origin', cache: 'no-store',
    headers: { Accept: 'application/json', Authorization: 'Bearer ' + token.trim().replace(/^Bearer\\s+/i, '') },
    body: form,
  });
  const result = await response.json().catch(() => null);
  if (!response.ok) throw new Error('HTTP ' + response.status + ': ' +
    (typeof result?.detail === 'string' ? result.detail : JSON.stringify(result?.detail || response.statusText)));
  return result;
}

export const api = {
  workflowDesigns: (token) => readJson(CASE_API + '/workflow/designs', { token }),
  createWorkflowDesign: (name, graph, token) => readJson(CASE_API + '/workflow/designs', {
    method: 'POST', token, body: { name, graph: graph || null },
  }),
  loadWorkflowDesign: (id, token) => readJson(CASE_API + '/workflow/designs/' + id, { token }),
  saveWorkflowDesign: (id, revision, name, graph, publish, token) => readJson(
    CASE_API + '/workflow/designs/' + id, {
      method: 'PUT', token, body: { expected_revision: revision, name, graph, publish },
    }),
  deleteWorkflowDesign: (id, token) => readJson(
    CASE_API + '/workflow/designs/' + id, { method: 'DELETE', token }),
  createWorkflowDebug: (id, token) => readJson(
    CASE_API + '/workflow/designs/' + id + '/debug-runs',
    { method: 'POST', token }),
  workflowDebug: (id, token) => readJson(
    CASE_API + '/workflow/debug-runs/' + id, { token }),
  workflowDebugAction: (id, action, node_id, payload, token) => readJson(
    CASE_API + '/workflow/debug-runs/' + id + '/actions',
    { method: 'POST', token, body: { action, node_id: node_id || null, payload: payload ?? null } }),
  nodeTestContract: (id, token) => readJson(CASE_API + '/features/' + id + '/test/contract', { token }),
  nodeTest: (id, body, token) => readJson(CASE_API + '/features/' + id + '/test',
    { method: 'POST', body, token }),
  nodeTestRuns: (id, token) => readJson(CASE_API + '/features/' + id + '/test/runs', { token }),
  nodeTestFiles: (id, token) => readJson(CASE_API + '/features/' + id + '/test/files', { token }),
  nodeTestPin: (id, token) => readJson(CASE_API + '/features/' + id + '/test/pin', { token }),
  saveNodeTestPin: (id, output, label, token) => readJson(
    CASE_API + '/features/' + id + '/test/pin', {
      method: 'PUT', body: { label, output }, token,
    }),
  deleteNodeTestPin: (id, token) => readJson(
    CASE_API + '/features/' + id + '/test/pin', { method: 'DELETE', token }),

  catalog: () => readJson(CASE_API + '/features'),
  plan: () => readJson(CASE_API + '/workflow/plan'),
  advance: (featureNo, token) => readJson(CASE_API + '/workflow/advance', {
    method: 'POST', token, body: { confirm_feature_no: featureNo },
  }),
  feature: (id, opts = {}) => readJson(CASE_API + '/features/' + id, opts),
  runs: (id) => readJson(CASE_API + '/features/' + id + '/runs?limit=15'),
  run: (id, mode, parameters, token) => readJson(
    CASE_API + '/features/' + id + '/run', {
      method: 'POST', token, body: { mode, parameters },
    }),
  job: (jobId, token) => readJson(CASE_API + '/feature-jobs/' + jobId, { token }),
};
