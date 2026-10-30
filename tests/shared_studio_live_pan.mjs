import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
const url=process.env.STUDIO_LIVE_URL||'https://procureflow-n8n-native-canvas-production.up.railway.app/?workflow=operations%2FPF05.json';
await mkdir('shared-studio-live-pan-artifacts',{recursive:true});
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
try{
  const page=await browser.newPage({viewport:{width:1680,height:1050}});
  const errors=[];
  page.on('pageerror',err=>errors.push(err.message));
  await page.goto(url,{waitUntil:'domcontentloaded',timeout:45000});
  await page.waitForFunction(()=>document.querySelectorAll('.vue-flow__node').length>=35,{timeout:35000});
  const pageText=await page.locator('body').innerText();
  assert(pageText.includes('SHARED N8N STUDIO'),'Wrong editor implementation');
  assert(pageText.includes('PROCUREFLOW'),'Wrong project mode');
  assert(pageText.includes('35 Nodes')&&pageText.includes('43 Connections'),'PF05 missing graph');
  assert(!pageText.includes('Set up owner account'),'Owner setup screen visible');
  await page.locator('button[title="화면 맞춤"]').click();
  await page.waitForTimeout(500);
  const inspect=()=>page.evaluate(()=>{
    const viewport=document.querySelector('.vue-flow__viewport');
    const pane=document.querySelector('.vue-flow__pane');
    const node=document.querySelector('.vue-flow__node[data-id="pf05-5"]');
    if(!viewport||!pane||!node)throw Error('Required native Vue Flow DOM missing');
    // Vue Flow moves its TRANSFORMATION PANE, not necessarily .vue-flow__viewport.
    // Measure both so a non-moving wrapper cannot produce false PASS or FAIL.
    const transformPane=document.querySelector('.vue-flow__transformationpane');
    const coord=el=>{
      if(!el)return null;
      const matrix=new DOMMatrixReadOnly(getComputedStyle(el).transform);
      return {css:getComputedStyle(el).transform,x:matrix.m41,y:matrix.m42,scale:matrix.m11};
    };
    return {viewport:coord(viewport),transformationpane:coord(transformPane),
      nodeStyle:node.getAttribute('style')||'',
      nodeCount:document.querySelectorAll('.vue-flow__node').length};
  });
  const before=await inspect();
  const point=await page.evaluate(()=>{
    const pane=document.querySelector('.vue-flow__pane');
    const r=pane.getBoundingClientRect();
    for(const [fx,fy] of [[.72,.74],[.17,.79],[.65,.88],[.82,.31],[.24,.63],[.72,.20],[.53,.70]]){
      const x=Math.round(r.left+r.width*fx),y=Math.round(r.top+r.height*fy);
      if(x<r.left+20||x>r.right-175||y<r.top+15||y>r.bottom-95)continue;
      const element=document.elementFromPoint(x,y);
      if(element&&(element===pane||element.closest('.vue-flow__pane')===pane)&&!element.closest('.vue-flow__node'))return{x,y,at:element.className?.baseVal||element.className};
    }
    return null;
  });
  assert(point,'No safe blank canvas pane to drag');
  await page.mouse.move(point.x,point.y);
  await page.mouse.down({button:'left'});
  await page.mouse.move(point.x+140,point.y+75,{steps:20});
  await page.mouse.up({button:'left'});
  await page.waitForTimeout(450);
  const after=await inspect();
  const elements=['transformationpane','viewport'];
  const shifts=elements.filter(k=>before[k]&&after[k]).map(k=>({
    element:k,dx:after[k].x-before[k].x,dy:after[k].y-before[k].y,
    scaleBefore:before[k].scale,scaleAfter:after[k].scale
  }));
  const changed=shifts.find(x=>Math.abs(x.dx)>15||Math.abs(x.dy)>15);
  const result={url,before,after,dragStart:point,intendedDelta:{x:140,y:75},
    observedTransforms:shifts,changedElement:changed?.element||null,
    logicalNodePositionUnchanged:before.nodeStyle===after.nodeStyle,
    noPageErrors:errors.length===0,errors};
  await page.screenshot({path:'shared-studio-live-pan-artifacts/live-PF05-pan-after.png',fullPage:true});
  await writeFile('shared-studio-live-pan-artifacts/pan-verdict.json',JSON.stringify(result,null,2));
  console.log('PROCUREFLOW_SHARED_STUDIO_LIVE_PAN_VERDICT',JSON.stringify(result));
  assert(changed,'Blank canvas left mouse drag did NOT change either the transformationpane or viewport');
  assert.equal(before.nodeStyle,after.nodeStyle,'Logical node moved while dragging blank canvas');
  assert.equal(before.nodeCount,35);
  assert.equal(after.nodeCount,35);
  assert.equal(errors.length,0,'Browser Vue errors during Pan');
  console.log('PROCUREFLOW_SHARED_STUDIO_LIVE_BLANK_PAN_PASS');
}finally{await browser.close();}
