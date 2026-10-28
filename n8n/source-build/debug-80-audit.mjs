#!/usr/bin/env node
/**
 * Audit 80 separate node-debugging requirements (IDs 81..160).
 * Existing report is the source of truth; a passing audit means the gap
 * inventory is accurate, NOT that the 80 requirements are implemented.
 */
import {readFile,writeFile} from 'node:fs/promises';
const source=process.argv[2]??'reports/workflow_81_160_implementation_20261025.md';
const target=process.argv[3]??'shared-debug-80-audit.json';
const raw=await readFile(source,'utf8');
const entries=[];
for(const line of raw.split(/\r?\n/)){
  const match=line.match(/^\|\s*(\d{2,3})\s*\|\s*(구현|부분|미구현)\s*\|\s*([^|]+)\|\s*([^|]+)\|/);
  if(!match)continue;
  const id=Number(match[1]);
  if(id<81||id>160)continue;
  entries.push({id,status:match[2],name:match[3].trim(),scopeAndGaps:match[4].trim()});
}
if(entries.length!==80)throw Error('Expected 80 requirements, found '+entries.length);
const ids=new Set(entries.map(x=>x.id));
for(let i=81;i<=160;i++)if(!ids.has(i))throw Error('Missing debug requirement '+i);
const counts={implemented:entries.filter(x=>x.status==='구현').length,partial:entries.filter(x=>x.status==='부분').length,notImplemented:entries.filter(x=>x.status==='미구현').length};
const summary={
  schemaVersion:'procureflow.debug-80-audit.v1',
  source,
  status:counts.partial+counts.notImplemented===0?'ALL_REPORTED_IMPLEMENTED_REQUIRES_RUNTIME_VALIDATION':'INCOMPLETE',
  ...counts,
  total:entries.length,
  runtimeVerified:0,
  notYetFullyImplemented:entries.filter(x=>x.status!=='구현'),
  allRequirements:entries
};
await writeFile(target,JSON.stringify(summary,null,2)+'\n');
console.log('DEBUG_80_AUDIT '+JSON.stringify({status:summary.status,counts,total:summary.total,runtimeVerified:summary.runtimeVerified}));
if(counts.implemented!==19||counts.partial!==47||counts.notImplemented!==14){
  console.log('DEBUG_80_BASELINE_CHANGED: update source report and inspect whether implementation evidence changed');
}
