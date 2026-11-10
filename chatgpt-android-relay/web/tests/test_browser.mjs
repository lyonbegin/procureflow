import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";

const markup=readFileSync(new URL("../static/index.html",import.meta.url),"utf8");
const defaultToken=markup.match(/id="admin-token"[^>]+value="([^"]+)"/)?.[1];
assert.ok(defaultToken?.length>=20,"Historical test console default is prefilled");
const roomId="room_test_123",jobId="job_123";
const state={rooms:[],files:[],jobs:[],messages:[]};
const calls=[];
function result(status,body){
  return {ok:status>=200&&status<300,status,
    headers:{get:()=>"application/json"},
    json:async()=>body,text:async()=>JSON.stringify(body)};
}
async function fakeFetch(url,args={}){
  const method=args.method||"GET",path=String(url),headers=args.headers||{};
  calls.push({method,path,headers,body:args.body});
  if(path==="/health")return result(200,{status:"ok",deviceOnline:true,consoleCount:1});
  if(path==="/api/v1/auth/check"||path==="/api/v1/auth/session"){
    if(headers["X-Console-Token"]==="admin-testing-secret"||
       headers["X-Console-Token"]===defaultToken)
      return result(200,{authenticated:true,role:"admin",user_id:null});
    if(headers["X-API-Key"]==="user-testing-secret")
      return result(200,{authenticated:true,role:"user",user_id:"tester-a"});
    return result(401,{detail:"Missing API key"});
  }
  if(!headers["X-Console-Token"]&&!headers["X-API-Key"])
    return result(401,{detail:"Missing API key"});
  if(path.startsWith("/api/v1/rooms?")&&method==="GET")return result(200,{rooms:state.rooms});
  if(path==="/api/v1/rooms"&&method==="POST"){
    const j=JSON.parse(args.body);
    const room={id:roomId,title:j.title,user_id:j.user_id,status:"active",android_state:"uncreated"};
    state.rooms=[room];return result(200,room);
  }
  if(path==="/api/v1/rooms/"+roomId+"/turns"&&method==="POST"){
    assert.equal(args.body.get("user_id"),"tester-a");
    assert.equal(args.body.get("text"),"What is in the photo?");
    const files=args.body.getAll("files");
    assert.equal(files.length,2);
    assert.equal(files[0].name,"picture.png");
    assert.equal(files[1].name,"report.pdf");
    state.files.push(...files.map((f,i)=>({
      id:"file_0000000000000000000000000000000"+i,
      room_id:roomId,name:f.name,size:f.size,
      kind:"input",sha256:"e".repeat(64)
    })));
    const job={id:jobId,room_id:roomId,action:"chat.send",status:"queued",stage:"queued",
      text:args.body.get("text"),attachment_ids:state.files.map(x=>x.id),
      files:state.files};
    state.jobs.push(job);
    state.messages.push({id:"msg1",role:"user",text:job.text,created_at:Date.now(),job_id:jobId});
    return result(200,job);
  }
  if(path==="/api/v1/files"&&method==="POST"){
    const f=args.body.get("file");
    assert.equal(f.name,"data.txt");
    const obj={id:"file_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",room_id:roomId,
      name:f.name,size:f.size,kind:"input",sha256:"f".repeat(64)};
    state.files.push(obj);return result(200,obj);
  }
  if(path.startsWith("/api/v1/rooms/"+roomId+"/messages")&&method==="POST"){
    const j=JSON.parse(args.body);
    state.jobs.push({id:"job_again",room_id:roomId,action:"chat.send",status:"queued",stage:"queued"});
    return result(200,{id:"job_again",text:j.text,attachment_ids:j.attachment_ids});
  }
  if(path.startsWith("/api/v1/rooms/"+roomId+"/messages")&&method==="GET")
    return result(200,{messages:state.messages});
  if(path.startsWith("/api/v1/jobs?")&&method==="GET")
    return result(200,{jobs:state.jobs});
  if(path.startsWith("/api/v1/files?")&&method==="GET")
    return result(200,{files:state.files});
  return result(404,{detail:"Unexpected mocked route "+method+" "+path});
}
class FakeSocket{
  static OPEN=1;
  constructor(){this.readyState=1;setTimeout(()=>this.onopen?.(),0);}
  send(s){assert.equal(JSON.parse(s).role,"console");}
  close(){this.readyState=3;}
}
const dom=new JSDOM(markup,{url:"https://relay.example.test/",runScripts:"dangerously",
  beforeParse(win){win.fetch=fakeFetch;win.WebSocket=FakeSocket;}});
