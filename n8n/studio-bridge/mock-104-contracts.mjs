// Offline contract simulator for all 43 business blocks and 104 features.
// No network, filesystem mutation, G2B lookup, credentials or n8n engine calls.
import {createHash} from 'node:crypto';
const clone=v=>JSON.parse(JSON.stringify(v));
export function simulateAllContracts(manifest,{caseId='DEMO_ONLY',injections={}}={}){
 if(caseId!=='DEMO_ONLY')throw Error('Only DEMO_ONLY fixtures are permitted');
 if(manifest.engine!=='n8n_only'||manifest.blocks?.length!==43)throw Error('Unexpected manifest');
 const ids=new Set(),featureOwners=new Map(),records=[];
 for(const [index,block] of manifest.blocks.entries()){
  if(ids.has(block.id))throw Error('Duplicate block '+block.id);
  ids.add(block.id);
  const features=[];
  for(const no of block.features||[]){
   if(!Number.isInteger(no)||no<1||no>104)throw Error('Invalid feature '+no);
   features.push(no);
   featureOwners.set(no,[...(featureOwners.get(no)||[]),block.id]);
  }
  const injected=injections[block.id]||{};
  const ok=injected.fail!==true;
  const record={sequence:index+1,blockId:block.id,name:block.label,
   input:{contract:block.input,caseId,source:'synthetic_fixture'},
   output:ok?{contract:block.output,fixtureValue:'MOCK_'+block.id}:null,
   successors:clone(block.to||[]),features,
   status:ok?'MOCK_PASS':'MOCK_HOLD',error:ok?null:'INJECTED_FAILURE',
   actualJobExecuted:false,simulationOnly:true};
  records.push(record);
 }
 for(const rec of records)for(const to of rec.successors)
  if(!ids.has(to))throw Error('Unknown successor '+to);
 const missing=Array.from({length:104},(_,i)=>i+1).filter(i=>!featureOwners.has(i));
 if(missing.length)throw Error('Unmapped features: '+missing.join(','));
 const coverage=Array.from({length:104},(_,i)=>({number:i+1,blocks:featureOwners.get(i+1),
  status:featureOwners.get(i+1).some(id=>records.find(r=>r.blockId===id).status!=='MOCK_PASS')?'MOCK_HOLD':'MOCK_PASS'}));
 const held=records.filter(x=>x.status==='MOCK_HOLD').map(x=>x.blockId);
 const fingerprint=createHash('sha256').update(JSON.stringify({caseId,records,coverage})).digest('hex');
 return {schema:'procureflow.mock-contract-e2e.v1',caseId,engine:'offline_contract_simulator',
  simulationOnly:true,actualJobExecuted:false,officialEvidenceVerified:false,bidSubmitted:false,
  status:held.length?'HOLD':'MOCK_COMPLETE',held,blocks:records,featureCoverage:coverage,
  counts:{blocks:records.length,features:coverage.length,mockedPass:coverage.filter(x=>x.status==='MOCK_PASS').length},
  fingerprint};
}
