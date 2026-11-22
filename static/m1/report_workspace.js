/* M1 会后报告审阅页：资料、生成、待处理、报告内容、审核与发布。 */
(function () {
  'use strict';

  var root = document.getElementById('r4Review');
  if (!root) return;

  var prepId = parseInt(root.getAttribute('data-prep-id'), 10);
  var studentName = root.getAttribute('data-student') || '';

  var SAVE_OK = '已保存';
  var SAVE_FAIL = '保存失败';
  var UPLOAD_FAIL = '上传失败，请重试。';
  var uploadingTranscript = false;
  var uploadingOther = false;
  var transcriptAttempt = 0;
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
    polling: null,
    panelEls: {},
    tab: 'R1',
    step: null,
    stepped: false,
    previewMode: false,
    transcriptSaving: null
  };

  var refs = {
    saved: document.getElementById('r4Saved'),
    retry: document.getElementById('r4Retry'),
    sourceSave: document.getElementById('r4SourceSave'),
    sourceRetry: document.getElementById('r4SourceRetry'),
    official: document.getElementById('r4Official'),
    frame: document.getElementById('r4Preview'),
    previewPane: document.getElementById('r4PreviewPane'),
    previewToggle: document.getElementById('r4PreviewToggle'),
    tag: document.getElementById('r4Tag'),
    srcNote: document.getElementById('r4SrcNote'),
    exportTitle: document.getElementById('r4ExportTitle'),
    print: document.getElementById('r4Print'),
    evidence: document.getElementById('r4Evidence'),
    publish: document.getElementById('r4Publish'),
    reopen: document.getElementById('r4Reopen'),
    publishedNote: document.getElementById('r4PublishedNote'),
    transcriptDrop: document.getElementById('r4Drop'),
    transcriptPick: document.getElementById('r4TranscriptPick'),
    transcriptError: document.getElementById('r4TranscriptError'),
    transcriptLine: document.getElementById('r4TranscriptLine'),
    transcriptName: document.getElementById('r4TranscriptName'),
    transcriptMeta: document.getElementById('r4TranscriptMeta'),
    transcriptReplace: document.getElementById('r4TranscriptReplace'),
    transcriptFile: document.getElementById('r4TranscriptFile'),
    transcriptText: document.getElementById('r4TranscriptText'),
    pasteFold: document.getElementById('r4PasteFold'),
    auto: document.getElementById('r4Auto'),
    others: document.getElementById('r4Others'),
    otherDrop: document.getElementById('r4OtherDrop'),
    otherPick: document.getElementById('r4OtherPick'),
    otherError: document.getElementById('r4OtherError'),
    otherFile: document.getElementById('r4OtherFile'),
    cover: document.getElementById('r4Cover'),
    metaStudent: document.getElementById('r4MetaStudent'),
    generate: document.getElementById('r4Generate'),
    generateBody: document.getElementById('r4GenerateBody'),
    generateReason: document.getElementById('r4GenerateReason'),
    genBox: document.getElementById('r4GenBox'),
    genOpen: document.getElementById('r4GenOpen'),
    meter: document.getElementById('r4Meter'),
    steps: document.getElementById('r4Steps'),
    safety: document.getElementById('r4Safety'),
    safetyItems: document.getElementById('r4SafetyItems'),
    checks: document.getElementById('r4Checks'),
    checksMore: document.getElementById('r4ChecksMore'),
    needCount: document.getElementById('r4NeedCount'),
    needText: document.getElementById('r4NeedText'),
    tipCount: document.getElementById('r4TipCount'),
    tabs: document.getElementById('r4Tabs'),
    content: document.getElementById('r4Content'),
    panels: document.getElementById('r4Panels')
  };

  var reportSave = window.M1ReportSave;
  var saves = reportSave.create(docUrl(''), renderSaveState, applySaveResult);
  var debounced = new Set();
  var frameEditor = null;
  var action = null;

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
    refs.saved.className = 'saved' + (isError ? ' r4-err' : '');
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
  function onUnload(event) {
    event.preventDefault();
    event.returnValue = '';
  }

  function updateActionButtons(snapshot) {
    var blocked = (state.checks || []).some(function (c) { return c.level === 'block'; });
    refs.print.disabled = !!action;
    refs.previewToggle.disabled = !!action;
    refs.reopen.disabled = !!action;
    refs.publish.disabled = !!action || (blocked && !snapshot.dirty && !snapshot.pending);
  }

  function renderSaveState(snapshot) {
    var unsaved = snapshot.dirty || snapshot.pending;
    if (unsaved) window.addEventListener('beforeunload', onUnload);
    else window.removeEventListener('beforeunload', onUnload);
    if (snapshot.fault) setSaved(snapshot.fault.message || SAVE_FAIL, true);
    else if (snapshot.saving) setSaved('保存中…');
    else setSaved(unsaved ? '有未保存的修改' : SAVE_OK);
    var retryable = !!snapshot.fault && snapshot.fault.status !== 409;
    show(refs.retry, retryable);
    show(refs.sourceRetry, retryable);
    show(refs.sourceSave, !!snapshot.fault);
    refs.sourceSave.textContent = snapshot.fault ? snapshot.fault.message : '';
    updateActionButtons(snapshot);
    if (frameEditor) frameEditor.sync(snapshot, !!action);
  }

  function applySaveResult(body, item) {
    if (body.report) state.report = body.report;
    state.report.rev = body.rev;
    state.report.status = body.status;
    state.report.current_version_id = body.version_id;
    state.report.label = STATUS_LABELS[body.status] || body.status;
    if (body.checks) state.checks = body.checks;
    if (body.appendix) state.appendix = body.appendix;
    if (body.version_id && (item.endpoint === '/doc' || item.endpoint.indexOf('/evidence/') === 0)) {
      state.has_edits = true;
    }
    applyStatus();
    renderTodo();
    renderAppendixPanel();
    if (frameEditor && body.checks) frameEditor.checks(body.checks);
    if (item.endpoint === '/doc' && item.body.changes[0].path[0] === 'meta' && frameEditor) {
      frameEditor.refresh();
    }
    (body.impacts || []).forEach(function (message) { toast(message, 'info'); });
  }

  function saveDoc(path, value) {
    return saves.add('/doc', 'PUT', { changes: [{ path: path, value: value }] });
  }

  function bindDebounced(input, onChange, save) {
    input.__r4Last = input.value;
    input.__r4Dirty = false;
    var timer = null;
    function flush() {
      clearTimeout(timer);
      debounced.delete(flush);
      var value = input.value;
      if (input.__r4Dirty && value !== input.__r4Last) {
        input.__r4Last = value;
        save(value);
      }
      input.__r4Dirty = false;
      saves.setDirty(flush, false);
    }
    input.addEventListener('input', function () {
      if (onChange) onChange(input.value);
      input.__r4Dirty = input.value !== input.__r4Last;
      debounced.add(flush);
      saves.setDirty(flush, input.__r4Dirty);
      clearTimeout(timer);
      timer = setTimeout(flush, 1500);
    });
    input.addEventListener('blur', flush);
  }

  function bindTextSave(input, path, mark) {
    if (!input) return;
    input.__r4Path = path;
    if (path) input.setAttribute('data-path', pathKey(path));
    bindDebounced(input, null, function (value) {
      saveDoc(path, value).then(function () { setMark(mark, 'edited'); });
    });
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
    button.id = 'r4Tab-' + key;
    button.setAttribute('aria-controls', 'r4Panel-' + key);
    button.addEventListener('click', function () { activateTab(key); });
    refs.tabs.appendChild(button);
    var panel = el('div', 'r4-panel');
    panel.id = 'r4Panel-' + key;
    panel.setAttribute('role', 'tabpanel');
    panel.setAttribute('aria-labelledby', button.id);
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
      buttons[i].tabIndex = on ? 0 : -1;
    }
    Object.keys(state.panelEls).forEach(function (name) {
      state.panelEls[name].hidden = name !== key;
    });
    var current = hashParts().step || state.step;
    try {
      history.replaceState(null, '', current ? stepHash(current, key) : '#tab=' + key);
    } catch (error) {
      /* 本地文件或受限环境忽略。 */
    }
  }

  function hashParts() {
    var hash = (window.location.hash || '').replace('#', '');
    if (hash.indexOf('=') < 0) return { tab: hash };
    var parts = {};
    hash.split('&').forEach(function (pair) {
      var at = pair.indexOf('=');
      if (at > 0) parts[pair.slice(0, at)] = pair.slice(at + 1);
    });
    return parts;
  }

  function stepHash(step, tab) {
    var hash = '#step=' + step;
    if (tab) hash += '&tab=' + tab;
    return hash;
  }

  function hashTab() {
    return hashParts().tab || 'R1';
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
    var hiddenSection = target.closest ? target.closest('[data-step]') : null;
    if (hiddenSection && hiddenSection.hidden) showStep(hiddenSection.getAttribute('data-step'));
    var panel = target.closest ? target.closest('.r4-panel') : null;
    if (panel && panel.id.indexOf('r4Panel-') === 0) activateTab(panel.id.slice(8));
    var field = target.matches('button, input, textarea, select') ? target
      : target.querySelector('summary, textarea, input, select, button') || target;
    var fold = field.closest('details');
    if (fold && field.tagName !== 'SUMMARY') fold.open = true;
    if (field.tabIndex < 0 && !field.matches('button, input, textarea, select')) field.tabIndex = -1;
    field.scrollIntoView({ block: 'center' });
    field.focus({ preventScroll: true });
  }

  /* ------------------------------------------------------------------ */
  /* 资料 / 封面                                                          */
  /* ------------------------------------------------------------------ */
  function autoRow(label, how, stateClass, stateText) {
    var row = el('div');
    var name = el('span');
    name.appendChild(document.createTextNode(label + ' '));
    name.appendChild(el('span', 'hint', how));
    row.appendChild(name);
    row.appendChild(el('span', 'st ' + stateClass, stateText));
    refs.auto.appendChild(row);
  }

  function renderSources() {
    var inputs = state.inputs || {};
    var y4 = inputs.y4 || {};
    var ft = inputs.first_touch || {};
    var q = inputs.questionnaires || {};

    refs.auto.textContent = '';
    autoRow('Y4 Assessment', '平台自动读取',
            y4.complete ? 's0' : 's2', y4.complete ? '已读取' : '未完成');
    autoRow('First Touch Meeting', '平台自动读取',
            ft.present ? 's0' : 'sn', ft.present ? '已读取' : '没有记录');
    if (q.total > 0) {
      autoRow('补充问卷', '平台自动读取',
              q.done >= q.total ? 's0' : 's1', q.done + ' / ' + q.total);
    }

    var report = state.report || {};
    var length = report.transcript_length || 0;
    show(refs.transcriptDrop, !length);
    show(refs.transcriptLine, !!length);
    refs.transcriptName.textContent = report.transcript_filename || '粘贴的文字';
    refs.transcriptMeta.textContent = length ? (length.toLocaleString('en-US') + ' 字') : '';
    if (length && !report.transcript_filename && refs.pasteFold) refs.pasteFold.open = true;
    refs.srcNote.textContent = length
      ? 'First Meeting 逐字稿 · ' + length.toLocaleString('en-US') + ' 字'
      : '上传后生成报告';

    refs.others.textContent = '';
    var others = inputs.others || [];
    others.forEach(function (item) {
      var row = el('div', 'file');
      var text = el('span');
      text.appendChild(el('b', '', item.label || '其他资料'));
      if (item.filename) text.appendChild(el('span', 'mu', ' ' + item.filename));
      row.appendChild(text);
      var remove = el('button', 'btn s g', '删除');
      remove.type = 'button';
      remove.addEventListener('click', function () { deleteOther(item); });
      row.appendChild(remove);
      refs.others.appendChild(row);
    });
  }

  function deleteOther(item) {
    if (!window.confirm('删除这份资料？')) return;
    api('/api/m1/sources/' + item.id, { method: 'DELETE' }).then(function () {
      toast('已删除');
      return refreshInputs();
    }).catch(function (error) {
      toast(error.message, 'error');
    });
  }

  function uploadControl(kind) {
    if (kind === 'transcript') {
      return { pick: transcriptExists() ? refs.transcriptReplace : refs.transcriptPick,
               error: refs.transcriptError, input: refs.transcriptFile };
    }
    return { pick: refs.otherPick, error: refs.otherError, input: refs.otherFile };
  }

  function clearUploadError(kind) {
    var control = uploadControl(kind);
    if (!control.error) return;
    control.error.textContent = '';
    control.error.hidden = true;
  }

  function showUploadError(kind, message) {
    var control = uploadControl(kind);
    if (control.error) {
      control.error.textContent = message || UPLOAD_FAIL;
      control.error.hidden = false;
    }
    if (control.input) control.input.value = '';
    focusUploadControl(kind);
  }

  function syncUploadButtons(locked) {
    var transcriptLocked = locked || uploadingTranscript || state.report.status === 'generating';
    refs.transcriptPick.disabled = transcriptLocked;
    refs.transcriptReplace.disabled = transcriptLocked;
    refs.otherPick.disabled = locked || uploadingOther;
  }

  function setUploadBusy(kind, busy) {
    if (kind === 'transcript') uploadingTranscript = busy;
    else uploadingOther = busy;
    syncUploadButtons(!!action || state.report.status === 'published');
  }

  function focusUploadControl(kind) {
    if (state.step !== 'sources') return;
    var target = uploadControl(kind).pick;
    if (target && !target.disabled) target.focus();
  }

  function uploadOther(file) {
    if (!file || refs.otherPick.disabled) return;
    clearUploadError('other');
    setUploadBusy('other', true);
    var form = new FormData();
    form.append('file', file);
    form.append('category', 'report_other');
    reportSave.request('/api/m1/preps/' + prepId + '/sources', { method: 'POST', body: form })
      .then(function (body) {
        refs.otherFile.value = '';
        setUploadBusy('other', false);
        var source = body.source;
        var others = state.inputs.others || [];
        state.inputs.others = others.filter(function (item) { return item.id !== source.id; })
          .concat({ id: source.id, label: source.label, filename: source.filename });
        renderSources();
        applyStatus();
        focusUploadControl('other');
        toast('已上传');
      })
      .catch(function (error) {
        setUploadBusy('other', false);
        showUploadError('other', error.message);
      });
  }

  function refreshInputs() {
    return api(docUrl('')).then(function (body) {
      state.inputs = body.inputs || {};
      renderSources();
      applyStatus();
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
    if (!(state.report.transcript_length > 0)) missing.push('需要先上传心有灵析会议逐字稿');
    var locked = status === 'published';
    var generating = status === 'generating';
    refs.generate.disabled = locked || generating || missing.length > 0;
    refs.generateReason.textContent = generating ? '正在生成。' : (locked ? '已正式发布。要重新生成，请先在「② 核对并发布」点「重新打开」。' : missing.join('；'));
    var regen = document.getElementById('r4Regenerate');
    if (regen) {
      regen.disabled = refs.generate.disabled;
      regen.title = refs.generateReason.textContent || '';
    }
  }

  function showGenPanel() {
    if (refs.generateBody) refs.generateBody.hidden = true;
    show(refs.genBox, true);
    show(refs.genOpen, false);
  }

  function hideGenPanel() {
    if (refs.generateBody) refs.generateBody.hidden = false;
    show(refs.genBox, false);
    show(refs.genOpen, false);
    refs.steps.textContent = '';
    refs.meter.style.width = '0%';
  }

  function renderSteps(steps, message) {
    refs.steps.textContent = '';
    if (message) refs.steps.appendChild(el('div', 'sub', message));
    var list = steps || [];
    var done = 0;
    list.forEach(function (step) {
      var ok = step.state === 'done' || step.state === 'skipped';
      if (ok) done += 1;
      var row = el('div', step.state === 'running' ? 'on' : (ok ? 'ok' : ''));
      row.appendChild(el('i'));
      var text = el('span');
      text.appendChild(document.createTextNode(step.label || step.step || ''));
      row.appendChild(text);
      row.appendChild(el('span', 'mu', STEP_LABELS[step.state] || step.state || ''));
      refs.steps.appendChild(row);
    });
    if (list.length) {
      refs.meter.style.width = Math.round((done / list.length) * 100) + '%';
    }
  }

  var genStatus = document.getElementById('r4GenStatus');
  var genRetry = document.getElementById('r4GenRetry');

  function generationStatus(message, retry) {
    genStatus.textContent = message;
    show(genStatus, !!message);
    show(genRetry, retry);
  }

  function stopPolling() {
    clearTimeout(state.polling);
    state.polling = null;
  }

  function pollJob(jobId, failures) {
    stopPolling();
    state.polling = setTimeout(function () {
      api('/api/m1/jobs/' + jobId).then(function (body) {
        var job = body.job || {};
        generationStatus('', false);
        renderSteps(job.steps, job.message);
        if (job.status === 'done') {
          stopPolling();
          load().then(function () {
            renderSteps(job.steps, '生成完成');
            show(refs.genOpen, true);
            toast('报告已生成');
          });
        } else if (job.status === 'error') {
          stopPolling();
          hideGenPanel();
          generationStatus(job.message || '生成失败，已保留之前的报告。', false);
          load();
        } else {
          pollJob(jobId, 0);
        }
      }).catch(function () {
        stopPolling();
        var retry = (failures || 0) + 1;
        generationStatus('暂时无法载入生成进度。', retry >= 4);
        if (retry < 4) pollJob(jobId, retry);
      });
    }, 2000 * ((failures || 0) + 1));
  }

  function resumeJobIfRunning() {
    if (state.report.status !== 'generating') {
      stopPolling();
      return;
    }
    if (state.polling) return;
    showGenPanel();
    var jobId = state.payload && state.payload.job_id;
    if (jobId) pollJob(jobId, 0);
    else generationStatus('生成正在进行，暂时无法载入进度。', true);
  }

  genRetry.addEventListener('click', function () {
    generationStatus('', false);
    load();
  });

  async function generate(confirmOverwrite) {
    if (action) return;
    try {
      await flushEdits();
    } catch (error) {
      setSaved(error.message, true);
      toast(error.message, 'error');
      return;
    }
    if (!confirmOverwrite && state.has_edits) {
      if (!window.confirm(GENERATE_CONFIRM)) return;
      confirmOverwrite = true;
    }
    api(docUrl('/generate'), jsonOptions('POST', { confirm_overwrite: !!confirmOverwrite }))
      .then(function (body) {
        state.report.status = 'generating';
        state.report.label = STATUS_LABELS.generating;
        applyStatus();
        showGenPanel();
        renderSteps([], '生成任务运行中');
        pollJob(body.job_id);
      })
      .catch(function (error) {
        if (error.status === 409 && error.body && error.body.error === '需要确认覆盖') {
          if (window.confirm(GENERATE_CONFIRM)) generate(true);
          return;
        }
        toast(error.message, 'error');
        hideGenPanel();
        load();
      });
  }

  /* ------------------------------------------------------------------ */
  /* 待处理                                                              */
  /* ------------------------------------------------------------------ */
  function checkItem(check) {
    var item = el('div', 'r4-checkitem');
    var row = el('button', 'r4-check ' + (check.level === 'block' ? 'block' : 'review'));
    row.type = 'button';
    row.appendChild(el('span', 'r4-checklevel', check.level === 'block' ? '阻断' : '提示'));
    row.appendChild(el('span', '', check.message || ''));
    if (check.path && check.path.length) {
      row.addEventListener('click', function () {
        if (!state.previewMode) scrollToPath(check.path);
        else switchReviewMode(false).then(function (changed) {
          if (changed) scrollToPath(check.path);
        });
      });
      item.appendChild(row);
    } else if (check.code === 'no_transcript') {
      row.addEventListener('click', function () {
        showStep('sources');
        refs.transcriptPick.focus();
      });
      item.appendChild(row);
    } else {
      item.appendChild(el('p', 'hint', check.message || ''));
    }
    return item;
  }

  function renderChecks() {
    var list = state.checks || [];
    var blocks = list.filter(function (check) { return check.level === 'block'; });
    var reviews = list.filter(function (check) { return check.level !== 'block'; });
    refs.checks.textContent = '';
    refs.checksMore.textContent = '';
    if (!blocks.length) refs.checks.appendChild(emptyNote('没有必须处理的问题。'));
    blocks.forEach(function (check) { refs.checks.appendChild(checkItem(check)); });
    reviews.forEach(function (check) { refs.checksMore.appendChild(checkItem(check)); });
    renderNeed(blocks.length, reviews.length);
  }

  function renderNeed(blockCount, tipCount) {
    refs.needCount.textContent = String(blockCount);
    refs.tipCount.textContent = String(tipCount);
    refs.needText.textContent = blockCount
      ? '选择待补全项，跳到对应的报告内容。'
      : '没有必须补全的地方。';
    refs.needText.className = blockCount ? 'hint' : 'hint r4-okline';
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
    renderChecks();
  }

  /* ------------------------------------------------------------------ */
  /* 步骤 / 发言人 / 导出                                                 */
  /* ------------------------------------------------------------------ */
  var STEPS = ['sources', 'review'];

  function showStep(name) {
    if (name === 'export') name = 'review';
    if (STEPS.indexOf(name) < 0) name = 'sources';
    if (name === 'review' && !state.doc) name = 'sources';
    state.step = name;
    var hasDoc = !!state.doc;
    document.querySelectorAll('#r4StepNav a[data-step]').forEach(function (a) {
      var step = a.getAttribute('data-step');
      var cls = '';
      if (step === 'sources') cls = (step === name) ? 'n' : (hasDoc ? 'd' : '');
      else cls = (step === name) ? 'n' : (hasDoc ? '' : 'x');
      a.className = cls;
      if (step === 'review' && !hasDoc) {
        a.setAttribute('aria-disabled', 'true');
        a.removeAttribute('aria-current');
      } else {
        a.removeAttribute('aria-disabled');
        if (step === name) a.setAttribute('aria-current', 'step');
        else a.removeAttribute('aria-current');
      }
    });
    document.querySelectorAll('#r4StepSources, #r4StepReview').forEach(function (node) {
      node.hidden = node.getAttribute('data-step') !== name;
    });
    try { history.replaceState(null, '', stepHash(name, state.tab)); } catch (e) { /* ignore */ }
    if (name === 'review') { loadSpeakers(); loadPreview(false); }
    renderExportState();
    window.scrollTo(0, 0);
  }

  function defaultStep() {
    if (state.report.status === 'generating') return 'sources';
    var match = /step=(\w+)/.exec(window.location.hash || '');
    if (match && STEPS.indexOf(match[1]) >= 0) return match[1];
    return state.doc ? 'review' : 'sources';
  }

  function loadSpeakers() {
    return api('/api/m1/preps/' + prepId + '/report/speakers').then(function (body) {
      if (!speakerChanges().controls.length) {
        renderSpeakers(body.speakers || {});
        applyStatus();
      }
    }).catch(function () { /* card keeps its default text */ });
  }

  function loadPreview(force) {
    var frame = refs.frame;
    var empty = document.getElementById('r4PreviewEmpty');
    if (!frame) return;
    var has = !!state.doc && state.report.status !== 'generating';
    show(refs.previewToggle, has);
    show(refs.content, has && !state.previewMode);
    show(refs.previewPane, has && state.previewMode);
    frame.hidden = !has || !state.previewMode;
    if (empty) empty.hidden = has;
    if (!has || !state.previewMode) return;
    var src = '/m1/preps/' + prepId + '/report/print?edit=1';
    if (force || !frame.getAttribute('src')) {
      frameEditor = null;
      frame.setAttribute('src', src);
    }
  }

  async function switchReviewMode(preview) {
    if (state.previewMode === preview || action) return false;
    action = 'preview';
    try {
      var ready = flushEdits();
      if (frameEditor) frameEditor.lock(true);
      applyStatus();
      await ready;
      state.previewMode = preview;
      if (!preview) {
        frameEditor = null;
        refs.frame.removeAttribute('src');
      }
      refs.previewToggle.setAttribute('aria-pressed', String(preview));
      refs.previewToggle.textContent = preview ? '返回分节审阅' : '查看打印版式';
      if (!preview) await load();
      loadPreview(preview);
      return true;
    } catch (error) {
      setSaved(error.message, true);
      return false;
    } finally {
      action = null;
      if (frameEditor) frameEditor.lock(state.report.status === 'published');
      applyStatus();
    }
  }

  refs.previewToggle.addEventListener('click', function () {
    switchReviewMode(!state.previewMode);
  });

  refs.tabs.addEventListener('keydown', function (event) {
    var tabs = Array.from(refs.tabs.querySelectorAll('[role=tab]'));
    var index = tabs.indexOf(event.target);
    if (index < 0) return;
    switch (event.key) {
      case 'ArrowRight': index = (index + 1) % tabs.length; break;
      case 'ArrowLeft': index = (index + tabs.length - 1) % tabs.length; break;
      case 'Home': index = 0; break;
      case 'End': index = tabs.length - 1; break;
      default: return;
    }
    event.preventDefault();
    activateTab(tabs[index].dataset.tab);
    tabs[index].focus();
  });

  function roleSelect(current) {
    var select = el('select');
    if (current === '') {
      var mixed = el('option', '', '（混合）');
      mixed.value = '';
      select.appendChild(mixed);
    }
    SPEAKERS.forEach(function (name) {
      var option = el('option', '', name);
      option.value = name;
      select.appendChild(option);
    });
    select.value = current;
    return select;
  }

  function renderSpeakers(sp) {
    var line = document.getElementById('r4SpkLine');
    var more = document.getElementById('r4SpkMore');
    var labelsWrap = document.getElementById('r4SpkLabels');
    var turnsWrap = document.getElementById('r4SpkTurns');
    var only = document.getElementById('r4SpkOnlyUnsure');
    if (!line || !more || !labelsWrap || !turnsWrap || !only) return;
    var status = sp.status || 'none';
    if (status === 'none' || status === 'stale' || status === 'error') {
      var text = '生成报告时会自动识别发言人。';
      if (status === 'error' && sp.message) text += ' ' + sp.message;
      line.textContent = text;
      more.hidden = true;
      return;
    }
    var counts = sp.counts || {};
    line.textContent = '学生 ' + (counts['学生'] || 0) + ' 段 · 导师 ' + (counts['导师'] || 0) + ' 段'
      + (counts['家长'] ? ' · 家长 ' + counts['家长'] + ' 段' : '')
      + (counts['其他'] ? ' · 其他 ' + counts['其他'] + ' 段' : '')
      + (counts['待确认'] ? ' · 待确认 ' + counts['待确认'] + ' 段' : '');
    more.hidden = false;

    labelsWrap.textContent = '';
    (sp.labels || []).forEach(function (item) {
      var row = el('div', 'r4-spk-row');
      row.appendChild(el('b', '', item.label));
      row.appendChild(el('span', 'sub', item.turns + ' 段 · ' + (item.samples || []).join(' / ')));
      var select = roleSelect(item.role || '');
      select.setAttribute('data-label', item.label);
      select.__r4Role = item.role || '';
      row.appendChild(select);
      labelsWrap.appendChild(row);
    });

    turnsWrap.textContent = '';
    (sp.turns || []).forEach(function (turn) {
      var row = el('div', 'r4-spk-row');
      row.setAttribute('data-role', turn.role || '待确认');
      row.appendChild(el('span', 'r4-spk-n', String(turn.n)));
      var select = roleSelect(turn.role || '待确认');
      select.setAttribute('data-turn', String(turn.n));
      select.__r4Role = turn.role || '待确认';
      row.appendChild(select);
      row.appendChild(el('span', 'r4-spk-text', turn.text || ''));
      turnsWrap.appendChild(row);
    });

    function applyFilter() {
      var rows = turnsWrap.querySelectorAll('.r4-spk-row');
      for (var i = 0; i < rows.length; i += 1) {
        rows[i].hidden = only.checked && rows[i].getAttribute('data-role') !== '待确认';
      }
    }
    only.onchange = applyFilter;
    if ((counts['待确认'] || 0) > 0) {
      more.open = true;
      only.checked = true;
    } else {
      only.checked = false;
    }
    applyFilter();
  }

  function speakerChanges() {
    var labels = {};
    var turns = {};
    var controls = Array.from(root.querySelectorAll('#r4SpkLabels select, #r4SpkTurns select'))
      .filter(function (item) { return item.value && item.value !== item.__r4Role; });
    controls.forEach(function (item) {
      if (item.hasAttribute('data-label')) labels[item.getAttribute('data-label')] = item.value;
      else turns[item.getAttribute('data-turn')] = item.value;
    });
    return { labels: labels, turns: turns, controls: controls };
  }

  function saveSpeakers() {
    var changes = speakerChanges();
    if (!changes.controls.length) return false;
    changes.controls.forEach(function (item) { item.__r4Role = item.value; });
    saves.add('/speakers', 'PUT', { labels: changes.labels, turns: changes.turns })
      .then(function (body) {
        if (!speakerChanges().controls.length) {
          if (body.speakers) {
            renderSpeakers(body.speakers);
            applyStatus();
          } else {
            loadSpeakers();
          }
        }
        toast(body.notice || SAVE_OK);
      });
    saves.setDirty(saveSpeakers, false);
    return true;
  }

  function renderExportState() {
    var node = document.getElementById('r4ExportState');
    if (!node) return;
    var blocks = (state.checks || []).filter(function (c) { return c.level === 'block'; }).length;
    var status = state.report && state.report.status;
    if (!state.doc) node.textContent = '还没有生成报告。';
    else if (status === 'published') node.textContent = '已正式发布。';
    else if (blocks) node.textContent = '报告还不完整（' + blocks + ' 项），补全后才能正式发布。现在导出的是草稿。';
    else node.textContent = '可以导出草稿，也可以直接正式发布。';
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
      saveEvidence(item, { speaker: speaker.value });
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
      saveEvidence(item, { status: status.value });
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

  function saveEvidence(item, fields) {
    saves.add('/evidence/' + item.id, 'PUT', fields).then(function () {
      Object.assign(item, fields);
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
    bindDebounced(input, function (value) {
      row[key] = { text: value, src: 'edited' };
    }, function () {
      saveDoc(['plan'], planPayload()).then(function () { setMark(mark, 'edited'); });
    });
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
    ['#r4Cover', '#r4Sources', '#r4GenerateCard', '#r4Content', '#r4Speakers'].forEach(function (sel) {
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
    syncUploadButtons(locked);
    show(refs.publishedNote, state.report.status === 'published');
  }

  function renderTag() {
    var status = state.report.status || 'draft';
    var text = '草稿';
    if (!state.doc) text = '逐字稿';
    else if (status === 'generating') text = '生成中';
    else if (status === 'published') text = '已发布';
    refs.tag.textContent = text;
  }

  function applyStatus() {
    var status = state.report.status || 'draft';
    renderTag();
    if (refs.exportTitle) {
      refs.exportTitle.textContent = status === 'published' ? '已正式发布' : '正式发布';
    }

    var hasVersion = state.doc !== null;
    var locked = status === 'published';
    show(refs.print, hasVersion && ['ai_draft', 'needs_check', 'reviewing', 'approved', 'published'].indexOf(status) !== -1);
    refs.print.textContent = status === 'approved' || status === 'published'
      ? '下载正式报告（家长）' : '导出报告草稿（内部审阅）';
    show(refs.evidence, hasVersion && status !== 'draft' && status !== 'generating');
    show(refs.publish, hasVersion && ['ai_draft', 'needs_check', 'reviewing', 'approved'].indexOf(status) !== -1);
    updateActionButtons(saves.snapshot());
    var official = state.payload && state.payload.official;
    show(refs.official, !!official && official.rev !== state.report.rev);
    if (official) {
      refs.official.href = reportSave.printUrl(refs.print.dataset.exportUrl,
        { expected_rev: official.rev, version_id: official.version_id });
    }
    show(refs.reopen, status === 'approved' || status === 'published');

    setEditable(locked || !!action);
    renderGenerateState();
    renderExportState();
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
    renderSources();
    renderCover();
    renderTodo();
    buildContent();
    applyStatus();
    resumeJobIfRunning();
  }

  function load() {
    return api(docUrl('')).then(function (body) {
      var report = body.report;
      var prev = saves.snapshot().pin;
      if (!saves.reset(report.rev, report.current_version_id)) return;
      applyPayload(body);
      if (prev && (prev.version_id !== report.current_version_id || prev.expected_rev !== report.rev)) {
        loadPreview(true);
      }
      if (!state.stepped) {
        state.stepped = true;
        showStep(defaultStep());
      }
      renderExportState();
      if (!refs.saved.textContent) setSaved(SAVE_OK);
    }).catch(function (error) {
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

  function flushEdits() {
    clearTimeout(transcriptTimer);
    if (frameEditor) frameEditor.collect();
    debounced.forEach(function (flush) { flush(); });
    saveSpeakers();
    saveTranscript();
    return saves.flush();
  }

  async function commitReview(kind, pin) {
    try {
      return await reportSave.request(docUrl('/' + kind), jsonOptions('POST', pin));
    } catch (error) {
      if (error.status && !error.uncertain) throw error;
      // A lost response can follow a committed transition. Verify the resulting
      // revision before refreshing the editor or offering another attempt.
      var saved = await reportSave.request(docUrl(''), { cache: 'no-store' });
      var report = saved.report;
      if (report.rev === pin.expected_rev + 1 && report.current_version_id === pin.version_id
          && report.status === (kind === 'publish' ? 'published' : 'reviewing')) {
        return saved;
      }
      if (report.rev !== pin.expected_rev || report.current_version_id !== pin.version_id) {
        saves.conflict();
        throw saves.snapshot().fault;
      }
      throw error;
    }
  }

  async function runReviewAction(kind) {
    if (action) return;
    if (kind === 'publish' && !window.confirm('确认正式发布？')) return;
    var popup = null;
    action = kind;
    try {
      if (kind === 'print') popup = reportSave.openPrintTab();
      if (state.previewMode && state.step === 'review' && state.report.status !== 'published' && !frameEditor) {
        throw new Error('报告预览仍在加载，请稍后重试。');
      }
      var ready = flushEdits();
      if (frameEditor) frameEditor.lock(true);
      applyStatus();
      var pin = await ready;
      if (!pin || !pin.version_id) throw new Error('还没有可导出的报告。');
      if (kind === 'print') {
        popup.location.replace(reportSave.printUrl(refs.print.dataset.exportUrl, pin));
        return;
      }
      if (kind === 'reopen' && state.report.status === 'reviewing') return;
      var body = await commitReview(kind, pin);
      if (body.report.status === 'published' && frameEditor) frameEditor.lock(true);
      if (body.report.status === 'published') {
        state.payload.official = { rev: body.report.rev, version_id: body.report.current_version_id };
      } else if (body.official) {
        state.payload.official = body.official;
      }
      saves.reset(body.report.rev, body.report.current_version_id);
      state.report = body.report;
      if (body.checks) state.checks = body.checks;
      loadPreview(true);
      applyStatus();
      setSaved(SAVE_OK);
    } catch (error) {
      if (popup) popup.close();
      if (error.status === 409 && error.body && error.body.rev) saves.conflict();
      if (error.body && error.body.checks) {
        state.checks = error.body.checks;
        renderTodo();
      }
      setSaved(error.message, true);
      toast(error.message, 'error');
    } finally {
      action = null;
      if (frameEditor) {
        frameEditor.lock(state.report.status === 'published');
        frameEditor.sync(saves.snapshot(), false);
      }
      applyStatus();
    }
  }

  refs.print.addEventListener('click', function (event) {
    if (event.detail <= 1) runReviewAction('print');
  });
  refs.publish.addEventListener('click', function (event) {
    if (event.detail <= 1) runReviewAction('publish');
  });
  refs.reopen.addEventListener('click', function (event) {
    if (event.detail <= 1) runReviewAction('reopen');
  });
  refs.retry.addEventListener('click', saves.retry);
  refs.sourceRetry.addEventListener('click', saves.retry);

  function uploadTranscript(chosen) {
    if (uploadControl('transcript').pick.disabled) return;
    var file = chosen || (refs.transcriptFile.files && refs.transcriptFile.files[0]);
    if (!file) {
      showUploadError('transcript', '请先选择文件');
      return;
    }
    clearUploadError('transcript');
    setUploadBusy('transcript', true);
    var attempt = transcriptAttempt += 1;
    var form = new FormData();
    form.append('file', file);
    saves.add('/transcript', 'POST', form, function (error, canChooseAgain) {
      if (canChooseAgain) setUploadBusy('transcript', false);
      showUploadError('transcript', error.message);
      if (!canChooseAgain && state.step === 'sources' && !refs.sourceRetry.hidden) {
        refs.sourceRetry.focus();
      }
    }).then(function () {
      if (attempt !== transcriptAttempt) return;
      refs.transcriptFile.value = '';
      setUploadBusy('transcript', false);
      clearUploadError('transcript');
      toast('逐字稿已上传');
      renderSources();
      applyStatus();
      focusUploadControl('transcript');
    });
  }

  var transcriptTimer = null;
  var REPLACE_CONFIRM = '将用新内容替换现有逐字稿（%n 字），确定吗？';

  function transcriptExists() {
    return !!(state.report && state.report.transcript_length > 0);
  }

  function replaceButton() {
    var button = document.getElementById('r4PasteReplace');
    if (button) return button;
    button = el('button', 'btn sm', '用这段文字替换现有逐字稿');
    button.type = 'button';
    button.id = 'r4PasteReplace';
    button.hidden = true;
    refs.transcriptText.parentNode.insertBefore(button, refs.transcriptText.nextSibling);
    button.addEventListener('click', function () {
      var n = state.report && state.report.transcript_length || 0;
      if (!window.confirm(REPLACE_CONFIRM.replace('%n', n))) return;
      saveTranscript(true).then(function (saved) { if (saved) button.hidden = true; });
    });
    return button;
  }

  function saveTranscript(force) {
    var text = refs.transcriptText.value.trim();
    if (!text || text === state.transcriptSaving) {
      saves.setDirty(refs.transcriptText, false);
      return Promise.resolve(false);
    }
    if (transcriptExists() && !force) {
      replaceButton().hidden = false;
      saves.setDirty(refs.transcriptText, true);
      return Promise.resolve(false);
    }
    var fault = saves.snapshot().fault;
    if (state.transcriptSaving && !(fault && (fault.status === 400 || fault.status === 422))) {
      return Promise.resolve(false);
    }
    state.transcriptSaving = text;
    refs.transcriptMeta.textContent = '保存中…';
    var saved = saves.add('/transcript', 'POST', { text: text });
    saves.setDirty(refs.transcriptText, false);
    return saved.then(function () {
      state.transcriptSaving = null;
      if (refs.transcriptText.value.trim() === text) refs.transcriptText.value = '';
      renderSources();
      saves.setDirty(refs.transcriptText, !!refs.transcriptText.value.trim());
      applyStatus();
      return true;
    });
  }

  if (refs.transcriptFile) {
    refs.transcriptFile.addEventListener('change', function () {
      clearUploadError('transcript');
      if (!(refs.transcriptFile.files && refs.transcriptFile.files[0])) return;
      if (transcriptExists()) {
        var n = state.report.transcript_length;
        if (!window.confirm(REPLACE_CONFIRM.replace('%n', n))) {
          refs.transcriptFile.value = '';
          focusUploadControl('transcript');
          return;
        }
      }
      uploadTranscript();
    });
    refs.transcriptFile.addEventListener('cancel', function () {
      clearUploadError('transcript');
      focusUploadControl('transcript');
    });
  }

  if (refs.transcriptPick) {
    refs.transcriptPick.addEventListener('click', function (event) {
      event.stopPropagation();
      clearUploadError('transcript');
      refs.transcriptFile.click();
    });
  }

  if (refs.transcriptReplace) {
    refs.transcriptReplace.addEventListener('click', function () {
      clearUploadError('transcript');
      refs.transcriptFile.click();
    });
  }

  if (refs.transcriptDrop) {
    refs.transcriptDrop.addEventListener('click', function (event) {
      if (event.target === refs.transcriptFile || refs.transcriptPick.disabled) return;
      clearUploadError('transcript');
      refs.transcriptFile.click();
    });
    ['dragenter', 'dragover'].forEach(function (name) {
      refs.transcriptDrop.addEventListener(name, function (event) {
        event.preventDefault();
        refs.transcriptDrop.classList.add('over');
      });
    });
    ['dragleave', 'drop'].forEach(function (name) {
      refs.transcriptDrop.addEventListener(name, function (event) {
        event.preventDefault();
        refs.transcriptDrop.classList.remove('over');
      });
    });
    refs.transcriptDrop.addEventListener('drop', function (event) {
      var file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
      if (!file) return;
      clearUploadError('transcript');
      if (transcriptExists()) {
        var n = state.report.transcript_length;
        if (!window.confirm(REPLACE_CONFIRM.replace('%n', n))) {
          focusUploadControl('transcript');
          return;
        }
      }
      uploadTranscript(file);
    });
  }

  if (refs.otherFile) {
    refs.otherFile.addEventListener('change', function () {
      clearUploadError('other');
      var file = refs.otherFile.files && refs.otherFile.files[0];
      uploadOther(file);
    });
    refs.otherFile.addEventListener('cancel', function () {
      clearUploadError('other');
      focusUploadControl('other');
    });
  }
  if (refs.otherPick) {
    refs.otherPick.addEventListener('click', function (event) {
      event.stopPropagation();
      clearUploadError('other');
      refs.otherFile.click();
    });
  }
  if (refs.otherDrop) {
    refs.otherDrop.addEventListener('click', function (event) {
      if (event.target === refs.otherFile || refs.otherPick.disabled) return;
      clearUploadError('other');
      refs.otherFile.click();
    });
    ['dragenter', 'dragover'].forEach(function (name) {
      refs.otherDrop.addEventListener(name, function (event) {
        event.preventDefault();
        refs.otherDrop.classList.add('over');
      });
    });
    ['dragleave', 'drop'].forEach(function (name) {
      refs.otherDrop.addEventListener(name, function (event) {
        event.preventDefault();
        refs.otherDrop.classList.remove('over');
      });
    });
    refs.otherDrop.addEventListener('drop', function (event) {
      clearUploadError('other');
      var file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
      uploadOther(file);
    });
  }

  refs.transcriptText.addEventListener('input', function () {
    saves.setDirty(refs.transcriptText, !!refs.transcriptText.value.trim());
    clearTimeout(transcriptTimer);
    transcriptTimer = setTimeout(saveTranscript, 1500);
  });
  refs.transcriptText.addEventListener('blur', function () {
    clearTimeout(transcriptTimer);
    saveTranscript();
  });

  var stepNav = document.getElementById('r4StepNav');
  if (stepNav) {
    stepNav.addEventListener('click', function (event) {
      var link = event.target && event.target.closest ? event.target.closest('a[data-step]') : null;
      if (!link) return;
      event.preventDefault();
      if (link.getAttribute('aria-disabled') === 'true') return;
      showStep(link.getAttribute('data-step'));
    });
  }

  if (refs.genOpen) {
    refs.genOpen.addEventListener('click', function (event) {
      event.preventDefault();
      showStep('review');
    });
  }

  var spkSave = document.getElementById('r4SpkSave');
  if (spkSave) spkSave.addEventListener('click', function () {
    if (!saveSpeakers()) toast('没有修改');
  });
  document.getElementById('r4Speakers').addEventListener('change', function () {
    saves.setDirty(saveSpeakers, speakerChanges().controls.length > 0);
  });

  window.M1ReportWorkspace = {
    attach: function (source, data, editor) {
      var path = new URL(refs.print.dataset.exportUrl, location.origin).pathname;
      if (source !== refs.frame.contentWindow || source.location.origin !== location.origin
          || source.location.pathname !== path || data.api !== docUrl('')) return null;
      var pin = saves.snapshot().pin;
      if (!pin) return null;
      frameEditor = editor;
      if (pin.expected_rev !== data.rev || pin.version_id !== data.version_id) saves.conflict();
      return {
        saves: saves,
        exportReport: function () { runReviewAction('print'); },
        refresh: function () { loadPreview(true); }
      };
    }
  };

  window.addEventListener('hashchange', function () {
    var match = /step=(\w+)/.exec(window.location.hash || '');
    if (!match) return;
    var step = match[1] === 'export' ? 'review' : match[1];
    if (STEPS.indexOf(step) < 0) return;
    if (step === 'review' && !state.doc) return;
    if (state.step === step) return;
    showStep(step);
  });
  var regen = document.getElementById('r4Regenerate');
  if (regen) regen.addEventListener('click', function () { generate(false); });

  load();
})();
