/* M1 发展计划：步骤切换、① 资料与目标、② 内部版审阅与自动保存 */
(function () {
  'use strict';

  var ROOT = document.getElementById('m1Plan');
  if (!ROOT) return;

  var CFG = window.M1_PLAN || {};
  var API = '/api/m1/plans/' + CFG.planId;

  var S = {
    rev: CFG.rev,
    status: CFG.status,
    doc: CFG.doc,
    checks: CFG.checks || [],
    goals: CFG.goals || [],
    step1: !!CFG.step1,
    step2: !!CFG.step2,
    canEdit: !!CFG.canEdit,
    useOld: false,
    job: CFG.jobId || null,
    chain: Promise.resolve(),
    docTimer: null,
    goalTimer: null,
    inputTimer: null,
    notesTimer: null,
    lastSaved: null,
    parentDoc: (CFG.parent || {}).doc || null,
    parentStatus: (CFG.parent || {}).status || 'none',
    parentStale: !!(CFG.parent || {}).stale,
    parentEditable: !!(CFG.parent || {}).editable,
    parentBlocking: CFG.parentBlocking || [],
    parentFits: null,
    parentFitText: '',
    parentTimer: null
  };

  /* ---------------------------------------------------------------- utils */
  function toast(message) {
    var host = document.getElementById('toasts');
    if (!host) return;
    var node = document.createElement('div');
    node.className = 'toast';
    node.textContent = message;
    host.appendChild(node);
    setTimeout(function () { node.remove(); }, 2600);
  }

  function request(method, url, body) {
    var opts = {method: method, credentials: 'same-origin', headers: {}};
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    return fetch(url, opts).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok || data.ok === false) {
          var err = new Error(data.error || '请求失败');
          err.status = res.status;
          err.payload = data;
          throw err;
        }
        return data;
      });
    });
  }

  function queue(fn) {
    var run = S.chain.then(fn);
    S.chain = run.catch(function () {});
    return run;
  }

  function get(obj, path) {
    return path.split('.').reduce(function (node, key) {
      return node === undefined || node === null ? undefined : node[key];
    }, obj);
  }

  function set(obj, path, value) {
    var keys = path.split('.');
    var last = keys.pop();
    var node = keys.reduce(function (cur, key) {
      if (cur[key] === undefined || cur[key] === null) cur[key] = {};
      return cur[key];
    }, obj);
    node[last] = value;
  }

  function clock() {
    var d = new Date();
    return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
  }

  function setSave(state, text) {
    var el = document.getElementById('saveState');
    if (!el) return;
    el.className = 'saved' + (state ? ' ' + state : '');
    el.textContent = text || (state === 'busy' ? '保存中…' : state === 'err' ? '保存失败' : '已保存 · ' + clock());
    if (state === 'ok') S.lastSaved = clock();
  }

  function dateLabel(value) {
    var text = String(value || '').slice(0, 16).replace('T', ' ');
    return text.length >= 16 ? text.slice(5) : text;
  }

  /* ------------------------------------------------------------- 步骤切换 */
  function panelFor(step) {
    return document.querySelector('.plan-step[data-panel="' + step + '"]');
  }

  function available(step) {
    var panel = panelFor(step);
    if (!panel) return false;
    if (step === 'internal') return CFG.status !== 'inputs';
    if (step === 'parent') return panel.getAttribute('data-avail') === '1';
    return true;
  }

  function wantedStep() {
    var match = /step=(inputs|internal|parent)/.exec(location.hash || '');
    var step = match ? match[1] : CFG.defaultStep;
    if (!available(step)) {
      if (available('internal')) step = 'internal';
      else if (available('inputs')) step = 'inputs';
    }
    return step;
  }

  function showStep(step, push) {
    ROOT.querySelectorAll('.plan-step').forEach(function (panel) {
      panel.hidden = panel.getAttribute('data-panel') !== step;
    });
    var hash = '#step=' + step;
    if (push && location.hash !== hash) history.replaceState(null, '', hash);
    window.scrollTo({top: 0, behavior: 'smooth'});
    if (step === 'parent') setTimeout(refreshParentFit, 80);
  }

  function applyStep(push) {
    showStep(wantedStep(), push);
  }

  ROOT.querySelectorAll('[data-step]').forEach(function (link) {
    link.addEventListener('click', function (event) {
      var step = link.getAttribute('data-step');
      if (link.getAttribute('aria-disabled') === 'true' || !available(step)) {
        event.preventDefault();
        if (step === 'internal') toast('生成内部教学计划后才能查看');
        else if (step === 'parent') toast('批准内部版后才能生成家长版');
        return;
      }
      event.preventDefault();
      showStep(step, true);
    });
  });

  window.addEventListener('hashchange', function () { applyStep(false); });
  applyStep(true);

  /* ------------------------------------------------------------ 长度计数 */
  function initCounters() {
    document.querySelectorAll('[data-limit]').forEach(function (field) {
      var limit = parseInt(field.getAttribute('data-limit'), 10);
      if (!limit) return;
      var counter = document.createElement('span');
      counter.className = 'pcnt';
      field.insertAdjacentElement('afterend', counter);
      function update() {
        var length = (field.textContent || '').length;
        counter.textContent = length + '/' + limit;
        counter.classList.toggle('over', length > limit);
      }
      field.addEventListener('input', update);
      update();
    });
  }
  initCounters();

  /* -------------------------------------------------------- ① 表头 / 输入 */
  function saveHeader(fields) {
    if (!S.step1) return Promise.resolve();
    setSave('busy');
    return queue(function () {
      return request('PATCH', API, Object.assign({rev: S.rev}, fields)).then(function (data) {
        S.rev = data.plan.rev;
        setSave('ok');
      });
    }).catch(function (err) {
      setSave('err');
      toast(err.message);
    });
  }

  ['hdrBlock', 'hdrStart', 'hdrEnd', 'hdrCredits'].forEach(function (id) {
    var input = document.getElementById(id);
    if (!input || !S.step1) return;
    input.addEventListener('change', function () {
      var fields = {};
      if (id === 'hdrBlock') fields.block_no = input.value;
      else if (id === 'hdrStart') fields.period_start = input.value;
      else if (id === 'hdrEnd') fields.period_end = input.value;
      else fields.credits = input.value;
      saveHeader(fields);
    });
  });

  var INPUT_SRC = {};
  document.querySelectorAll('[data-input]').forEach(function (field) {
    INPUT_SRC[field.getAttribute('data-input')] = field.getAttribute('data-src') || 'ai';
    if (!S.step1) return;
    field.addEventListener('input', function () {
      var key = field.getAttribute('data-input');
      INPUT_SRC[key] = 'edited';
      var badge = document.querySelector('[data-ai="' + key + '"]');
      if (badge) badge.hidden = true;
      clearTimeout(S.inputTimer);
      S.inputTimer = setTimeout(saveInputs, 700);
    });
  });

  function saveInputs() {
    if (!S.step1) return Promise.resolve();
    var values = {};
    document.querySelectorAll('[data-input]').forEach(function (field) {
      var key = field.getAttribute('data-input');
      values[key] = {text: field.textContent || '', src: INPUT_SRC[key] || 'ai'};
    });
    setSave('busy');
    return queue(function () {
      return request('PUT', API + '/inputs', {rev: S.rev, inputs: values}).then(function (data) {
        S.rev = data.plan.rev;
        setSave('ok');
      });
    }).catch(function (err) {
      setSave('err');
      toast(err.message);
    });
  }

  /* --------------------------------------------------------------- 目标 */
  function goalPayload() {
    return S.goals.map(function (goal) {
      return {
        code: goal.code,
        locked: !!goal.locked,
        goal: goal.goal,
        start: goal.start,
        expected: goal.expected
      };
    });
  }

  function saveGoals() {
    if (!S.step1) return Promise.resolve();
    setSave('busy');
    return queue(function () {
      return request('PUT', API + '/goals', {rev: S.rev, goals: goalPayload()}).then(function (data) {
        S.rev = data.plan.rev;
        setSave('ok');
      });
    }).catch(function (err) {
      setSave('err');
      toast(err.message);
      throw err;
    });
  }

  function findGoal(code) {
    return S.goals.filter(function (goal) { return goal.code === code; })[0];
  }

  document.querySelectorAll('[data-goal-text]').forEach(function (field) {
    var code = field.getAttribute('data-goal-text');
    if (!S.step1) return;
    field.addEventListener('input', function () {
      var goal = findGoal(code);
      if (!goal) return;
      goal.goal = {text: field.textContent || '', src: 'mentor'};
      clearTimeout(S.goalTimer);
      S.goalTimer = setTimeout(saveGoals, 700);
    });
  });

  document.querySelectorAll('[data-goal-value]').forEach(function (field) {
    var key = field.getAttribute('data-goal-value');
    var parts = key.split('-');
    var code = parts[0];
    var which = parts[1];
    if (!S.step1) return;
    field.addEventListener('input', function () {
      var goal = findGoal(code);
      if (!goal) return;
      goal[which] = {text: field.textContent || '', src: 'edited'};
      var badge = document.querySelector('[data-goal-ai="' + key + '"]');
      if (badge) badge.hidden = true;
      clearTimeout(S.goalTimer);
      S.goalTimer = setTimeout(saveGoals, 700);
    });
  });

  document.querySelectorAll('[data-lock]').forEach(function (button) {
    button.addEventListener('click', function () {
      var code = button.getAttribute('data-lock');
      var goal = findGoal(code);
      if (!goal || !S.step1) return;
      var locking = button.getAttribute('data-locked') === '1';
      goal.locked = locking;
      button.disabled = true;
      saveGoals().then(function () {
        var empty = !(goal.start.text || '').trim() && !(goal.expected.text || '').trim();
        if (locking && empty) {
          var dd = document.querySelectorAll('[data-goal-field="' + code + '-start"], [data-goal-field="' + code + '-expected"]');
          dd.forEach(function (node) { node.classList.add('busy'); });
          startJob(API + '/goals/' + code + '/fill', function () { location.reload(); });
        } else {
          location.reload();
        }
      }).catch(function () { button.disabled = false; });
    });
  });

  function addGoal(code) {
    if (!S.step1) return;
    if (!code) return;
    if (S.goals.length >= 3) { toast('最多 3 项目标'); return; }
    if (findGoal(code)) { toast('这项能力已经添加过了'); return; }
    S.goals.push({
      code: code, locked: false,
      goal: {text: '', src: 'mentor'},
      start: {text: '', src: 'ai'},
      expected: {text: '', src: 'ai'}
    });
    saveGoals().then(function () {
      toast('已添加目标，AI 正在填写起点和预期进展');
      startJob(API + '/goals/' + code + '/fill', function () { location.reload(); });
    }).catch(function () {});
  }

  document.querySelectorAll('[data-add-goal]').forEach(function (button) {
    button.addEventListener('click', function () { addGoal(button.getAttribute('data-add-goal')); });
  });

  var addGoalSelect = document.getElementById('addGoal');
  if (addGoalSelect && S.step1) {
    addGoalSelect.addEventListener('change', function () {
      if (addGoalSelect.value) addGoal(addGoalSelect.value);
    });
  }

  /* ----------------------------------------------------------- 个性化需求 */
  var notes = document.getElementById('personalNotes');
  if (notes && S.step1) {
    notes.addEventListener('input', function () {
      clearTimeout(S.notesTimer);
      S.notesTimer = setTimeout(function () {
        setSave('busy');
        queue(function () {
          return request('PUT', API + '/personal', {rev: S.rev, notes: notes.value}).then(function (data) {
            S.rev = data.plan.rev;
            setSave('ok');
          });
        }).catch(function (err) { setSave('err'); toast(err.message); });
      }, 700);
    });
  }

  var summaryText = document.getElementById('summaryText');
  if (summaryText && S.step1) {
    summaryText.addEventListener('input', function () {
      clearTimeout(S.summaryTimer);
      S.summaryTimer = setTimeout(function () {
        setSave('busy');
        queue(function () {
          return request('PUT', API + '/personal',
                         {rev: S.rev, summary: summaryText.value}).then(function (data) {
            S.rev = data.plan.rev;
            setSave('ok');
            var mark = document.getElementById('summaryAi');
            if (mark) mark.remove();
          });
        }).catch(function (err) { setSave('err'); toast(err.message); });
      }, 700);
    });
  }

  var fileInput = document.getElementById('fileInput');
  if (fileInput && S.step1) {
    fileInput.addEventListener('change', function () {
      if (!fileInput.files || !fileInput.files[0]) return;
      var form = new FormData();
      form.append('file', fileInput.files[0]);
      setSave('busy');
      fetch(API + '/files', {method: 'POST', body: form, credentials: 'same-origin'})
        .then(function (res) { return res.json(); })
        .then(function (data) {
          if (!data.ok) throw new Error(data.error || '上传失败');
          location.reload();
        })
        .catch(function (err) { setSave('err'); toast(err.message); });
    });
  }

  document.querySelectorAll('[data-del-file]').forEach(function (button) {
    button.addEventListener('click', function () {
      if (!S.step1) return;
      request('DELETE', '/api/m1/plan-files/' + button.getAttribute('data-del-file'))
        .then(function () { location.reload(); })
        .catch(function (err) { toast(err.message); });
    });
  });

  var summaryBtn = document.getElementById('summaryBtn');
  if (summaryBtn && S.step1) {
    summaryBtn.addEventListener('click', function () {
      if (summaryBtn.textContent.trim() === '重新生成'
          && !window.confirm('重新生成会替换现在的需求总结，确定吗？')) return;
      summaryBtn.disabled = true;
      startJob(API + '/personal/summary', function () { location.reload(); }, function () {
        summaryBtn.disabled = false;
      });
    });
  }

  /* --------------------------------------------------------------- 生成 */
  function updateGen(steps) {
    var map = {};
    (steps || []).forEach(function (row) { map[row.step] = row; });
    document.querySelectorAll('[data-gen-step]').forEach(function (row) {
      var data = map[row.getAttribute('data-gen-step')];
      row.classList.remove('on', 'ok');
      if (!data) return;
      if (data.state === 'running') row.classList.add('on');
      else if (data.state === 'done') row.classList.add('ok');
      var right = row.querySelector('.mu');
      if (right && data.seconds) right.textContent = data.seconds + 's';
    });
  }

  function pollJob(jobId, onDone, onError) {
    request('GET', '/api/m1/jobs/' + jobId).then(function (data) {
      var job = data.job || {};
      updateGen(job.steps);
      if (job.status === 'done') {
        if (onDone) onDone();
        return;
      }
      if (job.status === 'error') {
        toast(job.message || '生成失败');
        if (onError) onError();
        return;
      }
      setTimeout(function () { pollJob(jobId, onDone, onError); }, 1500);
    }).catch(function (err) {
      toast(err.message);
      if (onError) onError();
    });
  }

  function startJob(url, onDone, onError, body) {
    setSave('busy', '任务已开始');
    request('POST', url, body || {}).then(function (data) {
      pollJob(data.job_id, onDone, onError);
    }).catch(function (err) {
      setSave('err');
      toast(err.message);
      if (onError) onError();
    });
  }

  var genBtn = document.getElementById('genBtn');
  if (genBtn) {
    genBtn.addEventListener('click', function () {
      genBtn.disabled = true;
      request('POST', API + '/generate', {use_old_report: !!S.useOld}).then(function (data) {
        pollJob(data.job_id, function () {
          location.hash = 'step=internal';
          location.reload();
        }, function () {
          genBtn.disabled = false;
        });
      }).catch(function (err) {
        genBtn.disabled = false;
        toast(err.message);
      });
    });
  }

  var useOldBtn = document.getElementById('useOldBtn');
  if (useOldBtn) {
    useOldBtn.addEventListener('click', function () {
      S.useOld = true;
      var warn = document.getElementById('reportWarn');
      if (warn) warn.remove();
      var rest = (CFG.blockers || []).filter(function (item) {
        return item.indexOf('会后报告已更新') !== 0;
      });
      var hint = document.getElementById('genHint');
      if (hint) hint.textContent = rest.length ? rest.join('；') : '使用旧版会后报告生成。';
      if (genBtn) genBtn.disabled = rest.length > 0;
      toast('已选择继续使用旧版会后报告');
    });
  }

  ['rereadBtn', 'reextractBtn'].forEach(function (id) {
    var button = document.getElementById(id);
    if (!button) return;
    button.addEventListener('click', function () {
      button.disabled = true;
      startJob(API + '/read-report', function () { location.reload(); }, function () {
        button.disabled = false;
      });
    });
  });

  /* 刷新后继续显示正在跑的任务 */
  if (S.status === 'generating') {
    if (CFG.jobId) setTimeout(function () { pollJob(CFG.jobId, function () { location.reload(); }); }, 800);
    else {
      (function pollPlan() {
        setTimeout(function () {
          request('GET', API).then(function (data) {
            if (data.plan && data.plan.status !== 'generating') location.reload();
            else pollPlan();
          }).catch(function () { pollPlan(); });
        }, 2000);
      })();
    }
  }

  /* --------------------------------------------------------- ② 文档编辑 */
  if (!S.doc || !S.step2) {
    if (S.step2 && !S.doc) setSave('', '只读');
  }

  function saveDoc(reload) {
    if (!S.step2 || !S.doc) return Promise.resolve();
    setSave('busy');
    return queue(function () {
      return request('PUT', API + '/internal', {rev: S.rev, doc: S.doc}).then(function (data) {
        S.rev = data.rev;
        S.checks = data.checks || [];
        renderChecks();
        setSave('ok');
        if (reload) location.reload();
        return data;
      });
    }).catch(function (err) {
      setSave('err');
      toast(err.message);
      if (reload) setTimeout(function () { location.reload(); }, 900);
      throw err;
    });
  }

  function bindDocFields() {
    document.querySelectorAll('#doc [data-path]').forEach(function (field) {
      var path = field.getAttribute('data-path');
      if (field.tagName === 'SELECT') {
        field.addEventListener('change', function () {
          if (field.hasAttribute('data-source-type')) {
            var type = field.value;
            var base = path.replace(/\.source\.type$/, '');
            var source = get(S.doc, base + '.source') || {};
            if (type === 'world_bank') {
              var candidates = (CFG.sessionCandidates || {})[field.getAttribute('data-source-type').split('-')[0]] || [];
              var wbId = source.wb_id || (candidates[0] && candidates[0].wb_id);
              if (!wbId) {
                field.value = source.type || 'ai_original';
                toast('这一节没有可用的 WB 参考课');
                return;
              }
              source.wb_id = wbId;
              source.text = '';
            } else if (type === 'other') {
              var text = window.prompt('写参考来源（作者 / 书名 / 页码）', source.text || '');
              if (!text || !text.trim()) { field.value = source.type || 'ai_original'; return; }
              source.text = text.trim();
              source.wb_id = null;
            } else {
              source.wb_id = null;
              source.text = '';
            }
            source.type = type;
            set(S.doc, base + '.source', source);
            saveDoc(true);
            return;
          }
          set(S.doc, path, field.value);
          if (field.hasAttribute('data-source-lesson') || /\.source\.wb_id$/.test(path)) {
            saveDoc(true);
          } else if (/\.focus\.(primary|supporting)$/.test(path)) {
            saveDoc(true);
          } else {
            saveDoc(false);
          }
        });
        return;
      }
      if (field.tagName === 'INPUT') {
        field.addEventListener('change', function () {
          var value = field.type === 'number' ? parseInt(field.value, 10) || 1 : field.value;
          set(S.doc, path, value);
          saveDoc(false);
        });
        return;
      }
      field.addEventListener('input', function () {
        set(S.doc, path, field.textContent || '');
        clearTimeout(S.docTimer);
        S.docTimer = setTimeout(function () { saveDoc(false); }, 700);
      });
    });

    var mentor = document.getElementById('mentorNotes');
    if (mentor) {
      mentor.addEventListener('input', function () {
        S.doc.mentor_notes = {text: mentor.value, src: 'edited'};
        clearTimeout(S.docTimer);
        S.docTimer = setTimeout(function () { saveDoc(false); }, 700);
      });
    }
  }
  bindDocFields();

  function nextId(list, prefix) {
    var max = 0;
    (list || []).forEach(function (row) {
      var match = new RegExp('^' + prefix + '(\\d+)$').exec(row.id || '');
      if (match) max = Math.max(max, parseInt(match[1], 10));
    });
    return prefix + (max + 1);
  }

  document.querySelectorAll('[data-op]').forEach(function (button) {
    button.addEventListener('click', function () {
      if (!S.step2 || !S.doc) return;
      var index = parseInt(button.getAttribute('data-s'), 10);
      var session = (S.doc.sessions || [])[index];
      if (!session) return;
      var op = button.getAttribute('data-op');
      if (op === 'add-activity') {
        var activities = session.activities || (session.activities = []);
        var row = {
          id: nextId(activities, 's' + (index + 1) + 'a'),
          name: {text: '新的教学活动', src: 'ai'},
          minutes: 15,
          steps: {text: '（填写活动步骤）', src: 'ai'},
          questions: {text: '（填写引导问题）', src: 'ai'},
          materials: {text: '（填写所需材料）', src: 'ai'},
          source: {type: 'ai_original', wb_id: null, text: ''},
          block_review: false
        };
        var insertAt = activities.length;
        if (insertAt && activities[insertAt - 1].block_review) insertAt -= 1;
        activities.splice(insertAt, 0, row);
        saveDoc(true);
        return;
      }
      if (op === 'add-practice') {
        var practices = session.practice || (session.practice = []);
        var focus = session.focus || {};
        practices.push({
          id: nextId(practices, 's' + (index + 1) + 'p'),
          code: focus.primary || '',
          name: {text: '新的课后实践', src: 'ai'},
          task: {text: '（填写任务说明）', src: 'ai'},
          frequency: {text: '', src: 'ai'},
          platform: '无',
          evidence: {text: '（填写预期证据）', src: 'ai'}
        });
        saveDoc(true);
        return;
      }
      var activityIndex = parseInt(button.getAttribute('data-a'), 10);
      if (op === 'up' || op === 'down') {
        var acts = session.activities || [];
        var target = op === 'up' ? activityIndex - 1 : activityIndex + 1;
        if (target < 0 || target >= acts.length) return;
        if (acts[activityIndex].block_review || acts[target].block_review) return;
        var swap = acts[target];
        acts[target] = acts[activityIndex];
        acts[activityIndex] = swap;
        saveDoc(true);
        return;
      }
      if (op === 'del-activity') {
        var rows = session.activities || [];
        if (rows.length <= 1 || rows[activityIndex].block_review) return;
        rows.splice(activityIndex, 1);
        saveDoc(true);
        return;
      }
      if (op === 'del-practice') {
        var list = session.practice || [];
        var pIndex = parseInt(button.getAttribute('data-p'), 10);
        if (list.length <= 1) return;
        list.splice(pIndex, 1);
        saveDoc(true);
      }
    });
  });

  var regenSection = null;
  document.querySelectorAll('[data-regen]').forEach(function (button) {
    button.addEventListener('click', function () {
      regenSection = button.getAttribute('data-regen');
      var title = document.getElementById('regenH');
      if (title) title.textContent = regenSection === 'overview' ? '重新生成总体目标' : '重新生成本节';
      openDialog('regenDlg', button);
    });
  });

  var regenOk = document.getElementById('regenOk');
  if (regenOk) {
    regenOk.addEventListener('click', function () {
      if (!regenSection) return;
      regenOk.disabled = true;
      startJob(API + '/regenerate', function () { location.reload(); }, function () {
        regenOk.disabled = false;
      }, {section: regenSection});
    });
  }

  /* --------------------------------------------------------- 核对 / 批准 */
  function renderChecks() {
    var list = document.getElementById('checkList');
    var count = document.getElementById('checkCount');
    var review = (S.checks || []).filter(function (item) { return item.level === 'review'; });
    if (count) count.textContent = review.length;
    var warn = document.getElementById('approveWarn');
    if (warn) warn.hidden = review.length === 0;
    var title = document.getElementById('approveH');
    if (title) title.textContent = review.length ? '还有 ' + review.length + ' 处需要核对' : '批准内部版';
    if (!list) return;
    list.innerHTML = '';
    if (!review.length) {
      var ok = document.createElement('p');
      ok.className = 'okline';
      ok.id = 'checkEmpty';
      ok.textContent = '没有需要核对的地方。';
      list.appendChild(ok);
      return;
    }
    review.forEach(function (item, index) {
      var button = document.createElement('button');
      button.className = 'chk';
      button.setAttribute('data-go', (item.path || []).join('.'));
      var n = document.createElement('span');
      n.className = 'n';
      n.textContent = index + 1;
      var wrap = document.createElement('span');
      var b = document.createElement('b');
      b.textContent = item.label || '需要核对';
      var small = document.createElement('small');
      small.textContent = item.text || '';
      wrap.appendChild(b);
      wrap.appendChild(small);
      button.appendChild(n);
      button.appendChild(wrap);
      list.appendChild(button);
    });
    bindGo();
  }

  function flashField(path) {
    if (!path) { toast('这条提示没有对应的位置'); return; }
    var field = document.querySelector('#doc [data-path="' + path + '"]');
    if (!field) {
      field = document.querySelector('#doc [data-path^="' + path + '"]');
    }
    if (!field) { toast('这一处可能在文档其他地方，请手动查找'); return; }
    field.scrollIntoView({behavior: 'smooth', block: 'center'});
    field.classList.remove('flash');
    void field.offsetWidth;
    field.classList.add('flash');
    if (field.focus) field.focus();
  }

  function bindGo() {
    document.querySelectorAll('#doc [data-go], #checkList [data-go]').forEach(function (button) {
      button.onclick = function () { flashField(button.getAttribute('data-go')); };
    });
  }
  bindGo();
  renderChecks();

  function dialog(id) { return document.getElementById(id); }

  /* 对话框：打开时把焦点放到主按钮，关闭时还给打开的按钮，Esc 等同于 × */
  var dialogOpener = {};

  function openDialog(id, opener) {
    var box = dialog(id);
    if (!box) return null;
    dialogOpener[id] = opener || document.activeElement;
    box.hidden = false;
    var target = box.querySelector('.df .btn.p') || box.querySelector('.df button')
      || box.querySelector('button');
    if (target) target.focus();
    return box;
  }

  function closeDialog(id) {
    var box = dialog(id);
    if (!box || box.hidden) return;
    box.hidden = true;
    var back = dialogOpener[id];
    dialogOpener[id] = null;
    if (back && document.contains(back) && !back.disabled) back.focus();
  }

  function closeOnBackdrop(box) {
    if (!box) return;
    box.addEventListener('click', function (event) {
      if (event.target === box || event.target.closest('[data-close]')) closeDialog(box.id);
    });
  }
  ['approveDlg', 'reopenDlg', 'regenDlg', 'verDlg', 'parentConfirmDlg', 'parentRegenDlg'].forEach(function (id) { closeOnBackdrop(dialog(id)); });

  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') return;
    var open = document.querySelector('.dlg[role="dialog"]:not([hidden])');
    if (!open) return;
    event.preventDefault();
    closeDialog(open.id);
  });

  var approveBtn = document.getElementById('approveBtn');
  if (approveBtn) {
    approveBtn.addEventListener('click', function () {
      renderChecks();
      openDialog('approveDlg', approveBtn);
    });
  }

  var approveOk = document.getElementById('approveOk');
  if (approveOk) {
    approveOk.addEventListener('click', function () {
      approveOk.disabled = true;
      clearTimeout(S.docTimer);
      var pending = S.doc && S.step2 ? saveDoc(false) : Promise.resolve();
      pending.then(function () {
        return request('POST', API + '/approve', {});
      }).then(function () {
        location.reload();
      }).catch(function (err) {
        approveOk.disabled = false;
        toast(err.message);
      });
    });
  }

  var reopenBtn = document.getElementById('reopenBtn');
  if (reopenBtn) {
    reopenBtn.addEventListener('click', function () { openDialog('reopenDlg', reopenBtn); });
  }

  var reopenOk = document.getElementById('reopenOk');
  if (reopenOk) {
    reopenOk.addEventListener('click', function () {
      reopenOk.disabled = true;
      request('POST', API + '/reopen', {}).then(function () {
        location.reload();
      }).catch(function (err) {
        reopenOk.disabled = false;
        toast(err.message);
      });
    });
  }

  var verBtn = document.getElementById('verBtn');
  if (verBtn) {
    verBtn.addEventListener('click', function () {
      openDialog('verDlg', verBtn);
      var list = document.getElementById('verList');
      list.innerHTML = '<p class="hint">正在读取…</p>';
      request('GET', API + '/versions').then(function (data) {
        var rows = data.versions || [];
        list.innerHTML = '';
        if (!rows.length) { list.innerHTML = '<p class="hint">还没有版本。</p>'; return; }
        rows.slice().reverse().forEach(function (row) {
          var node = document.createElement('div');
          node.className = 'vrow';
          var part = document.createElement('span');
          part.className = 'part';
          part.textContent = row.part === 'parent' ? '家长版' : '内部版';
          var main = document.createElement('span');
          var b = document.createElement('b');
          b.textContent = '第 ' + row.n + ' 版';
          var small = document.createElement('small');
          small.textContent = ' · ' + dateLabel(row.created_at) + (row.created_by_name ? ' · ' + row.created_by_name : '') + (row.kind === 'ai_draft' ? ' · AI 初稿' : '');
          main.appendChild(b);
          main.appendChild(small);
          var tag = document.createElement('small');
          tag.textContent = row.kind === 'ai_draft' ? 'AI 初稿' : row.kind === 'regen' ? '重新生成' : '导师修改';
          node.appendChild(part);
          node.appendChild(main);
          node.appendChild(tag);
          list.appendChild(node);
        });
      }).catch(function (err) {
        list.innerHTML = '<p class="hint">' + err.message + '</p>';
      });
    });
  }

  /* --------------------------------------------------------- ③ 家长版 */
  var parentDocEl = document.getElementById('parentDoc');
  var parentConfirmBtn = document.getElementById('parentConfirmBtn');
  var parentExportBtn = document.getElementById('parentExportBtn');
  var fitFrame = document.getElementById('ppFrame');
  var fitSeq = 0;

  function parentPrintUrl() { return '/m1/plans/' + CFG.planId + '/parent/print'; }

  function parentStatusLabel(status) {
    var labels = {draft: '草稿 · 待确认', confirmed: '已确认', exported: '已导出',
                  generating: '生成中', none: '—'};
    return labels[status] || status || '—';
  }

  function parentSetStatus(status) {
    S.parentStatus = status;
    var chip = document.getElementById('parentStatusChip');
    if (chip) chip.textContent = parentStatusLabel(status);
  }

  function setParentSave(state, text) {
    var el = document.getElementById('parentSaveState');
    if (!el) return;
    el.className = 'saved' + (state ? ' ' + state : '');
    el.textContent = text || (state === 'busy' ? '保存中…' : state === 'err' ? '保存失败' : '已保存 · ' + clock());
  }

  function updateParentActions() {
    if (parentConfirmBtn) {
      parentConfirmBtn.disabled = !S.parentEditable || S.parentStatus !== 'draft'
        || S.parentStale || (S.parentBlocking || []).length > 0;
    }
    if (parentExportBtn) {
      parentExportBtn.disabled = !S.parentEditable
        || ['confirmed', 'exported'].indexOf(S.parentStatus) < 0
        || S.parentStale || (S.parentBlocking || []).length > 0 || S.parentFits === false;
    }
    var warn = document.getElementById('parentFitWarn');
    if (warn) {
      if (S.parentFits === false) {
        warn.hidden = false;
        warn.textContent = S.parentFitText || '超过两页，请缩短内容。';
      } else {
        warn.hidden = true;
        warn.textContent = '';
      }
    }
    var summary = document.getElementById('parentBlockSummary');
    if (summary) {
      var rows = S.parentBlocking || [];
      if (rows.length) {
        summary.hidden = false;
        summary.textContent = rows.length + ' 项待处理 · 先处理：'
          + (rows[0].label || '需要处理');
      } else {
        summary.hidden = true;
        summary.textContent = '';
      }
    }
  }

  function renderParentChecks() {
    var host = document.getElementById('ppChecks');
    var count = document.getElementById('ppCheckCount');
    if (!host) return;
    var rows = S.parentBlocking || [];
    if (count) count.textContent = rows.length;
    host.innerHTML = '';
    if (!rows.length) {
      var ok = document.createElement('p');
      ok.className = 'okline';
      ok.id = 'ppCheckEmpty';
      ok.textContent = '没有需要处理的地方。';
      host.appendChild(ok);
      updateParentActions();
      return;
    }
    rows.forEach(function (item, index) {
      var path = item.path || [];
      var button = document.createElement('button');
      button.className = 'chk';
      button.setAttribute('data-pp-go', path.join('.'));
      var n = document.createElement('span');
      n.className = 'n';
      n.textContent = index + 1;
      var wrap = document.createElement('span');
      var b = document.createElement('b');
      b.textContent = item.label || '需要处理';
      var small = document.createElement('small');
      small.textContent = item.text || '';
      wrap.appendChild(b);
      wrap.appendChild(small);
      button.appendChild(n);
      button.appendChild(wrap);
      button.addEventListener('click', function () { parentJump(path.join('.')); });
      host.appendChild(button);
      if (path[0] === 'family_seen') {
        var seen = document.createElement('button');
        seen.className = 'btn s g';
        seen.textContent = '已看过';
        seen.addEventListener('click', function () { markFamilySeen(path[1]); });
        host.appendChild(seen);
      }
    });
    updateParentActions();
  }

  function flashParentNode(node) {
    if (!node) { toast('这一处可能在文档其他地方，请手动查找'); return; }
    node.scrollIntoView({behavior: 'smooth', block: 'center'});
    node.classList.remove('flash');
    void node.offsetWidth;
    node.classList.add('flash');
    if (node.focus) node.focus();
  }

  function parentJump(path) {
    if (!path) { toast('这条提示没有对应的位置'); return; }
    if (path.indexOf('family_seen.') === 0) {
      flashParentNode(document.querySelector('[data-family="' + path.split('.')[1] + '"]'));
      return;
    }
    if (path === 'practice' || path.indexOf('practice.') === 0) {
      var picks = document.getElementById('ppPicks');
      if (picks) picks.scrollIntoView({behavior: 'smooth', block: 'center'});
      return;
    }
    var field = document.querySelector('#parentDoc [data-ppath="' + path + '"]')
      || document.querySelector('#parentDoc [data-ppath^="' + path + '"]');
    flashParentNode(field);
  }

  function saveParent(reload) {
    if (!S.parentEditable || !S.parentDoc) return Promise.resolve();
    setParentSave('busy');
    var before = S.parentStatus;
    return queue(function () {
      return request('PUT', API + '/parent', {rev: S.rev, doc: S.parentDoc}).then(function (data) {
        S.rev = data.rev;
        S.parentBlocking = data.blocking || [];
        S.parentStale = !!data.stale;
        var status = data.plan ? data.plan.parent_status : S.parentStatus;
        parentSetStatus(status);
        renderParentChecks();
        setParentSave('ok');
        if (['confirmed', 'exported'].indexOf(before) >= 0 && status === 'draft') {
          toast('已改为草稿，需要重新确认');
        }
        if (reload) location.reload();
        return data;
      });
    }).catch(function (err) {
      setParentSave('err');
      toast(err.message);
      if (reload) setTimeout(function () { location.reload(); }, 900);
      throw err;
    });
  }

  function markFamilySeen(index) {
    if (!S.parentEditable || !S.parentDoc) return;
    var seen = S.parentDoc.family_seen || (S.parentDoc.family_seen = [false, false]);
    seen[index] = true;
    var badge = document.querySelector('[data-family-ai="' + index + '"]');
    if (badge) badge.remove();
    saveParent().catch(function () {});
  }

  function measureParentFits() {
    return new Promise(function (resolve) {
      if (!fitFrame) { resolve({fits: true}); return; }
      var seq = ++fitSeq;
      fitFrame.onload = function () {
        if (seq !== fitSeq) return;
        var result = {fits: true};
        try {
          var doc = fitFrame.contentDocument;
          result = fitFrame.contentWindow.M1ParentFit.measure(doc.getElementById('ppPages'));
        } catch (err) { /* 量不到就按能放下来处理 */ }
        resolve(result);
      };
      fitFrame.src = parentPrintUrl() + '?measure=1&t=' + Date.now();
    });
  }

  function refreshParentFit() {
    if (!fitFrame || !S.parentDoc) return Promise.resolve();
    return measureParentFits().then(function (result) {
      S.parentFits = result.fits;
      S.parentFitText = result.fits ? ''
        : '第 ' + result.overflowPage + ' 页超出：' + (result.section || '页面内容');
      updateParentActions();
      return result;
    });
  }

  if (parentDocEl && S.parentEditable) {
    parentDocEl.querySelectorAll('[data-ppath]').forEach(function (field) {
      field.addEventListener('input', function () {
        var path = field.getAttribute('data-ppath');
        set(S.parentDoc, path, {text: field.textContent || '', src: 'edited'});
        var family = field.getAttribute('data-family');
        if (family !== null) {
          var seen = S.parentDoc.family_seen || (S.parentDoc.family_seen = [false, false]);
          var fi = parseInt(family, 10);
          if (seen[fi] !== true) {
            seen[fi] = true;
            var badge = document.querySelector('[data-family-ai="' + family + '"]');
            if (badge) badge.remove();
          }
        }
        clearTimeout(S.parentTimer);
        S.parentTimer = setTimeout(function () { saveParent().catch(function () {}); }, 700);
      });
    });
  }

  document.querySelectorAll('[data-pp-pick]').forEach(function (box) {
    box.addEventListener('change', function () {
      if (!S.parentEditable || !S.parentDoc) return;
      var ref = box.getAttribute('data-pp-pick');
      var picks = (S.parentDoc.practice || []).slice();
      if (box.checked) {
        if (picks.indexOf(ref) < 0) picks.push(ref);
        if (picks.length > 2) {
          box.checked = false;
          toast('最多选 2 项课后实践');
          return;
        }
      } else {
        picks = picks.filter(function (row) { return row !== ref; });
      }
      S.parentDoc.practice = picks;
      clearTimeout(S.parentTimer);
      saveParent(true).catch(function () {});
    });
  });

  var ppAddReview = document.getElementById('ppAddReview');
  if (ppAddReview) {
    ppAddReview.addEventListener('click', function () {
      if (!S.parentEditable || !S.parentDoc) return;
      var rows = S.parentDoc.review || (S.parentDoc.review = []);
      if (rows.length >= 4) { toast('最多 4 项成长观察'); return; }
      rows.push({label: {text: '新的观察', src: 'edited'},
                 text: {text: '', src: 'edited'}});
      saveParent(true).catch(function () {});
    });
  }

  document.querySelectorAll('[data-pp-del-review]').forEach(function (button) {
    button.addEventListener('click', function () {
      if (!S.parentEditable || !S.parentDoc) return;
      var rows = S.parentDoc.review || [];
      if (rows.length <= 2) { toast('至少保留 2 项成长观察'); return; }
      rows.splice(parseInt(button.getAttribute('data-pp-del-review'), 10), 1);
      saveParent(true).catch(function () {});
    });
  });

  function startParentJob(button) {
    if (button) button.disabled = true;
    toast('家长版生成已开始，完成后会自动刷新');
    startJob(API + '/parent/generate', function () { location.reload(); }, function () {
      if (button) button.disabled = false;
    });
  }

  var parentGenBtn = document.getElementById('parentGenBtn');
  if (parentGenBtn) {
    parentGenBtn.addEventListener('click', function () { startParentJob(parentGenBtn); });
  }

  ['parentRegenBtn', 'parentRegenBtn2'].forEach(function (id) {
    var button = document.getElementById(id);
    if (button) button.addEventListener('click', function () { openDialog('parentRegenDlg', button); });
  });

  var parentRegenOk = document.getElementById('parentRegenOk');
  if (parentRegenOk) {
    parentRegenOk.addEventListener('click', function () {
      parentRegenOk.disabled = true;
      startParentJob(parentRegenOk);
    });
  }

  if (parentConfirmBtn) {
    parentConfirmBtn.addEventListener('click', function () {
      openDialog('parentConfirmDlg', parentConfirmBtn);
    });
  }

  var parentConfirmOk = document.getElementById('parentConfirmOk');
  if (parentConfirmOk) {
    parentConfirmOk.addEventListener('click', function () {
      parentConfirmOk.disabled = true;
      clearTimeout(S.parentTimer);
      var pending = S.parentEditable && S.parentDoc ? saveParent(false) : Promise.resolve();
      pending.then(function () {
        return request('POST', API + '/parent/confirm', {});
      }).then(function () {
        location.reload();
      }).catch(function (err) {
        parentConfirmOk.disabled = false;
        if (err.payload && err.payload.blocking) {
          S.parentBlocking = err.payload.blocking;
          renderParentChecks();
        }
        toast(err.message);
      });
    });
  }

  if (parentExportBtn) {
    parentExportBtn.addEventListener('click', function () {
      parentExportBtn.disabled = true;
      measureParentFits().then(function (result) {
        S.parentFits = result.fits;
        S.parentFitText = result.fits ? ''
          : '第 ' + result.overflowPage + ' 页超出：' + (result.section || '页面内容');
        updateParentActions();
        if (!result.fits) {
          toast(S.parentFitText + '，请先缩短');
          return null;
        }
        return request('POST', API + '/parent/export', {fits: true}).then(function (data) {
          parentSetStatus((data.plan || {}).parent_status || 'exported');
          window.open(parentPrintUrl() + '?print=1', '_blank');
          location.reload();
        });
      }).catch(function (err) {
        toast(err.message === '请求失败' ? '导出失败，请重试' : err.message);
        updateParentActions();
      });
    });
  }

  updateParentActions();
  renderParentChecks();
})();
