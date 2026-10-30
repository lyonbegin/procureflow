// Server-side adapter for observing existing n8n execution IDs; NOT a runner.
// Requires an existing API key from runtime env. Never returns it or sends it to Studio browsers.
export async function inspectN8nExecution({baseUrl,apiKey,executionId,transport=fetch}){
 if(!/^https:\/\//.test(baseUrl||'')&&!/^http:\/\/127\.0\.0\.1(:\d+)?$/.test(baseUrl||''))
  throw Error('Existing secure n8n endpoint required');
 if(!apiKey)throw Error('Existing n8n service API key not configured');
 if(!/^[A-Za-z0-9_-]{1,80}$/.test(String(executionId)))throw Error('Invalid execution ID');
 const url=baseUrl.replace(/\/+$/,'')+'/api/v1/executions/'+encodeURIComponent(executionId)+'?includeData=true';
 const response=await transport(url,{method:'GET',headers:{'X-N8N-API-KEY':apiKey,'Accept':'application/json'},redirect:'error',signal:AbortSignal.timeout(12000)});
 if(!response.ok)throw Error('Existing n8n execution query HTTP '+response.status);
 const execution=await response.json();
 if(String(execution.id)!==String(executionId))throw Error('Execution ID mismatch');
 const runData=execution.data?.resultData?.runData||{};
 const nodes=Object.entries(runData).map(([name,attempts])=>({
  name,status:attempts.some(a=>a.error)?'error':attempts.length?'success':'unknown',
  durationMs:attempts.reduce((a,b)=>a+(b.executionTime||0),0),
  attempts:attempts.length,
  // Do not return raw potentially sensitive production node I/O to anonymous browser clients.
 }));
 return {executionId:String(execution.id),status:execution.status||'unknown',
  finished:execution.finished===true,mode:'existing_official_n8n_read_only',
  nodes,hasExecutionData:Object.keys(runData).length>0};
}
