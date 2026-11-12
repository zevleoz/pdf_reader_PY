/* M1 工作台：① 资料 ② 审阅定稿。 */
(function () {
  'use strict';

  var root = document.getElementById('m1Workspace');
  if (!root) return;

  var CTX = window.M1_CTX || {};
  var prepId = CTX.prepId;

  var state = {
    prepId: prepId,
    status: CTX.status || 'draft',
    rev: CTX.rev || 1,
    prep: CTX.prep || {},
    role: CTX.role || '',
    m1Admin: !!CTX.m1Admin,
    detail: null,
    doc: null,
    kb: null,
    fixed: {},
    y4Items: [],
    version: null,
    auto: null,
    uploads: [],
    step: 'sources',
    saveTimer: null,
    conflict: false,
    jobId: null,
    pollTimer: null,
    sync: null
  };

  var CATEGORY_LABELS = {
    parent: '家长初始反馈',
    case_review: 'Case Review',
    other: '其他资料',
    first_touch_extra: 'First Touch 补充'
  };

  var docEl = document.getElementById('m1doc');

  function el(tag, cls, value) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (value !== undefined && value !== null) node.textContent = value;
    return node;
  }

  function toast(message, type) {
    if (window.v2Toast) window.v2Toast(message, type);
  }

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

  function jsonBody(payload) {
    return {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    };
  }

  function fmtDT(value) {
    if (window.y4FmtDT) return window.y4FmtDT(value);
    if (!value) return '';
    var d = new Date(value);
    if (isNaN(d.getTime())) return String(value).slice(0, 16).replace('T', ' ');
    function p(n) { return (n < 10 ? '0' : '') + n; }
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
      ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  }

  function nowHM() {
    var d = new Date();
    function p2(n) { return (n < 10 ? '0' : '') + n; }
    return p2(d.getHours()) + ':' + p2(d.getMinutes());
  }

  function abilityInfo(code) {
    return window.M1Doc && window.M1Doc.abilityOf(state.kb, code);
  }

  /* ------------------------------------------------------------------ */
  /* 步骤条                                                              */
  /* ------------------------------------------------------------------ */
  function setStep(step) {
    var wantsGen = step === 'gen';
    if (wantsGen) step = 'sources';
    state.step = step;
    document.getElementById('stepSources').hidden = step !== 'sources';
    document.getElementById('stepReview').hidden = step !== 'review';

    var hasDoc = !!state.doc;
    document.querySelectorAll('#stepper a').forEach(function (link) {
      var key = link.getAttribute('data-step');
      link.classList.remove('d', 'n', 'x');
      link.removeAttribute('aria-disabled');
      link.removeAttribute('aria-current');
      if (key === 'sources') {
        link.classList.add(hasDoc && step !== 'sources' ? 'd' : 'n');
      } else if (!hasDoc) {
        link.classList.add('x');
        link.setAttribute('aria-disabled', 'true');
      } else if (step === 'review') {
        link.classList.add('n');
      }
      if (key === step) link.setAttribute('aria-current', 'step');
    });

    var tag = document.getElementById('wsTag');
    tag.textContent = state.status === 'generating' ? '生成中'
      : step === 'sources' ? '资料'
      : state.status === 'final' ? '已定稿'
      : hasDoc ? 'AI 初稿' : '资料';

    var go = document.getElementById('genGo');
    var box = document.getElementById('genBox');
    var busy = wantsGen || (state.status === 'generating' && !!state.jobId);
    go.hidden = busy;
    box.hidden = !busy;

    renderStepNote();
  }

  function renderStepNote() {
    var hasDoc = !!state.doc;
    var note = document.getElementById('stepSrcNote');
    var when = hasDoc ? fmtDT((state.version || {}).ai_generated_at) : '';
    note.textContent = hasDoc
      ? '已生成' + (when && when !== '—' ? ' · ' + when.slice(5) : '')
      : '确认后生成 AI 初稿';
    document.getElementById('toConfirm').textContent = hasDoc ? '重新生成 AI 初稿' : '生成 AI 初稿';
  }

  /* ------------------------------------------------------------------ */
  /* 会议信息                                                            */
  /* ------------------------------------------------------------------ */
  function renderInfo() {
    var prep = state.prep;
    document.getElementById('mdate').value = prep.meeting_date || '';
    document.getElementById('mentorBox').textContent = prep.mentor_name || '未指定';
    document.querySelectorAll('#durationSeg button').forEach(function (btn) {
      var on = parseInt(btn.getAttribute('data-dur'), 10) === prep.duration;
      btn.setAttribute('aria-pressed', String(on));
      btn.classList.toggle('on', on);
    });
    document.getElementById('durHint').textContent = prep.duration === 60
      ? '标准版：探索 1–2 个事件' : '延长版：探索 2–3 个事件';
    renderPeople();
    if (state.role === 'admin' || state.m1Admin) loadMentorOptions();
  }

  function renderPeople() {
    var box = document.getElementById('peopleBox');
    Array.prototype.slice.call(box.querySelectorAll('.chip:not(.add)')).forEach(function (n) { n.remove(); });
    var addBtn = document.getElementById('addPerson');
    (state.prep.attendees || []).forEach(function (person, index) {
      var tag = el('span', 'chip', person);
      var remove = el('button', '', '×');
      remove.setAttribute('type', 'button');
      remove.setAttribute('aria-label', '移除 ' + person);
      remove.addEventListener('click', function () {
        var next = (state.prep.attendees || []).slice();
        next.splice(index, 1);
        patchPrep({ attendees: next });
      });
      tag.appendChild(remove);
      box.insertBefore(tag, addBtn);
    });
  }

  function patchPrep(fields, quiet) {
    return api('/api/m1/preps/' + state.prepId, jsonBody(fields)).then(function (body) {
      state.prep = body.prep;
      if (state.detail) state.detail.prep = body.prep;
      renderInfo();
      if (!quiet) toast('会议信息已更新', 'success');
    }).catch(function (error) {
      toast(error.message, 'error');
    });
  }

  function loadMentorOptions() {
    api('/api/m1/mentors').then(function (body) {
      var users = body.mentors || [];
      if (!users.length) return;
      var box = document.getElementById('mentorBox');
      var select = el('select', 'inp');
      select.id = 'mentorSelect';
      var empty = el('option', '', '未指定');
      empty.value = '';
      select.appendChild(empty);
      users.forEach(function (user) {
        var option = el('option', '',
          user.display_name || user.username || ('用户 ' + user.id));
        option.value = user.id;
        if (String(user.id) === String(state.prep.mentor_user_id)) option.selected = true;
        select.appendChild(option);
      });
      select.addEventListener('change', function () {
        patchPrep({ mentor_user_id: select.value ? parseInt(select.value, 10) : null }, true);
      });
      box.textContent = '';
      box.appendChild(select);
    }).catch(function () { /* advisor 无用户列表权限时保持只读 */ });
  }

  /* ------------------------------------------------------------------ */
  /* 资料来源                                                            */
  /* ------------------------------------------------------------------ */
  function renderSources() {
    var auto = state.auto || {};
    var y4 = auto.y4 || { items: [] };
    var ft = auto.first_touch || {};
    var questionnaires = auto.questionnaires || [];
    var uploads = state.uploads || [];
    var parentUploads = uploads.filter(function (u) { return u.category === 'parent'; });
    var caseUploads = uploads.filter(function (u) { return u.category === 'case_review'; });
    var otherUploads = uploads.filter(function (u) { return u.category === 'other'; });
    var ftUploads = uploads.filter(function (u) { return u.category === 'first_touch_extra'; });

    /* Y4 */
    var y4Pill = document.getElementById('y4Pill');
    y4Pill.className = 'st ' + (y4.complete ? 's0' : 's1');
    y4Pill.textContent = y4.complete ? '已获取' : '未取得';
    var y4Body = document.getElementById('y4Body');
    y4Body.textContent = '';
    var y4Facts = el('ul', 'facts');
    if (y4.complete) {
      y4Facts.appendChild(el('li', '', '测评日期 ' + (y4.date || '—') + ' · 四份报告齐全（A2 / B3 / B4 / B6）'));
      y4Facts.appendChild(el('li', '', '按已确认的有效评价规则得出档位；报告中只显示档位，不显示原始分'));
      y4Facts.appendChild(el('li', '', '与 R4 相关的 ' + (y4.items || []).length + ' 项指标已对应到 18 项能力'));
    } else {
      y4Facts.appendChild(el('li', '', '尚未取得完整的 Y4 测评报告'));
    }
    y4Body.appendChild(y4Facts);
    var sixAm = y4.six_am || {};
    y4Body.appendChild(el('div', 'derived',
      sixAm.version || sixAm.date
        ? '6 A.M. 档案' + (sixAm.version ? ' v' + sixAm.version : '') +
          (sixAm.date ? '（' + sixAm.date + '）' : '') +
          ' · 由 Y4 衍生，只随 Y4 一起参考，不单独计为证据'
        : '6 A.M. 档案尚未生成 · 由 Y4 衍生，只随 Y4 一起参考，不单独计为证据'));

    /* First Touch */
    var ftPill = document.getElementById('ftPill');
    ftPill.className = 'st ' + (ft.present ? 's0' : 's1');
    ftPill.textContent = ft.present ? '已获取' : '未取得';
    var ftBody = document.getElementById('ftBody');
    ftBody.textContent = '';
    var ftFacts = el('ul', 'facts');
    if (ft.present) {
      ftFacts.appendChild(el('li', '', (ft.date || '—') + ' 会谈记录（会前 / 会谈中 / 会后）'));
      var summary = String(ft.text || '').split('\n').filter(Boolean)[0] || '';
      if (summary) ftFacts.appendChild(el('li', '', summary.length > 90 ? summary.slice(0, 90) + '…' : summary));
    } else {
      ftFacts.appendChild(el('li', '', '尚未取得 First Touch 会谈记录'));
    }
    ftBody.appendChild(ftFacts);
    var ftBtn = el('button', 'btn s', '补充其他会谈资料');
    ftBtn.setAttribute('type', 'button');
    ftBtn.style.justifySelf = 'start';
    ftBtn.addEventListener('click', function () { pickFile('first_touch_extra'); });
    ftBody.appendChild(ftBtn);
    if (ftUploads.length) ftBody.appendChild(renderFileList(ftUploads));

    /* 家长反馈 */
    var parentText = uploads.filter(function (u) {
      return u.category === 'parent' && !u.filename && u.text;
    }).map(function (u) { return u.text; }).join('\n\n');
    var textarea = document.getElementById('parentText');
    if (!textarea.value) textarea.value = parentText;
    var parentPill = document.getElementById('parentPill');
    var hasParent = parentUploads.length > 0 || textarea.value.trim().length > 0;
    parentPill.className = 'st ' + (hasParent ? 's0' : 'sn');
    parentPill.textContent = hasParent ? '已提供' : '未提供';
    var parentFiles = document.getElementById('parentFiles');
    parentFiles.textContent = '';
    var saveText = el('button', 'btn s', '保存这段文字');
    saveText.setAttribute('type', 'button');
    saveText.style.justifySelf = 'start';
    saveText.addEventListener('click', function () {
      var value = textarea.value.trim();
      if (!value) { textarea.focus(); toast('先粘贴家长反馈内容', 'error'); return; }
      addSource({ text: value, category: 'parent' });
    });
    if (!parentFiles.dataset.ready) {
      parentFiles.dataset.ready = '1';
      textarea.parentNode.insertBefore(saveText, textarea.nextSibling);
    }
    if (parentUploads.length) parentFiles.appendChild(renderFileList(parentUploads));

    /* 补充问卷 */
    var qPill = document.getElementById('qPill');
    var completed = questionnaires.filter(function (q) { return q.status === '已完成'; }).length;
    var missing = questionnaires.filter(function (q) { return q.status === '未取得'; }).length;
    qPill.className = 'st ' + (missing ? 's1' : completed ? 's0' : 'sn');
    qPill.textContent = missing ? '部分信息' : completed ? '已获取' : '未触发';
    var qList = document.getElementById('qList');
    qList.textContent = '';
    if (!questionnaires.length) {
      qList.appendChild(el('span', 'hint', '平台内没有已触发的补充问卷。'));
    } else {
      questionnaires.forEach(function (q) {
        var qrow = el('div', 'qrow');
        var label = el('span', '', q.title || q.code || '');
        label.appendChild(el('span', 'mu', q.date ? ' · ' + q.date : ''));
        qrow.appendChild(label);
        var cls = q.status === '已完成' ? 's0' : q.status === '未取得' ? 's1' : 'sn';
        qrow.appendChild(el('span', 'st ' + cls, q.status_text || q.status));
        qList.appendChild(qrow);
      });
      qList.appendChild(el('span', 'hint',
        '“未触发”表示 Y4 结果没有触发这份问卷，不等于正常；报告里会照实写明。'));
    }

    /* Case Review / 其他 */
    var casePill = document.getElementById('casePill');
    casePill.className = 'st ' + (caseUploads.length ? 's0' : 'sn');
    casePill.textContent = caseUploads.length ? '已提供 ' + caseUploads.length + ' 份' : '未提供';
    var caseFiles = document.getElementById('caseFiles');
    caseFiles.textContent = '';
    if (caseUploads.length) caseFiles.appendChild(renderFileList(caseUploads));

    var otherPill = document.getElementById('otherPill');
    otherPill.className = 'st ' + (otherUploads.length ? 's0' : 'sn');
    otherPill.textContent = otherUploads.length ? '已提供 ' + otherUploads.length + ' 份' : '未提供';
    var otherFiles = document.getElementById('otherFiles');
    otherFiles.textContent = '';
    if (otherUploads.length) otherFiles.appendChild(renderFileList(otherUploads));

    renderSummary({ y4: y4, ft: ft, questionnaires: questionnaires,
      parent: hasParent, caseCount: caseUploads.length, otherCount: otherUploads.length });

    document.querySelectorAll('[data-upload]').forEach(function (btn) {
      btn.onclick = function () { pickFile(btn.getAttribute('data-upload')); };
    });
  }

  function renderFileList(rows) {
    var wrap = el('div');
    wrap.style.display = 'grid';
    wrap.style.gap = '8px';
    rows.forEach(function (source) {
      var box = el('div', 'file');
      box.appendChild(el('span', 'nm', source.filename || source.label || '粘贴文字'));
      box.appendChild(el('span', 'st s0', source.status === 'partial' ? '部分识别' : '已识别'));

      var meta = el('div', 'meta');
      var catLabel = el('label', '', '类别 ');
      var select = el('select');
      select.setAttribute('aria-label', '资料类别');
      Object.keys(CATEGORY_LABELS).forEach(function (key) {
        var option = el('option', '', CATEGORY_LABELS[key]);
        option.value = key;
        if (key === source.category) option.selected = true;
        select.appendChild(option);
      });
      select.addEventListener('change', function () {
        updateSource(source.id, { category: select.value });
      });
      catLabel.appendChild(select);
      meta.appendChild(catLabel);

      var dateLabel = el('label', '', '日期 ');
      var dateInput = el('input');
      dateInput.type = 'date';
      dateInput.setAttribute('aria-label', '资料日期');
      dateInput.value = source.detected_date || '';
      dateInput.addEventListener('change', function () {
        updateSource(source.id, { detected_date: dateInput.value });
      });
      dateLabel.appendChild(dateInput);
      meta.appendChild(dateLabel);

      meta.appendChild(el('span', 'sp'));
      var remove = el('button', 'btn s g', '移除');
      remove.setAttribute('type', 'button');
      remove.addEventListener('click', function () { deleteSource(source.id); });
      meta.appendChild(remove);
      box.appendChild(meta);

      if (source.text) {
        var text = source.text.replace(/\s+/g, ' ').trim();
        box.appendChild(el('div', 'sum', text.length > 160 ? text.slice(0, 160) + '…' : text));
      }
      wrap.appendChild(box);
    });
    return wrap;
  }

  function renderSummary(info) {
    var box = document.getElementById('srcSummary');
    var groups = [
      info.y4.complete,
      info.ft.present,
      info.questionnaires.filter(function (q) { return q.status === '已完成'; }).length > 0,
      info.parent,
      info.caseCount > 0,
      info.otherCount > 0
    ].filter(Boolean).length;
    box.textContent = '将使用 ' + groups + ' 项资料。只有 Y4 必需，缺的写“信息不足”。';
  }

  function pickFile(category) {
    var input = el('input');
    input.type = 'file';
    input.accept = '.pdf,.doc,.docx,.txt,.md,.csv';
    input.style.display = 'none';
    document.body.appendChild(input);
    input.addEventListener('change', function () {
      var file = input.files && input.files[0];
      input.remove();
      if (file) uploadFile(file, category);
    });
    input.click();
  }

  function uploadFile(file, category) {
    var form = new FormData();
    form.append('file', file);
    form.append('category', category);
    api('/api/m1/preps/' + state.prepId + '/sources', { method: 'POST', body: form })
      .then(function (body) {
        var source = body.source || {};
        if (source.suggested_meeting_date && !state.prep.meeting_date) {
          var hint = document.getElementById('mdateHint');
          if (hint) hint.hidden = false;
          document.getElementById('mdate').value = source.suggested_meeting_date;
        }
        return refresh();
      })
      .then(function () { toast('资料已上传', 'success'); })
      .catch(function (error) { toast(error.message, 'error'); });
  }

  function addSource(payload) {
    api('/api/m1/preps/' + state.prepId + '/sources', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(function () {
      document.getElementById('parentText').value = '';
      return refresh();
    }).then(function () {
      toast('已加入资料', 'success');
    }).catch(function (error) { toast(error.message, 'error'); });
  }

  function updateSource(sourceId, fields) {
    api('/api/m1/sources/' + sourceId, jsonBody(fields))
      .then(refresh)
      .catch(function (error) { toast(error.message, 'error'); });
  }

  function deleteSource(sourceId) {
    api('/api/m1/sources/' + sourceId, { method: 'DELETE' })
      .then(refresh)
      .catch(function (error) { toast(error.message, 'error'); });
  }

  /* ---------- 确认资料 ---------- */
  function openConfirm() {
    var host = document.getElementById('m1ModalHost');
    host.textContent = '';
    var auto = state.auto || {};
    var y4 = auto.y4 || { items: [] };
    var ft = auto.first_touch || {};
    var questionnaires = auto.questionnaires || [];
    var uploads = state.uploads || [];
    var rows = [];

    if (y4.complete) {
      rows.push(['Y4 测评报告（4 份）', 'Y4 Assessment', y4.date || '', (y4.items || []).length + ' 项 R4 相关指标的档位']);
    }
    if (y4.six_am) {
      rows.push(['6 A.M. 档案', '随 Y4（衍生）', y4.six_am.date || '', '不单独计为证据']);
    }
    if (ft.present) {
      rows.push(['First Touch 会谈记录', 'First Touch', ft.date || '', '会谈原文与提取要点']);
    }
    var parentText = (document.getElementById('parentText').value || '').trim();
    rows.push(['家长反馈（粘贴文字 / 上传）', '家长初始反馈',
      (uploads.filter(function (u) { return u.category === 'parent'; })[0] || {}).detected_date || '',
      parentText ? '已提供家长反馈原文' : '未提供']);
    questionnaires.filter(function (q) { return q.status === '已完成'; }).forEach(function (q) {
      rows.push([q.title || q.code, '补充问卷', q.date || '', '按维度整理的原始回答']);
    });
    uploads.forEach(function (source) {
      rows.push([source.filename || source.label || '粘贴文字',
        CATEGORY_LABELS[source.category] || source.category,
        source.detected_date || '', '已提取摘要']);
    });

    var scrim = el('div', 'm1-scrim');
    var modal = el('div', 'modal');
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-labelledby', 'cfH');
    var head = el('div', 'head');
    head.appendChild(el('h2', '', '确认资料')).id = 'cfH';
    head.appendChild(el('span', 'sub', 'AI 会只用下面这些资料。看一眼类别和日期是否正确。'));
    modal.appendChild(head);

    var scroll = el('div', 'scroll-x');
    var table = el('table', 'table');
    var thead = el('thead');
    var headRow = el('tr');
    ['资料', '类别', '日期', '识别结果'].forEach(function (label) {
      headRow.appendChild(el('th', '', label));
    });
    thead.appendChild(headRow);
    table.appendChild(thead);
    var tbody = el('tbody');
    rows.forEach(function (row) {
      var tr = el('tr');
      row.forEach(function (value) { tr.appendChild(el('td', '', value)); });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    scroll.appendChild(table);
    modal.appendChild(scroll);

    var body = el('div', 'body');
    var missing = questionnaires.filter(function (q) { return q.status === '未取得'; })
      .map(function (q) { return (q.title || q.code) + '（未取得）'; });
    if (!uploads.some(function (u) { return u.category === 'other'; })) {
      missing.push('其他资料（未提供）');
    }
    var missText = missing.length
      ? '将在报告中标注“信息不足”：' + missing.join('、') + '。'
      : '资料已齐。';
    body.appendChild(el('p', 'miss', missText + '“未触发”的问卷照实写明。'));
    modal.appendChild(body);

    var foot = el('div', 'foot');
    var back = el('button', 'btn', '返回修改');
    back.setAttribute('type', 'button');
    back.addEventListener('click', closeModal);
    var go = el('button', 'btn pri', '确认并生成');
    go.setAttribute('type', 'button');
    go.addEventListener('click', function () { closeModal(); generate(); });
    foot.appendChild(back);
    foot.appendChild(go);
    modal.appendChild(foot);

    scrim.appendChild(modal);
    host.appendChild(scrim);
    scrim.addEventListener('click', function (event) {
      if (event.target === scrim) closeModal();
    });
    document.addEventListener('keydown', onEsc);
    go.focus();
  }

  function onEsc(event) {
    if (event.key === 'Escape') closeModal();
  }

  function closeModal() {
    document.getElementById('m1ModalHost').textContent = '';
    document.removeEventListener('keydown', onEsc);
  }

  /* ------------------------------------------------------------------ */
  /* ① 生成                                                              */
  /* ------------------------------------------------------------------ */
  function generate() {
    state.status = 'generating';
    document.getElementById('genOpen').hidden = true;
    setStep('gen');
    api('/api/m1/preps/' + state.prepId + '/generate', { method: 'POST' })
      .then(function (body) {
        var job = body.job || {};
        state.jobId = body.job_id || body.jobId || job.id || job.job_id || null;
        if (!state.jobId) {
          toast('已开始生成，完成后回到列表刷新', 'success');
          return;
        }
        sessionStorage.setItem('m1_job_' + state.prepId, state.jobId);
        pollJob();
      })
      .catch(function (error) {
        toast(error.message, 'error');
        state.status = 'draft';
        setStep('sources');
      });
  }

  function pollJob() {
    clearTimeout(state.pollTimer);
    api('/api/m1/jobs/' + state.jobId).then(function (body) {
      var job = body.job || body;
      var steps = job.steps || body.steps || [];
      var rows = Array.prototype.slice.call(document.querySelectorAll('#genList [data-i]'));
      if (Array.isArray(steps) && steps.length) {
        rows.forEach(function (row, index) {
          var step = steps[index] || {};
          var done = step.status === 'done' || step.status === 'ok' ||
            step.state === 'done';
          var running = step.status === 'running' || step.state === 'running';
          row.className = done ? 'ok' : running ? 'on' : '';
          var t = row.querySelector('[data-t]');
          if (t && step.seconds !== undefined) t.textContent = step.seconds + ' 秒';
        });
      } else if (typeof job.step === 'number') {
        rows.forEach(function (row, index) {
          row.className = index < job.step ? 'ok' : index === job.step ? 'on' : '';
        });
      }
      var progress = job.progress !== undefined ? job.progress
        : (Array.isArray(steps) && steps.length
          ? Math.round(steps.filter(function (s) {
            return s.status === 'done' || s.status === 'ok' || s.state === 'done';
          }).length / steps.length * 100)
          : (typeof job.step === 'number' ? Math.round(job.step / 7 * 100) : 0));
      var meter = document.getElementById('genMeter');
      if (meter) meter.style.width = Math.max(4, progress) + '%';

      var status = String(job.status || body.status || '').toLowerCase();
      if (['done', 'completed', 'succeeded', 'success', 'finished'].indexOf(status) !== -1) {
        finishGenerate();
        return;
      }
      if (['failed', 'error'].indexOf(status) !== -1) {
        toast(job.error || '生成失败，请重试', 'error');
        state.status = 'draft';
        setStep('sources');
        return;
      }
      state.pollTimer = setTimeout(pollJob, 2000);
    }).catch(function (error) {
      toast(error.message, 'error');
    });
  }

  function finishGenerate() {
    clearTimeout(state.pollTimer);
    sessionStorage.removeItem('m1_job_' + state.prepId);
    refresh().then(function () {
      state.status = (state.detail && state.detail.status) || 'review';
      if (state.doc) {
        setStep('gen');
        document.getElementById('genOpen').hidden = false;
        toast('AI 初稿已生成', 'success');
      } else {
        toast('生成完成，但还没有草稿', 'error');
      }
    });
  }

  /* ------------------------------------------------------------------ */
  /* ② 审阅定稿                                                           */
  /* ------------------------------------------------------------------ */
  function renderReview() {
    var final = state.status === 'final';
    var toolbar = document.getElementById('savedBadge');
    toolbar.hidden = !state.doc;
    document.getElementById('finalizeCard').hidden = final || !state.doc;
    document.getElementById('myQCard').hidden = final || !state.doc;

    if (!state.doc) {
      docEl.textContent = '';
      document.getElementById('stamp').textContent = '还没有 AI 初稿。先确认资料并生成。';
      document.getElementById('priList').textContent = '';
      document.getElementById('warnList').textContent = '';
      document.getElementById('factList').textContent = '';
      document.getElementById('factCount').textContent = '0';
      document.getElementById('warnCount').textContent = '0';
      document.getElementById('warnFold').hidden = true;
      document.getElementById('okLine').hidden = true;
      document.getElementById('priCount').textContent = '0 项';
      return;
    }

    renderStamp();
    window.M1Doc.render(docEl, {
      doc: state.doc,
      kb: state.kb,
      fixed: state.fixed,
      y4_items: state.y4Items,
      version: state.version,
      prep: state.prep,
      status: state.status
    }, {
      mode: final ? 'read' : 'edit',
      onEdit: onBlockEdit
    });

    renderSafety();
    renderLock(final);
    renderPriority();
    renderWarnings();
    renderFactFlags();
    renderFinalizeState();
    renderSync();
  }

  function renderStamp() {
    var version = state.version || {};
    var stamp = 'AI 初稿 ' + (fmtDT(version.ai_generated_at) || '—') +
      ' · 导师最后审核 ' + (fmtDT(version.reviewed_at) || '—');
    document.getElementById('stamp').textContent = stamp;
  }

  /* 事实核对标记：和服务器同一规则——已核对，或那一段文字已被改动，就算处理过。 */
  function blockText(id) {
    var found = null;
    (function walk(value) {
      if (found !== null || !value) return;
      if (Array.isArray(value)) { value.forEach(walk); return; }
      if (typeof value !== 'object') return;
      if (value.id === id && typeof value.text === 'string') { found = value.text; return; }
      Object.keys(value).forEach(function (key) {
        if (key !== 'fact_flags') walk(value[key]);
      });
    })(state.doc);
    return found;
  }

  function openFactFlags() {
    return ((state.doc && state.doc.fact_flags) || []).filter(function (flag) {
      if (flag.acked) return false;
      if (flag.block_id && flag.block_text !== undefined && flag.block_text !== null) {
        var current = blockText(flag.block_id);
        if (current === null || current.trim() !== String(flag.block_text).trim()) return false;
      }
      return true;
    });
  }

  function renderFactFlags() {
    var list = document.getElementById('factList');
    if (!list) return;
    var flags = state.status === 'final' ? [] : openFactFlags();
    list.textContent = '';
    document.getElementById('factCount').textContent = String(flags.length);
    flags.forEach(function (flag, index) {
      var row = el('div', 'chk');
      if (flag.block_id) {
        row.setAttribute('role', 'button');
        row.setAttribute('tabindex', '0');
        row.addEventListener('click', function (event) {
          if (event.target.closest('button')) return;
          jumpToBlock(flag.block_id);
        });
        row.addEventListener('keydown', function (event) {
          if (event.key !== 'Enter' && event.key !== ' ') return;
          event.preventDefault();
          jumpToBlock(flag.block_id);
        });
      }
      row.appendChild(el('span', 'n', String(index + 1)));
      var body = el('span');
      body.appendChild(el('b', '', flag.sentence || ''));
      if (flag.problem && flag.problem !== flag.sentence) {
        body.appendChild(el('small', '', flag.problem));
      }
      row.appendChild(body);
      var ack = el('button', 'btn s g', '我已核对');
      ack.setAttribute('type', 'button');
      ack.addEventListener('click', function () { ackFactFlag(flag, ack); });
      row.appendChild(ack);
      list.appendChild(row);
    });
    var warnCount = Number(document.getElementById('warnCount').textContent) || 0;
    document.getElementById('okLine').hidden = flags.length > 0 || warnCount > 0;
  }

  function jumpToBlock(id) {
    var nodes = docEl.querySelectorAll('[data-bid]');
    for (var i = 0; i < nodes.length; i += 1) {
      if (nodes[i].getAttribute('data-bid') === id) {
        nodes[i].scrollIntoView({ block: 'center', behavior: 'smooth' });
        nodes[i].classList.remove('flash');
        void nodes[i].offsetWidth;
        nodes[i].classList.add('flash');
        nodes[i].focus();
        return;
      }
    }
  }

  function ackFactFlag(flag, button) {
    button.disabled = true;
    // 先把还没保存的修改存上，再核对，避免两边的版本号对不上
    var pending = state.saveTimer ? (clearTimeout(state.saveTimer), saveDoc()) : Promise.resolve();
    pending.then(function () {
      return api('/api/m1/preps/' + state.prepId + '/fact-flags/' +
        encodeURIComponent(flag.id) + '/ack', { method: 'POST' });
    }).then(function (body) {
      flag.acked = true;
      state.rev = body.rev !== undefined ? body.rev : state.rev;
      renderFactFlags();
      renderFinalizeState();
    }).catch(function (error) {
      button.disabled = false;
      if (error.status === 409 && error.body && error.body.rev !== undefined) {
        showConflict(error.body);
      } else {
        toast(error.message, 'error');
      }
    });
  }

  function renderFinalizeState() {
    var btn = document.getElementById('finalizeBtn');
    var hint = document.getElementById('finalizeHint');
    if (state.status === 'final') return;
    if (!state.doc || state.status === 'generating') {
      btn.disabled = true;
      return;
    }
    btn.disabled = false;
    hint.textContent = '点击文档里任何文字都可以直接修改。定稿后锁定这一版用于会议。';
  }

  function renderSafety() {
    var host = document.getElementById('safetyBanner');
    host.textContent = '';
    var safety = ((state.doc.flags || {}).safety) || [];
    if (!safety.length) return;
    var banner = el('div', 'safety');
    banner.setAttribute('role', 'alert');
    banner.appendChild(el('b', '', '安全提示'));
    var message = '家长反馈中提到“' + safety.map(function (item) {
      return item.text || '';
    }).join('”；“') + '”。请先按安全流程人工核实，必要时转介。心有灵析报告不会对此做任何判断。';
    banner.appendChild(el('span', '', message));
    banner.appendChild(el('span', 'sp'));
    if (state.prep.safety_ack_at) {
      banner.appendChild(el('span', 'st s0', '已确认：已转交人工处理'));
    } else {
      var ack = el('button', 'btn s', '我已知晓，已按流程处理');
      ack.setAttribute('type', 'button');
      ack.addEventListener('click', function () {
        api('/api/m1/preps/' + state.prepId + '/safety-ack', { method: 'POST' })
          .then(function (body) {
            state.prep = body.prep || state.prep;
            if (state.detail) state.detail.prep = state.prep;
            renderSafety();
            renderFinalizeState();
            toast('已记录安全提示确认', 'success');
          })
          .catch(function (error) { toast(error.message, 'error'); });
      });
      banner.appendChild(ack);
    }
    host.appendChild(banner);
  }

  function renderLock(final) {
    var host = document.getElementById('lockBar');
    host.textContent = '';
    if (!final) return;
    var version = state.version || {};
    var bar = el('div', 'lockbar');
    bar.appendChild(el('b', '', '已定稿 v' + (version.n || '')));
    bar.appendChild(el('span', '',
      '导师审核 ' + (fmtDT(version.reviewed_at) || '—') + ' · ' +
      (state.prep.mentor_name || '') +
      '。这个版本已锁定，用于会议。'));
    bar.appendChild(el('span', 'sp'));
    var reopen = el('button', 'btn s', '基于此版本再修改');
    reopen.setAttribute('type', 'button');
    reopen.addEventListener('click', function () {
      api('/api/m1/preps/' + state.prepId + '/reopen', { method: 'POST' })
        .then(function () { return refresh(); })
        .then(function () {
          state.status = 'review';
          renderReview();
          setStep('review');
          toast('已基于此版本新建草稿，原定稿仍保留在历史版本中', 'success');
        })
        .catch(function (error) { toast(error.message, 'error'); });
    });
    bar.appendChild(reopen);
    host.appendChild(bar);
  }

  function eventCodes() {
    var codes = {};
    (state.doc.events || []).forEach(function (event) {
      (event.abilities || []).forEach(function (code) { codes[code] = true; });
    });
    return Object.keys(codes);
  }

  function renderPriority() {
    var doc = state.doc;
    var list = document.getElementById('priList');
    list.textContent = '';
    var priority = doc.priority || [];
    var final = state.status === 'final';
    priority.forEach(function (item) {
      var code = item.code;
      var ability = abilityInfo(code);
      var chip = el('span', 'chip');
      chip.appendChild(el('code', '', code));
      chip.appendChild(document.createTextNode(' ' + (ability ? ability.name : '')));
      var remove = el('button', '', '×');
      remove.setAttribute('type', 'button');
      remove.setAttribute('aria-label', '移除 ' + code);
      if (final) remove.disabled = true;
      remove.addEventListener('click', function () {
        state.priorityPending = code;
        removePriority(code);
      });
      chip.appendChild(remove);
      list.appendChild(chip);
    });

    var count = document.getElementById('priCount');
    count.textContent = priority.length + ' 项';

    var hint = document.getElementById('priHint');
    hint.hidden = priority.length <= 5;

    var select = document.getElementById('addAb');
    var current = select.value;
    select.textContent = '';
    var placeholder = el('option', '', '＋ 从 18 项中添加…');
    placeholder.value = '';
    select.appendChild(placeholder);
    var chosen = priority.map(function (item) { return item.code; });
    ((state.kb || {}).abilities || []).forEach(function (ability) {
      if (chosen.indexOf(ability.code) !== -1) return;
      var option = el('option', '', ability.code + ' ' + ability.name);
      option.value = ability.code;
      select.appendChild(option);
    });
    select.value = current && select.querySelector('option[value="' + current + '"]') ? current : '';
    select.disabled = state.status === 'final';
    select.onchange = function () {
      if (!select.value) return;
      addPriority(select.value);
      select.value = '';
    };

    var myQ = document.getElementById('myQab');
    var keep = myQ.value;
    myQ.textContent = '';
    var none = el('option', '', '不关联具体能力');
    none.value = '';
    myQ.appendChild(none);
    ((state.kb || {}).abilities || []).forEach(function (ability) {
      var option = el('option', '', ability.code + ' ' + ability.name);
      option.value = ability.code;
      myQ.appendChild(option);
    });
    myQ.value = keep || '';
  }

  function removePriority(code) {
    var doc = state.doc;
    doc.priority = (doc.priority || []).filter(function (item) { return item.code !== code; });
    var inPart3 = eventCodes().indexOf(code) !== -1;
    state.sync = inPart3 ? { code: code } : null;
    renderReview();
    scheduleSave();
  }

  function addPriority(code) {
    var doc = state.doc;
    if ((doc.priority || []).some(function (item) { return item.code === code; })) return;
    var ability = abilityInfo(code) || {};
    var lines = (state.y4Items || []).filter(function (item) {
      return (item.abilities || []).indexOf(code) !== -1;
    }).map(function (item) { return item.text; });
    doc.priority = doc.priority || [];
    doc.priority.push({
      code: code,
      evidence: lines.length ? lines : ['尚无直接证据，待会议中核实'],
      hypothesis: {
        id: 'h-' + code, text: '待导师补充', origin: 'mentor', ai_text: ''
      },
      why: {
        id: 'w-' + code, text: '导师添加', origin: 'mentor', ai_text: ''
      }
    });
    var covered = eventCodes().indexOf(code) !== -1;
    var hasBackup = (doc.backups || []).some(function (item) { return item.code === code; });
    if (!covered && !hasBackup) {
      doc.backups = doc.backups || [];
      doc.backups.push({
        code: code,
        missing: {
          id: 'bk-g-' + code, text: '事件探索未覆盖：' + (ability.ask || ''),
          origin: 'ai', ai_text: '事件探索未覆盖：' + (ability.ask || '')
        },
        question: {
          id: 'bk-q-' + code, text: ability.ask || '', origin: 'ai',
          ai_text: ability.ask || ''
        },
        timing: '第 4 环节；如已回答则跳过'
      });
    }
    state.sync = null;
    renderReview();
    scheduleSave();
    toast('已添加 ' + code + '，3.3 已补上对应的备用问题', 'success');
  }

  function renderSync() {
    var host = document.getElementById('syncBox');
    host.textContent = '';
    if (!state.sync) return;
    var code = state.sync.code;
    var ability = abilityInfo(code) || {};
    var box = el('div', 'sync');
    box.setAttribute('role', 'status');
    box.appendChild(el('span', '',
      'Part 3 中仍有关于 ' + code + ' ' + (ability.name || '') + ' 的追问。要一并移除吗？'));
    var row = el('div', 'row');
    var yes = el('button', 'btn s', '一并移除');
    yes.setAttribute('type', 'button');
    yes.addEventListener('click', function () {
      (state.doc.events || []).forEach(function (event) {
        event.abilities = (event.abilities || []).filter(function (c) { return c !== code; });
      });
      state.sync = null;
      renderReview();
      scheduleSave();
      toast('已从 Part 3 移除相关追问', 'success');
    });
    var no = el('button', 'btn s g', '保留不动');
    no.setAttribute('type', 'button');
    no.addEventListener('click', function () {
      state.sync = null;
      renderSync();
    });
    row.appendChild(yes);
    row.appendChild(no);
    box.appendChild(row);
    host.appendChild(box);
  }

  function renderWarnings() {
    var doc = state.doc;
    var list = document.getElementById('warnList');
    list.textContent = '';
    var warnings = [];
    ((doc.flags || {}).insufficient || []).forEach(function (text) {
      warnings.push(['w', text + '，报告中写明']);
    });
    var priorityCodes = (doc.priority || []).map(function (item) { return item.code; });
    eventCodes().forEach(function (code) {
      if (priorityCodes.indexOf(code) === -1) {
        warnings.push(['d', 'Part 3 仍保留 ' + code + ' 的追问，但 2.2 已取消这项能力，前后不一致']);
      }
    });
    warnings.forEach(function (item) {
      var line = el('div', 'warnline ' + item[0]);
      line.appendChild(el('span', 'dot'));
      line.appendChild(el('span', '', item[1]));
      list.appendChild(line);
    });
    document.getElementById('warnCount').textContent = warnings.length;
    document.getElementById('warnFold').hidden = warnings.length === 0;
    var okLine = document.getElementById('okLine');
    var flags = state.status === 'final' ? 0 : openFactFlags().length;
    okLine.hidden = flags > 0 || warnings.length > 0;
  }

  function onBlockEdit() {
    var badge = document.getElementById('savedBadge');
    badge.textContent = '未保存 · ' + nowHM();
    badge.classList.add('unsaved');
    renderFactFlags();
    renderFinalizeState();
    scheduleSave();
  }

  function scheduleSave() {
    if (state.status === 'final') return;
    clearTimeout(state.saveTimer);
    state.saveTimer = setTimeout(saveDoc, 700);
  }

  function saveDoc() {
    if (!state.doc || state.status === 'final' || state.conflict) return Promise.resolve();
    return api('/api/m1/preps/' + state.prepId + '/doc', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rev: state.rev, doc: state.doc })
    }).then(function (body) {
      state.rev = body.rev;
      var badge = document.getElementById('savedBadge');
      badge.textContent = '已自动保存 · ' + nowHM();
      badge.classList.remove('unsaved');
    }).catch(function (error) {
      if (error.status === 409) showConflict(error.body || {});
      else toast(error.message, 'error');
    });
  }

  function showConflict(body) {
    state.conflict = true;
    state.rev = body.rev !== undefined ? body.rev : state.rev;
    var host = document.getElementById('conflictBanner');
    host.textContent = '';
    var box = el('div', 'conflict');
    box.appendChild(el('b', '', '内容已在别处更新'));
    box.appendChild(el('span', '',
      '这个页面上的修改还没保存。先把下面的文字复制出来，再载入最新版。'));
    var local = [];
    (function walk(value) {
      if (!value) return;
      if (Array.isArray(value)) { value.forEach(walk); return; }
      if (typeof value !== 'object') return;
      if (value.id && value.origin === 'mentor') local.push(value.id + '：' + value.text);
      Object.keys(value).forEach(function (key) { walk(value[key]); });
    })(state.doc);
    var area = el('textarea', 'inp');
    area.readOnly = true;
    area.value = local.join('\n\n');
    box.appendChild(area);
    var row = el('div');
    var reload = el('button', 'btn s', '载入最新版');
    reload.setAttribute('type', 'button');
    reload.addEventListener('click', function () {
      state.conflict = false;
      host.textContent = '';
      refresh().then(function () {
        state.status = (state.detail && state.detail.status) || state.status;
        renderReview();
        setStep('review');
      });
    });
    row.appendChild(reload);
    box.appendChild(row);
    host.appendChild(box);
  }

  /* ------------------------------------------------------------------ */
  /* 定稿 / 预览                                                          */
  /* ------------------------------------------------------------------ */
  function finalize() {
    api('/api/m1/preps/' + state.prepId + '/finalize', { method: 'POST' })
      .then(function () {
        return refresh();
      })
      .then(function () {
        state.status = (state.detail && state.detail.status) || 'final';
        renderReview();
        setStep('review');
        toast('已定稿，可以下载 PDF 用于会议', 'success');
      })
      .catch(function (error) { toast(error.message, 'error'); });
  }

  function openFinalizeConfirm() {
    var flags = openFactFlags().length;
    var safety = (((state.doc || {}).flags || {}).safety) || [];
    var unacked = safety.length && !state.prep.safety_ack_at;
    var lead = unacked ? '有 ' + safety.length + ' 条安全提示还没确认。' : '';
    document.getElementById('finText').textContent = lead + (flags
      ? '还有 ' + flags + ' 处需要核对，可以先定稿。定稿后锁定这一版用于会议，PDF 不再带“草稿”水印；需要改的话可以重新打开。'
      : '定稿后锁定这一版用于会议，PDF 不再带“草稿”水印；需要改的话可以重新打开。');
    var dialog = document.getElementById('finConfirm');
    dialog.hidden = false;
    document.getElementById('finOk').focus();
  }

  function closeFinalizeConfirm() {
    document.getElementById('finConfirm').hidden = true;
  }

  function openPreview() {
    // 先同步开标签页，避免 await 之后被浏览器当作弹窗拦截。
    var tab = window.open('', '_blank');
    api('/api/m1/preps/' + state.prepId + '/export', { method: 'POST' })
      .then(function () {
        var url = '/m1/preps/' + state.prepId + '/print';
        if (tab) tab.location.href = url;
        else window.open(url, '_blank', 'noopener');
      })
      .catch(function (error) {
        if (tab) tab.close();
        toast(error.message, 'error');
      });
  }

  /* ------------------------------------------------------------------ */
  /* 数据加载                                                            */
  /* ------------------------------------------------------------------ */
  function applyDetail(body) {
    state.detail = body;
    state.status = body.status || state.status;
    state.rev = body.rev || state.rev;
    state.prep = body.prep || state.prep;
    state.doc = body.doc || null;
    state.kb = body.kb || state.kb;
    state.fixed = body.fixed || {};
    state.y4Items = body.y4_items || [];
    state.version = body.version || null;
    state.auto = body.auto || {};
    state.uploads = body.sources || [];
  }

  function refresh() {
    return api('/api/m1/preps/' + state.prepId).then(function (body) {
      applyDetail(body);
      renderInfo();
      renderSources();
      renderStepNote();
      if (state.step === 'review') renderReview();
      return body;
    });
  }

  function init() {
    api('/api/m1/preps/' + state.prepId).then(function (body) {
      applyDetail(body);
      renderInfo();
      renderSources();
      var step = state.status === 'generating' ? 'gen'
        : state.doc ? 'review' : 'sources';
      if (state.status === 'generating' && !state.doc) {
        var saved = sessionStorage.getItem('m1_job_' + state.prepId);
        if (saved) { state.jobId = saved; pollJob(); }
      }
      setStep(step);
      if (step === 'review') renderReview();
    }).catch(function (error) {
      toast(error.message, 'error');
    });
  }

  /* ---------- 事件绑定 ---------- */
  document.querySelectorAll('#stepper a').forEach(function (link) {
    link.addEventListener('click', function (event) {
      event.preventDefault();
      if (link.getAttribute('aria-disabled') === 'true') return;
      var step = link.getAttribute('data-step');
      setStep(step);
      if (step === 'review') renderReview();
      history.replaceState(null, '', '#step=' + step);
    });
  });

  document.getElementById('genOpen').addEventListener('click', function (event) {
    event.preventDefault();
    setStep('review');
    renderReview();
    history.replaceState(null, '', '#step=review');
  });

  window.addEventListener('hashchange', function () {
    var match = /step=(\w+)/.exec(window.location.hash || '');
    if (!match) return;
    var step = match[1] === 'export' ? 'review' : match[1];
    if (step !== 'sources' && step !== 'review') return;
    if (step === 'review' && !state.doc) return;
    if (state.step === step) return;
    setStep(step);
    if (step === 'review') renderReview();
  });

  document.getElementById('mdate').addEventListener('change', function (event) {
    patchPrep({ meeting_date: event.target.value }, true);
  });

  document.querySelectorAll('#durationSeg button').forEach(function (btn) {
    btn.addEventListener('click', function () {
      patchPrep({ duration: parseInt(btn.getAttribute('data-dur'), 10) }, true);
    });
  });

  document.getElementById('addPerson').addEventListener('click', function () {
    var input = document.getElementById('personInput');
    input.hidden = false;
    input.focus();
  });

  document.getElementById('personInput').addEventListener('keydown', function (event) {
    if (event.key !== 'Enter') return;
    var value = event.target.value.trim();
    if (!value) return;
    var next = (state.prep.attendees || []).concat([value]);
    event.target.value = '';
    event.target.hidden = true;
    patchPrep({ attendees: next }, true);
  });

  document.getElementById('toConfirm').addEventListener('click', openConfirm);
  document.getElementById('finalizeBtn').addEventListener('click', openFinalizeConfirm);
  document.getElementById('previewBtn').addEventListener('click', openPreview);

  var finConfirm = document.getElementById('finConfirm');
  finConfirm.addEventListener('click', function (event) {
    if (event.target === finConfirm || event.target.closest('[data-close]')) {
      closeFinalizeConfirm();
    }
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && !finConfirm.hidden) closeFinalizeConfirm();
  });
  document.getElementById('finOk').addEventListener('click', function () {
    closeFinalizeConfirm();
    finalize();
  });

  document.getElementById('addQ').addEventListener('click', function () {
    var textarea = document.getElementById('myQ');
    var value = textarea.value.trim();
    if (!value) { textarea.focus(); toast('先写下想问的问题', 'error'); return; }
    var code = document.getElementById('myQab').value || null;
    state.doc.backups = state.doc.backups || [];
    state.doc.backups.push({
      code: code,
      missing: {
        id: 'me-g-' + Date.now(), text: '导师补充', origin: 'mentor', ai_text: ''
      },
      question: {
        id: 'me-q-' + Date.now(), text: value, origin: 'mentor', ai_text: ''
      },
      timing: '第 4 环节'
    });
    textarea.value = '';
    renderReview();
    scheduleSave();
    toast('已加入 3.3 备用提问', 'success');
  });

  init();
})();
