import {mkdir,writeFile} from 'node:fs/promises';
import {dirname} from 'node:path';
// Read-only gate for EXISTING Railway n8n editor. No auth, DB, CLI, or workflow mutations.
// The response /healthz 200 only proves the Caddy proxy, NOT owner/editor readiness.
const base = (process.env.N8N_EDITOR_URL || 'https://procureflow-n8n-editor-gateway-production.up.railway.app').replace(/\/$/, '');
async function check(path) {
  const response = await fetch(base + path, {
    method: 'GET', redirect: 'manual', signal: AbortSignal.timeout(20000),
    headers: { 'Accept': 'application/json' },
  });
  const payload = await response.text();
  return { status: response.status, payload };
}
const [health, settings, setup, workflows] = await Promise.all(
  ['/healthz', '/rest/settings', '/setup', '/rest/workflows'].map(check),
);
let parsed = {};
try { parsed = JSON.parse(settings.payload); } catch {}
const ownerRequired = parsed?.data?.userManagement?.showSetupOnFirstLoad;
const verdict = {
  gatewayHealthStatus: health.status,
  settingsStatus: settings.status,
  ownerSetupRequired: ownerRequired ?? null,
  publicOwnerSetupStatus: setup.status,
  unauthenticatedWorkflowApiStatus: workflows.status,
  usesExistingServiceOnly: true,
  createdOwner: false,
  changedDatabase: false,
  // A failed owner gate is evidence of a blocked real editor, not a CI flake.
  ready: health.status === 200 && settings.status === 200 &&
    setup.status === 403 && workflows.status === 401 && ownerRequired === false,
  blocker: ownerRequired === true ? 'EDITOR_BLOCKED_UNCLAIMED_OWNER' :
    ownerRequired === false ? null : 'OWNER_READINESS_UNKNOWN',
};
console.log('EXISTING_N8N_EDITOR_READINESS', JSON.stringify(verdict));
// Persist a redacted, machine-readable snapshot even when the owner gate FAILS.
// Never record response bodies, cookies, credentials or workflow data.
const artifact = process.env.N8N_EDITOR_READINESS_ARTIFACT ||
  'existing-n8n-readiness-artifacts/readiness-verdict.json';
await mkdir(dirname(artifact), {recursive:true});
await writeFile(artifact, JSON.stringify(verdict, null, 2) + '\n');
if (health.status !== 200 || settings.status !== 200)
  throw Error('GATEWAY_NOT_READY: existing n8n gateway or settings unavailable');
if (setup.status !== 403)
  throw Error('SECURITY_FAILURE: public initial owner setup path is not blocked');
if (workflows.status !== 401)
  throw Error('SECURITY_FAILURE: private workflow API did not require n8n session');
if (ownerRequired !== false)
  throw Error('EDITOR_BLOCKED_UNCLAIMED_OWNER: the existing n8n database requires first-owner setup; NEVER claim editor ready from Railway deploy SUCCESS');
console.log('EXISTING_N8N_EDITOR_OWNER_GATE_PASS');
