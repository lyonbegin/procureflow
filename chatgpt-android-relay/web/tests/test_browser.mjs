import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";
const markup=readFileSync(new URL("../static/index.html",import.meta.url),"utf8");
let roomId="room_test_123",fileId="file_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", jobId="job_123";
const state={rooms:[],files:[],jobs:[],messages:[]};
const calls=[];
function result(status,body){
  return {ok:status>=200&&status<300,status,
          headers:{get:()=> "application/json"},json:async()=>body,text:async()=>JSON.stringify(body)};
}
async function fakeFetch(url,args={}){
  const method=args.method||"GET",str=String(url), headers=args.headers||{};
  calls.push({method,url:str,headers,body:args.body});
  if(str==="/health")return result(200,{status:"ok",deviceOnline:true,consoleCount:1});
  if(!headers["X-Console-Token"]&&!headers["X-API-Key"])return result(401,{detail:"Missing API key"});
  if(str==="/api/v1/users"&&method==="POST")return result(200,{user_id:"tester-a",api_key:"generated",name:"tester-a"});
  if(str.startsWith("/api/v1/rooms?")&&method==="GET")return result(200,{rooms:state.rooms});
  if(str==="/api/v1/rooms"&&method==="POST"){
    const body=JSON.parse(args.body);const room={id:roomId,title:body.title,user_id:body.user_id,status:"active",android_state:"uncreated"};
    state.rooms=[room];return result(200,room);
  }
  if(str.startsWith("/api/v1/rooms/"+roomId+"/messages")&&method==="POST"){
    const body=JSON.parse(args.body);state.jobs.push({id:jobId,room_id:roomId,action:"chat.send",stage:"queued",status:"queued"});
    state.messages.push({id:"msg_1",room_id:roomId,role:"user",text:body.text,created_at:Date.now(),job_id:jobId});
    return result(200,{...state.jobs[0],text:body.text,attachment_ids:body.attachment_ids});
  }
  if(str.startsWith("/api/v1/rooms/"+roomId+"/messages")&&method==="GET")return result(200,{messages:state.messages});
  if(str.startsWith("/api/v1/jobs?")&&method==="GET")return result(200,{jobs:state.jobs});
  if(str.startsWith("/api/v1/files?")&&method==="GET")return result(200,{files:state.files});
  if(str==="/api/v1/drive/files"&&method==="POST"){
    assert.equal(args.body.get("share_link"),"true");
    const obj={id:fileId,name:"image.png",size:10,kind:"drive",sha256:"f".repeat(64),room_id:roomId,
               drive_shared:1,drive_file_id:"drive123",drive_url:"https://drive.google.com/file/d/drive123/view"};
    state.files.push(obj);return result(200,obj);
  }
  if(str.startsWith("/api/v1/drive/status")&&method==="GET")
    return result(200,{user_id:"tester-a",configured:false,connected:false});
  if(str.startsWith("/api/v1/rooms/"+roomId)&&method==="DELETE")return result(200,{room_id:roomId,status:"delete_pending",job_id:"del_1"});
  return result(404,{detail:"Unexpected mocked route "+method+" "+str});
}
class FakeSocket{
  static OPEN=1;
  constructor(){this.readyState=1;setTimeout(()=>this.onopen?.(),0);}
  send(s){const p=JSON.parse(s);assert.equal(p.role,"console");}
  close(){this.readyState=3;}
}
const dom=new JSDOM(markup,{
 url:"https://relay.example.test/",
 runScripts:"dangerously",
 beforeParse(win){win.fetch=fakeFetch;win.WebSocket=FakeSocket;}
});
const doc=dom.window.document;
const pause=async()=>new Promise(r=>setTimeout(r,60));
await pause();
assert.equal(doc.querySelector("#server-status").textContent,"서버 온라인");
assert.equal(doc.querySelector("#admin-token").value,""); // Never embed admin secret in public HTML.
doc.querySelector("#admin-token").value="admin-testing-secret";
doc.querySelector("#room-title").value="API room test";
doc.querySelector("#create-room").click();
await pause();
assert.equal(doc.querySelector("#room-id").value,roomId);
assert.ok(state.rooms.length===1);
doc.querySelector("#message-text").value="Analyze contents";
doc.querySelector("#send-job").click();
await pause();
assert.equal(state.jobs.length,1);
assert.equal(state.messages.length,1);
const outgoing=calls.find(c=>c.method==="POST"&&c.url.endsWith("/messages"));
assert.deepEqual(JSON.parse(outgoing.body).attachment_ids,[]);
assert.equal(JSON.parse(outgoing.body).user_id,"tester-a");
assert.equal(doc.querySelector("#job-id").value,jobId);
// The file upload path is Google Drive, NOT the legacy Railway /files path.
doc.querySelector("#share-drive-link").checked=true;
const selection=doc.querySelector("#file-pick");
Object.defineProperty(selection,"files",{value:[new dom.window.File(["pngbytes"],"image.png",{type:"image/png"})],configurable:true});
doc.querySelector("#upload-file").click();
await pause();
assert.equal(state.files.length,1);
assert.equal(state.files[0].kind,"drive");
assert.ok(calls.some(x=>x.method==="POST"&&x.url==="/api/v1/drive/files"));
assert.ok(!calls.some(x=>x.method==="POST"&&x.url==="/api/v1/files"));
assert.ok(doc.querySelector("#request-preview").textContent.includes("/api/v1/rooms"));
assert.ok(doc.querySelector("#response-preview").textContent.includes("messages"));
doc.querySelector("#file-pick");
assert.ok(doc.querySelector("#upload-file"));
assert.ok(doc.querySelector("#delete-room"));
assert.ok(doc.querySelector("#list-files"));
assert.ok(doc.querySelector("#list-messages"));
assert.ok(doc.querySelector("#endpoint-tabs"));
console.log("PASS: API tester creates room and messages; Drive upload only, explicit share, no public embedded token");
dom.window.close();
