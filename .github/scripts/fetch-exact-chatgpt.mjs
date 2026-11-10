import { mkdir, readdir, stat, copyFile } from "node:fs/promises";
import { resolve, dirname, extname, join } from "node:path";
import { spawnSync } from "node:child_process";

const ROOT=resolve("mirror-download");
await mkdir(ROOT,{recursive:true});
const variants=[
  ["apkmirror-downloader","APKMirrorDownloader",
    {org:"openai",repo:"chatgpt"},
    [{version:"1.2026.300",arch:"universal",dpi:"120-640dpi",type:"bundle"},
     {version:"1.2026.300",arch:"universal",type:"bundle"}]],
  ["@nirewen/apkcombo-downloader","APKComboDownloader",
    {org:"chatgpt",repo:"com.openai.chatgpt"},
    [{version:"1.2026.300",arch:"universal",dpi:"120-640dpi",type:"bundle"},
     {version:"1.2026.300",arch:"universal",type:"bundle"}]]
];
async function files(root){
 const all=[];
 for(const entry of await readdir(root,{withFileTypes:true})){
   const p=join(root,entry.name);
   if(entry.isDirectory())all.push(...await files(p));
   else if(entry.isFile())all.push(p);
 }
 return all;
}
for(const [packageName,className,app,options] of variants){
 for(const [i,opt] of options.entries()){
  const out=join(ROOT,packageName.replace(/\W+/g,"_")+"_"+i);
  await mkdir(out,{recursive:true});
  console.log("Source",packageName,"query",JSON.stringify(opt));
  try{
   const mod=await import(packageName);
   const download=new mod[className]({outDir:out,overwrite:true});
   const result=await download.download(app,{...opt,outFile:"chatgpt_1_2026_300"});
   console.log("Downloader returned",typeof result, typeof result==="string"?result.slice(0,300):"");
  }catch(e){console.error("Downloader failed",String(e?.message||e).slice(0,600))}
  const discovered=await files(out);
  for(const candidate of discovered){
   if(!/\.(apkm|apks|xapk|zip)$/i.test(candidate))continue;
   const verify=spawnSync("python3",[".github/scripts/check-chatgpt-variant.py",candidate],{encoding:"utf8"});
   console.log("Check",candidate,verify.stdout.slice(0,400),verify.stderr.slice(0,300));
   if(verify.status===0){
    await copyFile(candidate,"/tmp/chatgpt-download.pkg");
    console.log("EXACT_CHATGPT_VARIANT_FOUND",candidate);
    process.exit(0);
   }
  }
 }
}
console.error("BLOCKED_PUBLIC_MIRRORS: no exact user-submitted APK variant found");
process.exit(41);
