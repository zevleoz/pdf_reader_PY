(function () {
  'use strict';

  var doc = typeof document !== 'undefined' ? document : null;
  var root = doc ? doc.getElementById('m1Lists') : null;
  var listHost = doc ? doc.getElementById('m1List') : null;
  var dlg = doc ? doc.getElementById('planDlg') : null;

  // 排序是纯函数，导出给页面测试用。
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { sortPreps: sortPreps, sortReports: sortReports,
      uniqueByStudent: uniqueByStudent };
  }
  if (!root || !listHost) return;

  var kind = root.dataset.kind || 'preps';

  var state = {
    preps: [],
    plans: [],
    eligible: [],
    me: null,
    who: 'mine',
    view: 'all',
    q: ''
  };

  try {
    var savedWho = window.localStorage.getItem('m1.' + kind + '.who');
    if (savedWho === 'all' || savedWho === 'mine') state.who = savedWho;
  } catch (err) {}

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function api(path, opts) {
    var init = Object.assign({ headers: {} }, opts || {});
    if (init.body && typeof init.body !== 'string') {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(init.body);
    }
    return fetch(path, init).then(function (r) {
      return r.json().then(function (data) {
        if (!r.ok || !data || data.ok === false) {
          var msg = (data && (data.reason || data.error)) || ('请求失败（' + r.status + '）');
          throw new Error(msg);
        }
        return data;
      });
    });
  }

  var DAYS = ['日', '一', '二', '三', '四', '五', '六'];

  function day(value) {
    return value ? String(value).slice(0, 10) : '';
  }

  function md(value) {
    var text = day(value);
    return text ? text.slice(5) : '';
  }

  function dateLabel(value) {
    var text = day(value);
    if (!text) return '日期待定';
    var parts = text.split('-');
    var d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    return parts[1] + '-' + parts[2] + ' 周' + DAYS[d.getDay()];
  }

  function matchesWho(row) {
    if (state.who === 'all') return true;
    if (state.me === null) return false;
    return row.created_by === state.me || row.mentor_user_id === state.me;
  }

  function matchesQuery(row) {
    if (!state.q) return true;
    var q = state.q.toLowerCase();
    return (row.student_name || '').toLowerCase().indexOf(q) !== -1 ||
      (row.student_code || '').toLowerCase().indexOf(q) !== -1;
  }

  // -------------------------------------------------------------------------
  // 会前准备
  // -------------------------------------------------------------------------
  function prepChip(prep) {
    if (prep.status === 'generating') return ['s1', '生成中'];
    if (prep.status === 'final') return ['s0', '已定稿'];
    if (prep.current_version_id) return ['s1', 'AI 初稿 · 待定稿'];
    return ['sn', '待生成'];
  }

  function prepView(prep, view) {
    if (view === 'none') return !prep.current_version_id;
    if (view === 'draft') return !!prep.current_version_id && prep.status !== 'final';
    if (view === 'final') return prep.status === 'final';
    return true;
  }

  function prepAction(prep) {
    var base = '/m1/preps/' + prep.id;
    if (!prep.current_version_id) return { label: '生成', href: base + '/prep', primary: false };
    if (prep.status !== 'final') {
      return { label: '去定稿', href: base + '/prep#step=review', primary: true };
    }
    return { label: '下载', href: base + '/print', primary: false, blank: true };
  }

  function prepRow(prep) {
    var action = prepAction(prep);
    return [
      nameCell(prep),
      timeCell(prep),
      materialCell(prep),
      chipCell('c-p', '状态', prepChip(prep)),
      el('span', 'c-r mu', md(prep.updated_at) || '—'),
      actionCell(action)
    ];
  }

  // -------------------------------------------------------------------------
  // 会后报告
  // -------------------------------------------------------------------------
  function reportChip(prep) {
    var report = prep.report || {};
    if (!report.started) return ['sn', '未开始'];
    if (report.status === 'published') return ['s0', '已发布'];
    if (report.status === 'generating') return ['s1', '生成中'];
    return ['s1', '草稿 · 待发布'];
  }

  function reportView(prep, view) {
    var report = prep.report || {};
    if (view === 'upload') return !report.started;
    if (view === 'publish') return !!report.started && report.status !== 'published';
    if (view === 'published') return report.status === 'published';
    return true;
  }

  function reportAction(prep) {
    var base = '/m1/preps/' + prep.id;
    var report = prep.report || {};
    if (!report.started) return { label: '上传逐字稿', href: base + '/report', primary: true };
    if (report.status !== 'published') {
      return { label: '核对发布', href: base + '/report#step=review', primary: true };
    }
    return { label: '下载', href: base + '/report/print?print=1', primary: false, blank: true };
  }

  function reportRow(prep) {
    var action = reportAction(prep);
    return [
      nameCell(prep),
      timeCell(prep),
      el('span', 'c-s mu', prep.transcript ? '已上传' : '未上传'),
      chipCell('c-p', '状态', reportChip(prep)),
      el('span', 'c-r mu', md(prep.published_at) || '—'),
      actionCell(action)
    ];
  }

  // -------------------------------------------------------------------------
  // 发展计划
  // -------------------------------------------------------------------------
  function planInternalChip(plan) {
    return plan.status === 'approved' ? ['s0', '已批准'] : ['s1', plan.status_label || ''];
  }

  function planParentChip(plan) {
    if (plan.parent_version_id && plan.parent_stale) return ['s2', '家长版 已过期'];
    if (!plan.parent_status || plan.parent_status === 'none') return ['sn', '—'];
    var tone = plan.parent_status === 'exported' ? 's0' : 's1';
    return [tone, plan.parent_label || plan.parent_status];
  }

  function planView(plan, view) {
    if (view === 'internal') return plan.status !== 'approved';
    if (view === 'parent') return plan.status === 'approved' && plan.parent_status === 'draft';
    if (view === 'exported') return plan.parent_status === 'exported';
    return true;
  }

  function planAction(plan) {
    var next = plan.next || {};
    var label = next.label || '打开';
    if (plan.status === 'inputs') label = '继续';
    return {
      label: label,
      href: '/m1/plans/' + plan.id + (next.hash || ''),
      primary: true
    };
  }

  function planRow(plan) {
    var goals = (plan.goals || []).map(function (item) {
      var name = item.name || (plan._names && plan._names[item.code]) || '';
      return name ? item.code + ' ' + name : item.code;
    }).join('、');
    var meta = [md(plan.period_start) + (plan.period_end ? ' 至 ' + md(plan.period_end) : ''),
      plan.mentor_name].filter(Boolean).join(' · ');
    var block = el('span', 'c-t', 'Block ' + plan.block_no);
    if (meta) block.appendChild(el('small', null, meta));
    return [
      nameCell(plan),
      block,
      el('span', 'c-s mu', goals || '—'),
      chipCell('c-p', '内部版', planInternalChip(plan)),
      chipCell('c-r', '家长版', planParentChip(plan)),
      actionCell(planAction(plan))
    ];
  }

  // -------------------------------------------------------------------------
  // 共用单元格
  // -------------------------------------------------------------------------
  function nameCell(row) {
    var cell = el('span', 'nm');
    cell.appendChild(el('b', null, row.student_name || '未命名学生'));
    cell.appendChild(el('small', null,
      [row.student_code, row.grade].filter(Boolean).join(' · ')));
    return cell;
  }

  function timeCell(prep) {
    var cell = el('span', 'c-t', dateLabel(prep.meeting_date));
    if (prep.mentor_name) cell.appendChild(el('small', null, prep.mentor_name));
    return cell;
  }

  function materialCell(prep) {
    var materials = prep.materials || [];
    var cell = el('span', 'c-s mu', materials.length ? materials.join('、') : '—');
    cell.title = cell.textContent;
    return cell;
  }

  function chipCell(cls, label, pair) {
    var cell = el('span', cls);
    cell.appendChild(el('em', null, label));
    cell.appendChild(el('span', 'st ' + pair[0], pair[1]));
    return cell;
  }

  function actionCell(action) {
    var cell = el('span', 'c-b');
    var link = el('a', 'btn s' + (action.primary ? ' p' : ''), action.label);
    link.href = action.href;
    if (action.blank) link.target = '_blank';
    link.addEventListener('click', function (event) { event.stopPropagation(); });
    cell.appendChild(link);
    return cell;
  }

  function makeRow(row, cells, href) {
    var node = el('div', 'lr m1l');
    node.setAttribute('role', 'link');
    node.tabIndex = 0;
    node.setAttribute('aria-label', row.student_name || '');
    node.dataset.href = href;
    cells.forEach(function (cell) { node.appendChild(cell); });
    function go() { window.location.href = href; }
    node.addEventListener('click', go);
    node.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar') {
        event.preventDefault();
        go();
      }
    });
    return node;
  }

  function headerRow() {
    var head = el('div', 'lh m1l');
    var labels = {
      preps: ['学生', '会议时间 · Mentor', '资料', '状态', '上次更新', ''],
      reports: ['学生', '会议时间 · Mentor', '逐字稿', '状态', '发布', ''],
      plans: ['学生', 'Block · 阶段', '发展目标', '内部版', '家长版', '']
    }[kind];
    labels.forEach(function (label) { head.appendChild(el('span', null, label)); });
    return head;
  }

  function emptyState() {
    var wrap = el('div', 'empty');
    wrap.innerHTML = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 16h4"/></svg>';
    wrap.appendChild(el('b', null, '没有符合条件的内容'));
    wrap.appendChild(el('span', null, state.q ? '换个关键词试试。' : '换个筛选试试。'));
    return wrap;
  }

  function uniqueByStudent(rows) {
    var seen = {};
    var sorted = rows.slice().sort(function (a, b) {
      var left = day(a.meeting_date) || '0000-00-00';
      var right = day(b.meeting_date) || '0000-00-00';
      if (left !== right) return left < right ? 1 : -1;
      return b.id - a.id;
    });
    return sorted.filter(function (row) {
      if (seen[row.student_id]) return false;
      seen[row.student_id] = true;
      return true;
    });
  }

  function sortPreps(rows) {
    var pending = rows.filter(function (p) { return p.status !== 'final'; });
    var final = rows.filter(function (p) { return p.status === 'final'; });
    pending.sort(function (a, b) {
      var left = day(a.meeting_date) || '9999-99-99';
      var right = day(b.meeting_date) || '9999-99-99';
      return left < right ? -1 : left > right ? 1 : 0;
    });
    final.sort(function (a, b) {
      var left = day(a.meeting_date) || '';
      var right = day(b.meeting_date) || '';
      return left < right ? 1 : left > right ? -1 : 0;
    });
    return pending.concat(final);
  }

  function sortReports(rows) {
    var pending = rows.filter(function (p) { return (p.report || {}).status !== 'published'; });
    var done = rows.filter(function (p) { return (p.report || {}).status === 'published'; });
    pending.sort(function (a, b) {
      var left = day(a.meeting_date) || '9999-99-99';
      var right = day(b.meeting_date) || '9999-99-99';
      return left < right ? -1 : left > right ? 1 : 0;
    });
    done.sort(function (a, b) {
      var left = day(a.published_at) || '';
      var right = day(b.published_at) || '';
      return left < right ? 1 : left > right ? -1 : 0;
    });
    return pending.concat(done);
  }

  function setCount(view, n) {
    var button = document.querySelector('.vw [data-view="' + view + '"]');
    var em = button && button.querySelector('em');
    if (em) em.textContent = String(n);
  }

  function prepareRows(rows) {
    if (kind === 'preps') return sortPreps(uniqueByStudent(rows));
    if (kind === 'reports') return sortReports(uniqueByStudent(rows));
    return rows;
  }

  function inView(row, view) {
    if (kind === 'preps') return prepView(row, view);
    if (kind === 'reports') return reportView(row, view);
    return planView(row, view);
  }

  function rowFor(row) {
    if (kind === 'preps') return prepRow(row);
    if (kind === 'reports') return reportRow(row);
    return planRow(row);
  }

  function render() {
    var all = prepareRows(kind === 'plans' ? state.plans : state.preps);
    var scoped = all.filter(function (row) {
      return matchesWho(row) && matchesQuery(row);
    });
    ['all', 'none', 'draft', 'final', 'upload', 'publish', 'published',
      'internal', 'parent', 'exported'].forEach(function (view) {
      setCount(view, scoped.filter(function (row) { return inView(row, view); }).length);
    });

    var counter = document.getElementById('m1Count');
    if (counter) {
      var span = counter.querySelector('span');
      if (span) span.textContent = String(scoped.length);
    }

    listHost.innerHTML = '';
    if (!scoped.length) {
      listHost.appendChild(emptyState());
      return;
    }
    var rows = scoped.filter(function (row) { return inView(row, state.view); });
    if (!rows.length) {
      listHost.appendChild(emptyState());
      return;
    }
    listHost.appendChild(headerRow());
    rows.forEach(function (row) {
      var href = kind === 'plans' ? '/m1/plans/' + row.id : '/m1/preps/' + row.id;
      listHost.appendChild(makeRow(row, rowFor(row), href));
    });
  }

  function setView(view) {
    state.view = view;
    Array.prototype.forEach.call(document.querySelectorAll('.vw [data-view]'), function (button) {
      button.classList.toggle('on', button.dataset.view === view);
    });
    render();
  }

  function setWho(who) {
    state.who = who;
    try { window.localStorage.setItem('m1.' + kind + '.who', who); } catch (err) {}
    Array.prototype.forEach.call(document.querySelectorAll('[data-who]'), function (button) {
      var on = button.dataset.who === who;
      button.classList.toggle('on', on);
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    if (kind === 'plans') {
      loadPlans();
      return;
    }
    render();
  }

  // -------------------------------------------------------------------------
  // 新建计划
  // -------------------------------------------------------------------------
  function planField(id) { return document.getElementById(id); }

  function setOptions(select, items) {
    select.innerHTML = '';
    var blank = el('option', null, '选择学生');
    blank.value = '';
    select.appendChild(blank);
    items.forEach(function (item) {
      var option = el('option', null,
        item.name + ' · ' + item.student_code + ' · 下一个 Block ' + item.next_block);
      option.value = String(item.student_id);
      select.appendChild(option);
    });
  }

  function chosenStudent() {
    var value = planField('planStudent').value;
    return state.eligible.filter(function (item) {
      return String(item.student_id) === value;
    })[0] || null;
  }

  function syncPlanGo() {
    var go = planField('planGo');
    if (!go) return;
    go.disabled = !(planField('planStudent').value &&
      planField('planBlock').value &&
      planField('planStart').value &&
      planField('planEnd').value);
  }

  function syncStudentFields() {
    var student = chosenStudent();
    var block = planField('planBlock');
    var grade = planField('planGradeWrap');
    var note = planField('planMentor');
    if (student) {
      block.value = String(student.next_block || 1);
      grade.hidden = student.wb_grade != null && student.wb_grade !== '';
    } else {
      block.value = '';
      grade.hidden = true;
    }
    if (student && student.mentor_user_id !== state.me && student.mentor_name) {
      note.hidden = false;
      note.textContent = '负责导师：' + student.mentor_name + '。只有负责导师可以修改。';
    } else {
      note.hidden = true;
      note.textContent = '';
    }
    syncPlanGo();
  }

  function openPlanDialog(prepId) {
    if (!dlg) return;
    var select = planField('planStudent');
    setOptions(select, state.eligible);
    ['planBlock', 'planStart', 'planEnd', 'planCredits'].forEach(function (id) {
      planField(id).value = '';
    });
    planField('planGradeWrap').hidden = true;
    planField('planMentor').hidden = true;

    var prep = state.preps.filter(function (row) {
      return String(row.id) === String(prepId || '');
    })[0];
    if (prep) {
      var matched = state.eligible.filter(function (item) {
        return item.student_id === prep.student_id;
      })[0];
      if (matched) select.value = String(matched.student_id);
    }
    syncStudentFields();
    dlg.hidden = false;
    select.focus();
  }

  function closePlanDialog() {
    if (dlg) dlg.hidden = true;
  }

  function submitPlan() {
    var student = chosenStudent();
    var go = planField('planGo');
    if (!student || !go) return;
    go.disabled = true;
    var body = {
      student_id: student.student_id,
      prep_id: student.prep_id,
      block_no: Number(planField('planBlock').value),
      period_start: planField('planStart').value,
      period_end: planField('planEnd').value,
      credits: planField('planCredits').value
    };
    if (planField('planGradeWrap').hidden === false) {
      body.wb_grade = Number(planField('planGrade').value.replace('G', ''));
    }
    api('/api/m1/plans', { method: 'POST', body: body }).then(function (data) {
      var id = data.plan && data.plan.id;
      window.location.href = id ? '/m1/plans/' + id + '#step=inputs' : '/m1/plans';
    }).catch(function (err) {
      go.disabled = false;
      if (window.v2Toast) window.v2Toast(err.message || '新建失败');
    });
  }

  function renderEligibleNote() {
    var host = document.getElementById('m1Eligible');
    if (!host) return;
    var ready = ['ai_draft', 'needs_check', 'reviewing', 'approved', 'published'];
    var blocked = state.preps.filter(function (row) {
      return ready.indexOf((row.report || {}).status || '') === -1;
    }).map(function (row) { return row.student_name; });
    if (blocked.length) {
      host.textContent = '可以发展计划的学生：会后报告已有 AI 草稿（' +
        blocked.join('、') + ' 的报告还没生成，所以不在这里）。';
    } else {
      host.textContent = '可以发展计划的学生：会后报告已有 AI 草稿的学生都在这里。';
    }
  }

  // -------------------------------------------------------------------------
  // 载入
  // -------------------------------------------------------------------------
  function loadPlans() {
    return api('/api/m1/plans?scope=' + state.who).then(function (data) {
      state.plans = data.plans || [];
      return Promise.all(state.plans.map(function (plan) {
        var needs = (plan.goals || []).some(function (item) { return !item.name; });
        if (!needs) return null;
        return api('/api/m1/plans/' + plan.id).then(function (detail) {
          var names = {};
          (detail.goals || []).forEach(function (item) { names[item.code] = item.name; });
          plan._names = names;
        }).catch(function () {});
      }));
    }).then(render);
  }

  Array.prototype.forEach.call(document.querySelectorAll('.vw [data-view]'), function (button) {
    button.addEventListener('click', function () { setView(button.dataset.view); });
  });
  Array.prototype.forEach.call(document.querySelectorAll('[data-who]'), function (button) {
    button.addEventListener('click', function () { setWho(button.dataset.who); });
  });

  var search = document.getElementById('m1Search');
  if (search) {
    search.addEventListener('input', function () {
      state.q = (search.value || '').trim();
      render();
    });
  }

  if (kind === 'plans') {
    var newBtn = document.getElementById('newPlan');
    if (newBtn) newBtn.addEventListener('click', function () { openPlanDialog(); });
    if (dlg) {
      dlg.addEventListener('click', function (event) {
        if (event.target === dlg) closePlanDialog();
      });
      document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && !dlg.hidden) closePlanDialog();
      });
      ['planDlgX', 'planCancel'].forEach(function (id) {
        var button = document.getElementById(id);
        if (button) button.addEventListener('click', closePlanDialog);
      });
      planField('planStudent').addEventListener('change', syncStudentFields);
      ['planBlock', 'planStart', 'planEnd'].forEach(function (id) {
        planField(id).addEventListener('input', syncPlanGo);
        planField(id).addEventListener('change', syncPlanGo);
      });
      planField('planGo').addEventListener('click', submitPlan);
    }
  }

  api('/api/m1/preps').then(function (data) {
    state.preps = data.preps || [];
    state.me = data.me == null ? null : Number(data.me);
    if (kind !== 'plans') {
      setWho(state.who);
      setView(state.view);
      return;
    }
    return api('/api/m1/plans/eligible').then(function (eligible) {
      state.eligible = eligible.students || [];
      renderEligibleNote();
      setWho(state.who);
      setView(state.view);
      var wanted = new URLSearchParams(window.location.search).get('new');
      if (wanted) openPlanDialog(wanted);
    });
  }).catch(function (err) {
    if (window.v2Toast) window.v2Toast(err.message || '加载失败');
  });
})();
