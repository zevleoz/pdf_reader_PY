"""DP13-C-b：直接执行 plan.js 的保存/版本/确认状态机（Node 行为测试）。

不检查源码里是否存在某段字符串，而是从真实 ``plan.js`` 中截取函数并在受控
环境里运行，断言 pending 保留、幂等身份复用、嵌套 patch 合成、版本推进顺序、
家庭建议确认与权限撤销等可观察行为。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent

_JS = r"""
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(process.cwd(), 'static/m1/plan.js'), 'utf8');
const CORE = require(path.join(process.cwd(), 'static/m1/plan_collab_core.js'));

function slice(name) {
  const start = src.indexOf('function ' + name + '(');
  if (start < 0) throw new Error('missing function ' + name);
  let i = src.indexOf('{', start), depth = 0, quote = null, comment = null;
  for (; i < src.length; i += 1) {
    const ch = src[i], next = src[i + 1];
    if (comment === 'line') { if (ch === '\n') comment = null; continue; }
    if (comment === 'block') { if (ch === '*' && next === '/') { comment = null; i += 1; } continue; }
    if (quote) {
      if (ch === '\\') { i += 1; continue; }
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '/' && next === '/') { comment = 'line'; i += 1; continue; }
    if (ch === '/' && next === '*') { comment = 'block'; i += 1; continue; }
    if (ch === "'" || ch === '"' || ch === '`') { quote = ch; continue; }
    if (ch === '{') depth += 1;
    else if (ch === '}') { depth -= 1; if (depth === 0) return src.slice(start, i + 1); }
  }
  throw new Error('unterminated function ' + name);
}

const state = [
  'clonePatch', 'isPlainObject', 'composePatch', 'ensurePending', 'rememberPath',
  'scheduleFlush', 'buildSectionPatch', 'stagePatch', 'stageField', 'updateSaveState',
  'sendPatch', 'acceptPatch', 'dropWrite', 'patchSection', 'isStaleError', 'flushSection',
  'hasUnresolved', 'flushAll', 'handlePatchError', 'applyPermissions', 'applyPresence',
  'handleEpochChange', 'applyFamilyFromPayload', 'familyRemoteDiffers',
  'adoptFamilyRemote', 'adoptFamilyRemoteIfClean', 'loadFamilyPayload',
  'markFamilySeen',
  'applyRevoked', 'restoreEditing', 'applyInternalSectionValue'
];
const body = state.map(slice).join('\n');

function assert(ok, message) {
  if (!ok) { console.error('FAIL: ' + message); process.exit(1); }
}

