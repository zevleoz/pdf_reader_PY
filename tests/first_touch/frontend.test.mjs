import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
const root = process.cwd();
const require = createRequire(path.join(root, 'frontend/package.json'));
const { build } = require('esbuild');
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'ft-test-'));
await build({ stdin: { contents: `export * from './src/pages/first-touch/controller'; export * from './src/pages/first-touch/observable'; export * from './src/pages/first-touch/bootstrap'; export * from './src/pages/first-touch/navigation'; export {default as View, ChatPanel} from './src/pages/first-touch/WorkspaceView'; export {Sheet} from './src/components/ui/sheet'; export {createElement} from 'react'; export {renderToStaticMarkup} from 'react-dom/server';`, resolveDir: path.join(root, 'frontend'), loader: 'ts' }, bundle: true, platform: 'node', format: 'cjs', outfile: path.join(temporary,'entry.cjs'), tsconfig: path.join(root,'frontend/tsconfig.json') });
const { attachController, observable, bootstrap, guardNavigation, View, ChatPanel, Sheet, createElement, renderToStaticMarkup } = require(path.join(temporary,'entry.cjs'));
const source = fs.readFileSync('static/js/first_touch_workspace.js','utf8');
const ctx = {sid:1,code:'TEST',name:'同学',grade:'10',school:'学校',advisorName:'顾问',canWrite:true,canStart:true,readOnly:false,role:'admin',sessionId:4};
function raw(overrides={}) {
 const window = { crypto: globalThis.crypto, addEventListener(){},removeEventListener(){} };
 new Function('window', 'fetch', 'v2Toast', source + '; return window.ftWorkspace;')(window, (...args) => globalThis.fetch(...args), () => {});
 // Build in the host realm so ordinary JSON containers use the real plain-object prototype.
 return Object.assign(window.ftWorkspace(ctx), overrides);
}
globalThis.document = { querySelector(){return null;} };
test('deep observation preserves native receivers and stable proxy identities', () => {
 let changed=0; const abort=new AbortController(), date=new Date(), form=new FormData();
 const c=observable({ nested:{rows:[]},abort,date,form },()=>changed++);
 c.nested.rows.push({label:'one'}); c.nested.rows[0].label='two';
 assert.ok(changed>=2); assert.equal(c.abort,abort); assert.equal(c.date,date); assert.equal(c.form,form);
 assert.equal(c.nested,c.nested); c.abort.abort(); assert.ok(abort.signal.aborted);
});
test('dispose aborts inflight request and rejects future requests BEFORE fetch',async()=>{
 let calls=0, signal;
 globalThis.fetch=(_path, options)=> { calls++; signal=options.signal; return new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(new DOMException('stopped','AbortError')))); };
 const a=attachController(raw(),()=>{});
 const pending=a.controller.request('/test'); const rejected=assert.rejects(pending,{name:'AbortError'});
 a.dispose(); await rejected; assert.ok(signal.aborted);
 await assert.rejects(a.controller.request('/mutation',{method:'POST'}),{name:'AbortError'}); assert.equal(calls,1);
});
test('caller abort composes with lifetime and aborts active polling fetch',async()=>{
 let signal;
 globalThis.fetch=(_path,options)=>{signal=options.signal;return new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(new DOMException('stopped','AbortError'))));};
 const a=attachController(raw(),()=>{}), abort=new AbortController();
 const request=a.controller.pollJob('job',abort.signal);const rejected=assert.rejects(request,{name:'AbortError'});
 abort.abort();await rejected;assert.ok(signal.aborted);a.dispose();
});
test('dispose rejects delays, clears timers and blocks stale continuation timers',async t=>{
 t.mock.timers.enable({apis:['setTimeout','setInterval']});
 let requests=0;globalThis.fetch=async()=>{requests++;return {ok:true,json:async()=>({status:'running'})};};
 const a=attachController(raw(),()=>{}); const c=a.controller;
 const delay=c.delay(1200);const rejection=assert.rejects(delay,{name:'AbortError'});
 c.startTimer(); c.saveTimer=setTimeout(()=>c.flushSave(),800); c.undoInterval=setInterval(()=>{},1000); c.previewTimer=setTimeout(()=>c.refreshPreview(),600);
 c.$nextTick(()=>assert.fail('disposed nextTick fired'));
 a.dispose(); await rejection; c.scheduleSave(); c.startTimer(); t.mock.timers.tick(10000); assert.equal(requests,0);
});
test('late request response cannot enter applySessionData or start downstream mutation',async()=>{
 let resolve;let calls=0;
 globalThis.fetch=()=>{calls++;return new Promise(r=>resolve=r);};
 const a=attachController(raw(),()=>{});const pending=a.controller.loadSession();a.dispose();
 resolve({ok:true,json:async()=>({session:{id:99,phase:2,revision:8}})});await pending;
 assert.equal(a.controller.sessionId,4);assert.equal(calls,1);
});
test('bootstrap gates summary before requests; resolves student then profile; viewer read only',async()=>{
 const boot={policy:{detail_level:'summary'},user:{role:'viewer'}};let paths=[];
 globalThis.fetch=async(url)=>{paths.push(url);return {ok:true,json:async()=>url==='/api/students'?{students:[{id:1,student_code:'TEST',name:'同学'}]}:{student:{id:1},permissions:{full:true,can_write:false},first_touch:{canStart:true,sessionId:4}}};};
 const signal=new AbortController().signal;
 assert.equal(await bootstrap('1',boot,signal),null);assert.deepEqual(paths,[]);
 boot.policy.detail_level='full';const result=await bootstrap('1',boot,signal);assert.ok(result.readOnly);assert.equal(result.sessionId,4);
 assert.deepEqual(paths,['/api/students','/api/profiling/students/TEST']);
 await assert.rejects(bootstrap('2',boot,signal),/范围/);
});
test('render each phase with original labels and actions, no escaped Chinese or Alpine runtime',()=>{
 const c=raw(); c.loading=false;
 c.interests=[{id:'i1',label:'天文',topicType:'interest',note:'观察',preferenceScore:3,competenceScore:2,specialFocus:true}];
 c.script={talkingPoints:['追问'],nextSummary:'总结'};
 for(const [step,strings] of [[0,['会谈提示','追问','AI 生成提示']],[1,['兴趣事项','兴趣分型','特别关注','备注','撤销']],[2,['会议转写','会谈总结','项目建议','确认报告']]]){
  c.step=step;c.undo={item:c.interests[0]};const html=renderToStaticMarkup(createElement(View,{c}));
  for(const text of strings)assert.ok(html.includes(text),text);
  assert.ok(!html.includes('\\u'));assert.ok(!html.includes('x-data'));assert.ok(!html.includes('iframe'));assert.ok(html.includes('会谈步骤'));
 }
 c.drawerOpen=true;c.chat.turns=[{question:'问题',answer:'回答',status:'COMPLETE'}];
 const html=renderToStaticMarkup(createElement(Sheet, {open:true}, createElement(ChatPanel,{c})));assert.ok(html.includes('回答'));assert.ok(html.includes('Shift+Enter'));
});
test('dirty back rejection restores by index once, no recursive popstate or premature router event',()=>{
 const listeners={};let confirmed=0,go,blocked=0;
 globalThis.location={href:'http://test/app/first-touch/students/1'};
 globalThis.history={state:{idx:5},go(delta){go=delta;},pushState(){assert.fail('should compensate with history.go');}};
 globalThis.window={confirm(){confirmed++;return false;},addEventListener(type,fn,capture){listeners[type]=fn;assert.equal(capture,true);},removeEventListener(type){delete listeners[type];}};
 globalThis.document={addEventListener(type,fn){listeners[type]=fn;},removeEventListener(type){delete listeners[type];}};
 const cleanup=guardNavigation({hasPendingSave:()=>true});
 history.state={idx:4};listeners.popstate({stopImmediatePropagation(){blocked++;}});
 assert.equal(go,1);assert.equal(confirmed,1);assert.equal(blocked,1);
 history.state={idx:5};listeners.popstate({stopImmediatePropagation(){blocked++;}});assert.equal(confirmed,1);assert.equal(blocked,2);
 let prevented=false;listeners.click({target:{closest:()=>({})},preventDefault(){prevented=true;},stopImmediatePropagation(){}});assert.ok(prevented);
 cleanup();assert.deepEqual(listeners,{});
});
process.on('exit',()=>fs.rmSync(temporary,{recursive:true,force:true}));
test('shared interest actions preserve scores, category, focus, notes, deletion and undo',()=>{
 const a=attachController(raw(),()=>{}),c=a.controller;
 c.newInterest='天文';c.addInterest();assert.equal(c.interests.length,1);
 const row=c.interests[0];c.setScore(row,'preferenceScore',3);c.setScore(row,'competenceScore',2);
 c.setNote(row,'观察星空');c.toggleStar(row);c.cycleCategory(row);
 assert.equal(row.preferenceScore,3);assert.equal(row.competenceScore,2);assert.ok(row.specialFocus);assert.equal(row.note,'观察星空');
 c.beginRename(row);c.nameDraft='天文学';c.commitRename(row);assert.equal(row.label,'天文学');
 c.deleteInterest(row);assert.equal(c.interests.length,0);c.undoDelete();assert.equal(c.interests[0].label,'天文学');a.dispose();
});
test('409 revision mismatch remains a conflict; generation 503 remains a visible error',async()=>{
 globalThis.document={querySelector(){return null;}};
 globalThis.fetch=async()=>({ok:false,status:409,json:async()=>({error:'版本冲突'})});
 const a=attachController(raw(),()=>{}),c=a.controller;c.newInterest='天文';c.addInterest();await c.flushSave();
 assert.ok(c.conflict.active);assert.ok(c.interestDirty);
 globalThis.fetch=async()=>({ok:false,status:503,json:async()=>({error:'任务暂不可用'})});
 c.conflict=null;await c.generateTalkingPoints();assert.equal(c.talkError,'任务暂不可用');a.dispose();
});
test('viewer actions cannot dispatch changes; aborted bootstrap does not issue a second request',async()=>{
 let calls=0;globalThis.fetch=async()=>{calls++;return {ok:true,json:async()=>({students:[{id:1,student_code:'TEST'}]})};};
 const a=attachController(raw({canWrite:false,readOnly:true}),()=>{});a.controller.newInterest='禁止';a.controller.addInterest();await a.controller.createSession();assert.equal(calls,0);a.dispose();
 const abort=new AbortController();globalThis.fetch=async()=>({ok:true,json:async()=>{abort.abort();return {students:[{id:1,student_code:'TEST'}]};}});
 await assert.rejects(bootstrap('1',{policy:{detail_level:'full'},user:{role:'admin'}},abort.signal),{name:'AbortError'});
});
test('preview, confirmation and exports use the shared revision-only report contract',async()=>{
 globalThis.document={querySelector(){return null;}};const calls=[];
 globalThis.fetch=async(path,options)=>{calls.push({path,method:options.method,body:JSON.parse(options.body)});return {ok:true,json:async()=>path.endsWith('/report-preview')?{missing:[],draft:{summary:'已检查'}}:{report:{id:81,version:2},revision:9}};};
 const a=attachController(raw({revision:8}),()=>{}),c=a.controller;
 await c.refreshPreview();assert.ok(c.confirmReady);await c.confirmReport();
 assert.equal(c.status,'COMPLETED');assert.equal(c.revision,9);assert.equal(c.downloadHref('pdf'),'/api/growth-talk/reports/81/download.pdf');assert.equal(c.downloadHref('json'),'/api/growth-talk/reports/81/download.json');
 assert.deepEqual(calls.map(x=>[x.path,x.method,x.body]),[['/api/v2/copilot/sessions/4/report-preview','POST',{revision:8}],['/api/v2/copilot/sessions/4/report-confirm','POST',{revision:8}]]);a.dispose();
});
test('generation preserves job envelopes and project provenance gate',async()=>{
 const calls=[];let jobResult={revision:2,result:{summary:'共享起草结果'}};
 globalThis.fetch=async(path,options)=>{calls.push({path,options});return {ok:true,json:async()=>path.includes('/jobs/')?{status:'done',result:jobResult}:{jobId:'synthetic'}};};
 const a=attachController(raw(),()=>{}),c=a.controller;
 await c.generateSummary();assert.equal(c.script.nextSummary,'共享起草结果');assert.equal(c.revision,2);
 c.meetingSourceId=7;jobResult={revision:3,batch:{items:[{recommendationId:'p',title:'星空研究',status:'advisor_excluded',interestRefs:[],evidenceQuotes:[]}]}};
 await c.generateProjects();assert.equal(c.projectItems[0].title,'星空研究');
 const before=calls.length;await c.toggleProject(c.projectItems[0]);assert.equal(calls.length,before);assert.ok(c.projectsError.includes('证据'));
 a.dispose();
});
test('DOM refs are imperative and do not produce render loops; history actions remain available',async()=>{
 let notifications=0;const a=attachController(raw(),()=>notifications++);a.controller.$refs.addInput={focus(){}};a.controller.$refs.addInput=null;assert.equal(notifications,0);
 globalThis.fetch=async(path)=>({ok:true,json:async()=>path.includes('/chats/')?{chat:{chatId:'history',turns:[{question:'历史问题',answer:'历史回答'}]}}:{chats:[{chatId:'history',question:'历史问题'}]}});
 await a.controller.loadChats();assert.equal(a.controller.chat.chatId,'history');assert.equal(a.controller.chat.turns[0].answer,'历史回答');a.dispose();
});

