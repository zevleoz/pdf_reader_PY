/* 6AM v0.6 · 学生总览：一行一名学生，颜色即级别；筛选 / 搜索 / 全部重算。 */
(function () {
  'use strict';

  var SA = window.SA;
  var DIMS = ['A1', 'A2', 'A3', 'A4', 'A5'];
  var FILTERS = [
    ['all', '全部'],
    ['talk', '待会谈'],
    ['blocked', '有阻塞'],
    ['legacy', '旧规则'],
    ['pending', '未生成']
  ];

  var state = { students: [], noReport: 0, filter: 'all', search: '', loaded: false };

  function worstOf(s) {
    var worst = -1;
    DIMS.forEach(function (dim) {
      worst = Math.max(worst, SA.sev((s.levels || {})[dim]));
    });
    return worst;
  }

  function riskCount(s) {
    var count = 0;
    DIMS.forEach(function (dim) {
      if (SA.sev((s.levels || {})[dim]) >= 2) count += 1;
    });
    return count;
  }

  function needsTalk(s) { return !!((s.needs_talk || []).length); }
  function hasBlocked(s) { return !!((s.blocked || []).length); }

  function matchFilter(s) {
    if (state.filter === 'talk') return needsTalk(s);
    if (state.filter === 'blocked') return hasBlocked(s);
    if (state.filter === 'legacy') return !!s.legacy;
    if (state.filter === 'pending') return !!s.pending;
    return true;
  }

  function matchSearch(s) {
    if (!state.search) return true;
    return String(s.name || '').toLowerCase().indexOf(state.search.toLowerCase()) >= 0;
  }

  function visible() {
    var list = state.students.filter(function (s) {
      return matchFilter(s) && matchSearch(s);
    });
    list.sort(function (a, b) {
      return ((a.pending ? 1 : 0) - (b.pending ? 1 : 0)) ||
        (worstOf(b) - worstOf(a)) ||
        (riskCount(b) - riskCount(a)) ||
        String(a.name || '').localeCompare(String(b.name || ''), 'zh-Hans-CN');
    });
    return list;
  }

  function countFor(key) {
    return state.students.filter(function (s) {
      if (key === 'talk') return needsTalk(s);
      if (key === 'blocked') return hasBlocked(s);
      if (key === 'legacy') return !!s.legacy;
      if (key === 'pending') return !!s.pending;
      return true;
    }).length;
  }

  function filtersHTML() {
    var shown = FILTERS.filter(function (f) {
      return f[0] === 'all' || f[0] === 'talk' || f[0] === 'blocked' ||
        countFor(f[0]) > 0 || state.filter === f[0];
    });
    return '<div class="filters" role="group" aria-label="筛选">' + shown.map(function (f) {
      var label = f[1] + (f[0] === 'all' ? '' : ' ' + countFor(f[0]));
      return '<button class="fchip" type="button" data-filter="' + f[0] + '" aria-pressed="' +
        (state.filter === f[0]) + '">' + SA.esc(label) + '</button>';
    }).join('') + '</div>';
  }

  function dimName(dim) {
    var dims = (SA.model && SA.model.dims) || [];
    for (var i = 0; i < dims.length; i += 1) {
      if (dims[i].id === dim) return dims[i].name || '';
    }
    return '';
  }

  /* 一格只放一个级别 chip；类型放进 title，悬停可见 */
  function cellHTML(s, dim) {
    var level = (s.levels || {})[dim];
    var type = (s.types || {})[dim];
    var chip = SA.chip(level) || '<span class="none">—</span>';
    return '<td class="dm"' + (type ? ' title="' + SA.esc(type) + '"' : '') + '>' +
      '<span class="dk">' + dim + '</span>' + chip + '</td>';
  }

  function whoHTML(s) {
    var meta = [s.grade, s.report_date].filter(function (x) { return x; }).join(' · ');
    var marks = '';
    if (s.safety) marks += '<span class="mark block">安全复核</span>';
    if (s.legacy) marks += '<span class="mark">旧规则</span>';
    return '<td class="who"><span class="nm">' + SA.esc(s.name || '') + '</span>' + marks +
      '<small>' + SA.esc(meta) + '</small></td>';
  }

  function talkHTML(s) {
    var dims = s.needs_talk || [];
    if (!dims.length) return '<td class="tk"><span class="none">—</span></td>';
    return '<td class="tk"><span class="tk-l">待会谈</span>' + SA.esc(dims.join(' ')) + '</td>';
  }

  function supportHTML(s) {
    var names = s.a6_top || [];
    if (!names.length) return '<td class="sup"><span class="none">—</span></td>';
    var shown = names.slice(0, 2).join(' · ');
    var more = names.length > 2 ? ' <span class="more">+' + (names.length - 2) + '</span>' : '';
    return '<td class="sup" title="' + SA.esc(names.join(' · ')) + '"><span class="one">' +
      SA.esc(shown) + '</span>' + more + '</td>';
  }

  function rowsHTML(list) {
    return list.map(function (s) {
      if (s.pending) {
        return '<tr class="pending" data-report="' + SA.esc(s.report_id) + '" tabindex="0">' +
          whoHTML(s) + '<td class="pend" colspan="7">未生成</td></tr>';
      }
      return '<tr data-report="' + SA.esc(s.report_id) + '" tabindex="0">' + whoHTML(s) +
        DIMS.map(function (dim) { return cellHTML(s, dim); }).join('') +
        talkHTML(s) + supportHTML(s) + '</tr>';
    }).join('');
  }

  function listHTML() {
    if (!state.students.length) {
      return '<div class="card empty">还没有学生报告。</div>';
    }
    var list = visible();
    if (!list.length) return '<div class="card empty">没有符合条件的学生。</div>';
    return '<div class="card tablewrap"><table class="roster"><colgroup><col class="c-who">' +
      DIMS.map(function () { return '<col class="c-dm">'; }).join('') +
      '<col class="c-tk"><col class="c-sup"></colgroup><thead><tr><th>学生</th>' +
      DIMS.map(function (dim) {
        return '<th class="dm">' + dim + '<small>' + SA.esc(dimName(dim)) + '</small></th>';
      }).join('') +
      '<th>会谈</th><th>先用的支持</th></tr></thead><tbody>' +
      rowsHTML(list) + '</tbody></table></div>';
  }

  function headHTML() {
    var sub = state.students.length + ' 名学生';
    if (state.noReport) sub += ' · ' + state.noReport + ' 名没有 Y4 报告';
    var pending = state.students.filter(function (s) { return s.pending; }).length;
    var admin = SA.isAdmin();
    return '<div class="ovhead"><div><h1>学生总览</h1><p class="sub">' + SA.esc(sub) +
      '</p></div><span class="spacer"></span>' +
      '<label class="sr" for="sa2-q">搜索学生</label>' +
      '<input class="search" id="sa2-q" type="search" placeholder="搜索姓名" value="' +
      SA.esc(state.search) + '">' +
      (admin && !pending ? '<button class="btn" type="button" data-rerun>全部重新生成</button>' : '') +
      '</div>' +
      (pending ? '<div class="pendbar"><span>' + pending + ' 名学生还没有生成 6AM</span>' +
        (admin ? '<button class="btn primary" type="button" data-rerun>全部生成</button>' : '') +
        '</div>' : '');
  }

  function render(el) {
    el.innerHTML = headHTML() + filtersHTML() + '<div id="sa2-ov-list">' + listHTML() + '</div>';
  }

  function renderError(el, err) {
    el.innerHTML = '<div class="ovhead"><div><h1>学生总览</h1>' +
      '<p class="sub">' + SA.esc(err.message) + '</p></div><span class="spacer"></span>' +
      '<button class="btn" type="button" data-retry>重试</button></div>';
  }

  function refreshList(el) {
    var box = el.querySelector('#sa2-ov-list');
    if (box) box.innerHTML = listHTML();
  }

  function load(el) {
    SA.loadModel().catch(function () {}).then(function () {
      return SA.api('/api/six-am/cohort');
    }).then(function (data) {
      state.students = data.students || [];
      state.noReport = data.no_report || 0;
      state.loaded = true;
      render(el);
    }).catch(function (err) {
      SA.toast(err.message, true);
      renderError(el, err);
    });
  }

  function bind(el) {
    if (el.getAttribute('data-sa2-bound')) return;
    el.setAttribute('data-sa2-bound', '1');

    el.addEventListener('click', function (e) {
      var target = e.target.closest('[data-filter],[data-report],[data-retry],[data-rerun]');
      if (!target) return;

      if (target.hasAttribute('data-retry')) { load(el); return; }

      if (target.hasAttribute('data-rerun')) {
        if (!window.confirm(target.textContent + '？')) return;
        target.disabled = true;
        target.textContent = '生成中…';
        SA.api('/api/six-am/rerun-all', { method: 'POST' }).then(function () {
          load(el);
        }).catch(function (err) {
          target.disabled = false;
          SA.toast(err.message, true);
        });
        return;
      }

      if (target.hasAttribute('data-filter')) {
        var next = target.getAttribute('data-filter');
        state.filter = (state.filter === next && next !== 'all') ? 'all' : next;
        render(el);
        return;
      }

      SA.go('student', { report: target.getAttribute('data-report'), dim: null });
    });

    el.addEventListener('input', function (e) {
      if (e.target.id === 'sa2-q') {
        state.search = e.target.value.trim();
        refreshList(el);
      }
    });

    el.addEventListener('keydown', function (e) {
      var row = e.target.closest('tr[data-report]');
      if (row && (e.key === 'Enter' || e.key === ' ')) {
        e.preventDefault();
        row.click();
      }
    });
  }

  SA.views.overview = {
    show: function (el) {
      bind(el);
      if (!state.loaded) el.innerHTML = '<p class="sub">加载中…</p>';
      load(el);
    }
  };
})();
