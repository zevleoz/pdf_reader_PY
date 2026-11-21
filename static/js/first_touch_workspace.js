window.ftWorkspace = function (ctx) {
  var CAT_LABELS = { subject: '学科', interest: '课外兴趣', social: '社会话题' };
  var CAT_ORDER = ['subject', 'interest', 'social'];
  var SUBJECT_WORDS = ['数学', '物理', '化学', '生物', '语文', '英语', '历史', '地理', '政治', '编程', '计算机', '经济'];
  var SOCIAL_WORDS = ['环保', '气候', '公益', '社会', '新闻', '政策', '心理', 'AI', '人工智能'];
  var LIKE_LABELS = ['不喜欢', '一般', '喜欢', '非常喜欢'];
  var GOOD_LABELS = ['不擅长', '一般', '擅长', '非常擅长'];
  var FIT_LABELS = {
    observation_research: '观察 / 研究',
    design_making: '设计 / 制作',
    data_business: '数据 / 商业',
    user_research_product: '用户研究 / 产品',
    debate_policy_communication: '辩论 / 政策 / 传播'
  };

  function uuid() {
    if (window.crypto && window.crypto.randomUUID) { return window.crypto.randomUUID(); }
    return 'i' + Date.now() + '-' + Math.random().toString(16).slice(2);
  }
  function pad(value) { return String(value).padStart(2, '0'); }

  return {
    sid: ctx.sid,
    sessionId: ctx.sessionId || null,
    code: ctx.code || '',
    name: ctx.name || '',
    grade: ctx.grade || '',
    school: ctx.school || '',
    advisorName: ctx.advisorName || '',
    canWrite: !!ctx.canWrite,
    canStart: !!ctx.canStart,
    readOnly: !!ctx.readOnly,
    role: ctx.role || '',

    stepLabels: ['会前 · Y4 速览', '会谈中 · 兴趣记录', '会后 · 整理与报告'],
    likeLabels: LIKE_LABELS,
    goodLabels: GOOD_LABELS,
    step: 0,
    revision: 1,
    status: 'ACTIVE',
    sessionRow: null,
    lastEditor: null,
    lastSavedAt: '',

    loading: true,
    loadError: '',
    createError: '',
    emptySaving: false,

    y4: null,
    interests: [],
    script: { talkingPoints: [], nextSummary: '' },
    analysis: {},
    meetingSourceId: null,
    meetingFileName: '',
    meetingInput: '',
    projectsCurrent: true,
    reportId: null,
    confirmedReport: null,

    saving: false,
    saveFail: false,
    saveQueued: false,
    navPending: null,
    saveTimer: null,
    previewTimer: null,
    saveDebounce: 800,
    interestDirty: false,
    scriptDirty: false,
    scriptPatch: {},
    meetingDirty: false,
    interestSeq: 0,
    scriptSeq: 0,
    meetingSeq: 0,

    conflict: null,
    conflictNotice: '',

    newInterest: '',
    editingId: null,
    nameDraft: '',
    selectedId: null,
    undo: null,
    undoSeconds: 5,
    undoTimer: null,
    undoInterval: null,

    timerStarted: false,
    timerStart: 0,
    timerId: null,
    elapsed: '00:00',

    talkBusy: false,
    talkError: '',

    transcriptPaste: '',
    uploadBusy: false,
    uploadError: '',
    analyzing: false,
    analyzeError: '',
    suggestionsError: '',
    reviewBusy: false,

    summaryBusy: false,
    summaryError: '',

    projectsBusy: false,
    projectsError: '',

    previewBusy: false,
    previewLoaded: false,
    previewError: '',
    missing: [],
    previewDraft: null,

    confirmBusy: false,
    confirmedError: '',
    editedAfterConfirm: false,

    candidates: [],
    decisionMap: {},
    newIds: {},

    drawerOpen: false,
    suggestedQuestions: ['接下来可以追问什么？', '哪些兴趣证据还不够？'],
    chat: { loading: false, sending: false, question: '', turns: [], history: [], chatId: null, controller: null, error: '' },

    init: function () {
      this.meetingInput = this.defaultMeetingInput();
      this.lastSavedAt = this.nowHM();
      this._beforeUnload = (event) => {
        if (!this.hasPendingSave()) { return; }
        event.preventDefault();
        event.returnValue = '';
      };
      window.addEventListener('beforeunload', this._beforeUnload);
      if (this.sessionId) {
        this.loadSession();
      } else if (this.canWrite && this.canStart) {
        this.createSession();
      } else {
        this.loading = false;
      }
    },
    destroy: function () {
      if (this._beforeUnload) { window.removeEventListener('beforeunload', this._beforeUnload); }
      if (this.timerId) { clearInterval(this.timerId); }
      if (this.saveTimer) { clearTimeout(this.saveTimer); }
      if (this.undoTimer) { clearTimeout(this.undoTimer); }
    },

    /* ---------- 基础 ---------- */
    request: async function (path, options) {
      options = options || {};
      options.credentials = 'same-origin';
      var response = await fetch(path, options);
      var data = {};
      try { data = await response.json(); } catch (error) { data = {}; }
      if (!response.ok || data.ok === false) {
        var failure = new Error(data.error || ('HTTP ' + response.status));
        failure.status = response.status;
        if (Array.isArray(data.missing)) { failure.missing = data.missing; }
        throw failure;
      }
      return data;
    },
    nowHM: function () {
      var parts = this.shanghaiParts(new Date());
      return parts.time;
    },
    fmtHM: function (value) {
      var parts = this.shanghaiParts(value);
      return parts ? parts.time : '';
    },
    fmtEditor: function (value) {
      var parts = this.shanghaiParts(value);
      return parts ? (parts.date + ' ' + parts.time) : '';
    },
    fmtDate: function (value) {
      if (!value) { return '—'; }
      return String(value).slice(0, 10);
    },
    fmtDuration: function (seconds) {
      return pad(Math.floor(seconds / 60)) + ':' + pad(seconds % 60);
    },
    normalizeIso: function (value) {
      var text = String(value || '').trim();
      if (!text || !/\d{2}:\d{2}/.test(text)) { return text; }
      if (/(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(text)) { return text; }
      return text + 'Z';
    },
    shanghaiParts: function (value) {
      var date = value instanceof Date ? value : new Date(this.normalizeIso(value));
      if (Number.isNaN(date.getTime())) { return null; }
      var parts = new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit',
        day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false
      }).formatToParts(date);
      var map = {};
      parts.forEach(function (part) { map[part.type] = part.value; });
      if (!map.year || !map.month || !map.day) { return null; }
      return {
        date: map.year + '-' + map.month + '-' + map.day,
        time: (map.hour === '24' ? '00' : map.hour) + ':' + map.minute
      };
    },
    floorTime: function (time) {
      var parts = String(time || '').split(':').map(Number);
      if (parts.length < 2 || !Number.isFinite(parts[0]) || !Number.isFinite(parts[1])) { return ''; }
      return pad(parts[0]) + ':' + pad(Math.floor(parts[1] / 15) * 15);
    },
    toMeetingInput: function (value) {
      var parts = this.shanghaiParts(value);
      if (!parts) { return ''; }
      return parts.date + 'T' + (this.floorTime(parts.time) || parts.time);
    },
    defaultMeetingInput: function () {
      var parts = this.shanghaiParts(new Date());
      return parts.date + 'T' + this.floorTime(parts.time);
    },
    delay: function (ms, signal) {
      return new Promise((resolve, reject) => {
        var timer = setTimeout(resolve, ms);
        if (!signal) { return; }
        signal.addEventListener('abort', function () {
          clearTimeout(timer);
          var error = new Error('已停止');
          error.name = 'AbortError';
          reject(error);
        }, { once: true });
      });
    },

    /* ---------- 加载 / 会话 ---------- */
    createSession: async function () {
      if (!this.canWrite || !this.canStart) { return; }
      this.loading = true;
      this.createError = '';
      this.emptySaving = true;
      try {
        var data = await this.request('/api/v2/students/' + this.sid + '/copilot/sessions', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}'
        });
        this.sessionId = data.session.id;
        await this.loadSession();
      } catch (error) {
        this.createError = error.message || '无法创建会谈';
        this.loading = false;
      } finally {
        this.emptySaving = false;
      }
    },
    loadSession: async function () {
      if (!this.sessionId) { this.loading = false; return; }
      this.loading = true;
      this.loadError = '';
      try {
        var data = await this.request('/api/v2/copilot/sessions/' + this.sessionId);
        this.applySessionData(data);
      } catch (error) {
        this.loadError = error.message || '会谈加载失败';
      } finally {
        this.loading = false;
      }
    },
    applySessionData: function (data) {
      var session = (data && data.session) || {};
      var supplements = session.supplements || [];
      var supplement = supplements[0] || null;
      var script = Object.assign({ talkingPoints: [], nextSummary: '' }, session.script || {});
      if (!Array.isArray(script.talkingPoints)) { script.talkingPoints = []; }
      if (typeof script.nextSummary !== 'string') { script.nextSummary = ''; }

      this.sessionRow = session;
      this.sessionId = session.id || this.sessionId;
      this.revision = typeof session.revision === 'number' ? session.revision : 1;
      this.status = session.status || 'ACTIVE';
      this.step = [0, 1, 2].indexOf(session.phase) >= 0 ? session.phase : 0;
      this.interests = (session.interests || []).map(function (item) {
        return Object.assign({}, item, {
          preferenceScore: item.preferenceScore === undefined ? null : item.preferenceScore,
          competenceScore: item.competenceScore === undefined ? null : item.competenceScore,
          note: item.note || '',
          specialFocus: !!item.specialFocus
        });
      });
      this.script = script;
      this.meetingSourceId = session.meeting_source_id || null;
      this.meetingInput = this.toMeetingInput(session.meeting_at) || this.defaultMeetingInput();
      this.y4 = data.y4Snapshot || script.y4Snapshot || null;
      this.analysis = (supplement && supplement.analysis) || {};
      this.projectsCurrent = data.projectsCurrent !== false;
      this.reportId = data.reportId || null;
      this.confirmedReport = data.report || null;
      this.lastEditor = data.lastEditor || null;
      var names = data.sourceFileNames || {};
      this.meetingFileName = names[String(this.meetingSourceId)] || (this.meetingSourceId ? '会议文字稿已上传' : '');
      this.lastSavedAt = this.fmtHM(session.updated_at) || this.nowHM();
      this.resetDirtyState();
      this.decisionMap = {};
      this.newIds = {};
      this.rebuildCandidates();
      this.editedAfterConfirm = false;
      if (this.step === 1) { this.startTimer(); }
      if (this.step === 2 && this.canWrite) { this.refreshPreview(); }
    },
    resetDirtyState: function () {
      this.interestDirty = false;
      this.scriptDirty = false;
      this.scriptPatch = {};
      this.meetingDirty = false;
      this.saveFail = false;
      this.navPending = null;
      if (this.saveTimer) { clearTimeout(this.saveTimer); }
      this.saveTimer = null;
    },
    loadLatest: async function () {
      if (!this.canWrite) { return; }
      var local = this.serializeInterests();
      try {
        var data = await this.request('/api/v2/copilot/sessions/' + this.sessionId);
        var serverInterests = (data.session && data.session.interests) || [];
        var serverIds = new Set(serverInterests.map(function (item) { return item.id; }));
        var serverLabels = new Set(serverInterests.map(function (item) { return String(item.label || '').trim().toLowerCase(); }));
        var extras = local.filter(function (item) {
          return !serverIds.has(item.id) && !serverLabels.has(String(item.label || '').trim().toLowerCase());
        });
        this.conflict = null;
        this.applySessionData(data);
        if (extras.length) {
          this.interests = this.interests.concat(extras);
          this.interestDirty = true;
          this.conflictNotice = '已载入最新，保留了 ' + extras.length + ' 项本地新增事项；其余以服务器版本为准。';
          this.scheduleSave();
        } else {
          this.conflictNotice = '已载入最新；本地修改已以服务器版本为准。';
        }
      } catch (error) {
        this.conflict = { active: true, error: error.message || '载入失败' };
      }
    },

    /* ---------- 步骤 ---------- */
    goStep: function (target) {
      if (target < 0 || target > 2) { return; }
      this.step = target;
      if (target === 1) {
        this.startTimer();
        this.focusAddInput();
      }
      if (target === 2 && this.canWrite) { this.refreshPreview(); }
      if (this.canWrite && this.sessionId && !this.readOnly) { this.syncPhase(target); }
    },
    focusAddInput: function () {
      this.$nextTick(function () {
        if (this.$refs.addInput) { this.$refs.addInput.focus(); }
      }.bind(this));
    },
    syncPhase: async function (target) {
      if (!this.canWrite || !this.sessionId || this.readOnly) { return; }
      if (this.saving) { this.navPending = target; return; }
      if (this.interestDirty || this.scriptDirty || this.meetingDirty) {
        await this.flushSave();
      }
      if (this.saving) { this.navPending = target; return; }
      try {
        var body = { phase: target, revision: this.revision };
        if (this.meetingDirty && this.meetingInput) { body.meetingAt = this.meetingInput; }
        var data = await this.request('/api/v2/copilot/sessions/' + this.sessionId + '/phase', {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
        });
        this.revision = data.revision;
        if (data.result && data.result.status) { this.status = data.result.status; }
        if (body.meetingAt) { this.meetingDirty = false; }
      } catch (error) {
        if (error.status === 409) { this.beginConflict(); }
      }
    },
    startTimer: function () {
      if (this.timerStarted) { return; }
      this.timerStarted = true;
      this.timerStart = Date.now();
      this.timerId = setInterval(() => {
        this.elapsed = this.fmtDuration(Math.floor((Date.now() - this.timerStart) / 1000));
      }, 1000);
    },

    /* ---------- 保存 ---------- */
    hasPendingSave: function () {
      return this.saving || this.interestDirty || this.scriptDirty || this.meetingDirty
        || Boolean(this.transcriptPaste.trim());
    },
    scheduleSave: function () {
      if (!this.canWrite || !this.sessionId) { return; }
      if (this.saveTimer) { clearTimeout(this.saveTimer); }
      this.saveTimer = setTimeout(() => { this.flushSave(); }, this.saveDebounce);
    },
    markInterestDirty: function () {
      if (this.confirmedReport) { this.editedAfterConfirm = true; }
      this.interestDirty = true;
      this.interestSeq += 1;
      this.scheduleSave();
    },
    markScriptDirty: function (patch) {
      if (this.confirmedReport) { this.editedAfterConfirm = true; }
      this.scriptPatch = Object.assign({}, this.scriptPatch, patch);
      this.scriptDirty = true;
      this.scriptSeq += 1;
      this.scheduleSave();
    },
    flushSave: async function () {
      if (!this.canWrite || !this.sessionId) { return; }
      if (this.saving) { this.saveQueued = true; return; }
      if (this.saveTimer) { clearTimeout(this.saveTimer); }
      this.saveTimer = null;
      this.saving = true;
      this.saveFail = false;
      try {
        while (true) {
          var path = null;
          var body = null;
          var kind = null;
          var interestSeq = this.interestSeq;
          var scriptSeq = this.scriptSeq;
          var meetingSeq = this.meetingSeq;
          if (this.interestDirty) {
            path = '/interest-draft';
            body = { revision: this.revision, interests: this.serializeInterests() };
            kind = 'interests';
          } else if (this.scriptDirty) {
            path = '/phase';
            body = { phase: this.step, revision: this.revision, script: Object.assign({}, this.scriptPatch) };
            if (this.meetingDirty && this.meetingInput) { body.meetingAt = this.meetingInput; }
            kind = 'script';
          } else if (this.meetingDirty && this.meetingInput) {
            path = '/phase';
            body = { phase: this.step, revision: this.revision, meetingAt: this.meetingInput };
            kind = 'meeting';
          } else {
            break;
          }
          var data = await this.request('/api/v2/copilot/sessions/' + this.sessionId + path, {
            method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
          });
          this.revision = data.revision;
          this.lastSavedAt = this.nowHM();
          if (kind === 'interests') {
            // 保存期间又有新改动时保留 dirty，循环会再存一次。
            if (this.interestSeq === interestSeq) { this.interestDirty = false; }
            if (this.projectItems.length) { this.projectsCurrent = false; }
            if (this.step === 2) { this.schedulePreview(); }
          } else if (kind === 'script') {
            if (this.scriptSeq === scriptSeq) {
              this.scriptDirty = false;
              this.scriptPatch = {};
            }
            if (this.meetingSeq === meetingSeq) { this.meetingDirty = false; }
            if (data.result && data.result.status) { this.status = data.result.status; }
            if (this.step === 2) { this.schedulePreview(); }
          } else {
            if (this.meetingSeq === meetingSeq) { this.meetingDirty = false; }
            if (data.result && data.result.status) { this.status = data.result.status; }
          }
        }
        this.saveFail = false;
      } catch (error) {
        if (error.status === 409) { this.beginConflict(); }
        else { this.saveFail = true; }
      } finally {
        this.saving = false;
        if (this.navPending !== null) {
          var target = this.navPending;
          this.navPending = null;
          if (!this.saveFail && !this.conflict) { this.syncPhase(target); }
        } else if (this.saveQueued) {
          this.saveQueued = false;
          this.scheduleSave();
        } else if ((this.interestDirty || this.scriptDirty || this.meetingDirty) && !this.saveFail && !this.conflict) {
          this.scheduleSave();
        }
      }
    },
    beginConflict: function () {
      this.conflict = { active: true };
      this.conflictNotice = '';
      this.saveFail = false;
    },
    serializeInterests: function () {
      return this.interests.map(function (item) {
        var row = Object.assign({}, item);
        row.label = String(row.label || '').trim();
        row.note = row.note || '';
        row.preferenceScore = row.preferenceScore === undefined ? null : row.preferenceScore;
        row.competenceScore = row.competenceScore === undefined ? null : row.competenceScore;
        row.specialFocus = !!row.specialFocus;
        if (typeof row.evidence !== 'string') { row.evidence = row.evidence || ''; }
        return row;
      });
    },

    /* ---------- 会谈时间 ---------- */
    meetingChanged: function () {
      if (!this.canWrite || !this.meetingInput) { this.meetingDirty = false; return; }
      if (this.confirmedReport) { this.editedAfterConfirm = true; }
      this.meetingDirty = true;
      this.meetingSeq += 1;
      this.scheduleSave();
    },

    /* ---------- ① 会谈提示 ---------- */
    setTalkingPoint: function (index, value) {
      this.script.talkingPoints[index] = value;
      this.markScriptDirty({ talkingPoints: this.script.talkingPoints.slice(0, 5) });
    },
    addTalkingPoint: function () {
      if (this.script.talkingPoints.length >= 5) { return; }
      this.script.talkingPoints.push('');
      this.markScriptDirty({ talkingPoints: this.script.talkingPoints.slice(0, 5) });
      this.$nextTick(function () {
        var inputs = document.querySelectorAll('.ft-tip-row .ft-input');
        if (inputs.length) { inputs[inputs.length - 1].focus(); }
      });
    },
    removeTalkingPoint: function (index) {
      this.script.talkingPoints.splice(index, 1);
      this.markScriptDirty({ talkingPoints: this.script.talkingPoints.slice(0, 5) });
    },
    generateTalkingPoints: async function () {
      if (!this.canWrite || this.talkBusy || !this.sessionId) { return; }
      this.talkBusy = true;
      this.talkError = '';
      try {
        var job = await this.dispatch('/talking-points');
        var result = job.result || {};
        this.revision = result.revision || job.revision || this.revision;
        this.script.talkingPoints = (result.points || []).slice(0, 5);
        this.scriptDirty = false;
        this.scriptPatch = {};
        this.lastSavedAt = this.nowHM();
        v2Toast('会谈提示已生成', 'success');
      } catch (error) {
        if (error.status === 409 || error.stale) { this.beginConflict(); }
        this.talkError = error.message || '生成失败';
      } finally {
        this.talkBusy = false;
      }
    },

    /* ---------- ② 兴趣记录 ---------- */
    guessCategory: function (label) {
      var name = String(label || '');
      if (SUBJECT_WORDS.some(function (word) { return name.indexOf(word) >= 0; })) { return 'subject'; }
      if (SOCIAL_WORDS.some(function (word) { return name.indexOf(word) >= 0; })) { return 'social'; }
      return 'interest';
    },
    catLabel: function (type) { return CAT_LABELS[type] || CAT_LABELS.interest; },
    labelKey: function (value) { return String(value || '').trim().toLowerCase(); },
    hasLabel: function (label, skipId) {
      var key = this.labelKey(label);
      return this.interests.some(function (item) {
        return item.id !== skipId && String(item.label || '').trim().toLowerCase() === key;
      });
    },
    addInterest: function () {
      if (!this.canWrite) { return; }
      var name = String(this.newInterest || '').trim();
      if (!name) { return; }
      if (name.length > 80) { v2Toast('兴趣名称不能超过 80 字', 'error'); return; }
      if (this.hasLabel(name, null)) { v2Toast('已存在同名兴趣', 'error'); return; }
      this.interests.push({
        id: uuid(), label: name, topicType: this.guessCategory(name),
        preferenceScore: null, competenceScore: null,
        note: '', evidence: '', specialFocus: false
      });
      this.newInterest = '';
      this.markInterestDirty();
      this.$nextTick(function () {
        if (this.$refs.addInput) { this.$refs.addInput.focus(); }
      }.bind(this));
    },
    addSuggestion: function (topic) {
      if (this.readOnly) { return; }
      this.newInterest = topic;
      this.addInterest();
      this.$nextTick(function () {
        if (this.$refs.addInput) { this.$refs.addInput.focus(); }
      }.bind(this));
    },
    get remainingSuggestions() {
      var snapshot = this.snapshot;
      if (!snapshot || !Array.isArray(snapshot.topicSuggestions)) { return []; }
      var self = this;
      return snapshot.topicSuggestions.filter(function (topic) { return !self.hasLabel(topic, null); });
    },
    beginRename: function (row) {
      if (!this.canWrite) { return; }
      this.editingId = row.id;
      this.nameDraft = row.label;
      this.$nextTick(function () {
        var input = document.querySelector('.ft-name-input');
        if (input) { input.focus(); input.select(); }
      });
    },
    commitRename: function (row) {
      if (this.editingId !== row.id) { return; }
      var next = String(this.nameDraft || '').trim();
      if (!next) { this.cancelRename(); return; }
      if (next.length > 80) { v2Toast('兴趣名称不能超过 80 字', 'error'); this.cancelRename(); return; }
      if (this.hasLabel(next, row.id)) { v2Toast('已存在同名兴趣', 'error'); this.cancelRename(); return; }
      row.label = next;
      this.editingId = null;
      this.nameDraft = '';
      this.markInterestDirty();
    },
    cancelRename: function () {
      this.editingId = null;
      this.nameDraft = '';
    },
    cycleCategory: function (row) {
      if (!this.canWrite) { return; }
      var index = CAT_ORDER.indexOf(row.topicType);
      row.topicType = CAT_ORDER[(index + 1) % CAT_ORDER.length];
      this.markInterestDirty();
    },
    toggleStar: function (row) {
      if (!this.canWrite) { return; }
      var next = !row.specialFocus;
      this.interests.forEach(function (item) { item.specialFocus = false; });
      row.specialFocus = next;
      this.markInterestDirty();
    },
    deleteInterest: function (row) {
      if (!this.canWrite) { return; }
      var index = this.interests.findIndex(function (item) { return item.id === row.id; });
      if (index < 0) { return; }
      var removed = this.interests.splice(index, 1)[0];
      if (this.selectedId === removed.id) { this.selectedId = null; }
      if (this.editingId === removed.id) { this.cancelRename(); }
      this.undo = { item: removed, index: index };
      this.undoSeconds = 5;
      if (this.undoTimer) { clearTimeout(this.undoTimer); }
      if (this.undoInterval) { clearInterval(this.undoInterval); }
      this.undoInterval = setInterval(() => {
        this.undoSeconds -= 1;
        if (this.undoSeconds <= 0) {
          clearInterval(this.undoInterval);
          this.undoInterval = null;
          this.undo = null;
        }
      }, 1000);
      this.undoTimer = setTimeout(() => {
        if (this.undoInterval) { clearInterval(this.undoInterval); this.undoInterval = null; }
      }, 5200);
      this.markInterestDirty();
    },
    undoDelete: function () {
      if (!this.undo) { return; }
      var restored = this.undo.item;
      var index = Math.min(this.undo.index, this.interests.length);
      this.interests.splice(index, 0, restored);
      this.undo = null;
      this.undoSeconds = 5;
      if (this.undoInterval) { clearInterval(this.undoInterval); this.undoInterval = null; }
      if (this.undoTimer) { clearTimeout(this.undoTimer); this.undoTimer = null; }
      this.markInterestDirty();
    },
    setScore: function (row, key, value) {
      if (!this.canWrite) { return; }
      row[key] = value;
      this.markInterestDirty();
    },
    setNote: function (row, value) {
      if (!this.canWrite) { return; }
      row.note = value;
      this.markInterestDirty();
    },
    toggleSelect: function (id) {
      this.selectedId = this.selectedId === id ? null : id;
    },
    rowClick: function (event, row) {
      // 双击名称用于重命名；第二下 click 不再切换选中。
      if (event && event.detail > 1) { return; }
      this.toggleSelect(row.id);
    },
    get snapshot() {
      return this.y4 || (this.script && this.script.y4Snapshot) || null;
    },
    get riasecRows() {
      var snapshot = this.snapshot;
      if (!snapshot || !Array.isArray(snapshot.riasec)) { return []; }
      var rows = snapshot.riasec.filter(function (item) { return item && typeof item === 'object'; });
      var scores = rows.map(function (item) {
        return typeof item.score === 'number' ? item.score : -1;
      });
      var max = Math.max.apply(null, scores.concat([1]));
      var sorted = rows.slice().sort(function (a, b) {
        return (typeof b.score === 'number' ? b.score : -1) - (typeof a.score === 'number' ? a.score : -1);
      });
      var topKeys = new Set(sorted.slice(0, 3).map(function (item) { return item.key; }));
      return sorted.map(function (item) {
        var score = typeof item.score === 'number' ? item.score : -1;
        return {
          key: item.key, label: item.label, score: typeof item.score === 'number' ? item.score : null,
          top: topKeys.has(item.key),
          width: score < 0 ? 0 : Math.max(0, Math.min(100, Math.round((score / max) * 100)))
        };
      });
    },
    get scoredInterests() {
      return this.interests.filter(function (item) {
        return item.preferenceScore !== null && item.preferenceScore !== undefined
          && item.competenceScore !== null && item.competenceScore !== undefined;
      });
    },
    get scoredCount() { return this.scoredInterests.length; },
    get pendingScoreCount() {
      return this.interests.filter(function (item) {
        return item.preferenceScore === null || item.preferenceScore === undefined
          || item.competenceScore === null || item.competenceScore === undefined;
      }).length;
    },
    get selectedLabel() {
      var self = this;
      var found = this.interests.find(function (item) { return item.id === self.selectedId; });
      return found ? found.label : '';
    },
    zoneClass: function (like, good) {
      if (like >= 2 && good >= 2) { return 'both'; }
      if (like >= 2) { return 'like'; }
      if (good >= 2) { return 'good'; }
      return '';
    },
    cellItems: function (like, good) {
      return this.scoredInterests.filter(function (item) {
        return item.preferenceScore === like && item.competenceScore === good;
      });
    },
    cellClick: function (like, good) {
      if (!this.canWrite) { return; }
      if (!this.selectedId) { v2Toast('先在左侧点选一项兴趣'); return; }
      var self = this;
      var row = this.interests.find(function (item) { return item.id === self.selectedId; });
      if (!row) { this.selectedId = null; return; }
      row.preferenceScore = like;
      row.competenceScore = good;
      this.selectedId = null;
      this.markInterestDirty();
      v2Toast('「' + row.label + '」喜欢 ' + like + ' · 擅长 ' + good, 'success');
    },

    /* ---------- ③ 会议转写建议 ---------- */
    analysisVersion: function () {
      if (this.analysis && this.analysis.analysisVersion) { return String(this.analysis.analysisVersion); }
      return JSON.stringify((this.analysis && this.analysis.newInterests) || []);
    },
    rebuildCandidates: function () {
      var analysis = this.analysis || {};
      var proposals = Array.isArray(analysis.newInterests) ? analysis.newInterests : [];
      var version = this.analysisVersion();
      var review = (analysis.interestReview && typeof analysis.interestReview === 'object'
        && analysis.interestReview.analysisVersion === version) ? analysis.interestReview : null;
      var bindings = (analysis.interestBindings && typeof analysis.interestBindings === 'object'
        && analysis.interestBindings.analysisVersion === version)
        ? (analysis.interestBindings.items || {}) : {};
      var confirmed = this.interests;
      var represented = new Set();
      var rows = [];
      var self = this;
      proposals.forEach(function (proposal, index) {
        if (!proposal || typeof proposal !== 'object') { return; }
        var rawLabel = typeof proposal.label === 'string' ? proposal.label : '';
        var original = (rawLabel.split(/[（(]/)[0] || '').trim();
        var key = String(index);
        var previous = review ? ((review.items || {})[key] || null) : null;
        var overlay = self.decisionMap[key] || null;
        var boundId = (overlay && overlay.interestId) || (previous && previous.interestId) || bindings[key] || null;
        var existing = boundId ? confirmed.find(function (item) { return item.id === boundId; }) : null;
        if (!existing) {
          existing = confirmed.find(function (item) {
            return self.labelKey(item.label) === self.labelKey(original);
          });
        }
        if (existing) { represented.add(existing.id); }
        var decision = overlay ? overlay.decision : (previous ? previous.decision : null);
        var conflicts = [];
        if (existing && !previous && !overlay) {
          ['preferenceScore', 'competenceScore'].forEach(function (field) {
            if (proposal[field] !== null && proposal[field] !== undefined && proposal[field] !== existing[field]) {
              conflicts.push(field);
            }
          });
        }
        rows.push({
          sourceIndex: index,
          existingId: existing ? existing.id : (boundId || null),
          proposal: proposal,
          label: existing ? existing.label : (original || rawLabel),
          topicType: existing ? existing.topicType : (proposal.topicType || 'interest'),
          preferenceScore: existing ? existing.preferenceScore
            : (proposal.preferenceScore === undefined ? null : proposal.preferenceScore),
          competenceScore: existing ? existing.competenceScore
            : (proposal.competenceScore === undefined ? null : proposal.competenceScore),
          note: existing ? (existing.note || '') : '',
          evidence: (existing && existing.evidence) || proposal.evidence || '',
          conflicts: conflicts,
          decision: decision,
          confirmedPreferenceScore: existing ? existing.preferenceScore : null,
          confirmedCompetenceScore: existing ? existing.competenceScore : null
        });
      });
      confirmed.forEach(function (item) {
        if (represented.has(item.id)) { return; }
        rows.push({
          sourceIndex: null, existingId: item.id, proposal: null,
          label: item.label, topicType: item.topicType,
          preferenceScore: item.preferenceScore, competenceScore: item.competenceScore,
          note: item.note || '', evidence: item.evidence || '',
          conflicts: [], decision: 'keep',
          confirmedPreferenceScore: item.preferenceScore,
          confirmedCompetenceScore: item.competenceScore
        });
      });
      this.candidates = rows;
    },
    get suggestions() {
      return this.candidates.filter(function (item) { return item.sourceIndex !== null; });
    },
    get pendingSuggestionCount() {
      return this.suggestions.filter(function (item) { return !item.decision; }).length;
    },
    conflictRows: function (suggestion) {
      return suggestion.conflicts.map(function (key) {
        var isPreference = key === 'preferenceScore';
        return {
          key: key,
          label: isPreference ? '喜欢' : '擅长',
          current: isPreference ? suggestion.confirmedPreferenceScore : suggestion.confirmedCompetenceScore,
          suggested: isPreference ? suggestion.proposal.preferenceScore : suggestion.proposal.competenceScore
        };
      });
    },
    decisionLabel: function (suggestion) {
      if (!suggestion.decision) { return ''; }
      if (suggestion.decision === 'exclude') { return '已忽略'; }
      if (suggestion.decision === 'keep') { return suggestion.existingId ? '保留我的评分' : '已保留'; }
      if (suggestion.decision === 'edit') { return '已调整评分'; }
      return '已采纳';
    },
    decideSuggestion: function (suggestion, accept) {
      if (!this.canWrite) { return; }
      var key = String(suggestion.sourceIndex);
      var row = suggestion.existingId
        ? this.interests.find(function (item) { return item.id === suggestion.existingId; }, this)
        : null;
      if (!row) {
        row = this.interests.find(function (item) {
          return this.labelKey(item.label) === this.labelKey(suggestion.label);
        }, this);
      }
      if (accept) {
        if (row) {
          this.decisionMap[key] = { decision: 'keep', interestId: row.id };
        } else {
          var id = uuid();
          row = {
            id: id, label: suggestion.label, topicType: suggestion.topicType || 'interest',
            preferenceScore: suggestion.proposal.preferenceScore === undefined ? null : suggestion.proposal.preferenceScore,
            competenceScore: suggestion.proposal.competenceScore === undefined ? null : suggestion.proposal.competenceScore,
            note: '', evidence: suggestion.evidence || '', specialFocus: false
          };
          this.interests.push(row);
          this.newIds[key] = id;
          this.decisionMap[key] = { decision: 'apply', interestId: id };
        }
      } else {
        if (this.newIds[key]) {
          this.interests = this.interests.filter(function (item) { return item.id !== this.newIds[key]; });
          delete this.newIds[key];
        }
        this.decisionMap[key] = { decision: 'exclude', interestId: null };
      }
      if (this.confirmedReport) { this.editedAfterConfirm = true; }
      this.rebuildCandidates();
      this.afterDecision();
    },
    applyConflict: function (suggestion, conflict) {
      if (!this.canWrite) { return; }
      var row = this.interests.find(function (item) { return item.id === suggestion.existingId; }, this);
      if (!row) { return; }
      row[conflict.key] = conflict.suggested;
      var applied = suggestion.conflicts.some(function (key) {
        return row[key] === suggestion.proposal[key];
      }, this);
      this.decisionMap[String(suggestion.sourceIndex)] = {
        decision: applied ? 'edit' : 'keep', interestId: suggestion.existingId
      };
      if (this.confirmedReport) { this.editedAfterConfirm = true; }
      this.rebuildCandidates();
      this.afterDecision();
    },
    keepConflict: function (suggestion, conflict) {
      if (!this.canWrite) { return; }
      var row = this.interests.find(function (item) { return item.id === suggestion.existingId; }, this);
      if (!row) { return; }
      row[conflict.key] = conflict.current;
      var applied = suggestion.conflicts.some(function (key) {
        return row[key] === suggestion.proposal[key];
      }, this);
      this.decisionMap[String(suggestion.sourceIndex)] = {
        decision: applied ? 'edit' : 'keep', interestId: suggestion.existingId
      };
      if (this.confirmedReport) { this.editedAfterConfirm = true; }
      this.rebuildCandidates();
      this.afterDecision();
    },
    afterDecision: function () {
      var pending = this.suggestions.filter(function (item) { return !item.decision; });
      if (!pending.length) { this.saveReview(); }
    },
    saveReview: async function () {
      if (!this.canWrite || this.reviewBusy) { return; }
      var items = {};
      var blocked = false;
      this.candidates.forEach(function (candidate) {
        if (candidate.sourceIndex === null) { return; }
        var key = String(candidate.sourceIndex);
        if (!candidate.decision) { blocked = true; return; }
        var interestId = candidate.existingId;
        if (!interestId && candidate.decision !== 'exclude') {
          interestId = this.newIds[key]
            || ((this.interests.find(function (item) {
              return this.labelKey(item.label) === this.labelKey(candidate.label);
            }, this) || {}).id);
        }
        if (candidate.decision !== 'exclude' && !interestId) { blocked = true; return; }
        items[key] = { interestId: interestId || null, decision: candidate.decision };
      }, this);
      if (blocked) { return; }
      this.reviewBusy = true;
      this.suggestionsError = '';
      var interestSeq = this.interestSeq;
      try {
        var data = await this.request('/api/v2/copilot/sessions/' + this.sessionId + '/phase', {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            phase: 2,
            revision: this.revision,
            interests: this.serializeInterests(),
            interestReview: { analysisVersion: this.analysisVersion(), items: items }
          })
        });
        this.revision = data.revision;
        if (data.result && data.result.savedSupplement) {
          this.analysis = data.result.savedSupplement.analysis || this.analysis;
        }
        if (data.result && data.result.status) { this.status = data.result.status; }
        if (this.interestSeq === interestSeq) { this.interestDirty = false; }
        this.decisionMap = {};
        this.newIds = {};
        this.rebuildCandidates();
        this.lastSavedAt = this.nowHM();
        if (this.step === 2) { this.schedulePreview(); }
        if (this.interestDirty) { this.scheduleSave(); }
      } catch (error) {
        if (error.status === 409) { this.beginConflict(); }
        else { this.suggestionsError = error.message || '建议保存失败'; }
      } finally {
        this.reviewBusy = false;
      }
    },

    /* ---------- ③ 会议转写 ---------- */
    uploadTranscript: function (event) {
      var input = event.target;
      var file = input.files && input.files[0];
      input.value = '';
      return this.saveTranscript(file, false);
    },
    submitPastedTranscript: function () {
      if (!this.transcriptPaste.trim() || !this.canWrite || this.uploadBusy || this.analyzing) { return; }
      var file = new File([this.transcriptPaste], '粘贴的文字稿.txt', { type: 'text/plain' });
      return this.saveTranscript(file, true);
    },
    saveTranscript: async function (file, fromPaste) {
      if (!file || !this.canWrite || this.uploadBusy || this.analyzing) { return; }
      if (!/\.(pdf|docx|txt|md)$/i.test(file.name)) {
        this.uploadError = '仅支持 PDF / DOCX / TXT / MD';
        return;
      }
      this.uploadBusy = true;
      this.uploadError = '';
      this.analyzeError = '';
      try {
        var form = new FormData();
        form.append('file', file);
        form.append('kind', 'MEETING');
        form.append('revision', String(this.revision));
        var data = await this.request('/api/v2/copilot/sessions/' + this.sessionId + '/sources', {
          method: 'POST', body: form
        });
        this.revision = data.revision;
        this.meetingSourceId = (data.result || {}).sourceId || null;
        this.meetingFileName = (data.result || {}).fileName || file.name;
        if (fromPaste) { this.transcriptPaste = ''; }
        this.uploadBusy = false;
        await this.analyzeTranscript();
      } catch (error) {
        if (error.status === 409) { this.beginConflict(); }
        this.uploadError = error.message || '上传失败';
      } finally {
        this.uploadBusy = false;
      }
    },
    analyzeTranscript: async function () {
      if (!this.canWrite || this.analyzing || !this.meetingSourceId) {
        if (!this.meetingSourceId && this.canWrite) { this.analyzeError = '请先上传会议转写'; }
        return;
      }
      this.analyzing = true;
      this.analyzeError = '';
      try {
        var job = await this.dispatch('/supplement');
        var result = job.result || {};
        this.revision = result.revision || job.revision || this.revision;
        this.analysis = result.analysis || this.analysis;
        if (this.projectItems.length) { this.projectsCurrent = false; }
        this.decisionMap = {};
        this.newIds = {};
        this.rebuildCandidates();
        this.lastSavedAt = this.nowHM();
        this.schedulePreview();
      } catch (error) {
        if (error.status === 409 || error.stale) { this.beginConflict(); }
        this.analyzeError = error.message || '分析失败';
      } finally {
        this.analyzing = false;
      }
    },

    /* ---------- ③ 总结 / 项目 / 报告 ---------- */
    setSummary: function (value) {
      if (!this.canWrite) { return; }
      this.script.nextSummary = value;
      this.markScriptDirty({ nextSummary: value });
    },
    generateSummary: async function () {
      if (!this.canWrite || this.summaryBusy) { return; }
      this.summaryBusy = true;
      this.summaryError = '';
      try {
        var job = await this.dispatch('/next-steps');
        var result = job.result || {};
        this.revision = result.revision || job.revision || this.revision;
        var summary = (result.result || {}).summary || '';
        this.script.nextSummary = summary;
        this.scriptDirty = false;
        this.scriptPatch = {};
        if (this.confirmedReport) { this.editedAfterConfirm = true; }
        this.lastSavedAt = this.nowHM();
        this.schedulePreview();
      } catch (error) {
        if (error.status === 409 || error.stale) { this.beginConflict(); }
        this.summaryError = error.message || '起草失败';
      } finally {
        this.summaryBusy = false;
      }
    },
    get projectItems() {
      var batch = this.analysis && this.analysis.projectRecommendations;
      return (batch && Array.isArray(batch.items)) ? batch.items : [];
    },
    get projectsStale() {
      return this.projectItems.length > 0 && !this.projectsCurrent;
    },
    fitLabel: function (value) { return FIT_LABELS[value] || value || '未分类'; },
    generateProjects: async function () {
      if (!this.canWrite || this.projectsBusy) { return; }
      if (!this.meetingSourceId) { this.projectsError = '请先上传会议转写再生成项目建议'; return; }
      this.projectsBusy = true;
      this.projectsError = '';
      try {
        var job = await this.dispatch('/projects');
        var result = job.result || {};
        this.revision = result.revision || job.revision || this.revision;
        if (result.batch) {
          this.analysis = Object.assign({}, this.analysis, { projectRecommendations: result.batch });
        }
        this.projectsCurrent = true;
        if (this.confirmedReport) { this.editedAfterConfirm = true; }
        this.lastSavedAt = this.nowHM();
        this.schedulePreview();
      } catch (error) {
        if (error.status === 409 || error.stale) { this.beginConflict(); }
        this.projectsError = error.message || '生成失败';
      } finally {
        this.projectsBusy = false;
      }
    },
    toggleProject: async function (item) {
      if (!this.canWrite || this.projectsBusy) { return; }
      var include = item.status !== 'student_review';
      if (include && (!(item.interestRefs || []).length || !(item.evidenceQuotes || []).length)) {
        this.projectsError = '这个方案缺少可追溯的兴趣或会议原文证据，暂时不能放进报告。';
        return;
      }
      var items = this.projectItems.map(function (row) {
        var copy = Object.assign({}, row);
        if (copy.recommendationId === item.recommendationId) {
          copy.status = include ? 'student_review' : 'advisor_excluded';
        }
        return copy;
      });
      this.projectsBusy = true;
      this.projectsError = '';
      try {
        var job = await this.dispatch('/projects', { items: items }, 'PATCH');
        var result = job.result || {};
        this.revision = result.revision || job.revision || this.revision;
        if (result.batch) {
          this.analysis = Object.assign({}, this.analysis, { projectRecommendations: result.batch });
        }
        this.projectsCurrent = true;
        if (this.confirmedReport) { this.editedAfterConfirm = true; }
        this.lastSavedAt = this.nowHM();
        this.schedulePreview();
      } catch (error) {
        if (error.status === 409 || error.stale) { this.beginConflict(); }
        this.projectsError = error.message || '保存失败';
      } finally {
        this.projectsBusy = false;
      }
    },
    schedulePreview: function () {
      if (!this.canWrite) { return; }
      if (this.previewTimer) { clearTimeout(this.previewTimer); }
      this.previewTimer = setTimeout(() => { this.refreshPreview(); }, 600);
    },
    refreshPreview: async function () {
      if (!this.canWrite || !this.sessionId) { return; }
      this.previewBusy = true;
      this.previewError = '';
      try {
        var data = await this.request('/api/v2/copilot/sessions/' + this.sessionId + '/report-preview', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ revision: this.revision })
        });
        this.missing = data.missing || [];
        this.previewDraft = data.draft || null;
        this.previewLoaded = true;
      } catch (error) {
        this.previewError = error.message || '报告预览失败';
      } finally {
        this.previewBusy = false;
      }
    },
    get requiredMissing() {
      return this.missing.filter(function (item) { return item.required; });
    },
    get confirmReady() {
      return this.previewLoaded && !this.previewBusy && this.requiredMissing.length === 0;
    },
    get needsNewVersion() {
      return !!this.confirmedReport && (this.status !== 'COMPLETED' || this.editedAfterConfirm);
    },
    confirmReport: async function () {
      if (!this.canWrite || !this.confirmReady || this.confirmBusy) { return; }
      this.confirmBusy = true;
      this.confirmedError = '';
      try {
        var data = await this.request('/api/v2/copilot/sessions/' + this.sessionId + '/report-confirm', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ revision: this.revision })
        });
        var report = data.report || {};
        this.confirmedReport = report;
        this.reportId = report.id || this.reportId;
        if (typeof data.revision === 'number') { this.revision = data.revision; }
        this.status = 'COMPLETED';
        this.editedAfterConfirm = false;
        this.lastSavedAt = this.nowHM();
        v2Toast('报告已生成', 'success');
      } catch (error) {
        if (error.status === 409) { this.beginConflict(); }
        if (error.status === 422 && error.missing) {
          this.missing = error.missing;
          this.previewLoaded = true;
        }
        if (error.status === 422) {
          // 报告准备可能在内容校验失败前已推进 revision，先同步再允许重试。
          await this.refreshRevisionFromServer();
        }
        this.confirmedError = error.message || '报告确认失败';
      } finally {
        this.confirmBusy = false;
      }
    },
    refreshRevisionFromServer: async function () {
      try {
        var data = await this.request('/api/v2/copilot/sessions/' + this.sessionId);
        if (data.session && typeof data.session.revision === 'number') {
          this.revision = data.session.revision;
          this.status = data.session.status || this.status;
        }
        if (data.report) { this.confirmedReport = data.report; }
      } catch (error) {
        // 网络错误时保留本地版本号，交给重试或冲突横幅处理。
      }
    },
    downloadHref: function (kind) {
      if (!this.confirmedReport || !this.confirmedReport.id) { return '#'; }
      return '/api/growth-talk/reports/' + this.confirmedReport.id
        + '/download.' + (kind === 'json' ? 'json' : 'pdf');
    },
    get student360Href() {
      return '/students/' + encodeURIComponent(this.code || '');
    },

    /* ---------- 作业 / 聊天 ---------- */
    pollJob: async function (jobId, signal) {
      for (var attempt = 0; attempt < 300; attempt += 1) {
        if (signal && signal.aborted) {
          var stopped = new Error('已停止');
          stopped.name = 'AbortError';
          throw stopped;
        }
        var job = await this.request('/api/v2/copilot/jobs/' + jobId);
        if (job.status === 'done') { return job; }
        if (job.status === 'error') {
          var failure = new Error(job.message || '任务失败');
          failure.stale = String(job.message || '').indexOf('已被修改') >= 0;
          throw failure;
        }
        await this.delay(1200, signal);
      }
      throw new Error('任务超时，请稍后重试');
    },
    dispatch: async function (path, extra, method) {
      if (!this.canWrite || !this.sessionId) { throw new Error('只读模式'); }
      var body = Object.assign({ revision: this.revision }, extra || {});
      var started = await this.request('/api/v2/copilot/sessions/' + this.sessionId + path, {
        method: method || 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      return this.pollJob(started.jobId);
    },
    toggleDrawer: async function () {
      this.drawerOpen = !this.drawerOpen;
      if (!this.drawerOpen) { return; }
      await this.loadChats();
    },
    loadChats: async function () {
      if (this.chat.loading) { return; }
      this.chat.loading = true;
      this.chat.error = '';
      try {
        var data = await this.request('/api/students/' + this.sid + '/copilot/chats');
        this.chat.history = data.chats || [];
        if (!this.chat.chatId && this.chat.history.length) {
          await this.loadChat(this.chat.history[0].chatId);
        }
      } catch (error) {
        this.chat.error = error.message || '对话加载失败';
      } finally {
        this.chat.loading = false;
      }
    },
    loadChat: async function (chatId) {
      try {
        var data = await this.request('/api/copilot/chats/' + chatId);
        var chat = data.chat || {};
        this.chat.chatId = chat.chatId || chatId;
        this.chat.turns = (chat.turns || []).map(function (turn) {
          return {
            question: turn.question || '',
            answer: turn.answer || '',
            status: turn.status === 'ERROR' ? 'ERROR' : (turn.answer ? 'COMPLETE' : 'STOPPED')
          };
        });
      } catch (error) {
        this.chat.error = error.message || '对话加载失败';
      }
    },
    askSuggestion: function (question) {
      if (!this.canWrite || this.chat.sending) { return; }
      this.chat.question = question;
      this.sendChat();
    },
    sendChat: async function () {
      if (!this.canWrite || this.chat.sending) { return; }
      var question = String(this.chat.question || '').trim();
      if (!question) { return; }
      if (question.length > 1000) { this.chat.error = '问题不能超过 1000 字'; return; }
      var history = this.chat.turns.slice(-6)
        .filter(function (turn) { return turn.answer && turn.status === 'COMPLETE'; })
        .map(function (turn) { return { question: turn.question, answer: turn.answer }; });
      var controller = new AbortController();
      this.chat.controller = controller;
      this.chat.turns.push({ question: question, answer: '', status: 'ASKED' });
      this.chat.question = '';
      this.chat.sending = true;
      this.chat.error = '';
      try {
        var body = { question: question, history: history };
        if (this.chat.chatId) { body.chatId = this.chat.chatId; }
        var path = this.sessionId
          ? ('/api/v2/copilot/sessions/' + this.sessionId + '/assistant')
          : ('/api/students/' + this.sid + '/copilot/assistant');
        var started = await this.request(path, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body), signal: controller.signal
        });
        this.chat.chatId = started.chatId || this.chat.chatId;
        var job = await this.pollJob(started.jobId, controller.signal);
        var result = job.result || {};
        var turn = this.chat.turns[this.chat.turns.length - 1];
        turn.answer = result.answer || '';
        turn.status = 'COMPLETE';
      } catch (error) {
        var current = this.chat.turns[this.chat.turns.length - 1];
        current.status = (error && error.name === 'AbortError') ? 'STOPPED' : 'ERROR';
        if (!error || error.name !== 'AbortError') {
          this.chat.error = error.message || '回答失败';
        }
      } finally {
        this.chat.controller = null;
        this.chat.sending = false;
      }
    },
    stopChat: function () {
      if (this.chat.controller) { this.chat.controller.abort(); }
    }
  };
};
