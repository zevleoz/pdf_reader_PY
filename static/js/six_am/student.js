/* 6AM v0.6 · 学生：维度切换、思维导图、会谈记录、A6 面板、First Touch 抽屉。 */
(function () {
  'use strict';

  var SA = window.SA;
  var state = { data: null, report: null, dim: null, drawer: false };

  function profileOf() { return (state.data && state.data.profile) || {}; }
  function model() { return SA.model || {}; }

  function dimSpec(dimId) {
    var dims = model().dims || [];
    for (var i = 0; i < dims.length; i += 1) {
      if (dims[i].id === dimId) return dims[i];
    }
    return null;
  }

  function dimIds() {
    var order = (profileOf().order || []).filter(function (id) {
      return ['A1', 'A2', 'A3', 'A4', 'A5'].indexOf(id) >= 0;
    });
    return order.length ? order : ['A1', 'A2', 'A3', 'A4', 'A5'];
  }

  function firstDim(data) {
    var order = ((data && data.profile && data.profile.order) || []);
    for (var i = 0; i < order.length; i += 1) {
      if (['A1', 'A2', 'A3', 'A4', 'A5'].indexOf(order[i]) >= 0) return order[i];
    }
    return 'A1';
  }

  function validDim(dimId) {
    return ['A1', 'A2', 'A3', 'A4', 'A5', 'A6'].indexOf(dimId) >= 0;
  }

  /* ── 头部 ───────────────────────────────────────────────── */
  function headerHTML(actions) {
    var data = state.data || {};
    var student = (data.profile || {}).student || {};
    var versions = data.versions || [];
    var versionSelect = '';
    if (versions.length > 1) {
      versionSelect = '<select class="ver" data-version aria-label="版本">' +
        versions.map(function (row) {
          return '<option value="' + SA.esc(row.profile_id) + '"' +
            (row.version === data.version ? ' selected' : '') + '>v' + SA.esc(row.version) + '</option>';
        }).join('') + '</select>';
    } else {
      versionSelect = '<span>v' + SA.esc(data.version) + '</span>';
    }
    return '<div class="shead"><div class="who"><h1>' + SA.esc(student.name || '') + '</h1>' +
      '<div class="meta"><span>' + SA.esc(student.grade || '') + '</span><span>·</span>' +
      '<span>' + SA.esc(data.report_date || '—') + '</span><span>·</span>' +
      versionSelect + '</div></div>' +
      '<span class="spacer"></span>' +
      (actions ? '<div class="row actions">' +
        '<button class="btn" type="button" data-generate>重新生成</button>' +
        '<button class="btn" type="button" data-open-ft>录入 First Touch</button>' +
        '</div>' : '') + '</div>';
  }

  function flagsHTML() {
    var flags = profileOf().flags || {};
    var h = '';
    if (flags.safety) h += '<div class="banner safety"><b>情绪安全复核</b></div>';
    if (flags.answer_state) h += '<div class="banner answer"><b>答题状态提示</b></div>';
    return h;
  }

  function dimsHTML() {
    var profile = profileOf();
    var current = state.dim;
    var h = '<div class="dims" role="group" aria-label="维度">';
    dimIds().forEach(function (id) {
      var spec = dimSpec(id) || { name: '' };
      var level = ((profile.dims || {})[id] || {}).level;
      h += '<button class="dim" type="button" data-dim="' + id + '" aria-selected="' +
        (current === id) + '"><span class="nm">' + SA.esc(id + ' ' + (spec.name || '')) + '</span>' +
        SA.chip(level) + '</button>';
    });
    var a6 = model().a6 || {};
    h += '<button class="dim" type="button" data-dim="A6" aria-selected="' +
      (current === 'A6') + '"><span class="nm">A6 ' + SA.esc(a6.name || '') + '</span></button>';
    return h + '</div>';
  }

  /* ── A6 面板 ────────────────────────────────────────────── */
  function a6Item(entry) {
    var fit = entry.fit_label === '慎用' ? '<span class="tag warn">慎用</span>' : '';
    var why = (entry.why || []).map(function (text) {
      return '<span class="why">' + SA.esc(text) + '</span>';
    }).join('');
    return '<li class="a6item"><span class="nm">' + SA.esc(entry.name || '') + '</span>' +
      fit + why + '</li>';
  }

  function a6Panel() {
    var a6 = profileOf().a6 || {};
    var ranked = a6.ranked || [];
    var top = ranked.filter(function (row) { return row.top; });
    var others = ranked.filter(function (row) { return !row.top; });
    var avoid = a6.avoid || [];
    var h = '<section class="card pad a6"><h2>先用</h2>';
    h += top.length ? '<ul class="a6list">' + top.map(a6Item).join('') + '</ul>' : '<p class="sub">—</p>';
    h += '<details class="a6more"><summary>其他（' + others.length + '）</summary>';
    h += others.length ? '<ul class="a6list">' + others.map(a6Item).join('') + '</ul>' : '<p class="sub">—</p>';
    h += '</details><h2>不用</h2>';
    h += avoid.length ? '<ul class="a6list">' + avoid.map(function (row) {
      return '<li class="a6item"><span class="nm">' + SA.esc(row.name || '') + '</span>' +
        '<span class="no">' + SA.esc(row.why || '') + '</span></li>';
    }).join('') + '</ul>' : '<p class="sub">—</p>';
    return h + '</section>';
  }

  /* ── First Touch 抽屉 ──────────────────────────────────── */
  function optionList(options, current) {
    return options.map(function (pair) {
      return '<option value="' + SA.esc(pair[0]) + '"' +
        (String(pair[0]) === String(current == null ? '' : current) ? ' selected' : '') +
        '>' + SA.esc(pair[1]) + '</option>';
    }).join('');
  }

  function boolValue(value) {
    if (value === true) return 'true';
    if (value === false) return 'false';
    return '';
  }

  function drawerHTML() {
    var inputs = profileOf().inputs || {};
    var ft = inputs.ft || {};
    var goal = ft.goal || {};
    var task = ft.standard_task || {};
    var schedule = ft.schedule || {};
    var parent = inputs.parent || {};
    var complaint = parent.complaint && typeof parent.complaint === 'object' ? parent.complaint : {};

    return '<div class="drawer-mask' + (state.drawer ? ' open' : '') + '" data-close-drawer></div>' +
      '<aside class="drawer' + (state.drawer ? ' open' : '') + '" role="dialog" aria-label="录入 First Touch"' +
      ' aria-hidden="' + (!state.drawer) + '">' +
      '<div class="row"><h2>录入 First Touch</h2><span class="spacer"></span>' +
      '<button class="btn ghost" type="button" data-close-drawer>关闭</button></div>' +

      '<fieldset class="gap"><legend>目标认同</legend>' +
      '<label class="fl" for="ft-judge">学生是否认同目标</label>' +
      '<select class="inp" id="ft-judge" data-ft="judgement">' +
      optionList([['', '—'], ['认同', '认同'], ['部分认同', '部分认同'], ['不认同', '不认同']],
        goal.judgement || '') + '</select></fieldset>' +

      '<fieldset class="gap"><legend>时间</legend>' +
      '<label class="fl" for="ft-liked">时间主要花在喜欢的事上</label>' +
      '<select class="inp" id="ft-liked" data-ft="time_on_liked">' +
      optionList([['', '未问'], ['true', '是'], ['false', '否']],
        boolValue(goal.time_on_liked)) + '</select>' +
      '<label class="fl" for="ft-full">会谈前确认时间排满</label>' +
      '<select class="inp" id="ft-full" data-ft="confirmed_full">' +
      optionList([['', '未问'], ['true', '是'], ['false', '否']],
        boolValue(schedule.confirmed_full)) + '</select></fieldset>' +

      '<fieldset class="gap"><legend>标准化任务</legend>' +
      '<label class="fl" for="ft-split">能拆出步骤</label>' +
      '<select class="inp" id="ft-split" data-ft="can_split">' +
      optionList([['', '—'], ['true', '是'], ['false', '否']],
        boolValue(task.can_split)) + '</select>' +
      '<label class="fl" for="ft-commit">能开始</label>' +
      '<select class="inp" id="ft-commit" data-ft="can_commit">' +
      optionList([['', '—'], ['true', '是'], ['false', '否']],
        boolValue(task.can_commit)) + '</select></fieldset>' +

      '<fieldset class="gap"><legend>家长主诉</legend>' +
      '<textarea class="inp" data-parent-complaint>' + SA.esc(complaint.text || '') + '</textarea>' +
      '</fieldset>' +

      '<div class="row"><button class="btn primary" type="button" data-save-ft>保存</button>' +
      '<button class="btn ghost" type="button" data-close-drawer>取消</button></div></aside>';
  }

  /* ── 渲染 ───────────────────────────────────────────────── */
  function render(el) {
    var writable = SA.canWrite();
    if (state.data && state.data.legacy) {
      el.innerHTML = headerHTML(false) +
        '<div class="card pad"><div class="row"><p>这份档案按旧规则生成</p><span class="spacer"></span>' +
        (writable ? '<button class="btn primary" type="button" data-generate>按新规则重新生成</button>' : '') +
        '</div></div>';
      return;
    }
    var dim = state.dim;
    var main = '';
    if (dim === 'A6') main = a6Panel();
    else main = '<section class="card mmcard">' +
      SA.mindmap.dim(model(), dim, { profile: profileOf(), writable: writable }) + '</section>';
    el.innerHTML = headerHTML(writable) + flagsHTML() + dimsHTML() + main + drawerHTML();
  }

  function renderEmpty(el) {
    el.innerHTML = '<div class="card empty">从学生总览选择一名学生。</div>';
  }

  function renderError(el, err) {
    el.innerHTML = '<div class="card empty"><span>' + SA.esc(err.message) + '</span>' +
      '<button class="btn" type="button" data-retry>重试</button></div>';
  }

  function loading(el) {
    el.innerHTML = '<p class="sub">加载中…</p>';
  }

  /* ── 取数 ───────────────────────────────────────────────── */
  function applyData(el, data) {
    state.data = data;
    if (!validDim(state.dim)) state.dim = firstDim(data);
    render(el);
  }

  function load(el, profileId) {
    if (!state.report) { renderEmpty(el); return; }
    loading(el);
    SA.loadModel().then(function () {
      var url = '/api/reports/' + encodeURIComponent(state.report) + '/six-am';
      if (profileId != null) url += '?profile_id=' + encodeURIComponent(profileId);
      return SA.api(url);
    }).then(function (data) {
      applyData(el, data);
    }).catch(function (err) {
      SA.toast(err.message, true);
      renderError(el, err);
    });
  }

  function submitInputs(el, body) {
    SA.postJSON('/api/reports/' + encodeURIComponent(state.report) + '/six-am/inputs', body)
      .then(function (data) { applyData(el, data); })
      .catch(function (err) { SA.toast(err.message, true); });
  }

  function gatherTalk(box) {
    var pressed = box.querySelector('[data-talk-result][aria-pressed="true"]');
    if (!pressed) return null;
    var record = {
      result: pressed.getAttribute('data-talk-result'),
      causes: [],
      note: ''
    };
    Array.prototype.forEach.call(box.querySelectorAll('[data-talk-cause]:checked'), function (input) {
      record.causes.push(input.getAttribute('data-talk-cause'));
    });
    var note = box.querySelector('[data-talk-note]');
    if (note) record.note = note.value.trim();
    if (record.result === 'set') {
      var level = box.querySelector('[data-talk-level]');
      record.set_level = level ? level.value : '关注';
    }
    return { dim: box.getAttribute('data-talk'), record: record };
  }

  function collectFT(el) {
    function value(name) {
      var node = el.querySelector('[data-ft="' + name + '"]');
      return node ? node.value : '';
    }
    function tri(name) {
      var raw = value(name);
      return raw === '' ? null : raw === 'true';
    }
    var complaint = el.querySelector('[data-parent-complaint]');
    return {
      ft: {
        goal: {
          judgement: value('judgement') || null,
          time_on_liked: tri('time_on_liked')
        },
        standard_task: {
          can_split: tri('can_split'),
          can_commit: tri('can_commit')
        },
        schedule: {
          confirmed_full: tri('confirmed_full')
        }
      },
      parent: { complaint: { text: complaint ? complaint.value.trim() : '' } }
    };
  }

  function setDrawer(el, open) {
    state.drawer = open;
    var mask = el.querySelector('.drawer-mask');
    var drawer = el.querySelector('.drawer');
    if (mask) mask.classList.toggle('open', open);
    if (drawer) {
      drawer.classList.toggle('open', open);
      drawer.setAttribute('aria-hidden', String(!open));
      if (open) {
        var first = drawer.querySelector('select, textarea, input');
        if (first) first.focus();
      }
    }
  }

  /* ── 事件 ───────────────────────────────────────────────── */
  function bind(el) {
    if (el.getAttribute('data-sa2-bound')) return;
    el.setAttribute('data-sa2-bound', '1');

    el.addEventListener('click', function (e) {
      var target = e.target.closest('[data-dim],[data-generate],[data-retry],[data-open-ft],' +
        '[data-close-drawer],[data-save-ft],[data-talk-save],[data-talk-clear],[data-talk-result]');
      if (!target) return;

      if (target.hasAttribute('data-dim')) {
        SA.go('student', { report: state.report, dim: target.getAttribute('data-dim') });
        return;
      }

      if (target.hasAttribute('data-retry')) { load(el); return; }

      if (target.hasAttribute('data-generate')) {
        target.disabled = true;
        SA.api('/api/reports/' + encodeURIComponent(state.report) + '/six-am/generate',
          { method: 'POST' })
          .then(function (data) { applyData(el, data); })
          .catch(function (err) {
            target.disabled = false;
            SA.toast(err.message, true);
          });
        return;
      }

      if (target.hasAttribute('data-open-ft')) { setDrawer(el, true); return; }
      if (target.hasAttribute('data-close-drawer')) { setDrawer(el, false); return; }

      if (target.hasAttribute('data-save-ft')) {
        submitInputs(el, collectFT(el));
        setDrawer(el, false);
        return;
      }

      if (target.hasAttribute('data-talk-result')) {
        var group = target.parentNode;
        Array.prototype.forEach.call(group.querySelectorAll('[data-talk-result]'), function (btn) {
          btn.setAttribute('aria-pressed', String(btn === target));
        });
        var box = target.closest('[data-talk]');
        var level = box ? box.querySelector('[data-talk-level]') : null;
        if (level) level.hidden = target.getAttribute('data-talk-result') !== 'set';
        return;
      }

      if (target.hasAttribute('data-talk-save')) {
        var boxSave = target.closest('[data-talk]');
        var gathered = boxSave ? gatherTalk(boxSave) : null;
        if (!gathered) return;
        var body = { talks: {} };
        body.talks[gathered.dim] = gathered.record;
        submitInputs(el, body);
        return;
      }

      if (target.hasAttribute('data-talk-clear')) {
        var boxClear = target.closest('[data-talk]');
        if (!boxClear) return;
        var clearBody = { talks: {} };
        clearBody.talks[boxClear.getAttribute('data-talk')] = null;
        submitInputs(el, clearBody);
      }
    });

    el.addEventListener('change', function (e) {
      var version = e.target.closest('[data-version]');
      if (version) load(el, version.value);
    });

    el.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && state.drawer) setDrawer(el, false);
    });
  }

  SA.views.student = {
    show: function (el, params) {
      bind(el);
      var report = params.report == null || params.report === '' ? null : String(params.report);
      var changed = report !== state.report;
      state.report = report;
      if (!report) {
        state.data = null;
        renderEmpty(el);
        return;
      }
      if (changed || !state.data) {
        state.data = null;
        state.dim = params.dim || null;
        load(el);
        return;
      }
      if (params.dim) state.dim = params.dim;
      render(el);
    }
  };
})();
