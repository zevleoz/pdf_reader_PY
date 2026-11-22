// Execute the complete shipped home script, including fetch, DOM, focus and user events.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync('static/m1/m1_home.js', 'utf8');

let activeElement = null;

function matchSelector(node, selector) {
  const attr = selector.match(/^\[([\w-]+)(?:="([^"]*)")?\]$/);
  if (attr) {
    let value = node.attributes[attr[1]];
    if (value === undefined) value = node[attr[1]];
    return attr[2] === undefined ? value !== undefined : String(value) === attr[2];
  }
  const tagged = selector.match(/^([\w-]+)\[([\w-]+)(?:="([^"]*)")?\]$/);
  if (tagged) {
    if (node.tagName !== tagged[1]) return false;
    let value = node.attributes[tagged[2]];
    if (value === undefined) value = node[tagged[2]];
    return tagged[3] === undefined ? value !== undefined : String(value) === tagged[3];
  }
  if (selector.startsWith('.')) return node.className.split(/\s+/).includes(selector.slice(1));
  return node.tagName === selector;
}

class Element {
  constructor(tag = 'div') {
    this.tagName = tag;
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.handlers = {};
    this.style = {};
    this.className = '';
    this.value = '';
    this.hidden = false;
    this.disabled = false;
    this.tabIndex = 0;
    this._text = '';
    this.classList = {
      add: name => this.classList.toggle(name, true),
      toggle: (name, on) => {
        const names = new Set(this.className.split(' ').filter(Boolean));
        if (on) names.add(name); else names.delete(name);
        this.className = [...names].join(' ');
      }
    };
  }
  set textContent(text) { this._text = String(text); this.children = []; }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
  set innerHTML(text) { this._text = ''; this.children = []; }
  appendChild(child) {
    if (child.tagName === 'fragment') this.children.push(...child.children);
    else this.children.push(child);
    return child;
  }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  getAttribute(key) {
    return Object.prototype.hasOwnProperty.call(this.attributes, key) ? this.attributes[key] : null;
  }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(key, fn) { (this.handlers[key] ||= []).push(fn); }
  fire(type, event = {}) {
    for (const fn of this.handlers[type] || []) fn({target: this, ...event});
  }
  focus() { activeElement = this; }
  all() { return this.children.flatMap(c => [c, ...c.all()]); }
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }
  querySelectorAll(selector) {
    const groups = String(selector).split(',').map(part => part.trim()).filter(Boolean);
    return this.all().filter(node => groups.some(group => matchSelector(node, group)));
  }
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return {promise, resolve, reject};
}

function responseObject(spec) {
  return {
    ok: spec.ok !== false,
    status: spec.status || (spec.ok === false ? 503 : 200),
    json: async () => (spec.body !== undefined ? spec.body : {})
  };
}

const flush = async () => {
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
};

function rosterWithExtras() {
  const roster = structuredClone(payload);
  // Other authorized students exercise participation, meeting groups and counts.
  roster.students.push(
    {student_id: 88, student_name: 'Future', student_code: 'F88', participating: true,
      roles: ['primary'], hub_url: '/m1/students/88', workflow_state: 'done',
      plan: {id: 880, block_no: 3, label: '已导出', tone: 's0'},
      next: {label: '打开发展计划', href: '/m1/plans/880#step=parent', primary: true},
      prep: {id: 88, meeting_date: '2099-12-31', mentor_name: 'Bob', status: 'final', has_doc: true,
        report: {started: true, status: 'published'}}},
    {student_id: 89, student_name: 'Past', student_code: 'P89', participating: true,
      roles: ['creator'], hub_url: '/m1/students/89', plan: null, workflow_state: 'todo',
      next: {label: '核对发布', href: '/m1/preps/89/report', primary: true},
      prep: {id: 89, meeting_date: '2000-01-01', status: 'review', has_doc: true,
        report: {started: true, status: 'ai_draft'}}},
    {student_id: 99, student_name: 'Other authorized', student_code: 'A99',
      participating: false, roles: [], hub_url: '/m1/students/99', workflow_state: 'todo',
      prep: null, plan: null, next: null},
    {student_id: 77, student_name: 'Team only', student_code: 'T77',
      participating: true, roles: ['co_mentor'], hub_url: '/m1/students/77', workflow_state: 'todo',
      prep: null, plan: null, next: null});
  return roster;
}

async function boot(options = {}) {
  const manager = !!options.manager;
  const tags = {m1Search: 'input', addStudent: 'button', addSearch: 'input', addDate: 'input',
    addGo: 'button', addDlgX: 'button', addCancel: 'button'};
  const ids = Object.fromEntries(['m1Home', 'm1List', 'm1Count', 'm1Search', 'addDlg',
    'addStudent', 'addSearch', 'pick', 'addDate', 'addGo', 'addDuration', 'addDlgX', 'addCancel']
    .map(id => [id, new Element(tags[id] || 'div')]));
  ids.addDlg.hidden = true;
  ids.addGo.disabled = true;
  ids.m1Count.appendChild(new Element('span'));
  ids.m1Home.dataset.studentId = options.studentId || '';
  ids.m1Home.dataset.manager = manager ? '1' : '0';

  // Mirror the rendered dialog order so Tab cycling matches the browser.
  ids.addDlg.appendChild(ids.addDlgX);
  ids.addDlg.appendChild(ids.addSearch);
  ids.addDlg.appendChild(ids.pick);
  ids.addDlg.appendChild(ids.addDate);
  ['60', '75', '90'].forEach(value => {
    const button = new Element('button');
    button.dataset.d = value;
    ids.addDuration.appendChild(button);
  });
  ids.addDlg.appendChild(ids.addDuration);
  ids.addDlg.appendChild(ids.addCancel);
  ids.addDlg.appendChild(ids.addGo);

  const views = ['all', 'todo', 'done'].map(view => {
    const b = new Element('button'); b.dataset.view = view; b.appendChild(new Element('em')); return b;
  });
  const who = ['mine', 'all'].map(value => {
    const b = new Element('button'); b.dataset.who = value; return b;
  });
  const storage = new Map(options.savedWho ? [['m1.list.who', options.savedWho]] : []);
  const location = {href: '', replace(href) { this.href = href; }};

  const body = new Element('body');
  const documentElement = new Element('html');
  const docHandlers = {};
  const document = {
    body,
    documentElement,
    get activeElement() { return activeElement || body; },
    getElementById: id => ids[id],
    createElement: tag => new Element(tag),
    createDocumentFragment: () => new Element('fragment'),
    addEventListener(type, fn) { (docHandlers[type] ||= []).push(fn); },
    fire(type, event = {}) {
      for (const fn of docHandlers[type] || []) fn({target: document, ...event});
    },
    querySelectorAll(selector) {
      if (selector === '.vw [data-view]') return views.slice();
      if (selector === '[data-who]') return who.slice();
      return [];
    },
    querySelector(selector) {
      const match = selector.match(/^\.vw \[data-view="(\w+)"\]$/);
      assert.ok(match, selector);
      return views.find(b => b.dataset.view === match[1]) || null;
    }
  };

  const queues = {
    roster: (options.rosterQueue || [{ok: true, body: rosterWithExtras()}]).slice(),
    students: (options.studentsQueue || [{ok: true, body: {ok: true, students: []}}]).slice()
  };
  const pending = {roster: [], students: []};
  const requests = [];

  function takeSpec(kind) {
    const queue = queues[kind];
    if (queue.length > 1) return queue.shift();
    if (queue.length === 1) return queue[0];
    return kind === 'roster'
      ? {ok: true, body: rosterWithExtras()}
      : {ok: true, body: {ok: true, students: []}};
  }

  const window = {
    location,
    localStorage: {
      getItem: key => (storage.has(key) ? storage.get(key) : null),
      setItem: (key, value) => storage.set(key, value)
    }
  };

  const fetch = path => {
    requests.push(path);
    const kind = path.indexOf('/roster') !== -1 ? 'roster' : 'students';
    const spec = takeSpec(kind);
    if (spec.reject) return Promise.reject(new Error(spec.reject));
    if (spec.hold) {
      const waiter = deferred();
      pending[kind].push(waiter);
      return waiter.promise;
    }
    return Promise.resolve(responseObject(spec));
  };

  vm.runInNewContext(source, {document, window, fetch});
  await flush();

  return {
    ids,
    document,
    views,
    who,
    storage,
    location,
    requests,
    pending,
    rows: () => ids.m1List.all().filter(e => e.attributes.role === 'link'),
    count: view => views.find(b => b.dataset.view === view).querySelector('em').textContent,
    total: () => ids.m1Count.querySelector('span').textContent,
    clickWho: value => who.find(b => b.dataset.who === value).fire('click'),
    clickView: value => views.find(b => b.dataset.view === value).fire('click'),
    press: value => views.find(b => b.dataset.view === value).attributes['aria-pressed'],
    button: (host, label) => host.all().find(e => e.tagName === 'button' && e.textContent === label),
    focusables: () => ids.addDlg.querySelectorAll('button, input, select, textarea, a, [tabindex]')
      .filter(node => !node.disabled && !node.hidden && node.tabIndex >= 0),
    key: (key, shiftKey = false) => document.fire('keydown', {
      key, shiftKey, preventDefault() {}, stopPropagation() {}
    }),
    release(kind, spec, index = 0) {
      const waiter = pending[kind].splice(index, 1)[0];
      assert.ok(waiter, 'no pending ' + kind + ' request');
      waiter.resolve(responseObject(spec));
    },
    flush
  };
}

(async () => {
  // Shared roster rows, groups, roles, filters, search, counts and navigation.
  for (const saved of [undefined, 'mine']) {
    const home = await boot({savedWho: saved});
    const {ids, rows, count, clickWho, clickView} = home;
    assert.equal(rows().length, 4);
    const shared = rows().find(r => r.dataset.href === payload.students[0].hub_url);
    assert.ok(shared, 'default home must render the API co-mentor row');
    assert.match(shared.textContent, /共同导师/);
    assert.equal((shared.textContent.match(/未共享/g) || []).length, 0);
    assert.ok(payload.students[0].prep, 'DP15 assignment reveals the existing prep');
    assert.match(shared.textContent, /待生成|未开始/, 'shared prep/report state is visible');
    assert.match(ids.m1List.textContent, /接下来的会议/);
    assert.match(ids.m1List.textContent, /日期已过的会议/);
    assert.deepEqual(['all', 'todo', 'done'].map(count), ['4', '3', '1']);
    assert.equal(home.total(), '4');
    clickView('todo'); assert.equal(rows().length, 3);
    assert.ok(rows().some(r => r.dataset.href === '/m1/students/77'), 'team without a plan is pending');
    clickView('done'); assert.equal(rows().length, 1); assert.match(rows()[0].textContent, /Future/);
    assert.match(rows()[0].textContent, /打开发展计划/, 'completed plan retains navigation');
    clickView('all');
    clickWho('all'); assert.equal(rows().length, 5); assert.equal(count('all'), '5');
    assert.equal(home.storage.get('m1.list.who'), 'all');
    ids.m1Search.value = payload.students[0].student_code.toLowerCase();
    ids.m1Search.fire('input');
    assert.equal(rows().length, 1); assert.equal(count('all'), '1');
    assert.equal(count('todo'), '1'); assert.equal(count('done'), '0');
    ids.m1Search.value = 'no match'; ids.m1Search.fire('input');
    assert.equal(rows().length, 0); assert.match(ids.m1List.textContent, /没有符合条件/);
    ids.m1Search.value = payload.students[0].student_name; ids.m1Search.fire('input');
    rows()[0].fire('keydown', {key: 'Enter', preventDefault() {}});
    assert.equal(home.location.href, payload.students[0].hub_url);
    home.location.href = '';
    rows()[0].fire('keydown', {key: 'Enter', target: new Element('a'),
      preventDefault() { throw new Error('Nested link must retain its action'); }});
    assert.equal(home.location.href, '');
    rows()[0].fire('click'); assert.equal(home.location.href, payload.students[0].hub_url);
    ids.addStudent.focus();
    ids.addStudent.fire('click');
    assert.equal(ids.addDlg.hidden, false);
    assert.equal(home.document.activeElement, ids.addSearch, 'dialog focus starts inside');
    assert.match(ids.pick.textContent, /暂无可添加 First Meeting/);
    assert.match(ids.pick.textContent, /已共享/);
    home.key('Escape');
  }

  // First paint is a loading state, not an apparent zero.
  {
    const home = await boot({
      rosterQueue: [{hold: true}],
      studentsQueue: [{ok: true, body: {ok: true, students: []}}]
    });
    assert.equal(home.total(), '—', 'total must not read zero while loading');
    assert.deepEqual(['all', 'todo', 'done'].map(home.count), ['—', '—', '—']);
    assert.match(home.ids.m1List.textContent, /正在加载学生/);
    assert.equal(home.ids.m1List.attributes['aria-busy'], 'true');
    assert.ok(!home.ids.m1List.textContent.includes('还没有学生'));
    home.release('roster', {ok: true, body: rosterWithExtras()});
    await home.flush();
    assert.equal(home.rows().length, 4);
    assert.equal(home.total(), '4');
    assert.equal(home.ids.m1List.attributes['aria-busy'], 'false');
  }

  // A roster 503 shows a persistent retry that preserves search and filters.
  {
    const roster = rosterWithExtras();
    const home = await boot({
      rosterQueue: [
        {ok: false, status: 503, body: {ok: false, error: '服务暂时不可用'}},
        {ok: true, body: roster}
      ]
    });
    assert.match(home.ids.m1List.textContent, /学生列表加载失败/);
    assert.match(home.ids.m1List.textContent, /服务暂时不可用/);
    assert.equal(home.total(), '—', 'a failure must not claim an empty roster');
    assert.ok(home.button(home.ids.m1List, '重试'), 'failure exposes a retry control');
    home.ids.m1Search.value = 'Past';
    home.ids.m1Search.fire('input');
    home.clickView('todo');
    home.clickWho('all');
    const retry = home.button(home.ids.m1List, '重试');
    assert.ok(retry, 'retry stays available after filter changes');
    retry.fire('click');
    await home.flush();
    assert.equal(home.ids.m1Search.value, 'Past', 'search survives retry');
    assert.equal(home.press('todo'), 'true', 'status filter survives retry');
    assert.equal(home.rows().length, 1);
    assert.match(home.rows()[0].textContent, /Past/);
    assert.equal(home.total(), '1');
  }

  // A successful empty response is the only source of the empty roster message.
  {
    const home = await boot({
      rosterQueue: [{ok: true, body: {ok: true, me: 1, students: []}}]
    });
    assert.match(home.ids.m1List.textContent, /还没有学生/);
    assert.equal(home.total(), '0');
    assert.deepEqual(['all', 'todo', 'done'].map(home.count), ['0', '0', '0']);
    assert.equal(home.ids.m1List.attributes['aria-busy'], 'false');
  }

  // Picker failure is isolated inside the open dialog and can be retried.
  {
    const candidate = {id: 501, name: '候选学生', student_code: 'Y4-501', grade: 'Y4',
      y4_complete: true, has_prep: false};
    const home = await boot({
      studentsQueue: [
        {ok: false, status: 503, body: {ok: false, error: '学生名单暂时不可用'}},
        {ok: true, body: {ok: true, students: [candidate]}}
      ]
    });
    assert.equal(home.rows().length, 4, 'roster stays usable after picker failure');
    home.focusables();
    home.ids.addStudent.focus();
    home.ids.addStudent.fire('click');
    assert.equal(home.ids.addDlg.hidden, false);
    assert.match(home.ids.pick.textContent, /学生名单暂时不可用/);
    assert.equal(home.rows().length, 4, 'open dialog keeps the roster rendered');
    const retry = home.button(home.ids.pick, '重试');
    assert.ok(retry, 'picker failure exposes its own retry');
    retry.focus();
    retry.fire('click');
    await home.flush();
    assert.equal(home.ids.addDlg.hidden, false);
    assert.equal(home.document.activeElement, home.ids.addSearch,
      'picker retry keeps focus inside the dialog');
    assert.match(home.ids.pick.textContent, /候选学生/);
    assert.match(home.ids.pick.textContent, /Y4 已完成/);
    const choice = home.ids.pick.all().find(e => e.tagName === 'button' && /候选学生/.test(e.textContent));
    assert.ok(choice);
    choice.focus();
    choice.fire('click');
    assert.equal(home.ids.addGo.disabled, false);
    assert.ok(home.ids.pick.all().includes(home.document.activeElement),
      'selecting a candidate keeps focus on a mounted control');
    home.key('Escape');
  }

  // A late older response must not replace a newer one.
  {
    const newer = rosterWithExtras();
    const older = {ok: true, body: {ok: true, me: 1, students: [
      {student_id: 700, student_name: 'Older response', student_code: 'OLD',
        participating: true, roles: ['primary'], hub_url: '/m1/students/700',
        workflow_state: 'todo', prep: null, plan: null, next: null}
    ]}};
    const home = await boot({
      rosterQueue: [
        {ok: false, status: 503, body: {ok: false, error: '服务暂时不可用'}},
        {hold: true}
      ]
    });
    const retry = home.button(home.ids.m1List, '重试');
    retry.fire('click');
    retry.fire('click');
    assert.equal(home.pending.roster.length, 2, 'two roster responses are in flight');
    home.release('roster', {ok: true, body: newer}, 1);
    await home.flush();
    assert.equal(home.rows().length, 4);
    home.release('roster', older, 0);
    await home.flush();
    assert.equal(home.rows().length, 4, 'older response is ignored');
    assert.ok(!home.ids.m1List.textContent.includes('Older response'));
  }

  // Keyboard-modal dialog: initial focus, Tab in both directions, Escape and Cancel restore.
  {
    const home = await boot();
    const {ids} = home;
    ids.addStudent.focus();
    ids.addStudent.fire('click');
    assert.equal(ids.addDlg.hidden, false);
    assert.equal(home.document.activeElement, ids.addSearch);
    const items = home.focusables();
    assert.equal(items[0], ids.addDlgX);
    assert.equal(items[items.length - 1], ids.addCancel);
    items[items.length - 1].focus();
    home.key('Tab');
    assert.equal(home.document.activeElement, items[0], 'Tab wraps to the first control');
    items[0].focus();
    home.key('Tab', true);
    assert.equal(home.document.activeElement, items[items.length - 1],
      'Shift+Tab wraps to the last control');
    ids.m1Search.focus();
    home.key('Tab');
    assert.equal(home.document.activeElement, items[0], 'Tab from outside enters the dialog');
    home.key('Escape');
    assert.equal(ids.addDlg.hidden, true);
    assert.equal(home.document.activeElement, ids.addStudent, 'Escape restores the trigger');

    ids.addStudent.focus();
    ids.addStudent.fire('click');
    ids.addCancel.fire('click');
    assert.equal(ids.addDlg.hidden, true);
    assert.equal(home.document.activeElement, ids.addStudent, 'Cancel restores the trigger');
  }

  // A direct student link focuses inside, then Escape falls back to a visible control.
  {
    const home = await boot({studentId: 555});
    assert.equal(home.ids.addDlg.hidden, false, 'direct entry opens the picker');
    assert.equal(home.document.activeElement, home.ids.addSearch);
    home.key('Escape');
    assert.equal(home.ids.addDlg.hidden, true);
    assert.equal(home.document.activeElement, home.ids.addStudent,
      'direct entry restores focus to the visible add control');
  }

  // A profiling link must preselect its student even if the picker responds after the roster.
  {
    const candidate = {id: 555, name: '待安排会议学生', student_code: 'Y4-555',
      y4_complete: true, has_prep: false};
    const home = await boot({studentId: candidate.id, studentsQueue: [{hold: true}]});
    assert.equal(home.ids.addDlg.hidden, false);
    assert.equal(home.ids.addGo.disabled, true);
    home.release('students', {ok: true, body: {ok: true, students: [candidate]}});
    await home.flush();
    assert.equal(home.ids.addGo.disabled, false, 'the linked eligible student is preselected');
    assert.match(home.ids.pick.querySelector('button').className, /\bon\b/);
    assert.equal(home.ids.pick.querySelector('button').getAttribute('aria-pressed'), 'true');
    assert.equal(home.document.activeElement, home.ids.addSearch,
      'waiting for the candidate preserves initial dialog focus');
  }

  // Status filters expose pressed state and update after selection.
  {
    const home = await boot();
    assert.equal(home.press('all'), 'true');
    assert.equal(home.press('todo'), 'false');
    assert.equal(home.press('done'), 'false');
    home.views.find(b => b.dataset.view === 'todo').focus();
    home.clickView('todo');
    assert.equal(home.press('todo'), 'true');
    assert.equal(home.press('all'), 'false');
    assert.equal(home.press('done'), 'false');
  }

  const manager = await boot({savedWho: 'mine', manager: true});
  assert.equal(manager.rows().length, 5, 'a mentor preference must not narrow a new manager roster');
  assert.ok(manager.rows().some(r => r.dataset.href === '/m1/students/99'));
  assert.equal(manager.who.find(b => b.dataset.who === 'all').attributes['aria-pressed'], 'true');

  const all = await boot({savedWho: 'all'});
  assert.equal(all.rows().length, 5, 'saved all preference must survive boot');
  assert.equal(all.who.find(b => b.dataset.who === 'all').attributes['aria-pressed'], 'true');

  const linked = await boot({studentId: payload.students[0].student_id});
  assert.equal(linked.location.href, payload.students[0].hub_url,
    'student entry must open hub without a prep ID');

  console.log('Home script: loading, retry, empty, picker retry, late response, keyboard focus and filters passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
