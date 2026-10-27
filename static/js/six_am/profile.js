/* 6AM 2.0 · 学生档案：六维一览、判定依据链、追问预览、行动修订、补充证据、版本记录。 */
(function () {
  'use strict';

  var SA = window.SA;

  var DIM_ZH = { A1: '自主感', A2: '认同感', A3: '可用空间', A4: '胜任信心', A5: '可起步性', A6: '启动支持' };
  var DIM_KEYS = ['A1', 'A2', 'A3', 'A4', 'A5', 'A6'];
  var FIT_CLASS = { '优先': 'p', '可考虑': 'k', '慎用': 'c', '避免': 'a' };

  var state = {
    report_id: null,
    profile_id: null,
    data: null,
    dim: 'A1',
    compare: false,
    answers: {},
    preview: {},
    previewSeq: 0,
    drawer: false,
    edit: false
  };

  function num(v) {
    if (v == null || v === '') return '';
    var n = Number(v);
    if (!isFinite(n)) return String(v);
    return String(Math.round(n * 10) / 10);
  }
  function dateShort(d) { return d ? String(d).slice(5, 10) : '—'; }
  function cardsOf(data) {
    var out = {};
    ((data && data.view_model && data.view_model.cards) || []).forEach(function (c) { out[c.dim] = c; });
    return out;
  }
  function orderedCards(data) {
    var map = cardsOf(data);
    return DIM_KEYS.map(function (k) { return map[k]; }).filter(Boolean);
  }
  function supportPlan(data, a6) {
    var prof = (data && data.profile) || {};
    if (prof.support_plan && (prof.support_plan.ranked || []).length) return prof.support_plan;
    var audit = (a6 && a6.audit) || {};
    return audit.support_ranking || prof.support_plan || {};
  }
  function topDirection(plan) {
    var ranked = (plan && plan.ranked) || [];
    var first = null;
    for (var i = 0; i < ranked.length; i++) {
      var d = ranked[i] && ranked[i].direction;
      if (!d) continue;
      if (ranked[i].fit_label === '优先') return String(d);
      if (!first) first = String(d);
    }
    return first;
  }

  /* ── 数据加载 ─────────────────────────────────────────────── */
  function getProfile(rid, pid) {
    var url = '/api/reports/' + encodeURIComponent(rid) + '/six-am' +
      (pid ? '?profile_id=' + encodeURIComponent(pid) : '');
    return fetch(url, { headers: { Accept: 'application/json' } }).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (json) {
        if (res.status === 404) {
          var err = new Error((json && json.error) || '尚无 6AM 档案');
          err.noProfile = true;
          throw err;
        }
        if (!json || json.ok === false) {
          throw new Error((json && json.error) || ('请求失败（HTTP ' + res.status + '）'));
        }
        return json;
      });
    });
  }

  function seedAnswers(data) {
    state.answers = {};
    var list = ((data && data.profile && data.profile.answers) || []);
    list.forEach(function (a) {
      if (a && a.q) state.answers[a.q] = { q: a.q, result: a.result || '', text: a.text || '' };
    });
  }

  function answersPayload() {
    return Object.keys(state.answers).map(function (k) { return state.answers[k]; })
      .filter(function (a) { return a && a.result; });
  }

  function answersBody() {
    var list = answersPayload();
    return list.length ? { answers: list } : {};
  }

  function load(el, rid, pid) {
    el.innerHTML = '<div class="card pad"><p class="sub">加载中…</p></div>';
    return getProfile(rid, pid).then(function (data) {
      state.data = data;
      state.edit = false;
      state.preview = {};
      seedAnswers(data);
      if (!cardsOf(data)[state.dim]) state.dim = 'A1';
      render(el);
    }).catch(function (err) {
      if (err.noProfile) renderNoProfile(el);
      else renderError(el, err);
    });
  }

  /* ── 空态 / 错误 ──────────────────────────────────────────── */
  function renderNoSelection(el) {
    el.innerHTML = '<div class="card pad"><p class="sub">从总览选择一名学生。</p>' +
      '<p style="margin-top:12px"><a class="btn" href="?view=overview" data-go="overview">← 返回总览</a></p></div>';
  }

  function renderNoProfile(el) {
    el.innerHTML = '<div class="card pad" style="display:flex;flex-direction:column;gap:12px">' +
      '<p>该报告还没有 6AM 档案</p>' +
      (SA.canWrite()
        ? '<div class="row"><button class="btn primary" type="button" data-gen="1">生成档案</button>' +
          '<span class="sub">生成后可在此补充证据与追问。</span></div>'
        : '<p class="sub">请联系有权限的同事先生成档案。</p>') +
      '<p><a class="btn ghost" href="?view=overview" data-go="overview">← 返回总览</a></p></div>';
  }

  function renderError(el, err) {
    el.innerHTML = '<div class="card pad" style="display:flex;flex-direction:column;gap:10px">' +
      '<p class="sub">' + SA.esc(err.message) + '</p>' +
      '<div class="row"><button class="btn" type="button" data-retry="1">重试</button>' +
      '<a class="btn ghost" href="?view=overview" data-go="overview">← 返回总览</a></div></div>';
  }

  /* ── 页头与提示条 ────────────────────────────────────────── */
  function header(data) {
    var prof = data.profile || {};
    var stu = prof.student || {};
    var rv = prof.rule_version || {};
    var h = '<div class="phead"><div class="who">' +
      '<div class="row"><button class="btn ghost" type="button" data-go="overview">← 总览</button></div>' +
      '<h1>' + SA.esc(stu.name || '') +
      ' <span class="sub" style="font-size:14px;font-weight:400">' + SA.esc(stu.grade || '') + '</span></h1>' +
      '<p class="sub">报告 ' + SA.esc(data.report_date || '—') + ' · 档案 v' + SA.esc(data.version || '') +
      ' · ' + SA.esc(!rv.label || rv.label === 'default' ? '默认规则' : '规则 ' + rv.label) + '</p></div>' +
      '<span class="spacer"></span><div class="row">';
    if (data.previous_states) {
      h += '<label class="row" style="gap:6px;font-size:12.5px;color:var(--muted)">' +
        '<input type="checkbox" id="p5-cmp"' + (state.compare ? ' checked' : '') + '> 对照上一版</label>';
    }
    if (SA.canWrite()) {
      h += '<button class="btn" type="button" data-open-evidence="1">补充证据</button>';
    }
    h += '<a class="btn" href="/api/reports/' + encodeURIComponent(data.report_id) +
      '/six-am/docx?profile_id=' + encodeURIComponent(data.profile_id) + '">下载 Word</a>' +
      '<button class="btn primary" type="button" data-review="1">加入评审会</button>';
    return h + '</div></div>';
  }

  function banners(cards) {
    var prof = state.data.profile || {};
    var h = '';
    if (prof.safety_review) {
      h += '<div class="banner safety" role="alert"><b>情绪安全复核</b><p>Y4 情绪指标落在最严重档。请先由顾问了解学生近况，必要时建议家长寻求专业评估；评估前不新增任务、不做启动推进。本模型不是心理诊断工具。</p></div>';
    }
    var missing = orderedCards(state.data).filter(function (c) {
      return c.dim !== 'A6' && (c.audit && c.audit.flags || []).indexOf('Y4 数据缺失') >= 0;
    }).map(function (c) { return c.dim; });
    if (missing.length) {
      h += '<div class="banner missing"><b>数据缺失</b><p style="color:var(--ink-2)">' +
        SA.esc(missing.join('、')) + ' 的核心 Y4 指标缺失。这些维度显示“稳固”只代表没有数据，不代表没有障碍。</p></div>';
    }
    return h;
  }

  /* ── 六维一览与处理顺序 ──────────────────────────────────── */
  function teamAdjust(dim) {
    var r = (state.data.reviews || {})[dim];
    if (!r || r.verdict !== 'adjust' || !r.adjusted_state) return '';
    return '<div class="cmp">团队调整为 <b>' + SA.esc(SA.STATE_ZH[r.adjusted_state] || r.adjusted_state) + '</b></div>';
  }

  function tiles(data, cards) {
    var a6 = cards.A6;
    var plan = supportPlan(data, a6);
    var h = '<div class="tiles" role="tablist" aria-label="六维">';
    DIM_KEYS.forEach(function (k) {
      var c = cards[k];
      if (!c) return;
      if (k === 'A6') {
        h += '<button class="tile" role="tab" type="button" data-dim="A6" aria-selected="' +
          (state.dim === 'A6') + '"><div class="k"><b>A6 ' + SA.esc(DIM_ZH.A6) + '</b></div>' +
          '<span class="tag">支持选择器</span><div class="subt">首选：' +
          SA.esc(topDirection(plan) || '—') + '</div></button>';
        return;
      }
      var prev = data.previous_states && data.previous_states[k];
      h += '<button class="tile" role="tab" type="button" data-dim="' + k + '" aria-selected="' +
        (state.dim === k) + '">' +
        (typeof c.priority_rank === 'number'
          ? '<span class="rank" title="处理顺序">' + c.priority_rank + '</span>' : '') +
        '<div class="k"><b>' + k + ' ' + SA.esc(DIM_ZH[k]) + '</b></div>' +
        SA.pill(c.state) + teamAdjust(k) +
        '<div class="subt">' + SA.esc(c.subtype_display || (c.state === 'Secure' ? '未见障碍' : '')) + '</div>' +
        SA.ev(c.state !== 'Secure' ? c.evidence_state : null) +
        (state.compare && prev && prev !== c.state
          ? '<div class="cmp">上一版：<s>' + SA.esc(SA.STATE_ZH[prev] || prev) + '</s></div>' : '') +
        '</button>';
    });
    return h + '</div>';
  }

  function orderSteps(data, cards) {
    var order = (data.view_model && data.view_model.summary && data.view_model.summary.priority_order) || [];
    if (!order.length) return '';
    return '<div class="order" aria-label="处理顺序">' + order.slice(0, 3).map(function (k, i) {
      var c = cards[k];
      if (!c) return '';
      return '<div class="step"><span class="n">' + (i + 1) + '</span><div><b>' + k + ' ' +
        SA.esc(DIM_ZH[k] || '') + '</b><p>' + SA.esc(c.priority_reason || '') + '</p></div></div>';
    }).join('') + '</div>';
  }

  /* ── 指标条 ─────────────────────────────────────────────── */
  function meter(ind) {
    if (ind.text) {
      return '<div class="val" style="grid-column:2 / 4;text-align:left">' + SA.esc(ind.text) + '</div>';
    }
    if (ind.rank != null) {
      var total = ind.rank_total || 15;
      var rpct = Math.max(0, Math.min(100, (total + 1 - ind.rank) / total * 100));
      return '<div class="meter"><span class="fill" style="width:' + rpct +
        '%;background:var(--ink-2);opacity:.35"></span></div><div class="val">第 ' + ind.rank +
        ' 位 / ' + total + '</div>';
    }
    var value = ind.value == null ? '' : num(ind.value);
    var text;
    if (ind.norm != null) {
      var gap = ind.gap;
      if (gap == null && ind.value != null) gap = Math.round((Number(ind.value) - Number(ind.norm)) * 10) / 10;
      text = value + ' / 常模 ' + num(ind.norm) + '（' + (gap > 0 ? '+' : '') + num(gap) + '）';
    } else if (ind.cut != null) {
      text = value + ' / 线 < ' + num(ind.cut);
    } else {
      text = value;
    }
    if (ind.max == null) {
      return '<div class="val" style="grid-column:2 / 4;text-align:left">' + SA.esc(text) + '</div>';
    }
    var pct = Math.max(0, Math.min(100, Number(ind.value) / Number(ind.max) * 100));
    var col = ind.strength === 'strong' ? 'var(--risk)' : ind.strength === 'weak' ? 'var(--watch)' : 'var(--ink-2)';
    var ref = ind.norm != null ? Number(ind.norm) : (ind.cut != null ? Number(ind.cut) : null);
    var tick = ref != null
      ? '<span class="tick" style="left:' + Math.max(0, Math.min(100, ref / Number(ind.max) * 100)) + '%"></span>'
      : '';
    return '<div class="meter"><span class="fill" style="width:' + pct + '%;background:' + col + '"></span>' +
      tick + '</div><div class="val">' + SA.esc(text) + '</div>';
  }

  function indicatorRow(ind, withTag) {
    var tag = '';
    if (withTag) {
      var label = ind.strength === 'strong' ? '强' : ind.strength === 'weak' ? '弱' : (ind.band || '—');
      tag = '<span class="str ' + (ind.strength || 'weak') + '">' + SA.esc(label) + '</span>';
    }
    return '<div class="ind"><div class="nm">' + SA.esc(ind.point) + tag + '</div>' + meter(ind) + '</div>';
  }

  /* ── 追问与预览 ─────────────────────────────────────────── */
  function answerButtons(q, writable) {
    var current = (state.answers[q.id] || {}).result || '';
    if (!writable) {
      return '<span class="tag">' + (q.answered || current ? '已记录' : '待确认') + '</span>';
    }
    var opts = [['confirm', '证实'], ['partial', '部分'], ['deny', '否定']];
    return '<div class="seg" role="group" aria-label="' + SA.esc(q.id) + ' 答案">' + opts.map(function (o) {
      return '<button type="button" data-ans="' + SA.esc(q.id) + '" data-v="' + o[0] +
        '" aria-pressed="' + (current === o[0]) + '">' + o[1] + '</button>';
    }).join('') + '</div>';
  }

  function questionsBlock(card, writable) {
    var qs = (card.rationale && card.rationale.open_questions) || [];
    if (!qs.length) return '<p class="sub">暂无待追问问题。</p>';
    var h = qs.map(function (q) {
      var pv = state.preview[q.id];
      return '<div class="q"><div class="row"><span class="mono">' + SA.esc(q.id) + '</span>' +
        '<span class="spacer"></span>' + answerButtons(q, writable) + '</div>' +
        '<div class="t">“' + SA.esc(q.text) + '”</div>' +
        (pv ? '<div class="preview">保存后预计：' + SA.esc(pv) + '</div>'
            : '<div class="meta">证实可升级证据等级；否定会把对应规则移出判定。</div>') +
        '</div>';
    }).join('');
    if (writable) {
      h += '<div class="row" style="margin-top:4px"><button class="btn primary" type="button" data-save-answers="1">保存并生成新版本</button>' +
        '<span class="sub">保存后生成新版本，上一版保留。</span></div>';
    }
    return h;
  }

  /* ── 判定依据与行动 ─────────────────────────────────────── */
  function a6Support(card) {
    var plan = supportPlan(state.data, card);
    var ranked = plan.ranked || [];
    if (!ranked.length) return '<p class="sub">暂无支持方式排序。</p>';
    return '<div class="support">' + ranked.map(function (r) {
      var fit = r.fit_label || '';
      return '<div class="s"><span>' + SA.esc(r.direction || '') + '</span>' +
        (fit ? '<span class="fit ' + (FIT_CLASS[fit] || 'k') + '">' + SA.esc(fit) + '</span>' : '') +
        '</div>';
    }).join('') + '</div>';
  }

  function detail(card) {
    var writable = SA.canWrite();
    var h = '<section class="card pad" style="display:flex;flex-direction:column;gap:12px">' +
      '<div class="row"><h2>' + card.dim + ' ' + SA.esc(DIM_ZH[card.dim]) + '</h2><span class="spacer"></span>' +
      (card.dim === 'A6'
        ? '<span class="tag">不判风险</span>'
        : SA.pill(card.state) + SA.ev(card.state !== 'Secure' ? card.evidence_state : null)) +
      '</div>';
    if (card.verdict) h += '<p class="verdict">' + SA.esc(card.verdict) + '</p>';
    h += '</section>';

    if (card.dim === 'A6') {
      h += '<section class="card pad" style="display:flex;flex-direction:column;gap:10px">' +
        '<div class="row"><h2>支持方式</h2><span class="spacer"></span><span class="sub">按匹配程度排序</span></div>' +
        a6Support(card) + '</section>';
    } else if (card.rationale) {
      var r = card.rationale;
      var inds = r.indicators || [];
      h += '<section class="card pad"><div class="row" style="margin-bottom:6px"><h2>判定依据</h2>' +
        '<span class="spacer"></span><span class="sub">理论 → Y4 证据 → 为什么是这个状态 → 还缺什么</span></div>' +
        '<div class="chain">' +
        '<div class="link"><span class="num">1</span><div class="body"><h3>理论</h3><p>' +
        SA.esc(r.theory || '') + '</p></div></div>' +
        '<div class="link"><span class="num">2</span><div class="body"><h3>Y4 证据</h3>' +
        (inds.length
          ? inds.map(function (i) { return indicatorRow(i, true); }).join('') +
            '<div class="legend"><span><i></i>同龄常模或风险线</span>' +
            '<span>强 = 明显低于常模 / 最严重档</span><span>弱 = Y4 “偏低/需关注”</span></div>'
          : '<p class="sub">无指标明细。</p>') +
        '</div></div>' +
        '<div class="link"><span class="num">3</span><div class="body"><h3>为什么是“' +
        SA.esc(SA.STATE_ZH[card.state] || '') + '”</h3><p>' + SA.esc(r.level_reason || '') + '</p>' +
        ((r.rules || []).map(function (rule) {
          return '<div class="rule"><span class="mono">' + SA.esc(rule.id || '') + '</span>' +
            SA.esc(rule.text || '') + '</div>';
        }).join('')) +
        '</div></div>' +
        '<div class="link"><span class="num">4</span><div class="body"><h3>还不能说明 · 什么会改变它</h3>' +
        questionsBlock(card, writable) + '</div></div>' +
        '</div></section>';
    }

    h += actionsBlock(card, writable);
    return h;
  }

  function actionsBlock(card, writable) {
    var next = card.next_actions || [];
    var avoid = card.avoid_actions || [];
    var h = '<section class="card pad" style="display:flex;flex-direction:column;gap:10px">' +
      '<div class="row"><h2>行动建议</h2><span class="spacer"></span>';
    if (state.edit) {
      h += '<button class="btn" type="button" data-cancel-edit="1">取消</button>' +
        '<button class="btn primary" type="button" data-save-actions="1">保存修订</button>';
    } else if (writable) {
      h += '<button class="btn" type="button" data-edit="1">修订（不生成新版本）</button>';
    }
    h += '</div>';
    if (state.edit) {
      h += '<label class="sub" for="p5-next">下一步（每行一条，最多 8 条）</label>' +
        '<textarea class="act-edit" id="p5-next" data-act="next" rows="4">' + SA.esc(next.join('\n')) + '</textarea>' +
        '<label class="sub" for="p5-avoid">避免（每行一条，最多 8 条）</label>' +
        '<textarea class="act-edit" id="p5-avoid" data-act="avoid" rows="3">' + SA.esc(avoid.join('\n')) + '</textarea>';
    } else {
      h += '<div class="acts"><div><h3>下一步</h3><ul>' +
        (next.length ? next.map(function (t) { return '<li>' + SA.esc(t) + '</li>'; }).join('')
                     : '<li class="sub">—</li>') + '</ul></div>' +
        '<div><h3>避免</h3><ul>' +
        (avoid.length ? avoid.map(function (t) { return '<li>' + SA.esc(t) + '</li>'; }).join('')
                      : '<li class="sub">—</li>') + '</ul></div></div>';
    }
    return h + '</section>';
  }

  /* ── 右栏 ───────────────────────────────────────────────── */
  function rail(cards) {
    var data = state.data;
    var plan = supportPlan(data, cards.A6);
    var ranked = plan.ranked || [];
    var h = '<aside class="rail"><section class="card pad"><h2 style="margin-bottom:10px">支持方式</h2>' +
      '<div class="support">';
    if (!ranked.length) h += '<p class="sub">—</p>';
    ranked.forEach(function (r) {
      var fit = r.fit_label || '';
      h += '<div class="s"><span>' + SA.esc(r.direction || '') + '</span>' +
        (fit ? '<span class="fit ' + (FIT_CLASS[fit] || 'k') + '">' + SA.esc(fit) + '</span>' : '') +
        '</div>';
    });
    h += '</div></section>';
    h += '<section class="card pad"><h2 style="margin-bottom:10px">版本记录</h2>';
    var versions = data.versions || [];
    if (!versions.length) {
      h += '<p class="sub">暂无版本记录。</p>';
    } else {
      h += '<div class="tl">' + versions.map(function (v) {
        return '<button class="it" type="button" data-vpid="' + v.profile_id + '">' +
          '<span class="dot"></span><div><b>v' + SA.esc(v.version) + '</b> ' +
          '<small>' + SA.esc(dateShort(v.created_at)) + '</small>' +
          (v.profile_id === data.profile_id ? ' <span class="tag">当前</span>' : '') +
          '<p>' + SA.esc((v.changes || []).join('；')) + '</p></div></button>';
      }).join('') + '</div>';
    }
    return h + '</section></aside>';
  }

  /* ── 补充证据抽屉 ───────────────────────────────────────── */
  function triOpts(val, labels, placeholder) {
    var cur = val === true ? 'yes' : (val === false ? 'no' : '');
    return [['', placeholder], ['yes', labels[0]], ['no', labels[1]]].map(function (o) {
      return '<option value="' + o[0] + '"' + (cur === o[0] ? ' selected' : '') + '>' + o[1] + '</option>';
    }).join('');
  }
  function triVal(v) { return v === 'yes' ? true : (v === 'no' ? false : null); }

  function subjectRow(r) {
    r = r || {};
    return '<div class="subj-row">' +
      '<input class="inp gp-sj-name" placeholder="学科" aria-label="学科" value="' + SA.esc(r.subject || '') + '">' +
      '<input class="inp gp-sj-self" placeholder="学生自评水平" aria-label="学生自评水平" value="' + SA.esc(r.self_level || '') + '">' +
      '<input class="inp gp-sj-actual" placeholder="实际状态" aria-label="实际状态" value="' + SA.esc(r.actual || '') + '">' +
      '<select class="inp gp-sj-gap" aria-label="偏差方向">' +
      [['', '偏差方向'], ['below', '自评低于实际'], ['equal', '自评等于实际'], ['above', '自评高于实际']].map(function (o) {
        return '<option value="' + o[0] + '"' + ((r.gap || '') === o[0] ? ' selected' : '') + '>' + o[1] + '</option>';
      }).join('') + '</select>' +
      '<button class="btn ghost" type="button" data-subj-del="1" aria-label="删除该学科">删除</button></div>';
  }

  function drawerHTML() {
    var d = state.data || {};
    var g = (d.profile && d.profile.gaps) || {};
    var fam = g.family_complaint || {};
    var tags = fam.tags || [];
    var sch = g.schedule || {};
    var goal = g.goal || {};
    if (!goal.text && !goal.judgement) {
      ((d.profile && d.profile.evidence_log) || []).some(function (item) {
        if (item && item.source === 'FT' && item.kind === 'goal' && item.detail) {
          goal = item.detail;
          return true;
        }
        return false;
      });
    }
    var subj = Array.isArray(g.subject_status) ? g.subject_status : [];
    var st = g.standard_task || {};
    var nextV = parseInt(d.version, 10);
    var btnLabel = '保存并生成新版本' + (isFinite(nextV) ? '（v' + nextV + ' → v' + (nextV + 1) + '）' : '');

    return '<div class="drawer-mask' + (state.drawer ? ' open' : '') + '" data-close-drawer="1"></div>' +
      '<aside class="drawer' + (state.drawer ? ' open' : '') + '" role="dialog" aria-label="补充证据"' +
      ' aria-hidden="' + (state.drawer ? 'false' : 'true') + '">' +
      '<div class="row"><h2>补充证据</h2><span class="spacer"></span>' +
      '<button class="btn ghost" type="button" data-close-drawer="1">关闭</button></div>' +
      '<p class="sub">家长诉求用于 A1/A2，排期用于 A3，学科状态用于 A4，标准化任务用于 A5。</p>' +

      '<fieldset class="gap"><legend>家长诉求</legend>' +
      '<div class="row" style="gap:10px">' + ['无兴趣', '动力不足', '其他'].map(function (t) {
        return '<label class="row" style="gap:5px;font-size:13px"><input type="checkbox" class="gp-fam-tag" value="' +
          t + '"' + (tags.indexOf(t) >= 0 ? ' checked' : '') + '> ' + t + '</label>';
      }).join('') + '</div>' +
      '<textarea class="inp gp-fam-text" placeholder="主诉原文">' + SA.esc(fam.text || '') + '</textarea>' +
      '<div class="row"><label class="sub" for="p5-fam-src">采集来源</label>' +
      '<select class="inp gp-fam-source" id="p5-fam-src" style="width:auto">' +
      ['', '家长环节', '顾问记录'].map(function (v) {
        return '<option value="' + v + '"' + ((fam.source || '') === v ? ' selected' : '') + '>' +
          (v || '请选择') + '</option>';
      }).join('') + '</select></div></fieldset>' +

      '<fieldset class="gap"><legend>排期与负荷</legend>' +
      '<textarea class="inp gp-sch-overview" placeholder="一周日程概要（每天课程/活动时段数）">' + SA.esc(sch.overview || '') + '</textarea>' +
      '<div class="row"><label class="sub" for="p5-sch-hours">自由时间（小时/周）</label>' +
      '<input class="inp gp-sch-hours" id="p5-sch-hours" type="number" min="0" step="1" style="width:110px" value="' +
      SA.esc(sch.free_hours_per_week == null ? '' : sch.free_hours_per_week) + '">' +
      '<label class="sub" for="p5-sch-load">负荷评级</label>' +
      '<select class="inp gp-sch-load" id="p5-sch-load" style="width:auto">' +
      ['', '高', '中', '低'].map(function (v) {
        return '<option value="' + v + '"' + ((sch.load_level || '') === v ? ' selected' : '') + '>' +
          (v || '请选择') + '</option>';
      }).join('') + '</select></div></fieldset>' +

      '<fieldset class="gap"><legend>当前目标</legend>' +
      '<input class="inp gp-goal-text" maxlength="200" placeholder="目标描述（≤ 200 字）" value="' +
      SA.esc(goal.text || '') + '">' +
      '<label class="sub" for="p5-goal-judge">学生对目标的认同</label>' +
      '<select class="inp gp-goal-judge" id="p5-goal-judge">' +
      ['', '认同', '部分认同', '不认同'].map(function (v) {
        return '<option value="' + v + '"' + ((goal.judgement || '') === v ? ' selected' : '') + '>' +
          (v || '（未填）') + '</option>';
      }).join('') + '</select>' +
      '<p class="sub">用于 A2 活动场景：认同 → 稳固，部分认同 → 关注，不认同 → 风险。</p></fieldset>' +

      '<fieldset class="gap"><legend>学科状态</legend><div id="p5-subj-rows">' +
      subj.map(subjectRow).join('') + '</div>' +
      '<div><button class="btn" type="button" data-subj-add="1">添加学科</button></div></fieldset>' +

      '<fieldset class="gap"><legend>标准化任务结果</legend>' +
      '<input class="inp gp-st-form" placeholder="任务形式" value="' + SA.esc(st.form || '') + '">' +
      '<label class="sub" for="p5-st-split">能否拆出步骤</label>' +
      '<select class="inp gp-st-split" id="p5-st-split">' +
      triOpts(st.can_split, ['能拆出有序步骤', '拆不出有序步骤'], '能否拆出步骤') + '</select>' +
      '<label class="sub" for="p5-st-commit">能否承诺开始</label>' +
      '<select class="inp gp-st-commit" id="p5-st-commit">' +
      triOpts(st.can_commit, ['能承诺第一步与时间', '不能承诺'], '能否承诺开始') + '</select>' +
      '<label class="sub" for="p5-st-emotion">情绪反应</label>' +
      '<select class="inp gp-st-emotion" id="p5-st-emotion">' +
      ['', '畏难', '烦躁', '无所谓', '正常'].map(function (v) {
        return '<option value="' + v + '"' + ((st.emotion || '') === v ? ' selected' : '') + '>' +
          (v ? '情绪：' + v : '情绪反应') + '</option>';
      }).join('') + '</select></fieldset>' +

      '<div class="row"><button class="btn primary" type="button" data-save-gaps="1">' + btnLabel + '</button>' +
      '<button class="btn ghost" type="button" data-close-drawer="1">取消</button></div>' +
      '</aside>';
  }

  function collectGaps(el) {
    var q = function (sel) { return el.querySelector(sel); };
    var gaps = {};
    var tags = [];
    Array.prototype.forEach.call(el.querySelectorAll('.gp-fam-tag'), function (c) {
      if (c.checked) tags.push(c.value);
    });
    var famText = q('.gp-fam-text');
    var famSrc = q('.gp-fam-source');
    var fam = {
      tags: tags,
      text: famText ? famText.value.trim() : '',
      source: famSrc ? famSrc.value : ''
    };
    if (fam.tags.length || fam.text) gaps.family_complaint = fam;

    var schOverview = q('.gp-sch-overview');
    var schHours = q('.gp-sch-hours');
    var schLoad = q('.gp-sch-load');
    var sch = {
      overview: schOverview ? schOverview.value.trim() : '',
      free_hours_per_week: schHours && schHours.value !== '' ? Number(schHours.value) : null,
      load_level: schLoad ? schLoad.value : ''
    };
    if (sch.overview || sch.free_hours_per_week != null || sch.load_level) gaps.schedule = sch;

    var goalText = q('.gp-goal-text');
    var goalJudge = q('.gp-goal-judge');
    if (goalJudge && goalJudge.value) {
      gaps.goal = {
        text: goalText ? goalText.value.trim().slice(0, 200) : '',
        judgement: goalJudge.value
      };
    }

    var rows = [];
    Array.prototype.forEach.call(el.querySelectorAll('.subj-row'), function (row) {
      var name = row.querySelector('.gp-sj-name').value.trim();
      if (!name) return;
      rows.push({
        subject: name,
        self_level: row.querySelector('.gp-sj-self').value.trim(),
        actual: row.querySelector('.gp-sj-actual').value.trim(),
        gap: row.querySelector('.gp-sj-gap').value
      });
    });
    if (rows.length) gaps.subject_status = rows;

    var stForm = q('.gp-st-form');
    var stSplit = q('.gp-st-split');
    var stCommit = q('.gp-st-commit');
    var stEmotion = q('.gp-st-emotion');
    if (stSplit && triVal(stSplit.value) !== null) {
      gaps.standard_task = {
        form: stForm ? stForm.value.trim() : '',
        can_split: triVal(stSplit.value),
        can_commit: stCommit ? triVal(stCommit.value) : null,
        emotion: stEmotion ? stEmotion.value : ''
      };
    }
    return gaps;
  }

  /* ── 渲染 ───────────────────────────────────────────────── */
  function render(el) {
    if (!state.data) { renderNoSelection(el); return; }
    var data = state.data;
    var cards = cardsOf(data);
    var card = cards[state.dim] || cards.A1;
    if (!card) { renderNoSelection(el); return; }
    el.innerHTML = header(data) + banners(cards) + tiles(data, cards) + orderSteps(data, cards) +
      '<div class="split"><div class="detail">' + detail(card) + '</div>' + rail(cards) + '</div>' +
      drawerHTML();
    bind(el);
  }

  /* ── 动作 ───────────────────────────────────────────────── */
  function replacePayload(el, data) {
    state.data = data;
    state.edit = false;
    render(el);
  }

  function preview(el, qid, result) {
    state.answers[qid] = { q: qid, result: result, text: (state.answers[qid] || {}).text || '' };
    state.preview = {};
    render(el);
    var seq = ++state.previewSeq;
    fetch('/api/reports/' + encodeURIComponent(state.report_id) + '/six-am/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(answersBody())
    }).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (json) {
        if (!json || json.ok === false) throw new Error((json && json.error) || '预览失败');
        return json;
      });
    }).then(function (json) {
      if (seq !== state.previewSeq) return;
      var changes = json.changes || [];
      state.preview[qid] = changes.length ? changes.join('；') : '无变化';
      render(el);
    }).catch(function (err) {
      if (seq !== state.previewSeq) return;
      state.preview[qid] = '预览失败：' + err.message;
      render(el);
    });
  }

  function saveAnswers(el, btn) {
    btn.disabled = true;
    btn.textContent = '保存中…';
    var body = answersBody();
    body.gaps = collectGaps(el);
    fetch('/api/reports/' + encodeURIComponent(state.report_id) + '/six-am/answers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (json) {
        if (!json || json.ok === false) throw new Error((json && json.error) || '保存失败');
        return json;
      });
    }).then(function (json) {
      SA.toast('已生成新版本 v' + json.version);
      SA.go('profile', { report_id: state.report_id, profile_id: json.profile_id });
    }).catch(function (err) {
      btn.disabled = false;
      btn.textContent = '保存并生成新版本';
      SA.toast(err.message, true);
    });
  }

  function saveGaps(el, btn) {
    btn.disabled = true;
    btn.textContent = '保存中…';
    var body = answersBody();
    body.gaps = collectGaps(el);
    fetch('/api/reports/' + encodeURIComponent(state.report_id) + '/six-am/answers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (json) {
        if (!json || json.ok === false) throw new Error((json && json.error) || '保存失败');
        return json;
      });
    }).then(function (json) {
      state.drawer = false;
      SA.toast('已生成新版本 v' + json.version);
      SA.go('profile', { report_id: state.report_id, profile_id: json.profile_id });
    }).catch(function (err) {
      btn.disabled = false;
      btn.textContent = '保存并生成新版本';
      SA.toast(err.message, true);
    });
  }

  function saveActions(el, btn) {
    var nextEl = el.querySelector('.act-edit[data-act="next"]');
    var avoidEl = el.querySelector('.act-edit[data-act="avoid"]');
    var split = function (box) {
      return (box && box.value || '').split('\n').map(function (t) { return t.trim(); })
        .filter(function (t) { return !!t; });
    };
    var next = split(nextEl);
    var avoid = split(avoidEl);
    if (next.length > 8 || avoid.length > 8) { SA.toast('每类最多 8 条', true); return; }
    var tooLong = next.concat(avoid).some(function (t) { return t.length > 300; });
    if (tooLong) { SA.toast('单条最多 300 字', true); return; }
    btn.disabled = true;
    fetch('/api/reports/' + encodeURIComponent(state.report_id) + '/six-am/action-overrides', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        profile_id: state.data.profile_id,
        dim: state.dim,
        next_actions: next,
        avoid_actions: avoid
      })
    }).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (json) {
        if (!json || json.ok === false) throw new Error((json && json.error) || '保存失败');
        return json;
      });
    }).then(function (json) {
      replacePayload(el, json);
      SA.toast('已更新行动建议（版本不变）');
    }).catch(function (err) {
      btn.disabled = false;
      SA.toast(err.message, true);
    });
  }

  function generate(el, btn) {
    btn.disabled = true;
    btn.textContent = '生成中…';
    fetch('/api/reports/' + encodeURIComponent(state.report_id) + '/six-am/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}'
    }).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (json) {
        if (!json || json.ok === false) throw new Error((json && json.error) || '生成失败');
        return json;
      });
    }).then(function (json) {
      SA.go('profile', { report_id: state.report_id, profile_id: json.profile_id });
    }).catch(function (err) {
      btn.disabled = false;
      btn.textContent = '生成档案';
      SA.toast(err.message, true);
    });
  }

  function addSubjectRow() {
    var wrap = document.getElementById('p5-subj-rows');
    if (!wrap) return;
    var div = document.createElement('div');
    div.innerHTML = subjectRow({});
    wrap.appendChild(div.firstChild);
  }

  /* ── 事件 ───────────────────────────────────────────────── */
  function bind(el) {
    if (el.getAttribute('data-sa2-p5-bound')) return;
    el.setAttribute('data-sa2-p5-bound', '1');

    el.addEventListener('click', function (e) {
      var t = e.target.closest('[data-go],[data-retry],[data-gen],[data-review],[data-dim],' +
        '[data-ans],[data-save-answers],[data-open-evidence],[data-close-drawer],' +
        '[data-edit],[data-cancel-edit],[data-save-actions],[data-vpid],' +
        '[data-save-gaps],[data-subj-add],[data-subj-del]');
      if (!t) return;

      if (t.hasAttribute('data-go')) {
        e.preventDefault();
        SA.go(t.getAttribute('data-go'));
        return;
      }
      if (t.hasAttribute('data-retry')) { show(el, { report_id: state.report_id, profile_id: state.profile_id }); return; }
      if (t.hasAttribute('data-gen')) {
        if (!SA.canWrite()) return;
        generate(el, t);
        return;
      }
      if (t.hasAttribute('data-review')) {
        SA.go('review', { report_id: state.report_id });
        return;
      }
      if (t.hasAttribute('data-dim')) {
        state.dim = t.getAttribute('data-dim');
        state.edit = false;
        state.preview = {};
        render(el);
        return;
      }
      if (t.hasAttribute('data-ans')) {
        if (!SA.canWrite()) return;
        preview(el, t.getAttribute('data-ans'), t.getAttribute('data-v'));
        return;
      }
      if (t.hasAttribute('data-save-answers')) {
        if (!SA.canWrite()) return;
        saveAnswers(el, t);
        return;
      }
      if (t.hasAttribute('data-open-evidence')) {
        state.drawer = true;
        render(el);
        var first = el.querySelector('.drawer .inp');
        if (first) first.focus();
        return;
      }
      if (t.hasAttribute('data-close-drawer')) {
        state.drawer = false;
        render(el);
        return;
      }
      if (t.hasAttribute('data-edit')) {
        state.edit = true;
        render(el);
        return;
      }
      if (t.hasAttribute('data-cancel-edit')) {
        state.edit = false;
        render(el);
        return;
      }
      if (t.hasAttribute('data-save-actions')) {
        if (!SA.canWrite()) return;
        saveActions(el, t);
        return;
      }
      if (t.hasAttribute('data-vpid')) {
        SA.go('profile', { report_id: state.report_id, profile_id: t.getAttribute('data-vpid') });
        return;
      }
      if (t.hasAttribute('data-save-gaps')) {
        if (!SA.canWrite()) return;
        saveGaps(el, t);
        return;
      }
      if (t.hasAttribute('data-subj-add')) { addSubjectRow(); return; }
      if (t.hasAttribute('data-subj-del')) {
        var row = t.closest('.subj-row');
        if (row && row.parentNode) row.parentNode.removeChild(row);
        return;
      }
    });

    el.addEventListener('change', function (e) {
      if (e.target.id === 'p5-cmp') {
        state.compare = !!e.target.checked;
        render(el);
      }
    });
  }

  function show(el, params) {
    params = params || {};
    var rid = params.report_id || null;
    var pid = params.profile_id || null;
    state.report_id = rid;
    state.profile_id = pid;
    state.data = null;
    state.drawer = false;
    state.edit = false;
    state.preview = {};
    state.answers = {};
    if (!rid) { renderNoSelection(el); return; }
    load(el, rid, pid);
  }

  SA.views.profile = { show: show };
})();
