/* 6AM 2.0 · 总览：全班名单、五维状态分布、筛选与搜索。 */
(function () {
  'use strict';

  var SA = window.SA;
  var DIMS = [['A1', '自主感'], ['A2', '认同感'], ['A3', '可用空间'], ['A4', '胜任信心'], ['A5', '可起步性']];
  var DIM_ZH = {};
  DIMS.forEach(function (d) { DIM_ZH[d[0]] = d[1]; });

  var ORDER = ['Secure', 'Watch', 'At-Risk', 'Blocked'];
  var BAR_COLOR = { Secure: 'line', Watch: 'watch', 'At-Risk': 'risk', Blocked: 'block' };
  var RANK = { Secure: 0, Watch: 1, 'At-Risk': 2, Blocked: 3 };

  var FILTERS = [
    ['all', '全部'], ['safety', '需安全复核'], ['risk', '风险及以上'],
    ['y4only', '仅 Y4 线索'], ['missing', '数据缺失'], ['pending', '待评审']
  ];

  var state = { filter: 'all', search: '', students: [], distribution: {} };

  function worst(s) {
    var w = 'Secure';
    DIMS.forEach(function (d) {
      var st = s.states[d[0]];
      if ((RANK[st] || 0) > RANK[w]) w = st;
    });
    return w;
  }
  function isY4Only(s) {
    return DIMS.some(function (d) {
      return RANK[s.states[d[0]]] >= 2 && s.evidence[d[0]] === 'Hypothesis';
    });
  }
  function match(s) {
    if (state.search && String(s.name || '').indexOf(state.search) < 0) return false;
    switch (state.filter) {
      case 'safety': return !!s.safety;
      case 'block': return worst(s) === 'Blocked';
      case 'risk': return RANK[worst(s)] >= 2;
      case 'y4only': return isY4Only(s);
      case 'missing': return !!(s.missing && s.missing.length);
      case 'pending': return s.review_status === 'pending';
      default: return true;
    }
  }

  function reviewTag(status) {
    if (status === 'pending') return '<span class="tag" style="background:var(--watch-bg);color:var(--watch)">待评审</span>';
    if (status === 'reviewed') return '<span class="tag" style="background:var(--ok-bg);color:var(--ok)">已评审</span>';
    return '<span class="sub">—</span>';
  }
  function dateShort(d) { return d ? String(d).slice(5) : '—'; }
  function versionLabel(v) { return v == null ? '' : 'v' + v; }

  function kpi(f, num, label, alert) {
    return '<button class="kpi' + (alert && num ? ' alert' : '') + '" type="button" data-filter="' + f +
      '" aria-pressed="' + (state.filter === f) + '"><strong>' + num + '</strong><span>' + label + '</span></button>';
  }

  function kpis() {
    var list = state.students;
    var safety = list.filter(function (s) { return s.safety; }).length;
    var block = list.filter(function (s) { return worst(s) === 'Blocked'; }).length;
    var y4 = list.filter(isY4Only).length;
    var pend = list.filter(function (s) { return s.review_status === 'pending'; }).length;
    return '<div class="kpis">' +
      kpi('safety', safety, '需情绪安全复核', true) +
      kpi('block', block, '有阻塞维度', true) +
      kpi('y4only', y4, '风险仅凭 Y4 线索，待补证据') +
      kpi('pending', pend, '待团队评审') + '</div>';
  }

  function distributionCard() {
    var h = '<section class="card pad" aria-label="各维度分布"><div class="row" style="margin-bottom:12px">' +
      '<h2>各维度状态分布</h2><span class="spacer"></span><span class="legend">' +
      ORDER.map(function (s) { return SA.pill(s); }).join(' ') + '</span></div><div class="dist">';
    DIMS.forEach(function (d) {
      var dist = state.distribution[d[0]] || {};
      var total = 0;
      ORDER.forEach(function (s) { total += (dist[s] || 0); });
      var atRisk = (dist['At-Risk'] || 0) + (dist.Blocked || 0);
      h += '<div class="d"><div class="lbl"><b>' + d[0] + ' ' + d[1] + '</b>' +
        '<span class="cnt">≥ 风险 ' + atRisk + '/' + total + '</span></div><div class="bar">' +
        ORDER.map(function (s) {
          var cnt = dist[s] || 0;
          if (!cnt || !total) return '';
          return '<span style="width:' + (cnt / total * 100) + '%;background:var(--' + BAR_COLOR[s] +
            ')" title="' + SA.STATE_ZH[s] + ' ' + cnt + '"></span>';
        }).join('') + '</div></div>';
    });
    return h + '</div></section>';
  }

  function filtersRow() {
    return '<div class="row"><div class="filters" role="group" aria-label="筛选">' +
      FILTERS.map(function (f) {
        return '<button class="chip" type="button" data-filter="' + f[0] + '" aria-pressed="' +
          (state.filter === f[0]) + '">' + f[1] + '</button>';
      }).join('') + '</div><span class="spacer"></span>' +
      '<label class="sr" for="sa2-q">搜索学生</label>' +
      '<input class="search" id="sa2-q" type="search" placeholder="搜索学生" value="' + SA.esc(state.search) + '"></div>';
  }

  function listHTML() {
    if (!state.students.length) {
      return '<div class="card pad"><p class="sub">还没有 6AM 档案。在学生的报告页生成后会出现在这里。</p></div>';
    }
    var list = state.students.filter(match);
    if (!list.length) {
      return '<div class="card pad"><p class="sub">没有符合筛选条件的学生。</p></div>';
    }
    var h = '<div class="card tablewrap"><table class="roster"><thead><tr><th>学生</th>' +
      DIMS.map(function (d) { return '<th>' + d[0] + ' ' + d[1] + '</th>'; }).join('') +
      '<th>A6 首选支持</th><th>先处理</th><th>评审</th></tr></thead><tbody>';
    list.forEach(function (s) {
      h += '<tr data-report="' + s.report_id + '" data-profile="' + s.profile_id + '" tabindex="0">' +
        '<td class="who"><b>' + SA.esc(s.name) + '</b><small>' + SA.esc(s.grade) + ' · ' +
        dateShort(s.report_date) + ' · ' + versionLabel(s.version) + '</small>' +
        (s.safety ? '<div class="flag">● 需安全复核</div>' : '') +
        ((s.missing && s.missing.length) ? '<div class="flag" style="color:var(--watch)">● 数据缺失</div>' : '') +
        '</td>';
      DIMS.forEach(function (d) {
        var st = s.states[d[0]];
        h += '<td><div class="cell">' + SA.pill(st) +
          SA.ev(st !== 'Secure' ? s.evidence[d[0]] : null) + '</div></td>';
      });
      var first = (s.order || [])[0];
      h += '<td>' + SA.esc(s.a6_top || '—') + '</td><td>' +
        (first ? first + ' ' + (DIM_ZH[first] || '') : '—') + '</td><td>' +
        reviewTag(s.review_status) + '</td></tr>';
    });
    h += '</tbody></table></div>';

    h += '<div class="cards-m">' + list.map(function (s) {
      return '<button class="card pad" type="button" data-report="' + s.report_id + '" data-profile="' +
        s.profile_id + '" style="text-align:left;display:flex;flex-direction:column;gap:8px">' +
        '<div class="row"><b>' + SA.esc(s.name) + '</b><span class="sub">' + SA.esc(s.grade) + ' · ' +
        versionLabel(s.version) + '</span><span class="spacer"></span>' + reviewTag(s.review_status) + '</div>' +
        (s.safety ? '<div class="flag">● 需安全复核</div>' : '') +
        '<div class="row" style="gap:6px 10px">' + DIMS.map(function (d) {
          return '<span style="display:inline-flex;gap:4px;align-items:center;white-space:nowrap">' +
            '<span class="sub" style="font-size:11.5px">' + d[0] + '</span>' +
            SA.pill(s.states[d[0]]) + '</span>';
        }).join('') + '</div></button>';
    }).join('') + '</div>';
    return h;
  }

  function render(el) {
    el.innerHTML =
      '<div class="row"><div><h1>6AM 启动模型 · 总览</h1><p class="sub">' +
        state.students.length + ' 名学生有档案</p></div><span class="spacer"></span>' +
        '<a class="btn" href="/insights/six-am/rules">规则与参数</a>' +
        '<button class="btn primary" type="button" data-go="review">开始评审会</button></div>' +
      kpis() + distributionCard() + filtersRow() +
      '<div id="sa2-ov-list">' + listHTML() + '</div>';
    bind(el);
  }

  function renderError(el, err) {
    el.innerHTML =
      '<div class="row"><div><h1>6AM 启动模型 · 总览</h1>' +
      '<p class="sub">' + SA.esc(err.message) + '</p></div><span class="spacer"></span>' +
      '<button class="btn" type="button" data-retry="1">重试</button></div>';
    bind(el);
  }

  function refreshList(el) {
    var box = el.querySelector('#sa2-ov-list');
    if (box) box.innerHTML = listHTML();
  }

  function syncControls(el) {
    var btns = el.querySelectorAll('[data-filter]');
    Array.prototype.forEach.call(btns, function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-filter') === state.filter));
    });
    refreshList(el);
  }

  function bind(el) {
    if (el.getAttribute('data-sa2-bound')) return;
    el.setAttribute('data-sa2-bound', '1');
    el.addEventListener('click', function (e) {
      var t = e.target.closest('[data-go],[data-filter],[data-report],[data-retry]');
      if (!t) return;
      if (t.hasAttribute('data-retry')) { show(el); return; }
      if (t.hasAttribute('data-go')) { SA.go(t.getAttribute('data-go')); return; }
      if (t.hasAttribute('data-filter')) {
        var f = t.getAttribute('data-filter');
        state.filter = (state.filter === f && f !== 'all') ? 'all' : f;
        syncControls(el);
        return;
      }
      SA.go('profile', { report_id: t.getAttribute('data-report'), profile_id: t.getAttribute('data-profile') });
    });
    el.addEventListener('input', function (e) {
      if (e.target.id === 'sa2-q') {
        state.search = e.target.value.trim();
        refreshList(el);
      }
    });
    el.addEventListener('keydown', function (e) {
      var row = e.target.closest('tr[data-report]');
      if (row && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); row.click(); }
    });
  }

  function show(el) {
    if (!state.students.length) el.innerHTML = '<p class="sub">加载中…</p>';
    SA.api('/api/six-am/cohort').then(function (data) {
      state.students = data.students || [];
      state.distribution = data.distribution || {};
      render(el);
    }).catch(function (err) {
      SA.toast(err.message, true);
      renderError(el, err);
    });
  }

  SA.views.overview = { show: show };
})();