function makeEngine(overrides) {
  const save = [];
  let seq = 0;
  const fields = [0, 1].map(function (index) {
    return {
      index: index, tagName: 'DIV', contenteditable: 'true', disabled: false,
      textContent: '', attrs: {},
      getAttribute: function (name) { return name === 'contenteditable' ? this.contenteditable : null; },
      setAttribute: function (name, value) {
        if (name === 'contenteditable') this.contenteditable = value; else this.attrs[name] = value;
      },
      removeAttribute: function (name) { if (name === 'contenteditable') this.contenteditable = null; },
    };
  });
  const note = {hidden: true, style: {}, textContent: '', onclick: null};
  const base = {
    S: {
      doc: null, parentDoc: null, canEdit: true, revoked: false, offline: false,
      sections: {}, knownVersions: {}, observedDocVersion: 1, docVersion: 1,
      pending: {}, conflicts: {}, leases: {}, leasePromises: {}, locked: {}, writes: [],
      inflight: 0, familyHashes: [], familySeen: [], parentEditable: true,
      familyRemote: null, familyRemoteVersion: 0, familyRefreshSeq: 0
    },
    CORE: CORE,
    API: '/api',
    TAB_ID: 'test-tab',
    save: save,
    setSave: function (stateName, label) { save.push([stateName, label]); },
    notifyPresence: function () {},
    renderConflicts: function () {},
    renderPresence: function () {},
    applyLocks: function () {},
    setPlanRev: function () {},
    setParentSave: function () {},
    updateFamilyBadges: function () {},
    stopPresence: function () {},
    startPresence: function () {},
    pollPresence: function () {},
    scheduleRenew: function () {},
    refreshFamilyState: function () { return Promise.resolve(); },
    refreshFamilyAdvice: function () { return Promise.resolve(); },
    refreshRemoteSections: function () {},
    showRemoteNotice: function () {},
    refreshFamilyDom: function (index) {
      const node = fakeDocument.querySelector('[data-family="' + index + '"]');
      if (node) node.textContent = CORE.textOf(base.S.parentDoc.family[index]);
    },
    toast: function () {},
    ensureRemoteNote: function () { return note; },
    document: null,
    window: {confirm: function () { return false; }},
    location: {reload: function () { throw new Error('unexpected reload'); }},
    set: CORE.set,
    fieldValue: function (field) { return field.value !== undefined ? field.value : field.textContent; },
    idemKey: function (section) { seq += 1; return 'k-' + section + '-' + seq; },
    ensureLease: function () { return Promise.resolve('lease-token'); },
    queue: function (fn) { return fn(); },
    request: function () { return Promise.resolve({ok: true, section_version: 1, document_version: 1}); },
    note: note,
    fields: fields,
  };
  const deps = Object.assign(base, overrides || {});
  const fakeDocument = {
    visibilityState: 'visible',
    activeElement: null,
    querySelector: function (selector) {
      const match = /^\[data-family="(\d+)"\]$/.exec(selector);
      return match ? (fields[Number(match[1])] || null) : null;
    },
    querySelectorAll: function () { return fields; },
    getElementById: function (id) { return id === 'collabOffline' ? note : null; },
  };
  deps.document = deps.document || fakeDocument;
  deps.fakeDocument = fakeDocument;
  const paramNames = Object.keys(deps);
  const factory = new Function(paramNames.join(','), body + '\nreturn {' + state.join(',') + '};');
  const engine = factory.apply(null, paramNames.map(function (name) { return deps[name]; }));
  engine.deps = deps;
  return engine;
}

function field(value, path, kind) {
  return {
    tagName: 'DIV', value: undefined, textContent: value,
    getAttribute: function (name) {
      if (name === 'data-path' && kind !== 'parent') return path;
      if (name === 'data-ppath' && kind === 'parent') return path;
      return null;
    }
  };
}

/* 1. 嵌套字段和整列表 patch 的形状。 */
(function testNestedAndLists() {
  const engine = makeEngine({});
  const S = engine.deps.S;
  S.doc = {sessions: [{
    title: {text: '标题', src: 'ai'},
    focus: {primary: 'R2.2', text: {text: '重点', src: 'ai'}},
    content: {mindsets: {text: '心态', src: 'ai'}, skills: {text: '技能', src: 'ai'},
              techniques: {text: '技巧', src: 'ai'}},
    review: [{text: '一'}, {text: '二'}],
  }]};
  S.parentDoc = {
    family: [{text: '建议一', src: 'ai'}, {text: '建议二', src: 'ai'}],
    practice_options: [
      {ref: 's1p1', title: {text: '练习一', src: 'ai'}, text: {text: '说明一', src: 'ai'}},
      {ref: 's1p2', title: {text: '练习二', src: 'ai'}, text: {text: '说明二', src: 'ai'}},
    ],
  };
  engine.stageField(field('新心态', 'sessions.0.content.mindsets'), false);
  engine.stageField(field('新技能', 'sessions.0.content.skills'), false);
  engine.stageField(field('新重点', 'sessions.0.focus.text'), false);
  engine.stageField(field('R2.3', 'sessions.0.focus.primary'), false);
  let entry = S.pending['internal.session.1'];
  let patch = engine.buildSectionPatch('internal.session.1', entry.paths, entry.patch);
  assert(patch.content.mindsets.text === '新心态', 'mindsets retained');
  assert(patch.content.skills.text === '新技能', 'skills merged, not replaced');
  assert(patch.focus.text.text === '新重点' && patch.focus.primary === 'R2.3',
    'focus siblings merged');

  engine.stageField(field('新建议', 'family.0', 'parent'), false);
  entry = S.pending['parent.family'];
  patch = engine.buildSectionPatch('parent.family', entry.paths, entry.patch);
  assert(Array.isArray(patch) && patch.length === 2, 'family stays an array, not {"0":...}');
  assert(patch[0].text === '新建议' && patch[1].text === '建议二', 'family keeps sibling');

  engine.stageField(field('新练习标题', 'practice_options.0.title', 'parent'), false);
  engine.stageField(field('新练习说明', 'practice_options.0.text', 'parent'), false);
  entry = S.pending['parent.practice_options'];
  patch = engine.buildSectionPatch('parent.practice_options', entry.paths, entry.patch);
  assert(Array.isArray(patch) && patch.length === 2, 'practice options stays an array');
  assert(patch[0].title.text === '新练习标题' && patch[0].text.text === '新练习说明',
    'both edits in one list patch');
  console.log('nested/list composition OK');
})();

