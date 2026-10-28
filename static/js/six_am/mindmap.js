/* 6AM v0.6 · 思维导图
   SA.mindmap.dim(model, dimId, state) → 维度树（节点、顺序与 R1 的 MD 导出规则一致）
   SA.mindmap.a6(model, a6state) → 启动支持树
   state = {profile, writable}；规则视图传 null（不淡显、不标本学生）。 */
(function () {
  'use strict';

  var SA = window.SA;
  var LEVELS = ['稳固', '关注', '风险'];
  var CLS = { '稳固': 'sec', '关注': 'watch', '风险': 'risk', '阻塞': 'block' };
  var RESULT_ZH = { confirm: '证实', deny: '未证实', set: '调整为' };

  function esc(s) { return SA.esc(s); }

  function dimOf(model, dimId) {
    var dims = (model && model.dims) || [];
    for (var i = 0; i < dims.length; i += 1) {
      if (dims[i].id === dimId) return dims[i];
    }
    return null;
  }

  function findById(list, key, value) {
    var out = null;
    (list || []).forEach(function (item) {
      if (!out && item && item[key] === value) out = item;
    });
    return out;
  }

  /* ── facts ─────────────────────────────────────────────── */
  function factLine(fact) {
    if (!fact) return '';
    var label = fact.label == null ? '' : String(fact.label);
    var value = fact.value == null ? '' : String(fact.value);
    if (!label && !value && fact.raw == null && fact.norm == null) return '';
    var parts = [];
    if (fact.raw != null) parts.push(String(fact.raw));
    if (fact.norm != null) parts.push('常模 ' + String(fact.norm));
    var detail = value;
    if (parts.length) detail += '（' + parts.join(' / ') + '）';
    return label + '：' + detail;
  }

  function factsPair(facts) {
    var seen = {};
    var lines = [];
    (facts || []).forEach(function (fact) {
      var key = [fact && fact.label, fact && fact.value, fact && fact.raw, fact && fact.norm].join('\u0001');
      if (seen[key]) return;
      seen[key] = true;
      var line = factLine(fact);
      if (line) lines.push(line);
    });
    if (!lines.length) return { html: '', plain: '' };
    return {
      html: '<div class="mm-facts">' + lines.map(function (line) {
        return '<div>' + esc(line) + '</div>';
      }).join('') + '</div>',
      plain: lines.join(' · ')
    };
  }

  /* ── 节点 ───────────────────────────────────────────────── */
  function levelNode(level, text, opts) {
    opts = opts || {};
    var cls = 'mm-node mm-lv ' + CLS[level];
    if (opts.hit) cls += ' is-hit';
    else if (opts.faded) cls += ' is-faded';
    var head = opts.strike ? '<s>' + esc(level) + '</s>' : esc(level);
    var inner = '<b>' + head + '</b>';
    if (text) inner += '<small>' + esc(text) + '</small>';
    if (opts.hit) inner += '<span class="me">本学生</span>';
    if (opts.talkAdjust) inner += '<span class="me alt">会谈调整</span>';
    var fp = factsPair(opts.facts);
    var title = fp.plain ? ' title="' + esc(fp.plain) + '"' : '';
    if (opts.hit) return '<span class="' + cls + '">' + inner + fp.html + '</span>';
    if (fp.html) {
      return '<details class="mm-more"><summary class="' + cls + '"' + title + '>' +
        inner + '</summary>' + fp.html + '</details>';
    }
    return '<span class="' + cls + '"' + title + '>' + inner + '</span>';
  }

  function branchNode(name, note) {
    return '<span class="mm-node mm-branch">' + esc(name) +
      (note ? '<small class="mm-note">' + esc(note) + '</small>' : '') + '</span>';
  }

  function typeNode(name, text, hit, hasProfile) {
    var cls = 'mm-node type';
    if (hit) cls += ' is-hit';
    else if (hasProfile) cls += ' is-faded';
    return '<span class="' + cls + '">' + esc(name) +
      (text ? '<small>' + esc(text) + '</small>' : '') + '</span>';
  }

  function plainNode(cls, html, title) {
    return '<span class="mm-node ' + cls + '"' + (title ? ' title="' + esc(title) + '"' : '') +
      '>' + html + '</span>';
  }

  function textNode(cls, text) {
    return plainNode(cls, esc(text));
  }

  /* ── 会谈记录 ──────────────────────────────────────────── */
  function talkOf(profile, dimId) {
    var talks = ((profile || {}).inputs || {}).talks || {};
    return talks[dimId] || null;
  }

  function causeNames(dim, record) {
    var picked = (record && record.causes) || [];
    return picked.map(function (id) {
      var cause = findById((dim.blocked || {}).causes, 'id', id);
      return cause ? cause.name : id;
    });
  }

  function talkReadOnly(dim, record) {
    var line = RESULT_ZH[record.result] || '';
    if (record.result === 'set' && record.set_level) line += ' ' + record.set_level;
    var names = causeNames(dim, record);
    return '<div class="talk-ro"><b>会谈记录</b><span>' + esc(line) + '</span>' +
      (names.length ? '<span>' + esc(names.join(' · ')) + '</span>' : '') +
      (record.note ? '<span class="note">' + esc(record.note) + '</span>' : '') + '</div>';
  }

  function talkForm(dim, record) {
    var current = record ? record.result : null;
    var causes = ((dim.blocked || {}).causes) || [];
    var picked = (record && record.causes) || [];
    var h = '<div class="talk" data-talk="' + esc(dim.id) + '">' +
      '<div class="tl">会谈记录</div>' +
      '<div class="seg">' +
      ['confirm', 'deny', 'set'].map(function (value) {
        return '<button type="button" data-talk-result="' + value + '" aria-pressed="' +
          (current === value) + '">' + RESULT_ZH[value] + '</button>';
      }).join('') + '</div>';
    h += '<select data-talk-level' + (current === 'set' ? '' : ' hidden') + ' aria-label="调整为">' +
      SA.LEVELS.map(function (level) {
        var selected = (record && record.set_level ? record.set_level : '关注') === level;
        return '<option value="' + esc(level) + '"' + (selected ? ' selected' : '') + '>' +
          esc(level) + '</option>';
      }).join('') + '</select>';
    if (causes.length) {
      h += '<div class="causes">' + causes.map(function (cause) {
        return '<label><input type="checkbox" data-talk-cause="' + esc(cause.id) + '"' +
          (picked.indexOf(cause.id) >= 0 ? ' checked' : '') + '>' + esc(cause.name) + '</label>';
      }).join('') + '</div>';
    }
    h += '<input type="text" data-talk-note placeholder="备注" aria-label="备注" value="' +
      esc(record && record.note ? record.note : '') + '">' +
      '<div class="row"><button type="button" class="btn primary" data-talk-save>保存</button>' +
      '<button type="button" class="btn ghost" data-talk-clear>清除</button></div></div>';
    return h;
  }

  function talkControl(dim, d, profile, state) {
    if (!d) return null;
    var record = talkOf(profile, dim.id);
    var writable = !!(state && state.writable);
    if (!writable) {
      return record ? { extra: talkReadOnly(dim, record), panel: '' } : null;
    }
    if (SA.sev(d.level) < 2 && !record) return null;
    var extra = '';
    if (record) {
      var label = RESULT_ZH[record.result] || '';
      if (record.result === 'set' && record.set_level) label += ' ' + record.set_level;
      extra = '<small>' + esc(label) + '</small>';
    } else {
      extra = '<span class="talk-open">会谈记录</span>';
    }
    return { extra: extra, panel: talkForm(dim, record) };
  }

  /* ── 阻塞链 ────────────────────────────────────────────── */
  function blockedHTML(dim, d, profile, state) {
    var blocked = dim.blocked || {};
    var isBlocked = !!(d && d.blocked);
    var setBlocked = !!(d && d.set_by_talk && d.level === '阻塞');
    var hit = isBlocked || setBlocked;
    var control = talkControl(dim, d, profile, state);
    var via;
    if (control && control.panel) {
      via = '<details class="talk-box"><summary class="mm-node via"><b>' +
        esc(blocked.via || '') + '</b>' + control.extra + '</summary>' + control.panel + '</details>';
    } else {
      via = '<div class="mm-node via"><b>' + esc(blocked.via || '') + '</b>' +
        (control ? control.extra : '') + '</div>';
    }
    var blockedNode = levelNode('阻塞', blocked.name || '', {
      hit: hit,
      faded: !!d && !hit,
      talkAdjust: setBlocked && !isBlocked
    });
    var causes = ((blocked.causes) || []).map(function (cause) {
      var stateRow = d ? findById(d.causes, 'id', cause.id) : null;
      var hinted = !!(stateRow && stateRow.hint === true);
      var picked = !!(stateRow && stateRow.picked);
      var solid = hinted || picked;
      var cls = 'mm-node cause' + (solid ? ' is-hit' : (d ? ' is-faded' : ''));
      var inner = '<b>' + esc(cause.name) + '</b>' +
        (hinted ? '<span class="hint-tag">Y4 提示</span>' : '') +
        (cause.text ? '<small>' + esc(cause.text) + '</small>' : '');
      return '<li><span class="' + cls + '">' + inner + '</span></li>';
    }).join('');
    return '<li>' + via + '<ul><li>' + blockedNode +
      (causes ? '<ul>' + causes + '</ul>' : '') + '</li></ul></li>';
  }

  /* ── 一个 part 的级别节点 ──────────────────────────────── */
  function firstPartAt(dim, d, level) {
    var parts = dim.parts || [];
    for (var i = 0; i < parts.length; i += 1) {
      var row = d && (d.parts || {})[parts[i].id];
      if (row && row.level === level) return parts[i].id;
    }
    return parts.length ? parts[0].id : null;
  }

  function partLevels(dim, part, d, profile, state, attachBlocked, honorSetTalk) {
    var out = '';
    LEVELS.forEach(function (level) {
      var spec = (part.levels || {})[level];
      if (!spec) return;
      var row = d && (d.parts || {})[part.id];
      var setTalk = !!(d && d.set_by_talk && honorSetTalk !== false);
      var modelOnly = !!(d && d.set_by_talk && honorSetTalk === false);
      var hit = false;
      var strike = false;
      if (d && modelOnly) {
        hit = false;
      } else if (d) {
        if (setTalk) {
          hit = d.level === level && firstPartAt(dim, d, d.level) === part.id;
          strike = level === d.model_level && d.level !== d.model_level;
        } else {
          hit = !!row && row.level === level;
        }
      }
      var facts = row && row.nodes && row.nodes[level] ? row.nodes[level].facts : [];
      var node = levelNode(level, spec.text, {
        hit: hit,
        faded: !!d && !hit,
        facts: facts,
        strike: strike,
        talkAdjust: hit && setTalk
      });
      var child = '';
      if (level === '风险' && attachBlocked) {
        child = blockedHTML(dim, d, profile, state);
      }
      out += '<li>' + node + (child ? '<ul>' + child + '</ul>' : '') + '</li>';
    });
    return out;
  }

  /* ── 类型节点 ──────────────────────────────────────────── */
  function dimTypesBranch(dim, d) {
    if (!dim.types || !dim.types.length) return '';
    var names = (d && d.types) || [];
    return '<li>' + branchNode('类型') + '<ul>' + dim.types.map(function (ctype) {
      return '<li>' + typeNode(ctype.name, ctype.text, names.indexOf(ctype.name) >= 0, !!d) + '</li>';
    }).join('') + '</ul></li>';
  }

  function partTypesBranch(part, d) {
    if (!part.types || !part.types.length) return '';
    var names = (d && (d.parts || {})[part.id] ? d.parts[part.id].types : []) || [];
    return '<li>' + branchNode('类型') + '<ul>' + part.types.map(function (ctype) {
      return '<li>' + typeNode(ctype.name, ctype.text, names.indexOf(ctype.name) >= 0, !!d) + '</li>';
    }).join('') + '</ul></li>';
  }

  /* ── 三种布局 ──────────────────────────────────────────── */
  function singleLayout(dim, d, profile, state) {
    var part = (dim.parts || [])[0] || {};
    var h = '<li>' + branchNode('状态') + '<ul>';
    if (dim.intro) h += '<li>' + textNode('intro', dim.intro) + '</li>';
    h += partLevels(dim, part, d, profile, state, true);
    h += '</ul></li>';
    h += dimTypesBranch(dim, d);
    return h;
  }

  function sidesLayout(dim, d, profile, state) {
    var parts = dim.parts || [];
    var blocked = dim.blocked || {};
    var target = blocked.part || (parts.length ? parts[parts.length - 1].id : null);
    var h = '';
    parts.forEach(function (part) {
      h += '<li>' + branchNode(part.name, part.note) + '<ul>';
      h += partLevels(dim, part, d, profile, state, part.id === target);
      h += (part.extra || []).map(function (extra) {
        return '<li>' + textNode('extra', extra) + '</li>';
      }).join('');
      h += partTypesBranch(part, d);
      h += '</ul></li>';
    });
    if (dim.combine_text) h += '<li>' + textNode('extra', dim.combine_text) + '</li>';
    return h;
  }

  function summaryFacts(d, level) {
    var facts = [];
    Object.keys((d && d.parts) || {}).forEach(function (partId) {
      var row = d.parts[partId];
      if (row && row.level === level && row.nodes && row.nodes[level]) {
        facts = facts.concat(row.nodes[level].facts || []);
      }
    });
    return facts;
  }

  function typesLayout(dim, d, profile, state) {
    var summary = dim.summary || {};
    var setTalk = !!(d && d.set_by_talk);
    var h = '<li>' + branchNode('状态') + '<ul>';
    LEVELS.forEach(function (level) {
      if (!summary[level]) return;
      var hit = false;
      var strike = false;
      if (d) {
        hit = setTalk ? d.level === level : d.model_level === level;
        strike = setTalk && level === d.model_level && d.level !== d.model_level;
      }
      var node = levelNode(level, summary[level], {
        hit: hit,
        faded: !!d && !hit,
        facts: summaryFacts(d, level),
        strike: strike,
        talkAdjust: hit && setTalk
      });
      var child = level === '风险' ? blockedHTML(dim, d, profile, state) : '';
      h += '<li>' + node + (child ? '<ul>' + child + '</ul>' : '') + '</li>';
    });
    h += '</ul></li>';

    h += '<li>' + branchNode('类型') + '<ul>';
    var dimNames = (d && d.types) || [];
    (dim.parts || []).forEach(function (part) {
      h += '<li>' + typeNode(part.type_name, part.name,
        dimNames.indexOf(part.type_name) >= 0, !!d) + '<ul>';
      h += partLevels(dim, part, d, profile, state, false, false);
      var refs = ((part.refs || []).map(function (ref) {
        return String((ref && ref.text) || '').trim();
      })).filter(function (text) { return !!text; });
      if (refs.length) {
        h += '<li>' + textNode('ref', '参考：' + refs.join(' · ')) + '</li>';
      }
      h += '</ul></li>';
    });
    (dim.refs || []).forEach(function (ref) {
      var row = d ? findById(d.refs, 'name', ref.name) : null;
      var hinted = !!(row && row.hint === true);
      var label = ref.name ? ref.name + '：' + (ref.text || '') : (ref.text || '');
      var cls = 'ref' + (hinted ? ' is-hit' : (d ? ' is-faded' : ''));
      h += '<li><span class="mm-node ' + cls + '">' + esc(label) + '</span></li>';
    });
    h += '</ul></li>';
    return h;
  }

  function dimTree(model, dimId, state) {
    var dim = dimOf(model, dimId);
    if (!dim) return '';
    var profile = state ? state.profile : null;
    var d = profile ? (((profile.dims || {})[dimId]) || null) : null;
    var children = '';
    if (dim.layout === 'types') children = typesLayout(dim, d, profile, state);
    else if (dim.layout === 'sides') children = sidesLayout(dim, d, profile, state);
    else children = singleLayout(dim, d, profile, state);
    var root = '<span class="mm-node mm-root">' + esc(dim.id) + ' ' + esc(dim.name) + '</span>';
    return '<div class="mm-wrap"><div class="mm"><ul><li>' + root +
      '<ul>' + children + '</ul></li></ul></div></div>';
  }

  /* ── A6 树 ─────────────────────────────────────────────── */
  function a6Detail(item) {
    var detail = String(item.fit_text || '').trim();
    if (String(item.avoid_text || '').trim()) detail += '；' + String(item.avoid_text).trim();
    if (String(item.caution_text || '').trim()) detail += '；' + String(item.caution_text).trim();
    return detail;
  }

  function a6Node(name, detail) {
    return '<span class="mm-node mm-item"><b>' + esc(name) + '</b>' +
      (detail ? '<small>' + esc(detail) + '</small>' : '') + '</span>';
  }

  function a6Tree(model) {
    var a6 = (model && model.a6) || {};
    var items = (a6.items || []).filter(function (item) { return item && typeof item === 'object'; });
    var h = '<li>' + branchNode(a6.y4_title || '') + '<ul>';
    (a6.groups || []).forEach(function (group) {
      h += '<li>' + branchNode(group) + '<ul>';
      items.forEach(function (item) {
        var detail = a6Detail(item);
        if (item.group !== group || !String(item.fit_text || '').trim()) return;
        h += '<li>' + a6Node(item.name, detail) + '</li>';
      });
      h += '</ul></li>';
    });
    h += '</ul></li>';

    h += '<li>' + branchNode(a6.dims_title || '') + '<ul>';
    (a6.dims_order || []).forEach(function (label) {
      h += '<li>' + branchNode(label) + '<ul>';
      items.forEach(function (item) {
        var link = findById(item.links, 'label', label);
        if (!link) return;
        h += '<li>' + a6Node(item.name, link.note || '') + '</li>';
      });
      var cautions = items.filter(function (item) {
        return findById(item.caution, 'label', label);
      }).map(function (item) { return item.name; });
      if (cautions.length) {
        h += '<li>' + textNode('extra', '慎用：' + cautions.join(' · ')) + '</li>';
      }
      h += '</ul></li>';
    });
    h += '</ul></li>';

    var root = '<span class="mm-node mm-root">A6 ' + esc(a6.name || '') + '</span>';
    return '<div class="mm-wrap"><div class="mm"><ul><li>' + root +
      '<ul>' + h + '</ul></li></ul></div></div>';
  }

  SA.mindmap = {
    dim: function (model, dimId, state) { return dimTree(model, dimId, state); },
    a6: function (model, a6state) { return a6Tree(model, a6state); }
  };
})();
