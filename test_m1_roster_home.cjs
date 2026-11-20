// Execute the complete shipped home script, including fetch, DOM and user events.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync('static/m1/m1_home.js', 'utf8');

class Element {
  constructor(tag = 'div') {
    this.tagName = tag;
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.handlers = {};
    this.className = '';
    this.value = '';
    this.hidden = true;
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
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(key, fn) { (this.handlers[key] ||= []).push(fn); }
  fire(type, event = {}) {
    for (const fn of this.handlers[type] || []) fn({target: this, ...event});
  }
  focus() {}
  all() { return this.children.flatMap(c => [c, ...c.all()]); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  querySelectorAll(selector) { return this.all().filter(c => c.tagName === selector); }
}

async function boot(saved, studentId, manager = false) {
  const ids = Object.fromEntries(['m1Home', 'm1List', 'm1Count', 'm1Search', 'addDlg',
    'addStudent', 'addSearch', 'pick', 'addDate', 'addGo', 'addDuration', 'addDlgX', 'addCancel']
    .map(id => [id, new Element()]));
  ids.m1Count.appendChild(new Element('span'));
  ids.m1Home.dataset.studentId = studentId || '';
  ids.m1Home.dataset.manager = manager ? '1' : '0';
  const views = ['all', 'todo', 'done'].map(view => {
    const b = new Element('button'); b.dataset.view = view; b.appendChild(new Element('em')); return b;
  });
  const who = ['mine', 'all'].map(value => {
    const b = new Element('button'); b.dataset.who = value; return b;
  });
  const storage = new Map(saved ? [['m1.list.who', saved]] : []);
  const location = {href: '', replace(href) { this.href = href; }};
  const requests = [];
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
  const document = {
    getElementById: id => ids[id],
    createElement: tag => new Element(tag),
    createDocumentFragment: () => new Element('fragment'),
    addEventListener() {},
    querySelectorAll(selector) {
      if (selector === '.vw [data-view]') return views;
      if (selector === '[data-who]') return who;
      throw new Error('Unexpected selector: ' + selector);
    },
    querySelector(selector) {
      const match = selector.match(/^\.vw \[data-view="(\w+)"\]$/);
      assert.ok(match, selector);
      return views.find(b => b.dataset.view === match[1]);
    }
  };
  vm.runInNewContext(source, {document, window: {location,
    localStorage: {getItem: key => storage.get(key), setItem: (k, v) => storage.set(k, v)}},
    fetch: async path => {
      requests.push(path);
      const rosterPath = manager ? '/api/m1/roster?include_unassigned=1' : '/api/m1/roster';
      assert.ok([rosterPath, '/api/m1/students'].includes(path), path);
      return {ok: true, json: async () => path === rosterPath ? roster : {students: []}};
    }});
  await new Promise(resolve => setImmediate(resolve));
  const rows = () => ids.m1List.all().filter(e => e.attributes.role === 'link');
  const count = view => views.find(b => b.dataset.view === view).querySelector('em').textContent;
  const clickWho = value => who.find(b => b.dataset.who === value).fire('click');
  const clickView = value => views.find(b => b.dataset.view === value).fire('click');
  return {ids, rows, count, clickWho, clickView, who, storage, location, requests};
}

(async () => {
  for (const saved of [undefined, 'mine']) {
    const home = await boot(saved);
    const {ids, rows, count, clickWho, clickView} = home;
    assert.equal(rows().length, 4);
    const shared = rows().find(r => r.dataset.href === payload.students[0].hub_url);
    assert.ok(shared, 'default home must render the API co-mentor row');
    assert.match(shared.textContent, /共同导师/);
    assert.equal((shared.textContent.match(/未共享/g) || []).length, 0);
    assert.ok(payload.students[0].prep, 'DP15 assignment reveals the existing prep');
    assert.match(shared.textContent, /待生成|未开始/, 'shared prep/report state is visible');
    assert.match(ids.m1List.textContent, /接下来的会议/);
    assert.match(ids.m1List.textContent, /接下来的会议/);
    assert.match(ids.m1List.textContent, /已开过的会议/);
    assert.deepEqual(['all', 'todo', 'done'].map(count), ['4', '3', '1']);
    assert.equal(ids.m1Count.querySelector('span').textContent, '4');
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
    ids.addStudent.fire('click');
    assert.equal(ids.addDlg.hidden, false);
    assert.match(ids.pick.textContent, /暂无可添加 First Meeting/);
    assert.match(ids.pick.textContent, /已共享/);
  }
  const manager = await boot('mine', undefined, true);
  assert.equal(manager.rows().length, 5, 'a mentor preference must not narrow a new manager roster');
  assert.ok(manager.rows().some(r => r.dataset.href === '/m1/students/99'));
  assert.equal(manager.who.find(b => b.dataset.who === 'all').attributes['aria-pressed'], 'true');

  const all = await boot('all');
  assert.equal(all.rows().length, 5, 'saved all preference must survive boot');
  assert.equal(all.who.find(b => b.dataset.who === 'all').attributes['aria-pressed'], 'true');
  const linked = await boot(undefined, payload.students[0].student_id);
  assert.equal(linked.location.href, payload.students[0].hub_url, 'student entry must open hub without a prep ID');
  console.log('Full home script: shared row, groups, roles, filters, storage, search, counts, navigation, picker passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
