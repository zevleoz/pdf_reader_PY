/*
 * Direct-plan input module (DP12 Task 2).
 *
 * Mount contract for Task 4:
 *   {% include "m1/_direct_inputs.html" %}
 * The partial loads this script and stylesheet once. Auto-initialisation uses
 * #m1DirectInputs[data-plan-id]. If the host page also owns the plan revision:
 *
 *   var di = window.M1DirectInputs.init(document.getElementById('m1DirectInputs'), {
 *     onRev: function (rev) { planState.rev = rev; }
 *   });
 *   di.setRev(planState.rev);   // after goal / duration edits that bump rev
 *   di.flush();                 // before calling any generate endpoint
 *
 * The module never confirms the brief by itself and never auto-applies an
 * extraction result over edits typed while the job was running.
 */
(function () {
  'use strict';

  var GROUPS = [
    { key: 'student', label: '学生本人', note: '学生自己的表达，和家长诉求分开记录。' },
    { key: 'parent', label: '家长诉求', note: '家长明确提出的优先项；不会因为标记可进入家长版就自动发布。' },
    { key: 'teaching', label: '内部教学判断', note: '导师判断。至少三项都填写并勾选「用于教学」，才能生成内部版。' },
    { key: 'context', label: '其他背景', note: '可选背景；没有来源时保持未注明。' }
  ];

  var BRIEF_FIELDS = [
    { key: 'student_wish', label: '学生意愿', group: 'student',
      help: '学生自己说想改善什么，不是家长目标。' },
    { key: 'student_willingness', label: '学生意愿程度', group: 'student',
      help: '学生愿意投入的程度或条件。' },
    { key: 'topics_to_avoid', label: '需要避开的话题', group: 'student',
      help: '学生明确不想谈、或目前不宜触碰的内容。' },
    { key: 'parent_priority', label: '家长优先关注', group: 'parent',
      help: '家长希望优先解决什么；与学生意愿分开。' },
    { key: 'learning_need', label: '学习需求', group: 'teaching', required: true,
      help: '这一阶段要解决的核心学习或情绪需求。' },
    { key: 'current_situation', label: '当前情境', group: 'teaching', required: true,
      help: '现在实际发生了什么。' },
    { key: 'current_response', label: '当前反应', group: 'teaching', required: true,
      help: '学生目前如何反应或应对。' },
    { key: 'strengths', label: '优势', group: 'context',
      help: '已经表现出来、可以借力的优势。' },
    { key: 'interests', label: '兴趣', group: 'context',
      help: '可用来建立连接的兴趣。' },
    { key: 'preferences', label: '偏好', group: 'context',
      help: '学习方式、节奏或沟通偏好。' },
    { key: 'constraints', label: '限制条件', group: 'context',
      help: '时间、环境、家庭或其他现实限制。' },
    { key: 'teaching_implications', label: '教学启示', group: 'context',
      help: '这些信息对教学设计意味着什么。' }
  ];

  var PROVENANCE = [
    { value: 'mentor', label: '导师' },
    { value: 'student', label: '学生' },
    { value: 'parent', label: '家长' },
    { value: 'file', label: '上传资料' },
    { value: 'report', label: '会后报告' },
    { value: 'unknown', label: '未注明' }
  ];

  var DISCLOSURE = [
    { value: 'internal_only', label: '仅内部使用' },
    { value: 'parent_safe', label: '可进入家长版' }
  ];

  var PROFILE_FIELDS = [
    { key: 'strengths', label: '优势', help: '学生已经表现出来的优势。' },
    { key: 'needs', label: '需求', help: '你判断的核心需求。' },
    { key: 'context', label: '情境', help: '家庭、学校或最近发生的事。' },
    { key: 'interests', label: '兴趣', help: '可以用来建立连接的线索。' }
  ];

  // ---- pure helpers (exported for focused tests) -------------------------
  function emptyEntry() {
    return { text: '', provenance: 'unknown', source_ref: '', use_for_teaching: false,
      disclosure: 'internal_only' };
  }

  function normalizeEntry(value) {
    var entry = emptyEntry();
    if (value && typeof value === 'object') {
      entry.text = value.text == null ? '' : String(value.text);
      entry.provenance = value.provenance || 'unknown';
      entry.source_ref = value.source_ref == null ? '' : String(value.source_ref);
      entry.use_for_teaching = !!value.use_for_teaching;
      entry.disclosure = value.disclosure === 'parent_safe' ? 'parent_safe' : 'internal_only';
    }
    return entry;
  }

  function briefFromPlan(plan) {
    var out = {};
    BRIEF_FIELDS.forEach(function (field) { out[field.key] = emptyEntry(); });
    var list = plan && (plan.teaching_brief || plan.brief);
    if (Array.isArray(list)) {
      list.forEach(function (item) {
        if (item && out[item.key]) out[item.key] = normalizeEntry(item);
      });
    } else if (list && typeof list === 'object') {
      Object.keys(list).forEach(function (key) {
        if (out[key]) out[key] = normalizeEntry(list[key]);
      });
    }
    return out;
  }

  function briefPayload(brief) {
    var out = {};
    BRIEF_FIELDS.forEach(function (field) {
      var entry = normalizeEntry(brief && brief[field.key]);
      out[field.key] = { text: entry.text, provenance: entry.provenance,
        source_ref: entry.source_ref, use_for_teaching: entry.use_for_teaching,
        disclosure: entry.disclosure };
    });
    return out;
  }

  function briefSignature(brief) {
    return BRIEF_FIELDS.map(function (field) {
      var entry = normalizeEntry(brief && brief[field.key]);
      return [field.key, entry.text, entry.provenance, entry.source_ref,
        entry.use_for_teaching ? '1' : '0', entry.disclosure].join('\u0001');
    }).join('\u0002');
  }

  function missingTeaching(brief) {
    return BRIEF_FIELDS.filter(function (field) { return field.required; })
      .filter(function (field) {
        var entry = normalizeEntry(brief && brief[field.key]);
        return !entry.text.trim() || !entry.use_for_teaching;
      }).map(function (field) { return field; });
  }

  function profileFromPlan(plan) {
    var inputs = (plan && plan.inputs) || {};
    var out = {};
    PROFILE_FIELDS.forEach(function (field) {
      var value = inputs[field.key] || {};
      out[field.key] = {
        text: value.text == null ? '' : String(value.text),
        src: value.src || 'mentor'
      };
    });
    return out;
  }

  function profilePayload(profile) {
    var out = {};
    PROFILE_FIELDS.forEach(function (field) {
      var value = (profile && profile[field.key]) || {};
      out[field.key] = { text: value.text == null ? '' : String(value.text),
        src: value.src || 'mentor' };
    });
    return out;
  }

  function provenanceLabel(value) {
    var found = PROVENANCE.filter(function (item) { return item.value === value; })[0];
    return found ? found.label : '未注明';
  }

  // Shared same-page write lane. The plan editor installs the instance before
  // either editor can save; keeping this factory pure also makes races testable.
  function createWriteBridge(initialRev, onRev) {
    var rev = Number(initialRev || 0);
    var chain = Promise.resolve();
    var pending = 0;
    return {
      enqueue: function (fn) {
        pending += 1;
        var run = chain.then(fn, fn).finally(function () { pending -= 1; });
        chain = run.catch(function () {});
        return run;
      },
      isIdle: function () { return pending === 0; },
      getRev: function () { return rev; },
      setRev: function (next) {
        if (next == null || !isFinite(Number(next))) return rev;
        rev = Number(next);
        if (onRev) onRev(rev);
        return rev;
      }
    };
  }

  function directGateBlockers(base, plan) {
    var blockers = (base || []).slice();
    var data = plan || {};
    var brief = data.teaching_brief || {};
    var required = [
      ['learning_need', '学习需求'],
      ['current_situation', '当前情境'],
      ['current_response', '当前反应']
    ];
    var missing = required.filter(function (row) {
      var entry = brief[row[0]] || {};
      return !(entry.text == null ? '' : String(entry.text)).trim() || !entry.use_for_teaching;
    });
    if (!data.brief_revision || data.brief_confirmed_revision !== data.brief_revision)
      blockers.push('请确认当前教学简报');
    if (missing.length)
      blockers.push('请补充并授权用于教学：' + missing.map(function (row) { return row[1]; }).join('、'));
    return blockers;
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
      GROUPS: GROUPS,
      BRIEF_FIELDS: BRIEF_FIELDS,
      PROVENANCE: PROVENANCE,
      missingTeaching: missingTeaching,
      briefPayload: briefPayload,
      briefFromPlan: briefFromPlan,
      briefSignature: briefSignature,
      profilePayload: profilePayload,
      profileFromPlan: profileFromPlan,
      normalizeEntry: normalizeEntry,
      provenanceLabel: provenanceLabel,
      createWriteBridge: createWriteBridge,
      directGateBlockers: directGateBlockers
    };
  }

  var doc = typeof document !== 'undefined' ? document : null;
  if (!doc) return;

  var active = null;

  function createInstance(root, options) {
    var initial = options && options.initial;
    if (!initial) {
      var script = root.querySelector('[data-role="initial"]');
      if (script) {
        try { initial = JSON.parse(script.textContent); } catch (err) { initial = null; }
      }
    }
    var planId = Number(root.dataset.planId || (initial && initial.plan && initial.plan.id) || 0);
    var state = {
      planId: planId,
      rev: Number(root.dataset.rev || (initial && initial.plan && initial.plan.rev) || 0),
      plan: (initial && initial.plan) || {},
      files: (initial && initial.files) || [],
      goals: (initial && initial.goals) || [],
      profile: profileFromPlan(initial && initial.plan),
      brief: briefFromPlan(initial && initial.plan),
      canEdit: root.dataset.canEdit === '1',
      baseCanEdit: root.dataset.canEdit === '1',
      goalNames: {},
      profileDirty: false,
      briefDirty: false,
      conflict: false,
      extracting: false,
      goalsBusy: false,
      timers: {},
      queue: Promise.resolve(),
      destroyed: false
    };
    ((initial && initial.goals) || []).forEach(function (goal) {
      state.goalNames[goal.code] = goal.name || '';
    });

    var opts = options || {};
    var els = {};
    ['status', 'alert', 'profile', 'brief', 'briefState', 'briefMissing', 'files',
      'goals', 'profileState', 'briefSaveState', 'uploadState', 'extractState',
      'goalState'].forEach(function (name) {
      els[name] = root.querySelector('[data-role="' + name + '"]');
    });

    function el(tag, cls, text) {
      var node = doc.createElement(tag);
      if (cls) node.className = cls;
      if (text != null) node.textContent = text;
      return node;
    }

    function updateRev(plan) {
      if (!plan) return;
      if (plan.rev != null) state.rev = Number(plan.rev);
      root.dataset.rev = String(state.rev);
      if (window.M1PlanWriteBridge) window.M1PlanWriteBridge.setRev(state.rev);
      if (typeof opts.onRev === 'function') opts.onRev(state.rev);
      try {
        window.dispatchEvent(new CustomEvent('m1:plan-rev', {
          detail: { planId: state.planId, rev: state.rev, source: 'direct_inputs' }
        }));
      } catch (err) {}
    }

    function applyPlan(plan) {
      state.plan = plan || {};
      var status = state.plan.status;
      state.canEdit = state.baseCanEdit && (status === 'inputs' || status === 'review');
      updateRev(state.plan);
    }

    function request(path, init) {
      init = Object.assign({ headers: {} }, init || {});
      if (init.body && !(typeof FormData !== 'undefined' && init.body instanceof FormData)) {
        init.headers['Content-Type'] = 'application/json';
        init.body = JSON.stringify(init.body);
      }
      return fetch(path, init).then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (body) {
          if (!res.ok || body.ok === false) {
            var error = new Error(body.reason || body.error || ('请求失败（' + res.status + '）'));
            error.status = res.status;
            error.rev = body.rev;
            error.body = body;
            throw error;
          }
          return body;
        });
      });
    }

    function enqueue(fn) {
      if (window.M1PlanWriteBridge) return window.M1PlanWriteBridge.enqueue(fn);
      state.queue = state.queue.then(fn, fn);
      return state.queue;
    }

    function canEdit() { return state.canEdit && !state.destroyed; }

    function briefConfirmed() {
      return !state.briefDirty && !!(state.plan.brief_revision &&
        state.plan.brief_confirmed_revision === state.plan.brief_revision);
    }

    function setState(node, text, tone) {
      if (!node) return;
      node.textContent = text || '';
      node.dataset.tone = tone || '';
    }

    function showAlert(message, actions) {
      if (!els.alert) return;
      els.alert.innerHTML = '';
      els.alert.appendChild(el('p', null, message));
      if (actions && actions.length) {
        var row = el('div', 'di-alert-actions');
        actions.forEach(function (action) {
          var button = el('button', 'btn s', action.label);
          button.type = 'button';
          button.addEventListener('click', function () {
            clearAlert();
            action.run();
          });
          row.appendChild(button);
        });
        els.alert.appendChild(row);
      }
      els.alert.hidden = false;
      els.alert.setAttribute('tabindex', '-1');
      els.alert.focus();
    }

    function clearAlert() {
      if (!els.alert) return;
      els.alert.hidden = true;
      els.alert.innerHTML = '';
    }

    function handleSaveError(error, label) {
      var payload = error.payload || error.body || {};
      var code = payload.code || '';
      if (error.status === 409 || code === 'stale_section' || code === 'stale_document') {
        state.conflict = true;
        if (error.rev != null) {
          state.rev = Number(error.rev);
          root.dataset.rev = String(state.rev);
        }
        showAlert(
          '这部分已在别处更新。你在' + label + '里的修改仍保留在页面上，没有被丢弃。',
          [
            { label: '保留我的文字并重新应用', run: resolveConflict },
            { label: '放弃修改并刷新', run: function () {
              state.conflict = false;
              state.profileDirty = false;
              state.briefDirty = false;
              refresh();
            } }
          ]
        );
        return false;
      }
      if (code === 'lease_conflict') {
        var holder = payload.holder || {};
        showAlert((holder.name || '其他导师') + '正在编辑这部分，暂时无法保存。你的文字仍在页面上。', [
          { label: '稍后重试', run: function () {
            if (label === '学生资料') saveProfile(); else saveBrief();
          } }
        ]);
        return false;
      }
      showAlert(error.message || (label + '保存失败'), [
        { label: '重试', run: function () {
          if (label === '学生资料') saveProfile(); else saveBrief();
        } }
      ]);
      return false;
    }

    function resolveConflict() {
      state.conflict = false;
      if (state.profileDirty) schedule('profile');
      if (state.briefDirty) schedule('brief');
    }

    function saveProfile() {
      if (!canEdit() || state.conflict || !state.profileDirty) return Promise.resolve(true);
      var payload = profilePayload(state.profile);
      state.profileDirty = false;
      setState(els.profileState, '正在保存…', 'busy');
      renderStatus();
      var bridge = window.M1PlanWriteBridge;
      if (bridge && bridge.patchSection) {
        return bridge.patchSection('inputs', payload).then(function (data) {
          state.plan.inputs = data.section_value;
          if (!state.profileDirty) {
            state.profile = profileFromPlan(state.plan);
            setState(els.profileState, '已保存', 'ok');
          }
          renderStatus();
          return true;
        }).catch(function (error) {
          state.profileDirty = true;
          setState(els.profileState, '保存失败', 'err');
          renderStatus();
          return handleSaveError(error, '学生资料');
        });
      }
      return enqueue(function () {
        return request('/api/m1/plans/' + state.planId + '/inputs', {
          method: 'PUT', body: { rev: state.rev, inputs: payload }
        }).then(function (data) {
          applyPlan(data.plan);
          if (!state.profileDirty) {
            state.profile = profileFromPlan(data.plan);
            setState(els.profileState, '已保存', 'ok');
          }
          renderStatus();
          return true;
        }).catch(function (error) {
          state.profileDirty = true;
          setState(els.profileState, '保存失败', 'err');
          renderStatus();
          return handleSaveError(error, '学生资料');
        });
      });
    }

    function saveBrief() {
      if (!canEdit() || state.conflict || !state.briefDirty) return Promise.resolve(true);
      var payload = briefPayload(state.brief);
      var signature = briefSignature(state.brief);
      state.briefDirty = false;
      setState(els.briefSaveState, '正在保存…', 'busy');
      renderStatus();
      var bridge = window.M1PlanWriteBridge;
      if (bridge && bridge.patchSection) {
        return bridge.patchSection('brief', {teaching_brief: payload}).then(function () {
          return request('/api/m1/plans/' + state.planId, {method: 'GET'});
        }).then(function (data) {
          applyPlan(data.plan);
          if (briefSignature(state.brief) === signature) {
            state.brief = briefFromPlan(data.plan);
            renderBrief();
            setState(els.briefSaveState, '已保存', 'ok');
          }
          renderStatus();
          return true;
        }).catch(function (error) {
          state.briefDirty = true;
          setState(els.briefSaveState, '保存失败', 'err');
          renderStatus();
          return handleSaveError(error, '教学简报');
        });
      }
      return enqueue(function () {
        return request('/api/m1/plans/' + state.planId + '/brief', {
          method: 'PUT', body: { rev: state.rev, teaching_brief: payload, mark_edited: true }
        }).then(function (data) {
          applyPlan(data.plan);
          if (briefSignature(state.brief) === signature) {
            state.brief = briefFromPlan(data.plan);
            renderBrief();
            setState(els.briefSaveState, '已保存', 'ok');
          }
          renderStatus();
          return true;
        }).catch(function (error) {
          state.briefDirty = true;
          setState(els.briefSaveState, '保存失败', 'err');
          renderStatus();
          return handleSaveError(error, '教学简报');
        });
      });
    }

    function clearTimer(kind) {
      if (state.timers[kind]) {
        clearTimeout(state.timers[kind]);
        state.timers[kind] = null;
      }
    }

    function schedule(kind) {
      state[kind + 'Dirty'] = true;
      clearTimer(kind);
      if (!canEdit() || state.conflict) return;
      state.timers[kind] = setTimeout(function () {
        state.timers[kind] = null;
        if (kind === 'profile') saveProfile(); else saveBrief();
      }, 1100);
      renderStatus();
    }

    function flush() {
      clearTimer('profile');
      clearTimer('brief');
      return saveProfile().then(function (ok) {
        if (!ok) return false;
        return saveBrief();
      });
    }

    function fieldEntry(key) { return state.brief[key] || emptyEntry(); }

    function entryMissing(field) {
      if (!field.required) return false;
      var entry = fieldEntry(field.key);
      return !entry.text.trim() || !entry.use_for_teaching;
    }

    function updateMissingSummary() {
      if (!els.briefMissing) return;
      var missing = missingTeaching(state.brief);
      if (!missing.length) {
        els.briefMissing.textContent = '三项教学输入已填写并勾选用于教学。';
        els.briefMissing.dataset.tone = 'ok';
      } else {
        els.briefMissing.textContent = '还缺：' + missing.map(function (field) {
          return field.label;
        }).join('、') + '（需要填写并勾选「用于教学」）。';
        els.briefMissing.dataset.tone = 'warn';
      }
    }

    function renderRef(field, entry, wrap) {
      wrap.innerHTML = '';
      if (entry.provenance === 'file') {
        var select = el('select');
        var blank = el('option', null, state.files.length ? '选择文件' : '先上传资料');
        blank.value = '';
        select.appendChild(blank);
        state.files.forEach(function (file) {
          var option = el('option', null, file.filename || ('文件 ' + file.id));
          option.value = String(file.id);
          select.appendChild(option);
        });
        select.value = entry.source_ref || '';
        select.disabled = !canEdit();
        select.addEventListener('change', function () {
          entry.source_ref = select.value;
          schedule('brief');
        });
        wrap.appendChild(select);
      } else if (entry.provenance === 'report') {
        var input = el('input');
        input.readOnly = true;
        input.value = entry.source_ref || ('报告版本 #' + (state.plan.report_version_id || ''));
        wrap.appendChild(input);
      } else {
        var text = el('input');
        text.type = 'text';
        text.placeholder = '可选，例如家长消息 2026-10-02';
        text.value = entry.source_ref || '';
        text.disabled = !canEdit();
        text.addEventListener('input', function () {
          entry.source_ref = text.value;
          schedule('brief');
        });
        wrap.appendChild(text);
      }
    }

    function updateFieldIndicators(field) {
      var wrap = els.brief.querySelector('[data-key="' + field.key + '"]');
      if (!wrap) return;
      var entry = fieldEntry(field.key);
      var source = wrap.querySelector('[data-role="source"]');
      if (source) source.textContent = '来源：' + provenanceLabel(entry.provenance);
      var missing = wrap.querySelector('[data-role="missing"]');
      if (missing) {
        var isMissing = entryMissing(field);
        missing.hidden = !isMissing;
        missing.textContent = isMissing
          ? (entry.text.trim() ? '需要勾选「用于教学」' : '需要填写这条教学输入') : '';
      }
    }

    function renderBriefField(field) {
      var entry = fieldEntry(field.key);
      var wrap = el('div', 'di-field di-brief-field');
      wrap.dataset.key = field.key;

      var head = el('div', 'di-entry-head');
      var label = el('label', null, field.label);
      label.htmlFor = 'diBrief-' + field.key;
      head.appendChild(label);
      var source = el('span', 'di-src');
      source.dataset.role = 'source';
      source.textContent = '来源：' + provenanceLabel(entry.provenance);
      head.appendChild(source);
      wrap.appendChild(head);
      wrap.appendChild(el('p', 'di-help', field.help));

      var textarea = el('textarea');
      textarea.id = 'diBrief-' + field.key;
      textarea.rows = 3;
      textarea.value = entry.text;
      textarea.disabled = !canEdit();
      textarea.addEventListener('input', function () {
        entry.text = textarea.value;
        if (entry.provenance === 'unknown' && textarea.value.trim()) {
          entry.provenance = 'mentor';
          var select = wrap.querySelector('[data-role="provenance"]');
          if (select) select.value = 'mentor';
          renderRef(field, entry, wrap.querySelector('[data-role="ref"]'));
        }
        updateFieldIndicators(field);
        updateMissingSummary();
        schedule('brief');
      });
      wrap.appendChild(textarea);

      var meta = el('div', 'di-entry-meta');
      var provLabel = el('label', null, '来源');
      var provSelect = el('select');
      provSelect.dataset.role = 'provenance';
      PROVENANCE.forEach(function (item) {
        if (item.value === 'report' && !state.plan.report_version_id) return;
        var option = el('option', null, item.label);
        option.value = item.value;
        provSelect.appendChild(option);
      });
      provSelect.value = entry.provenance;
      provSelect.disabled = !canEdit();
      provSelect.addEventListener('change', function () {
        entry.provenance = provSelect.value;
        if (entry.provenance !== 'file' && entry.provenance !== 'report') {
          entry.source_ref = '';
        }
        renderRef(field, entry, wrap.querySelector('[data-role="ref"]'));
        updateFieldIndicators(field);
        schedule('brief');
      });
      provLabel.appendChild(provSelect);
      meta.appendChild(provLabel);

      var refLabel = el('label', null, '来源说明');
      var refWrap = el('span');
      refWrap.dataset.role = 'ref';
      renderRef(field, entry, refWrap);
      refLabel.appendChild(refWrap);
      meta.appendChild(refLabel);

      var useLabel = el('label', 'di-check');
      var use = el('input');
      use.type = 'checkbox';
      use.checked = !!entry.use_for_teaching;
      use.disabled = !canEdit();
      use.addEventListener('change', function () {
        entry.use_for_teaching = use.checked;
        updateFieldIndicators(field);
        updateMissingSummary();
        schedule('brief');
      });
      useLabel.appendChild(use);
      useLabel.appendChild(doc.createTextNode(' 用于教学'));
      meta.appendChild(useLabel);

      var disclosureLabel = el('label', null, '披露');
      var disclosure = el('select');
      DISCLOSURE.forEach(function (item) {
        var option = el('option', null, item.label);
        option.value = item.value;
        disclosure.appendChild(option);
      });
      disclosure.value = entry.disclosure;
      disclosure.disabled = !canEdit();
      disclosure.addEventListener('change', function () {
        entry.disclosure = disclosure.value;
        schedule('brief');
      });
      disclosureLabel.appendChild(disclosure);
      meta.appendChild(disclosureLabel);
      wrap.appendChild(meta);

      var missing = el('p', 'di-missing');
      missing.dataset.role = 'missing';
      var isMissing = entryMissing(field);
      missing.hidden = !isMissing;
      missing.textContent = isMissing
        ? (entry.text.trim() ? '需要勾选「用于教学」' : '需要填写这条教学输入') : '';
      wrap.appendChild(missing);
      return wrap;
    }

    function renderBrief() {
      if (!els.brief) return;
      els.brief.innerHTML = '';
      GROUPS.forEach(function (group) {
        var section = el('section', 'di-group');
        section.appendChild(el('h4', null, group.label));
        section.appendChild(el('p', 'di-help', group.note));
        var fields = el('div', 'di-fields');
        BRIEF_FIELDS.filter(function (field) { return field.group === group.key; })
          .forEach(function (field) { fields.appendChild(renderBriefField(field)); });
        section.appendChild(fields);
        els.brief.appendChild(section);
      });
      updateMissingSummary();
    }

    function renderProfile() {
      if (!els.profile) return;
      els.profile.innerHTML = '';
      PROFILE_FIELDS.forEach(function (field) {
        var wrap = el('div', 'di-field');
        var label = el('label', null, field.label);
        label.htmlFor = 'diProfile-' + field.key;
        wrap.appendChild(label);
        wrap.appendChild(el('p', 'di-help', field.help));
        var textarea = el('textarea');
        textarea.id = 'diProfile-' + field.key;
        textarea.rows = 3;
        textarea.value = (state.profile[field.key] || {}).text || '';
        textarea.disabled = !canEdit();
        textarea.addEventListener('input', function () {
          state.profile[field.key] = state.profile[field.key] || { src: 'mentor' };
          state.profile[field.key].text = textarea.value;
          schedule('profile');
        });
        wrap.appendChild(textarea);
        els.profile.appendChild(wrap);
      });
    }

    function formatSize(size) {
      if (size == null) return '';
      return size >= 1024 ? Math.floor(size / 1024) + ' KB' : size + ' B';
    }

    function textStatus(value) {
      if (value === 'ok' || value === 'done' || value === 'parsed') return '已解析';
      if (value === 'pending' || value === 'processing') return '解析中';
      if (value === 'error' || value === 'failed') return '解析失败';
      return '已上传';
    }

    function renderFiles() {
      if (!els.files) return;
      els.files.innerHTML = '';
      if (!state.files.length) {
        var empty = el('li', 'di-empty', '还没有上传资料。粘贴资料或上传文件后可以提取草案。');
        els.files.appendChild(empty);
        return;
      }
      state.files.forEach(function (file) {
        var item = el('li', 'di-file');
        item.appendChild(el('span', 'di-file-name', file.filename || ('文件 ' + file.id)));
        item.appendChild(el('span', 'di-file-meta',
          [textStatus(file.text_status), formatSize(file.size)].filter(Boolean).join(' · ')));
        if (canEdit()) {
          var del = el('button', 'di-link', '删除');
          del.type = 'button';
          del.addEventListener('click', function () { deleteFile(file); });
          item.appendChild(del);
        }
        els.files.appendChild(item);
      });
    }

    function renderGoals() {
      if (!els.goals) return;
      els.goals.innerHTML = '';
      var goals = state.plan.goals || [];
      if (!goals.length) {
        els.goals.appendChild(el('p', 'di-empty',
          '还没有目标。先在目标选择中选 1–3 个，再回来让 AI 起草措辞。'));
        return;
      }
      goals.forEach(function (item) {
        var row = el('div', 'di-goal');
        var head = el('div', 'di-goal-head');
        head.appendChild(el('code', null, item.code));
        head.appendChild(el('b', null, state.goalNames[item.code] || ''));
        head.appendChild(el('span', item.locked ? 'st s0' : 'st sn',
          item.locked ? '已确认' : '待确认'));
        row.appendChild(head);
        var text = ((item.goal || {}).text || '').trim();
        row.appendChild(el('p', text ? 'di-goal-text' : 'di-goal-text mu',
          text || '还没有目标措辞。'));
        if (!item.locked) {
          var button = el('button', 'btn s', 'AI 起草目标描述');
          button.type = 'button';
          button.dataset.role = 'fill';
          button.dataset.code = item.code;
          button.disabled = !canEdit() || !briefConfirmed();
          button.addEventListener('click', function () { fillGoal(item.code, button); });
          row.appendChild(button);
          if (!briefConfirmed()) {
            row.appendChild(el('span', 'di-help', '先保存并确认教学简报。'));
          }
        }
        els.goals.appendChild(row);
      });
    }

    function renderStatus() {
      if (!els.status) return;
      if (!canEdit()) {
        setState(els.status, '只读：当前步骤不能再修改。', 'mute');
      } else if (state.conflict) {
        setState(els.status, '有版本冲突，修改仍保留。', 'warn');
      } else if (state.extracting) {
        setState(els.status, '正在提取资料…', 'busy');
      } else if (state.profileDirty || state.briefDirty) {
        setState(els.status, '有未保存的修改，稍后自动保存。', 'busy');
      } else {
        setState(els.status, '可编辑', 'ok');
      }

      if (els.briefState) {
        var briefState = '未保存';
        if (state.plan.brief_revision) {
          briefState = '第 ' + state.plan.brief_revision + ' 版';
          if (state.briefDirty) briefState += ' · 有修改未保存';
          else if (state.plan.brief_confirmed_revision === state.plan.brief_revision) {
            briefState += ' · 已确认';
          } else {
            briefState += ' · 待确认';
          }
        }
        els.briefState.textContent = briefState;
      }

      var saveButtons = root.querySelectorAll('[data-role="save-profile"], [data-role="save-brief"]');
      Array.prototype.forEach.call(saveButtons, function (button) {
        button.disabled = !canEdit();
      });
      Array.prototype.forEach.call(root.querySelectorAll('textarea, select, input'), function (node) {
        if (node.closest('[data-role="alert"]')) return;
        node.disabled = !canEdit();
      });
      var confirm = root.querySelector('[data-role="confirm-brief"]');
      if (confirm) {
        confirm.disabled = !canEdit() || !state.plan.brief_revision ||
          state.profileDirty || state.briefDirty || state.conflict ||
          briefConfirmed() || state.extracting;
      }
      var upload = root.querySelector('[data-role="upload"]');
      if (upload) upload.disabled = !canEdit() || state.extracting;
      var extract = root.querySelector('[data-role="extract"]');
      if (extract) extract.disabled = !canEdit() || state.extracting;
      Array.prototype.forEach.call(root.querySelectorAll('[data-role="fill"]'), function (button) {
        button.disabled = !canEdit() || !briefConfirmed() || state.goalsBusy;
      });
    }

    function render() {
      renderProfile();
      renderBrief();
      renderFiles();
      renderGoals();
      renderStatus();
    }

    function upload() {
      var input = root.querySelector('[data-role="file-input"]');
      if (!input || !input.files || !input.files[0] || !canEdit()) return;
      var form = new FormData();
      form.append('file', input.files[0]);
      setState(els.uploadState, '正在上传…', 'busy');
      request('/api/m1/plans/' + state.planId + '/files', { method: 'POST', body: form })
        .then(function (data) {
          if (data.file) state.files.push(data.file);
          input.value = '';
          renderFiles();
          renderBrief();
          setState(els.uploadState, '已上传', 'ok');
        }).catch(function (error) {
          setState(els.uploadState, '上传失败：' + (error.message || ''), 'err');
          showAlert(error.message || '上传失败', []);
        });
    }

    function deleteFile(file) {
      if (!canEdit()) return;
      setState(els.uploadState, '正在删除…', 'busy');
      request('/api/m1/plan-files/' + file.id, { method: 'DELETE' })
        .then(function () {
          state.files = state.files.filter(function (item) { return item.id !== file.id; });
          renderFiles();
          renderBrief();
          setState(els.uploadState, '已删除', 'ok');
        }).catch(function (error) {
          setState(els.uploadState, '删除失败：' + (error.message || ''), 'err');
        });
    }

    function pollJob(jobId, done, fail) {
      var attempts = 0;
      function tick() {
        if (state.destroyed) return;
        request('/api/m1/jobs/' + jobId).then(function (data) {
          var job = data.job || {};
          if (job.status === 'done') { done(job); return; }
          if (job.status === 'failed' || job.status === 'error') {
            fail(new Error(job.error || '任务失败'));
            return;
          }
          attempts += 1;
          if (attempts > 200) { fail(new Error('任务超时')); return; }
          setTimeout(tick, 1500);
        }).catch(fail);
      }
      tick();
    }

    function extractionSignature() {
      return briefSignature(state.brief) + '\u0003' +
        JSON.stringify(profilePayload(state.profile));
    }

    function extract() {
      if (!canEdit() || state.extracting) return;
      var before = extractionSignature();
      setState(els.extractState, '正在准备…', 'busy');
      flush().then(function (ok) {
        if (!ok) return null;
        return request('/api/m1/plans/' + state.planId + '/extract-inputs', {
          method: 'POST', body: { rev: state.rev }
        });
      }).then(function (data) {
        if (!data) return;
        state.extracting = true;
        renderStatus();
        setState(els.extractState, '正在提取…', 'busy');
        pollJob(data.job_id, function () {
          state.extracting = false;
          renderStatus();
          if (extractionSignature() !== before) {
            setState(els.extractState, '提取完成，等待你选择。', 'warn');
            showAlert(
              '提取已完成，但你在提取期间修改了内容。载入提取结果会覆盖这些修改；保留当前内容则不会载入。',
              [
                { label: '载入提取结果（覆盖当前修改）', run: function () {
                  state.briefDirty = false;
                  state.profileDirty = false;
                  refresh();
                  setState(els.extractState, '已载入提取结果，请逐项复核。', 'ok');
                } },
                { label: '保留当前内容', run: function () {
                  refreshMetaOnly().then(function () {
                    setState(els.extractState, '已保留当前内容。', 'ok');
                  });
                } }
              ]
            );
            return;
          }
          refresh().then(function () {
            setState(els.extractState, '提取完成，请逐项复核来源与教学授权。', 'ok');
          });
        }, function (error) {
          state.extracting = false;
          renderStatus();
          setState(els.extractState, '提取失败：' + (error.message || ''), 'err');
          showAlert('提取失败。已输入内容仍保留在页面上，可以直接重试。', [
            { label: '重试提取', run: extract }
          ]);
        });
      }).catch(function (error) {
        state.extracting = false;
        renderStatus();
        setState(els.extractState, '提取失败：' + (error.message || ''), 'err');
        showAlert(error.message || '提取失败', [{ label: '重试提取', run: extract }]);
      });
    }

    function confirmBrief() {
      if (!canEdit() || state.extracting) return;
      flush().then(function (ok) {
        if (!ok) return null;
        if (state.briefDirty) throw new Error('简报还有未保存的修改');
        if (!state.plan.brief_revision) throw new Error('先保存教学简报');
        return request('/api/m1/plans/' + state.planId + '/brief/confirm', {
          method: 'POST', body: { rev: state.rev }
        });
      }).then(function (data) {
        if (!data) return;
        applyPlan(data.plan);
        renderStatus();
        state.brief = briefFromPlan(data.plan);
        renderBrief();
        var missing = missingTeaching(state.brief);
        if (missing.length) {
          showAlert('教学简报已确认。生成前仍需补齐：' +
            missing.map(function (field) { return field.label; }).join('、') + '。', []);
        } else {
          clearAlert();
          setState(els.briefSaveState, '已确认', 'ok');
        }
      }).catch(function (error) {
        showAlert(error.message || '确认失败', [
          { label: '重试确认', run: confirmBrief }
        ]);
      });
    }

    function fillGoal(code, button) {
      if (!canEdit() || state.goalsBusy) return;
      if (!briefConfirmed()) {
        setState(els.goalState, '先保存并确认教学简报。', 'warn');
        return;
      }
      state.goalsBusy = true;
      button.disabled = true;
      setState(els.goalState, '正在起草…', 'busy');
      renderStatus();
      flush().then(function (ok) {
        if (!ok) return null;
        return request('/api/m1/plans/' + state.planId + '/goals/' + code + '/fill', {
          method: 'POST', body: { rev: state.rev }
        });
      }).then(function (data) {
        if (!data) {
          state.goalsBusy = false;
          renderStatus();
          return;
        }
        pollJob(data.job_id, function () {
          state.goalsBusy = false;
          refresh().then(function () {
            setState(els.goalState, '已更新目标措辞。', 'ok');
          });
        }, function (error) {
          state.goalsBusy = false;
          renderStatus();
          setState(els.goalState, '起草失败：' + (error.message || ''), 'err');
          showAlert(error.message || '目标起草失败', []);
        });
      }).catch(function (error) {
        state.goalsBusy = false;
        renderStatus();
        setState(els.goalState, '起草失败：' + (error.message || ''), 'err');
        showAlert(error.message || '目标起草失败', []);
      });
    }

    function refreshMetaOnly() {
      return request('/api/m1/plans/' + state.planId).then(function (data) {
        applyPlan(data.plan);
        state.files = (data.personal && data.personal.files) || [];
        state.goals = data.goals || state.goals;
        state.goals.forEach(function (goal) {
          if (goal.name) state.goalNames[goal.code] = goal.name;
        });
        renderFiles();
        renderGoals();
        renderStatus();
        state.profileDirty = true;
        state.briefDirty = true;
        renderStatus();
        return true;
      });
    }

    function refresh() {
      return request('/api/m1/plans/' + state.planId).then(function (data) {
        applyPlan(data.plan);
        state.files = (data.personal && data.personal.files) || [];
        state.goals = data.goals || [];
        state.goals.forEach(function (goal) {
          if (goal.name) state.goalNames[goal.code] = goal.name;
        });
        state.profile = profileFromPlan(data.plan);
        state.brief = briefFromPlan(data.plan);
        state.profileDirty = false;
        state.briefDirty = false;
        state.conflict = false;
        clearAlert();
        render();
        return true;
      }).catch(function (error) {
        showAlert(error.message || '刷新失败', []);
        return false;
      });
    }

    function setRev(rev) {
      if (rev == null) return;
      state.rev = Number(rev);
      root.dataset.rev = String(state.rev);
      if (window.M1PlanWriteBridge) window.M1PlanWriteBridge.setRev(state.rev);
    }

    root.querySelector('[data-role="save-profile"]').addEventListener('click', function () {
      clearTimer('profile');
      saveProfile();
    });
    root.querySelector('[data-role="save-brief"]').addEventListener('click', function () {
      clearTimer('brief');
      saveBrief();
    });
    root.querySelector('[data-role="confirm-brief"]').addEventListener('click', confirmBrief);
    root.querySelector('[data-role="upload"]').addEventListener('click', upload);
    root.querySelector('[data-role="extract"]').addEventListener('click', extract);

    var instance = {
      root: root,
      refresh: refresh,
      flush: flush,
      getRev: function () { return state.rev; },
      setRev: setRev,
      configure: function (next) {
        opts = Object.assign({}, opts, next || {});
        if (typeof opts.onRev === 'function') opts.onRev(state.rev);
        return instance;
      },
      destroy: function () {
        clearTimer('profile');
        clearTimer('brief');
        state.destroyed = true;
        if (active === instance) active = null;
      },
      getState: function () {
        return {
          rev: state.rev,
          profileDirty: state.profileDirty,
          briefDirty: state.briefDirty,
          conflict: state.conflict,
          extracting: state.extracting
        };
      }
    };

    render();
    return instance;
  }

  function init(rootOrSelector, options) {
    var root = typeof rootOrSelector === 'string'
      ? doc.querySelector(rootOrSelector) : rootOrSelector;
    if (!root) return null;
    if (active && active.root === root) {
      return options ? active.configure(options) : active;
    }
    active = createInstance(root, options || {});
    return active;
  }

  window.M1DirectInputs = {
    version: 1,
    init: init,
    getActive: function () { return active; },
    createWriteBridge: createWriteBridge,
    directGateBlockers: directGateBlockers
  };

  if (doc.readyState === 'loading') {
    doc.addEventListener('DOMContentLoaded', function () {
      if (!active) init(doc.getElementById('m1DirectInputs'));
    });
  } else if (!active) {
    init(doc.getElementById('m1DirectInputs'));
  }
})();
