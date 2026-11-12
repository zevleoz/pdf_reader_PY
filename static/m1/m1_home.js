(function () {
  'use strict';

  var root = document.getElementById('m1Home');
  var listHost = document.getElementById('m1List');
  if (!root || !listHost) return;

  var dlg = document.getElementById('addDlg');
  var addBtn = document.getElementById('addStudent');
  var addSearch = document.getElementById('addSearch');
  var pickHost = document.getElementById('pick');
  var addDate = document.getElementById('addDate');
  var addGo = document.getElementById('addGo');
  var durationSeg = document.getElementById('addDuration');

  var state = {
    preps: [],
    me: null,
    who: 'mine',
    view: 'all',
    q: '',
    students: [],
    sel: null,
    duration: 60,
    openedFrom: null
  };

  // 添加人筛选：我添加的（默认）/ 全部，选择记在 localStorage['m1.list.who']。
  try {
    var savedWho = window.localStorage.getItem('m1.list.who');
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

  function localToday() {
    var d = new Date();
    return [d.getFullYear(),
      String(d.getMonth() + 1).padStart(2, '0'),
      String(d.getDate()).padStart(2, '0')].join('-');
  }

  var DAYS = ['日', '一', '二', '三', '四', '五', '六'];

  function dateLabel(value) {
    if (!value) return '日期待定';
    var parts = value.split('-');
    var d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    return parts[1] + '-' + parts[2] + ' 周' + DAYS[d.getDay()];
  }

  function isPast(prep) {
    return !!prep.meeting_date && prep.meeting_date < localToday();
  }

  function matchesWho(prep) {
    if (state.who === 'all') return true;
    return state.me !== null && prep.created_by === state.me;
  }

  function matchesQuery(prep) {
    if (!state.q) return true;
    var q = state.q.toLowerCase();
    return (prep.student_name || '').toLowerCase().indexOf(q) !== -1 ||
      (prep.student_code || '').toLowerCase().indexOf(q) !== -1;
  }

  function inView(prep, view) {
    if (view === 'todo') return !!prep.next;
    if (view === 'done') return !prep.next;
    return true;
  }

  function prepChip(prep) {
    if (prep.status === 'generating') return ['s1', '生成中'];
    if (prep.status === 'final') return ['s0', '已定稿'];
    if (prep.current_version_id) return ['s1', 'AI 初稿 · 待定稿'];
    return ['sn', '待生成'];
  }

  function reportChip(prep) {
    var report = prep.report || {};
    if (!report.started) return ['sn', '未开始'];
    if (report.status === 'published') return ['s0', '已发布'];
    if (report.status === 'generating') return ['s1', '生成中'];
    if (report.status === 'draft') return ['s1', '待生成'];
    return ['s1', '草稿 · 待发布'];
  }

  function planChip(prep) {
    if (!prep.plan) return ['sn', '—'];
    return [prep.plan.tone || 's1', 'Block ' + prep.plan.block_no + ' · ' + prep.plan.label];
  }

  function makeRow(prep) {
    var row = el('div', 'lr m1l');
    row.setAttribute('role', 'link');
    row.tabIndex = 0;
    row.setAttribute('aria-label', prep.student_name + ' 的 First Meeting');
    row.dataset.href = '/m1/preps/' + prep.id;

    var nameCell = el('span', 'nm');
    nameCell.appendChild(el('b', null, prep.student_name || '未命名学生'));
    nameCell.appendChild(el('small', null,
      [prep.student_code, prep.grade].filter(Boolean).join(' · ')));
    row.appendChild(nameCell);

    var timeCell = el('span', 'c-t', dateLabel(prep.meeting_date));
    if (prep.mentor_name) timeCell.appendChild(el('small', null, prep.mentor_name));
    row.appendChild(timeCell);

    var prepPair = prepChip(prep);
    var prepCell = el('span', 'c-s mu');
    prepCell.appendChild(el('span', 'st ' + prepPair[0], prepPair[1]));
    row.appendChild(prepCell);

    var reportPair = reportChip(prep);
    var reportCell = el('span', 'c-p');
    reportCell.appendChild(el('em', null, '会后报告'));
    reportCell.appendChild(el('span', 'st ' + reportPair[0], reportPair[1]));
    row.appendChild(reportCell);

    var planPair = planChip(prep);
    var planCell = el('span', 'c-r');
    planCell.appendChild(el('em', null, '发展计划'));
    planCell.appendChild(el('span', 'st ' + planPair[0], planPair[1]));
    row.appendChild(planCell);

    var actionCell = el('span', 'c-b');
    if (prep.next) {
      var link = el('a', 'btn s' + (prep.next.primary ? ' p' : ''), prep.next.label);
      link.href = prep.next.href;
      link.addEventListener('click', function (event) { event.stopPropagation(); });
      actionCell.appendChild(link);
    }
    row.appendChild(actionCell);

    function go() { window.location.href = row.dataset.href; }
    row.addEventListener('click', go);
    row.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar') {
        event.preventDefault();
        go();
      }
    });
    return row;
  }

  function headerRow() {
    var head = el('div', 'lh m1l');
    head.appendChild(el('span', null, '学生'));
    head.appendChild(el('span', null, 'First Meeting · Mentor'));
    head.appendChild(el('span', null, '会前准备'));
    head.appendChild(el('span', null, '会后报告'));
    head.appendChild(el('span', null, '发展计划'));
    head.appendChild(el('span'));
    return head;
  }

  function groupBlock(title, small, rows) {
    var fragment = document.createDocumentFragment();
    var heading = el('h3', 'grp', title);
    heading.appendChild(el('small', null, small));
    fragment.appendChild(heading);
    fragment.appendChild(headerRow());
    rows.forEach(function (prep) { fragment.appendChild(makeRow(prep)); });
    return fragment;
  }

  function renderList(rows) {
    listHost.innerHTML = '';

    var upcoming = rows.filter(function (prep) { return !isPast(prep); });
    var past = rows.filter(isPast);
    upcoming.sort(function (a, b) {
      if (!a.meeting_date) return 1;
      if (!b.meeting_date) return -1;
      return a.meeting_date < b.meeting_date ? -1 : a.meeting_date > b.meeting_date ? 1 : 0;
    });
    past.sort(function (a, b) {
      return a.meeting_date < b.meeting_date ? 1 : a.meeting_date > b.meeting_date ? -1 : 0;
    });

    if (upcoming.length) {
      listHost.appendChild(groupBlock('接下来的会议',
        upcoming.length + ' · 按时间先后', upcoming));
    }
    if (past.length) {
      listHost.appendChild(groupBlock('已开过的会议',
        past.length + ' · 最近的在前', past));
    }
  }

  function emptyState(title, text) {
    var wrap = el('div', 'empty');
    wrap.innerHTML = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="15" rx="1.5"/><path d="M4 10h16M9 3v4M15 3v4"/></svg>';
    wrap.appendChild(el('b', null, title));
    wrap.appendChild(el('span', null, text));
    return wrap;
  }

  function setCount(view, n) {
    var button = document.querySelector('.vw [data-view="' + view + '"]');
    var em = button && button.querySelector('em');
    if (em) em.textContent = String(n);
  }

  function render() {
    var scoped = state.preps.filter(function (prep) {
      return matchesWho(prep) && matchesQuery(prep);
    });
    ['all', 'todo', 'done'].forEach(function (view) {
      setCount(view, scoped.filter(function (prep) { return inView(prep, view); }).length);
    });

    var rows = scoped.filter(function (prep) { return inView(prep, state.view); });
    var counter = document.getElementById('m1Count');
    if (counter) {
      var span = counter.querySelector('span');
      if (span) span.textContent = String(scoped.length);
    }

    if (!state.preps.length) {
      listHost.innerHTML = '';
      listHost.appendChild(emptyState('还没有学生', '点右上角「添加学生」开始。'));
      return;
    }
    if (!rows.length) {
      listHost.innerHTML = '';
      listHost.appendChild(emptyState('没有符合条件的学生', '换个筛选试试。'));
      return;
    }
    renderList(rows);
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
    try { window.localStorage.setItem('m1.list.who', who); } catch (err) {}
    Array.prototype.forEach.call(document.querySelectorAll('[data-who]'), function (button) {
      var on = button.dataset.who === who;
      button.classList.toggle('on', on);
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    render();
  }

  function selectable(student) {
    return !!student.y4_complete && !student.has_prep;
  }

  function closeDialog() {
    if (!dlg) return;
    dlg.hidden = true;
    if (state.openedFrom && typeof state.openedFrom.focus === 'function') {
      state.openedFrom.focus();
    }
  }

  function renderPick() {
    if (!pickHost) return;
    var q = (addSearch.value || '').trim().toLowerCase();
    pickHost.innerHTML = '';
    var found = state.students.filter(function (student) {
      if (!q) return true;
      return (student.name || '').toLowerCase().indexOf(q) !== -1 ||
        (student.student_code || '').toLowerCase().indexOf(q) !== -1;
    });
    // 可选学生排最前，其次已在 M1，最后是其余不可选的学生；组内保持原有顺序。
    var groups = [[], [], []];
    found.forEach(function (student) {
      groups[selectable(student) ? 0 : (student.has_prep ? 1 : 2)].push(student);
    });
    found = groups[0].concat(groups[1], groups[2]).slice(0, 40);

    if (!found.length) pickHost.appendChild(el('p', 'hint', '没有匹配的学生。'));

    found.forEach(function (student) {
      var ok = selectable(student);
      var button = el('button');
      button.type = 'button';
      button.disabled = !ok;
      if (state.sel === student.id) button.classList.add('on');
      button.appendChild(el('b', null, student.name || '未命名学生'));
      var meta = [student.student_code, student.grade, student.school]
        .filter(Boolean).join(' · ');
      button.appendChild(el('small', null, meta));
      var right = el('span', 'r');
      if (ok) {
        right.className = 'r st s0';
        right.textContent = 'Y4 已完成';
      } else {
        right.textContent = student.has_prep ? '已在心有灵析' : (student.reason || 'Y4 尚未完成');
      }
      button.appendChild(right);
      if (!ok) button.title = right.textContent;
      button.addEventListener('click', function () {
        if (!ok) return;
        state.sel = student.id;
        renderPick();
        syncAddGo();
      });
      pickHost.appendChild(button);
    });
  }

  function syncAddGo() {
    if (addGo) addGo.disabled = !state.sel;
  }

  function openDialog(studentId) {
    if (!dlg) return;
    state.openedFrom = document.activeElement;
    state.sel = null;
    state.duration = 60;
    if (addDate) addDate.value = '';
    if (addSearch) addSearch.value = '';
    if (durationSeg) {
      Array.prototype.forEach.call(durationSeg.querySelectorAll('button'), function (button) {
        var on = button.dataset.d === '60';
        button.classList.toggle('on', on);
        button.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
    }
    if (studentId) {
      var student = state.students.filter(function (s) { return s.id === Number(studentId); })[0];
      if (student && selectable(student)) {
        state.sel = student.id;
      } else if (student && window.v2Toast) {
        window.v2Toast(student.reason || '已在心有灵析');
      }
    }
    renderPick();
    syncAddGo();
    dlg.hidden = false;
    if (addSearch) addSearch.focus();
  }

  function submit() {
    if (!state.sel || !addGo) return;
    addGo.disabled = true;
    api('/api/m1/preps', {
      method: 'POST',
      body: {
        student_id: state.sel,
        meeting_date: addDate ? addDate.value : '',
        duration: state.duration
      }
    }).then(function (data) {
      if (data.created === false && window.v2Toast) window.v2Toast('这位学生已经在心有灵析里');
      var id = data.prep && data.prep.id;
      window.location.href = id ? '/m1/preps/' + id : '/m1';
    }).catch(function (err) {
      addGo.disabled = false;
      syncAddGo();
      if (window.v2Toast) window.v2Toast(err.message || '添加失败');
    });
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

  if (addBtn) addBtn.addEventListener('click', function () { openDialog(); });
  if (dlg) {
    dlg.addEventListener('click', function (event) {
      if (event.target === dlg) closeDialog();
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && !dlg.hidden) closeDialog();
    });
  }
  ['addDlgX', 'addCancel'].forEach(function (id) {
    var button = document.getElementById(id);
    if (button) button.addEventListener('click', closeDialog);
  });
  if (addSearch) addSearch.addEventListener('input', renderPick);
  if (durationSeg) {
    Array.prototype.forEach.call(durationSeg.querySelectorAll('button'), function (button) {
      button.addEventListener('click', function () {
        state.duration = Number(button.dataset.d) || 60;
        Array.prototype.forEach.call(durationSeg.querySelectorAll('button'), function (other) {
          var on = other === button;
          other.classList.toggle('on', on);
          other.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
      });
    });
  }
  if (addGo) addGo.addEventListener('click', submit);

  Promise.all([
    api('/api/m1/preps'),
    api('/api/m1/students').catch(function () { return { students: [] }; })
  ]).then(function (results) {
    state.preps = results[0].preps || [];
    state.me = results[0].me == null ? null : Number(results[0].me);
    state.students = results[1].students || [];
    setWho(state.who);
    setView(state.view);

    var wanted = Number(root.dataset.studentId || 0);
    if (!wanted) return;
    var listed = state.preps.filter(function (prep) { return prep.student_id === wanted; })[0];
    if (listed) {
      window.location.replace('/m1/preps/' + listed.id);
      return;
    }
    openDialog(wanted);
  });
})();