const doc=dom.window.document;
const pause=async()=>new Promise(r=>setTimeout(r,80));
await pause();
assert.equal(doc.querySelector("#server-status").textContent,"서버 온라인");
assert.ok(!markup.includes("Google 계정 연결"),"No Google account connect flow");
assert.ok(!markup.includes('id="drive-connect"'),"No Drive popup UI");
assert.ok(markup.includes("/api/v1/rooms/{room_id}/turns"));
assert.ok(markup.includes("Railway"));
assert.equal(doc.querySelector("#admin-token").value,defaultToken);
assert.equal(doc.querySelector("#auth-notice").hidden,true);
assert.match(doc.querySelector("#api-auth-status").textContent,/인증 완료/);
assert.ok(calls.some(x=>x.path==="/api/v1/auth/session"&&x.headers["X-Console-Token"]===defaultToken),
  "Default key must auto-authenticate without manual input");
const earlier=calls.filter(x=>x.path.startsWith("/api/v1/rooms")).length;
doc.querySelector("#list-rooms").click();
await pause();
assert.ok(calls.filter(x=>x.path.startsWith("/api/v1/rooms")).length>earlier,
  "Test buttons must work with the restored default");
assert.ok(!calls.some(x=>x.headers["X-Console-Token"]===defaultToken&&x.path.startsWith("/api/v1/")&&x.path!=="/api/v1/auth/session"&&x.method==="BAD"));
doc.querySelector("#admin-token").value="admin-testing-secret";
doc.querySelector("#verify-auth").click();
await pause();
assert.equal(doc.querySelector("#auth-notice").hidden,true);
assert.match(doc.querySelector("#api-auth-status").textContent,/인증 완료/);
assert.ok(calls.some(x=>x.path==="/api/v1/auth/session"),"First validated login creates a secure session");
doc.querySelector("#room-title").value="Direct relay room";
doc.querySelector("#create-room").click();
await pause();
assert.equal(doc.querySelector("#room-id").value,roomId);

let selected=[
  new dom.window.File(["pngbytes"],"picture.png",{type:"image/png"}),
  new dom.window.File(["pdfbytes"],"report.pdf",{type:"application/pdf"})
];
const picker=doc.querySelector("#file-pick");
Object.defineProperty(picker,"files",{get:()=>selected,configurable:true});
picker.onchange();
assert.match(doc.querySelector("#local-file-preview").textContent,/picture.png/);
doc.querySelector("#message-text").value="What is in the photo?";
doc.querySelector("#send-job").click();
await pause();
assert.equal(state.jobs.length,1);
assert.equal(state.files.length,2);
assert.equal(state.messages.length,1);
assert.equal(doc.querySelector("#job-id").value,jobId);
assert.ok(calls.some(x=>x.path==="/api/v1/rooms/"+roomId+"/turns"&&x.method==="POST"));
assert.ok(!calls.some(x=>x.path.startsWith("/api/v1/drive/")));
assert.match(doc.querySelector("#file-list").textContent,/Railway/);

selected=[new dom.window.File(["text"],"data.txt",{type:"text/plain"})];
doc.querySelector("#upload-file").click();
await pause();
assert.equal(state.files.length,3);
assert.ok(calls.some(x=>x.path==="/api/v1/files"&&x.method==="POST"));
selected=[];
await pause();
const check=[...doc.querySelectorAll(".filecheck")].find(x=>!x.disabled&&!x.checked);
assert.ok(check);
check.click();
doc.querySelector("#message-text").value="Read my saved file";
doc.querySelector("#send-job").click();
await pause();
const saved=calls.find(x=>x.path.endsWith("/messages")&&x.method==="POST");
assert.ok(saved);
// Newly uploaded file is preselected; selecting another saved file results in both.
assert.equal(JSON.parse(saved.body).attachment_ids.length,2);
assert.ok(!calls.some(x=>x.path.includes("/drive/")));
console.log("PASS: historical default prefilled and auto-authenticated; API tester works without manual key input");
dom.window.close();
