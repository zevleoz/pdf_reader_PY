/* =========================================================================
   6AM 启动模型主页面
   信息架构：左侧按状态分组的六维导航（A1–A5 + A6 支持选择器），
             右侧为当前维度的“判断 / 依据 / 行动”三标签工作区。
   数据源：GET /api/reports/<id>/six-am
     payload.profile    原始审计数据（答案、缺口、证据留痕）
     payload.view_model 展示数据（cards 固定 A1–A6 顺序）
   保存路径：
     POST /six-am/action-overrides  行动修订，就地更新，不生成新版本
     POST /six-am/answers           追问/缺口保存并重跑，生成新版本
   页面不渲染分数、公式或内部排序。
   ========================================================================= */
(function () {
  'use strict';

  var students = [];
  var reports = [];
  var payload = null;    // {profile_id, version, profile, versions, view_model, ...}
  var selectedDim = null;
  var selectedTab = 'judgment';

  var $ = function (id) { return document.getElementById(id); };

  var TABS = ['judgment', 'evidence', 'action'];
  var DIM_ORDER = ['A1', 'A2', 'A3', 'A4', 'A5', 'A6'];

  // 左侧分组顺序固定；空分组不渲染。A6 单独作为“支持选择器”组。
  var GROUPS = [
    { state: 'Blocked', title: '阻塞 Blocked' },
    { state: 'At-Risk', title: '风险 At-Risk' },
    { state: 'Watch', title: '关注 Watch' },
    { state: 'Secure', title: '稳固 Secure' }
  ];

  // 四类缺口 → 维度：家长诉求 A1/A2，排期负荷 A3，学科状态 A4，标准化任务 A5；A6 无缺口块
  var GAP_BY_DIM = { A1: ['family'], A2: ['family'], A3: ['schedule'], A4: ['subject'], A5: ['standard'], A6: [] };
  var OVERRIDE_MAX_ITEMS = 8;
  var OVERRIDE_MAX_LEN = 300;

  // ── 基础工具 ──────────────────────────────────────────────
  function setStatus(msg, isErr) {
    var el = $('sa-status');
    el.textContent = msg || '';
    el.className = 'sa-status' + (isErr ? ' err' : '');
  }
  function api(url, opts) {
    return fetch(url, opts).then(function (r) {
      if (r.status === 403 || r.status === 401) { location.href = '/login?next=/six-am'; throw new Error('未登录'); }
      return r.json();
    });
  }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // 中英混排标签拆成主中文 + 小号英文：
  // "Autonomy 自主感"（英文在前）→ 自主感 / Autonomy
  // "风险 At-Risk"（中文在前）→ 风险 / At-Risk
  function splitLabel(label) {
    var s = String(label == null ? '' : label).trim();
    if (!s) return { zh: '', en: '' };
    var parts = s.split(/\s+/);
    if (parts.length === 1) return { zh: s, en: '' };
    if (/^[A-Za-z]/.test(parts[0])) {
      return { zh: parts[parts.length - 1], en: parts.slice(0, -1).join(' ') };
    }
    return { zh: parts[0], en: parts.slice(1).join(' ') };
  }
  function zhEn(label) {
    var p = splitLabel(label);
    return esc(p.zh) + (p.en ? ' <small>' + esc(p.en) + '</small>' : '');
  }

  function profile() { return (payload && payload.profile) || {}; }
  function viewModel() { return (payload && payload.view_model) || {}; }
  function cards() { return viewModel().cards || []; }
  function cardOf(dim) {
    var found = null;
    cards().forEach(function (c) { if (c.dim === dim) found = c; });
    return found;
  }

  function stateClass(c) {
    return { Secure: 'st-secure', Watch: 'st-watch', 'At-Risk': 'st-atrisk', Blocked: 'st-blocked' }[c.state] || 'st-secure';
  }
  function evClass(c) {
    return c === 'Confirmed' ? 'sa-ev c' : (c === 'Hypothesis' ? 'sa-ev h' : 'sa-ev');
  }

  function stateBadge(c) {
    if (c.dim === 'A6') {
      return '<span class="sa-badge st-a6">' + zhEn(c.state_label || '支持选择器') + '</span>';
    }
    return '<span class="sa-badge ' + stateClass(c) + '">' + zhEn(c.state_label) + '</span>';
  }
  function evBadge(c) {
    if (!c.evidence_label) return '';
    return '<span class="' + evClass(c.evidence_state) + '">' + zhEn(c.evidence_label) + '</span>';
  }
  function deferredBadge(c) {
    return c.deferred ? '<span class="sa-deferred">长期目标</span>' : '';
  }
  function editedBadge(c) {
    return c.manually_edited ? '<span class="sa-edited">已人工修订</span>' : '';
  }

  // ── 加载列表 ──────────────────────────────────────────────
  function loadStudents() {
    api('/api/students').then(function (j) {
      if (!j.ok) { setStatus(j.error || '加载学生失败', true); return; }
      students = j.students || [];
      var sel = $('sa-student');
      sel.innerHTML = '<option value="">选择学生</option>';
      students.forEach(function (s) {
        var o = document.createElement('option');
        o.value = s.id; o.textContent = s.name + (s.grade ? '（' + s.grade + '）' : '');
        sel.appendChild(o);
      });
      if (students.length === 1) { sel.value = String(students[0].id); loadReports(); }
    });
  }
  function loadReports() {
    var sid = $('sa-student').value;
    var sel = $('sa-report');
    sel.innerHTML = '<option value="">选择报告</option>';
    payload = null; selectedDim = null; renderAll();
    if (!sid) return;
    api('/api/students/' + sid + '/reports').then(function (j) {
      if (!j.ok) { setStatus(j.error || '加载报告失败', true); return; }
      reports = j.reports || [];
      reports.forEach(function (r) {
        var o = document.createElement('option');
        o.value = r.id; o.textContent = (r.report_date || '') + ' · #' + r.id;
        sel.appendChild(o);
      });
      if (reports.length) { sel.value = String(reports[0].id); loadProfile(); }
    });
  }
  function loadProfile(profileId) {
    var rid = $('sa-report').value;
    if (!rid) return;
    var url = '/api/reports/' + rid + '/six-am' + (profileId ? ('?profile_id=' + profileId) : '');
    setStatus('加载档案…');
    api(url).then(function (j) {
      if (!j.ok) {
        payload = null; selectedDim = null; renderAll();
        setStatus(j.error || '尚无 6AM 档案，可点击“重跑档案”生成。', true);
        return;
      }
      payload = j;
      if (!cardOf(selectedDim)) selectedDim = defaultDim();
      renderAll();
      setStatus('档案 v' + j.version + '（' + y4FmtDT(j.created_at) + '）');
    }).catch(function (e) { setStatus(String(e.message || e), true); });
  }

  // 默认选中第一个非空分组的第一项；全部稳固时即 A1。
  function cardsInState(state) {
    var out = [];
    DIM_ORDER.forEach(function (dim) {
      var c = cardOf(dim);
      if (c && c.dim !== 'A6' && c.state === state) out.push(c);
    });
    return out;
  }
  function defaultDim() {
    for (var i = 0; i < GROUPS.length; i++) {
      var items = cardsInState(GROUPS[i].state);
      if (items.length) return items[0].dim;
    }
    var first = null;
    DIM_ORDER.forEach(function (dim) {
      if (!first && dim !== 'A6' && cardOf(dim)) first = cardOf(dim);
    });
    return first ? first.dim : 'A6';
  }

  // ── 总渲染 ────────────────────────────────────────────────
  function renderAll() {
    var show = !!payload;
    $('sa-main').hidden = !show;
    if (!show) {
      $('sa-version').innerHTML = '<option value="">版本</option>';
      $('sa-nav').innerHTML = '';
      $('sa-workspace-head').innerHTML = '';
      TABS.forEach(function (t) {
        var panel = $('sa-panel-' + t);
        if (panel) { panel.innerHTML = ''; panel.hidden = true; }
      });
      return;
    }
    renderVersionSelect();
    if (!cardOf(selectedDim)) selectedDim = defaultDim();
    renderNav();
    renderWorkspace();
    setTab(selectedTab, false);
  }

  function renderVersionSelect() {
    var sel = $('sa-version');
    sel.innerHTML = '';
    (payload.versions || []).forEach(function (v) {
      var o = document.createElement('option');
      o.value = v.profile_id;
      o.textContent = 'v' + v.version + ' · ' + y4FmtDT(v.created_at);
      if (String(v.profile_id) === String(payload.profile_id)) o.selected = true;
      sel.appendChild(o);
    });
  }

  // ── 左侧：按状态分组的六维导航 ────────────────────────────
  function navItem(c) {
    var name = splitLabel(c.title);
    var current = c.dim === selectedDim;
    return '<button type="button" class="sa-nav-item" data-dim="' + esc(c.dim) + '"' +
      (current ? ' aria-current="true"' : '') + '>' +
      '<span class="sa-nav-name">' + esc(c.dim) + ' ' + esc(name.zh) +
        (name.en ? '<small>' + esc(name.en) + '</small>' : '') + '</span>' +
      '<span class="sa-nav-meta">' + stateBadge(c) + evBadge(c) + deferredBadge(c) + '</span>' +
      '</button>';
  }
  function navGroup(title, items) {
    var t = splitLabel(title);
    return '<div class="sa-nav-group">' +
      '<h2 class="sa-nav-group-title">' + esc(t.zh) +
        (t.en ? ' <small>' + esc(t.en) + '</small>' : '') + '</h2>' +
      '<div class="sa-nav-items">' + items.map(navItem).join('') + '</div>' +
      '</div>';
  }
  function renderNav() {
    var html = '';
    GROUPS.forEach(function (g) {
      var items = cardsInState(g.state);
      if (items.length) html += navGroup(g.title, items);
    });
    var a6 = cardOf('A6');
    if (a6) html += navGroup('支持选择器 A6', [a6]);
    $('sa-nav').innerHTML = html;
  }

  // 只切换选中态，不重建左栏 DOM：重建会让整列导航重绘一次，看起来像“闪一下”，
  // 同时会丢失悬停态与滚动位置。徽章/分组只在 renderAll 时随数据一起刷新。
  function syncNavSelection(dim) {
    Array.prototype.forEach.call(document.querySelectorAll('#sa-nav .sa-nav-item'), function (btn) {
      if (btn.getAttribute('data-dim') === dim) btn.setAttribute('aria-current', 'true');
      else btn.removeAttribute('aria-current');
    });
  }

  function selectDim(dim) {
    if (!dim || dim === selectedDim) return;
    selectedDim = dim;
    syncNavSelection(dim);
    renderWorkspace();
    setTab(selectedTab, false);
    var btn = document.querySelector('.sa-nav-item[data-dim="' + dim + '"]');
    // preventScroll：焦点落在左栏时不要把页面滚回导航顶部。
    if (btn) btn.focus({ preventScroll: true });
  }

  // ── 右侧：维度头 + 三标签 ─────────────────────────────────
  function renderWorkspace() {
    var c = cardOf(selectedDim);
    if (!c) {
      $('sa-workspace-head').innerHTML = '';
      TABS.forEach(function (t) { $('sa-panel-' + t).innerHTML = ''; });
      return;
    }
    renderWorkspaceHead(c);
    $('sa-panel-judgment').innerHTML = renderJudgment(c);
    $('sa-panel-evidence').innerHTML = renderEvidence(c);
    $('sa-panel-action').innerHTML = renderAction(c);
    bindPanelEvents(c);
  }

  function renderWorkspaceHead(c) {
    var name = splitLabel(c.title);
    $('sa-workspace-head').innerHTML =
      '<div class="sa-workspace-title">' + esc(c.dim) + ' · ' + esc(name.zh) +
        (name.en ? '<small>' + esc(name.en) + '</small>' : '') + '</div>' +
      '<div class="sa-workspace-badges">' + stateBadge(c) + evBadge(c) +
        deferredBadge(c) + editedBadge(c) + '</div>';
  }

  function setTab(name, focus) {
    if (TABS.indexOf(name) < 0) name = 'judgment';
    selectedTab = name;
    TABS.forEach(function (t) {
      var tab = $('sa-tab-' + t);
      var panel = $('sa-panel-' + t);
      var active = t === name;
      if (tab) {
        tab.setAttribute('aria-selected', active ? 'true' : 'false');
        tab.tabIndex = active ? 0 : -1;
      }
      if (panel) panel.hidden = !active;
    });
    if (focus) {
      var activeTab = $('sa-tab-' + name);
      if (activeTab) activeTab.focus();
    }
  }

  // ── 判断标签页 ────────────────────────────────────────────
  function evidenceExplanation(c) {
    var map = {
      Hypothesis: '当前判断来自 Y4 初筛，尚未经追问确认。',
      Supported: '已有补充证据支持，仍可在“依据”中继续确认。',
      Confirmed: '判断已由追问或外部证据确认。',
      Refuted: '原有判断已被追问否定。'
    };
    if (c.dim === 'A6') return '支持选择器，无证据状态。';
    if (!c.evidence_label) return '暂无证据状态记录。';
    var extra = map[c.evidence_state] || '';
    return zhEn(c.evidence_label) + (extra ? '：' + extra : '');
  }

  function renderJudgment(c) {
    var html = '';

    html += '<section class="sa-sec sa-sec-first">' +
      '<h3>证据状态</h3>' +
      '<p class="sa-judgment-evidence">' + evidenceExplanation(c) + '</p>' +
      '</section>';

    html += '<section class="sa-sec">' +
      '<h3>一句话判断</h3>' +
      '<p class="sa-headline">' + esc(c.headline || '') + '</p>' +
      '</section>';

    html += judgmentReason(c);
    html += judgmentQuestions(c);
    return html;
  }

  // 只呈现长期目标与跨维修正/备注；不展示内部排序原因。
  function judgmentReason(c) {
    var items = [];
    if (c.deferred && c.deferred_reason) items.push('长期目标：' + c.deferred_reason);
    ((c.audit || {}).cross_mods || []).forEach(function (m) {
      var action = String((m && m.action) || '');
      if (action) items.push('联动：' + action);
    });
    ((c.audit || {}).notes || []).forEach(function (n) {
      if (n) items.push('注：' + n);
    });

    var body;
    if (!items.length) {
      body = '<div class="sa-empty">本维度暂无额外联动说明；判断原因见上方证据状态与一句话判断。</div>';
    } else {
      body = '<ul class="sa-reason-list">' + items.map(function (t) {
        return '<li>' + esc(t) + '</li>';
      }).join('') + '</ul>';
    }
    return '<section class="sa-sec"><h3>当前判断原因 / 联动说明</h3>' + body + '</section>';
  }

  function judgmentQuestions(c) {
    var count = (c.questions || []).length;
    var label = c.dim === 'A6' ? '支持偏好追问' : '待确认问题';
    var text = label + '：<b>' + count + '</b> 条' +
      (count ? '，可在“依据”中录入答案。' : '。');
    var btn = count ?
      '<button type="button" class="sa-btn sa-mini" data-goto-tab="evidence">去“依据”录入</button>' : '';
    return '<section class="sa-sec"><h3>待确认问题</h3>' +
      '<div class="sa-inline sa-question-count"><span>' + text + '</span>' + btn + '</div></section>';
  }

  // ── 依据标签页 ────────────────────────────────────────────
  function listSection(title, items, emptyText, hideWhenEmpty) {
    if (hideWhenEmpty && (!items || !items.length)) return '';
    var html = '<section class="sa-sec"><h3>' + esc(title) + '</h3>';
    if (!items || !items.length) {
      html += '<div class="sa-empty">' + esc(emptyText) + '</div>';
    } else {
      html += '<ul class="sa-fact-list">';
      items.forEach(function (t) { html += '<li>' + esc(t) + '</li>'; });
      html += '</ul>';
    }
    return html + '</section>';
  }

  function renderEvidence(c) {
    var isA6 = c.dim === 'A6';
    var html = '';

    // A6 只渲染有数据的区块，不强行展示空白证据区。
    html += listSection('Y4 事实', c.y4_facts, '当前维度暂无 Y4 事实记录。', isA6);
    html += listSection('初筛假设', c.hypotheses, '无初筛假设。', isA6);
    html += listSection('补充证据 / 已确认依据', c.confirmed_evidence, '尚无追问确认的补充证据。', isA6);

    html += questionsSection(c, isA6);
    if (!isA6) html += gapsSection(c.dim);

    html += auditSection(c);
    html += evidenceLogSection(isA6);

    html += '<section class="sa-sec"><div class="sa-save-row">' +
      '<button id="sa-save-answers" type="button" class="sa-btn primary">保存追问并重跑（生成新版本）</button>' +
      '<span id="sa-save-answers-status" class="sa-status" role="status"></span></div>' +
      '<p class="sa-note">保存本维度的追问答案与缺口字段，重跑后生成新版本（旧版本保留，可在顶部切换）。</p>' +
      '</section>';

    return html;
  }

  function questionsSection(c, hideWhenEmpty) {
    var ansMap = {};
    (profile().answers || []).forEach(function (a) { if (a && a.q) ansMap[a.q] = a; });
    var qs = c.questions || [];
    if (hideWhenEmpty && !qs.length) return '';
    var title = c.dim === 'A6' ? '支持偏好追问与答案' : '待确认问题与答案';
    var html = '<section class="sa-sec"><h3>' + title + '</h3>';
    if (!qs.length) {
      html += '<div class="sa-empty">' +
        (c.dim === 'A6' ? '当前无支持偏好追问。' : '当前维度无待确认问题。') + '</div>';
    }
    qs.forEach(function (q) {
      var a = ansMap[q.id] || {};
      var basis = q.basis_rules || q.verify || [];
      html += '<div class="sa-ans-row" data-q="' + esc(q.id) + '">' +
        '<div class="sa-ans-q"><span class="qid">' + esc(q.id) + '</span>' + esc(q.ask) +
        '<div class="basis">验证目标：' + esc((q.verify || []).join('、')) +
        (basis.length ? ' · 依据 ' + esc(basis.join('、')) : '') + '</div></div>' +
        '<select class="sa-select sa-ans-result" aria-label="验证结果（' + esc(q.id) + '）">' +
        ['', 'confirm', 'partial', 'deny'].map(function (v) {
          var label = { '': '未填', confirm: '证实', partial: '部分证实', deny: '否定' }[v];
          return '<option value="' + v + '"' + (a.result === v ? ' selected' : '') + '>' + label + '</option>';
        }).join('') + '</select>' +
        '<input class="sa-input sa-ans-text" aria-label="答案记录（' + esc(q.id) + '）" ' +
        'placeholder="记录学生原话/要点（可选）" value="' + esc(a.text || '') + '">' +
        '</div>';
    });
    return html + '</section>';
  }

  // ── 四类缺口（按维度过滤）─────────────────────────────────
  function gapsSection(dim) {
    var kinds = GAP_BY_DIM[dim] || [];
    if (!kinds.length) return '';
    var g = profile().gaps || {};
    var html = '<section class="sa-sec"><h3>数据缺口（本维度相关）</h3>';
    kinds.forEach(function (k) {
      if (k === 'family') html += familyGapBlock(g.family_complaint || {});
      if (k === 'schedule') html += scheduleGapBlock(g.schedule || {});
      if (k === 'subject') html += subjectGapBlock(g.subject_status || []);
      if (k === 'standard') html += standardGapBlock(g.standard_task || {});
    });
    return html + '</section>';
  }

  function familyGapBlock(fam) {
    var tags = fam.tags || [];
    var html = '<fieldset class="sa-gap-block"><legend>家长诉求<span>R2.8 · 主诉标签 + 原文 + 来源</span></legend>';
    html += '<div class="sa-inline" style="margin-block-end:6px">' +
      ['无兴趣', '动力不足', '其他'].map(function (t) {
        return '<label class="sa-check"><input type="checkbox" class="sa-fam-tag" value="' + t + '"' +
          (tags.indexOf(t) >= 0 ? ' checked' : '') + '> ' + t + '</label>';
      }).join('') + '</div>';
    html += '<label class="sa-visually-hidden" for="sa-fam-text">主诉原文</label>' +
      '<textarea id="sa-fam-text" class="sa-input sa-fam-text" placeholder="主诉原文">' + esc(fam.text || '') + '</textarea>';
    html += '<div class="sa-inline" style="margin-block-start:6px">' +
      '<label class="sa-check" for="sa-fam-source">采集来源</label>' +
      '<select id="sa-fam-source" class="sa-select sa-fam-source">' +
      ['', '家长环节', '顾问记录'].map(function (v) {
        return '<option value="' + v + '"' + ((fam.source || '') === v ? ' selected' : '') + '>' + (v || '请选择') + '</option>';
      }).join('') + '</select></div></fieldset>';
    return html;
  }

  function scheduleGapBlock(sch) {
    var html = '<fieldset class="sa-gap-block"><legend>排期与负荷<span>R3.6 · 日程概要 + 自由时间 + 负荷评级</span></legend>';
    html += '<label class="sa-visually-hidden" for="sa-sch-overview">一周日程概要</label>' +
      '<textarea id="sa-sch-overview" class="sa-input sa-sch-overview" placeholder="一周日程概要（每天课程/活动时段数）">' +
      esc(sch.overview || '') + '</textarea>';
    html += '<div class="sa-inline" style="margin-block-start:6px">' +
      '<label class="sa-check" for="sa-sch-hours">自由时间（小时/周）</label>' +
      '<input id="sa-sch-hours" class="sa-input sa-sch-hours" type="number" min="0" step="1" style="inline-size:110px" ' +
      'value="' + esc(sch.free_hours_per_week == null ? '' : sch.free_hours_per_week) + '">' +
      '<label class="sa-check" for="sa-sch-load">负荷评级</label>' +
      '<select id="sa-sch-load" class="sa-select sa-sch-load">' +
      ['', '高', '中', '低'].map(function (v) {
        return '<option value="' + v + '"' + ((sch.load_level || '') === v ? ' selected' : '') + '>' + (v || '请选择') + '</option>';
      }).join('') + '</select></div></fieldset>';
    return html;
  }

  function subjectGapBlock(subj) {
    var html = '<fieldset class="sa-gap-block"><legend>学科状态<span>R4.9 · 学科 + 自评 + 实际 + 偏差方向</span></legend>';
    html += '<div id="sa-subj-rows"></div>';
    html += '<button class="sa-btn sa-mini" id="sa-subj-add" type="button" style="margin-block-start:6px">添加学科</button></fieldset>';
    pendingSubjects = Array.isArray(subj) ? subj : [];
    return html;
  }

  function standardGapBlock(st) {
    var html = '<fieldset class="sa-gap-block"><legend>标准化任务结果<span>R5.7 · 拆解与承诺测试 + 情绪反应</span></legend>';
    html += '<div class="sa-inline">' +
      '<label class="sa-visually-hidden" for="sa-st-form">任务形式</label>' +
      '<input id="sa-st-form" class="sa-input sa-st-form" style="flex:1;min-inline-size:180px" placeholder="任务形式" value="' + esc(st.form || '') + '">' +
      '<label class="sa-visually-hidden" for="sa-st-split">能否拆出步骤</label>' +
      '<select id="sa-st-split" class="sa-select sa-st-split">' + triOpts(st.can_split, ['能拆出有序步骤', '拆不出有序步骤'], '能否拆出步骤') + '</select>' +
      '<label class="sa-visually-hidden" for="sa-st-commit">能否承诺开始</label>' +
      '<select id="sa-st-commit" class="sa-select sa-st-commit">' + triOpts(st.can_commit, ['能承诺第一步与时间', '不能承诺'], '能否承诺开始') + '</select>' +
      '<label class="sa-visually-hidden" for="sa-st-emotion">情绪反应</label>' +
      '<select id="sa-st-emotion" class="sa-select sa-st-emotion">' +
      ['', '畏难', '烦躁', '无所谓', '正常'].map(function (v) {
        return '<option value="' + v + '"' + ((st.emotion || '') === v ? ' selected' : '') + '>' + (v ? '情绪：' + v : '情绪反应') + '</option>';
      }).join('') + '</select></div></fieldset>';
    return html;
  }

  function triOpts(val, labels, placeholder) {
    var opts = [['', placeholder], ['yes', labels[0]], ['no', labels[1]]];
    var cur = val === true ? 'yes' : (val === false ? 'no' : '');
    return opts.map(function (o) {
      return '<option value="' + o[0] + '"' + (cur === o[0] ? ' selected' : '') + '>' + o[1] + '</option>';
    }).join('');
  }
  function triVal(v) { return v === 'yes' ? true : (v === 'no' ? false : null); }

  // subjectGapBlock 先输出占位容器，行在 bindPanelEvents 阶段填充
  var pendingSubjects = [];
  function addSubjRow(r) {
    var wrap = $('sa-subj-rows');
    if (!wrap) return;
    var div = document.createElement('div');
    div.className = 'sa-subj-row';
    div.innerHTML =
      '<input class="sa-input sa-mini sj-name" placeholder="学科" aria-label="学科" value="' + esc(r.subject || '') + '">' +
      '<input class="sa-input sa-mini sj-self" placeholder="学生自评水平" aria-label="学生自评水平" value="' + esc(r.self_level || '') + '">' +
      '<input class="sa-input sa-mini sj-actual" placeholder="实际状态" aria-label="实际状态" value="' + esc(r.actual || '') + '">' +
      '<select class="sa-select sa-mini sj-gap" aria-label="偏差方向">' +
      [['', '偏差方向'], ['below', '自评低于实际'], ['equal', '自评等于实际'], ['above', '自评高于实际']].map(function (o) {
        return '<option value="' + o[0] + '"' + ((r.gap || '') === o[0] ? ' selected' : '') + '>' + o[1] + '</option>';
      }).join('') +
      '</select>' +
      '<button class="sa-btn sa-del" type="button" aria-label="删除该学科">×</button>';
    div.querySelector('.sa-del').addEventListener('click', function () { div.remove(); });
    wrap.appendChild(div);
  }

  // ── 折叠审计区 ────────────────────────────────────────────
  function evText(e) {
    if (!e || typeof e !== 'object') return String(e || '');
    if (e.point) {
      var s = e.point + ' = ' + (e.eval_value == null ? '' : e.eval_value);
      if (e.source) s += '（' + e.source + '）';
      if (e.bias) s += ' [' + e.bias + ']';
      return s;
    }
    if (e.order_value != null) return '排序：' + e.order_value + ' 第 ' + e.pos + ' 位（前 ' + e.top_n + '）';
    if (e.rule) return '依赖 ' + e.rule + ' 命中';
    if (e.evidence) return '证据 ' + e.evidence + ' = ' + e.value;
    if (e.predicate) return '谓词 ' + e.predicate;
    if (e.dim) return e.dim + ' 状态 = ' + e.state;
    return JSON.stringify(e);
  }
  function effectText(eff) {
    if (!eff) return '';
    var parts = [];
    if (eff.state) parts.push('状态 → ' + eff.state);
    if (eff.subtype) parts.push('亚型 → ' + eff.subtype);
    if (eff.confidence) parts.push('证据等级 → ' + eff.confidence);
    if (eff.escalate) parts.push(eff.escalate);
    if (eff.deescalate) parts.push('降一级');
    if (eff.flags) parts.push('标记：' + eff.flags.join('、'));
    (eff.support_ops || []).forEach(function (op) {
      parts.push('支持方向 ' + op.direction + (op.kind ? '（' + op.kind + '）' : ''));
    });
    return parts.join('；');
  }

  function auditSection(c) {
    var a = c.audit || {};
    var html = '<details class="sa-audit"><summary>规则审计（触发规则 / 跨维修正 / 标记，默认收拢）</summary>' +
      '<div class="sa-audit-body">';
    var any = false;

    (a.refuted_rules || []).forEach(function (r) {
      any = true;
      html += '<div class="sa-rule refuted"><span class="rid">' + esc(r.rule) + '</span> ' +
        '<span class="eff">' + esc(r.title || '') + '</span> ' +
        '<span class="sa-chip">' + esc(r.label || '被排除 Refuted') +
        (r.refuted_by ? '（被 ' + esc(r.refuted_by) + ' 否定）' : '') + '</span></div>';
    });
    (a.triggered_rules || []).forEach(function (t) {
      any = true;
      html += '<div class="sa-rule"><span class="rid">' + esc(t.id) + '</span> ' +
        '<span class="eff">' + esc(t.title || '') + '</span>';
      var eff = effectText(t.effect);
      if (eff) html += '<div class="eff">→ ' + esc(eff) + '</div>';
      (t.evidence || []).slice(0, 6).forEach(function (e) {
        html += '<div class="ev">· ' + esc(evText(e)) + '</div>';
      });
      html += '</div>';
    });
    (a.cross_mods || []).forEach(function (m) {
      any = true;
      html += '<div class="sa-xmod">跨维修正 <span class="sa-tag">' + esc(m.id) + '</span> ' + esc(m.action) + '</div>';
    });
    (a.flags || []).forEach(function (f) {
      any = true;
      html += '<span class="sa-chip">' + esc(f) + '</span>';
    });
    (a.notes || []).forEach(function (n) {
      any = true;
      html += '<div class="sa-note">注：' + esc(n) + '</div>';
    });
    // A6 支持排序（审计附件）
    var sr = a.support_ranking;
    if (sr && (sr.ranked || []).length) {
      any = true;
      html += '<div class="sa-note">支持排序：</div>';
      sr.ranked.forEach(function (item) {
        html += '<div class="sa-rule"><span class="rid">' + esc(item.direction) + '</span> ' +
          '<span class="eff">' + esc(item.fit_label || item.predicted_effectiveness || '') + '</span>' +
          ((item.basis_rules || []).length ? ' <span class="sa-tag">' + esc(item.basis_rules.join(',')) + '</span>' : '') +
          (item.cautions ? '<div class="ev">' + esc(item.cautions) + '</div>' : '') + '</div>';
      });
    }
    if (!any) html += '<div class="sa-empty">本维度无审计记录。</div>';
    return html + '</div></details>';
  }

  // ── 全档案证据留痕（放在“依据”标签折叠区）─────────────────
  function evidenceLogSection(hideWhenEmpty) {
    var log = profile().evidence_log || [];
    if (hideWhenEmpty && !log.length) return '';
    var html = '<details class="sa-audit sa-log"><summary>全档案证据留痕（追问 / 家长 / FT 录入原始记录）</summary>' +
      '<div class="sa-audit-body">';
    if (!log.length) {
      html += '<div class="sa-empty">暂无外部证据（仅 Y4 数据）。</div>';
    }
    log.forEach(function (e) {
      var d = e.detail;
      var txt = typeof d === 'string' ? d : JSON.stringify(d);
      html += '<div class="sa-evidence-item"><span class="sa-tag">' + esc(e.source) + '</span> ' +
        '<span class="sa-tag">' + esc(e.kind) + '</span> ' + esc(txt) + '</div>';
    });
    return html + '</div></details>';
  }

  // ── 行动标签页 ────────────────────────────────────────────
  function renderAction(c) {
    var html = '';

    html += '<section class="sa-sec sa-sec-first">' +
      '<h3>下一步行动<span class="sa-sec-sub">每行一条，最多 ' + OVERRIDE_MAX_ITEMS +
        ' 条、每条 ' + OVERRIDE_MAX_LEN + ' 字</span></h3>' +
      '<label class="sa-visually-hidden" for="sa-next-actions">下一步行动（每行一条）</label>' +
      '<textarea id="sa-next-actions" class="sa-input sa-actions" rows="3" placeholder="每行一条行动建议">' +
      esc((c.next_actions || []).join('\n')) + '</textarea>' +
      '</section>';

    html += '<section class="sa-sec">' +
      '<h3>避免事项<span class="sa-sec-sub">每行一条，最多 ' + OVERRIDE_MAX_ITEMS +
        ' 条、每条 ' + OVERRIDE_MAX_LEN + ' 字</span></h3>' +
      '<label class="sa-visually-hidden" for="sa-avoid-actions">避免事项（每行一条）</label>' +
      '<textarea id="sa-avoid-actions" class="sa-input sa-actions" rows="2" placeholder="每行一条避免事项">' +
      esc((c.avoid_actions || []).join('\n')) + '</textarea>' +
      '</section>';

    if (c.dim === 'A6') html += a6SupportBlock(c);

    html += '<section class="sa-sec"><div class="sa-save-row">' +
      '<button id="sa-save-actions" type="button" class="sa-btn">保存行动修订（不生成新版本）</button>' +
      '<span id="sa-save-actions-status" class="sa-status" role="status"></span></div>' +
      '<p class="sa-note">清空两个编辑框后保存，即恢复为系统生成的行动建议。</p></section>';

    return html;
  }

  function a6SupportBlock(c) {
    var next = c.next_actions || [];
    var avoid = c.avoid_actions || [];
    var nextHtml = next.length ? '<ul class="sa-fact-list">' + next.map(function (t) {
      return '<li>' + esc(t) + '</li>';
    }).join('') + '</ul>' : '<div class="sa-empty">暂无支持方向。</div>';
    var avoidHtml = avoid.length ? '<ul class="sa-fact-list">' + avoid.map(function (t) {
      return '<li>' + esc(t) + '</li>';
    }).join('') + '</ul>' : '<div class="sa-empty">暂无慎用 / 避免项。</div>';
    return '<section class="sa-sec"><h3>A6 支持方向与慎用/避免项' +
      '<span class="sa-sec-sub">当前系统生成，供编辑时对照</span></h3>' +
      '<div class="sa-a6-panel">' +
      '<div class="sa-a6-col"><h4>支持方向</h4>' + nextHtml + '</div>' +
      '<div class="sa-a6-col"><h4>慎用 / 避免</h4>' + avoidHtml + '</div>' +
      '</div></section>';
  }

  // ── 面板事件 ──────────────────────────────────────────────
  function bindPanelEvents(c) {
    var addBtn = $('sa-subj-add');
    if (addBtn) {
      addBtn.addEventListener('click', function () { addSubjRow({}); });
      pendingSubjects.forEach(function (r) { addSubjRow(r); });
      pendingSubjects = [];
    }
    var saveActionsBtn = $('sa-save-actions');
    if (saveActionsBtn) saveActionsBtn.addEventListener('click', saveActions);
    var saveAnswersBtn = $('sa-save-answers');
    if (saveAnswersBtn) saveAnswersBtn.addEventListener('click', saveAnswers);
  }

  // ── 保存：行动修订（不生成新版本）───────────────────────────
  function parseActionLines(text) {
    return String(text || '').split('\n').map(function (s) { return s.trim(); }).filter(Boolean);
  }
  function validateActions(next, avoid) {
    if (next.length > OVERRIDE_MAX_ITEMS || avoid.length > OVERRIDE_MAX_ITEMS) {
      return '每个列表最多 ' + OVERRIDE_MAX_ITEMS + ' 条';
    }
    var all = next.concat(avoid);
    for (var i = 0; i < all.length; i++) {
      if (all[i].length > OVERRIDE_MAX_LEN) return '单条最多 ' + OVERRIDE_MAX_LEN + ' 字';
    }
    return null;
  }
  function panelStatus(id, msg, isErr) {
    var el = $(id);
    if (!el) return;
    el.textContent = msg || '';
    el.className = 'sa-status' + (isErr ? ' err' : '');
  }
  function saveActions() {
    var c = cardOf(selectedDim);
    if (!c || !payload) return;
    var next = parseActionLines($('sa-next-actions').value);
    var avoid = parseActionLines($('sa-avoid-actions').value);
    var err = validateActions(next, avoid);
    if (err) { panelStatus('sa-save-actions-status', err, true); return; }
    var btn = $('sa-save-actions');
    btn.disabled = true;
    panelStatus('sa-save-actions-status', '保存中…');
    api('/api/reports/' + $('sa-report').value + '/six-am/action-overrides', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        profile_id: payload.profile_id, dim: c.dim,
        next_actions: next, avoid_actions: avoid
      })
    }).then(function (j) {
      if (!j.ok) {
        btn.disabled = false;
        panelStatus('sa-save-actions-status', j.error || '保存失败', true);
        return;
      }
      payload = j;
      renderAll();
      setStatus('行动修订已保存：' + c.dim + '，档案仍为 v' + j.version + '（不生成新版本）');
    }).catch(function (e) {
      btn.disabled = false;
      panelStatus('sa-save-actions-status', String(e.message || e), true);
    });
  }

  // ── 保存：追问答案 + 缺口 → 重跑（新版本）────────────────────
  // answers 为整表替换语义：以档案中已有答案为底，叠加本面板当前维度的编辑，
  // 避免只提交当前维度时清空其他维度已录答案。
  function mergedAnswers() {
    var map = {};
    (profile().answers || []).forEach(function (a) {
      if (a && a.q) map[a.q] = { q: a.q, result: a.result, text: a.text || '' };
    });
    Array.prototype.forEach.call(document.querySelectorAll('#sa-panel-evidence .sa-ans-row'), function (row) {
      var q = row.getAttribute('data-q');
      var result = row.querySelector('.sa-ans-result').value;
      var text = row.querySelector('.sa-ans-text').value.trim();
      if (result || text) map[q] = { q: q, result: result || 'partial', text: text };
      else delete map[q];
    });
    return Object.keys(map).map(function (k) { return map[k]; });
  }

  // 只采集当前维度渲染出的缺口块；其余维度缺口由后端从旧档案恢复合并
  function collectGapsFor(dim) {
    var gaps = {};
    var kinds = GAP_BY_DIM[dim] || [];
    var q = function (sel) { return document.querySelector('#sa-panel-evidence ' + sel); };
    if (kinds.indexOf('family') >= 0) {
      var tags = [];
      Array.prototype.forEach.call(document.querySelectorAll('#sa-panel-evidence .sa-fam-tag'), function (c) {
        if (c.checked) tags.push(c.value);
      });
      gaps.family_complaint = {
        tags: tags,
        text: q('.sa-fam-text').value.trim(),
        source: q('.sa-fam-source').value
      };
    }
    if (kinds.indexOf('schedule') >= 0) {
      var hoursVal = q('.sa-sch-hours').value;
      gaps.schedule = {
        overview: q('.sa-sch-overview').value.trim(),
        free_hours_per_week: hoursVal === '' ? null : Number(hoursVal),
        load_level: q('.sa-sch-load').value
      };
    }
    if (kinds.indexOf('subject') >= 0) {
      var rows = [];
      Array.prototype.forEach.call(document.querySelectorAll('#sa-panel-evidence .sa-subj-row'), function (row) {
        var name = row.querySelector('.sj-name').value.trim();
        if (!name) return;
        rows.push({
          subject: name,
          self_level: row.querySelector('.sj-self').value.trim(),
          actual: row.querySelector('.sj-actual').value.trim(),
          gap: row.querySelector('.sj-gap').value
        });
      });
      gaps.subject_status = rows;
    }
    if (kinds.indexOf('standard') >= 0) {
      gaps.standard_task = {
        form: q('.sa-st-form').value.trim(),
        can_split: triVal(q('.sa-st-split').value),
        can_commit: triVal(q('.sa-st-commit').value),
        emotion: q('.sa-st-emotion').value
      };
    }
    return gaps;
  }

  function saveAnswers() {
    var c = cardOf(selectedDim);
    if (!c || !payload) return;
    var btn = $('sa-save-answers');
    btn.disabled = true;
    panelStatus('sa-save-answers-status', '保存并重跑中…');
    api('/api/reports/' + $('sa-report').value + '/six-am/answers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answers: mergedAnswers(), gaps: collectGapsFor(c.dim) })
    }).then(function (j) {
      if (!j.ok) {
        btn.disabled = false;
        panelStatus('sa-save-answers-status', j.error || '保存失败', true);
        return;
      }
      payload = j;
      if (!cardOf(selectedDim)) selectedDim = defaultDim();
      renderAll();
      setStatus('已生成新版本 v' + j.version + '（' + y4FmtDT(j.created_at) + '），追问与缺口已并入档案');
    }).catch(function (e) {
      btn.disabled = false;
      panelStatus('sa-save-answers-status', String(e.message || e), true);
    });
  }

  // ── 其他动作 ──────────────────────────────────────────────
  function rerun() {
    var rid = $('sa-report').value;
    if (!rid) { setStatus('请先选择报告', true); return; }
    var btn = $('sa-rerun');
    btn.disabled = true; setStatus('重跑中…');
    api('/api/reports/' + rid + '/six-am/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload ? { profile_id: payload.profile_id } : {})
    }).then(function (j) {
      btn.disabled = false;
      if (!j.ok) { setStatus(j.error || '重跑失败', true); return; }
      payload = j;
      if (!cardOf(selectedDim)) selectedDim = defaultDim();
      renderAll();
      setStatus('档案 v' + j.version + '（' + y4FmtDT(j.created_at) + '）');
    }).catch(function (e) { btn.disabled = false; setStatus(String(e.message || e), true); });
  }

  function downloadJSON() {
    var rid = $('sa-report').value;
    if (!rid || !payload) { setStatus('请先加载档案', true); return; }
    api('/api/reports/' + rid + '/six-am/json?profile_id=' + payload.profile_id).then(function (j) {
      if (!j.ok) { setStatus(j.error || '导出失败', true); return; }
      var blob = new Blob([JSON.stringify(j.json, null, 2)], { type: 'application/json' });
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = j.filename || '6am.json';
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(a.href);
    });
  }

  // ── 标签切换（鼠标 + 左右方向键）────────────────────────────
  function initTabs() {
    TABS.forEach(function (t) {
      var tab = $('sa-tab-' + t);
      tab.addEventListener('click', function () { setTab(t, false); });
    });
    var tablist = document.querySelector('.sa-tabs');
    tablist.addEventListener('keydown', function (e) {
      var idx = TABS.indexOf(selectedTab);
      var next = null;
      if (e.key === 'ArrowRight') next = (idx + 1) % TABS.length;
      else if (e.key === 'ArrowLeft') next = (idx - 1 + TABS.length) % TABS.length;
      else if (e.key === 'Home') next = 0;
      else if (e.key === 'End') next = TABS.length - 1;
      if (next == null) return;
      e.preventDefault();
      setTab(TABS[next], true);
    });
    // “去依据录入”等跨标签跳转；不重绘面板，避免丢失已输入内容。
    $('sa-workspace').addEventListener('click', function (e) {
      var btn = e.target.closest ? e.target.closest('[data-goto-tab]') : null;
      if (btn) setTab(btn.getAttribute('data-goto-tab'), true);
    });
  }

  // ── 事件绑定 ──────────────────────────────────────────────
  $('sa-student').addEventListener('change', loadReports);
  $('sa-report').addEventListener('change', function () { selectedDim = null; loadProfile(); });
  $('sa-version').addEventListener('change', function () {
    if ($('sa-version').value) loadProfile($('sa-version').value);
  });
  $('sa-rerun').addEventListener('click', rerun);
  $('sa-json').addEventListener('click', downloadJSON);
  $('sa-docx').addEventListener('click', function () {
    var rid = $('sa-report').value;
    if (!rid || !payload) { setStatus('请先加载档案', true); return; }
    window.open('/api/reports/' + rid + '/six-am/docx?profile_id=' + payload.profile_id, '_blank');
  });
  $('sa-nav').addEventListener('click', function (e) {
    var btn = e.target.closest ? e.target.closest('.sa-nav-item') : null;
    if (btn) selectDim(btn.getAttribute('data-dim'));
  });

  initTabs();
  loadStudents();
})();