/* 2. 失败保留草稿，重试复用完全相同的请求身份。 */
(async function testFailureRetention() {
  const calls = [];
  let mode = 'fail';
  const engine = makeEngine({
    request: function (method, url, body) {
      calls.push(JSON.parse(JSON.stringify(body)));
      if (mode === 'fail') {
        const err = new Error('网络中断'); err.status = 0; return Promise.reject(err);
      }
      return Promise.resolve({ok: true, section_version: 2, document_version: 1});
    }
  });
  const S = engine.deps.S;
  S.doc = {sessions: [{title: {text: '旧标题', src: 'ai'}}]};
  engine.stageField(field('新标题', 'sessions.0.title.text'), false);
  const ok1 = await engine.flushSection('internal.session.1');
  assert(ok1 === false, 'failed save reports false');
  assert(S.pending['internal.session.1'], 'failed draft kept');
  assert(S.pending['internal.session.1'].error, 'failure recorded');
  assert(!engine.deps.save.some(function (row) { return row[0] === 'ok'; }),
    'no false saved indicator');
  const firstKey = calls[0].idempotency_key;
  const firstExpected = calls[0].expected_version;
  mode = 'ok';
  const ok2 = await engine.flushSection('internal.session.1');
  assert(ok2 === true, 'retry succeeds');
  assert(!S.pending['internal.session.1'], 'pending cleared after success');
  assert(calls.length === 2, 'retried once');
  assert(calls[1].idempotency_key === firstKey, 'same idempotency identity reused');
  assert(calls[1].expected_version === firstExpected, 'same expected version reused');
  assert(engine.deps.save[engine.deps.save.length - 1][0] === 'ok', 'saved only after ack');
  console.log('failure retention/idempotent identity OK');
})();

/* 3. 慢响应期间继续输入：等第二轮确认后才显示已保存。 */
(async function testTypingDuringSlowResponse() {
  const calls = [];
  let resolveFirst;
  const engine = makeEngine({
    request: function (method, url, body) {
      calls.push(JSON.parse(JSON.stringify(body)));
      if (calls.length === 1) {
        return new Promise(function (resolve) {
          resolveFirst = function () {
            resolve({ok: true, section_version: 2, document_version: 1});
          };
        });
      }
      return Promise.resolve({ok: true, section_version: 3, document_version: 1});
    }
  });
  const S = engine.deps.S;
  S.doc = {sessions: [{title: {text: '标题', src: 'ai'}, evidence: {text: '表现', src: 'ai'}}]};
  engine.stageField(field('标题2', 'sessions.0.title.text'), false);
  const pending = engine.flushSection('internal.session.1');
  engine.stageField(field('表现2', 'sessions.0.evidence.text'), false);
  await new Promise(function (resolve) { setTimeout(resolve, 0); });
  assert(!engine.deps.save.some(function (row) { return row[0] === 'ok'; }),
    'must not claim saved while request is in flight');
  resolveFirst();
  const ok = await pending;
  assert(ok === true, 'second round succeeds');
  assert(calls.length === 2, 'typing during flight triggers a second write');
  assert(calls[1].patch.title.text === '标题2' && calls[1].patch.evidence.text === '表现2',
    'second write carries both edits');
  assert(engine.deps.save[engine.deps.save.length - 1][0] === 'ok', 'saved after second ack');
  console.log('slow-response typing OK');
})();

