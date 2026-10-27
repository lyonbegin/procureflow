import { createServer } from 'node:http';
import { readFile, readdir } from 'node:fs/promises';
import { join, extname, resolve, sep } from 'node:path';

const root = '/preview';
const dist = join(root, 'dist');
const sources = { operational: join(root, 'workflows', 'operational'), scenarios: join(root, 'workflows', 'scenarios') };
const port = Number(process.env.PORT || 3000);
const types = { '.js':'text/javascript; charset=utf-8', '.css':'text/css; charset=utf-8', '.html':'text/html; charset=utf-8', '.svg':'image/svg+xml', '.png':'image/png', '.woff':'font/woff', '.woff2':'font/woff2' };
const filenamePattern = /^(?:PF(?:0[1-9]|1[0-5])|S(?:0[1-9]|10))$/;

async function catalog() {
  const result = [];
  for (const [group, dir] of Object.entries(sources)) {
    const expected = group === 'operational' ? /^PF(?:0[1-9]|1[0-5])\.json$/ : /^S(?:0[1-9]|10)\.json$/;
    for (const file of (await readdir(dir)).filter(n => expected.test(n)).sort()) {
      const w = JSON.parse(await readFile(join(dir,file), 'utf8'));
      result.push({ group, id: file.slice(0,-5), workflowId: w.id, name: w.name, nodeCount: w.nodes.length, edgeCount: Object.values(w.connections || {}).length, active: w.active === true });
    }
  }
  return result;
}
function send(res, code, data, type='application/json; charset=utf-8') {
  res.writeHead(code, {'Content-Type':type, 'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff'});
  res.end(typeof data === 'string' || Buffer.isBuffer(data) ? data : JSON.stringify(data));
}
createServer(async (req,res) => {
  try {
    if (req.method !== 'GET') return send(res,405,{error:'READ_ONLY'});
    const pathname = new URL(req.url || '/', 'http://local').pathname;
    if (pathname === '/healthz') return send(res,200,{ok:true,viewer:'read-only',catalogCount:(await catalog()).length});
    if (pathname === '/api/catalog') return send(res,200,{engine:'n8n',renderer:'Vue Flow 1.48.0',execution:false,workflows:await catalog()});
    const match = /^\/api\/workflows\/(operational|scenarios)\/(PF\d{2}|S\d{2})$/.exec(pathname);
    if (match) {
      const [_,group,id] = match;
      if (!filenamePattern.test(id) || (group==='operational') !== id.startsWith('PF')) return send(res,404,{error:'NOT_FOUND'});
      const w = JSON.parse(await readFile(join(sources[group],id+'.json'), 'utf8'));
      return send(res,200,{source:'native-n8n-workflow-json',workflow:w});
    }
    const target = pathname === '/' ? join(dist,'index.html') : resolve(dist,'.'+pathname);
    if (!target.startsWith(dist+sep) && target !== join(dist,'index.html')) return send(res,403,{error:'FORBIDDEN'});
    try { return send(res,200,await readFile(target),types[extname(target)] || 'application/octet-stream'); }
    catch { return send(res,404,{error:'NOT_FOUND'}); }
  } catch (error) { console.error(error); send(res,500,{error:'PREVIEW_ERROR'}); }
}).listen(port,'0.0.0.0',()=>console.log('ProcureFlow real n8n JSON preview ready on',port));
