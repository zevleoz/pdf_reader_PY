/* M1 会后报告审阅页：资料、生成、待处理、报告内容、审核与发布。 */
(function () {
  'use strict';

  var root = document.getElementById('r4Review');
  if (!root) return;

  var prepId = parseInt(root.getAttribute('data-prep-id'), 10);
  var studentName = root.getAttribute('data-student') || '';
  var jobKey = 'm1_report_job_' + prepId;

  var SAVE_OK = '已保存';
  var SAVE_FAIL = '保存失败';
  var CONFLICT = '内容已在别处更新，请刷新。';
  var GENERATE_CONFIRM = '将生成新版本。当前版本和修改会保留，但不再显示。';
  var QUOTE_WARN = '引用在逐字稿中找不到';

  var STATUS_LABELS = {
    draft: '待生成',
    generating: '生成中',
    ai_draft: 'AI 草稿',
    needs_check: '待核实',
    reviewing: '导师审核中',
    approved: '审核通过',
    published: '正式发布'
  };
  var STATUS_CLASS = {
    draft: '',
    generating: 'info',
    ai_draft: 'warn',
    needs_check: 'warn',
    reviewing: 'brand',
    approved: 'ok',
    published: 'ok'
  };
  var STEP_LABELS = {
    pending: '等待',
    running: '进行中',
    done: '完成',
    skipped: '跳过'
  };
  var SPEAKERS = ['学生', '导师', '家长', '其他', '待确认'];
  var EVIDENCE_STATUSES = ['已确认', '待核实', '不采用'];

  var state = {
    payload: null,
    report: {},
    inputs: {},
    doc: null,
    evidence: [],
    ratings: {},
    mapped: {},
    checks: [],
    appendix: [],
    fixed: {},
    has_edits: false,
    pending: 0,
    conflict: false,
    polling: null,
    saveQueue: Promise.resolve(),
    panelEls: {},
    tab: 'R1'
  };

  var refs = {
    saved: document.getElementById('r4Saved'),
    statusPill: document.getElementById('r4StatusPill'),
    statusLabel: document.getElementById('r4StatusLabel'),
    print: document.getElementById('r4Print'),
    download: document.getElementById('r4Download'),
    evidence: document.getElementById('r4Evidence'),
    approve: document.getElementById('r4Approve'),
    publish: document.getElementById('r4Publish'),
    reopen: document.getElementById('r4Reopen'),
    publishedNote: document.getElementById('r4PublishedNote'),
    y4Pill: document.getElementById('r4Y4Pill'),
    y4Note: document.getElementById('r4Y4Note'),
    ftPill: document.getElementById('r4FtPill'),
    ftNote: document.getElementById('r4FtNote'),
    transcriptMeta: document.getElementById('r4TranscriptMeta'),
    transcriptFile: document.getElementById('r4TranscriptFile'),
    transcriptUpload: document.getElementById('r4TranscriptUpload'),
    transcriptText: document.getElementById('r4TranscriptText'),
    transcriptSave: document.getElementById('r4TranscriptSave'),
    others: document.getElementById('r4Others'),
    cover: document.getElementById('r4Cover'),
    metaStudent: document.getElementById('r4MetaStudent'),
    generate: document.getElementById('r4Generate'),
    generateReason: document.getElementById('r4GenerateReason'),
    steps: document.getElementById('r4Steps'),
    safety: document.getElementById('r4Safety'),
    safetyItems: document.getElementById('r4SafetyItems'),
    safetyAck: document.getElementById('r4SafetyAck'),
    checks: document.getElementById('r4Checks'),
    tabs: document.getElementById('r4Tabs'),
    panels: document.getElementById('r4Panels')
  };

  /* ------------------------------------------------------------------ */
  /* 基础工具                                                            */
  /* ------------------------------------------------------------------ */
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function toast(message, type) {
    if (window.v2Toast) window.v2Toast(message, type);
  }

  /* 与 m1_workspace.js:60 相同的错误约定。 */
  function api(path, options) {
    return fetch(path, options || {}).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (body) {
        if (!res.ok || body.ok === false) {
          var error = new Error(body.error || ('请求失败（' + res.status + '）'));
          error.status = res.status;
          error.body = body;
          throw error;
        }
        return body;
      });
    });
  }

  function jsonOptions(method, payload) {
    return {
      method: method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    };
  }

  function docUrl(tail) {
    return '/api/m1/preps/' + prepId + '/report' + (tail || '');
  }

  function fieldText(value) {
    if (value && typeof value === 'object') return value.text || '';
    return typeof value === 'string' ? value : '';
  }

  function sourceOf(value) {
    return value && typeof value === 'object' && value.src === 'edited' ? 'edited' : 'ai';
  }

  function markNode(value) {
    var edited = sourceOf(value) === 'edited';
    return el('span', edited ? 'mk ed' : 'mk', edited ? '已修改' : 'AI');
  }

  function setMark(node, src) {
    if (!node) return;
    node.className = src === 'edited' ? 'mk ed' : 'mk';
    node.textContent = src === 'edited' ? '已修改' : 'AI';
  }

  function setSaved(message, isError) {
    refs.saved.textContent = message || '';
    refs.saved.className = 'sub' + (isError ? ' r4-err' : '');
  }

  function show(node, visible) {
    if (node) node.hidden = !visible;
  }

  function setPill(node, cls, text) {
    node.className = 'pill' + (cls ? ' ' + cls : '');
    node.textContent = text;
  }

  function pathKey(path) {
    return JSON.stringify(path);
  }

  function samePath(left, right) {
    if (!left || !right || left.length !== right.length) return false;
    for (var i = 0; i < left.length; i += 1) {
      if (left[i] !== right[i]) return false;
    }
    return true;
  }

  function isPrefix(left, right) {
    if (!left || !right || left.length >= right.length) return false;
    for (var i = 0; i < left.length; i += 1) {
      if (left[i] !== right[i]) return false;
    }
    return true;
  }

  /* ------------------------------------------------------------------ */
  /* 保存                                                                */
  /* ------------------------------------------------------------------ */
  function updateUnload() {
    if (state.pending > 0) window.addEventListener('beforeunload', onUnload);
    else window.removeEventListener('beforeunload', onUnload);
  }

  function onUnload(event) {
    event.preventDefault();
    event.returnValue = '';
  }

  function applySaveResult(body) {
    state.report.rev = body.rev;
    state.report.status = body.status;
    state.report.label = STATUS_LABELS[body.status] || body.status;
    state.checks = body.checks || [];
    state.appendix = body.appendix || [];
    state.has_edits = true;
    applyStatus();
    renderTodo();
    renderAppendixPanel();
    setSaved(SAVE_OK);
    (body.impacts || []).forEach(function (message) {
      if (message) toast(message, 'info');
    });
  }

  function saveDoc(path, value) {
    state.pending += 1;
    updateUnload();
    var task = function () {
      if (state.conflict) {
        var blocked = new Error(CONFLICT);
        blocked.r4Conflict = true;
        throw blocked;
      }
      return api(docUrl('/doc'), jsonOptions('PUT', {
        rev: state.report.rev,
        changes: [{ path: path, value: value }]
      })).then(function (body) {
        applySaveResult(body);
        return body;
      }).catch(function (error) {
        if (error.status === 409) {
          state.conflict = true;
          setSaved(CONFLICT, true);
        } else if (!error.r4Conflict) {
          setSaved(SAVE_FAIL, true);
          toast(error.message, 'error');
        }
        throw error;
      });
    };
    var chained = state.saveQueue.then(task, task);
    state.saveQueue = chained.catch(function () {});
    chained.then(function () {
      state.pending -= 1;
      updateUnload();
    }, function () {
      state.pending -= 1;
      updateUnload();
    });
    return chained;
  }

  function bindTextSave(input, path, mark) {
    if (!input) return;
    input.__r4Path = path;
    input.__r4Mark = mark || null;
    if (path) input.setAttribute('data-path', pathKey(path));
    input.__r4Last = input.value;
    input.__r4Dirty = false;
    var timer = null;

    function flush() {
      clearTimeout(timer);
      if (!input.__r4Dirty || state.conflict) return;
      if (state.report.status === 'published') return;
      input.__r4Dirty = false;
      var value = input.value;
      if (value === input.__r4Last) return;
      saveDoc(path, value).then(function () {
        input.__r4Last = value;
        setMark(input.__r4Mark, 'edited');
      }).catch(function () {
        input.__r4Dirty = true;
      });
    }

    input.addEventListener('input', function () {
      input.__r4Dirty = true;
      setSaved('');
      clearTimeout(timer);
      timer = setTimeout(flush, 1500);
    });
    input.addEventListener('blur', flush);
  }

  function textAreaField(label, value) {
    var wrap = el('label', 'field r4-field');
    var head = el('div', 'r4-fieldhead');
    head.appendChild(el('span', '', label));
    var mark = markNode(value);
    head.appendChild(mark);
    wrap.appendChild(head);
    var input = el('textarea', 'inp');
    input.value = fieldText(value);
    wrap.appendChild(input);
    return { wrap: wrap, input: input, mark: mark };
  }

  function textAreaBlock(label, value, path) {
    var field = textAreaField(label, value);
    bindTextSave(field.input, path, field.mark);
    return field.wrap;
  }

  /* ------------------------------------------------------------------ */
  /* 标签页                                                              */
  /* ------------------------------------------------------------------ */
  function addTab(key, label) {
    var button = el('button', 'r4-tab', label);
    button.type = 'button';
    button.setAttribute('role', 'tab');
    button.setAttribute('data-tab', key);
    button.addEventListener('click', function () { activateTab(key); });
    refs.tabs.appendChild(button);
    var panel = el('div', 'r4-panel');
    panel.id = 'r4Panel-' + key;
    panel.setAttribute('role', 'tabpanel');
    refs.panels.appendChild(panel);
    state.panelEls[key] = panel;
  }

  function activateTab(key) {
    if (!state.panelEls[key]) key = Object.keys(state.panelEls)[0];
    if (!key) return;
    state.tab = key;
    var buttons = refs.tabs.querySelectorAll('.r4-tab');
    for (var i = 0; i < buttons.length; i += 1) {
      var on = buttons[i].getAttribute('data-tab') === key;
      buttons[i].className = 'r4-tab' + (on ? ' on' : '');
      buttons[i].setAttribute('aria-selected', on ? 'true' : 'false');
    }
    Object.keys(state.panelEls).forEach(function (name) {
      state.panelEls[name].hidden = name !== key;
    });
    try {
      history.replaceState(null, '', '#' + key);
    } catch (error) {
      /* 本地文件或受限环境忽略。 */
    }
  }

  function hashTab() {
    var hash = (window.location.hash || '').replace('#', '');
    return hash || 'R1';
  }

  function emptyNote(text) {
    return el('div', 'sub r4-empty', text);
  }

  function scrollToPath(path) {
    if (!path || !path.length) return;
    if (path[0] === 'appendix') activateTab('appendix');
    var nodes = root.querySelectorAll('[data-path]');
    var exact = null;
    var under = null;
    var over = null;
    for (var i = 0; i < nodes.length; i += 1) {
      var parsed;
      try {
        parsed = JSON.parse(nodes[i].getAttribute('data-path'));
      } catch (error) {
        continue;
      }
      if (!exact && samePath(parsed, path)) exact = nodes[i];
      if (!under && isPrefix(parsed, path)) under = nodes[i];
      if (!over && isPrefix(path, parsed)) over = nodes[i];
    }
    var target = exact || under || over;
    if (!target) return;
    var panel = target.closest ? target.closest('.r4-panel') : null;
    if (panel && panel.id.indexOf('r4Panel-') === 0) activateTab(panel.id.slice(8));
    target.scrollIntoView({ block: 'center' });
    if (typeof target.focus === 'function') target.focus();
  }

  /* ------------------------------------------------------------------ */
  /* 资料 / 封面                                                          */
  /* ------------------------------------------------------------------ */
  function renderSources() {
    var inputs = state.inputs || {};
    var y4 = inputs.y4 || {};
    setPill(refs.y4Pill, y4.complete ? 'ok' : 'warn', y4.complete ? '已读取' : '缺失');
    refs.y4Note.textContent = y4.complete
      ? (y4.date ? '测评日期 ' + y4.date : '')
      : '未找到完整的 Y4 测评，暂不能生成。';

    var ft = inputs.first_touch || {};
    setPill(refs.ftPill, ft.present ? 'ok' : '', ft.present ? '已读取' : '未提供（可选）');
    refs.ftNote.textContent = ft.present ? (ft.date || '') : '';

    var report = state.report || {};
    var length = report.transcript_length || 0;
    refs.transcriptMeta.textContent = length
      ? ((report.transcript_filename || '已录入逐字稿') + ' · ' + length + ' 字')
      : '未上传';

    refs.others.textContent = '';
    var others = inputs.others || [];
    if (!others.length) {
      refs.others.appendChild(el('span', 'sub', '没有其他资料。'));
    }
    others.forEach(function (item) {
      var row = el('div', 'r4-other');
      row.appendChild(el('b', '', item.label || item.category || ''));
      row.appendChild(el('span', 'sub', item.filename || ''));
      refs.others.appendChild(row);
    });
  }

  function renderCover() {
    var meta = (state.doc && state.doc.meta) || {};
    refs.metaStudent.setAttribute('data-path', pathKey(['meta', 'student_name']));
    refs.metaStudent.value = meta.student_name || studentName || '';
    var fields = refs.cover.querySelectorAll('[data-meta]');
    for (var i = 0; i < fields.length; i += 1) {
      var input = fields[i];
      var key = input.getAttribute('data-meta');
      input.value = meta[key] || '';
      if (!input.__r4Path) {
        bindTextSave(input, ['meta', key], null);
      } else {
        input.__r4Last = input.value;
        input.__r4Dirty = false;
      }
    }
  }

  /* ------------------------------------------------------------------ */
  /* 生成                                                                */
  /* ------------------------------------------------------------------ */
  function renderGenerateState() {
    var status = state.report.status;
    var missing = [];
    if (!((state.inputs.y4 || {}).complete)) missing.push('需要先读取 Y4 测评');
    if (!(state.report.transcript_length > 0)) missing.push('需要先上传 M1 会议逐字稿');
    var locked = status === 'published';
    var generating = status === 'generating';
    refs.generate.disabled = locked || generating || missing.length > 0;
    refs.generateReason.textContent = generating ? '正在生成。' : (locked ? '' : missing.join('；'));
  }

  function renderSteps(steps, message) {
    refs.steps.hidden = false;
    refs.steps.textContent = '';
    if (message) refs.steps.appendChild(el('div', 'sub', message));
    (steps || []).forEach(function (step) {
      var row = el('div', 'gen-row ' + (step.state === 'running' ? 'run' : (step.state === 'done' || step.state === 'skipped' ? 'ok' : '')));
      row.appendChild(el('span', 'ic'));
      var text = el('span');
      text.appendChild(el('b', '', step.label || step.step || ''));
      row.appendChild(text);
      row.appendChild(el('span', 'sub', STEP_LABELS[step.state] || step.state || ''));
      refs.steps.appendChild(row);
    });
  }

  function stopPolling() {
    if (state.polling) {
      clearInterval(state.polling);
      state.polling = null;
    }
  }

  function pollJob(jobId) {
    stopPolling();
    state.polling = setInterval(function () {
      api('/api/m1/jobs/' + jobId).then(function (body) {
        var job = body.job || {};
        renderSteps(job.steps, job.message);
        if (job.status === 'done') {
          stopPolling();
          try { localStorage.removeItem(jobKey); } catch (error) { /* 忽略 */ }
          load();
        } else if (job.status === 'error') {
          stopPolling();
          try { localStorage.removeItem(jobKey); } catch (error) { /* 忽略 */ }
          toast(job.message || '生成失败', 'error');
          load();
        }
      }).catch(function (error) {
        stopPolling();
        toast(error.message, 'error');
        load();
      });
    }, 2000);
  }

  function startStatusPoll() {
    stopPolling();
    state.polling = setInterval(function () { load(); }, 2000);
  }

  function resumeJobIfRunning() {
    if (state.report.status !== 'generating') {
      stopPolling();
      return;
    }
    if (state.polling) return;
    var stored = '';
    try { stored = localStorage.getItem(jobKey) || ''; } catch (error) { stored = ''; }
    if (stored) {
      renderSteps([], '生成任务运行中');
      pollJob(stored);
    } else {
      startStatusPoll();
    }
  }

  function generate(confirmOverwrite) {
    if (!confirmOverwrite && state.has_edits) {
      if (!window.confirm(GENERATE_CONFIRM)) return;
      confirmOverwrite = true;
    }
    api(docUrl('/generate'), jsonOptions('POST', { confirm_overwrite: !!confirmOverwrite }))
      .then(function (body) {
        state.report.status = 'generating';
        state.report.label = STATUS_LABELS.generating;
        applyStatus();
        renderSteps([], '生成任务运行中');
        try { localStorage.setItem(jobKey, body.job_id); } catch (error) { /* 忽略 */ }
        pollJob(body.job_id);
      })
      .catch(function (error) {
        if (error.status === 409 && error.body && error.body.error === '需要确认覆盖') {
          if (window.confirm(GENERATE_CONFIRM)) generate(true);
          return;
        }
        toast(error.message, 'error');
        load();
      });
  }

  /* ------------------------------------------------------------------ */
  /* 待处理                                                              */
  /* ------------------------------------------------------------------ */
  function renderChecks() {
    var list = state.checks || [];
    refs.checks.textContent = '';
    if (!list.length) {
      refs.checks.appendChild(el('div', 'sub', '没有待处理问题。'));
      return;
    }
    list.forEach(function (check) {
      var row = el('button', 'r4-check ' + (check.level === 'block' ? 'block' : 'review'));
      row.type = 'button';
      row.appendChild(el('span', 'r4-checklevel', check.level === 'block' ? '阻断' : '复核'));
      row.appendChild(el('span', '', check.message || ''));
      row.addEventListener('click', function () { scrollToPath(check.path); });
      refs.checks.appendChild(row);
    });
  }

  function renderTodo() {
    var report = state.report || {};
    var safety = report.safety || [];
    show(refs.safety, safety.length > 0);
    refs.safetyItems.textContent = '';
    safety.forEach(function (item) {
      var row = el('div');
      row.appendChild(el('b', '', item.text || ''));
      if (item.source_ref) row.appendChild(el('span', 'sub', ' · ' + item.source_ref));
      refs.safetyItems.appendChild(row);
    });
    var acked = !!report.safety_ack_at;
    refs.safetyAck.disabled = acked;
    refs.safetyAck.textContent = acked ? '已确认' : '已知悉并人工核实';
    renderChecks();
  }

  /* ------------------------------------------------------------------ */
  /* 报告内容                                                            */
  /* ------------------------------------------------------------------ */
  function abilityRow(dimId, code) {
    var dims = (state.doc && state.doc.dims) || {};
    var dim = dims[dimId] || {};
    var abilities = dim.abilities || {};
    return abilities[code] || {};
  }

  function y4Group(dim, item, row) {
    var path = ['dims', dim.id, 'abilities', item.code, 'y4_selected'];
    var wrap = el('div', 'r4-y4');
    wrap.setAttribute('data-path', pathKey(path));
    var mapped = state.mapped[item.code] || [];
    var selected = row.y4_selected || [];
    if (!mapped.length) {
      wrap.appendChild(el('span', 'sub', '没有对应的 Y4 指标。'));
      return wrap;
    }
    mapped.forEach(function (code) {
      var entry = state.ratings[code];
      var check = !entry || entry.state === 'check';
      var line = el('label', 'r4-y4row' + (check ? ' check' : ''));
      var box = el('input');
      box.type = 'checkbox';
      box.value = code;
      box.checked = selected.indexOf(code) !== -1;
      box.addEventListener('change', function () {
        var next = [];
        var boxes = wrap.querySelectorAll('input[type="checkbox"]');
        for (var i = 0; i < boxes.length; i += 1) {
          if (boxes[i].checked) next.push(boxes[i].value);
        }
        saveDoc(path, next).then(function () {
          row.y4_selected = next;
        }).catch(function () {
          var current = row.y4_selected || [];
          for (var j = 0; j < boxes.length; j += 1) {
            boxes[j].checked = current.indexOf(boxes[j].value) !== -1;
          }
        });
      });
      line.appendChild(box);
      line.appendChild(el('span', '', entry ? entry.family_line : code));
      if (check) line.appendChild(el('span', 'pill warn', '待核实'));
      wrap.appendChild(line);
    });
    return wrap;
  }

  function renderTagStates(wrap, tags) {
    var chips = wrap.querySelectorAll('.r4-tag');
    for (var i = 0; i < chips.length; i += 1) {
      var key = chips[i].getAttribute('data-tag');
      chips[i].setAttribute('aria-pressed', tags.indexOf(key) !== -1 ? 'true' : 'false');
    }
  }

  function tagChips(dim, item, row, mark) {
    var path = ['dims', dim.id, 'abilities', item.code, 'tags'];
    var wrap = el('div', 'r4-tags');
    wrap.setAttribute('data-path', pathKey(path));
    var selected = (row.tags || []).slice();
    (state.fixed.tags || []).forEach(function (tag) {
      var chip = el('button', 'r4-tag');
      chip.type = 'button';
      chip.setAttribute('data-tag', tag.key);
      chip.setAttribute('aria-pressed', selected.indexOf(tag.key) !== -1 ? 'true' : 'false');
      chip.style.background = tag.bg;
      chip.style.borderColor = tag.border;
      chip.style.color = tag.ink;
      chip.appendChild(el('span', 'r4-tagicon', tag.icon));
      chip.appendChild(el('span', '', tag.key));
      chip.addEventListener('click', function () {
        var previous = (row.tags || []).slice();
        var next = previous.slice();
        var at = next.indexOf(tag.key);
        if (at >= 0) next.splice(at, 1);
        else next.push(tag.key);
        saveDoc(path, next).then(function () {
          row.tags = next;
          row.tags_src = 'edited';
          renderTagStates(wrap, next);
          setMark(mark, 'edited');
        }).catch(function (error) {
          renderTagStates(wrap, row.tags || []);
          if (error.status !== 409) toast(error.message, 'error');
        });
      });
      wrap.appendChild(chip);
    });
    return wrap;
  }

  function evidenceItem(item, locked) {
    var wrap = el('div', 'r4-evitem');
    var tools = el('div', 'r4-evtools');

    var speakerLabel = el('label', 'r4-evsel');
    speakerLabel.appendChild(el('span', '', '发言人'));
    var speaker = el('select', 'inp');
    SPEAKERS.forEach(function (name) {
      var option = el('option', '', name);
      option.value = name;
      speaker.appendChild(option);
    });
    speaker.value = item.speaker || '待确认';
    speaker.disabled = locked;
    speaker.addEventListener('change', function () {
      saveEvidence(item, { speaker: speaker.value }, speaker);
    });
    speakerLabel.appendChild(speaker);
    tools.appendChild(speakerLabel);

    var statusLabel = el('label', 'r4-evsel');
    statusLabel.appendChild(el('span', '', '审核状态'));
    var status = el('select', 'inp');
    EVIDENCE_STATUSES.forEach(function (name) {
      var option = el('option', '', name);
      option.value = name;
      status.appendChild(option);
    });
    status.value = item.status || '待核实';
    status.disabled = locked;
    status.addEventListener('change', function () {
      saveEvidence(item, { status: status.value }, status);
    });
    statusLabel.appendChild(status);
    tools.appendChild(statusLabel);
    wrap.appendChild(tools);

    var meta = el('div', 'r4-evmeta');
    meta.appendChild(el('span', 'pill', item.source || ''));
    meta.appendChild(el('span', 'sub', item.type || ''));
    if (item.location) meta.appendChild(el('span', 'sub', item.location));
    wrap.appendChild(meta);

    wrap.appendChild(el('div', 'r4-quote', item.quote || ''));
    if (!item.quote_verified) wrap.appendChild(el('div', 'r4-warn', QUOTE_WARN));

    var interp = el('div', 'r4-evtext');
    interp.appendChild(el('b', '', 'AI 解释'));
    interp.appendChild(el('span', '', item.interpretation || ''));
    wrap.appendChild(interp);

    var limits = el('div', 'r4-evtext');
    limits.appendChild(el('b', '', '证据局限'));
    limits.appendChild(el('span', '', item.limits || ''));
    wrap.appendChild(limits);
    return wrap;
  }

  function saveEvidence(item, fields, control) {
    if (state.conflict || state.report.status === 'published') return;
    state.pending += 1;
    updateUnload();
    var task = function () {
      if (state.conflict) {
        var blocked = new Error(CONFLICT);
        blocked.r4Conflict = true;
        throw blocked;
      }
      var payload = { rev: state.report.rev };
      if (fields.status !== undefined) payload.status = fields.status;
      if (fields.speaker !== undefined) payload.speaker = fields.speaker;
      return api(docUrl('/evidence/' + item.id), jsonOptions('PUT', payload)).then(function (body) {
        state.report.rev = body.rev;
        state.report.status = body.status;
        state.report.label = STATUS_LABELS[body.status] || body.status;
        state.checks = body.checks || [];
        state.has_edits = true;
        applyStatus();
        renderTodo();
        setSaved(SAVE_OK);
        return body;
      }).catch(function (error) {
        if (error.status === 409) {
          state.conflict = true;
          setSaved(CONFLICT, true);
        } else if (!error.r4Conflict) {
          setSaved(SAVE_FAIL, true);
          toast(error.message, 'error');
        }
        control.value = fields.status !== undefined
          ? (item.status || '待核实') : (item.speaker || '待确认');
        throw error;
      });
    };
    var chained = state.saveQueue.then(task, task);
    state.saveQueue = chained.catch(function () {});
    chained.then(function () {
      state.pending -= 1;
      updateUnload();
    }, function () {
      state.pending -= 1;
      updateUnload();
    });
  }

  function abilityEvidence(code) {
    var items = (state.evidence || []).filter(function (item) {
      return (item.ability_codes || []).indexOf(code) !== -1;
    });
    var details = el('details', 'r4-ev');
    var open = items.some(function (item) { return item.speaker === '待确认'; });
    details.open = open;
    details.appendChild(el('summary', '', '证据（' + items.length + '）'));
    if (!items.length) details.appendChild(el('div', 'sub', '暂无证据条目。'));
    items.forEach(function (item) {
      details.appendChild(evidenceItem(item, state.report.status === 'published'));
    });
    return details;
  }

  function abilityCard(dim, item, row) {
    var card = el('section', 'surface r4-ab');
    var head = el('div', 'head');
    head.setAttribute('data-path', pathKey(['dims', dim.id, 'abilities', item.code]));
    head.appendChild(el('b', '', item.code + ' ' + item.name));
    head.appendChild(el('span', 'sp'));
    card.appendChild(head);

    var body = el('div', 'body');
    body.appendChild(el('div', 'sub r4-desc', item.description || ''));

    var columns = (state.fixed.analysis || {}).columns || [];
    var sectY4 = el('div', 'r4-sect');
    var y4Head = el('div', 'r4-lbl');
    y4Head.appendChild(el('span', '', columns[2] || 'Y4 与其他线索'));
    y4Head.appendChild(markNode(row.other_clues));
    sectY4.appendChild(y4Head);
    sectY4.appendChild(y4Group(dim, item, row));
    var clues = el('textarea', 'inp');
    clues.value = fieldText(row.other_clues);
    sectY4.appendChild(clues);
    bindTextSave(clues, ['dims', dim.id, 'abilities', item.code, 'other_clues'],
                 y4Head.querySelector('.mk'));
    body.appendChild(sectY4);

    var sectMeeting = el('div', 'r4-sect');
    var meetingHead = el('div', 'r4-lbl');
    meetingHead.appendChild(el('span', '', columns[3] || '首次会议核实情况'));
    var meetingMark = markNode(row.meeting);
    meetingHead.appendChild(meetingMark);
    sectMeeting.appendChild(meetingHead);
    var meeting = el('textarea', 'inp');
    meeting.value = fieldText(row.meeting);
    sectMeeting.appendChild(meeting);
    bindTextSave(meeting, ['dims', dim.id, 'abilities', item.code, 'meeting'], meetingMark);
    body.appendChild(sectMeeting);

    var sectTags = el('div', 'r4-sect');
    var tagHead = el('div', 'r4-lbl');
    tagHead.appendChild(el('span', '', columns[4] || '综合判断'));
    var tagMark = markNode({ src: row.tags_src });
    tagHead.appendChild(tagMark);
    sectTags.appendChild(tagHead);
    sectTags.appendChild(tagChips(dim, item, row, tagMark));
    body.appendChild(sectTags);

    var sectEvidence = el('div', 'r4-sect');
    sectEvidence.appendChild(el('div', 'r4-lbl', '证据'));
    sectEvidence.appendChild(abilityEvidence(item.code));
    body.appendChild(sectEvidence);

    card.appendChild(body);
    return card;
  }

  function buildDimPanel(dim) {
    var panel = state.panelEls[dim.id];
    var dimDoc = ((state.doc && state.doc.dims) || {})[dim.id] || null;
    if (!dimDoc) {
      panel.appendChild(emptyNote('还没有生成报告内容。'));
      return;
    }
    (dim.abilities || []).forEach(function (item) {
      panel.appendChild(abilityCard(dim, item, abilityRow(dim.id, item.code)));
    });
    panel.appendChild(textAreaBlock(
      (state.fixed.analysis || {}).finding_title || '',
      dimDoc.core_finding,
      ['dims', dim.id, 'core_finding']));
    panel.appendChild(textAreaBlock(
      (state.fixed.analysis || {}).context_title || '',
      dimDoc.context_notes,
      ['dims', dim.id, 'context_notes']));
  }

  function buildProfilePanel() {
    var panel = state.panelEls.profile;
    if (!state.doc) {
      panel.appendChild(emptyNote('还没有生成报告内容。'));
      return;
    }
    var profile = state.fixed.profile || {};
    panel.appendChild(el('h3', 'r4-h3', profile.portrait_title || ''));
    var portrait = state.doc.portrait || {};
    (state.fixed.dims || []).forEach(function (dim) {
      panel.appendChild(textAreaBlock(
        dim.id + ' ' + (dim.portrait_sub || dim.zh || ''),
        portrait[dim.id],
        ['portrait', dim.id]));
    });
    panel.appendChild(el('h3', 'r4-h3', profile.findings_title || ''));
    var findings = state.doc.findings || {};
    var columns = profile.findings_columns || [];
    ['resources', 'needs', 'open'].forEach(function (key) {
      var row = findings[key] || {};
      var block = el('div', 'r4-finding');
      block.appendChild(el('div', 'r4-lbl', (profile.findings_rows || {})[key] || key));
      block.appendChild(textAreaBlock(columns[1] || '', row.finding, ['findings', key, 'finding']));
      block.appendChild(textAreaBlock(columns[2] || '', row.meaning, ['findings', key, 'meaning']));
      panel.appendChild(block);
    });
  }

  function planPayload() {
    return ((state.doc && state.doc.plan) || []).map(function (row) {
      return {
        ability: row.ability,
        goal: fieldText(row.goal),
        mentor: fieldText(row.mentor),
        family: fieldText(row.family),
        evidence: fieldText(row.evidence)
      };
    });
  }

  function savePlan() {
    saveDoc(['plan'], planPayload()).catch(function () {});
  }

  function planRow(row, index, panelRows, columns) {
    var card = el('div', 'r4-plan-row');
    var top = el('div', 'r4-plan-top');
    top.appendChild(el('span', 'r4-k', columns[0] || ''));

    var select = el('select', 'inp');
    var abilities = state.fixed.dims || [];
    abilities.forEach(function (dim) {
      (dim.abilities || []).forEach(function (item) {
        var option = el('option', '', item.code + ' ' + item.name);
        option.value = item.code;
        select.appendChild(option);
      });
    });
    select.value = row.ability || '';
    select.addEventListener('change', function () {
      row.ability = select.value;
      savePlan();
    });
    top.appendChild(select);

    var remove = el('button', 'btn sm r4-plan-remove', '移除');
    remove.type = 'button';
    remove.disabled = (state.doc.plan || []).length <= 1 || state.report.status === 'published';
    remove.addEventListener('click', function () {
      if ((state.doc.plan || []).length <= 1) return;
      state.doc.plan.splice(index, 1);
      savePlan();
      renderPlanPanel();
    });
    top.appendChild(remove);
    card.appendChild(top);

    ['goal', 'mentor', 'family', 'evidence'].forEach(function (key, at) {
      var field = textAreaField(columns[at + 1] || '', row[key]);
      bindPlanField(field.input, row, key, field.mark, index);
      card.appendChild(field.wrap);
    });
    panelRows.appendChild(card);
  }

  function bindPlanField(input, row, key, mark, index) {
    input.setAttribute('data-path', pathKey(['plan', index, key]));
    input.__r4Last = input.value;
    input.__r4Dirty = false;
    var timer = null;
    function flush() {
      clearTimeout(timer);
      if (!input.__r4Dirty || state.conflict) return;
      if (state.report.status === 'published') return;
      input.__r4Dirty = false;
      row[key] = { text: input.value, src: 'edited' };
      saveDoc(['plan'], planPayload()).then(function () {
        input.__r4Last = input.value;
        setMark(mark, 'edited');
      }).catch(function () {
        input.__r4Dirty = true;
      });
    }
    input.addEventListener('input', function () {
      input.__r4Dirty = true;
      row[key] = { text: input.value, src: 'edited' };
      setSaved('');
      clearTimeout(timer);
      timer = setTimeout(flush, 1500);
    });
    input.addEventListener('blur', flush);
  }

  function renderPlanPanel() {
    var panel = state.panelEls.plan;
    if (!panel) return;
    panel.textContent = '';
    if (!state.doc) {
      panel.appendChild(emptyNote('还没有生成报告内容。'));
      return;
    }
    var profile = state.fixed.plan || {};
    panel.appendChild(el('div', 'sub', profile.intro || ''));
    var plan = state.doc.plan || [];
    var list = el('div', 'r4-plan');
    list.setAttribute('data-path', pathKey(['plan']));
    var columns = profile.columns || [];
    plan.forEach(function (row, index) {
      planRow(row, index, list, columns);
    });
    panel.appendChild(list);

    var add = el('button', 'btn sm r4-plan-add', '添加一项');
    add.type = 'button';
    add.disabled = plan.length >= 3 || state.report.status === 'published';
    add.addEventListener('click', function () {
      if ((state.doc.plan || []).length >= 3) return;
      var first = null;
      (state.fixed.dims || []).some(function (dim) {
        (dim.abilities || []).some(function (item) {
          first = item.code;
          return true;
        });
        return !!first;
      });
      state.doc.plan = state.doc.plan || [];
      state.doc.plan.push({
        ability: first,
        goal: { text: '', src: 'ai' },
        mentor: { text: '', src: 'ai' },
        family: { text: '', src: 'ai' },
        evidence: { text: '', src: 'ai' }
      });
      savePlan();
      renderPlanPanel();
    });
    panel.appendChild(add);
    panel.appendChild(textAreaBlock(profile.review_title || '', state.doc.review_advice, ['review_advice']));
  }

  function buildAppendixPanel() {
    renderAppendixPanel();
  }

  function renderAppendixPanel() {
    var panel = state.panelEls.appendix;
    if (!panel) return;
    panel.textContent = '';
    panel.appendChild(el('div', 'r4-note', '附录根据综合判断自动生成，不能手动修改。'));
    var rows = state.appendix || [];
    if (!rows.length) {
      panel.appendChild(el('div', 'sub', '暂无附录条目。'));
      return;
    }
    rows.forEach(function (row) {
      var card = el('div', 'r4-appendix-row');
      card.setAttribute('data-path', pathKey(['appendix', row.code]));
      var head = el('div', 'r4-appendix-head');
      head.appendChild(el('b', '', row.code + ' ' + (row.name || '')));
      (row.tags || []).forEach(function (tag) {
        head.appendChild(el('span', 'pill', tag));
      });
      card.appendChild(head);
      var missing = row.scene === '场景原文待导入';
      card.appendChild(el('div', missing ? 'r4-warn' : 'r4-scene', row.scene || ''));
      panel.appendChild(card);
    });
  }

  function buildContent() {
    refs.tabs.textContent = '';
    refs.panels.textContent = '';
    state.panelEls = {};
    var fixed = state.fixed || {};
    (fixed.dims || []).forEach(function (dim) {
      addTab(dim.id, dim.id + ' ' + (dim.zh || ''));
    });
    addTab('profile', '04 综合画像');
    addTab('plan', '05 成长方案');
    addTab('appendix', '附录');
    (fixed.dims || []).forEach(buildDimPanel);
    buildProfilePanel();
    renderPlanPanel();
    buildAppendixPanel();
    activateTab(hashTab());
  }

  /* ------------------------------------------------------------------ */
  /* 状态与动作                                                          */
  /* ------------------------------------------------------------------ */
  function setEditable(locked) {
    ['#r4Cover', '#r4Sources', '#r4GenerateCard', '#r4Content'].forEach(function (sel) {
      var node = root.querySelector(sel);
      if (!node) return;
      var controls = node.querySelectorAll('input, textarea, select, button');
      for (var i = 0; i < controls.length; i += 1) {
        if (controls[i].classList.contains('r4-tab')) continue;
        controls[i].disabled = locked;
      }
    });
    if (!locked) {
      var plan = (state.doc && state.doc.plan) || [];
      var add = root.querySelector('.r4-plan-add');
      if (add) add.disabled = plan.length >= 3;
      var remove = root.querySelectorAll('.r4-plan-remove');
      for (var j = 0; j < remove.length; j += 1) remove[j].disabled = plan.length <= 1;
    }
    show(refs.publishedNote, locked);
  }

  function applyStatus() {
    var status = state.report.status || 'draft';
    refs.statusLabel.textContent = state.report.label || STATUS_LABELS[status] || status;
    refs.statusPill.className = 'pill' + (STATUS_CLASS[status] ? ' ' + STATUS_CLASS[status] : '');

    var hasVersion = state.doc !== null;
    var locked = status === 'published';
    show(refs.print, hasVersion && ['ai_draft', 'needs_check', 'reviewing', 'approved'].indexOf(status) !== -1);
    show(refs.download, status === 'published');
    show(refs.evidence, hasVersion && status !== 'draft' && status !== 'generating');
    show(refs.approve, ['ai_draft', 'needs_check', 'reviewing'].indexOf(status) !== -1);
    show(refs.publish, status === 'approved');
    show(refs.reopen, status === 'approved' || status === 'published');

    setEditable(locked);
    renderGenerateState();
  }

  /* ------------------------------------------------------------------ */
  /* 载入                                                                */
  /* ------------------------------------------------------------------ */
  function applyPayload(body) {
    state.payload = body;
    state.report = body.report || {};
    state.inputs = body.inputs || {};
    state.doc = body.doc || null;
    state.evidence = body.evidence || [];
    state.ratings = body.ratings || {};
    state.mapped = body.mapped || {};
    state.checks = body.checks || [];
    state.appendix = body.appendix || [];
    state.fixed = body.fixed || {};
    state.has_edits = !!body.has_edits;
    state.conflict = false;

    refs.steps.hidden = true;
    refs.steps.textContent = '';
    renderSources();
    renderCover();
    renderTodo();
    buildContent();
    applyStatus();
    resumeJobIfRunning();
  }

  function load() {
    return api(docUrl('')).then(applyPayload).catch(function (error) {
      setSaved(SAVE_FAIL + '：' + error.message, true);
      toast(error.message, 'error');
    });
  }

  /* ------------------------------------------------------------------ */
  /* 事件                                                                */
  /* ------------------------------------------------------------------ */
  refs.generate.addEventListener('click', function () {
    if (refs.generate.disabled) return;
    generate(false);
  });

  refs.approve.addEventListener('click', function () {
    var blocks = (state.checks || []).filter(function (check) { return check.level === 'block'; });
    if (blocks.length) {
      refs.checks.scrollIntoView({ block: 'center' });
      return;
    }
    api(docUrl('/approve'), { method: 'POST' }).then(function (body) {
      state.report = body.report;
      state.checks = body.checks || [];
      applyStatus();
      renderTodo();
      setSaved(SAVE_OK);
    }).catch(function (error) {
      if (error.status === 400 && error.body && error.body.blocking) {
        state.checks = error.body.checks || state.checks;
        renderTodo();
        refs.checks.scrollIntoView({ block: 'center' });
      }
      toast(error.message, 'error');
    });
  });

  refs.publish.addEventListener('click', function () {
    if (!window.confirm('确认正式发布？')) return;
    api(docUrl('/publish'), { method: 'POST' }).then(function (body) {
      state.report = body.report;
      applyStatus();
      setSaved(SAVE_OK);
    }).catch(function (error) {
      toast(error.message, 'error');
    });
  });

  refs.reopen.addEventListener('click', function () {
    api(docUrl('/reopen'), { method: 'POST' }).then(function (body) {
      state.report = body.report;
      applyStatus();
      setSaved(SAVE_OK);
      load();
    }).catch(function (error) {
      toast(error.message, 'error');
    });
  });

  refs.safetyAck.addEventListener('click', function () {
    api(docUrl('/safety-ack'), { method: 'POST' }).then(function () {
      return load();
    }).catch(function (error) {
      toast(error.message, 'error');
    });
  });

  function uploadTranscript() {
    var file = refs.transcriptFile.files && refs.transcriptFile.files[0];
    if (!file) {
      toast('请先选择文件', 'error');
      return;
    }
    var form = new FormData();
    form.append('file', file);
    api(docUrl('/transcript'), { method: 'POST', body: form }).then(function (body) {
      refs.transcriptFile.value = '';
      if (body.report) state.report = body.report;
      renderSources();
      applyStatus();
      setSaved(SAVE_OK);
    }).catch(function (error) {
      toast(error.message, 'error');
    });
  }

  refs.transcriptUpload.addEventListener('click', uploadTranscript);
  refs.transcriptSave.addEventListener('click', function () {
    var text = refs.transcriptText.value;
    if (!text.trim()) {
      toast('请先粘贴逐字稿内容', 'error');
      return;
    }
    api(docUrl('/transcript'), jsonOptions('POST', { text: text })).then(function (body) {
      refs.transcriptText.value = '';
      if (body.report) state.report = body.report;
      renderSources();
      applyStatus();
      setSaved(SAVE_OK);
    }).catch(function (error) {
      toast(error.message, 'error');
    });
  });

  load();
})();
