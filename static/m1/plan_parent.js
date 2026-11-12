/* M1 家长版：两页 A4 的溢出检查（打印页与步③共用） */
(function () {
  'use strict';

  var PAGE_HEIGHT = 1123;

  function sectionAt(pg, limit) {
    var marks = [].slice.call(pg.querySelectorAll('[data-sec]'));
    var name = '';
    for (var i = 0; i < marks.length; i += 1) {
      if (marks[i].getBoundingClientRect().top <= limit + 1) {
        name = marks[i].getAttribute('data-sec') || name;
      } else {
        break;
      }
    }
    return name;
  }

  function measure(root) {
    var result = {fits: true, overflowPage: 0, section: '', pages: []};
    if (!root) return result;
    var pages = [].slice.call(root.querySelectorAll('.pg'));
    pages.forEach(function (pg, index) {
      var style = window.getComputedStyle(pg);
      var padTop = parseFloat(style.paddingTop) || 0;
      var padBottom = parseFloat(style.paddingBottom) || 0;
      var content = pg.scrollHeight - padTop - padBottom;
      var avail = PAGE_HEIGHT - padTop - padBottom;
      var over = content - avail;
      result.pages.push({index: index + 1, over: Math.round(over)});
      if (over > 2) {
        result.fits = false;
        if (!result.overflowPage) {
          result.overflowPage = index + 1;
          var limit = pg.getBoundingClientRect().top + padTop + avail;
          result.section = sectionAt(pg, limit);
        }
      }
    });
    return result;
  }

  window.M1ParentFit = {measure: measure, PAGE_HEIGHT: PAGE_HEIGHT};
})();