/* 4. 批准前 flushAll 等待在途写入；失败时拒绝通过。 */
(async function testFlushAllWaitsAndBlocksApproval() {
  let mode = 'ok';
  let release;
  const engine = makeEngine({
    request: function () {
      if (mode === 'fail') return Promise.reject(Object.assign(new Error('500'), {status: 500}));
      if (mode === 'slow') {
        return new Promise(function (resolve) {
          release = function () {
            resolve({ok: true, section_version: 1, document_version: 1});
          };
        });
      }
      return Promise.resolve({ok: true, section_version: 1, document_version: 1});
    }
  });
  const S = engine.deps.S;
  S.doc = {sessions: [{title: {text: 't', src: 'ai'}, evidence: {text: 'e', src: 'ai'}}]};
  mode = 'slow';
  engine.stageField(field('t2', 'sessions.0.title.text'), false);
  const flush = engine.flushAll();
  let settled = false;
  flush.then(function () { settled = true; });
  await new Promise(function (resolve) { setTimeout(resolve, 0); });
  assert(settled === false, 'flushAll must wait for in-flight write');
  release();
  assert(await flush === true, 'flushAll completes after ack');

  mode = 'fail';
  engine.stageField(field('e2', 'sessions.0.evidence.text'), false);
  assert(await engine.flushAll() === false, 'approval blocked while a save is unresolved');
  console.log('flushAll wait/block OK');
})();

/* 5. presence 只记录观察版本，绝不提前推进 loaded baseline。 */
(function testPresenceDoesNotAdoptVersions() {
  let changed = null;
  const engine = makeEngine({
    refreshRemoteSections: function (sections) { changed = sections; }
  });
  const S = engine.deps.S;
  S.docVersion = 2;
  S.sections = {'internal.session.1': 3};
  S.knownVersions = {'internal.session.1': 3};
  S.observedDocVersion = 2;
  engine.applyPresence({
    document_version: 2,
    permissions: {can_edit: true, can_approve: true},
    sections: {'internal.session.1': 7},
    leases: []
  });
  assert(changed && changed.indexOf('internal.session.1') >= 0, 'remote change detected');
  assert(S.sections['internal.session.1'] === 3, 'baseline not advanced before content fetch');
  assert(S.knownVersions['internal.session.1'] === 7, 'observed version recorded');
  console.log('presence version separation OK');
})();

/* 6. 取得租约不是重放旧正文的授权。 */
(async function testLeaseDoesNotAdoptDocumentEpoch() {
  const S = {
    docVersion: 2, observedDocVersion: 2, leases: {}, leasePromises: {}, locked: {}
  };
  const fn = new Function('S', 'request', 'API', 'TAB_ID', 'applyLocks', 'scheduleRenew',
    slice('ensureLease') + '\nreturn ensureLease;');
  const ensureLease = fn(S, function () {
    return Promise.resolve({ok: true, token: 'tok', document_version: 9,
                            section_version: 9, expires_in: 45});
  }, '/api', 'test-tab', function () {}, function () {});
  await ensureLease('internal.session.1');
  assert(S.docVersion === 2, 'lease must not advance the loaded document epoch');
  assert(S.observedDocVersion === 9, 'lease response only updates observed epoch');
  console.log('lease epoch separation OK');
})();

