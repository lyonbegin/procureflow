import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {FixtureRunner} from '../n8n/studio-bridge/fixture-runner.mjs';
const suite=JSON.parse(await readFile(new URL('../n8n/scenarios.json',import.meta.url),'utf8'));
assert.equal(suite.scenarios.length,10);
for(const scenario of suite.scenarios){
 const runner=new FixtureRunner(suite,scenario.id,{now:()=> '2026-10-30T00:00:00.000Z'});
 let first=runner.step();
 assert.equal(first.cursor,1);
 assert.equal(first.status,scenario.steps.length===1?'completed':'paused');
 runner.pause();
 const completed=runner.run();
 assert.equal(completed.status,'completed');
 assert.equal(completed.events.length,scenario.steps.length);
 assert.equal(completed.expectedVerdict,scenario.expected);
 assert(completed.executionId.startsWith('mock-'));
 assert.equal(completed.caseId,'DEMO_ONLY');
 assert.equal(completed.bidSubmitted,false);
 assert.equal(completed.actualJobExecuted,false);
 assert(completed.events.every((event,index)=>
  event.sequence===index+1&&event.simulationOnly===true&&event.actualJobExecuted===false&&
  event.status==='success'&&event.input&&event.output));
 assert.throws(()=>new FixtureRunner({...suite,never_calls_official_api:false},scenario.id),/Unsafe fixture/);
 console.log(scenario.id,'MOCK_TRACE_PASS',completed.events.length,scenario.expected);
 const stopped=new FixtureRunner(suite,scenario.id);
 stopped.step();stopped.stop();
 assert.throws(()=>stopped.step(),/Stopped/);
}
console.log('OFFLINE_SCENARIO_RUNNER_10_PASS; NO REAL API, CRAWL, DB, OR N8N EXECUTION');
