/* =========================================================================
   Y4 综合测评 — App Shell 脚本（侧边导航 + 内联搜索 + 悬停展开）
   无依赖 vanilla JS，以 defer 方式加载；仅在含 [data-app-shell]
   挂载点的页面上生效。设计令牌见 templates/style.css 与 app_shell.css。
   ========================================================================= */
(function () {
  'use strict';

  if (window.__Y4_SHELL__) return;
  window.__Y4_SHELL__ = true;

  /* ---------- 图标（lucide 风格描边 SVG） ---------- */
  function svg(inner, size) {
    size = size || 18;
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="' + size + '" height="' + size + '" aria-hidden="true">' + inner + '</svg>';
  }

  var ICONS = {
    file: '<path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    chart: '<path d="M18 20V10"/><path d="M12 20V4"/><path d="M6 20v-6"/>',
    calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/>',
    clipboard: '<rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="m9 14 2 2 4-4"/>',
    mic: '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><path d="M12 19v3"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
    flask: '<path d="M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2"/><path d="M8.5 2h7"/><path d="M7 16h10"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    collapse: '<path d="m11 17-5-5 5-5"/><path d="m18 17-5-5 5-5"/>',
    logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
    shield: '<path d="M12 22s8-3.5 8-10V5l-8-3-8 3v7c0 6.5 8 10 8 10z"/>'
  };

  var MENU_ICON = '<line x1="4" y1="6" x2="20" y2="6"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="18" x2="20" y2="18"/>';

  /* ---------- 导航定义 ---------- */
  var NAV = [
    { title: '工作台', items: [
      { label: '报告生成', href: '/generate', icon: 'file' },
      { label: '学生档案', href: '/students', icon: 'users' },
      { label: '数据总览', href: '/dashboard', icon: 'chart' }
    ] },
    { title: '预约中心', items: [
      { label: '预约测评', href: '/booking', icon: 'calendar' },
      { label: '预约管理', href: '/admin/bookings', icon: 'clipboard' }
    ] },
    { title: '解读', items: [
      { label: '解读会纪要', href: '/transcript', icon: 'mic' }
    ] },
    { title: '内部工具', items: [
      { label: '内部下载', href: '/internal', icon: 'download' },
      { label: 'Prompt Lab', href: '/prompt-lab', icon: 'flask' }
    ] }
  ];

  var KBD_HINT = /Mac|iPhone|iPad/.test(navigator.platform || '') ? '⌘K' : 'Ctrl K';

  /* ---------- 状态与元素 ---------- */
  var sidebar = null;
  var overlay = null;
  var hamburger = null;
  var collapseBtn = null;
  var footerEl = null;
  var searchInput = null;
  var hoverTimer = null;
  var mobileMq = window.matchMedia('(max-width: 1023px)');

  /* ---------- 初始化 ---------- */
  function init() {
    var mount = document.querySelector('[data-app-shell]');
    if (!mount) return;

    document.body.classList.add('y4-has-shell');

    var saved = null;
    try { saved = localStorage.getItem('y4.sidebar.collapsed'); } catch (e) { /* ignore */ }
    if (saved === '1') document.body.classList.add('y4-collapsed');

    buildHamburger();
    buildSidebar();
    buildOverlay();
    setActive();
    bindGlobalKeys();
    loadFooter();
    bindHoverExpand();
  }

  /* ---------- 构建 DOM ---------- */
  function buildHamburger() {
    hamburger = document.createElement('button');
    hamburger.type = 'button';
    hamburger.className = 'y4-hamburger';
    hamburger.setAttribute('aria-label', '打开导航');
    hamburger.setAttribute('aria-expanded', 'false');
    hamburger.innerHTML = svg(MENU_ICON, 18);
    hamburger.addEventListener('click', openDrawer);
    document.body.appendChild(hamburger);
  }

  function buildSidebar() {
    sidebar = document.createElement('aside');
    sidebar.className = 'y4-sidebar';

    var html = '';
    html += '<a class="y4-brand" href="/"><span class="y4-logo-chip"><img src="/branding/logo_color.png" alt=""></span>';
    html += '<span class="y4-brand-text-wrap"><span class="y4-brand-name">凭远教育</span><span class="y4-brand-sub">Y4 综合测评</span></span></a>';
    html += '<button type="button" class="y4-collapse" aria-label="收起导航">' + svg(ICONS.collapse, 18) + '</button>';
    html += '<div class="y4-search-box">';
    html += svg(ICONS.search, 16);
    html += '<input type="text" id="y4SearchInput" placeholder="搜索页面…" autocomplete="off" spellcheck="false">';
    html += '<kbd class="y4-kbd">' + KBD_HINT + '</kbd>';
    html += '</div>';
    html += '<nav class="y4-nav">';
    NAV.forEach(function (group) {
      html += '<div class="y4-nav-group" data-group="' + group.title + '">';
      html += '<div class="y4-group-title">' + group.title + '</div>';
      group.items.forEach(function (item) {
        html += '<a class="y4-item" href="' + item.href + '" data-label="' + item.label + '" data-group="' + group.title + '">' +
          '<span class="y4-item-icon">' + svg(ICONS[item.icon], 18) + '</span>' +
          '<span class="y4-item-label">' + item.label + '</span></a>';
      });
      html += '</div>';
    });
    html += '</nav>';
    html += '<div class="y4-footer" id="y4Footer"></div>';
    sidebar.innerHTML = html;

    var logoImg = sidebar.querySelector('.y4-logo-chip img');
    if (logoImg) logoImg.addEventListener('error', function () { logoImg.remove(); });

    collapseBtn = sidebar.querySelector('.y4-collapse');
    collapseBtn.addEventListener('click', onCollapseClick);

    sidebar.addEventListener('click', function (e) {
      var link = e.target && e.target.closest ? e.target.closest('a') : null;
      if (link) closeDrawer();
    });

    searchInput = sidebar.querySelector('#y4SearchInput');
    searchInput.addEventListener('input', onSearchInput);

    document.body.appendChild(sidebar);
  }

  function buildOverlay() {
    overlay = document.createElement('div');
    overlay.className = 'y4-overlay';
    overlay.addEventListener('click', closeDrawer);
    document.body.appendChild(overlay);
  }

  /* ---------- 当前页高亮 ---------- */
  function setActive() {
    var p = location.pathname.replace(/\/+$/, '') || '/';
    var items = sidebar.querySelectorAll('.y4-item[href]');
    Array.prototype.forEach.call(items, function (el) {
      var href = el.getAttribute('href');
      if (!href) return;
      if (p === href || p.indexOf(href + '/') === 0) {
        el.classList.add('y4-active');
        el.setAttribute('aria-current', 'page');
      }
    });
  }

  /* ---------- 折叠 ---------- */
  function onCollapseClick() {
    if (mobileMq.matches) { closeDrawer(); return; }
    var collapsed = document.body.classList.toggle('y4-collapsed');
    try { localStorage.setItem('y4.sidebar.collapsed', collapsed ? '1' : '0'); } catch (e) { /* ignore */ }
    if (!collapsed) sidebar.classList.remove('y4-hover-expand');
  }

  /* ---------- 悬停展开（折叠态 + 桌面端） ---------- */
  function bindHoverExpand() {
    sidebar.addEventListener('mouseenter', function () {
      if (!document.body.classList.contains('y4-collapsed')) return;
      if (mobileMq.matches) return;
      if (hoverTimer) { clearTimeout(hoverTimer); hoverTimer = null; }
      sidebar.classList.add('y4-hover-expand');
    });
    sidebar.addEventListener('mouseleave', function () {
      if (!document.body.classList.contains('y4-collapsed')) return;
      if (mobileMq.matches) return;
      if (hoverTimer) clearTimeout(hoverTimer);
      hoverTimer = setTimeout(function () {
        sidebar.classList.remove('y4-hover-expand');
        hoverTimer = null;
      }, 200);
    });
  }

  /* ---------- 内联搜索过滤 ---------- */
  function onSearchInput() {
    var q = searchInput.value.trim().toLowerCase();
    var groups = sidebar.querySelectorAll('.y4-nav-group');
    Array.prototype.forEach.call(groups, function (group) {
      var items = group.querySelectorAll('.y4-item');
      var visible = 0;
      Array.prototype.forEach.call(items, function (item) {
        if (!q) {
          item.style.display = '';
          visible++;
        } else {
          var hay = (item.getAttribute('data-label') + ' ' + item.getAttribute('data-group') + ' ' + item.getAttribute('href')).toLowerCase();
          if (hay.indexOf(q) !== -1) {
            item.style.display = '';
            visible++;
          } else {
            item.style.display = 'none';
          }
        }
      });
      var title = group.querySelector('.y4-group-title');
      if (title) title.style.display = visible > 0 ? '' : 'none';
    });
  }

  /* ---------- 移动端抽屉 ---------- */
  function openDrawer() {
    sidebar.classList.add('y4-open');
    overlay.classList.add('y4-show');
    hamburger.setAttribute('aria-expanded', 'true');
  }

  function closeDrawer() {
    if (!sidebar) return;
    sidebar.classList.remove('y4-open');
    overlay.classList.remove('y4-show');
    if (hamburger) hamburger.setAttribute('aria-expanded', 'false');
  }

  /* ---------- 底部：管理员状态 ---------- */
  function loadFooter() {
    footerEl = sidebar.querySelector('#y4Footer');
    fetch('/api/admin/check')
      .then(function (r) { return r.json(); })
      .then(function (d) { renderFooter(!!(d && d.is_admin)); })
      .catch(function () { renderFooter(false); });
  }

  function renderFooter(isAdmin) {
    if (!footerEl) return;
    if (isAdmin) {
      footerEl.innerHTML =
        '<div class="y4-admin-chip">' + svg(ICONS.shield, 14) + '<span class="y4-footer-text">管理员</span></div>' +
        '<button type="button" class="y4-logout">' + svg(ICONS.logout, 15) + '<span class="y4-footer-text">登出</span></button>';
      footerEl.querySelector('.y4-logout').addEventListener('click', function () {
        fetch('/api/admin/logout', { method: 'POST' })
          .then(function () { window.location.href = '/login'; })
          .catch(function () { window.location.href = '/login'; });
      });
    } else {
      footerEl.innerHTML = '<a class="y4-login-link" href="/login">管理员登录</a>';
    }
  }

  /* ---------- 全局快捷键 ---------- */
  function bindGlobalKeys() {
    document.addEventListener('keydown', function (e) {
      if (e.key && (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        if (document.body.classList.contains('y4-collapsed') && !mobileMq.matches) {
          sidebar.classList.add('y4-hover-expand');
        }
        searchInput.focus();
        searchInput.select();
        return;
      }
      if (e.key === 'Escape') {
        if (document.activeElement === searchInput) {
          searchInput.value = '';
          searchInput.blur();
          onSearchInput();
          return;
        }
        closeDrawer();
        return;
      }
    });
  }

  /* ---------- 启动 ---------- */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