test('pasted transcripts use the file upload and keep the draft on failure', async () => {
 const transcript = '顾问：你最近在做什么？\n学生：我在观察星空。';
 const c = raw({ transcriptPaste: transcript, revision: 7 });
 let analyses = 0;
 c.analyzeTranscript = async () => { analyses++; };
 c.request = async () => { throw new Error('上传失败'); };
 await c.submitPastedTranscript();
 assert.equal(c.transcriptPaste, transcript);
 assert.equal(c.uploadError, '上传失败');
 assert.equal(analyses, 0);
 assert.ok(c.hasPendingSave());

 c.request = async (url, options) => {
  assert.equal(url, '/api/v2/copilot/sessions/4/sources');
  assert.equal(options.method, 'POST');
  assert.equal(options.body.get('revision'), '7');
  assert.equal(options.body.get('kind'), 'MEETING');
  const file = options.body.get('file');
  assert.equal(file.name, '粘贴的文字稿.txt');
  assert.equal(await file.text(), transcript);
  return { revision: 8, result: { sourceId: 15, fileName: file.name } };
 };
 await c.submitPastedTranscript();
 assert.equal(c.transcriptPaste, '');
 assert.equal(c.meetingSourceId, 15);
 assert.equal(c.revision, 8);
 assert.equal(analyses, 1);
 assert.ok(!c.hasPendingSave());
});