/* 7. 家庭建议：stale ack 不采纳 unseen hash；刷新显示后才允许再次确认。 */
(async function testFamilyAckBindsDisplayedText() {
  const applied = [];
  let mode = 'stale';
  const engine = makeEngine({
    refreshFamilyAdvice: function () { applied.push('refresh'); return Promise.resolve(); },
    request: function (method, url, body) {
      applied.push(JSON.parse(JSON.stringify(body)));
      if (mode === 'stale') {
        const err = new Error('家庭建议已更新');
        err.status = 409;
        err.payload = {code: 'stale_family_ack', current_hashes: ['new-1', 'new-2']};
        return Promise.reject(err);
      }
      return Promise.resolve({ok: true, section_version: 2, document_version: 1});
    }
  });
  const S = engine.deps.S;
  S.familyHashes = ['old-1', 'old-2'];
  S.familySeen = [false, false];
  S.parentDoc = {family: [{text: '旧一', src: 'ai'}, {text: '旧二', src: 'ai'}]};
  engine.deps.fakeDocument.querySelector('[data-family="0"]').textContent = '旧一';
  engine.deps.fakeDocument.querySelector('[data-family="1"]').textContent = '旧二';

  const ok1 = await engine.markFamilySeen(0);
  assert(ok1 === false, 'stale ack not treated as success');
  assert(S.familyHashes[0] === 'old-1', 'must not adopt current_hashes without showing advice');
  assert(applied.some(function (item) { return item === 'refresh'; }),
    'stale ack triggers advice refresh');
  assert(applied.filter(function (item) { return item && item.patch && item.patch.hashes; }).length === 1,
    'no automatic second acknowledgement');

  engine.applyFamilyFromPayload({
    parent: {doc: {family: [{text: '新一', src: 'ai'}, {text: '新二', src: 'ai'}]}},
    parent_family: [{hash: 'new-1', seen: false}, {hash: 'new-2', seen: false}],
    collaboration: {sections: {'parent.family': 5, 'parent.family_seen': 6}}
  }, true);
  assert(S.familyHashes[0] === 'new-1' && S.familyHashes[1] === 'new-2',
    'new hashes bound after rendering');
  assert(S.sections['parent.family_seen'] === 6,
    'family_seen dependency version adopted together with displayed advice');
  assert(S.parentDoc.family[0].text === '新一', 'new advice rendered');
  assert(engine.deps.fakeDocument.querySelector('[data-family="0"]').textContent === '新一',
    'DOM shows the new advice');
  assert(S.familySeen[0] === false, 'fresh advice starts unacknowledged');

  mode = 'ok';
  const ok2 = await engine.markFamilySeen(0);
  const sent = applied.filter(function (item) { return item && item.patch && item.patch.hashes; }).pop();
  assert(ok2 === true, 'explicit re-review acknowledges');
  assert(sent.patch.hashes[0] === 'new-1' && sent.patch.hashes[1] === 'new-2',
    'ack uses displayed hashes');
  console.log('family ack binding OK');
})();

/* 7b. 家庭正文变化会 bump family_seen 依赖版本：确认要用已知最新版本，
   版本漂移时只刷新建议、不生成不可见的 family_seen 冲突卡片。 */
(async function testFamilyAckVersionDrift() {
  const events = [];
  const engine = makeEngine({
    refreshFamilyAdvice: function () { events.push('refresh'); return Promise.resolve(); },
    request: function (method, url, body) {
      events.push({method: method, body: JSON.parse(JSON.stringify(body || {}))});
      if (method === 'PATCH') {
        const err = new Error('section 已更新');
        err.status = 409;
        err.payload = {code: 'stale_section', section: 'parent.family_seen',
                       current: 5};
        return Promise.reject(err);
      }
      return Promise.resolve({ok: true});
    }
  });
  const S = engine.deps.S;
  S.familyHashes = ['old-1', 'old-2'];
  S.familySeen = [false, false];
  S.parentDoc = {family: [{text: '旧一', src: 'ai'}, {text: '旧二', src: 'ai'}]};
  S.sections['parent.family_seen'] = 2;
  S.knownVersions['parent.family_seen'] = 5;

  const ok = await engine.markFamilySeen(0);
  const sent = events.filter(function (item) {
    return item && item.method === 'PATCH';
  }).pop();
  assert(sent.body.expected_version === 5,
    'ack uses newest observed dependency version');
  assert(ok === false, 'version drift does not acknowledge');
  assert(events.indexOf('refresh') >= 0,
    'version drift fetches and displays current advice');
  assert(!S.conflicts['parent.family_seen'],
    'no invisible conflict card for family_seen');
  assert(S.familyHashes[0] === 'old-1',
    'hashes stay bound to displayed text until refresh completes');
  console.log('family seen version drift OK');
})();

