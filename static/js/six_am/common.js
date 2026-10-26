/* 6AM 2.0 共享层：window.SA
   页面壳（视图切换 / 地址栏同步）与各视图共用的工具函数。
   视图模块自行注册：SA.views.<name> = { show: function (el, params) {} }。 */
(function () {
  'use strict';

  var SA = {};
  window.SA = SA;

  var VIEWS = ['overview', 'profile', 'review'];
  var ST_CLASS = { Secure: 'S', Watch: 'W', 'At-Risk': 'R', Blocked: 'B' };
  var EV_CLASS = { Hypothesis: 'H', Supported: 'P', Confirmed: 'C' };

  SA.STATE_ZH = { Secure: '稳固', Watch: '关注', 'At-Risk': '风险', Blocked: '阻塞' };
  SA.EV_ZH = { Hypothesis: '仅线索', Supported: '有佐证', Confirmed: '已证实' };
  SA.views = {};

  SA.esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  };

  /* 状态 pill：颜色 + 0–3 格，与原型 pill() 一致 */
  SA.pill = function (state) {
    var cls = ST_CLASS[state] || 'S';
    return '<span class="st ' + cls + '"><i><b></b><b></b><b></b></i>' +
      (SA.STATE_ZH[state] || '') + '</span>';
  };

  /* 证据点：无证据返回空串，与原型 evb() 一致 */
  SA.ev = function (evidence) {
    if (!evidence) return '';
    return '<span class="ev ' + (EV_CLASS[evidence] || 'H') + '">' +
      (SA.EV_ZH[evidence] || '') + '</span>';
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

  function root() { return document.getElementById('sa2'); }

  SA.canWrite = function () {
    var el = root();
    return !!el && el.getAttribute('data-can-write') === 'true';
  };

  SA.toast = function (msg, isErr) {
    if (typeof window.v2Toast === 'function') {
      window.v2Toast(msg, isErr ? 'error' : 'info');
    } else if (typeof window.y4Toast === 'function') {
      window.y4Toast(msg, isErr ? 'error' : 'info');
    }
  };

  function section(view) { return document.getElementById('sa2-' + view); }

  function writeUrl(view, params) {
    var q = ['view=' + encodeURIComponent(view)];
    if (params.report_id != null) q.push('report_id=' + encodeURIComponent(params.report_id));
    if (params.profile_id != null) q.push('profile_id=' + encodeURIComponent(params.profile_id));
    var url = location.pathname + '?' + q.join('&');
    if (location.pathname + location.search !== url) {
      history.replaceState(null, '', url);
    }
  }

  /* 切换视图：换显隐、同步 tab、写地址栏、调用视图的 show() */
  SA.go = function (view, params) {
    if (VIEWS.indexOf(view) < 0) view = 'overview';
    params = params || {};
    VIEWS.forEach(function (v) {
      var sec = section(v);
      if (sec) sec.hidden = (v !== view);
      var tab = document.getElementById('sa2-tab-' + v);
      if (tab) {
        tab.setAttribute('aria-selected', String(v === view));
        tab.setAttribute('tabindex', v === view ? '0' : '-1');
      }
    });
    writeUrl(view, params);
    var mod = SA.views[view];
    var sec = section(view);
    if (mod && typeof mod.show === 'function' && sec) mod.show(sec, params);
    window.scrollTo(0, 0);
  };

  function init() {
    var nav = document.getElementById('sa2-tabs');
    if (nav) {
      nav.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-view]');
        if (btn) SA.go(btn.getAttribute('data-view'));
      });
    }
    var q = new URLSearchParams(location.search);
    var params = {};
    if (q.get('report_id')) params.report_id = q.get('report_id');
    if (q.get('profile_id')) params.profile_id = q.get('profile_id');
    SA.go(q.get('view') || 'overview', params);
  }

  /* defer 脚本按文档顺序执行：等 DOMContentLoaded，四个模块都注册完再首屏路由 */
  if (document.readyState === 'complete') {
    init();
  } else {
    document.addEventListener('DOMContentLoaded', init);
  }
})();