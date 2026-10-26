/* 6AM 2.0 · 评审会：按紧急度排队、逐项记录团队结论、键盘切换与会议纪要。 */
(function () {
  'use strict';

  var SA = window.SA;

  var DIM_ZH = { A1: '自主感', A2: '认同感', A3: '可用空间', A4: '胜任信心', A5: '可起步性' };
  var DIM_KEYS = ['A1', 'A2', 'A3', 'A4', 'A5'];
  var STATE_KEYS = ['Secure', 'Watch', 'At-Risk', 'Blocked'];
  var RANK = { Secure: 0, Watch: 1, 'At-Risk': 2, Blocked: 3 };
  var VERDICT_ZH = { agree: '同意', adjust: '调整状态', evidence: '证据不足，需追问' };

  var state = {
    el: null,
    items: [],
    index: 0,
    compare: false,
    profiles: {},
    drafts: {},
    session: {},
    sessionOrder: [],
    minutesOpen: false
  };

  function current() { return state.items[state.index] || null; }
  function keyOf(it) { return it.s.report_id + ':' + it.dim; }
  function num(v) {
    if (v == null || v === '') return '';
    var n = Number(v);
    if (!isFinite(n)) return String(v);
    return String(Math.round(n * 10) / 10);
  }

  /* ── 队列 ───────────────────────────────────────────────── */
  function buildQueue(students) {
    var q = [];
    (students || []).forEach(function (s) {
      DIM_KEYS.forEach(function (k) {
        var st = s.states && s.states[k];
        if (st === 'At-Risk' || st === 'Blocked') q.push({ s: s, dim: k });
      });
    });
    q.sort(function (a, b) {
      var sa = a.s.safety ? 1 : 0;
      var sb = b.s.safety ? 1 : 0;
      if (sa !== sb) return sb - sa;
      var ra = RANK[(a.s.states || {})[a.dim]] || 0;
      var rb = RANK[(b.s.states || {})[b.dim]] || 0;
      if (ra !== rb) return rb - ra;
      var na = String(a.s.name || '');
      var nb = String(b.s.name || '');
      if (na !== nb) return na < nb ? -1 : 1;
      return a.dim < b.dim ? -1 : 1;
    });
    return q;
  }

  function doneCount() {
    return state.items.filter(function (it) {
      var r = (it.s.reviews || {})[it.dim];
      return !!(r && r.verdict);
    }).length;
  }

  /* ── 草稿 ───────────────────────────────────────────────── */
  function draftFor(it) {
    var key = keyOf(it);
    var d = state.drafts[key];
    if (!d) {
      var r = (it.s.reviews || {})[it.dim] || {};
      d = state.drafts[key] = {
        v: r.verdict || '',
        to: r.adjusted_state || 'At-Risk',
        note: r.note || '',
        owner: r.owner || '',
        due: r.due_date || ''
      };
    }
    return d;
  }

  /* ── 指标条 ─────────────────────────────────────────────── */
  function meter(ind) {
    if (ind.text) {
      return '<div class="meter"></div><div class="val">' + SA.esc(ind.text) + '</div>';
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

  function cardFor(it) {
    var p = state.profiles[it.s.report_id];
    if (!p || p.error) return null;
    var cards = (p.view_model && p.view_model.cards) || [];
    for (var i = 0; i < cards.length; i++) {
      if (cards[i].dim === it.dim) return cards[i];
    }
    return null;
  }

  function fetchProfile(it, el) {
    var rid = it.s.report_id;
    if (Object.prototype.hasOwnProperty.call(state.profiles, rid)) return;
    state.profiles[rid] = null;
    fetch('/api/reports/' + encodeURIComponent(rid) + '/six-am', { headers: { Accept: 'application/json' } })
      .then(function (res) {
        return res.json().catch(function () { return null; }).then(function (json) {
          if (!json || json.ok === false) throw new Error((json && json.error) || ('请求失败（HTTP ' + res.status + '）'));
          return json;
        });
      })
      .then(function (json) {
        state.profiles[rid] = json;
        if (state.el) render(state.el);
      })
      .catch(function (err) {
        state.profiles[rid] = { error: err.message };
        if (state.el) render(state.el);
      });
  }

  /* ── 阶段 ───────────────────────────────────────────────── */
  function stageHTML(it) {
    var s = it.s;
    var dim = it.dim;
    var st = (s.states || {})[dim];
    var ev = (s.evidence || {})[dim];
    var subtype = (s.subtypes || {})[dim];
    var d = draftFor(it);
    var writable = SA.canWrite();
    var total = state.items.length;

    var h = '<section class="card pad stage" aria-live="polite">' +
      '<div class="row"><span class="sub">' + (state.index + 1) + ' / ' + total + '</span>' +
      '<span class="spacer"></span>' +
      '<button class="btn" type="button" data-step="-1" aria-label="上一项">← 上一项</button>' +
      '<button class="btn" type="button" data-step="1" aria-label="下一项">下一项 →</button></div>' +
      '<div class="row"><h2 style="font-size:17px">' + SA.esc(s.name) + ' · ' + dim + ' ' +
      SA.esc(DIM_ZH[dim] || '') + '</h2>' + SA.pill(st) +
      SA.ev(ev) + (subtype ? '<span class="tag">' + SA.esc(subtype) + '</span>' : '') + '</div>';

    var prev = s.previous_states && s.previous_states[dim];
    if (state.compare && prev && prev !== st) {
      h += '<p class="cmp">上一版：<s>' + SA.esc(SA.STATE_ZH[prev] || prev) + '</s> → 当前：' +
        SA.esc(SA.STATE_ZH[st] || st) + '</p>';
    }
    if (s.safety && dim === 'A3') {
      h += '<div class="banner safety"><b>情绪安全复核</b><p>先确认谁负责了解近况、是否需要建议专业评估。</p></div>';
    }

    var p = state.profiles[s.report_id];
    if (p === undefined || p === null) {
      fetchProfile(it, state.el);
      h += '<p class="sub">加载中…</p>';
    } else if (p.error) {
      h += '<p class="sub">档案加载失败：' + SA.esc(p.error) + '</p>';
    } else {
      var card = cardFor(it);
      if (card) {
        if (card.verdict) h += '<p class="big">' + SA.esc(card.verdict) + '</p>';
        var r = card.rationale;
        if (r && r.level_reason) h += '<p class="reason">' + SA.esc(r.level_reason) + '</p>';
        var inds = (r && r.indicators) || [];
        if (inds.length) {
          h += '<div style="display:flex;flex-direction:column;gap:8px">' +
            inds.map(function (i) {
              return '<div class="ind"><div class="nm">' + SA.esc(i.point) + '</div>' + meter(i) + '</div>';
            }).join('') + '</div>';
        }
      }
    }

    h += controlsHTML(it, d, writable);
    return h + '</section>';
  }

  function controlsHTML(it, d, writable) {
    var h = '<div class="decide"><h3>团队结论</h3>';
    if (!writable) {
      var r = (it.s.reviews || {})[it.dim];
      if (r && r.verdict) {
        h += '<p>' + SA.esc(VERDICT_ZH[r.verdict] || r.verdict) +
          (r.verdict === 'adjust' && r.adjusted_state
            ? '为 ' + SA.esc(SA.STATE_ZH[r.adjusted_state] || r.adjusted_state) : '') + '</p>' +
          (r.note ? '<p class="sub">理由：' + SA.esc(r.note) + '</p>' : '') +
          '<p class="sub">' + [r.owner ? '负责人：' + SA.esc(r.owner) : '',
            r.due_date ? '截止：' + SA.esc(r.due_date) : '',
            r.author ? '记录：' + SA.esc(r.author) : ''].filter(Boolean).join(' · ') + '</p>';
      } else {
        h += '<p class="sub">尚无团队结论。</p>';
      }
      return h + '</div>';
    }

    h += '<div class="seg" role="group" aria-label="团队结论">' +
      [['agree', '同意'], ['adjust', '调整状态'], ['evidence', '证据不足，需追问']].map(function (o) {
        return '<button type="button" data-dec="' + o[0] + '" aria-pressed="' + (d.v === o[0]) + '">' +
          o[1] + '</button>';
      }).join('') + '</div>';
    if (d.v === 'adjust') {
      h += '<div class="row"><label class="sub" for="p5-adj">调整为</label>' +
        '<select id="p5-adj" class="btn" data-f="adj">' + STATE_KEYS.map(function (k) {
          return '<option value="' + k + '"' + (d.to === k ? ' selected' : '') + '>' +
            SA.esc(SA.STATE_ZH[k]) + '</option>';
        }).join('') + '</select></div>';
    }
    h += '<label class="sub" for="p5-note">理由与跟进</label>' +
      '<textarea id="p5-note" data-f="note" placeholder="例：同意。下次会谈由王老师追问 Q1.4，10/30 前回填。">' +
      SA.esc(d.note) + '</textarea>' +
      '<div class="row"><label class="sub" for="p5-owner">负责人</label>' +
      '<input id="p5-owner" class="btn" type="text" data-f="owner" style="width:150px" value="' + SA.esc(d.owner) + '">' +
      '<label class="sub" for="p5-due">截止日期</label>' +
      '<input id="p5-due" class="btn" type="date" data-f="due" style="width:160px" value="' + SA.esc(d.due) + '">' +
      '<span class="spacer"></span>' +
      '<button class="btn primary" type="button" data-save-review="1">保存结论</button>' +
      '<span class="sub" data-save-msg></span></div>';
    return h + '</div>';
  }

  /* ── 纪要 ───────────────────────────────────────────────── */
  function minutesText() {
    if (!state.sessionOrder.length) return '还没有形成结论的条目。';
    var lines = ['6AM 评审会纪要'];
    state.sessionOrder.forEach(function (k, i) {
      var x = state.session[k];
      var verdict = x.verdict === 'adjust'
        ? '调整为 ' + (SA.STATE_ZH[x.to] || x.to)
        : (VERDICT_ZH[x.verdict] || x.verdict);
      var line = (i + 1) + '. ' + x.name + ' · ' + x.dim + ' ' + (DIM_ZH[x.dim] || '') + '：' + verdict;
      if (x.note) line += '；理由：' + x.note;
      if (x.owner) line += '；负责人：' + x.owner;
      if (x.due) line += '；截止：' + x.due;
      lines.push(line);
    });
    return lines.join('\n');
  }

  function minutesHTML() {
    var text = minutesText();
    return '<section class="card pad" style="display:flex;flex-direction:column;gap:10px">' +
      '<div class="row"><h2>会议纪要</h2><span class="spacer"></span>' +
      '<button class="btn" type="button" data-copy-minutes="1">复制纪要</button>' +
      '<button class="btn ghost" type="button" data-minutes="1">收起</button></div>' +
      '<pre class="minutes-box" id="p5-min-text">' + SA.esc(text) + '</pre></section>';
  }

  function copyMinutes(el) {
    var box = el.querySelector('#p5-min-text');
    if (!box) return;
    var text = box.textContent;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        SA.toast('已复制会议纪要');
      }).catch(function () { selectNode(box); });
    } else {
      selectNode(box);
    }
  }
  function selectNode(box) {
    var range = document.createRange();
    range.selectNodeContents(box);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    SA.toast('已选中纪要，请按 ⌘C 复制');
  }

  /* ── 渲染 ───────────────────────────────────────────────── */
  function render(el) {
    state.el = el;
    if (!state.items.length) {
      el.innerHTML = '<div class="row"><div><h1>评审会</h1>' +
        '<p class="sub">本次 0 项 · 排序：安全复核 → 阻塞 → 风险</p></div></div>' +
        '<div class="card pad"><p class="sub">没有待评审的条目。所有风险以上的维度都已稳固，或还没有 6AM 档案。</p></div>';
      bind(el);
      return;
    }
    var total = state.items.length;
    var done = doneCount();
    var anyPrev = state.items.some(function (it) { return !!it.s.previous_states; });
    var h = '<div class="row"><div><h1>评审会</h1><p class="sub">本次 ' + total +
      ' 项 · 已形成结论 ' + done + ' 项 · 排序：安全复核 → 阻塞 → 风险</p></div>' +
      '<span class="spacer"></span>';
    if (anyPrev) {
      h += '<label class="row" style="gap:6px;font-size:12.5px;color:var(--muted)">' +
        '<input type="checkbox" id="p5-rv-cmp"' + (state.compare ? ' checked' : '') + '> 对照上一版</label>';
    }
    h += '<button class="btn" type="button" data-minutes="1">会议纪要</button></div>';
    h += '<div class="progress" aria-hidden="true"><span style="width:' +
      (total ? Math.round(done / total * 100) : 0) + '%"></span></div>';
    if (state.minutesOpen) h += minutesHTML();

    h += '<div class="rv"><nav class="card queue" aria-label="评审队列">' + state.items.map(function (it, i) {
      var st = (it.s.states || {})[it.dim];
      var r = (it.s.reviews || {})[it.dim];
      return '<button type="button" data-rv="' + i + '" aria-current="' + (i === state.index) + '">' +
        '<div class="qh"><b>' + SA.esc(it.s.name) + ' · ' + it.dim + ' ' +
        SA.esc(DIM_ZH[it.dim] || '') + '</b>' + (r && r.verdict ? '<span class="done">✓</span>' : '') + '</div>' +
        '<div class="row" style="gap:6px">' + SA.pill(st) + SA.ev((it.s.evidence || {})[it.dim]) +
        (it.s.safety && it.dim === 'A3' ? '<span class="flag">安全复核</span>' : '') + '</div></button>';
    }).join('') + '</nav>';
    h += stageHTML(current()) + '</div>';
    el.innerHTML = h;
    bind(el);
  }

  /* ── 保存结论 ───────────────────────────────────────────── */
  function saveReview(el, btn) {
    var it = current();
    if (!it) return;
    var d = draftFor(it);
    if (!d.v) { SA.toast('请先选择团队结论', true); return; }
    if (d.v === 'adjust' && !d.to) { SA.toast('请选择调整后的状态', true); return; }
    btn.disabled = true;
    var msg = el.querySelector('[data-save-msg]');
    if (msg) msg.textContent = '保存中…';
    var body = {
      profile_id: it.s.profile_id,
      dim: it.dim,
      verdict: d.v,
      note: d.note.trim(),
      owner: d.owner.trim(),
      due_date: d.due.trim()
    };
    if (d.v === 'adjust') body.adjusted_state = d.to;
    fetch('/api/reports/' + encodeURIComponent(it.s.report_id) + '/six-am/reviews', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (json) {
        if (!json || json.ok === false) throw new Error((json && json.error) || '保存失败');
        return json;
      });
    }).then(function (json) {
      if (!it.s.reviews) it.s.reviews = {};
      it.s.reviews[it.dim] = json.review || {
        verdict: body.verdict, adjusted_state: body.adjusted_state || null,
        note: body.note, owner: body.owner, due_date: body.due_date
      };
      var key = keyOf(it);
      if (!state.session[key]) state.sessionOrder.push(key);
      state.session[key] = {
        name: it.s.name, dim: it.dim, verdict: body.verdict,
        to: body.adjusted_state, note: body.note, owner: body.owner, due: body.due_date
      };
      if (state.index < state.items.length - 1) state.index += 1;
      render(el);
      SA.toast('已记录团队结论');
    }).catch(function (err) {
      btn.disabled = false;
      if (msg) msg.textContent = '';
      SA.toast(err.message, true);
    });
  }

  function step(delta) {
    var next = state.index + delta;
    if (next < 0) next = 0;
    if (next > state.items.length - 1) next = state.items.length - 1;
    state.index = next;
  }

  /* ── 事件 ───────────────────────────────────────────────── */
  function bind(el) {
    if (el.getAttribute('data-sa2-rv-bound')) return;
    el.setAttribute('data-sa2-rv-bound', '1');

    el.addEventListener('click', function (e) {
      var t = e.target.closest('[data-rv],[data-step],[data-dec],[data-save-review],' +
        '[data-minutes],[data-copy-minutes]');
      if (!t) return;
      if (t.hasAttribute('data-rv')) {
        state.index = parseInt(t.getAttribute('data-rv'), 10) || 0;
        render(el);
        return;
      }
      if (t.hasAttribute('data-step')) {
        step(parseInt(t.getAttribute('data-step'), 10) || 0);
        render(el);
        return;
      }
      if (t.hasAttribute('data-dec')) {
        var it = current();
        if (!it) return;
        var d = draftFor(it);
        d.v = t.getAttribute('data-dec');
        render(el);
        return;
      }
      if (t.hasAttribute('data-save-review')) {
        if (!SA.canWrite()) return;
        saveReview(el, t);
        return;
      }
      if (t.hasAttribute('data-minutes')) {
        state.minutesOpen = !state.minutesOpen;
        render(el);
        return;
      }
      if (t.hasAttribute('data-copy-minutes')) {
        copyMinutes(el);
        return;
      }
    });

    el.addEventListener('change', function (e) {
      if (e.target.id === 'p5-rv-cmp') {
        state.compare = !!e.target.checked;
        render(el);
        return;
      }
      if (e.target.getAttribute('data-f') === 'adj') {
        var it = current();
        if (it) draftFor(it).to = e.target.value;
      }
    });

    el.addEventListener('input', function (e) {
      var f = e.target.getAttribute('data-f');
      if (!f || f === 'adj') return;
      var it = current();
      if (!it) return;
      var d = draftFor(it);
      if (f === 'note') d.note = e.target.value;
      else if (f === 'owner') d.owner = e.target.value;
      else if (f === 'due') d.due = e.target.value;
    });
  }

  /* ← → 切换；输入时不拦截 */
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    var sec = document.getElementById('sa2-review');
    if (!sec || sec.hidden || !state.items.length) return;
    var t = e.target || {};
    var tag = String(t.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || t.isContentEditable) return;
    e.preventDefault();
    step(e.key === 'ArrowLeft' ? -1 : 1);
    render(sec);
  });

  /* ── 加载 ───────────────────────────────────────────────── */
  function load(el, params) {
    var rid = params && params.report_id ? String(params.report_id) : null;
    el.innerHTML = '<div class="card pad"><p class="sub">加载中…</p></div>';
    SA.api('/api/six-am/cohort').then(function (data) {
      state.items = buildQueue(data.students || []);
      var start = 0;
      if (rid) {
        for (var i = 0; i < state.items.length; i++) {
          if (String(state.items[i].s.report_id) === rid) { start = i; break; }
        }
      }
      state.index = Math.max(0, Math.min(start, state.items.length - 1));
      render(el);
    }).catch(function (err) {
      SA.toast(err.message, true);
      el.innerHTML = '<div class="card pad" style="display:flex;flex-direction:column;gap:10px">' +
        '<p class="sub">' + SA.esc(err.message) + '</p>' +
        '<div><button class="btn" type="button" data-retry-rv="1">重试</button></div></div>';
      var btn = el.querySelector('[data-retry-rv]');
      if (btn) btn.addEventListener('click', function () { load(el, params); });
    });
  }

  function show(el, params) {
    params = params || {};
    state.el = el;
    state.profiles = {};
    state.drafts = {};
    state.minutesOpen = false;
    load(el, params);
  }

  SA.views.review = { show: show };
})();
