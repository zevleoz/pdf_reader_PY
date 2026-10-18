/* =========================================================================
   6AM 启动模型主页面：六维地图 + 右侧行动面板
   数据源：GET /api/reports/<id>/six-am
     payload.profile    原始审计数据（答案、缺口、证据留痕）
     payload.view_model 行动卡展示数据（cards 固定 A1–A6 顺序）
   保存路径：
     POST /six-am/action-overrides  行动修订，就地更新，不生成新版本
     POST /six-am/answers           追问/缺口保存并重跑，生成新版本
   页面不渲染任何 ObstacleScore 或规则公式。
   ========================================================================= */
(function () {
  'use strict';

  var students = [];
  var reports = [];
  var payload = null;    // {profile_id, version, profile, versions, view_model, ...}
  var selectedDim = null;

  var $ = function (id) { return document.getElementById(id); };

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
  // "Autonomy 自主感"（英文在前，可能多词）→ 中文取末段；"稳固 Secure"（中文在前）→ 中文取首段
  function splitZhEn(label) {
    var s = String(label || '');
    var i = s.lastIndexOf(' ');
    if (i < 0) return { zh: s, en: '' };
    return { zh: s.slice(i + 1), en: s.slice(0, i) };
  }
  function zhFirst(label) {
    var s = String(label || '');
    var i = s.indexOf(' ');
    return i < 0 ? s : s.slice(0, i);
  }

  function profile() { return (payload && payload.profile) || {}; }
  function viewModel() { return (payload && payload.view_model) || {}; }
  function cards() { return viewModel().cards || []; }
  function cardOf(dim) {
    var found = null;
    cards().forEach(function (c) { if (c.dim === dim) found = c; });
    return found;
  }
  function summary() { return viewModel().summary || {}; }

  function stateClass(st) {
    return { Secure: 'st-secure', Watch: 'st-watch', 'At-Risk': 'st-atrisk', Blocked: 'st-blocked' }[st] || 'st-secure';
  }
  function evClass(c) {
    return c === 'Confirmed' ? 'sa-ev c' : (c === 'Hypothesis' ? 'sa-ev h' : 'sa-ev');
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

  // 默认选中：最高优先级非 Secure 维度（priority_order 首项）；无障碍时选中 A1
  function defaultDim() {
    var order = summary().priority_order || [];
    for (var i = 0; i < order.length; i++) {
      var c = cardOf(order[i]);
      if (c && c.dim !== 'A6' && c.state !== 'Secure') return c.dim;
    }
    return 'A1';
  }

  // ── 总渲染 ────────────────────────────────────────────────
  function renderAll() {
    var show = !!payload;
    $('sa-summary').hidden = !show;
    $('sa-main').hidden = !show;
    $('sa-evidence').hidden = !show;
    if (!show) {
      $('sa-version').innerHTML = '<option value="">版本</option>';
      $('sa-map-grid').innerHTML = '';
      $('sa-panel').innerHTML = '';
      return;
    }
    renderSummary();
    renderVersionSelect();
    renderMap();
    renderPanel();
    renderEvidenceLog();
  }

  function renderSummary() {
    var s = summary();
    var prof = profile();
    var st = s.student || {};
    var rv = prof.rule_version || {};
    var items = [
      '<span>学生：<b>' + esc(st.name || '—') + '</b></span>',
      '<span>年级：<b>' + esc(st.grade || '—') + '</b></span>',
      '<span>报告：<b>#' + esc(s.report_id || prof.report_id || '') + '</b></span>',
      '<span>规则版本：<b>' + esc(rv.label || 'default') + (rv.id ? '（id=' + rv.id + '）' : '') + '</b></span>',
      '<span>档案版本：<b>v' + esc(payload.version) + '</b></span>',
      '<span>生成时间：<b>' + esc(s.generated_at || prof.generated_at || '') + '</b></span>'
    ];
    var primary = s.primary_obstacle;
    if (primary && primary.dim) {
      var pc = cardOf(primary.dim);
      var pTitle = pc ? splitZhEn(pc.title).zh : primary.dim;
      items.push('<span>首要处理：<b>' + esc(primary.dim) + ' ' + esc(pTitle) + '</b></span>');
    }
    items.push('<span>待确认问题：<b>' + esc(s.open_question_count || 0) + '</b> 条</span>');
    (s.deferred || []).forEach(function (d) {
      if (d && d.dim) items.push('<span>长期目标：<b>' + esc(d.dim) + '</b></span>');
    });
    $('sa-summary-meta').innerHTML = items.join('');
    $('sa-summary-note').textContent = s.sequence_note || '';
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

  // ── 六维地图（固定 A1–A6 顺序）─────────────────────────────
  function prioBadge(c) {
    if (c.deferred) return '<span class="sa-prio deferred">长期目标</span>';
    if (c.priority_label) {
      return '<span class="sa-prio">' + esc(c.priority_label) +
        (c.priority_rank ? ' ' + esc(c.priority_rank) : '') + '</span>';
    }
    return '';
  }
  function stateBadge(c) {
    if (c.dim === 'A6') return '<span class="sa-badge st-secure">支持选择器</span>';
    return '<span class="sa-badge ' + stateClass(c.state) + '">' + esc(zhFirst(c.state_label)) + '</span>';
  }
  function evBadge(c) {
    if (!c.evidence_label) return '';
    return '<span class="' + evClass(c.evidence_state) + '">' + esc(c.evidence_label) + '</span>';
  }

  function renderMap() {
    var wrap = $('sa-map-grid');
    wrap.innerHTML = '';
    cards().forEach(function (c) {
      var name = splitZhEn(c.title);
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'sa-dim-card';
      btn.setAttribute('aria-pressed', c.dim === selectedDim ? 'true' : 'false');
      btn.setAttribute('data-dim', c.dim);
      btn.innerHTML =
        '<div class="sa-dim-card-top">' +
          '<div class="sa-dim-name">' + esc(c.dim) + ' · ' + esc(name.zh) +
            (name.en ? '<small>' + esc(name.en) + '</small>' : '') + '</div>' +
          '<div class="sa-dim-badges">' + stateBadge(c) + evBadge(c) + '</div>' +
        '</div>' +
        '<p class="sa-dim-headline">' + esc(c.headline) + '</p>' +
        '<div class="sa-dim-foot">' + prioBadge(c) +
          (c.manually_edited ? '<span class="sa-edited">已人工修订</span>' : '') + '</div>';
      btn.addEventListener('click', function () {
        selectedDim = c.dim;
        renderMap();
        renderPanel();
      });
      wrap.appendChild(btn);
    });
  }

  // ── 右侧行动面板 ──────────────────────────────────────────
  function listSection(title, items, emptyText) {
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

  function renderPanel() {
    var panel = $('sa-panel');
    var c = cardOf(selectedDim);
    if (!c) { panel.innerHTML = ''; return; }
    var name = splitZhEn(c.title);
    var html = '';

    // 头部：维度名 + 状态/证据/优先级
    html += '<div class="sa-panel-head">' +
      '<div class="sa-dim-name">' + esc(c.dim) + ' · ' + esc(name.zh) +
        (name.en ? '<small>' + esc(name.en) + '</small>' : '') + '</div>' +
      '<div class="sa-panel-badges">' + stateBadge(c) + evBadge(c) + prioBadge(c) +
        (c.manually_edited ? '<span class="sa-edited">已人工修订</span>' : '') + '</div>' +
      '</div>';

    // 判断
    html += '<section class="sa-sec"><h3>判断</h3>' +
      '<p class="sa-headline">' + esc(c.headline) + '</p>';
    if (c.deferred && c.deferred_reason) {
      html += '<p class="sa-note">长期目标：' + esc(c.deferred_reason) + '</p>';
    } else if (c.priority_reason) {
      html += '<p class="sa-note">' + esc(c.priority_reason) + '</p>';
    }
    html += '</section>';

    // Y4 事实 / 初筛假设 / 补充证据
    html += listSection('Y4 事实', c.y4_facts, '当前维度暂无 Y4 事实记录。');
    html += listSection('初筛假设', c.hypotheses, '无初筛假设。');
    html += listSection('补充证据（已确认依据）', c.confirmed_evidence, '尚无追问确认的补充证据。');

    // 行动编辑（下一步 / 避免事项）
    html += '<section class="sa-sec"><h3>下一步行动<span class="sa-sec-sub">每行一条，最多 ' +
      OVERRIDE_MAX_ITEMS + ' 条、每条 ' + OVERRIDE_MAX_LEN + ' 字</span></h3>' +
      '<label class="sa-visually-hidden" for="sa-next-actions">下一步行动（每行一条）</label>' +
      '<textarea id="sa-next-actions" class="sa-input sa-actions" rows="3" placeholder="每行一条行动建议">' +
      esc((c.next_actions || []).join('\n')) + '</textarea>' +
      '<h3 style="margin-block-start:12px">避免事项</h3>' +
      '<label class="sa-visually-hidden" for="sa-avoid-actions">避免事项（每行一条）</label>' +
      '<textarea id="sa-avoid-actions" class="sa-input sa-actions" rows="2" placeholder="每行一条避免事项">' +
      esc((c.avoid_actions || []).join('\n')) + '</textarea>' +
      '<div class="sa-save-row">' +
      '<button id="sa-save-actions" type="button" class="sa-btn">保存行动修订（不生成新版本）</button>' +
      '<span id="sa-save-actions-status" class="sa-status" role="status"></span></div>' +
      '<p class="sa-note">清空两个编辑框后保存，即恢复为系统生成的行动建议。</p></section>';

    // 待确认问题与答案
    html += questionsSection(c);

    // 维度相关缺口（A6 无缺口块，仅有上方支持偏好追问）
    html += gapsSection(c.dim);

    // 保存追问并重跑
    html += '<section class="sa-sec"><div class="sa-save-row">' +
      '<button id="sa-save-answers" type="button" class="sa-btn primary">保存追问并重跑（生成新版本）</button>' +
      '<span id="sa-save-answers-status" class="sa-status" role="status"></span></div>' +
      '<p class="sa-note">保存本维度的追问答案与缺口字段，重跑后生成新版本（旧版本保留，可在上方切换）。</p></section>';

    // 折叠审计区
    html += auditSection(c);

    panel.innerHTML = html;
    bindPanelEvents(c);
  }

  function questionsSection(c) {
    var ansMap = {};
    (profile().answers || []).forEach(function (a) { if (a && a.q) ansMap[a.q] = a; });
    var qs = c.questions || [];
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
    if (e.dim) return e.dim + ' state = ' + e.state;
    return JSON.stringify(e);
  }
  function effectText(eff) {
    if (!eff) return '';
    var parts = [];
    if (eff.state) parts.push('state → ' + eff.state);
    if (eff.subtype) parts.push('亚型 → ' + eff.subtype);
    if (eff.confidence) parts.push('confidence → ' + eff.confidence);
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

  // ── 页级证据留痕（折叠）───────────────────────────────────
  function renderEvidenceLog() {
    var log = profile().evidence_log || [];
    var html = '';
    if (!log.length) html = '<div class="sa-empty">暂无外部证据（仅 Y4 数据）。</div>';
    log.forEach(function (e) {
      var d = e.detail;
      var txt = typeof d === 'string' ? d : JSON.stringify(d);
      html += '<div class="sa-evidence-item"><span class="sa-tag">' + esc(e.source) + '</span> ' +
        '<span class="sa-tag">' + esc(e.kind) + '</span> ' + esc(txt) + '</div>';
    });
    $('sa-evidence-body').innerHTML = html;
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
    Array.prototype.forEach.call(document.querySelectorAll('#sa-panel .sa-ans-row'), function (row) {
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
    var q = function (sel) { return document.querySelector('#sa-panel ' + sel); };
    if (kinds.indexOf('family') >= 0) {
      var tags = [];
      Array.prototype.forEach.call(document.querySelectorAll('#sa-panel .sa-fam-tag'), function (c) {
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
      Array.prototype.forEach.call(document.querySelectorAll('#sa-panel .sa-subj-row'), function (row) {
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

  loadStudents();
})();
