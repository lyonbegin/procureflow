import {readFileSync,writeFileSync} from 'node:fs';
const path=process.argv[2];
if(!path)throw Error('catalog path required');
let source=readFileSync(path,'utf8');
const mark="export const PROCURE_WORKFLOWS=Object.freeze([\n";
if(!source.includes(mark)||!source.includes("PROCURE_WORKFLOWS.length!==29"))
  throw Error('unexpected pinned shared studio catalog');
source=source.replace(mark,mark+
"  ['operations/PF00-public-nine-real.json','실제 공고 · 9단계 원본 증빙 조회'],\n"+
"  ['operations/PF01-stage1-dataflow.json','실제 공고 · N01/N02 식별·조건 분기'],\n");
if(!source.includes("size!==29")||!source.includes("must contain 29 unique"))
  throw Error('unexpected shared studio uniqueness guard');
source=source.replace("PROCURE_WORKFLOWS.length!==29","PROCURE_WORKFLOWS.length!==31");
source=source.replace("size!==29","size!==31");
source=source.replace("must contain 29 unique","must contain 31 unique");
if(!source.includes("length!==31")||!source.includes("size!==31")||!source.includes("must contain 31 unique"))
  throw Error('failed to patch procurement workflow catalog counts');
writeFileSync(path,source);
console.log('PROCUREFLOW_REAL_WORKFLOW_SELECTOR_REGISTERED=31');
const appPath=process.argv[3];
if(!appPath)throw Error('App.vue path required for project-safe N01 input defaults');
let app=readFileSync(appPath,'utf8');
const from="node01InputJson.value=JSON.stringify({ui_selection:node01Mode(),requested_detail_limit:1},null,2);";
const to="node01InputJson.value=JSON.stringify(IS_PROCUREMENT?(stockOriginal.value?.meta?.studioDefaultInput||{}):{ui_selection:node01Mode(),requested_detail_limit:1},null,2);";
if(!app.includes(from))throw Error("unexpected pinned shared App N01 defaults");
app=app.replace(from,to);
writeFileSync(appPath,app);
console.log('PROCUREFLOW_N01_DEFAULTS_FROM_WORKFLOW_META_PATCHED');
