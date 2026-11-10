import { chromium } from "playwright";
import { mkdir, rename } from "node:fs/promises";
import { spawnSync } from "node:child_process";

const dir="emulator-evidence";
await mkdir(dir,{recursive:true});
const browser=await chromium.launch({headless:true,args:["--disable-blink-features=AutomationControlled"]});
const context=await browser.newContext({
  locale:"en-US",
  viewport:{width:1460,height:1000},
  acceptDownloads:true,
  userAgent:"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
});
const page=await context.newPage();
page.setDefaultTimeout(12000);
const start="https://www.apkmirror.com/apk/openai/chatgpt/chatgpt-1-2026-300-release/";
let download;
page.on("download", d=>{download=d;});
const visited=[];
async function snapshot(n){
 const title=await page.title().catch(()=>"");
 const url=page.url();
 const body=await page.locator("body").innerText().catch(()=>"");
 const anchors=await page.locator("a").evaluateAll(arr=>arr.map(a=>({
   text:(a.innerText||"").replace(/\s+/g," ").trim().slice(0,90),
   href:a.href
 })).filter(a=>a.href && /download|2026-300|120-640|apkm|bundle/i.test(a.text+" "+a.href))).catch(()=>[]);
 console.log("PAGE",n,JSON.stringify({title,url,bodySample:body.slice(0,600),links:anchors.slice(0,50)}));
 await page.screenshot({path:dir+"/mirror-"+n+".png",fullPage:false}).catch(()=>{});
 return {title,url,body,anchors};
}
try{
 await page.goto(start,{waitUntil:"domcontentloaded",timeout:45000});
 for(let n=0;n<10;n++){
   await page.waitForTimeout(n===0?4000:1500);
   const state=await snapshot(n);
   visited.push(state.url);
   if(download)break;
   if(/just a moment|performing security verification|checking your browser|cloudflare/i.test(state.title+" "+state.body.slice(0,800))){
     console.log("WAIT_FOR_STANDARD_SITE_VERIFICATION",n);
     await page.waitForTimeout(12000);
     continue;
   }
   if(/cannot be loaded without javascript|attention required|verify you are human|access denied|error 403/i.test(state.body.slice(0,800))){
     console.log("BLOCKED_MIRROR_JS_CHALLENGE");
     break;
   }
   // Prefer the exact universal 120-640dpi variant (35-split package).
   const links=state.anchors;
   const candidates=[
     ...links.filter(x=>/download apk bundle|download apkm|download bundle/i.test(x.text)),
     ...links.filter(x=>/1\.2026\.300/i.test(x.text)&&/120-640/i.test(x.text)),
     ...links.filter(x=>/\/download\/\??/.test(x.href)&&!visited.includes(x.href)),
     ...links.filter(x=>/2026-300.*android-apk-download/.test(x.href)&&!visited.includes(x.href))
   ];
   const next=candidates.find(x=>!visited.includes(x.href) && x.href.startsWith("https://www.apkmirror.com/"));
   if(!next){
     console.log("BLOCKED_NO_DOWNLOAD_LINK");
     break;
   }
   console.log("FOLLOW",next.text,next.href);
   const started=page.waitForEvent("download",{timeout:9000}).catch(()=>null);
   await page.goto(next.href,{waitUntil:"domcontentloaded",timeout:45000}).catch(e=>console.log("NAV_ERROR",String(e).slice(0,200)));
   download=await started;
   if(download)break;
 }
 if(!download){
  console.error("BLOCKED_BROWSER_DOWNLOAD: no exact APKM downloaded");
  process.exitCode=40;
 }else{
  const fname=download.suggestedFilename();
  const loc="/tmp/chatgpt-browser-download"+(fname.match(/\.(apkm|xapk|zip)$/i)?.[0]||".apkm");
  await download.saveAs(loc);
  const check=spawnSync("python3",[".github/scripts/check-chatgpt-variant.py",loc],{encoding:"utf8"});
  console.log("DOWNLOADED",fname,check.stdout,check.stderr);
  if(check.status===0){
   await rename(loc,"/tmp/chatgpt-download.pkg");
   console.log("MATCHED_UPLOADED_X86_64_SPLITS");
  }else{
   console.error("BLOCKED_BROWSER_SHA256_MISMATCH");
   process.exitCode=41;
  }
 }
}finally{
 await browser.close();
}
