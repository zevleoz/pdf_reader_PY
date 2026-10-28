/* 6AM v0.6 共享层：window.SA
   视图壳（总览 / 学生 / 规则）、地址栏同步（?view=&report=&dim=，前进后退可用）、
   模型加载与级别 chip。视图模块自行注册：SA.views.<name> = {show: function(el, params){}}。 */
(function () {
  'use strict';

  var SA = {};
  window.SA = SA;

  var VIEWS = ['overview', 'student', 'rules'];
  var LEVELS = ['稳固', '关注', '风险', '阻塞'];
  var SEV = { '稳固': 0, '关注': 1, '风险': 2, '阻塞': 3 };
  var CLS = { '稳固': 'sec', '关注': 'watch', '风险': 'risk', '阻塞': 'block' };

  SA.views = {};
  SA.LEVELS = LEVELS;

  SA.esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  };

  SA.sev = function (level) {
    return SEV[String(level)] == null ? -1 : SEV[String(level)];
  };

  /* 级别 chip：全站唯一入口 */
  SA.chip = function (level) {
    var cls = CLS[String(level)];
    if (!cls) return '';
    return '<span class="lv-chip ' + cls + '">' + SA.esc(level) + '</span>';
  };

  /* fetch + JSON；ok 为 false（或 HTTP 失败）时抛出 Error(json.error) */
  SA.api = function (url, opts) {
    return fetch(url, opts).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (json) {
        if (!json || json.ok === false) {
          throw new Error((json && json.error) || ('请求失败（HTTP ' + res.status + '）'));
        }
        return json;
      });
    });
  };

  SA.postJSON = function (url, body) {
    return SA.api(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    });
  };

  function root() { return document.getElementById('sa2'); }

  SA.canWrite = function () {
    var el = root();
    return !!el && el.getAttribute('data-can-write') === 'true';
  };

  SA.isAdmin = function () {
    var el = root();
    return !!el && el.getAttribute('data-is-admin') === 'true';
  };

  SA.toast = function (msg, isErr) {
    if (typeof window.v2Toast === 'function') {
      window.v2Toast(msg, isErr ? 'error' : 'info');
    } else if (typeof window.y4Toast === 'function') {
      window.y4Toast(msg, isErr ? 'error' : 'info');
    }
  };

  /* 模型只取一次 */
  SA.model = null;
  SA.loadModel = function () {
    if (SA.model) return Promise.resolve(SA.model);
    if (!SA._modelP) {
      SA._modelP = SA.api('/api/six-am/model').then(function (data) {
        SA.model = data.model;
        return SA.model;
      });
      SA._modelP.catch(function () {});
    }
    return SA._modelP;
  };

  function section(view) { return document.getElementById('sa2-' + view); }

  var state = { view: 'overview', report: null, dim: null };

  SA.params = function () {
    return { view: state.view, report: state.report, dim: state.dim };
  };

  function urlFor(view, report, dim) {
    var q = ['view=' + encodeURIComponent(view)];
    if (report != null && report !== '') q.push('report=' + encodeURIComponent(report));
    if (dim) q.push('dim=' + encodeURIComponent(dim));
    return location.pathname + '?' + q.join('&');
  }

  function syncHistory(replace) {
    var url = urlFor(state.view, state.report, state.dim);
    if (location.pathname + location.search === url) return;
    if (replace) history.replaceState(null, '', url);
    else history.pushState(null, '', url);
  }

  function paint() {
    VIEWS.forEach(function (v) {
      var sec = section(v);
      if (sec) sec.hidden = (v !== state.view);
      var tab = document.getElementById('sa2-tab-' + v);
      if (tab) {
        tab.setAttribute('aria-selected', String(v === state.view));
        tab.setAttribute('tabindex', v === state.view ? '0' : '-1');
      }
    });
    var mod = SA.views[state.view];
    var sec = section(state.view);
    if (mod && typeof mod.show === 'function' && sec) {
      mod.show(sec, { report: state.report, dim: state.dim });
    }
  }

  /* 切换视图：换显隐、同步 tab、写地址栏、调用视图的 show() */
  SA.go = function (view, params, opts) {
    if (VIEWS.indexOf(view) < 0) view = 'overview';
    params = params || {};
    state.view = view;
    if ('report' in params) state.report = params.report == null || params.report === '' ? null : String(params.report);
    if ('dim' in params) state.dim = params.dim || null;
    syncHistory(!!(opts && opts.replace));
    paint();
    window.scrollTo(0, 0);
  };

  function routeFromUrl() {
    var q = new URLSearchParams(location.search);
    var view = q.get('view');
    if (VIEWS.indexOf(view) < 0) view = 'overview';
    var report = q.get('report');
    var dim = q.get('dim');
    state.view = view;
    state.report = report || null;
    state.dim = dim || null;
    syncHistory(true);
    paint();
  }

  function init() {
    var nav = document.getElementById('sa2-tabs');
    if (nav) {
      nav.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-view]');
        if (btn) SA.go(btn.getAttribute('data-view'));
      });
    }
    window.addEventListener('popstate', routeFromUrl);
    SA.loadModel().catch(function () {});
    routeFromUrl();
  }

  /* defer 脚本按文档顺序执行：等 DOMContentLoaded，模块都注册完再首屏路由 */
  if (document.readyState === 'complete') {
    init();
  } else {
    document.addEventListener('DOMContentLoaded', init);
  }
})();