/* 10. 聚焦中的家庭建议：远端新正文与 hash 分开保存，移出焦点后原子采纳。 */
(async function testFocusedFamilyAdviceKeepsDisplayedHash() {
  const calls = [];
  const engine = makeEngine({
    request: function (method, url, body) {
      calls.push({method: method, body: JSON.parse(JSON.stringify(body || {}))});
      return Promise.resolve({ok: true, section_version: 2, document_version: 1});
    },
    toast: function (message) { calls.push({toast: message}); }
  });
  const S = engine.deps.S;
  S.parentDoc = {family: [{text: '旧建议一', src: 'ai'},
                          {text: '建议二', src: 'ai'}]};
  S.familyHashes = ['old-0', 'old-1'];
  S.familySeen = [false, true];
  S.sections = {'parent.family': 1, 'parent.family_seen': 1};
  S.familyRemoteVersion = 1;
  engine.deps.fields[0].textContent = '旧建议一';
  engine.deps.fields[1].textContent = '建议二';
  engine.deps.fakeDocument.activeElement = engine.deps.fields[0];

  engine.applyFamilyFromPayload({
    parent_family: [{hash: 'new-0', seen: false}, {hash: 'old-1', seen: true}],
    parent: {doc: {family: [{text: '新建议一', src: 'ai'},
                            {text: '建议二', src: 'ai'}]}},
    collaboration: {sections: {'parent.family': 2, 'parent.family_seen': 3}}
  }, true);

  assert(engine.deps.fields[0].textContent === '旧建议一',
    'focused field text is not overwritten');
  assert(S.familyHashes[0] === 'old-0', 'displayed hash stays old while focused');
  assert(S.familyRemote.hashes[0] === 'new-0', 'remote snapshot kept separately');
  assert(S.familySeen[0] === false, 'changed advice still unacknowledged');
  assert(S.familyHashes[1] === 'old-1' && S.familySeen[1] === true,
    'unchanged second advice keeps hash and acknowledgement');
  assert(!S.sections['parent.family_seen'] || S.sections['parent.family_seen'] === 1,
    'baseline not advanced before adoption');

  const denied = await engine.markFamilySeen(0);
  assert(denied === false, 'acknowledgement rejected while field focused');
  assert(!calls.some(function (item) { return item.method === 'PATCH'; }),
    'no ack request with old hash');

  engine.deps.fakeDocument.activeElement = null;
  assert(engine.adoptFamilyRemote(0) === true, 'explicit adoption succeeds');
  assert(engine.deps.fields[0].textContent === '新建议一',
    'adopted text rendered');
  assert(S.familyHashes[0] === 'new-0', 'matching hash installed atomically');
  assert(S.familySeen[0] === false, 'adoption requires a fresh acknowledgement');
  assert(S.sections['parent.family'] === 2, 'baseline advances after adoption');
  assert(S.familySeen[1] === true, 'unaffected advice remains acknowledged');

  calls.length = 0;
  const ok = await engine.markFamilySeen(0);
  const ack = calls.filter(function (item) { return item.method === 'PATCH'; }).pop();
  assert(ok === true && ack, 'acknowledgement succeeds after adoption');
  assert(ack.body.patch.hashes[0] === 'new-0',
    'acknowledgement sends the displayed (new) hash');
  console.log('focused family advice OK');
})();

