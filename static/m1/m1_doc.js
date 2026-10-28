/* =========================================================================
   M1 文档渲染器（workspace / print 共用）
   输入：doc JSON（README §4）+ 知识库 + Y4 证据快照 + prep。
   - 所有块文本一律用 textContent 注入，绝不拼接 HTML。
   - mode: 'edit'（可编辑 + AI/已修改/导师 标记）| 'print'（无标记、只读）。
   ========================================================================= */
(function () {
  'use strict';

  var DIM_FALLBACK = {
    R1: { en: 'Recognize', zh: '识别' },
    R2: { en: 'Regulate', zh: '调节' },
    R3: { en: 'Relate', zh: '连接' },
    R4: { en: 'Recover', zh: '恢复' }
  };

  function h(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  function add(parent, node) { if (node) parent.appendChild(node); return node; }

  function text(parent, value) {
    if (value === undefined || value === null || value === '') return parent;
    parent.appendChild(document.createTextNode(String(value)));
    return parent;
  }

  function strong(parent, value) {
    parent.appendChild(h('b', 'k', value));
    return parent;
  }

  function p(textValue, cls) {
    return h('p', cls || '', textValue);
  }

  function heading(level, value, cls) {
    return h('h' + level, cls || '', value);
  }

  function table(headers, widths) {
    var t = h('table', 't');
    var thead = h('thead');
    var tr = h('tr');
    headers.forEach(function (label, i) {
      var th = h('th', '', label);
      if (widths && widths[i]) th.style.width = widths[i];
      tr.appendChild(th);
    });
    thead.appendChild(tr);
    t.appendChild(thead);
    var body = h('tbody');
    t.appendChild(body);
    return { el: t, body: body };
  }

  function row(tbody) {
    var tr = h('tr');
    tbody.appendChild(tr);
    return tr;
  }

  function cell(tr, contents) {
    var td = h('td');
    if (Array.isArray(contents)) {
      contents.forEach(function (item) {
        if (item === null || item === undefined) return;
        td.appendChild(typeof item === 'string' ? document.createTextNode(item) : item);
      });
    } else if (contents !== undefined && contents !== null) {
      td.appendChild(typeof contents === 'string'
        ? document.createTextNode(contents) : contents);
    }
    tr.appendChild(td);
    return td;
  }

  function callout(emoji, bold, body, gray) {
    var box = h('div', 'call' + (gray ? ' gray' : ''));
    box.appendChild(h('span', 'e', emoji)).setAttribute('aria-hidden', 'true');
    var content = h('div');
    content.appendChild(h('b', '', bold));
    if (body) {
      String(body).split('\n').forEach(function (line) {
        content.appendChild(h('br'));
        text(content, line);
      });
    }
    box.appendChild(content);
    return box;
  }

  function fmtDate(value) {
    if (!value) return '';
    return String(value).slice(0, 10);
  }

  function fmtDT(value) {
    if (!value) return '';
    var date = new Date(value);
    if (isNaN(date.getTime())) return String(value).slice(0, 16).replace('T', ' ');
    function p2(n) { return (n < 10 ? '0' : '') + n; }
    return date.getFullYear() + '-' + p2(date.getMonth() + 1) + '-' + p2(date.getDate()) +
      ' ' + p2(date.getHours()) + ':' + p2(date.getMinutes());
  }

  function markerLabel(block) {
    if (!block) return '';
    var origin = block.origin || 'ai';
    if (origin === 'mentor') {
      return block.ai_text ? '已修改' : '导师';
    }
    return 'AI';
  }

  function markerClass(block) {
    var origin = block.origin || 'ai';
    if (origin !== 'mentor') return 'mk';
    return block.ai_text ? 'mk ed' : 'mk me';
  }

  /* ---------- 块 ---------- */
  function blockNode(parent, block, opts) {
    if (!block || typeof block !== 'object') {
      parent.appendChild(h('div', 'blk', ''));
      return null;
    }
    var node = h('div', 'blk');
    node.textContent = block.text || '';
    node.setAttribute('data-bid', block.id || '');
    if (opts.mode === 'edit') {
      node.setAttribute('contenteditable', 'true');
      node.addEventListener('input', function () {
        var value = readText(node);
        block.text = value;
        block.origin = 'mentor';
        var mk = node.parentNode ? node.parentNode.querySelector(
          '.mk[data-mk="' + (block.id || '') + '"]') : null;
        if (mk) {
          mk.className = markerClass(block);
          mk.textContent = markerLabel(block);
        }
        if (opts.onEdit) opts.onEdit(block.id, value, node);
      });
      node.addEventListener('paste', function (event) {
        // 粘贴一律转为纯文本，避免外部 HTML 进入文档。
        event.preventDefault();
        var plain = (event.clipboardData || window.clipboardData).getData('text/plain');
        document.execCommand('insertText', false, plain);
      });
    }
    parent.appendChild(node);
    if (opts.mode === 'edit' || opts.mode === 'read') {
      var mk = h('span', markerClass(block), markerLabel(block));
      mk.setAttribute('contenteditable', 'false');
      mk.setAttribute('data-mk', block.id || '');
      parent.appendChild(mk);
    }
    return node;
  }

  // a block plus its AI / 已修改 / 导师 marker in one wrapper, for table cells
  // (blockNode appends both to its parent; returning only the node dropped the marker)
  function blockWrap(block, opts) {
    var wrap = h('div');
    blockNode(wrap, block, opts);
    return wrap;
  }

  function readText(node) {
    var value = node.innerText !== undefined ? node.innerText : node.textContent;
    return String(value || '').replace(/\u00a0/g, ' ').replace(/\n+$/, '');
  }

  function insuf(parent, value) {
    return parent.appendChild(h('span', 'insuf', value));
  }

  function findBlock(doc, id) {
    var found = null;
    (function walk(value) {
      if (found || !value) return;
      if (Array.isArray(value)) { value.forEach(walk); return; }
      if (typeof value !== 'object') return;
      if (value.id === id && typeof value.text === 'string') { found = value; return; }
      Object.keys(value).forEach(function (key) { walk(value[key]); });
    })(doc);
    return found;
  }

  /* ---------- 各部分 ---------- */
  function metaOf(doc, prep) {
    var meta = (doc && doc.meta) || {};
    var merged = {};
    ['student', 'grade', 'school', 'meeting_date', 'mentor', 'duration', 'people']
      .forEach(function (key) {
        var fromDoc = meta[key];
        if (fromDoc === undefined || fromDoc === null || fromDoc === '' ||
            (Array.isArray(fromDoc) && !fromDoc.length)) {
          merged[key] = prep ? (prep[key] !== undefined ? prep[key] : '') : '';
        } else {
          merged[key] = fromDoc;
        }
      });
    merged.duration = parseInt(merged.duration, 10) || 60;
    merged.people = Array.isArray(merged.people) ? merged.people : [];
    return merged;
  }

  function agendaRows(fixed, duration) {
    var base = (fixed && fixed.agenda_60) || [];
    if (!base.length) return [];
    var times;
    if (duration === 60) times = ['5 min', '10 min', '30 min', '10 min', '5 min'];
    else times = ['8 min', '10 min', (duration === 75 ? '42' : '55') + ' min',
                  (duration === 75 ? '10' : '12') + ' min', '5 min'];
    return base.map(function (item, i) {
      return {
        segment: item.segment, time: times[i] || item.time, task: item.task
      };
    });
  }

  function partOne(root, data, meta, opts) {
    var kb = data.kb || {};
    var fixed = data.fixed || {};
    root.appendChild(heading(2, 'Part 1｜Meeting Overview & Sources'));
    root.appendChild(heading(3, '1.1｜Meeting Overview 基本信息与会议结构'));

    var info = h('p');
    strong(info, '基本信息：');
    text(info, [meta.student, meta.grade, meta.school].filter(Boolean).join(' · '));
    text(info, ' · 会议日期 ' + (meta.meeting_date || '未安排'));
    text(info, ' · M1 Mentor ' + (meta.mentor || '未指定'));
    text(info, ' · 预计会议时长 ' + meta.duration + ' 分钟');
    text(info, ' · 参会人员 ' + (meta.people.length ? meta.people.join('、') : '未填写'));
    root.appendChild(info);

    root.appendChild(h('div', 'lbl', '固定结构｜从会前准备到最终反馈'));
    var structure = table(['环节', '核心任务', '预期输出'], ['24%', '', '30%']);
    (fixed.structure_rows || []).forEach(function (item) {
      var tr = row(structure.body);
      cell(tr, item.stage);
      cell(tr, item.task);
      cell(tr, item.output);
    });
    root.appendChild(structure.el);

    root.appendChild(h('div', 'lbl',
      '学生 First Meeting 固定流程（' +
      (meta.duration === 60 ? '建议标准版 60 分钟' : '延长版 ' + meta.duration + ' 分钟') + '）'));
    var agenda = table(['环节', '时间', '主要任务'], ['30%', '14%']);
    agendaRows(fixed, meta.duration).forEach(function (item) {
      var tr = row(agenda.body);
      cell(tr, item.segment);
      cell(tr, item.time);
      cell(tr, item.task);
    });
    root.appendChild(agenda.el);

    root.appendChild(callout('💡', '会议原则：', fixed.principle_callout));

    root.appendChild(heading(3, '1.2｜Sources & Completeness 会前资料来源与完整性'));
    var sources = table(['Evidence Source', '会前提取信息', '资料状态'], ['20%', '', '28%']);
    (data.doc.sources || []).forEach(function (item) {
      var tr = row(sources.body);
      cell(tr, item.label || item.key || '');
      var td = cell(tr, []);
      var value = (item.extracted || {}).text || '';
      if (item.key === 'other' && /尚未取得/.test(value)) {
        insuf(td, '尚未取得相关资料');
      } else {
        blockNode(td, item.extracted, opts);
      }
      cell(tr, item.status_text || '');
    });
    root.appendChild(sources.el);
  }

  function partTwo(root, data, opts) {
    var doc = data.doc;
    var kb = data.kb || {};
    var fixed = data.fixed || {};
    var dims = {};
    (kb.dims || []).forEach(function (d) { dims[d.id] = d; });

    root.appendChild(heading(2, 'Part 2｜R4 初步情绪力画像 Preliminary Emotional Profile'));
    root.appendChild(heading(3, '2.1｜R4 Initial Assessment 四维初步画像'));
    var tableDims = table(['R4 维度', 'Potential 初步线索', 'Interference 初步线索', 'Key Evidence Gap'],
      ['15%', '', '', '22%']);
    (doc.dims || []).forEach(function (item) {
      var dim = dims[item.dim] || DIM_FALLBACK[item.dim] || { en: '', zh: '' };
      var tr = row(tableDims.body);
      cell(tr, item.dim + '｜' + [dim.en, dim.zh].filter(Boolean).join(' '));
      cell(tr, [blockWrap(item.potential, opts)]);
      cell(tr, [blockWrap(item.interference, opts)]);
      cell(tr, [blockWrap(item.gap, opts)]);
    });
    root.appendChild(tableDims.el);

    var priority = doc.priority || [];
    root.appendChild(heading(3, '2.2｜Priority R4 Abilities 会议重点确认能力'));
    root.appendChild(p('本次建议优先确认 ' + priority.length + ' 项能力。' +
      (fixed.priority_note || '')));
    if (priority.length) {
      var tablePri = table(['重点', 'R4 能力', '原始 Evidence / VERDICT', '初步假设', '为什么本次需要确认'],
        ['9%', '15%', '30%', '', '21%']);
      priority.forEach(function (item) {
        var ability = abilityOf(kb, item.code);
        var tr = row(tablePri.body);
        cell(tr, '☑️');
        cell(tr, item.code + ' ' + (ability ? ability.name : ''));
        var evidenceTd = cell(tr, []);
        (item.evidence || []).forEach(function (line, i) {
          if (i) evidenceTd.appendChild(h('br'));
          text(evidenceTd, line);
        });
        cell(tr, [blockWrap(item.hypothesis, opts)]);
        cell(tr, [blockWrap(item.why, opts)]);
      });
      root.appendChild(tablePri.el);
    } else {
      root.appendChild(p('本次未选择重点确认能力。', 'insuf'));
    }

    root.appendChild(heading(3, '2.3｜Evidence Conflicts & Special Attention'));
    var spec = table(['类型', '已发现的线索', '处理方式'], ['24%', '', '28%']);
    [
      ['conflict', 'Evidence Conflicts｜证据不一致', '进入 Part 3 情境 1 的核实安排，避免择一当作事实'],
      ['context', 'Contextual Factors｜环境与情境', '将情境因素与学生能力分开描述'],
      ['attention', 'Special Attention｜特别关注', '普通不确定性，保留']
    ].forEach(function (item) {
      var tr = row(spec.body);
      cell(tr, item[1]);
      cell(tr, [blockWrap((doc.special || {})[item[0]], opts)]);
      cell(tr, item[2]);
    });
    root.appendChild(spec.el);
  }

  function partThree(root, data, opts) {
    var doc = data.doc;
    var kb = data.kb || {};
    var fixed = data.fixed || {};

    root.appendChild(heading(2, 'Part 3｜First Meeting Preparation'));
    root.appendChild(heading(3, '3.1｜R4 Quick Check 四维快速核实'));
    var quick = table(['R4 维度', '建议开放式切入问题', '目标'], ['15%', '', '32%']);
    (fixed.quick_check || []).forEach(function (item) {
      var tr = row(quick.body);
      cell(tr, item.dim);
      cell(tr, item.question);
      cell(tr, item.goal);
    });
    root.appendChild(quick.el);
    root.appendChild(p(fixed.quick_check_note || ''));

    var events = (doc.events || []).filter(function (e) {
      return (e.abilities || []).length;
    });
    root.appendChild(heading(3, '3.2｜Event-based Exploration 重点事件深入探索'));
    if (events.length) {
      var evTable = table(['重点情境', '已有线索及来源', '关联的 Priority R4 能力',
        '需要核实的 Evidence Gap', '建议追问'], ['15%', '22%', '15%', '18%', '']);
      events.forEach(function (item) {
        var tr = row(evTable.body);
        cell(tr, [blockWrap(item.title, opts)]);
        cell(tr, item.clue || '');
        cell(tr, (item.abilities || []).map(function (code) {
          var ability = abilityOf(kb, code);
          return code + ' ' + (ability ? ability.name : '');
        }).join('；'));
        cell(tr, [blockWrap(item.gap, opts)]);
        cell(tr, [blockWrap(item.questions, opts)]);
      });
      root.appendChild(evTable.el);
    } else {
      root.appendChild(p('尚无真实事件线索，建议使用开放探索主题。', 'insuf'));
    }
    root.appendChild(callout('🗣️', 'Event-based R4 Assessment｜事件探索建议路径',
      fixed.event_path_callout));

    root.appendChild(heading(3, '3.3｜Backup Questions 备用提问', 'red'));
    var backups = doc.backups || [];
    var bkTable = table(['待确认 R4 能力', '事件探索后可能仍缺的证据', '备用问题',
      '建议提问时机 / 是否可延后'], ['18%', '', '', '22%']);
    if (backups.length) {
      backups.forEach(function (item) {
        var ability = abilityOf(kb, item.code);
        var tr = row(bkTable.body);
        cell(tr, item.code ? (item.code + ' ' + (ability ? ability.name : '')) : '导师补充');
        cell(tr, [blockWrap(item.missing, opts)]);
        cell(tr, [blockWrap(item.question, opts)]);
        cell(tr, item.timing || '第 4 环节；如已回答则跳过');
      });
    } else {
      var tr = row(bkTable.body);
      var td = cell(tr, []);
      td.setAttribute('colspan', '4');
      insuf(td, '重点能力均已在 3.2 中安排核实。');
    }
    root.appendChild(bkTable.el);

    root.appendChild(heading(3, '3.4｜Student Reflection & Growth Direction 总结与初步成长方向'));
    var growth = doc.growth || {};
    var growthTable = table(['准备事项', '建议内容'], ['20%']);
    var trWish = row(growthTable.body);
    cell(trWish, '学生成长意愿');
    cell(trWish, [blockWrap(growth.wish, opts)]);
    var trNext = row(growthTable.body);
    cell(trNext, '下一步可能方向');
    cell(trNext, [blockWrap(growth.next, opts)]);
    root.appendChild(growthTable.el);
  }

  function appendix(root, data, opts) {
    var kb = data.kb || {};
    var fixed = data.fixed || {};
    var dims = kb.dims || [];
    var abilities = kb.abilities || [];
    var byCode = {};
    (data.doc.appendix || []).forEach(function (item) { byCode[item.code] = item; });

    root.appendChild(heading(2, 'Appendix｜R4 Full Evidence Review（18 项能力）'));
    var call = h('div', 'call gray');
    call.appendChild(h('span', 'e', '📋')).setAttribute('aria-hidden', 'true');
    var body = h('div');
    body.appendChild(h('b', '', '附录用途：'));
    text(body, fixed.appendix_callout || '');
    call.appendChild(body);
    root.appendChild(call);

    dims.forEach(function (dim) {
      root.appendChild(heading(3, dim.id + '｜' + dim.en + ' ' + dim.zh));
      var t = table(['R4 能力', 'R4 相关指标分析', '会议中需确认', '证据核验', '是否推荐验证'],
        ['14%', '27%', '20%', '', '14%']);
      abilities.filter(function (a) { return a.dim === dim.id; }).forEach(function (ability) {
        var item = byCode[ability.code] || {};
        var tr = row(t.body);
        cell(tr, ability.code + ' ' + ability.name);

        var analysis = h('div');
        strong(analysis, '相关指标：');
        var lines = (data.y4_items || []).filter(function (y) {
          return (y.abilities || []).indexOf(ability.code) !== -1;
        }).map(function (y) { return y.text; });
        var lead = ability.indicator_note ? ability.indicator_note + '：' : '';
        text(analysis, lead + (lines.length ? lines.join(' · ') : '未取得 Y4 指标') + '。');
        strong(analysis, '分析与缺口：');
        text(analysis, ability.gap_note || '');
        cell(tr, [analysis]);

        cell(tr, ability.ask || '');

        var checkTd = cell(tr, []);
        if (item.check && item.check.text) blockNode(checkTd, item.check, opts);

        var recTd = cell(tr, []);
        text(recTd, item.recommend ? '☑️ 推荐' : '□ 暂不推荐');
        recTd.appendChild(h('br'));
        insuf(recTd, (item.reason && item.reason.text) || '');
      });
      root.appendChild(t.el);
    });
  }

  function abilityOf(kb, code) {
    if (!code || !kb || !kb.abilities) return null;
    for (var i = 0; i < kb.abilities.length; i++) {
      if (kb.abilities[i].code === code) return kb.abilities[i];
    }
    return null;
  }

  function render(root, data, options) {
    if (!root || !data || !data.doc) return;
    var opts = options || {};
    opts.mode = opts.mode || 'edit';

    var doc = data.doc;
    var meta = metaOf(doc, data.prep || {});
    var version = data.version || {};

    root.textContent = '';
    root.classList.toggle('editing', opts.mode === 'edit');
    root.classList.toggle('plain', opts.mode === 'print');
    root.classList.toggle('draftmark', data.status !== 'final');

    root.appendChild(h('div', 'icon', '🧭')).setAttribute('aria-hidden', 'true');
    root.appendChild(h('div', 'title', 'M1 FM会前准备 · ' + (meta.student || '')));

    partOne(root, data, meta, opts);
    partTwo(root, data, opts);
    partThree(root, data, opts);
    appendix(root, data, opts);

    var foot = h('div', 'foot');
    foot.appendChild(h('span', '', 'M1 FM会前准备框架 · ' + (meta.student || '')));
    var stamp = 'AI 初稿 ' + (fmtDT(version.ai_generated_at) || '—');
    if (data.status === 'final' && version.reviewed_at) {
      stamp += ' · 导师审核 ' + fmtDT(version.reviewed_at);
    }
    foot.appendChild(h('span', '', stamp));
    root.appendChild(foot);

    if (opts.onRendered) opts.onRendered(root, meta);
    return meta;
  }

  window.M1Doc = {
    render: render,
    findBlock: findBlock,
    markerLabel: markerLabel,
    metaOf: metaOf,
    fmtDT: fmtDT,
    fmtDate: fmtDate,
    abilityOf: abilityOf
  };
})();
