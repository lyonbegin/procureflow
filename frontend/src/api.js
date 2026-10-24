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

export const api = {
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
