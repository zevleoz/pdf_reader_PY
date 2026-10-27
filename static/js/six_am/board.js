/* 6AM 规则板 · 指标映射 / 严重度 / A6 支持，含预览影响、草稿与发布。 */
(function () {
  'use strict';

  var root = document.getElementById('sab');
  if (!root) { return; }

  var ST_CLASS = { Secure: 'S', Watch: 'W', 'At-Risk': 'R', Blocked: 'B' };
  var ST_ZH = { Secure: '稳固', Watch: '关注', 'At-Risk': '风险', Blocked: '阻塞' };

  /* 规则板不加载 common.js（其首屏路由会改写地址栏），本地补同一套工具 */
  var SA = window.SA || {
    esc: function (s) {
      return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
      });
    },
    pill: function (state) {
      return '<span class="st ' + (ST_CLASS[state] || 'S') + '"><i><b></b><b></b><b></b></i>' +
        (ST_ZH[state] || '') + '</span>';
    },
    api: function (url) {
      return fetch(url).then(function (res) {
        return res.json().catch(function () { return null; }).then(function (json) {
          if (!json || json.ok === false) {
            throw new Error((json && json.error) || ('请求失败（HTTP ' + res.status + '）'));
          }
          return json;
        });
      });
    },
    toast: function (msg, isErr) {
      if (typeof window.v2Toast === 'function') {
        window.v2Toast(msg, isErr ? 'error' : 'info');
      } else if (typeof window.y4Toast === 'function') {
        window.y4Toast(msg, isErr);
      }
    }
  };

  var DIMS = ['A1', 'A2', 'A3', 'A4', 'A5'];
  var DIM_ZH = { A1: '自主感', A2: '认同感', A3: '可用空间', A4: '胜任信心', A5: '可起步性' };
  var LEVELS = ['Secure', 'Watch', 'At-Risk', 'Blocked'];
  var LEVEL_SIGN = { Secure: '稳固', Watch: '关注', 'At-Risk': '风险', Blocked: '阻塞' };
  var BAR_VAR = { Secure: 'var(--secure)', Watch: 'var(--watch)', 'At-Risk': 'var(--risk)', Blocked: 'var(--block)' };
  var GATE_ZH = { body: '身体关', emotion: '情绪关', time: '时间关' };

  /* 指标映射页的分组（与 mockup 一致） */
  var GROUPS = ['自驱力', '学习动机与方法', '情绪与自我', '人格', '依恋', '体质', '认知与执行', '生涯力', '会谈与家长', '其他'];
  var GROUP_OF = {
    autonomy: '自驱力', competence: '自驱力', belonging_good: '自驱力',
    deep_motive: '学习动机与方法', self_efficacy: '学习动机与方法',
    surface_low: '学习动机与方法', surface_not_low: '学习动机与方法',
    strategy_low: '学习动机与方法', self_reg_low: '学习动机与方法',
    anxiety: '情绪与自我', depression: '情绪与自我', emotion_total_low: '情绪与自我',
    esteem_anx: '情绪与自我', self_concept_low: '情绪与自我', mindset_low: '情绪与自我',
    control_low: '情绪与自我', control_high: '情绪与自我', wellbeing_ok: '情绪与自我',
    answer_state: '情绪与自我', safety: '情绪与自我',
    anxiety_flag: '情绪与自我', esteem_flag: '情绪与自我',
    conscientiousness: '人格', neuroticism_high: '人格', extraversion_low: '人格',
    extraversion_high: '人格', agreeable_high: '人格', openness_many: '人格',
    peer_attach_high: '依恋', peer_attach_low: '依恋',
    parent_high: '依恋', parent_low: '依恋', parent_mid: '依恋',
    sleep: '体质', exercise_diet: '体质',
    wm_flex_low: '认知与执行', cog_vs_self: '认知与执行',
    inhibition_low: '认知与执行', attention_low: '认知与执行',
    holland_all_low: '生涯力', holland_peak: '生涯力', holland_c_high: '生涯力',
    indep_boss_top5: '生涯力', safety_top3: '生涯力', achieve_safety: '生涯力',
    achieve_or_prestige_top5: '生涯力',
    ft_goal: '会谈与家长', ft_task: '会谈与家长',
    schedule_full: '会谈与家长', parent_complaint: '会谈与家长'
  };

  /* 亚型中文名只写 README 里写明的那些，其余只显示编号 */
  var SUBTYPE_NAMES = {
    'A1-S2': '自主抗争型', 'A2-S4': '无动机型',
    'A3-S1': '情绪消耗型', 'A3-S2': '恢复不足型', 'A3-S3': '认知饱和型', 'A3-S4': '时间过满型',
    'A5-S1': '任务拆解困难型', 'A5-S3': '外部结构依赖型'
  };
  var SUBTYPES = ['A1-S2', 'A2-S2', 'A2-S3', 'A2-S4',
    'A3-S1', 'A3-S2', 'A3-S3', 'A3-S4',
    'A4-S1', 'A4-S2', 'A4-S3', 'A4-S4',
    'A5-S1', 'A5-S2', 'A5-S3'];

  /* 每个参数只在一张卡上出现（按 README 示例：前 N 位在 A1，思维模式阈值在 A4） */
  var PARAM_DIM = {
    top_n_values: 'A1', control_low_max: 'A1', control_high_min: 'A1',
    schedule_free_hours_max: 'A3',
    top_n_safety: 'A4', mindset_low_max: 'A4', cog_pct_min: 'A4',
    a5_min_supporting: 'A5', a6_top_n: 'A6'
  };

  var state = {
    canEdit: false, published: null, drafts: [], version: null,
    spec: null, publishedSpec: null,
    signals: {}, signalOrder: [], paramMeta: {},
    tab: 't1', dirty: false, errors: [],
    preview: null, pvOpen: null, compare: null,
    picker: null, publishConfirm: false
  };

  /* ── 工具 ─────────────────────────────────────────────── */
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function labelOf(id) {
    var s = state.signals[id];
    return s ? s.label : String(id == null ? '' : id);
  }
  function dimSpec(dim) { return (state.spec && state.spec.dimensions && state.spec.dimensions[dim]) || {}; }
  function paramValue(name) { return (state.spec.params || {})[name]; }
  function groupOf(id) { return GROUP_OF[id] || '其他'; }

  function postJSON(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(function (res) {
      return res.json().catch(function () {
        return { ok: false, errors: ['请求失败（HTTP ' + res.status + '）'] };
      });
    });
  }

  function markDirty() {
    state.dirty = true;
    syncStatus();
  }

  function statusText() {
    if (state.dirty) { return '有未保存修改'; }
    if (state.version && state.version.status === 'draft') { return '草稿'; }
    return '已发布';
  }
  function statusClass() {
    if (state.dirty) { return ' dirty'; }
    if (state.version && state.version.status === 'draft') { return ' draft'; }
    return '';
  }
  function syncStatus() {
    var el = root.querySelector('#bstat');
    if (!el) { return; }
    el.className = 'bstat' + statusClass();
    el.textContent = statusText();
  }

  /* ── A6 条件 ──────────────────────────────────────────── */
  function a6Refs() {
    var refs = {};
    function walk(cond) {
      if (!cond || typeof cond !== 'object') { return; }
      if (cond.signal) { refs[cond.signal] = true; }
      if (cond.not) { walk(cond.not); }
      if (cond.any) { cond.any.forEach(walk); }
      if (cond.all) { cond.all.forEach(walk); }
    }
    (state.spec.a6 || []).forEach(function (entry) {
      walk(entry.assign); walk(entry.caution); walk(entry.avoid);
    });
    return refs;
  }

  function condText(c) {
    if (c.signal) { return labelOf(c.signal); }
    if (c.dim) { return c.dim + ' ≥ ' + LEVEL_SIGN[c.min]; }
    if (c.gate) {
      var parts = String(c.gate).split('.');
      return parts[0] + ' ' + (GATE_ZH[parts[1]] || parts[1]) + ' ≥ ' + LEVEL_SIGN[c.min];
    }
    if (c.subtype) { return c.subtype + (SUBTYPE_NAMES[c.subtype] ? ' ' + SUBTYPE_NAMES[c.subtype] : ''); }
    if (c.dim_any_min) { return '任一维度 ≥ ' + LEVEL_SIGN[c.dim_any_min]; }
    if (c.not) { return '非 ' + condText(c.not); }
    return '条件';
  }
  function condKind(c) {
    if (c.gate) { return 'gate'; }
    if (c.dim || c.dim_any_min) { return 'dim'; }
    if (c.subtype) { return 'sub'; }
    return '';
  }

  function rmBtn(entryIdx, field, path) {
    if (!state.canEdit) { return ''; }
    return '<button type="button" data-rm="' + entryIdx + ':' + field + ':' +
      path.join(',') + '" aria-label="移除条件">×</button>';
  }

  function chipsHTML(cond, entryIdx, field, path) {
    if (!cond) { return ''; }
    if (cond.any || cond.all) {
      var key = cond.any ? 'any' : 'all';
      return '<span class="grp"><span class="gl">' + (key === 'any' ? '任一' : '全部') + '</span>' +
        cond[key].map(function (sub, i) {
          return chipsHTML(sub, entryIdx, field, path.concat([i]));
        }).join('') + '</span>';
    }
    return '<span class="cond ' + condKind(cond) + '">' + SA.esc(condText(cond)) +
      rmBtn(entryIdx, field, path) + '</span>';
  }

  function condCell(entry, entryIdx, field) {
    var cond = entry[field];
    var h = '<div class="chips">' + chipsHTML(cond, entryIdx, field, []);
    if (state.canEdit) {
      var key = entryIdx + ':' + field;
      h += '<button type="button" class="addc" data-add="' + key + '">' +
        (cond ? '添加' : '添加条件') + '</button>';
    }
    h += '</div>';
    if (state.picker && state.picker.entry === entryIdx && state.picker.field === field) {
      h += '<div class="a6pick"><select data-picksel="' + entryIdx + ':' + field + '">' +
        pickerOptions() + '</select>' +
        '<button type="button" data-pickok="' + entryIdx + ':' + field + '">添加</button>' +
        '<button type="button" data-pickcancel="1">取消</button></div>';
    }
    return h;
  }

  function pickerOptions() {
    var h = '<option value="">选择条件…</option><optgroup label="信号">';
    state.signalOrder.forEach(function (id) {
      h += '<option value="sig:' + id + '">' + SA.esc(labelOf(id)) + '</option>';
    });
    h += '</optgroup><optgroup label="维度 ≥ 级别">';
    DIMS.forEach(function (dim) {
      ['Watch', 'At-Risk', 'Blocked'].forEach(function (lv) {
        h += '<option value="dim:' + dim + ':' + lv + '">' + dim + ' ≥ ' + LEVEL_SIGN[lv] + '</option>';
      });
    });
    ['body', 'emotion', 'time'].forEach(function (g) {
      ['Watch', 'At-Risk', 'Blocked'].forEach(function (lv) {
        h += '<option value="gate:A3.' + g + ':' + lv + '">A3 ' + GATE_ZH[g] +
          ' ≥ ' + LEVEL_SIGN[lv] + '</option>';
      });
    });
    h += '</optgroup><optgroup label="亚型">';
    SUBTYPES.forEach(function (s) {
      h += '<option value="sub:' + s + '">' + s +
        (SUBTYPE_NAMES[s] ? ' ' + SUBTYPE_NAMES[s] : '') + '</option>';
    });
    return h + '</optgroup>';
  }

  function condFromValue(v) {
    var p = String(v || '').split(':');
    if (p[0] === 'sig' && p[1]) { return { signal: p[1] }; }
    if (p[0] === 'dim' && p[1] && p[2]) { return { dim: p[1], min: p[2] }; }
    if (p[0] === 'gate' && p[1] && p[2]) { return { gate: p[1], min: p[2] }; }
    if (p[0] === 'sub' && p[1]) { return { subtype: p[1] }; }
    return null;
  }

  function addCond(cond, add) {
    if (!cond) { return add; }
    if (cond.any) { return { any: cond.any.concat([add]) }; }
    if (cond.all) { return { all: cond.all.concat([add]) }; }
    return { any: [cond, add] };
  }

  function removePath(cond, path) {
    if (!cond || !path.length) { return null; }
    var key = cond.any ? 'any' : (cond.all ? 'all' : null);
    if (!key) { return cond; }
    var arr = cond[key].slice();
    var idx = path[0];
    if (path.length === 1) {
      arr.splice(idx, 1);
    } else {
      var sub = removePath(arr[idx], path.slice(1));
      if (sub) { arr[idx] = sub; } else { arr.splice(idx, 1); }
    }
    if (!arr.length) { return null; }
    var out = {};
    out[key] = arr;
    return out;
  }

  /* ── 页头 ─────────────────────────────────────────────── */
  function versionOptions() {
    var cur = state.version ? String(state.version.id) : '';
    function opt(value, label) {
      return '<option value="' + value + '"' +
        (String(value) === cur ? ' selected' : '') + '>' + label + '</option>';
    }
    var h = '';
    if (state.published) {
      h += opt(state.published.id, '已发布 · ' + SA.esc(state.published.label));
    } else {
      h += opt('', '默认规则');
    }
    state.drafts.forEach(function (d) {
      h += opt(d.id, '草稿 · ' + SA.esc(d.label));
    });
    return h;
  }

  function headerHTML() {
    var h = '<div class="bhead"><div><h1>6AM 规则板</h1><p class="sub">' +
      SA.esc((state.spec && state.spec.version) || 'v0.5') + ' 规则 · ' +
      (state.canEdit ? '点击单元格可修改 · 保存即生成规则草稿版本' : '只读查看') +
      '</p></div><span class="spacer"></span>' +
      '<select class="vsel" id="bver" aria-label="规则版本">' + versionOptions() + '</select>' +
      '<span class="bstat' + statusClass() + '" id="bstat">' + statusText() + '</span>';
    if (state.canEdit) {
      h += '<button class="btn" type="button" data-act="preview">预览影响</button>';
      h += '<button class="btn primary" type="button" data-act="save">保存为草稿</button>';
      if (state.errors.length) {
        h += '<span class="berr">' + SA.esc(state.errors.join('；')) + '</span>';
      }
      if (state.publishConfirm) {
        h += '<span class="confirmrow">发布后立即对全部档案生效' +
          '<button class="btn primary" type="button" data-act="publish-ok">确认发布</button>' +
          '<button class="btn" type="button" data-act="publish-cancel">取消</button></span>';
      } else {
        var ready = !!(state.version && state.version.status === 'draft');
        h += '<button class="btn" type="button" data-act="publish"' +
          (ready ? '' : ' disabled') + '>发布此版本</button>';
      }
    }
    h += '<button class="btn" type="button" data-act="compare">与已发布版本对比</button></div>';
    return h;
  }

  /* ── 预览影响 ─────────────────────────────────────────── */
  function barHTML(label, dist) {
    var total = 0;
    LEVELS.forEach(function (lv) { total += dist[lv] || 0; });
    var segs = LEVELS.map(function (lv) {
      var cnt = dist[lv] || 0;
      if (!cnt || !total) { return ''; }
      return '<span style="width:' + (cnt / total * 100) + '%;background:' + BAR_VAR[lv] + '"></span>';
    }).join('');
    return '<div class="barline"><span class="caption">' + label + '</span>' +
      '<div class="bar">' + segs + '</div></div>';
  }

  function previewHTML() {
    var p = state.preview;
    if (!p) { return ''; }
    var changed = p.changed || [];
    var h = '<div class="card bpanel" id="bpreview"><div class="row"><h2>预览影响</h2>' +
      '<span class="sub">共 ' + changed.length + ' 名学生的结果会变化</span><span class="spacer"></span>' +
      '<button class="btn ghost" type="button" data-act="pv-close">关闭</button></div>';
    if (!changed.length) {
      h += '<p class="sub">当前规则与已发布版本的结果一致。</p>';
    }
    h += '<div class="pv">';
    DIMS.forEach(function (dim) {
      var nd = p.distribution[dim] || {};
      var od = (p.published_distribution || {})[dim] || {};
      var cnt = changed.filter(function (c) { return (c.dims || {})[dim]; }).length;
      h += '<div class="d" data-pvdim="' + dim + '" role="button" tabindex="0" aria-pressed="' +
        (state.pvOpen === dim) + '"><div class="row2"><b>' + dim + ' ' + DIM_ZH[dim] +
        '</b><span class="caption">变化 ' + cnt + ' 人</span></div>' +
        '<div class="bars">' + barHTML('新规则', nd) + barHTML('已发布', od) + '</div>' +
        '<div class="caption">' + LEVELS.map(function (lv) {
          return LEVEL_SIGN[lv] + ' ' + (nd[lv] || 0);
        }).join(' · ') + '</div></div>';
    });
    h += '</div>';
    if (state.pvOpen) {
      var rows = changed.filter(function (c) { return (c.dims || {})[state.pvOpen]; });
      h += '<div><div class="lbl2">' + state.pvOpen + ' 变化的档案</div>' +
        (rows.length ? '<ul class="chg">' + rows.map(function (c) {
          var d = c.dims[state.pvOpen];
          return '<li>' + SA.esc(c.name || ('#' + c.report_id)) +
            ' · 报告 #' + c.report_id + '：' + LEVEL_SIGN[d[0]] + ' → ' + LEVEL_SIGN[d[1]] + '</li>';
        }).join('') + '</ul>' : '<p class="sub">该维度没有变化的档案。</p>') + '</div>';
    }
    return h + '</div>';
  }

  /* ── 与已发布版本对比 ─────────────────────────────────── */
  function diffSpec(oldSpec, newSpec) {
    var rows = [];
    var op = oldSpec.params || {}, np = newSpec.params || {};
    Object.keys(np).forEach(function (k) {
      if (String(op[k]) !== String(np[k])) {
        var meta = state.paramMeta[k] || {};
        rows.push({ k: meta.label || k, o: String(op[k] == null ? '—' : op[k]), n: String(np[k]) });
      }
    });
    DIMS.forEach(function (dim) {
      var o = ((oldSpec.dimensions || {})[dim] || {}).supporting || [];
      var n = ((newSpec.dimensions || {})[dim] || {}).supporting || [];
      var added = n.filter(function (id) { return o.indexOf(id) < 0; });
      var removed = o.filter(function (id) { return n.indexOf(id) < 0; });
      if (added.length) { rows.push({ k: dim + ' 新增辅助', o: '', n: added.map(labelOf).join('、') }); }
      if (removed.length) { rows.push({ k: dim + ' 移除辅助', o: removed.map(labelOf).join('、'), n: '' }); }
    });
    var on = oldSpec.notes || {}, nn = newSpec.notes || {};
    Object.keys(nn).forEach(function (k) {
      if (String(on[k] || '') !== String(nn[k] || '')) {
        rows.push({ k: k + ' 备注', o: String(on[k] || '—'), n: String(nn[k] || '—') });
      }
    });
    var oldA6 = {};
    (oldSpec.a6 || []).forEach(function (e) { oldA6[e.id] = e; });
    (newSpec.a6 || []).forEach(function (e) {
      var before = oldA6[e.id];
      if (!before) { return; }
      if (String(before.name || '') !== String(e.name || '')) {
        rows.push({ k: e.group + ' 名称', o: String(before.name || ''), n: String(e.name || '') });
      }
      if (String(before.note || '') !== String(e.note || '')) {
        rows.push({ k: e.name + ' 备注', o: String(before.note || '—'), n: String(e.note || '—') });
      }
      ['assign', 'caution', 'avoid'].forEach(function (field) {
        if (JSON.stringify(before[field] || null) !== JSON.stringify(e[field] || null)) {
          var zh = { assign: '何时分配', caution: '慎用', avoid: '避免' }[field];
          rows.push({ k: e.name + ' · ' + zh, o: '已发布条件', n: '已修改' });
        }
      });
    });
    return rows;
  }

  function compareHTML() {
    if (!state.compare) { return ''; }
    var rows = state.compare;
    var h = '<div class="card bpanel"><div class="row"><h2>与已发布版本对比</h2><span class="spacer"></span>' +
      '<button class="btn ghost" type="button" data-act="cmp-close">关闭</button></div>';
    if (!rows.length) {
      h += '<p class="sub">当前规则与已发布版本一致。</p>';
    } else {
      h += '<div class="diff">' + rows.map(function (r) {
        var val = '';
        if (r.o) { val += '<span class="o">' + SA.esc(r.o) + '</span>'; }
        if (r.n) { val += (val ? ' → ' : '') + '<span class="n">' + SA.esc(r.n) + '</span>'; }
        return '<div class="dr"><span class="k">' + SA.esc(r.k) + '</span><span>' + val + '</span></div>';
      }).join('') + '</div>';
    }
    return h + '</div>';
  }

  /* ── 页签 ① 指标映射 ──────────────────────────────────── */
  function roleOf(sig, dim) {
    var kind = sig.kind || '';
    var member = (sig.dims || []).indexOf(dim) >= 0;
    if (!member) { return { cls: 'none', txt: '·', tog: false }; }
    if (kind === 'main' || kind === 'track' || kind === 'activity' || kind.indexOf('gate') === 0) {
      return { cls: 'main', txt: '主', tog: false };
    }
    if (kind === 'confirm') { return { cls: 'conf', txt: '确认', tog: false }; }
    if (kind === 'type') { return { cls: 'type', txt: '类型', tog: false }; }
    if (kind === 'warn') { return { cls: 'warn', txt: '预警', tog: false }; }
    if ((dimSpec(dim).supporting || []).indexOf(sig.id) >= 0) {
      return { cls: 'aux', txt: '辅', tog: true };
    }
    var scores = kind === 'supporting' || kind === 'extra' || kind === 'secure';
    return { cls: 'none', txt: '·', tog: scores };
  }

  function mapHTML() {
    var refs = a6Refs();
    var h = '<div class="row" style="margin-bottom:8px"><p class="sub">每个 Y4 指标在哪个维度起什么作用。' +
      (state.canEdit ? '点击单元格切换：· ↔ 辅' : '') + '</p><span class="spacer"></span>' +
      '<div class="legend2"><span class="role main">主</span>定位用的主指标 ' +
      '<span class="role aux">辅</span>升级或分型 <span class="role gate">触发</span>A6 分配 ' +
      '<span class="role conf">确认</span>会谈确认 <span class="role type">类型</span>' +
      '<span class="role warn">预警</span></div></div>' +
      '<div class="card bscroll"><table class="bmap"><thead><tr><th>Y4 指标</th><th>官方档位</th>' +
      DIMS.map(function (d) { return '<th class="c">' + d + '</th>'; }).join('') +
      '<th class="c">A6</th></tr></thead><tbody>';
    GROUPS.forEach(function (g) {
      var ids = state.signalOrder.filter(function (id) { return groupOf(id) === g; });
      if (!ids.length) { return; }
      h += '<tr class="grp"><td colspan="8">' + SA.esc(g) + '</td></tr>';
      ids.forEach(function (id) {
        var sig = state.signals[id] || { id: id, label: id, kind: '', dims: [], official_labels: '' };
        h += '<tr><td>' + SA.esc(sig.label) + '</td><td class="sub">' +
          SA.esc(sig.official_labels || '—') + '</td>';
        DIMS.forEach(function (dim) {
          var r = roleOf(sig, dim);
          var tog = state.canEdit && r.tog;
          h += '<td class="c"><span class="role ' + r.cls + (tog ? ' tog' : '') + '"' +
            (tog ? ' data-toggle="' + dim + '" data-sig="' + id + '"' : '') + '>' + r.txt + '</span></td>';
        });
        h += '<td class="c">' + (refs[id] ? '<span class="role gate">触发</span>'
          : '<span class="role none">·</span>') + '</td></tr>';
      });
    });
    return h + '</tbody></table></div>';
  }

  /* ── 页签 ② 严重度 ────────────────────────────────────── */
  function cardKeys() { return ['A1', 'A2', 'A3', 'A4', 'A5', 'A6']; }
  function cardTitle(k) { return k === 'A6' ? '整份档案' : k + ' ' + DIM_ZH[k]; }

  function mainSignalIds(dim) {
    var d = dimSpec(dim);
    if (dim === 'A3') {
      var out = [];
      ['body', 'emotion', 'time'].forEach(function (g) {
        ((d.gates || {})[g] || []).forEach(function (id) { out.push(id); });
      });
      return out;
    }
    if (dim === 'A4') {
      var t = d.tracks || {};
      return [t.learning, t.general].filter(Boolean);
    }
    var ids = (d.main || []).slice();
    if (d.activity) { ids.push(d.activity); }
    return ids;
  }

  function mainText(k) {
    if (k === 'A6') { return '—'; }
    var d = dimSpec(k);
    if (k === 'A3') {
      var g = d.gates || {};
      return '三道关：① ' + (g.body || []).map(labelOf).join(' / ') +
        ' → ② ' + (g.emotion || []).map(labelOf).join(' / ') +
        ' → ③ ' + (g.time || []).map(labelOf).join(' / ');
    }
    if (k === 'A4') {
      var t = d.tracks || {};
      return '两条：学习 ' + labelOf(t.learning) + ' · 通用 ' + labelOf(t.general);
    }
    var parts = (d.main || []).map(labelOf);
    if (d.activity) { parts.push('活动：' + labelOf(d.activity)); }
    return parts.join(' · ');
  }

  function officialRows(k) {
    return mainSignalIds(k).map(function (id) {
      var s = state.signals[id] || {};
      return {
        name: labelOf(id),
        values: String(s.official_labels || '').split(' / ').filter(Boolean)
      };
    });
  }

  function supportingLabels(dim) {
    var ids = dimSpec(dim).supporting || [];
    return ids.length ? ids.map(labelOf).join('、') : '无辅助指标';
  }

  function ladderFor(k) {
    var sup = k === 'A6' ? '' : supportingLabels(k);
    if (k === 'A1') {
      return [
        ['Secure', labelOf('autonomy') + ' 不低及以上'],
        ['Watch', labelOf('autonomy') + ' 偏低'],
        ['At-Risk', '关注 + 任一辅助：' + sup],
        ['Blocked', '风险 + 会谈或家长确认']
      ];
    }
    if (k === 'A2') {
      return [
        ['Secure', labelOf('deep_motive') + ' 不低，且 目标 认同'],
        ['Watch', labelOf('deep_motive') + ' 偏低，或 目标 部分认同'],
        ['At-Risk', '关注 + 任一辅助：' + sup],
        ['Blocked', '风险 + 确认']
      ];
    }
    if (k === 'A3') {
      return [
        ['Secure', '三道关都过'],
        ['Watch', '睡眠 中等；或 情绪 需关注；或 运动 / 饮食 较差；或 工作记忆 偏低'],
        ['At-Risk', '睡眠 差 / 较差；或 情绪 需特殊关注；或 时间 排满'],
        ['Blocked', '风险 + 确认']
      ];
    }
    if (k === 'A4') {
      return [
        ['Secure', '两条都不低'],
        ['Watch', '任一条 偏低'],
        ['At-Risk', '两条都偏低；或 任一条偏低 + 任一辅助：' + sup],
        ['Blocked', '风险 + 确认']
      ];
    }
    if (k === 'A5') {
      return [
        ['Secure', labelOf('conscientiousness') + ' 不低及以上'],
        ['Watch', labelOf('conscientiousness') + ' 偏低 或更低'],
        ['At-Risk', '关注 + 至少 ' + paramVal('a5_min_supporting', 2) + ' 个辅助：' + sup +
          '；或 规划小任务未通过'],
        ['Blocked', '风险 + 规划小任务未通过（拆不出 / 不肯开始）或会谈确认']
      ];
    }
    return [
      ['Watch', '答题状态提示：自我概念整体 偏低 + 情绪稳定性总分 明显偏低'],
      ['At-Risk', '抑郁或焦虑 需特殊关注 → 安全提示']
    ];
  }

  function paramVal(name, fallback) {
    var v = ((state.spec || {}).params || {})[name];
    return typeof v === 'number' ? v : fallback;
  }

  function paramsFor(k) {
    return Object.keys(PARAM_DIM).filter(function (name) { return PARAM_DIM[name] === k; });
  }

  function noteHTML(k) {
    var val = (state.spec.notes || {})[k] || '';
    if (!state.canEdit) {
      return val ? '<p class="bnote-ro">' + SA.esc(val) + '</p>' : '<p class="bnote-ro">—</p>';
    }
    return '<textarea class="bnote" data-note="' + k + '" placeholder="写下这一维的判断备注">' +
      SA.esc(val) + '</textarea>';
  }

  function cardHTML(k) {
    var h = '<div class="card bcard"><div class="bh"><b>' + cardTitle(k) + '</b></div>' +
      '<div><div class="lbl2">主指标</div><div>' + SA.esc(mainText(k)) + '</div></div>' +
      '<div><div class="lbl2">官方档位</div>';
    var offs = officialRows(k);
    if (!offs.length) {
      h += '<div class="sub">—</div>';
    } else {
      offs.forEach(function (o) {
        h += '<div class="scale"><span style="background:transparent;padding:0 6px 0 0">' +
          SA.esc(o.name) + '</span>' + o.values.map(function (v) {
            return '<span>' + SA.esc(v) + '</span>';
          }).join('') + '</div>';
      });
    }
    h += '</div><div class="ladder">' +
      ladderFor(k).map(function (row) {
        return SA.pill(row[0]) + '<span>' + SA.esc(row[1]) + '</span>';
      }).join('') + '</div>';
    var ps = paramsFor(k);
    if (ps.length) {
      h += '<div><div class="lbl2">参数</div>' + ps.map(function (name) {
        var meta = state.paramMeta[name] || { label: name, min: 0, max: 999, step: 1 };
        var v = paramValue(name);
        var input = state.canEdit
          ? '<input type="number" data-param="' + name + '" min="' + meta.min + '" max="' + meta.max +
            '" step="' + (meta.step || 1) + '" value="' + SA.esc(String(v == null ? '' : v)) + '">'
          : '<b style="text-align:right">' + SA.esc(String(v == null ? '—' : v)) + '</b>';
        return '<div class="prow"><span>' + SA.esc(meta.label) + '</span>' + input + '</div>';
      }).join('') + '</div>';
    }
    return h + '<div><div class="lbl2">备注</div>' + noteHTML(k) + '</div></div>';
  }

  function sevHTML() {
    return '<p class="sub" style="margin-bottom:8px">Y4 官方档位不改写；级别由档位决定，原始分（距常模）' +
      '只决定同一级别内谁先处理。阻塞都需要会谈或家长确认。</p><div class="dims2">' +
      cardKeys().map(cardHTML).join('') + '</div>';
  }

  /* ── 页签 ③ A6 支持 ───────────────────────────────────── */
  function catHTML() {
    var h = '<p class="sub" style="margin-bottom:8px">A6 是支持方式目录：根据 A1–A5 结果和特质，' +
      '每名学生分配几项。仅供导师内部参考。</p>' +
      '<div class="card bscroll"><table class="bcat"><thead><tr>' +
      '<th>类别</th><th>支持方式</th><th>何时分配</th><th>慎用</th><th>避免</th><th>备注</th>' +
      '</tr></thead><tbody>';
    (state.spec.a6 || []).forEach(function (entry, i) {
      h += '<tr><td class="sub">' + SA.esc(entry.group || '') + '</td>' +
        '<td>' + (state.canEdit
          ? '<input class="binp" data-a6name="' + i + '" value="' + SA.esc(entry.name || '') + '">'
          : '<b>' + SA.esc(entry.name || '') + '</b>') + '</td>' +
        '<td>' + condCell(entry, i, 'assign') + '</td>' +
        '<td>' + condCell(entry, i, 'caution') + '</td>' +
        '<td>' + condCell(entry, i, 'avoid') + '</td>' +
        '<td>' + (state.canEdit
          ? '<textarea class="bnote" data-a6note="' + i + '" placeholder="备注">' +
            SA.esc(entry.note || '') + '</textarea>'
          : '<span class="muted2">' + (entry.note ? SA.esc(entry.note) : '—') + '</span>') + '</td></tr>';
    });
    return h + '</tbody></table></div>';
  }

  /* ── 渲染 ─────────────────────────────────────────────── */
  function render() {
    root.innerHTML = headerHTML() + previewHTML() + compareHTML() +
      '<div class="tabs" role="tablist" aria-label="规则板页签">' +
      '<button type="button" role="tab" data-tab="t1" aria-selected="' + (state.tab === 't1') + '">① 指标映射</button>' +
      '<button type="button" role="tab" data-tab="t2" aria-selected="' + (state.tab === 't2') + '">② 严重度</button>' +
      '<button type="button" role="tab" data-tab="t3" aria-selected="' + (state.tab === 't3') + '">③ A6 支持</button>' +
      '</div>' +
      '<section id="bs-t1"' + (state.tab === 't1' ? '' : ' hidden') + '>' + mapHTML() + '</section>' +
      '<section id="bs-t2"' + (state.tab === 't2' ? '' : ' hidden') + '>' + sevHTML() + '</section>' +
      '<section id="bs-t3"' + (state.tab === 't3' ? '' : ' hidden') + '>' + catHTML() + '</section>';
  }

  /* ── 保存 / 预览 / 发布 ───────────────────────────────── */
  function load(versionId) {
    root.innerHTML = '<p class="sub">规则板加载中…</p>';
    var url = '/api/six-am/board' +
      (versionId ? '?version_id=' + encodeURIComponent(versionId) : '');
    SA.api(url).then(function (data) {
      state.canEdit = data.can_edit === true && root.getAttribute('data-can-edit') !== 'false';
      state.published = data.published || null;
      state.drafts = data.drafts || [];
      state.version = data.version || null;
      state.spec = clone(data.spec);
      state.publishedSpec = null;
      state.paramMeta = data.param_meta || {};
      state.signals = {};
      state.signalOrder = [];
      (data.signals || []).forEach(function (s) {
        state.signals[s.id] = s;
        state.signalOrder.push(s.id);
      });
      state.dirty = false;
      state.errors = [];
      state.preview = null;
      state.pvOpen = null;
      state.compare = null;
      state.picker = null;
      state.publishConfirm = false;
      render();
    }).catch(function (err) {
      SA.toast(err.message, true);
      root.innerHTML = '<div class="row"><div><h1>6AM 规则板</h1><p class="sub">' +
        SA.esc(err.message) + '</p></div><span class="spacer"></span>' +
        '<button class="btn" type="button" data-act="retry">重试</button></div>';
    });
  }

  function save() {
    return postJSON('/api/six-am/board', {
      label: null,
      base_version_id: state.version ? state.version.id : null,
      spec: state.spec
    }).then(function (json) {
      if (!json || json.ok !== true) {
        state.errors = (json && json.errors) || [(json && json.error) || '保存失败'];
        render();
        return;
      }
      state.errors = [];
      SA.toast('已保存为草稿', false);
      load(json.version_id);
    }).catch(function (err) {
      state.errors = [err.message];
      render();
    });
  }

  function runPreview() {
    return postJSON('/api/six-am/board/preview', { spec: state.spec }).then(function (json) {
      if (!json || json.ok !== true) {
        state.errors = (json && json.errors) || [(json && json.error) || '预览失败'];
        render();
        return;
      }
      state.errors = [];
      state.preview = json;
      state.compare = null;
      state.pvOpen = null;
      render();
      var box = root.querySelector('#bpreview');
      if (box && box.scrollIntoView) { box.scrollIntoView({ block: 'nearest' }); }
    }).catch(function (err) {
      SA.toast(err.message, true);
    });
  }

  function publish() {
    var id = state.version && state.version.id;
    if (!id) { return; }
    postJSON('/api/six-am/rule-versions/' + id + '/publish', {}).then(function (json) {
      if (!json || json.ok !== true) {
        SA.toast((json && json.error) || '发布失败', true);
        return;
      }
      state.publishConfirm = false;
      SA.toast('已发布该版本', false);
      load(id);
    }).catch(function (err) {
      SA.toast(err.message, true);
    });
  }

  /* ── 事件 ─────────────────────────────────────────────── */
  function onClick(e) {
    var tabBtn = e.target.closest('[data-tab]');
    if (tabBtn) {
      state.tab = tabBtn.getAttribute('data-tab');
      state.picker = null;
      render();
      return;
    }

    var rm = e.target.closest('[data-rm]');
    if (rm) {
      var seg = rm.getAttribute('data-rm').split(':');
      var entry = state.spec.a6[+seg[0]];
      var field = seg[1];
      var path = seg[2] ? seg[2].split(',').map(Number) : [];
      entry[field] = path.length ? removePath(entry[field], path) : null;
      markDirty();
      render();
      return;
    }

    var add = e.target.closest('[data-add]');
    if (add) {
      var key = add.getAttribute('data-add').split(':');
      state.picker = { entry: +key[0], field: key[1] };
      render();
      return;
    }

    if (e.target.hasAttribute('data-pickcancel')) {
      state.picker = null;
      render();
      return;
    }

    var ok = e.target.closest('[data-pickok]');
    if (ok) {
      var k = ok.getAttribute('data-pickok');
      var sel = root.querySelector('[data-picksel="' + k + '"]');
      var cond = sel ? condFromValue(sel.value) : null;
      if (cond) {
        var parts = k.split(':');
        var entry2 = state.spec.a6[+parts[0]];
        entry2[parts[1]] = addCond(entry2[parts[1]], cond);
        markDirty();
      }
      state.picker = null;
      render();
      return;
    }

    var tg = e.target.closest('[data-toggle]');
    if (tg && state.canEdit) {
      var dim = tg.getAttribute('data-toggle');
      var sid = tg.getAttribute('data-sig');
      var ds = state.spec.dimensions[dim];
      if (!ds.supporting) { ds.supporting = []; }
      var i = ds.supporting.indexOf(sid);
      if (i >= 0) { ds.supporting.splice(i, 1); } else { ds.supporting.push(sid); }
      markDirty();
      render();
      return;
    }

    var pvd = e.target.closest('[data-pvdim]');
    if (pvd) {
      var d = pvd.getAttribute('data-pvdim');
      state.pvOpen = state.pvOpen === d ? null : d;
      render();
      return;
    }

    var act = e.target.closest('[data-act]');
    if (!act) { return; }
    var a = act.getAttribute('data-act');
    if (a === 'preview') { runPreview(); }
    else if (a === 'save') { save(); }
    else if (a === 'compare') {
      SA.api('/api/six-am/board').then(function (data) {
        state.publishedSpec = data.spec;
        state.compare = diffSpec(data.spec, state.spec);
        state.preview = null;
        render();
      }).catch(function (err) { SA.toast(err.message, true); });
    } else if (a === 'publish') {
      state.publishConfirm = true;
      render();
    } else if (a === 'publish-ok') { publish(); }
    else if (a === 'publish-cancel') { state.publishConfirm = false; render(); }
    else if (a === 'pv-close') { state.preview = null; state.pvOpen = null; render(); }
    else if (a === 'cmp-close') { state.compare = null; render(); }
    else if (a === 'retry') { load(null); }
  }

  function onInput(e) {
    var t = e.target;
    if (t.hasAttribute('data-note')) {
      state.spec.notes[t.getAttribute('data-note')] = t.value;
      markDirty();
    } else if (t.hasAttribute('data-a6name')) {
      state.spec.a6[+t.getAttribute('data-a6name')].name = t.value;
      markDirty();
    } else if (t.hasAttribute('data-a6note')) {
      state.spec.a6[+t.getAttribute('data-a6note')].note = t.value;
      markDirty();
    }
  }

  function onChange(e) {
    var t = e.target;
    if (t.id === 'bver') {
      load(t.value || null);
      return;
    }
    if (t.hasAttribute && t.hasAttribute('data-param')) {
      var name = t.getAttribute('data-param');
      var meta = state.paramMeta[name] || {};
      var v = parseFloat(t.value);
      if (isNaN(v)) { t.value = String(paramValue(name)); return; }
      var lo = meta.min == null ? 0 : meta.min;
      var hi = meta.max == null ? 9999 : meta.max;
      v = Math.min(hi, Math.max(lo, v));
      state.spec.params[name] = v;
      t.value = String(v);
      markDirty();
    }
  }

  function bind() {
    if (root.getAttribute('data-bound')) { return; }
    root.setAttribute('data-bound', '1');
    root.addEventListener('click', onClick);
    root.addEventListener('input', onInput);
    root.addEventListener('change', onChange);
    window.addEventListener('beforeunload', function (e) {
      if (!state.dirty) { return; }
      e.preventDefault();
      e.returnValue = '';
    });
  }

  bind();
  load(null);
})();