/* 11. 未保存草稿：远端快照不覆盖正文/hash，必须显式采纳且保留草稿。 */
(async function testDirtyFamilyDraftKeepsDisplayedHash() {
  const engine = makeEngine({});
  const S = engine.deps.S;
  S.parentDoc = {family: [{text: '本地草稿一', src: 'edited'},
                          {text: '建议二', src: 'ai'}]};
  S.familyHashes = ['old-0', 'old-1'];
  S.familySeen = [false, true];
  S.sections = {'parent.family': 1, 'parent.family_seen': 1};
  S.pending['parent.family'] = {
    paths: [], patch: {family: []}, timer: null, key: 'draft-key',
    attempt: null, error: null, sending: null, revision: 1
  };
  engine.deps.fields[0].textContent = '本地草稿一';
  engine.deps.fields[1].textContent = '建议二';

  engine.applyFamilyFromPayload({
    parent_family: [{hash: 'new-0', seen: false}, {hash: 'old-1', seen: true}],
    parent: {doc: {family: [{text: '远端新建议', src: 'ai'},
                            {text: '建议二', src: 'ai'}]}},
    collaboration: {sections: {'parent.family': 2, 'parent.family_seen': 3}}
  }, true);

  assert(engine.deps.fields[0].textContent === '本地草稿一',
    'draft text is not overwritten');
  assert(S.parentDoc.family[0].text === '本地草稿一', 'local draft preserved');
  assert(S.familyHashes[0] === 'old-0', 'old hash stays bound to draft text');
  assert(S.familyRemote.family[0].text === '远端新建议',
    'remote text kept for later adoption');
  assert(engine.adoptFamilyRemote(0) === false, 'adoption blocked while draft pending');

  delete S.pending['parent.family'];
  assert(engine.adoptFamilyRemote(0) === true, 'adoption allowed after draft cleared');
  assert(engine.deps.fields[0].textContent === '远端新建议'
    && S.familyHashes[0] === 'new-0', 'text and hash adopted together');
  assert(S.familySeen[0] === false && S.familySeen[1] === true,
    'only adopted advice needs fresh acknowledgement');
  console.log('dirty family draft OK');
})();

/* 12. 迟到/乱序的 GET：后发请求的结果优先，旧回复不能回退正文/hash。 */
(async function testDelayedFamilyRefreshIgnoresStaleReply() {
  const pending = [];
  const engine = makeEngine({
    request: function (method, url, body) {
      return new Promise(function (resolve) { pending.push(resolve); });
    }
  });
  const S = engine.deps.S;
  S.parentDoc = {family: [{text: '旧建议', src: 'ai'}, {text: '建议二', src: 'ai'}]};
  S.familyHashes = ['old-0', 'old-1'];
  S.familySeen = [false, true];
  S.sections = {'parent.family': 1, 'parent.family_seen': 1};
  engine.deps.fields[0].textContent = '旧建议';
  engine.deps.fields[1].textContent = '建议二';

  const first = engine.loadFamilyPayload(false);
  const second = engine.loadFamilyPayload(false);
  assert(pending.length === 2, 'two refresh requests issued');

  pending[1]({
    parent_family: [{hash: 'newest-0', seen: false}, {hash: 'old-1', seen: true}],
    parent: {doc: {family: [{text: '最新建议', src: 'ai'},
                            {text: '建议二', src: 'ai'}]}},
    collaboration: {sections: {'parent.family': 3, 'parent.family_seen': 4}}
  });
  await second;
  assert(engine.deps.fields[0].textContent === '最新建议'
    && S.familyHashes[0] === 'newest-0', 'newest reply adopted');

  pending[0]({
    parent_family: [{hash: 'stale-0', seen: false}, {hash: 'old-1', seen: true}],
    parent: {doc: {family: [{text: '更旧建议', src: 'ai'},
                            {text: '建议二', src: 'ai'}]}},
    collaboration: {sections: {'parent.family': 2, 'parent.family_seen': 2}}
  });
  await first;
  assert(engine.deps.fields[0].textContent === '最新建议',
    'late reply does not roll back displayed text');
  assert(S.familyHashes[0] === 'newest-0', 'late reply does not roll back hash');
  assert(S.sections['parent.family'] === 3, 'late reply does not roll back baseline');
  console.log('delayed family refresh OK');
})();

