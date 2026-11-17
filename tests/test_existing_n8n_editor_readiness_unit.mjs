// Synthetic-only contract tests for the read-only EXISTING editor owner gate.
// No Railway, n8n, database, credentials or workflow API is mutated.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {spawn} from 'node:child_process';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

async function runOwnerGate(ownerRequired, options={}){
  const canary='SECRET_MUST_NEVER_APPEAR_IN_ARTIFACT';
  const server=createServer((req,res)=>{
    res.setHeader('content-type','application/json');
    if(req.method!=='GET'){res.writeHead(405);res.end();return;}
    switch(req.url){
      case '/healthz':res.writeHead(200);res.end(JSON.stringify({status:'ok',secret:canary}));break;
      case '/rest/settings':if(options.settingsDisconnect){req.socket.destroy();break;}
        if(options.settingsInvalid){res.writeHead(200);res.end('not-json '+canary);break;}
        res.writeHead(200);res.end(JSON.stringify({
        data:{userManagement:{showSetupOnFirstLoad:ownerRequired}},privateToken:canary
      }));break;
      case '/setup':res.writeHead(options.setupOpen?200:403);res.end(JSON.stringify({secret:canary}));break;
      case '/rest/workflows':res.writeHead(options.workflowsOpen?200:401);res.end(JSON.stringify({secret:canary}));break;
      default:res.writeHead(404);res.end();
    }
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const dir=await mkdtemp(join(tmpdir(),'pf-owner-gate-'));
  const artifact=join(dir,'readiness-verdict.json');
  try{
    const result=await new Promise((resolve,reject)=>{
      const child=spawn(process.execPath,['tests/test_existing_n8n_editor_readiness.mjs'],{
        env:{...process.env,
          N8N_EDITOR_URL:'http://127.0.0.1:'+server.address().port,
          N8N_EDITOR_READINESS_ARTIFACT:artifact},
        stdio:['ignore','pipe','pipe']
      });
      let stdout='',stderr='';
      child.stdout.on('data',chunk=>stdout+=chunk.toString());
      child.stderr.on('data',chunk=>stderr+=chunk.toString());
      child.on('error',reject);
      child.on('close',code=>resolve({code,stdout,stderr}));
    });
    const content=await readFile(artifact,'utf8');
    const verdict=JSON.parse(content);
    assert.equal(verdict.ownerSetupRequired,options.settingsDisconnect||options.settingsInvalid?null:ownerRequired);
    assert.equal(verdict.gatewayHealthStatus,200);
    assert.equal(verdict.settingsStatus,options.settingsDisconnect?null:200);
    assert.equal(verdict.publicOwnerSetupStatus,options.setupOpen?200:403);
    assert.equal(verdict.unauthenticatedWorkflowApiStatus,options.workflowsOpen?200:401);
    assert.equal(verdict.createdOwner,false);
    assert.equal(verdict.changedDatabase,false);
    assert.equal(content.includes(canary),false);
    assert.equal(result.stdout.includes(canary),false);
    assert.equal(result.stderr.includes(canary),false);
    return {result,verdict};
  }finally{
    await new Promise(resolve=>server.close(resolve));
    await rm(dir,{recursive:true,force:true});
  }
}
test('blocked owner remains a failed CI gate but writes redacted diagnostic artifact',async()=>{
  const {result,verdict}=await runOwnerGate(true);
  assert.equal(result.code,1);
  assert.match(result.stderr,/EDITOR_BLOCKED_UNCLAIMED_OWNER/);
  assert.equal(verdict.ready,false);
  assert.equal(verdict.blocker,'EDITOR_BLOCKED_UNCLAIMED_OWNER');
});
test('already claimed owner passes without creating or changing anything',async()=>{
  const {result,verdict}=await runOwnerGate(false);
  assert.equal(result.code,0,result.stderr);
  assert.equal(verdict.ready,true);
  assert.equal(verdict.blocker,null);
});

test('gateway settings connection failure writes redacted failure evidence, never false PASS',async()=>{
  const {result,verdict}=await runOwnerGate(false,{settingsDisconnect:true});
  assert.equal(result.code,1);
  assert.equal(verdict.ready,false);
  assert.equal(verdict.blocker,'GATEWAY_NOT_READY');
  assert.match(result.stderr,/GATEWAY_NOT_READY/);
});
test('malformed settings JSON is not proof that the editor owner is claimed',async()=>{
  const {result,verdict}=await runOwnerGate(false,{settingsInvalid:true});
  assert.equal(result.code,1);
  assert.equal(verdict.ready,false);
  assert.equal(verdict.blocker,'OWNER_READINESS_UNKNOWN');
});
test('public owner setup must remain forbidden even when owner flag is false',async()=>{
  const {result,verdict}=await runOwnerGate(false,{setupOpen:true});
  assert.equal(result.code,1);
  assert.equal(verdict.ready,false);
  assert.equal(verdict.blocker,'PUBLIC_OWNER_SETUP_NOT_BLOCKED');
});
test('workflow API without authentication must fail closed',async()=>{
  const {result,verdict}=await runOwnerGate(false,{workflowsOpen:true});
  assert.equal(result.code,1);
  assert.equal(verdict.ready,false);
  assert.equal(verdict.blocker,'WORKFLOW_AUTH_NOT_ENFORCED');
});
