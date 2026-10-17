/* Y4 平台 2.0 — ⌘K 命令面板（Agent H：docs/agent_instructions/08-global-interaction-layer.md 5.4）
   依赖：
     - Alpine.js 3（增强交互；缺席时本文件不产生任何效果，页面保持完整可读）
     - 模板 _command_palette.html 注入的 window.Y4_CMDK_ROLE / window.Y4_CMDK_ICONS
   契约：
     - ⌘K / Ctrl+K 打开，Esc 关闭，↑↓ 导航，Enter 执行，点击遮罩关闭
     - 命令为前端常量数组（按角色过滤），学生搜索走 GET /api/students/search（250ms 防抖）
     - reduced-motion 下不播放面板缩放/位移动画（对应 CSS 侧同名媒体查询） */
(function () {
  'use strict';

  var COMMANDS = [
    { group: '前往', label: '新建报告生成', hint: '上传 PDF 生成 Y4 报告', href: '/generate', icon: 'file', roles: ['admin', 'advisor'] },
    { group: '前往', label: '去工作台', hint: '', href: '/workspace', icon: 'grid' },
    { group: '前往', label: '学生档案', hint: '', href: '/students', icon: 'users' },
    { group: '前往', label: '问卷题库', hint: '', href: '/questionnaires/bank', icon: 'book', roles: ['admin', 'advisor'] },
    { group: '前往', label: '数据总览', hint: '', href: '/insights/dashboard', icon: 'chart' },
    { group: '前往', label: 'Y4 研判', hint: '', href: '/insights/y4-signals', icon: 'radar' },
    { group: '前往', label: '6AM 启动模型', hint: '', href: '/insights/six-am', icon: 'target' },
    { group: '前往', label: '预约管理', hint: '', href: '/tools/bookings', icon: 'calendar', roles: ['admin', 'advisor'] },
    { group: '前往', label: '解读会纪要', hint: '', href: '/tools/transcript', icon: 'mic', roles: ['admin', 'advisor'] },
    { group: '管理', label: '用户管理', hint: '', href: '/system/users', icon: 'shield', roles: ['admin'] }
  ];
  window.Y4_COMMANDS = COMMANDS;

  function prefersReducedMotion() {
    return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  window.commandPalette = function () {
    var role = window.Y4_CMDK_ROLE || '';
    var icons = window.Y4_CMDK_ICONS || {};
    var commands = COMMANDS.filter(function (c) {
      return !c.roles || c.roles.indexOf(role) !== -1;
    });

    return {
      open: false,
      ready: false,
      q: '',
      selected: 0,
      total: 0,
      loading: false,
      groups: [],
      students: [],
      reduced: prefersReducedMotion(),

      init: function () {
        var self = this;
        this.rebuild();
        // 输入即时过滤命令 + 结果到达后重排（学生搜索另行 250ms 防抖）
        this.$watch('q', function () { self.rebuild(); });
        window.addEventListener('keydown', function (e) {
          var k = e.key || '';
          if ((e.metaKey || e.ctrlKey) && (k === 'k' || k === 'K')) {
            e.preventDefault();
            self.toggle();
          } else if (k === 'Escape' && self.open) {
            e.preventDefault();
            self.close();
          }
        });
        window.addEventListener('y4a-cmdk-open', function () { self.openPalette(); });
      },

      toggle: function () { this.open ? this.close() : this.openPalette(); },

      openPalette: function () {
        var self = this;
        if (this.open) { this.focusInput(); return; }
        this.open = true;
        this.ready = false;
        this.q = '';
        this.students = [];
        this.selected = 0;
        this.rebuild();
        this.$nextTick(function () {
          self.focusInput();
          self.ready = true;
        });
      },

      close: function () {
        this.open = false;
        this.ready = false;
        this.q = '';
        this.students = [];
        this.groups = [];
        this.total = 0;
        this.selected = 0;
      },

      focusInput: function () {
        var el = this.$refs && this.$refs.cmdkInput;
        if (el) { el.focus(); if (el.select) { el.select(); } }
      },

      rowIcon: function (it) {
        if (it.type === 'student') { return icons.users || icons.dot || ''; }
        return icons[it.icon] || icons.dot || '';
      },

      /* 学生搜索：≥1 字符，防抖由模板 @input.debounce.250ms 触发 */
      searchStudents: function () {
        var self = this;
        var kw = (this.q || '').trim();
        if (kw.length < 1) {
          this.students = [];
          this.loading = false;
          return;
        }
        this.loading = true;
        fetch('/api/students/search?q=' + encodeURIComponent(kw), { credentials: 'same-origin' })
          .then(function (r) { return r.json(); })
          .then(function (res) { self.students = (res && res.students) || []; })
          .catch(function () { self.students = []; })
          .then(function () {
            self.loading = false;
            self.selected = 0;
            self.rebuild();
          });
      },

      rebuild: function () {
        var q = (this.q || '').trim().toLowerCase();
        var groups = [];
        var buckets = {};
        var order = [];
        commands.forEach(function (c) {
          var hay = (c.label + ' ' + (c.group || '') + ' ' + (c.hint || '')).toLowerCase();
          if (q && hay.indexOf(q) === -1) { return; }
          var g = c.group || '命令';
          if (!buckets[g]) { buckets[g] = []; order.push(g); }
          buckets[g].push({ type: 'command', label: c.label, hint: c.hint || '', href: c.href, icon: c.icon });
        });
        order.forEach(function (g) { groups.push({ title: g, items: buckets[g] }); });
        if (q && this.students.length) {
          groups.push({ title: '学生', items: this.students.map(function (s) {
            var hint = [s.student_code, s.school, s.advisor_name]
              .filter(function (x) { return x; }).join(' · ');
            return { type: 'student', label: s.name, hint: hint, code: s.student_code };
          }) });
        }
        var i = 0;
        groups.forEach(function (grp) { grp.items.forEach(function (it) { it.idx = i++; }); });
        this.groups = groups;
        this.total = i;
        if (this.selected >= i) { this.selected = 0; }
      },

      move: function (delta) {
        if (!this.total) { return; }
        var n = this.selected + delta;
        if (n < 0) { n = this.total - 1; }
        if (n >= this.total) { n = 0; }
        this.selected = n;
      },

      runSelected: function () {
        var row = this.findRow(this.selected);
        if (row) { this.run(row); }
      },

      findRow: function (idx) {
        for (var gi = 0; gi < this.groups.length; gi++) {
          var items = this.groups[gi].items;
          for (var ii = 0; ii < items.length; ii++) {
            if (items[ii].idx === idx) { return items[ii]; }
          }
        }
        return null;
      },

      run: function (it) {
        if (!it) { return; }
        var href = it.type === 'student'
          ? ('/students/' + encodeURIComponent(it.code || ''))
          : it.href;
        if (href) {
          this.close();
          window.location.href = href;
        }
      }
    };
  };

  /* 顶栏触发入口与全局快捷键同效 */
  window.y4OpenCmdk = function () {
    window.dispatchEvent(new CustomEvent('y4a-cmdk-open'));
  };
})();
