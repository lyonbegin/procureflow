// Offline test-only scenario execution. No HTTP, credentials, DB, G2B or bid submission.
import {randomUUID} from 'node:crypto';
export class FixtureRunner {
 constructor(suite,id,{now=()=>new Date().toISOString()}={}){
  if(suite.origin!=='fictional_test_fixtures'||suite.never_calls_official_api!==true)throw Error('Unsafe fixture provenance');
  const scenario=suite.scenarios.find(x=>x.id===id);
  if(!scenario)throw Error('Unknown fixture '+id);
  this.scenario=scenario;this.id=id;this.caseId='DEMO_ONLY';this.executionId='mock-'+randomUUID();
  this.state=structuredClone(suite.base_state);this.events=[];this.cursor=0;this.status='paused';
  this.now=now;this.forbidden=true;
 }
 step(){
  if(this.status==='stopped')throw Error('Stopped execution cannot resume');
  if(this.cursor>=this.scenario.steps.length)return this.result();
  const step=this.scenario.steps[this.cursor];
  if(step.index!==this.cursor+1)throw Error('Fixture step order mismatch');
  if(!/^PF(?:0[1-9]|1[0-5])$/.test(step.flow))throw Error('Unknown PF stage');
  const before=structuredClone(this.state);
  const patch=structuredClone(step.patch||{});
  this.state={...this.state,...patch};
  this.cursor++;
  this.events.push({executionId:this.executionId,nodeId:step.flow,nodeLabel:step.flow_label,
   event:step.event,sequence:this.cursor,startedAt:this.now(),finishedAt:this.now(),
   input:before,output:structuredClone(this.state),patch,status:'success',
   simulationOnly:true,actualJobExecuted:false});
  this.status=this.cursor===this.scenario.steps.length?'completed':'paused';
  return this.result();
 }
 run(){while(this.cursor<this.scenario.steps.length)this.step();return this.result();}
 pause(){if(this.status==='stopped')throw Error('Stopped');this.status='paused';return this.result();}
 stop(){this.status='stopped';return this.result();}
 result(){return {executionId:this.executionId,scenarioId:this.id,caseId:this.caseId,
   status:this.status,cursor:this.cursor,total:this.scenario.steps.length,
   expectedVerdict:this.scenario.expected,simulationOnly:true,actualJobExecuted:false,
   bidSubmitted:false,state:structuredClone(this.state),events:structuredClone(this.events)};}
}