/* 13. 本地保存后的回读：正文一致时只安装 hash，不清掉已确认状态。 */
(function testFamilyReadbackKeepsAcknowledgement() {
  const engine = makeEngine({});
  const S = engine.deps.S;
  S.parentDoc = {family: [{text: '已保存建议', src: 'edited'},
                          {text: '建议二', src: 'ai'}]};
  S.familyHashes = ['old-0', 'old-1'];
  S.familySeen = [true, true];
  S.sections = {'parent.family': 2, 'parent.family_seen': 2};
  engine.deps.fields[0].textContent = '已保存建议';
  engine.deps.fields[1].textContent = '建议二';

  engine.applyFamilyFromPayload({
    parent_family: [{hash: 'saved-0', seen: true}, {hash: 'old-1', seen: true}],
    parent: {doc: {family: [{text: '已保存建议', src: 'edited'},
                            {text: '建议二', src: 'ai'}]}},
    collaboration: {sections: {'parent.family': 3, 'parent.family_seen': 4}}
  }, false);

  assert(S.familyHashes[0] === 'saved-0', 'readback installs matching hash');
  assert(S.familySeen[0] === true,
    'acknowledgement preserved because displayed advice did not change');
  assert(engine.deps.fields[0].textContent === '已保存建议',
    'readback does not rewrite identical text');
  console.log('family readback OK');
})();

/* 8. 权限撤销：停止轮询、禁用编辑，但保留本地草稿。 */
(function testRevokedRetainsDrafts() {
  let stopped = 0;
  const engine = makeEngine({stopPresence: function () { stopped += 1; }});
  const S = engine.deps.S;
  S.canEdit = true;
  S.pending['internal.session.1'] = {paths: [], patch: {title: {text: '草稿'}}};
  engine.applyPermissions({can_edit: false, can_approve: false});
  assert(S.revoked === true && S.canEdit === false, 'revoked state set');
  assert(stopped === 1, 'presence polling stopped');
  assert(engine.deps.note.hidden === false && engine.deps.note.textContent,
    'revoked notice shown');
  assert(engine.deps.fields.every(function (item) {
    return item.contenteditable === 'false';
  }), 'editing disabled');
  assert(S.pending['internal.session.1'], 'local draft retained for recovery');
  assert(engine.deps.save[engine.deps.save.length - 1][0] === 'err', 'save state is error');
  console.log('revocation OK');
})();

/* 9. 远端 session 刷新只更新它拥有的字段，不能覆盖 activities/practice。 */
(function testSessionRefreshOwnsOnlySessionFields() {
  const engine = makeEngine({});
  const S = engine.deps.S;
  S.doc = {sessions: [{
    title: {text: '旧标题', src: 'ai'},
    evidence: {text: '旧证据', src: 'ai'},
    content: {mindsets: {text: '旧心态', src: 'ai'}},
    activities: [{id: 'a1', name: {text: '本地活动草稿', src: 'edited'}}],
    practice: [{id: 'p1', task: {text: '本地练习草稿', src: 'edited'}}]
  }]};
  engine.applyInternalSectionValue('internal.session.1', {sessions: [{
    title: {text: '远端标题', src: 'ai'},
    evidence: {text: '远端证据', src: 'ai'},
    content: {mindsets: {text: '远端心态', src: 'ai'}},
    activities: [{id: 'a1', name: {text: '远端活动', src: 'ai'}}],
    practice: [{id: 'p1', task: {text: '远端练习', src: 'ai'}}]
  }]});
  const local = S.doc.sessions[0];
  assert(local.title.text === '远端标题', 'owned title refreshed');
  assert(local.content.mindsets.text === '远端心态', 'owned content refreshed');
  assert(local.activities[0].name.text === '本地活动草稿',
    'child activity draft not overwritten');
  assert(local.practice[0].task.text === '本地练习草稿',
    'child practice draft not overwritten');

  engine.applyInternalSectionValue('internal.session.1.activity.a1',
    {sessions: [{activities: [{id: 'a1', name: {text: '远端活动新版', src: 'ai'}}]}]});
  assert(S.doc.sessions[0].activities[0].name.text === '远端活动新版',
    'addressed child item refreshed by stable id');
  console.log('session field ownership OK');
})();

setTimeout(function () {
  process.stdout.write('DP13 client state behaviours passed\n');
}, 50);
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node 未安装")
def test_plan_js_save_state_behaviours():
    proc = subprocess.run(["node", "-e", _JS], cwd=str(ROOT),
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "DP13 client state behaviours passed" in proc.stdout
