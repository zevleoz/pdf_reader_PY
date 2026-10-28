/* 6AM v0.6 · 规则：模型里的六张思维导图（只读）+ 下载 MD。 */
(function () {
  'use strict';

  var SA = window.SA;

  SA.views.rules = {
    show: function (el) {
      el.innerHTML = '<p class="sub">加载中…</p>';
      SA.loadModel().then(function (model) {
        var h = '<div class="rules-head"><div><h1>规则</h1><p class="sub">规则版本 ' +
          SA.esc(model.version || '') + ' · ' + SA.esc(model.date || '') + '</p></div>' +
          '<span class="spacer"></span>' +
          '<a class="btn" href="/api/six-am/model.md" download>下载思维导图 MD</a></div>' +
          '<div class="rules-list">';
        (model.dims || []).forEach(function (dim) {
          h += '<section class="card mmcard">' + SA.mindmap.dim(model, dim.id, null) + '</section>';
        });
        h += '<section class="card mmcard">' + SA.mindmap.a6(model, null) + '</section></div>';
        el.innerHTML = h;
      }).catch(function (err) {
        SA.toast(err.message, true);
        el.innerHTML = '<div class="card empty"><span>' + SA.esc(err.message) + '</span></div>';
      });
    }
  };
})();
