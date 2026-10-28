/* 6AM v0.6 · 学生总览：一行一名学生，颜色即级别；筛选 / 搜索 / 全部重算。 */
(function () {
  'use strict';

  var SA = window.SA;
  var DIMS = ['A1', 'A2', 'A3', 'A4', 'A5'];
  var FILTERS = [
    ['all', '全部'],
    ['talk', '待会谈'],
    ['blocked', '有阻塞'],
    ['legacy', '旧规则']
  ];

  var state = { students: [], filter: 'all', search: '', loaded: false };

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
      return (worstOf(b) - worstOf(a)) ||
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
      return true;
    }).length;
  }

  function filtersHTML() {
    return '<div class="filters" role="group" aria-label="筛选">' + FILTERS.map(function (f) {
      var label = f[1] + (f[0] === 'all' ? '' : ' ' + countFor(f[0]));
      return '<button class="fchip" type="button" data-filter="' + f[0] + '" aria-pressed="' +
        (state.filter === f[0]) + '">' + SA.esc(label) + '</button>';
    }).join('') + '</div>';
  }

  function tagsHTML(s) {
    var h = '';
    if (needsTalk(s)) h += '<span class="tag warn">待会谈</span>';
    if (s.safety) h += '<span class="tag block">安全复核</span>';
    if (s.legacy) h += '<span class="tag legacy">旧规则</span>';
    return h;
  }

  function cellsHTML(s, dim) {
    var level = (s.levels || {})[dim];
    var type = (s.types || {})[dim];
    return '<td class="dm"><small class="dk">' + dim + '</small>' + SA.chip(level) +
      (type ? '<small>' + SA.esc(type) + '</small>' : '') + '</td>';
  }

  function rowsHTML(list) {
    return list.map(function (s) {
      return '<tr data-report="' + SA.esc(s.report_id) + '" tabindex="0">' +
        '<td class="who"><b>' + SA.esc(s.name || '') + '</b>' +
        '<small><span class="gr-m">' + SA.esc(s.grade || '') + ' · </span>' +
        SA.esc(s.report_date || '') + ' · v' + SA.esc(s.version) + '</small></td>' +
        '<td class="gr">' + SA.esc(s.grade || '') + '</td>' +
        DIMS.map(function (dim) { return cellsHTML(s, dim); }).join('') +
        '<td class="sup">' + SA.esc((s.a6_top || []).join(' · ') || '—') + '</td>' +
        '<td class="tags">' + tagsHTML(s) + '</td></tr>';
    }).join('');
  }

  function listHTML() {
    if (!state.students.length) {
      return '<div class="card empty">还没有 6AM 档案。</div>';
    }
    var list = visible();
    if (!list.length) return '<div class="card empty">没有符合条件的学生。</div>';
    return '<div class="card tablewrap"><table class="roster"><thead><tr>' +
      '<th>姓名</th><th>年级</th>' +
      DIMS.map(function (dim) { return '<th>' + dim + '</th>'; }).join('') +
      '<th>先用的支持</th><th></th></tr></thead><tbody>' +
      rowsHTML(list) + '</tbody></table></div>';
  }

  function headHTML() {
    return '<div class="ovhead"><div><h1>学生总览</h1><p class="sub">' +
      state.students.length + ' 名学生</p></div><span class="spacer"></span>' +
      (SA.isAdmin() ? '<button class="btn" type="button" data-rerun>全部重算</button>' : '') +
      '<label class="sr" for="sa2-q">搜索学生</label>' +
      '<input class="search" id="sa2-q" type="search" placeholder="搜索" value="' +
      SA.esc(state.search) + '"></div>';
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
    SA.api('/api/six-am/cohort').then(function (data) {
      state.students = data.students || [];
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
        if (!window.confirm('全部重算？')) return;
        target.disabled = true;
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
