import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { JSDOM } from 'jsdom';
const markup = readFileSync(new URL('../static/index.html', import.meta.url), 'utf8');
let generatedId = 0;
class FakeSocket {
  static OPEN = 1;
  constructor(url) {
    this.url=url;
    this.readyState=1;
    this.sent=[];
    FakeSocket.latest=this;
    setTimeout(()=>this.onopen?.(),0);
  }
  send(data) { this.sent.push(JSON.parse(data)); }
  receive(message) { this.onmessage?.({data:JSON.stringify(message)}); }
  close() { this.readyState=3;this.onclose?.({code:1000}); }
}
const dom = new JSDOM(markup, {
  url:'https://chatgpt-relay-web-production.up.railway.app/',
  runScripts:'dangerously',
  beforeParse(window) {
    window.WebSocket=FakeSocket;
    Object.defineProperty(window.crypto,'randomUUID',{value:()=>String(++generatedId),configurable:true});
  }
});
const doc=dom.window.document;
doc.querySelector('#token').value='test-console-token';
doc.querySelector('#connect').click();
await new Promise(r=>setTimeout(r,20));
let socket=FakeSocket.latest;
assert.equal(socket.sent[0].role,'console');
socket.receive({type:'auth.ok',role:'console',deviceOnline:true});
const textarea=doc.querySelector('#prompt');
textarea.value='First button test';
doc.querySelector('button[type="submit"]').click();
let commands=socket.sent.filter(p=>p.type==='command');
assert.equal(commands.length,1);
assert.equal(commands[0].action,'chat.send');
assert.equal(commands[0].payload.text,'First button test');
socket.receive({type:'command.accepted',id:commands[0].id});
socket.receive({type:'command.queued',id:commands[0].id,action:'chat.send'});
socket.receive({type:'command.received',id:commands[0].id});
socket.receive({type:'command.progress',id:commands[0].id,stage:'질문 텍스트 입력 완료'});
socket.receive({type:'command.result',id:commands[0].id,result:{stage:'send_confirmed_composer_cleared_via_named'}});
assert.match(doc.querySelector('.msg.user').dataset.delivery,/Android 전송 확인/);
textarea.value='Second enter test';
textarea.dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
commands=socket.sent.filter(p=>p.type==='command');
assert.equal(commands.length,2);
assert.equal(commands[1].payload.text,'Second enter test');
assert.equal(doc.querySelectorAll('.msg.user').length,2);
console.log('PASS: browser submit button and Enter both produce chat.send frames');
dom.window.close();
