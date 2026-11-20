// Synthetic hook harness: no server, DOM, database, model, or network calls.
import { build } from 'esbuild';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
const entry = fileURLToPath(new URL('../Minutes.tsx', import.meta.url));
const mock = `const H=new Proxy({}, {get:(_,k)=>globalThis.__minutesHarness[k],set:(_,k,v)=>(globalThis.__minutesHarness[k]=v,true)});
export const createElement=(type,props,...children)=>({type,props:{...props,children}});
export const useState=v=>{const i=H.index++;if(!(i in H.hooks))H.hooks[i]=typeof v==='function'?v():v;return [H.hooks[i],v=>{H.hooks[i]=typeof v==='function'?v(H.hooks[i]):v;H.pending=true}]};
export const useRef=v=>{const i=H.index++;return H.hooks[i]||(H.hooks[i]={current:v})};
export const useEffect=(fn,deps)=>{const i=H.index++,old=H.hooks[i];if(!old||deps.some((v,j)=>!Object.is(v,old.deps[j]))){H.effects.push(()=>{old?.cleanup?.();H.hooks[i]={deps,cleanup:fn()}})}};
export const useLocation=()=>H.location;
export const useNavigate=()=> (url)=>{const u=new URL(url,'https://fixture.invalid/app/minutes');H.location={pathname:'/minutes',search:u.search,hash:u.hash,key:String(++H.route)};H.pending=true};
export const useBoot=()=>H.boot;export const csrfToken=()=> 'synthetic-csrf';
export const getJSON=(url)=>H.request('GET',url);
export const postJSON=(url,body)=>H.request('POST',url,body);
export const putJSON=(url,body)=>H.request('PUT',url,body);
export const deleteJSON=(url)=>H.request('DELETE',url);
export const errorText=e=>e.message;
export const Fragment='fragment';export const Button='button';export default 'header';
export const saveResponse=async(r,name)=>H.downloads.push({name,text:await r.text()});`;
const bundle = await build({ entryPoints: [entry], bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'transform', tsconfigRaw: { compilerOptions: { jsx: 'react' } }, plugins: [{ name: 'synthetic', setup(b) { b.onResolve({ filter: /^(react$|react-router-dom$|@\/|\.\/profile\/common$)/ }, () => ({ path: 'mock', namespace: 'mock' })); b.onLoad({ filter: /.*/, namespace: 'mock' }, () => ({ contents: mock, loader: 'js' })) } }] });
const { default: Minutes } = await import('data:text/javascript;base64,' + Buffer.from(bundle.outputFiles[0].text).toString('base64'));
let H; const storage = new Map();
globalThis.sessionStorage = { getItem: k => storage.get(k) || null, setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k) };
globalThis.window = { confirm: () => true, addEventListener() { }, removeEventListener() { }, location: {} };
Object.defineProperty(globalThis, 'navigator', { value: { clipboard: { writeText: async text => { H.copied = text } } }, configurable: true });
const students = [{ id: 1, name: '虚构甲', student_code: 'FAKE-1' }, { id: 2, name: '虚构乙', student_code: 'FAKE-2' }];
const records = [{ id: 11, student_id: 1, report_id: 101, transcript_text: '历史原文'.repeat(20), minutes_text: '# 历史纪要', student_name: '虚构甲' }];
function reset(search = '', hash = '', role = 'admin', detail = 'full') {
  storage.clear(); H = globalThis.__minutesHarness = { hooks: [], index: 0, effects: [], pending: true, route: 0, location: { pathname: '/minutes', search, hash, key: '0' }, boot: { user: { role }, policy: { detail_level: detail } }, calls: [], downloads: [] };
  H.request = async (method, url, body) => { H.calls.push({ method, url, body }); if (H.override) { const result = H.override(method, url, body); if (result !== undefined) return result } if (url === '/api/admin/check') return { authenticated: true, user_id: H.userId || 7 }; if (url === '/api/students') return { students }; if (url.endsWith('/reports')) return { ok: true, reports: [{ id: url.includes('/2/') ? 202 : 101 }] }; if (url.endsWith('/minutes')) return { ok: true, minutes: url.includes('/1/') ? records : [] }; if (url === '/api/minutes/11') return method === 'GET' ? { ok: true, ...records[0] } : { ok: true }; if (url === '/api/transcript') return { ok: true, summary: '# 生成内容', minutes_id: null }; throw Error('Unexpected synthetic request ' + url) };
  globalThis.fetch = async (url, init) => { H.calls.push({ method: init.method, url, body: JSON.parse(init.body) }); return new Response('synthetic-docx') };
}
function nodes(tree) { if (!tree || typeof tree !== 'object') return []; return [tree, ...(tree.props?.children || []).flat(Infinity).flatMap(nodes)] }
function label(node) { return (node?.props?.children || []).flat(Infinity).map(x => typeof x === 'object' ? label(x) : x ?? '').join('') }
function find(text) { const n = nodes(H.tree).find(n => n.type === 'button' && label(n) === text); assert.ok(n, 'button ' + text); return n }
async function settle() { for (let i = 0; i < 12; i++) { await new Promise(r => setImmediate(r)); if (H.pending) { H.pending = false; H.index = 0; const root = Minutes(); H.tree = typeof root.type === 'function' ? root.type(root.props) : root; const effects = H.effects.splice(0); effects.forEach(fn => fn()) } } }
async function click(text) { find(text).props.onClick(); await settle() }
async function input(id, value) { const n = nodes(H.tree).find(n => n.props?.id === id); assert.ok(n, id); n.props.onChange({ target: { value } }); await settle() }
reset('?student_id=1&report_id=101', '#m11'); await settle(); assert.equal(nodes(H.tree).find(n => n.props?.id === 'minutes-source').props.value, records[0].transcript_text);
await click('DOCX'); assert.deepEqual(H.calls.at(-1).body, { minutes_id: 11 }); assert.ok(!H.calls.some(c => c.method === 'PUT'));
await input('minutes-edit', '手动编辑'); await click('DOCX'); assert.deepEqual(H.calls.slice(-2).map(c => c.method), ['PUT', 'POST']); assert.equal(H.calls.at(-2).body.minutes_text, '手动编辑');
console.log('PASS history hash; structured export; manual PUT before binary DOCX');
reset(); await settle(); await input('minutes-source', '虚构逐字稿'.repeat(20)); await click('生成纪要'); assert.ok(label(H.tree).includes('未保存')); await click('复制'); assert.equal(H.copied, '# 生成内容'); await click('TXT'); assert.equal(H.downloads.at(-1).text, H.copied); await click('DOCX'); assert.equal(H.calls.at(-1).body.summary, H.copied); assert.ok(!('student_id' in H.calls.find(c => c.url === '/api/transcript').body));
console.log('PASS unlinked generation; persistence failure retains result; copy/TXT/unlinked DOCX');
for (const [role, detail] of [['viewer', 'full'], ['advisor', 'summary']]) { reset('?student_id=1', '#m11', role, detail); await settle(); assert.equal(H.calls.length, 0); assert.ok(label(H.tree).includes('当前账号不显示纪要内容')); }
console.log('PASS viewer and summary: no editor requests');
reset('?student_id=1'); let resolve; H.override = (method, url) => url === '/api/students/1/reports' ? new Promise(r => resolve = r) : undefined; await settle(); const pick = nodes(H.tree).filter(n => n.type === 'select')[0]; pick.props.onChange({ target: { value: '2' } }); await settle(); resolve({ ok: true, reports: [{ id: 101 }] }); await settle(); assert.ok(label(H.tree).includes('虚构乙')); assert.ok(!nodes(H.tree).some(n => n.type === 'option' && n.props.value === 101));
console.log('PASS late student request cannot restore stale report');
reset('?student_id=1&report_id=202'); await settle(); assert.ok(label(H.tree).includes('所选报告不属于当前学生')); assert.equal(nodes(H.tree).find(n => n.type === 'fieldset').props.disabled, true);
console.log('PASS mismatched URL report blocks generation');
reset('?student_id=1'); let identity; H.override = (m, u) => u === '/api/admin/check' ? new Promise(r => identity = r) : undefined; await settle(); assert.equal(storage.size, 0); assert.ok(!H.calls.some(c => c.url === '/api/students/1/minutes')); identity({ authenticated: true, user_id: 19 }); await settle(); assert.ok([...storage.keys()].every(k => k.startsWith('minutes-draft:v2:19:')));
console.log('PASS no draft storage until identity; account-scoped key');
reset('?student_id=1'); H.override = (m, u) => u === '/api/admin/check' ? Promise.reject(Error('identity unavailable')) : undefined; await settle(); await input('minutes-source', '本地临时输入'); assert.equal(storage.size, 0);
console.log('PASS identity failure disables persistence');
reset('?student_id=1'); let roster; H.override = (m, u) => u === '/api/students' ? new Promise(r => roster = r) : undefined; await settle(); let fields = nodes(H.tree).filter(n => n.type === 'input'); fields[2].props.onChange({ target: { value: '手填年级' } }); await settle(); roster({ students: [{ ...students[0], grade: '服务端年级', gender: '女' }] }); await settle(); fields = nodes(H.tree).filter(n => n.type === 'input'); assert.deepEqual(fields.slice(1).map(n => n.props.value), ['虚构甲', '手填年级', '女']);
console.log('PASS late student metadata fills blanks and preserves typed grade');
// Reuse one tab's session storage under a different authenticated account.
await input('minutes-source', '账号一私有草稿'); const oldStorage = new Map(storage); reset('?student_id=1'); for (const [k, v] of oldStorage) storage.set(k, v); H.userId = 8; await settle(); assert.equal(nodes(H.tree).find(n => n.props?.id === 'minutes-source').props.value, '');
console.log('PASS another account cannot restore previous account draft');
const safety = await build({ stdin: { contents: `import React from 'react';import {renderToStaticMarkup} from 'react-dom/server';import Markdown from ${JSON.stringify(fileURLToPath(new URL('./Markdown.tsx', import.meta.url)))};export default renderToStaticMarkup(React.createElement(Markdown,{text:'# <img src=x onerror=alert(1)>\\n- **安全**\\n> <script>bad()</script>'}));`, resolveDir: fileURLToPath(new URL('../../..', import.meta.url)), loader: 'tsx' }, bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'transform', tsconfigRaw: { compilerOptions: { jsx: 'react' } } });
const vm = await import('node:vm'); const context = { exports: {}, module: { exports: {} }, require: (await import('node:module')).createRequire(import.meta.url), process, TextEncoder, TextDecoder, ReadableStream }; context.exports = context.module.exports; vm.runInNewContext(safety.outputFiles[0].text, context); const html = context.module.exports.default; assert.ok(html.includes('&lt;img')); assert.ok(!html.includes('<script>')); assert.ok(html.includes('<ul')); assert.ok(html.includes('<strong>安全</strong>'));
console.log('PASS real React static rendering escapes HTML and preserves markdown structure');

reset('?student_id=1');
H.override = (method, url) => url === '/api/students' ? Promise.resolve({students:[{...students[0],grade:'虚构年级',gender:'女'}]}) : undefined;
await settle();
let confirmations=0;
window.confirm=()=>{confirmations++;return false};
const historyButton=nodes(H.tree).find(n=>n.type==='button'&&label(n).startsWith('#11'));
historyButton.props.onClick();
await settle();
assert.equal(confirmations,0);
assert.equal(nodes(H.tree).find(n=>n.props?.id==='minutes-source').props.value,records[0].transcript_text);
await input('minutes-source','确实修改过的原文');
const studentPicker=nodes(H.tree).filter(n=>n.type==='select')[0];
studentPicker.props.onChange({target:{value:'2'}});
await settle();
assert.equal(confirmations,1);
assert.equal(H.location.search,'?student_id=1&report_id=101');
window.confirm=()=>true;
console.log('PASS auto-filled metadata stays clean; edited transcript warns and cancellation preserves selection');
