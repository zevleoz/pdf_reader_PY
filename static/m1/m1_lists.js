(function () {
  'use strict';

  var doc = typeof document !== 'undefined' ? document : null;
  var root = doc ? doc.getElementById('m1Lists') : null;
  var listHost = doc ? doc.getElementById('m1List') : null;
  var dlg = doc ? doc.getElementById('planDlg') : null;

  // 排序与新建表单是纯函数，导出给页面测试用。
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { sortPreps: sortPreps, sortReports: sortReports,
      uniqueByStudent: uniqueByStudent, reportRowsByStudent: reportRowsByStudent, eligiblePath: eligiblePath,
      creationPayload: creationPayload, planHintText: planHintText,
      gradeVisible: gradeVisible };
  }
  if (!root || !listHost) return;

  var kind = root.dataset.kind || 'preps';

  var state = {
    preps: [],
    plans: [],
    eligible: [],
    eligibleReport: [],
    eligibleDirect: [],
    loaded: { report: false, direct: false },
    mentors: [],
    mentorsLoaded: false,
    canAssignMentor: root.dataset.canAssignMentor === '1',
    meName: root.dataset.meName || '',
    mode: 'report',
    me: null,
    who: root.dataset.defaultWho === 'all' ? 'all' : 'mine',
    view: 'all',
    q: ''
  };

  try {
    var savedWho = window.localStorage.getItem('m1.' + kind + '.who2');
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

  function eligiblePath(mode) {
    return mode === 'direct'
      ? '/api/m1/plans/eligible?source_mode=mentor_inputs'
      : '/api/m1/plans/eligible';
  }

  function gradeVisible(mode, student) {
    if (mode === 'direct') return true;
    return !(student && student.wb_grade != null && student.wb_grade !== '');
  }

  function planHintText(mode, opts) {
    var hasStudent = opts && opts.hasStudent;
    var hasDates = opts && opts.hasDates;
    var hasMentor = opts && opts.hasMentor;
    var count = opts && opts.eligibleCount;
    if (mode === 'direct') {
      if (count === 0) return '没有可访问的学生。';
      if (!hasStudent) return '先选择学生';
      if (!hasMentor) return '选择负责导师';
      if (!hasDates) return '填好阶段开始和结束后就可以新建';
      return '直接创建不需要会后报告；新建后填写教学简报并确认。';
    }
    if (count === 0) return '还没有会后报告已生成 AI 草稿的学生。';
    if (!hasStudent) return '先选择学生';
    if (!hasDates) return '填好阶段开始和结束后就可以新建';
    return '会后报告生成 AI 草稿后就可以新建';
  }

  // 两种创建方式共用一套字段，但派生字段不同：报告路径必须带 prep_id，
  // 直接路径必须带 source_mode，且从不发送 prep/report 标识。
  function creationPayload(mode, values) {
    var body = {
      student_id: Number(values.studentId),
      block_no: Number(values.blockNo),
      period_start: values.periodStart,
      period_end: values.periodEnd,
      credits: values.credits
    };
    if (values.wbGrade != null && values.wbGrade !== '') {
      body.wb_grade = Number(String(values.wbGrade).replace(/^G/, ''));
    }
    if (mode === 'direct') {
      body.source_mode = 'mentor_inputs';
      if (values.mentorUserId != null && values.mentorUserId !== '') {
        body.mentor_user_id = Number(values.mentorUserId);
      }
    } else {
      body.prep_id = Number(values.prepId);
    }
    return body;
  }

  function matchesWho(row) {
    if (state.who === 'all') return true;
    if (state.me === null) return false;
    return row.assigned || row.created_by === state.me || row.mentor_user_id === state.me;
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
    if (prep.can_edit === false) return { label: '查看', href: base + '/prep', primary: false };
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
    if (report.can_edit === false) return { label: '查看', href: base + '/report', primary: false };
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
    var co = ((plan.team || {}).co_mentors || []).map(function (row) {
      return row.name;
    }).filter(Boolean);
    var meta = [md(plan.period_start) + (plan.period_end ? ' 至 ' + md(plan.period_end) : ''),
      plan.mentor_name,
      co.length ? '共同导师 ' + co.join('、') : ''].filter(Boolean).join(' · ');
    var block = el('span', 'c-t', 'Block ' + plan.block_no);
    var planMeta = plan.source_mode === 'mentor_inputs'
      ? ('直接创建' + (meta ? ' · ' + meta : '')) : meta;
    if (planMeta) block.appendChild(el('small', null, planMeta));
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
    node.addEventListener('click', function (event) {
      if (event.target.closest('a, button, input, select, textarea')) return;
      go();
    });
    node.addEventListener('keydown', function (event) {
      if (event.target !== node) return;
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

  function reportRowsByStudent(rows) {
    var started = rows.filter(function (row) {
      var report = row.report || {};
      return report.started || (report.status && report.status !== 'draft');
    });
    return uniqueByStudent(started).concat(uniqueByStudent(rows).filter(function (row) {
      return !started.some(function (other) { return other.student_id === row.student_id; });
    }));
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
    if (kind === 'reports') return sortReports(reportRowsByStudent(rows));
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
      var href = kind === 'plans' ? planAction(row).href
        : '/m1/preps/' + row.id + (kind === 'reports' ? '/report'
          : (row.current_version_id && row.status !== 'final' ? '/prep#step=review' : '/prep'));
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

  // persist=true 仅在用户点击「我参与的 / 全部」时传入；页面启动不写 localStorage
  function setWho(who, persist) {
    state.who = who;
    if (persist) {
      try { window.localStorage.setItem('m1.' + kind + '.who2', who); } catch (err) {}
    }
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

  function eligibleFor(mode) {
    return mode === 'direct' ? state.eligibleDirect : state.eligibleReport;
  }

  function setOptions(select, items) {
    select.innerHTML = '';
    var blank = el('option', null, '选择学生');
    blank.value = '';
    select.appendChild(blank);
    items.forEach(function (item) {
      var meta = [item.student_code, item.grade].filter(Boolean).join(' · ');
      var option = el('option', null,
        item.name + (meta ? ' · ' + meta : '') + ' · 下一个 Block ' + item.next_block);
      option.value = String(item.student_id);
      select.appendChild(option);
    });
  }

  function chosenStudent() {
    var value = planField('planStudent').value;
    return eligibleFor(state.mode).filter(function (item) {
      return String(item.student_id) === value;
    })[0] || null;
  }

  function currentMentorId() {
    var select = planField('planMentorUser');
    if (select && !select.hidden && select.value) return select.value;
    return state.me == null ? '' : String(state.me);
  }

  function showPlanError(message) {
    var box = planField('planError');
    if (!box) return;
    box.textContent = message || '';
    box.hidden = !message;
  }

  function clearPlanError() {
    showPlanError('');
  }

  function syncPlanGo() {
    var go = planField('planGo');
    if (!go) return;
    var select = planField('planMentorUser');
    var hasStudent = !!planField('planStudent').value;
    var hasBlock = Number(planField('planBlock').value) > 0;
    var hasDates = !!(planField('planStart').value && planField('planEnd').value);
    var hasMentor = true;
    if (state.mode === 'direct' && state.canAssignMentor && select && !select.hidden) {
      hasMentor = !!select.value;
    }
    go.disabled = !(hasStudent && hasBlock && hasDates && hasMentor);
    var hint = planField('planHint');
    if (hint) {
      hint.textContent = planHintText(state.mode, {
        hasStudent: hasStudent, hasDates: hasDates, hasMentor: hasMentor,
        eligibleCount: eligibleFor(state.mode).length
      });
    }
  }

  function syncStudentFields() {
    var student = chosenStudent();
    var block = planField('planBlock');
    var grade = planField('planGradeWrap');
    var note = planField('planMentor');
    if (student) {
      block.value = String(student.next_block || 1);
    } else {
      block.value = '';
    }
    grade.hidden = !gradeVisible(state.mode, student);
    if (state.mode === 'direct') {
      note.hidden = true;
      note.textContent = '';
    } else if (student && student.mentor_user_id !== state.me && student.mentor_name) {
      note.hidden = false;
      note.textContent = '负责导师：' + student.mentor_name + '。只有负责导师可以修改。';
    } else {
      note.hidden = true;
      note.textContent = '';
    }
    syncPlanGo();
  }

  function syncMentorFields() {
    var wrap = planField('planMentorWrap');
    var selfWrap = planField('planMentorSelfWrap');
    var direct = state.mode === 'direct';
    var assign = direct && state.canAssignMentor && state.mentors.length > 0;
    if (wrap) wrap.hidden = !assign;
    if (selfWrap) selfWrap.hidden = !(direct && !assign);
    var self = planField('planMentorSelf');
    if (self) self.value = (state.meName || '当前账号') + '（你）';
    syncPlanGo();
  }

  function loadEligible(mode) {
    if (state.loaded[mode]) return Promise.resolve(eligibleFor(mode));
    return api(eligiblePath(mode)).then(function (data) {
      var rows = data.students || [];
      if (mode === 'direct') state.eligibleDirect = rows;
      else state.eligibleReport = rows;
      state.loaded[mode] = true;
      return rows;
    });
  }

  function loadMentors() {
    if (state.mentorsLoaded) return Promise.resolve();
    return api('/api/m1/mentors').then(function (data) {
      state.mentors = data.mentors || [];
      state.mentorsLoaded = true;
      var select = planField('planMentorUser');
      if (!select) return;
      select.innerHTML = '';
      state.mentors.forEach(function (mentor) {
        var option = el('option', null, mentor.display_name || ('用户 ' + mentor.id));
        option.value = String(mentor.id);
        select.appendChild(option);
      });
      var self = state.me == null ? '' : String(state.me);
      var hasSelf = state.mentors.some(function (mentor) {
        return String(mentor.id) === self;
      });
      if (hasSelf) select.value = self;
      else if (state.mentors[0]) select.value = String(state.mentors[0].id);
    }).catch(function () {
      state.canAssignMentor = false;
    });
  }

  function setMode(mode) {
    state.mode = mode === 'direct' ? 'direct' : 'report';
    Array.prototype.forEach.call(document.querySelectorAll('#planMode [data-mode]'), function (button) {
      var on = button.dataset.mode === state.mode;
      button.classList.toggle('on', on);
      button.setAttribute('aria-checked', on ? 'true' : 'false');
    });
    var note = planField('planModeNote');
    if (note) {
      note.textContent = state.mode === 'direct'
        ? '直接创建不读取会后报告；Block、阶段周期和负责导师为必填。'
        : '会后报告生成 AI 草稿后就可以新建；也可以直接创建教案。';
    }
    clearPlanError();
    return loadEligible(state.mode).then(function () {
      setOptions(planField('planStudent'), eligibleFor(state.mode));
      if (state.mode === 'direct' && state.canAssignMentor) return loadMentors();
      return null;
    }).then(function () {
      syncMentorFields();
      syncStudentFields();
      renderEligibleNote();
    }).catch(function (err) {
      showPlanError(err.message || '加载学生失败');
    });
  }

  function openPlanDialog(prepId, opts) {
    if (!dlg) return Promise.resolve();
    opts = opts || {};
    return setMode(opts.mode === 'direct' ? 'direct' : 'report').then(function () {
      var select = planField('planStudent');
      setOptions(select, eligibleFor(state.mode));
      ['planBlock', 'planStart', 'planEnd', 'planCredits'].forEach(function (id) {
        planField(id).value = '';
      });
      planField('planGrade').value = '';
      clearPlanError();

      var studentId = opts.studentId;
      if (studentId == null && prepId) {
        var prep = state.preps.filter(function (row) {
          return String(row.id) === String(prepId);
        })[0];
        if (prep) studentId = prep.student_id;
      }
      if (studentId != null) {
        var matched = eligibleFor(state.mode).filter(function (item) {
          return String(item.student_id) === String(studentId);
        })[0];
        if (matched) select.value = String(matched.student_id);
      }
      syncStudentFields();
      dlg.hidden = false;
      select.focus();
    });
  }

  function closePlanDialog() {
    if (dlg) dlg.hidden = true;
  }

  function submitPlan() {
    var student = chosenStudent();
    var go = planField('planGo');
    if (!student || !go) return;
    go.disabled = true;
    clearPlanError();
    var values = {
      studentId: student.student_id,
      prepId: student.prep_id,
      blockNo: planField('planBlock').value,
      periodStart: planField('planStart').value,
      periodEnd: planField('planEnd').value,
      credits: planField('planCredits').value,
      wbGrade: planField('planGradeWrap').hidden ? '' : planField('planGrade').value,
      mentorUserId: state.mode === 'direct' ? currentMentorId() : ''
    };
    api('/api/m1/plans', { method: 'POST', body: creationPayload(state.mode, values) })
      .then(function (data) {
        var id = data.plan && data.plan.id;
        window.location.href = id ? '/m1/plans/' + id + '#step=inputs' : '/m1/plans';
      }).catch(function (err) {
        go.disabled = false;
        showPlanError(err.message || '新建失败');
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
    var reportNote = blocked.length
      ? '会后报告已有 AI 草稿的学生可以新建（' + blocked.join('、') + ' 的报告还没生成）。'
      : '会后报告已有 AI 草稿的学生都可以新建。';
    host.textContent = reportNote + ' 没有报告也可以直接创建教案。';
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
    button.addEventListener('click', function () { setWho(button.dataset.who, true); });
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
      Array.prototype.forEach.call(document.querySelectorAll('#planMode [data-mode]'), function (button) {
        button.addEventListener('click', function () { setMode(button.dataset.mode); });
        button.addEventListener('keydown', function (event) {
          if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
          event.preventDefault();
          var next = button.dataset.mode === 'report' ? 'direct' : 'report';
          setMode(next);
          var target = document.querySelector('#planMode [data-mode="' + next + '"]');
          if (target) target.focus();
        });
      });
      planField('planStudent').addEventListener('change', function () {
        clearPlanError();
        syncStudentFields();
      });
      ['planBlock', 'planStart', 'planEnd', 'planCredits', 'planGrade'].forEach(function (id) {
        var field = planField(id);
        if (!field) return;
        field.addEventListener('input', function () { clearPlanError(); syncPlanGo(); });
        field.addEventListener('change', function () { clearPlanError(); syncPlanGo(); });
      });
      var mentorSelect = planField('planMentorUser');
      if (mentorSelect) {
        mentorSelect.addEventListener('change', function () { clearPlanError(); syncPlanGo(); });
      }
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
      state.eligibleReport = eligible.students || [];
      state.loaded.report = true;
      renderEligibleNote();
      setWho(state.who);
      setView(state.view);
      var params = new URLSearchParams(window.location.search);
      var wantedPrep = params.get('new');
      var wantedStudent = params.get('new_student');
      var wantedMode = params.get('mode');
      if (wantedStudent) {
        openPlanDialog(null, { mode: 'direct', studentId: wantedStudent });
      } else if (wantedMode === 'direct') {
        openPlanDialog(null, { mode: 'direct' });
      } else if (wantedPrep) {
        openPlanDialog(wantedPrep);
      }
    });
  }).catch(function (err) {
    if (window.v2Toast) window.v2Toast(err.message || '加载失败');
  });
})();
