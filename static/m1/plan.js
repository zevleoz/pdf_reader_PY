/* M1 发展计划：步骤切换、① 资料与目标、② 内部版审阅与自动保存 */
(function () {
  'use strict';

  var ROOT = document.getElementById('m1Plan');
  if (!ROOT) return;

  var CFG = window.M1_PLAN || {};
  var API = '/api/m1/plans/' + CFG.planId;
  var CORE = window.M1PlanCollabCore || {};
  var COLLAB = CFG.collaboration || {};
  var TAB_ID = 'tab-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
  var POLL_SECONDS = Math.max(5, Number(COLLAB.poll_seconds) || 15);

  var S = {
    rev: CFG.rev,
    versionId: null,
    status: CFG.status,
    doc: CFG.doc,
    checks: CFG.checks || [],
    goals: CFG.goals || [],
    step1: !!CFG.step1,
    step2: !!CFG.step2,
    canEdit: !!CFG.canEdit,
    canApprove: !!CFG.canApprove,
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
    parentTimer: null,
    proposal: null,
    directGateCleared: false,
    sections: Object.assign({}, COLLAB.sections || {}),
    docVersion: Number(COLLAB.document_version) || 1,
    leases: {},
    leasePromises: {},
    pending: {},
    conflicts: {},
    locked: {},
    activeSection: null,
    offline: !navigator.onLine,
    revoked: false,
    idem: 0,
    presenceTimer: null,
    pollTimer: null,
    renewTimer: null,
    polling: false,
    writes: [],
    familyHashes: (((CFG.parent || {}).family) || []).map(function (row) { return row.hash; }),
    familySeen: (((CFG.parent || {}).family) || []).map(function (row) { return !!row.seen; }),
    familyRemote: null,
    familyRemoteVersion: 0,
    familyRefreshSeq: 0,
    knownVersions: Object.assign({}, COLLAB.sections || {}),
    observedDocVersion: Number(COLLAB.document_version) || 1
  };

  var WRITE_BRIDGE = window.M1DirectInputs && window.M1DirectInputs.createWriteBridge
    ? window.M1DirectInputs.createWriteBridge(S.rev, function (rev) { S.rev = rev; })
    : {rev: Number(S.rev || 0), chain: Promise.resolve()};
  if (!WRITE_BRIDGE.enqueue) {
    WRITE_BRIDGE.getRev = function () { return this.rev; };
    WRITE_BRIDGE.setRev = function (rev) { this.rev = Number(rev); S.rev = this.rev; };
    WRITE_BRIDGE.isIdle = function () { return !this.busy; };
    WRITE_BRIDGE.enqueue = function (fn) {
      var self = this; var run = this.chain.then(function () { self.busy = true; return fn(); }, function () { self.busy = true; return fn(); });
      run = run.finally(function () { self.busy = false; }); this.chain = run.catch(function () {}); return run;
    };
  }
  window.M1PlanWriteBridge = WRITE_BRIDGE;
  WRITE_BRIDGE.patchSection = patchSection;
  WRITE_BRIDGE.flushAll = flushAll;
  WRITE_BRIDGE.releaseAll = releaseAll;
  WRITE_BRIDGE.heartbeat = heartbeat;
  function setPlanRev(rev) {
    if (rev == null) return;
    S.rev = Number(rev);
    WRITE_BRIDGE.setRev(S.rev);
    var module = window.M1DirectInputs && window.M1DirectInputs.getActive
      ? window.M1DirectInputs.getActive() : null;
    if (module) module.setRev(S.rev);
  }

  var DOC_NODE = document.getElementById('doc');
  if (DOC_NODE) S.versionId = parseInt(DOC_NODE.getAttribute('data-version'), 10) || null;
  var DIRECT = ROOT.getAttribute('data-source-mode') === 'mentor_inputs';
  var DIRECT_BRIEF_BLOCKERS = /^(请确认当前教学简报|请补充并授权用于教学：)/;
  var DIRECT_BASE_BLOCKERS = (CFG.blockers || []).filter(function (item) { return !DIRECT_BRIEF_BLOCKERS.test(item); });

  /* 页面载入时服务器上的内部版内容；与 S.doc 比对判断有没有未保存的改动 */
  var DOC_BASE = JSON.stringify(S.doc || null);
  function docChanged() {
    return !!S.doc && JSON.stringify(S.doc) !== DOC_BASE;
  }

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
    return WRITE_BRIDGE.enqueue(fn);
  }

  /* ------------------------------------------------- DP13 协作：租约与分段保存 */
  function idemKey(section) {
    S.idem += 1;
    return TAB_ID + '-' + String(section).replace(/[^A-Za-z0-9_.-]/g, '_') + '-' +
      S.idem + '-' + Date.now().toString(36);
  }

  function sectionForField(field) {
    if (!field) return null;
    var path = field.getAttribute('data-path');
    if (path && CORE.internalSection) {
      var internal = CORE.internalSection(S.doc, path);
      return internal ? internal.section : null;
    }
    path = field.getAttribute('data-ppath');
    if (path && CORE.parentSection) {
      var parent = CORE.parentSection(S.parentDoc, path);
      return parent ? parent.section : null;
    }
    return null;
  }

  function fieldValue(field) {
    if (field.tagName === 'INPUT' || field.tagName === 'SELECT' || field.tagName === 'TEXTAREA') {
      return field.value;
    }
    return field.textContent || '';
  }

  function clonePatch(value) {
    if (Array.isArray(value)) return value.map(clonePatch);
    if (value && typeof value === 'object') {
      var out = {};
      Object.keys(value).forEach(function (key) { out[key] = clonePatch(value[key]); });
      return out;
    }
    return value;
  }

  function isPlainObject(value) {
    return !!value && typeof value === 'object' && !Array.isArray(value);
  }

  /* 契约要求：嵌套对象按叶子合并；整列表 patch 保持数组，后者覆盖前者。
     每次调用都返回新对象，避免复用/改写正在发送的 payload。 */
  function composePatch(base, incoming) {
    if (incoming === undefined) return clonePatch(base);
    if (base === undefined || base === null) return clonePatch(incoming);
    if (Array.isArray(base) || Array.isArray(incoming)) return clonePatch(incoming);
    if (!isPlainObject(base) || !isPlainObject(incoming)) return clonePatch(incoming);
    var out = clonePatch(base);
    Object.keys(incoming).forEach(function (key) {
      out[key] = composePatch(out[key], incoming[key]);
    });
    return out;
  }

  function ensurePending(section, key) {
    var entry = S.pending[section];
    if (!entry) {
      entry = S.pending[section] = {
        paths: [], patch: null, timer: null, key: key || idemKey(section),
        attempt: null, error: null, sending: null, revision: 0
      };
    }
    return entry;
  }

  function rememberPath(entry, kind, path) {
    var id = kind + ':' + path;
    var found = (entry.paths || []).some(function (row) { return row.id === id; });
    if (!found) entry.paths.push({id: id, kind: kind, path: path});
  }

  function scheduleFlush(section, entry, immediate) {
    setSave('busy', '未保存');
    notifyPresence('editing');
    clearTimeout(entry.timer);
    entry.timer = setTimeout(function () { flushSection(section); }, immediate ? 0 : 650);
  }

  /* section 的完整 patch：以本地文档为准重建所有脏叶子，再叠加显式整段 patch。
     这样 content.mindsets 与 content.skills、focus 兄弟字段不会互相覆盖。 */
  function buildSectionPatch(section, paths, directPatch) {
    var patch = directPatch ? clonePatch(directPatch) : null;
    (paths || []).forEach(function (item) {
      var source = item.kind === 'parent' ? S.parentDoc : S.doc;
      var value = CORE.get ? CORE.get(source, item.path) : undefined;
      var built = item.kind === 'parent'
        ? (CORE.parentPatch ? CORE.parentPatch(S.parentDoc, item.path, value) : null)
        : (CORE.internalPatch ? CORE.internalPatch(S.doc, item.path, value) : null);
      if (!built || built.section !== section) return;
      patch = composePatch(patch, built.patch);
    });
    return patch;
  }

  function stagePatch(section, patch, immediate, key) {
    if (!section || !patch) return;
    if (!S.canEdit || S.revoked) return;
    if (S.conflicts[section]) {
      S.conflicts[section].patch = composePatch(S.conflicts[section].patch, patch);
      renderConflicts();
      return;
    }
    var entry = ensurePending(section, key);
    entry.patch = composePatch(entry.patch, patch);
    entry.error = null;
    entry.revision += 1;
    scheduleFlush(section, entry, immediate);
  }

  function stageField(field, immediate) {
    var path = field.getAttribute('data-path');
    var kind = path ? 'internal' : 'parent';
    if (!path) path = field.getAttribute('data-ppath');
    if (!path) return;
    var value = fieldValue(field);
    if (kind === 'parent' && /^family\./.test(path)) {
      set(S.parentDoc || {}, path, {text: value, src: 'edited'});
    } else {
      set(kind === 'internal' ? (S.doc || {}) : (S.parentDoc || {}), path, value);
    }
    var target = kind === 'internal'
      ? (CORE.internalSection ? CORE.internalSection(S.doc, path) : null)
      : (CORE.parentSection ? CORE.parentSection(S.parentDoc, path) : null);
    if (!target || !S.canEdit || S.revoked) return;
    if (S.conflicts[target.section]) {
      S.conflicts[target.section].patch = buildSectionPatch(
        target.section, [{id: kind + ':' + path, kind: kind, path: path}]);
      renderConflicts();
      return;
    }
    var entry = ensurePending(target.section);
    rememberPath(entry, kind, path);
    entry.error = null;
    entry.revision += 1;
    scheduleFlush(target.section, entry, immediate);
  }

  function isStaleError(err) {
    var code = err.payload && err.payload.code;
    return code === 'stale_section' || code === 'stale_document';
  }

  function flushSection(section) {
    var entry = S.pending[section];
    if (!entry) return Promise.resolve(true);
    if (entry.sending) return entry.sending;
    clearTimeout(entry.timer);
    if (S.revoked || !S.canEdit) return Promise.resolve(false);
    if (S.offline) {
      setSave('err', '离线');
      return Promise.resolve(false);
    }
    var patch = buildSectionPatch(section, entry.paths, entry.patch);
    if (!patch) {
      delete S.pending[section];
      updateSaveState();
      return Promise.resolve(true);
    }
    var identity = null;
    if (entry.attempt) {
      if (JSON.stringify(entry.attempt.patch) === JSON.stringify(patch)) {
        identity = clonePatch(entry.attempt);
      } else {
        /* 内容已变：旧幂等键只对应旧 patch，不能用它重发新内容。 */
        entry.attempt = null;
        entry.key = idemKey(section);
      }
    }
    var sentRevision = entry.revision;
    setSave('busy');
    var promise = patchSection(section, patch, entry.key, identity).then(function () {
      entry.attempt = null;
      entry.error = null;
      if (entry.revision !== sentRevision) {
        entry.key = idemKey(section);
        entry.sending = null;
        return flushSection(section);
      }
      if (S.pending[section] === entry) delete S.pending[section];
      updateSaveState();
      if (section === 'parent.family') refreshFamilyState();
      return true;
    }).catch(function (err) {
      entry.error = err;
      entry.attempt = err.identity || entry.attempt;
      if (isStaleError(err)) {
        var latest = buildSectionPatch(section, entry.paths, entry.patch) || patch;
        if (S.conflicts[section]) {
          /* 发送期间可能又输入了内容：冲突卡片保留最新本地正文。 */
          S.conflicts[section].patch = latest;
          if (err.payload && err.payload.code === 'stale_document') {
            S.conflicts[section].docVersion = err.payload.current;
          }
        } else {
          handlePatchError(section, err, latest);
        }
        if (S.pending[section] === entry) delete S.pending[section];
      }
      updateSaveState();
      return false;
    }).then(function (ok) {
      entry.sending = null;
      return ok;
    }, function (err) {
      entry.sending = null;
      throw err;
    });
    entry.sending = promise;
    return promise;
  }

  function hasUnresolved() {
    if (Object.keys(S.conflicts).length) return true;
    return Object.keys(S.pending).some(function (section) {
      var entry = S.pending[section];
      return !!entry.error && !entry.sending;
    });
  }

  /* 等待 debounce 条目、排队中的请求和在途写入全部确认后再返回。
     期间新到的编辑会进入下一轮，避免批准/导出漏掉刚输入的文字。 */
  function flushAll() {
    function round() {
      var sections = Object.keys(S.pending);
      if (sections.length) {
        return sections.reduce(function (chain, section) {
          return chain.then(function (ok) {
            if (ok === false) return false;
            return flushSection(section);
          });
        }, Promise.resolve(true)).then(function (ok) {
          if (ok === false) return false;
          return round();
        });
      }
      var active = S.writes.slice();
      if (!active.length) return Promise.resolve(!hasUnresolved());
      return Promise.all(active.map(function (write) {
        return write.catch(function () {});
      })).then(function () {
        if (Object.keys(S.pending).length) return round();
        return !hasUnresolved();
      });
    }
    return round();
  }

  function updateSaveState() {
    if (S.revoked) { setSave('err', '无编辑权限'); return; }
    if (hasUnresolved() && !Object.keys(S.pending).length) { setSave('err', '有冲突'); return; }
    var failed = Object.keys(S.pending).some(function (section) {
      return !!S.pending[section].error;
    });
    if (failed) { setSave('err', '未保存'); return; }
    if (Object.keys(S.pending).length || (S.inflight || 0)) {
      setSave('busy', '未保存');
      return;
    }
    setSave('ok');
  }

  /* identity 固定了 patch、expected_version、document_version 与幂等键。
     响应丢失时用同一身份重试，服务器已提交则安全回放，未提交才真正执行。 */
  function sendPatch(section, identity, token) {
    var body = {
      patch: clonePatch(identity.patch),
      expected_version: identity.expected_version,
      document_version: identity.document_version,
      lease_token: token,
      idempotency_key: identity.idempotency_key
    };
    S.inflight = (S.inflight || 0) + 1;
    return request('PATCH', API + '/sections/' + encodeURIComponent(section), body)
      .then(function (data) {
        acceptPatch(section, data);
        return data;
      }).finally(function () { S.inflight = Math.max(0, (S.inflight || 1) - 1); });
  }

  function acceptPatch(section, data) {
    S.sections[section] = data.section_version;
    S.knownVersions[section] = data.section_version;
    if (data.document_version) {
      S.docVersion = data.document_version;
      S.observedDocVersion = data.document_version;
    }
    if (data.version_id) S.versionId = data.version_id;
    if (data.checks) S.checks = data.checks;
    if (data.rev != null) setPlanRev(data.rev);
    var parent = CORE.dependencyParent ? CORE.dependencyParent(section) : null;
    if (parent) {
      S.sections[parent] = (S.sections[parent] || 0) + 1;
      S.knownVersions[parent] = S.sections[parent];
    }
    if (section === 'parent.family') {
      S.sections['parent.family_seen'] = (S.sections['parent.family_seen'] || 0) + 1;
      S.knownVersions['parent.family_seen'] = S.sections['parent.family_seen'];
    }
    delete S.locked[section];
    applyLocks();
  }

  function dropWrite(write) {
    var index = S.writes.indexOf(write);
    if (index >= 0) S.writes.splice(index, 1);
  }

  function patchSection(section, patch, key, identity) {
    var base = identity ? clonePatch(identity) : {
      patch: clonePatch(patch),
      /* 使用本地已载入内容对应的版本；不因服务器前进就静默采用新版本。 */
      expected_version: S.sections[section] || 0,
      document_version: S.docVersion,
      idempotency_key: key || idemKey(section)
    };
    var write = ensureLease(section).then(function (token) {
      return queue(function () { return sendPatch(section, base, token); });
    }).catch(function (err) {
      err.identity = base;
      handlePatchError(section, err, base.patch);
      throw err;
    });
    S.writes.push(write);
    write.then(function () { dropWrite(write); }, function () { dropWrite(write); });
    return write;
  }

  function ensureLease(section) {
    if (S.leases[section]) return Promise.resolve(S.leases[section]);
    if (S.leasePromises[section]) return S.leasePromises[section];
    var promise = request('POST', API + '/leases/acquire',
      {section: section, tab_id: TAB_ID}).then(function (data) {
        if (!data.token) throw new Error('没有取得编辑权');
        S.leases[section] = data.token;
        /* 不在这里采纳 acquire 返回的 section/document 版本：本地正文仍是
           页面载入时的版本；若服务器已前进，保存时必须走 stale 冲突视图。 */
        S.observedDocVersion = data.document_version || S.observedDocVersion;
        delete S.locked[section];
        applyLocks();
        scheduleRenew();
        return data.token;
      }).catch(function (err) {
        var payload = err.payload || {};
        if (payload.code === 'lease_conflict') {
          var holder = payload.holder || {};
          S.locked[section] = holder.name || '其他导师';
          applyLocks();
        } else if (err.status === 403 || err.status === 404) {
          applyRevoked('你没有这个计划的编辑权限（可能已被移出团队或计划已关闭）。本地未保存文字仍保留。');
        }
        throw err;
      }).finally(function () { delete S.leasePromises[section]; });
    S.leasePromises[section] = promise;
    return promise;
  }

  function releaseLease(section, keepalive) {
    var token = S.leases[section];
    if (!token) return Promise.resolve();
    delete S.leases[section];
    delete S.locked[section];
    applyLocks();
    var body = JSON.stringify({section: section, token: token});
    if (keepalive && navigator.sendBeacon) {
      navigator.sendBeacon(API + '/leases/release',
        new Blob([body], {type: 'application/json'}));
      return Promise.resolve();
    }
    return request('POST', API + '/leases/release', {section: section, token: token})
      .catch(function () {});
  }

  function releaseAll(keepalive) {
    var sections = Object.keys(S.leases);
    return Promise.all(sections.map(function (section) {
      return releaseLease(section, keepalive);
    }));
  }

  function releaseRelated(listSection) {
    var childPrefix = null;
    if (/\.activities$/.test(listSection)) {
      childPrefix = listSection.replace(/\.activities$/, '.activity.');
    } else {
      childPrefix = listSection + '.';
    }
    var tasks = Object.keys(S.leases).filter(function (section) {
      return section !== listSection && section.indexOf(childPrefix) === 0;
    }).map(function (section) { return releaseLease(section); });
    return Promise.all(tasks);
  }

  function handlePatchError(section, err, patch) {
    var payload = err.payload || {};
    if (section === 'parent.family_seen' &&
        (payload.code === 'stale_section' || payload.code === 'stale_document')) {
      /* 家庭正文刚刚又变化：不建不可编辑的 family_seen 冲突卡片，先取回
         并展示最新建议，等用户重新阅读后再次确认。 */
      toast('家庭建议已在别处更新，正在载入最新内容…');
      refreshFamilyAdvice().then(function () {
        toast('已显示最新家庭建议，请重新阅读后再点「已看过」');
      });
    } else if (payload.code === 'stale_section') {
      /* 不采纳 current_version：本地正文仍是旧版本，只有真正取回并采用
         服务端内容后才能推进 baseline。 */
      S.conflicts[section] = {
        section: section,
        patch: patch,
        current: payload.current,
        currentVersion: payload.current_version,
        docVersion: payload.current_document_version || S.docVersion,
        message: err.message
      };
      renderConflicts();
      notifyPresence('conflict');
    } else if (payload.code === 'stale_document') {
      S.conflicts[section] = {
        section: section,
        patch: patch,
        current: undefined,
        currentVersion: S.sections[section] || 0,
        docVersion: payload.current,
        message: err.message
      };
      renderConflicts();
      notifyPresence('conflict');
    } else if (payload.code === 'lease_conflict') {
      var holder = payload.holder || {};
      S.locked[section] = holder.name || '其他导师';
      applyLocks();
      renderPresence();
    } else if (payload.code === 'stale_family_ack') {
      /* 不采纳 current_hashes：必须先把最新建议真正展示出来，再允许确认。 */
      toast('家庭建议已在别处更新，正在载入最新内容…');
      refreshFamilyAdvice().then(function () {
        toast('已显示最新家庭建议，请重新阅读后再点「已看过」');
      });
    } else if (payload.code === 'parent_blocking') {
      S.parentBlocking = payload.blocking || [];
      toast(err.message);
    } else if (err.status === 403 || err.status === 404) {
      applyRevoked('你没有这个计划的编辑权限（可能已被移出团队或计划已关闭）。本地未保存文字仍保留。');
    } else if (payload.code === 'lease_required') {
      toast('编辑权已失效，正在重试…');
    } else {
      toast(err.message || '保存失败，请重试');
    }
  }

  function applyLocks() {
    if (!S.canEdit) return;
    document.querySelectorAll('#doc [data-path], #parentDoc [data-ppath]').forEach(function (field) {
      var section = sectionForField(field);
      var locked = !!(section && S.locked[section]);
      if (locked) {
        if (field.__collabEditable === undefined) {
          field.__collabEditable = field.getAttribute('contenteditable');
          field.__collabDisabled = !!field.disabled;
        }
        if (field.__collabEditable === 'true') field.setAttribute('contenteditable', 'false');
        if (field.tagName === 'INPUT' || field.tagName === 'SELECT') field.disabled = true;
        field.setAttribute('data-collab-locked', '1');
        field.title = '正在由' + S.locked[section] + '编辑';
      } else if (field.__collabEditable !== undefined) {
        if (field.__collabEditable === 'true') field.setAttribute('contenteditable', 'true');
        else if (field.__collabEditable === null) field.removeAttribute('contenteditable');
        if (field.tagName === 'INPUT' || field.tagName === 'SELECT') {
          field.disabled = !!field.__collabDisabled;
        }
        field.removeAttribute('data-collab-locked');
        field.removeAttribute('title');
        delete field.__collabEditable;
        delete field.__collabDisabled;
      }
    });
    updateSectionBadges();
  }

  function updateSectionBadges() {
    var count = Object.keys(S.locked).length;
    var node = document.getElementById('collabCount');
    if (node) node.textContent = count ? count + ' 处只读' : '';
  }

  function presenceState() {
    if (S.offline) return 'offline';
    if (Object.keys(S.conflicts).length) return 'conflict';
    if (S.activeSection) return 'editing';
    if (Object.keys(S.pending).length || (S.inflight || 0)) return 'saving';
    return 'saved';
  }

  function notifyPresence(state) {
    S.presenceState = state || presenceState();
    if (!S.offline) heartbeat(S.presenceState);
  }

  function heartbeat(state) {
    if (S.offline) return Promise.resolve();
    return request('POST', API + '/presence', {
      tab_id: TAB_ID,
      state: state || presenceState(),
      editing_section: S.activeSection || ''
    }).catch(function () {});
  }

  function scheduleRenew() {
    if (S.renewTimer) return;
    var ttl = Number(COLLAB.lease_ttl) || 45;
    S.renewTimer = setInterval(function () {
      if (document.visibilityState !== 'visible' || S.offline) return;
      Object.keys(S.leases).forEach(function (section) {
        request('POST', API + '/leases/renew',
          {section: section, token: S.leases[section], tab_id: TAB_ID})
          .catch(function (err) {
            delete S.leases[section];
            var payload = err.payload || {};
            if (payload.code === 'lease_conflict') {
              var holder = payload.holder || {};
              S.locked[section] = holder.name || '其他导师';
            }
            applyLocks();
          });
      });
      renderPresence();
    }, Math.max(5000, Math.floor(ttl * 1000 / 3)));
  }

  function pollPresence() {
    if (S.polling || S.revoked || document.visibilityState !== 'visible') return Promise.resolve();
    S.polling = true;
    return request('GET', API + '/presence').then(applyPresence)
      .catch(function (err) {
        if (err.status === 403 || err.status === 404) {
          applyRevoked('你没有这个计划的编辑权限（可能已被移出团队或计划已关闭）。本地未保存文字仍保留。');
        }
      }).finally(function () { S.polling = false; });
  }

  function applyPermissions(perms) {
    if (!perms) return;
    if (perms.can_edit !== undefined) {
      var next = !!perms.can_edit;
      if (!next && (S.canEdit || !S.revoked)) {
        applyRevoked(S.canEdit
          ? '你的编辑权限已被移除（可能已被移出团队或计划已关闭）。本地未保存文字仍保留。'
          : '当前为只读状态，不能编辑这个计划。');
      } else if (next && S.revoked) {
        restoreEditing();
      }
      S.canEdit = next;
    }
    if (perms.can_approve !== undefined) S.canApprove = !!perms.can_approve;
    renderPresence();
  }

  function applyPresence(data) {
    if (!data) return;
    S.lastPresence = data;
    S.presenceParticipants = data.participants || [];
    S.presenceLeases = data.leases || [];
    applyPermissions(data.permissions);
    var epoch = Number(data.document_version) || S.observedDocVersion;
    if (epoch > S.observedDocVersion) S.observedDocVersion = epoch;
    var changed = [];
    Object.keys(data.sections || {}).forEach(function (section) {
      var version = Number(data.sections[section]) || 0;
      /* 只记录“观察到的”服务器版本；本地 baseline 只有在正文真正取回
         并采用后才推进，避免用旧正文配新版本重放。 */
      S.knownVersions[section] = version;
      if (version > (S.sections[section] || 0) && !S.pending[section] &&
          !(S.inflight || 0) && !S.conflicts[section]) {
        changed.push(section);
      }
    });
    var locked = {};
    (data.leases || []).forEach(function (lease) {
      if (lease.section && Number(lease.user_id) !== Number(CFG.userId)) {
        locked[lease.section] = lease.name || '其他导师';
      }
    });
    S.locked = locked;
    applyLocks();
    renderPresence();
    if (epoch > S.docVersion) handleEpochChange();
    if (changed.length && !(S.inflight || 0)) refreshRemoteSections(changed);
    /* 家庭建议即使正被编辑也要保留远端快照：有新版本先取回，但不覆盖
       聚焦字段/未保存草稿；用户移出焦点或显式采纳后才安装 hash。 */
    var familyVersion = Number((data.sections || {})['parent.family']) || 0;
    if (familyVersion > (S.familyRemoteVersion || S.sections['parent.family'] || 0)) {
      refreshFamilyState();
    }
    Object.keys(S.pending).forEach(function (section) {
      if (!S.locked[section] && !S.conflicts[section] && !S.pending[section].timer &&
          !S.pending[section].sending) {
        S.pending[section].timer = setTimeout(function () { flushSection(section); }, 300);
      }
    });
  }

  function refreshRemoteSections(changed) {
    var structural = changed.filter(function (section) {
      return /(activities|practice|family|review|practice_options)$/.test(section);
    });
    var scalar = changed.filter(function (section) {
      return structural.indexOf(section) < 0;
    });
    if (structural.length) showRemoteNotice(structural);
    if (!scalar.length) return Promise.resolve([]);
    return request('GET', API).then(function (data) {
      var adopted = [];
      scalar.forEach(function (section) {
        if (S.pending[section] || S.conflicts[section] || S.revoked) return;
        if (section.indexOf('internal.') === 0 && data.internal && data.internal.doc && S.doc) {
          applyInternalSectionValue(section, data.internal.doc);
          adopted.push(section);
        } else if (section.indexOf('parent.') === 0 && data.parent && data.parent.doc &&
                   S.parentDoc && section !== 'parent.family_seen') {
          applyParentSectionValue(section, data.parent.doc);
          adopted.push(section);
        }
      });
      var versions = ((data.collaboration || {}).sections) || {};
      adopted.forEach(function (section) {
        if (versions[section] !== undefined) {
          S.sections[section] = versions[section];
          S.knownVersions[section] = versions[section];
        }
        refreshDomSection(section);
      });
      /* 整份 plan 已取回，document epoch 与正文一致，可以推进 baseline。 */
      var docVersion = Number((data.collaboration || {}).document_version) ||
        Number(data.document_version) || S.docVersion;
      if (!Object.keys(S.pending).length && !Object.keys(S.conflicts).length) {
        S.docVersion = docVersion;
        S.observedDocVersion = docVersion;
      }
      updateFamilyBadges();
      return adopted;
    }).catch(function () { return []; });
  }

  function applyInternalSectionValue(section, serverDoc) {
    var match = /^internal\.session\.(\d+)$/.exec(section);
    if (section === 'internal.overview') {
      S.doc.overview = clonePatch(serverDoc.overview);
    } else if (section === 'internal.mentor_notes') {
      S.doc.mentor_notes = clonePatch(serverDoc.mentor_notes);
    } else if (match) {
      /* session 段只拥有这些字段；activities/practice 由各自子段维护。 */
      var localSession = S.doc.sessions[parseInt(match[1], 10) - 1];
      var serverSession = (serverDoc.sessions || [])[parseInt(match[1], 10) - 1];
      if (!localSession || !serverSession) return;
      ['title', 'review', 'focus', 'content', 'evidence', 'next_prep'].forEach(function (key) {
        if (serverSession[key] !== undefined) localSession[key] = clonePatch(serverSession[key]);
      });
    } else {
      var item = /^internal\.session\.(\d+)\.(activity|practice)\.(.+)$/.exec(section);
      if (!item) return;
      var index = parseInt(item[1], 10) - 1;
      var serverRow = ((serverDoc.sessions || [])[index] || {});
      var serverList = item[2] === 'activity' ? serverRow.activities : serverRow.practice;
      var found = (serverList || []).filter(function (row) { return String(row.id) === item[3]; })[0];
      if (!found) return;
      var localList = item[2] === 'activity'
        ? (S.doc.sessions[index] || {}).activities
        : (S.doc.sessions[index] || {}).practice;
      (localList || []).forEach(function (row, i) {
        if (String(row.id) === item[3]) localList[i] = clonePatch(found);
      });
    }
  }

  function applyParentSectionValue(section, serverParent) {
    var session = /^parent\.session\.(\d+)$/.exec(section);
    if (section === 'parent.intro') S.parentDoc.intro = clonePatch(serverParent.intro);
    else if (section === 'parent.transition') S.parentDoc.transition = clonePatch(serverParent.transition);
    else if (/^parent\.goal\./.test(section)) {
      var code = section.slice('parent.goal.'.length);
      var serverGoal = (serverParent.goals || []).filter(function (g) { return g.code === code; })[0];
      var localGoal = (S.parentDoc.goals || []).filter(function (g) { return g.code === code; })[0];
      if (serverGoal && localGoal) localGoal.text = clonePatch(serverGoal.text);
    } else if (session) {
      /* 只覆盖 parent.session 拥有的 title/summary，不动其他内容。 */
      var index = parseInt(session[1], 10) - 1;
      var localSession = (S.parentDoc.sessions || [])[index];
      var serverSession = (serverParent.sessions || [])[index];
      if (!localSession || !serverSession) return;
      ['title', 'summary'].forEach(function (key) {
        if (serverSession[key] !== undefined) localSession[key] = clonePatch(serverSession[key]);
      });
    }
  }

  function refreshDomSection(section) {
    document.querySelectorAll('#doc [data-path], #parentDoc [data-ppath]').forEach(function (field) {
      if (document.activeElement === field) return;
      if (sectionForField(field) !== section) return;
      var path = field.getAttribute('data-path') || field.getAttribute('data-ppath');
      var source = field.getAttribute('data-path') ? S.doc : S.parentDoc;
      var value = CORE.get ? CORE.get(source, path) : null;
      if (field.tagName === 'INPUT' || field.tagName === 'SELECT' || field.tagName === 'TEXTAREA') {
        if (field.tagName === 'INPUT' && /\.minutes$/.test(path)) {
          field.value = String((value && value.minutes) || value || 0);
        } else {
          field.value = CORE.textOf ? CORE.textOf(value) : String(value == null ? '' : value);
        }
      } else {
        field.textContent = CORE.textOf ? CORE.textOf(value) : String(value == null ? '' : value);
      }
    });
    updateFamilyBadges();
  }

  function ensureRemoteNote() {
    var host = document.getElementById('collabPanel');
    if (!host) return null;
    var note = document.getElementById('collabRemoteNote');
    if (!note) {
      note = document.createElement('p');
      note.id = 'collabRemoteNote';
      note.className = 'hint';
      host.appendChild(note);
    }
    return note;
  }

  function showRemoteNotice(sections) {
    var note = ensureRemoteNote();
    if (!note) return;
    S.remoteSections = S.remoteSections || [];
    sections.forEach(function (section) {
      if (S.remoteSections.indexOf(section) < 0) S.remoteSections.push(section);
    });
    note.textContent = S.remoteSections.map(function (section) {
      return CORE.sectionLabel ? CORE.sectionLabel(section) : section;
    }).join('、') + ' 有新的结构修改。先保存本页文字，再点此载入最新内容。';
    note.style.cursor = 'pointer';
    note.onclick = function () { reconcileRemote(); };
  }

  /* 结构更新不直接 reload：先把本页所有草稿确认保存，失败或仍有冲突就
     不刷新，避免把无关文本当作快捷方式丢掉。 */
  function reconcileRemote() {
    flushAll().then(function (ok) {
      if (!ok) {
        toast('还有未保存或未处理的修改，请先保存/解决冲突再载入最新内容');
        return;
      }
      location.reload();
    });
  }

  function handleEpochChange() {
    var unresolved = Object.keys(S.pending).length || Object.keys(S.conflicts).length ||
      (S.inflight || 0) > 0;
    if (!unresolved) {
      location.reload();
      return;
    }
    var note = ensureRemoteNote();
    if (!note) return;
    note.textContent = '计划已在别处重新生成。本页未保存的文字已保留；' +
      '请先复制或保存，再点此载入最新内容（会丢弃本页未保存文字）。';
    note.style.cursor = 'pointer';
    note.onclick = function () {
      if (!window.confirm('载入最新内容会丢弃本页尚未保存的文字。确定继续？')) return;
      location.reload();
    };
  }

  function applyRevoked(message) {
    S.revoked = true;
    S.canEdit = false;
    S.canApprove = false;
    S.offline = false;
    stopPresence();
    var note = document.getElementById('collabOffline');
    if (!note) note = ensureRemoteNote();
    if (note) {
      note.hidden = false;
      note.style.cursor = 'default';
      note.onclick = null;
      note.textContent = message || '你没有这个计划的编辑权限。本地未保存文字仍保留。';
    }
    document.querySelectorAll('#doc [data-path], #parentDoc [data-ppath], [data-family], #mentorNotes')
      .forEach(function (field) {
        if (field.__revokedEditable === undefined) {
          field.__revokedEditable = field.getAttribute('contenteditable');
          field.__revokedDisabled = !!field.disabled;
        }
        if (field.__revokedEditable === 'true') field.setAttribute('contenteditable', 'false');
        if (field.tagName === 'INPUT' || field.tagName === 'SELECT' || field.tagName === 'TEXTAREA') {
          field.disabled = true;
        }
      });
    updateFamilyBadges();
    renderPresence();
    setSave('err', '无编辑权限');
  }

  function restoreEditing() {
    S.revoked = false;
    S.offline = false;
    document.querySelectorAll('#doc [data-path], #parentDoc [data-ppath], [data-family], #mentorNotes')
      .forEach(function (field) {
        if (field.__revokedEditable !== undefined) {
          if (field.__revokedEditable === null) field.removeAttribute('contenteditable');
          else field.setAttribute('contenteditable', field.__revokedEditable);
          delete field.__revokedEditable;
        }
        if (field.__revokedDisabled !== undefined) {
          field.disabled = field.__revokedDisabled;
          delete field.__revokedDisabled;
        }
      });
    var note = document.getElementById('collabOffline');
    if (note) note.hidden = true;
    startPresence();
    pollPresence();
  }

  function renderPresence() {
    var self = document.getElementById('collabSelf');
    var list = document.getElementById('collabList');
    var count = document.getElementById('collabCount');
    var participants = S.presenceParticipants || [];
    var roleLabels = {primary: '负责导师', co_mentor: '共同导师', admin: '管理员', viewer: '只读'};
    var stateLabels = {editing: '正在编辑', saving: '保存中', saved: '在线', conflict: '有冲突', offline: '离线'};
    if (self) {
      self.textContent = (CFG.userName || '你') + ' · ' +
        (S.canApprove ? '可批准与导出' : (S.canEdit ? '可编辑，不可批准' : '只读')) +
        (S.offline ? ' · 离线' : '');
    }
    if (count) {
      count.textContent = participants.length ? participants.length + ' 人在线' : '';
    }
    if (!list) return;
    list.innerHTML = '';
    participants.forEach(function (item) {
      var row = document.createElement('div');
      row.className = 'collab-chip' + (Number(item.user_id) === Number(CFG.userId) ? ' is-self' : '');
      var name = document.createElement('b');
      name.textContent = item.name || '导师';
      var role = document.createElement('span');
      role.className = 'role';
      role.textContent = roleLabels[item.role] || item.role || '协作者';
      var detail = document.createElement('span');
      detail.className = 'sec';
      var bits = [];
      if (item.state) bits.push(stateLabels[item.state] || item.state);
      if (item.editing_section && CORE.sectionLabel) bits.push(CORE.sectionLabel(item.editing_section));
      detail.textContent = bits.join(' · ');
      row.appendChild(name);
      row.appendChild(role);
      if (detail.textContent) row.appendChild(detail);
      list.appendChild(row);
    });
    if (!participants.length) {
      var empty = document.createElement('p');
      empty.className = 'hint';
      empty.textContent = S.canEdit ? '只有你在线。' : '暂时没有其他协作者。';
      list.appendChild(empty);
    }
  }

  function renderConflicts() {
    var host = document.getElementById('collabConflicts');
    if (!host) return;
    host.innerHTML = '';
    var sections = Object.keys(S.conflicts);
    host.hidden = !sections.length;
    sections.forEach(function (section) {
      var conflict = S.conflicts[section];
      var card = document.createElement('div');
      card.className = 'collab-conflict';
      card.setAttribute('data-conflict', section);
      var title = document.createElement('b');
      title.textContent = (CORE.sectionLabel ? CORE.sectionLabel(section) : section) + ' 已在别处更新';
      card.appendChild(title);
      var local = document.createElement('p');
      local.innerHTML = '<span class="lbl">你的文字：</span>';
      local.appendChild(document.createTextNode(
        CORE.conflictPreview ? CORE.conflictPreview(conflict.patch) : ''));
      card.appendChild(local);
      if (conflict.current !== undefined) {
        var server = document.createElement('p');
        server.innerHTML = '<span class="lbl">当前版本：</span>';
        server.appendChild(document.createTextNode(
          CORE.conflictCurrent
            ? CORE.conflictCurrent(conflict.patch, conflict.current)
            : (CORE.conflictPreview ? CORE.conflictPreview(conflict.current) : '')));
        card.appendChild(server);
      }
      var message = document.createElement('p');
      message.className = 'hint';
      message.textContent = conflict.message || '请对比后选择保留哪一版。';
      card.appendChild(message);
      var acts = document.createElement('div');
      acts.className = 'acts';
      if (conflict.current !== undefined) {
        /* stale_document 没有可对照的当前文字，不能把旧 epoch 的正文
           当作“重新应用”直接写回，只允许改用当前版本。 */
        var keep = document.createElement('button');
        keep.className = 'btn s';
        keep.type = 'button';
        keep.textContent = '保留我的文字并重新应用';
        keep.addEventListener('click', function () { reapplyConflict(section); });
        acts.appendChild(keep);
      }
      var useServer = document.createElement('button');
      useServer.className = 'btn';
      useServer.type = 'button';
      useServer.textContent = '改用当前版本';
      useServer.addEventListener('click', function () { useServerConflict(section); });
      acts.appendChild(useServer);
      card.appendChild(acts);
      host.appendChild(card);
    });
  }

  function reapplyConflict(section) {
    var conflict = S.conflicts[section];
    if (!conflict || conflict.current === undefined) return;
    request('GET', API).then(function (data) {
      var versions = ((data.collaboration || {}).sections) || {};
      var serverVersion = Number(versions[section]);
      if (!isNaN(serverVersion) && serverVersion !== Number(conflict.currentVersion)) {
        conflict.currentVersion = serverVersion;
        conflict.message = '这部分内容也已被再次更新，请直接改用当前版本或重新编辑。';
        renderConflicts();
        return null;
      }
      var docVersion = Number((data.collaboration || {}).document_version) ||
        Number(conflict.docVersion) || S.docVersion;
      return patchSection(section, conflict.patch, idemKey(section), {
        patch: clonePatch(conflict.patch),
        expected_version: conflict.currentVersion,
        document_version: docVersion,
        idempotency_key: idemKey(section)
      });
    }).then(function (result) {
      if (!result) return;
      delete S.conflicts[section];
      delete S.pending[section];
      renderConflicts();
      updateSaveState();
      if (section === 'parent.family') refreshFamilyState();
    }).catch(function (err) {
      toast(err.message);
    });
  }

  function reloadAfterFlush() {
    flushAll().then(function (ok) {
      if (!ok) {
        toast('还有未保存或未处理的修改，请先保存/解决冲突再载入最新内容');
        return;
      }
      location.reload();
    });
  }

  function useServerConflict(section) {
    var conflict = S.conflicts[section];
    if (!conflict) return;
    if (conflict.current === undefined ||
        /(activities|practice|family|review|practice_options)$/.test(section)) {
      /* 结构冲突/生命周期冲突：先把本页其他草稿保存成功，再整页载入，
         不把“改用当前版本”变成丢弃无关文本的快捷方式。 */
      reloadAfterFlush();
      return;
    }
    request('GET', API).then(function (data) {
      if (section.indexOf('internal.') === 0 && data.internal && data.internal.doc) {
        applyInternalSectionValue(section, data.internal.doc);
      } else if (section.indexOf('parent.') === 0 && data.parent && data.parent.doc) {
        applyParentSectionValue(section, data.parent.doc);
      }
      var versions = ((data.collaboration || {}).sections) || {};
      if (versions[section] !== undefined) {
        S.sections[section] = versions[section];
        S.knownVersions[section] = versions[section];
      } else {
        S.sections[section] = conflict.currentVersion;
      }
      var docVersion = Number((data.collaboration || {}).document_version) ||
        Number(conflict.docVersion) || S.docVersion;
      S.docVersion = docVersion;
      S.observedDocVersion = docVersion;
      delete S.conflicts[section];
      delete S.pending[section];
      renderConflicts();
      refreshDomSection(section);
      updateSaveState();
    }).catch(function (err) { toast(err.message); });
  }

  function updateFamilyBadges() {
    [0, 1].forEach(function (index) {
      var host = document.querySelector('[data-family="' + index + '"]');
      var badge = document.querySelector('[data-family-ai="' + index + '"]');
      var ack = document.querySelector('[data-family-seen="' + index + '"]');
      var adopt = document.querySelector('[data-family-adopt="' + index + '"]');
      var remote = S.familyRemote;
      var canAdopt = !!(remote && remote.family && remote.family[index] !== undefined);
      var blocked = !!(S.conflicts['parent.family'] || familyRemoteDiffers(index));
      if (blocked) {
        /* 远端正文尚未显示（草稿/冲突/聚焦）：先禁止确认，提供显式采纳。 */
        if (ack) ack.remove();
        if (!badge && host) {
          badge = document.createElement('span');
          badge.className = 'ai';
          badge.setAttribute('data-family-ai', String(index));
          badge.textContent = 'AI 新写';
          host.parentNode.insertBefore(badge, host.nextSibling);
        }
        if (!adopt && canAdopt && host && S.parentEditable && S.canEdit && !S.revoked) {
          adopt = document.createElement('button');
          adopt.type = 'button';
          adopt.className = 'btn s';
          adopt.setAttribute('data-family-adopt', String(index));
          adopt.style.cssText = 'height:26px;font-size:11.5px;margin-left:6px';
          adopt.textContent = '查看新建议';
          adopt.addEventListener('click', function () { adoptFamilyRemote(index); });
          if (badge && badge.parentNode) badge.parentNode.insertBefore(adopt, badge.nextSibling);
        }
        return;
      }
      if (adopt) adopt.remove();
      if (S.familySeen[index]) {
        if (badge) badge.remove();
        if (ack) ack.remove();
        return;
      }
      if (!badge && host) {
        badge = document.createElement('span');
        badge.className = 'ai';
        badge.setAttribute('data-family-ai', String(index));
        badge.textContent = 'AI 新写';
        host.parentNode.insertBefore(badge, host.nextSibling);
      }
      if (!ack && host && S.parentEditable && S.canEdit && !S.revoked) {
        ack = document.createElement('button');
        ack.type = 'button';
        ack.className = 'btn s';
        ack.setAttribute('data-family-seen', String(index));
        ack.style.cssText = 'height:26px;font-size:11.5px;margin-left:6px';
        ack.textContent = '已看过';
        ack.addEventListener('click', function () { markFamilySeen(index); });
        if (badge && badge.parentNode) badge.parentNode.insertBefore(ack, badge.nextSibling);
      }
    });
  }

  function refreshFamilyDom(index) {
    var node = document.querySelector('[data-family="' + index + '"]');
    if (!node || document.activeElement === node) return;
    var value = ((S.parentDoc || {}).family || [])[index];
    node.textContent = CORE.textOf ? CORE.textOf(value) : String(value == null ? '' : value);
  }

  /* 把服务器返回的家庭建议绑定到“实际显示在 DOM 里的文本”：
     - 文本已经一致：hash 可以安全安装；
     - 文本不同：只有无草稿、无冲突且字段未聚焦时才渲染并安装 hash；
     - 否则保留当前显示的 hash/seen，把服务器快照单独存入 familyRemote，
       等用户移出焦点或显式点“查看新建议”后再原子采纳。 */
  function applyFamilyFromPayload(data, resetChanged) {
    var rows = data.parent_family || [];
    if (!rows.length || !S.parentDoc) return [];
    var serverFamily = ((data.parent || {}).doc || {}).family || [];
    var versions = ((data.collaboration || {}).sections) || {};
    var dirty = !!(S.pending['parent.family'] || S.conflicts['parent.family']);
    var hashes = (S.familyHashes || []).slice();
    var seen = (S.familySeen || []).slice();
    var remoteHashes = [];
    var remoteSeen = [];
    var allAdopted = !dirty;
    rows.forEach(function (row, index) {
      var prevHash = hashes[index];
      var serverValue = serverFamily[index];
      var node = document.querySelector('[data-family="' + index + '"]');
      var focused = !!node && document.activeElement === node;
      var localValue = ((S.parentDoc || {}).family || [])[index];
      var serverText = CORE.textOf ? CORE.textOf(serverValue)
        : String(serverValue == null ? '' : serverValue);
      var displayedText = node ? (node.textContent || '')
        : (CORE.textOf ? CORE.textOf(localValue)
          : String(localValue == null ? '' : localValue));
      remoteHashes[index] = row.hash;
      remoteSeen[index] = !!row.seen;
      if (serverValue === undefined) {
        remoteHashes[index] = prevHash;
        allAdopted = false;
        return;
      }
      /* 显示文本与服务器一致：hash 确实对应当前文字，可以安装。 */
      if (serverText === displayedText) {
        hashes[index] = row.hash;
        seen[index] = !!(seen[index] || row.seen);
        return;
      }
      /* 有草稿/冲突，或字段正在聚焦：不能改写正文或光标，
         也不能提前把新 hash 当成“已显示”。 */
      if (dirty || focused) {
        allAdopted = false;
        return;
      }
      if (!Array.isArray(S.parentDoc.family)) S.parentDoc.family = [];
      S.parentDoc.family[index] = clonePatch(serverValue);
      refreshFamilyDom(index);
      hashes[index] = row.hash;
      seen[index] = false;
    });
    S.familyHashes = hashes;
    S.familySeen = seen;
    S.familyRemote = {
      family: clonePatch(serverFamily),
      hashes: remoteHashes,
      seen: remoteSeen,
      familyVersion: versions['parent.family'],
      familySeenVersion: versions['parent.family_seen']
    };
    if (versions['parent.family'] !== undefined) {
      S.knownVersions['parent.family'] = versions['parent.family'];
      S.familyRemoteVersion = versions['parent.family'];
      /* 只有所有条目都真正采纳后才推进编辑 baseline。 */
      if (allAdopted && !dirty) S.sections['parent.family'] = versions['parent.family'];
    }
    if (versions['parent.family_seen'] !== undefined) {
      S.knownVersions['parent.family_seen'] = versions['parent.family_seen'];
      if (allAdopted && !dirty) {
        S.sections['parent.family_seen'] = versions['parent.family_seen'];
      }
    }
    updateFamilyBadges();
    return hashes;
  }

  function familyRemoteDiffers(index) {
    var remote = S.familyRemote;
    if (!remote || !remote.hashes) return false;
    var hash = remote.hashes[index];
    return hash !== undefined && hash !== (S.familyHashes || [])[index];
  }

  /* 用户显式选择采纳服务器正文：先渲染正文，再原子安装对应 hash。 */
  function adoptFamilyRemote(index) {
    var remote = S.familyRemote;
    var family = (remote && remote.family) || [];
    if (!S.parentDoc || family[index] === undefined) {
      toast('没有可载入的新建议');
      return false;
    }
    if (S.pending['parent.family'] || S.conflicts['parent.family']) {
      toast('请先保存或处理家庭建议的修改，再载入新建议');
      return false;
    }
    var node = document.querySelector('[data-family="' + index + '"]');
    if (node && document.activeElement === node) {
      toast('请先移出家庭建议编辑框，再载入新建议');
      return false;
    }
    if (!Array.isArray(S.parentDoc.family)) S.parentDoc.family = [];
    S.parentDoc.family[index] = clonePatch(family[index]);
    refreshFamilyDom(index);
    var hashes = (S.familyHashes || []).slice();
    var seen = (S.familySeen || []).slice();
    hashes[index] = remote.hashes[index];
    seen[index] = false;
    S.familyHashes = hashes;
    S.familySeen = seen;
    var all = true;
    (remote.hashes || []).forEach(function (hash, i) {
      if (hash !== undefined && hash !== hashes[i]) all = false;
    });
    if (all && remote.familyVersion !== undefined) {
      S.sections['parent.family'] = remote.familyVersion;
      S.knownVersions['parent.family'] = remote.familyVersion;
      S.familyRemoteVersion = remote.familyVersion;
    }
    if (all && remote.familySeenVersion !== undefined) {
      S.sections['parent.family_seen'] = remote.familySeenVersion;
      S.knownVersions['parent.family_seen'] = remote.familySeenVersion;
    }
    updateFamilyBadges();
    return true;
  }

  /* 焦点离开且没有草稿/冲突时，才自动采纳等待中的新建议。 */
  function adoptFamilyRemoteIfClean(index) {
    setTimeout(function () {
      var node = document.querySelector('[data-family="' + index + '"]');
      if (node && document.activeElement === node) return;
      if (S.pending['parent.family'] || S.conflicts['parent.family']) return;
      if (!familyRemoteDiffers(index)) return;
      if (adoptFamilyRemote(index)) {
        toast('家庭建议已更新，请重新阅读后再点「已看过」');
      }
    }, 0);
  }

  function loadFamilyPayload(resetChanged) {
    S.familyRefreshSeq = (S.familyRefreshSeq || 0) + 1;
    var seq = S.familyRefreshSeq;
    return request('GET', API).then(function (data) {
      /* 迟到的旧 GET 不能覆盖后发请求已经采纳的更新。 */
      if (seq !== S.familyRefreshSeq) return;
      applyFamilyFromPayload(data, resetChanged);
    }).catch(function () {});
  }

  function refreshFamilyState() {
    return loadFamilyPayload(false);
  }

  function refreshFamilyAdvice() {
    return loadFamilyPayload(true);
  }

  function startPresence() {
    if (S.presenceStarted || S.revoked) return;
    S.presenceStarted = true;
    heartbeat(presenceState());
    pollPresence();
    S.presenceTimer = setInterval(function () {
      if (document.visibilityState !== 'visible') return;
      heartbeat(presenceState());
    }, POLL_SECONDS * 1000);
    S.pollTimer = setInterval(pollPresence, POLL_SECONDS * 1000);
    scheduleRenew();
  }

  function stopPresence() {
    clearInterval(S.presenceTimer);
    clearInterval(S.pollTimer);
    clearInterval(S.renewTimer);
    S.presenceTimer = null;
    S.pollTimer = null;
    S.renewTimer = null;
    S.presenceStarted = false;
  }

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') {
      startPresence();
      pollPresence();
    }
  });
  window.addEventListener('online', function () {
    if (S.revoked) return;
    S.offline = false;
    var offline = document.getElementById('collabOffline');
    if (offline) offline.hidden = true;
    pollPresence().then(function () {
      Object.keys(S.pending).forEach(function (section) {
        if (!S.conflicts[section] && !S.locked[section]) {
          S.pending[section].timer = setTimeout(function () { flushSection(section); }, 300);
        }
      });
    });
    heartbeat('saved');
  });
  window.addEventListener('offline', function () {
    S.offline = true;
    var offline = document.getElementById('collabOffline');
    if (offline) offline.hidden = false;
    setSave('err', '离线');
  });
  window.addEventListener('pagehide', function () {
    stopPresence();
    releaseAll(true);
  });
  startPresence();

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
      counter.title = '建议长度，仅供参考，不影响确认或导出';
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
    return patchSection('header', fields).then(function () {
      setSave('ok');
      return releaseLease('header');
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

  /* 每节时长：保存后重新计算核对，不重新生成内容 */
  function durationInputs() {
    return Array.prototype.slice.call(document.querySelectorAll('[data-duration]'));
  }

  function durationValues() {
    return durationInputs().map(function (input) { return parseInt(input.value, 10); });
  }

  function refreshDurTotal() {
    var node = document.getElementById('durTotal');
    if (!node) return;
    var sum = durationValues().reduce(function (total, value) { return total + (isNaN(value) ? 0 : value); }, 0);
    node.textContent = '合计 ' + sum + ' 分钟';
  }

  function saveDurations() {
    if (!S.step1) return Promise.resolve();
    setSave('busy');
    clearTimeout(S.docTimer);
    var pending = (S.step2 && S.doc && docChanged()) ? flushDoc() : Promise.resolve();
    return pending.then(function () {
      // Validate and read values at dispatch time. Each change is serialized,
      // so rapid edits cannot race a stale revision.
      var values = durationValues();
      if (values.length !== 3 || values.some(function (value) { return !(value >= 15 && value <= 180); })) {
        toast('每节时长需要 15–180 分钟');
        return;
      }
      return patchSection('durations', {session_durations: values}).then(function () {
        refreshTimingBudgets(values);
        setSave('ok');
        return releaseLease('durations');
      });
    }).catch(function (err) {
      setSave('err');
      toast(err.message);
      throw err;
    });
  }

  function refreshTimingBudgets(durations) {
    document.querySelectorAll('[data-timing-budget]').forEach(function (node) {
      var index = parseInt(node.getAttribute('data-timing-budget'), 10);
      var duration = durations[index];
      var activity = parseInt(node.getAttribute('data-activity-minutes'), 10) || 0;
      var review = parseInt(node.getAttribute('data-review-minutes'), 10) || 0;
      var transition = parseInt(node.getAttribute('data-transition-minutes'), 10) || 0;
      var blockReview = parseInt(node.getAttribute('data-block-review-minutes'), 10) || 0;
      var total = activity + review + transition;
      var label = node.querySelector('[data-duration-label]');
      var summary = node.querySelector('[data-timing-summary]');
      var off = node.querySelector('[data-timing-delta]');
      if (label) label.textContent = '本节 ' + duration + ' 分钟';
      if (summary) summary.textContent = '活动 ' + activity + ' 分钟' +
        (blockReview ? '（含 Block Review ' + blockReview + ' 分钟）' : '') +
        ' · 上次回顾 ' + review + ' 分钟 · 转换 ' + transition +
        ' 分钟 · 合计 ' + total + ' 分钟 · 可用于教学 ' +
        (duration - review - transition - blockReview) + ' 分钟';
      if (off) {
        off.hidden = total === duration;
        off.textContent = '与计划相差 ' + (total - duration >= 0 ? '+' : '') +
          (total - duration) + ' 分钟，可在①调整每节时长或活动分钟数';
      }
    });
  }

  if (durationInputs().length) {
    durationInputs().forEach(function (input) {
      input.addEventListener('input', refreshDurTotal);
      input.addEventListener('change', function () { if (S.step1) saveDurations(); });
    });
    refreshDurTotal();
  }

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
    return patchSection('inputs', values).then(function () {
      setSave('ok');
      return releaseLease('inputs');
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
    return patchSection('goals', {goals: goalPayload()}).then(function () {
      setSave('ok');
      return releaseLease('goals');
    }).catch(function (err) {
      setSave('err');
      toast(err.message);
      throw err;
    });
  }

  function findGoal(code) {
    return S.goals.filter(function (goal) { return goal.code === code; })[0];
  }

  function goalEmpty(goal) {
    return !((goal && goal.goal && goal.goal.text) || '').trim();
  }

  /* 已锁定且发展目标为空：框用警告色并显示提示行 */
  function refreshGoalWarn(code) {
    var goal = findGoal(code);
    var field = document.querySelector('[data-goal-text="' + code + '"]');
    var warn = document.querySelector('[data-goal-warn="' + code + '"]');
    var missing = !!goal && !!goal.locked && goalEmpty(goal);
    if (field) { if (missing) field.setAttribute('data-missing', '1'); else field.removeAttribute('data-missing'); }
    if (warn) warn.hidden = !missing;
  }

  /* 生成原因行：只在客户端重算「发展目标还没写」这一条，其余原因沿用页面载入时的结果 */
  var GOAL_BLOCKER = /的发展目标还没写$/;
  function refreshGenReason() {
    var btn = document.getElementById('genBtn');
    var hint = document.getElementById('genHint');
    if (!btn || !hint || !S.step1) return;
    var rest = (CFG.blockers || []).filter(function (item) {
      if (GOAL_BLOCKER.test(item)) return false;
      if (S.useOld && item.indexOf('会后报告已更新') === 0) return false;
      return true;
    });
    var missing = S.goals.filter(goalEmpty).map(function (goal) { return goal.code; });
    if (missing.length) rest.unshift(missing.join('、') + ' 的发展目标还没写');
    hint.textContent = rest.length ? rest.join('；') : (S.useOld ? '使用旧版会后报告生成。' : '约 1–3 分钟，可以离开页面。');
    btn.disabled = rest.length > 0;
  }

  document.querySelectorAll('[data-goal-text]').forEach(function (field) {
    var code = field.getAttribute('data-goal-text');
    if (!S.step1) return;
    field.addEventListener('input', function () {
      var goal = findGoal(code);
      if (!goal) return;
      goal.goal = {text: field.textContent || '', src: 'mentor'};
      var badge = document.querySelector('[data-goal-ai="' + code + '-goal"]');
      if (badge) badge.hidden = true;
      if (!field.textContent) field.innerHTML = '';
      refreshGoalWarn(code);
      refreshGenReason();
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
      if (locking && goalEmpty(goal)) {
        var gf = document.querySelector('[data-goal-text="' + code + '"]');
        if (gf) gf.focus();
        toast('先写这一项的发展目标，再锁定。');
        return;
      }
      goal.locked = locking;
      button.disabled = true;
      saveGoals().then(function () {
        var empty = !(goal.start.text || '').trim() && !(goal.expected.text || '').trim();
        if (locking && empty) {
          var dd = document.querySelectorAll('[data-goal-field="' + code + '-start"], [data-goal-field="' + code + '-expected"]');
          dd.forEach(function (node) { node.classList.add('busy'); });
          startJob(API + '/goals/' + code + '/fill', function () { location.reload(); }, null, {rev: S.rev});
        } else {
          location.reload();
        }
      }).catch(function () { button.disabled = false; });
    });
  });

  function fillGoal(code, button) {
    clearTimeout(S.goalTimer);
    if (button) button.disabled = true;
    function failed() {
      if (button) { button.disabled = false; button.textContent = 'AI 补全失败，重试'; }
      else location.reload(); // 已保存的空目标会显示补全 / 重试按钮
    }
    saveGoals().then(function () {
      startJob(API + '/goals/' + code + '/fill', function () { location.reload(); }, failed, {rev: S.rev});
    }).catch(failed);
  }

  document.querySelectorAll('[data-fill-goal]').forEach(function (button) {
    button.addEventListener('click', function () {
      if (S.step1) fillGoal(button.getAttribute('data-fill-goal'), button);
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
    toast('已添加目标，AI 正在填写发展目标、起点和预期进展');
    fillGoal(code);
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
        patchSection('personal', {notes: notes.value}).then(function () {
          setSave('ok');
          return releaseLease('personal');
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
        patchSection('personal', {summary: summaryText.value}).then(function () {
            setSave('ok');
            var mark = document.getElementById('summaryAi');
            if (mark) mark.remove();
            return releaseLease('personal');
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

  /* ------------------------------------------------------------ 直接创建输入 */
  function directModule() {
    return (window.M1DirectInputs && window.M1DirectInputs.getActive)
      ? window.M1DirectInputs.getActive() : null;
  }

  function flushDirect() {
    var module = directModule();
    if (!module) return Promise.resolve();
    return module.flush().then(function (ok) {
      if (!ok) throw new Error('学生资料或教学简报还没保存');
      S.rev = module.getRev();
    });
  }

  window.addEventListener('m1:plan-rev', function (event) {
    var detail = event.detail || {};
    if (String(detail.planId) !== String(CFG.planId)) return;
    setPlanRev(detail.rev);
    if (DIRECT) refreshDirectGate();
  });

  /* 简报确认后，页面载入时算出的阻断原因可能过期；只清除与本计划状态一致的简报阻断 */
  function refreshDirectGate() {
    if (!DIRECT) return;
    var requestId = S.directGateRequest = (S.directGateRequest || 0) + 1;
    request('GET', API).then(function (data) {
      if (requestId !== S.directGateRequest) return;
      var plan = data.plan || {};
      CFG.blockers = window.M1DirectInputs && window.M1DirectInputs.directGateBlockers
        ? window.M1DirectInputs.directGateBlockers(DIRECT_BASE_BLOCKERS, plan)
        : DIRECT_BASE_BLOCKERS.slice();
      refreshGenReason();
    }).catch(function () {});
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
        if (onDone) onDone(job);
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
    flushDirect().then(function () {
      return flushAll();
    }).then(function (ok) {
      if (ok === false) throw new Error('还有未保存或冲突的内容');
      return releaseAll();
    }).then(function () {
      return request('POST', url, body || {});
    }).then(function (data) {
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
      flushDirect().then(function () {
        return flushAll();
      }).then(function (ok) {
        if (ok === false) throw new Error('还有未保存或冲突的内容');
        return releaseAll();
      }).then(function () {
        return request('POST', API + '/generate', {use_old_report: !!S.useOld, rev: S.rev});
      }).then(function (data) {
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
      refreshGenReason();
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

  /* 兼容旧调用：只把本页未保存的分段改动送出，不再整份覆盖文档。
     结构变化（增删、排序）由 mutateInternalList 单独处理。 */
  function saveDoc(reload) {
    if (!S.step2 || !S.doc) return Promise.resolve();
    return flushAll().then(function (ok) {
      if (ok === false) throw new Error('还有未保存或冲突的内容');
      renderChecks();
      if (reload) location.reload();
    });
  }

  function refreshRichCount(field) {
    var details = field.closest ? field.closest('.act-more') : null;
    if (!details) return;
    var fields = details.querySelectorAll('[data-rich-field]');
    var filled = 0;
    fields.forEach(function (node) { if ((node.textContent || '').trim()) filled += 1; });
    var counter = details.querySelector('.rich-n');
    if (counter) counter.textContent = filled + '/' + fields.length;
  }

  function flushDoc() {
    clearTimeout(S.docTimer);
    return flushAll().then(function (ok) {
      if (ok === false) throw new Error('还有未保存或冲突的内容');
      return null;
    });
  }

  function mutateInternalList(section, value) {
    if (!S.step2 || !S.doc) return Promise.resolve();
    if (S.conflicts[section]) {
      toast('这部分有冲突，请先处理');
      return Promise.resolve();
    }
    return flushAll().then(function (ok) {
      if (ok === false) throw new Error('请先处理未保存或冲突的内容');
      return releaseRelated(section);
    }).then(function () {
      return patchSection(section, value);
    }).then(function () {
      location.reload();
    }).catch(function (err) {
      setSave('err');
      toast(err.message);
    });
  }

  function beginSection(section) {
    if (!section || !S.canEdit) return;
    S.activeSection = section;
    notifyPresence('editing');
    if (!S.leases[section] && !S.locked[section]) {
      ensureLease(section).catch(function (err) {
        var payload = err.payload || {};
        if (payload.code === 'lease_conflict') {
          var holder = payload.holder || {};
          toast('这一部分正在由' + (holder.name || '其他导师') + '编辑，暂时只读');
        }
      });
    }
  }

  function endSection(section) {
    if (!section) return;
    setTimeout(function () {
      var active = sectionForField(document.activeElement);
      if (active === section) return;
      S.activeSection = null;
      flushSection(section).then(function (ok) {
        if (!S.pending[section] || S.conflicts[section]) releaseLease(section);
        notifyPresence();
      });
    }, 0);
  }

  function bindCollabFocus() {
    document.querySelectorAll('#doc [data-path], #parentDoc [data-ppath]').forEach(function (field) {
      field.addEventListener('focusin', function () {
        beginSection(sectionForField(field));
      });
      field.addEventListener('focusout', function () {
        endSection(sectionForField(field));
      });
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
            stageField(field, true);
            return;
          }
          set(S.doc, path, field.value);
          stageField(field, true);
        });
        return;
      }
      if (field.tagName === 'INPUT') {
        field.addEventListener('change', function () {
          var value = field.type === 'number' ? parseInt(field.value, 10) || 1 : field.value;
          set(S.doc, path, value);
          stageField(field, true);
        });
        return;
      }
      field.addEventListener('input', function () {
        /* 旧文档里的富字段可能是纯字符串；首次编辑时升级成 {text, src}，避免写坏结构 */
        if (/\.text$/.test(path)) {
          var parentPath = path.slice(0, -5);
          var parent = get(S.doc, parentPath);
          if (typeof parent === 'string') set(S.doc, parentPath, {text: parent, src: 'mentor'});
        }
        set(S.doc, path, field.textContent || '');
        refreshRichCount(field);
        stageField(field, false);
      });
    });

    var mentor = document.getElementById('mentorNotes');
    if (mentor) {
      mentor.addEventListener('input', function () {
        S.doc.mentor_notes = {text: mentor.value, src: 'edited'};
        /* 契约：internal.mentor_notes 的 patch 就是字段本身。 */
        stagePatch('internal.mentor_notes', {text: mentor.value, src: 'edited'}, false);
      });
    }
    bindCollabFocus();
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
        if (session.teaching_schema === 2) {
          ['purpose', 'personalization', 'student_action', 'expected_attempt', 'support', 'extension'].forEach(function (key) {
            row[key] = {text: '', src: 'mentor'};
          });
          row.input_refs = [];
        }
        var insertAt = activities.length;
        if (insertAt && activities[insertAt - 1].block_review) insertAt -= 1;
        activities.splice(insertAt, 0, row);
        mutateInternalList('internal.session.' + (index + 1) + '.activities', activities);
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
        mutateInternalList('internal.session.' + (index + 1) + '.practice', practices);
        return;
      }
      var activityIndex = parseInt(button.getAttribute('data-a'), 10);
      if (op === 'propose-activity') {
        startProposal(index, activityIndex, button);
        return;
      }
      if (op === 'up' || op === 'down') {
        var acts = session.activities || [];
        var target = op === 'up' ? activityIndex - 1 : activityIndex + 1;
        if (target < 0 || target >= acts.length) return;
        if (acts[activityIndex].block_review || acts[target].block_review) return;
        var swap = acts[target];
        acts[target] = acts[activityIndex];
        acts[activityIndex] = swap;
        mutateInternalList('internal.session.' + (index + 1) + '.activities', acts);
        return;
      }
      if (op === 'del-activity') {
        var rows = session.activities || [];
        if (rows.length <= 1 || rows[activityIndex].block_review) return;
        rows.splice(activityIndex, 1);
        mutateInternalList('internal.session.' + (index + 1) + '.activities', rows);
        return;
      }
      if (op === 'del-practice') {
        var list = session.practice || [];
        var pIndex = parseInt(button.getAttribute('data-p'), 10);
        if (list.length <= 1) return;
        list.splice(pIndex, 1);
        mutateInternalList('internal.session.' + (index + 1) + '.practice', list);
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

  /* ------------------------------------------------- 单项活动替换建议 */
  var REF_LABELS = {
    'brief.student_wish': '学生意愿',
    'brief.student_willingness': '学生意愿程度',
    'brief.topics_to_avoid': '避免的话题',
    'brief.parent_priority': '家长关注',
    'brief.strengths': '优势',
    'brief.learning_need': '学习需要',
    'brief.current_situation': '当前情境',
    'brief.current_response': '当前反应',
    'brief.interests': '兴趣',
    'brief.preferences': '学习偏好',
    'brief.constraints': '限制',
    'brief.teaching_implications': '教学启示',
    'inputs.strengths': '报告 · 积极资源',
    'inputs.needs': '报告 · 主要需求',
    'inputs.context': '报告 · 生活情境',
    'inputs.interests': '报告 · 兴趣偏好'
  };

  function valueText(value) {
    if (value === undefined || value === null) return '';
    if (typeof value === 'string') return value;
    return value.text === undefined || value.text === null ? '' : String(value.text);
  }

  function sourceText(activity) {
    var source = activity.source || {};
    if (source.type === 'world_bank') return 'World Bank · ' + (source.wb_id || '参考课');
    if (source.type === 'other') return source.text || '其他参考';
    return 'AI Original';
  }

  function cmpRow(host, label, text) {
    if (!text) return;
    var row = document.createElement('p');
    var name = document.createElement('b');
    name.className = 'lbl';
    name.textContent = label + '：';
    row.appendChild(name);
    row.appendChild(document.createTextNode(text));
    host.appendChild(row);
  }

  function fillProposalColumn(host, activity) {
    host.innerHTML = '';
    var title = document.createElement('p');
    title.className = 'cmp-t';
    title.textContent = valueText(activity.name) || '未命名活动';
    host.appendChild(title);
    cmpRow(host, '分钟', String(activity.minutes || ''));
    cmpRow(host, '教学目标与理由', valueText(activity.purpose));
    cmpRow(host, '针对这名学生的设计', valueText(activity.personalization));
    cmpRow(host, '步骤', valueText(activity.steps));
    cmpRow(host, '引导问题', valueText(activity.questions));
    cmpRow(host, '材料', valueText(activity.materials));
    cmpRow(host, '学生要做什么', valueText(activity.student_action));
    cmpRow(host, '可观察的尝试', valueText(activity.expected_attempt));
    cmpRow(host, '学生卡住时', valueText(activity.support));
    cmpRow(host, '学生准备好时', valueText(activity.extension));
    cmpRow(host, '参考来源', sourceText(activity));
    var refs = (activity.input_refs || []).map(function (ref) { return REF_LABELS[ref] || ref; });
    if (refs.length) cmpRow(host, '依据', refs.join('、'));
  }

  function cancelProposalById(proposalId) {
    if (!proposalId) return;
    request('POST', API + '/activity-proposals/' + proposalId + '/cancel', {}).catch(function () {});
  }

  function cancelProposal(silent) {
    S.proposalToken = (S.proposalToken || 0) + 1;
    var proposal = S.proposal;
    S.proposal = null;
    if (S.proposalButton) {
      S.proposalButton.disabled = false;
      S.proposalButton = null;
    }
    if (proposal && proposal.status === 'pending') {
      cancelProposalById(proposal.id);
      if (!silent) toast('已取消，文档没有改动');
    }
  }

  function startProposal(sessionIndex, activityIndex, button) {
    if (!S.step2 || !S.doc) return;
    var session = S.doc.sessions[sessionIndex];
    var activity = session && (session.activities || [])[activityIndex];
    if (!activity || activity.block_review) return;

    var token = (S.proposalToken || 0) + 1;
    S.proposalToken = token;
    S.proposal = null;
    S.proposalButton = button;
    if (button) button.disabled = true;

    var stat = document.getElementById('proposalStat');
    var error = document.getElementById('proposalErr');
    var cmp = document.getElementById('proposalCmp');
    var checks = document.getElementById('proposalChecks');
    var checkList = document.getElementById('proposalCheckList');
    var okButton = document.getElementById('proposalOk');
    if (stat) stat.textContent = '正在保存当前修改…';
    if (error) { error.textContent = ''; error.hidden = true; }
    if (cmp) cmp.hidden = true;
    if (checks) { checks.hidden = true; checks.open = false; }
    if (checkList) checkList.innerHTML = '';
    if (okButton) okButton.disabled = true;
    openDialog('proposalDlg', button);

    flushDoc().then(function () {
      return releaseAll();
    }).then(function () {
      if (token !== S.proposalToken) return null;
      if (stat) stat.textContent = '正在生成替换建议…';
      if (!S.versionId) throw new Error('还没有可替换的内部版版本');
      return request('POST', API + '/activity-proposals',
                     {rev: S.rev, source_version_id: S.versionId, activity_id: activity.id});
    }).then(function (data) {
      if (!data) return null;
      return new Promise(function (resolve, reject) {
        pollJob(data.job_id, function (job) { resolve(job); }, function () {
          reject(new Error('生成建议失败'));
        });
      });
    }).then(function (job) {
      if (!job) return null;
      if (token !== S.proposalToken) {
        cancelProposalById(job.proposal_id);
        return null;
      }
      if (!job.proposal_id) throw new Error('没有拿到替换建议');
      return request('GET', API + '/activity-proposals/' + job.proposal_id).then(function (data) {
        if (token !== S.proposalToken) return null;
        var proposal = data.proposal || {};
        S.proposal = proposal;
        var oldActivity = S.doc.sessions[sessionIndex].activities[activityIndex];
        fillProposalColumn(document.getElementById('proposalOld'), oldActivity);
        fillProposalColumn(document.getElementById('proposalNew'), proposal.candidate || {});
        (proposal.checks || []).forEach(function (item) {
          var row = document.createElement('p');
          row.className = 'hint';
          row.textContent = (item.label || '提示') + '：' + (item.text || '');
          checkList.appendChild(row);
        });
        if (checks) checks.hidden = !(proposal.checks || []).length;
        if (cmp) cmp.hidden = false;
        if (stat) stat.textContent = '建议已生成。应用前不会改动文档。';
        if (okButton) okButton.disabled = false;
        return null;
      });
    }).catch(function (err) {
      if (token !== S.proposalToken) return;
      if (stat) stat.textContent = '没有生成建议，文档未改动。';
      if (error) {
        error.textContent = err.message || '生成建议失败';
        error.hidden = false;
      }
      if (button) button.disabled = false;
    });
  }

  var proposalOk = document.getElementById('proposalOk');
  if (proposalOk) {
    proposalOk.addEventListener('click', function () {
      var proposal = S.proposal;
      if (!proposal) return;
      proposalOk.disabled = true;
      var error = document.getElementById('proposalErr');
      var stat = document.getElementById('proposalStat');
      if (error) { error.textContent = ''; error.hidden = true; }
      releaseAll().then(function () {
        return request('POST', API + '/activity-proposals/' + proposal.id + '/accept',
                {rev: S.rev, source_version_id: proposal.source_version_id, activity_id: proposal.activity_id});
      }).then(function () {
          S.proposal = null;
          closeDialog('proposalDlg');
          location.reload();
        }).catch(function (err) {
          if (stat) stat.textContent = '未应用替换，文档没有改动。';
          if (error) {
            error.textContent = err.status === 409
              ? '这条建议已过期。关闭后可以重新替换；当前文档没有改动。'
              : (err.message || '应用失败');
            error.hidden = false;
          }
          proposalOk.disabled = err.status === 409;
        });
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
    if (!field) {
      /* 节级或时长提示没有独立的可编辑字段：定位到本节 / 本节时长行 / 对应活动 */
      var match = /^sessions\.(\d+)(?:\.activities\.(\d+))?/.exec(path);
      if (match) {
        var session = document.querySelector('#doc [data-session="' + match[1] + '"]');
        if (session) {
          if (match[2] !== undefined) field = session.querySelector('.act[data-a="' + match[2] + '"]');
          if (!field && /\.timing(\.|$)/.test(path)) field = session.querySelector('[data-timing]');
          if (!field) field = session;
        }
      }
    }
    if (!field) { toast('这一处可能在文档其他地方，请手动查找'); return; }
    var details = field.closest ? field.closest('details') : null;
    if (details) details.open = true;
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
    if (id === 'proposalDlg') cancelProposal(false);
  }

  function closeOnBackdrop(box) {
    if (!box) return;
    box.addEventListener('click', function (event) {
      if (event.target === box || event.target.closest('[data-close]')) closeDialog(box.id);
    });
  }
  ['approveDlg', 'reopenDlg', 'regenDlg', 'proposalDlg', 'verDlg', 'parentConfirmDlg', 'parentRegenDlg'].forEach(function (id) { closeOnBackdrop(dialog(id)); });

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
      setApproveError('');
      openDialog('approveDlg', approveBtn);
    });
  }

  function setApproveError(message) {
    var el = document.getElementById('approveErr');
    if (!el) return;
    el.textContent = message || '';
    el.hidden = !message;
  }

  var approveOk = document.getElementById('approveOk');
  if (approveOk) {
    approveOk.addEventListener('click', function () {
      approveOk.disabled = true;
      setApproveError('');
      flushDirect().then(function () {
        return flushAll();
      }).then(function (ok) {
        if (ok === false) throw new Error('还有未保存或冲突的内容，先处理后再批准');
        return releaseAll();
      }).then(function () {
        return request('POST', API + '/approve', {rev: S.rev, version_id: S.versionId || undefined});
      }).then(function () {
        location.reload();
      }).catch(function (err) {
        approveOk.disabled = false;
        setApproveError(err.message || '请求失败');
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
      releaseAll().then(function () {
        return request('POST', API + '/reopen', {rev: S.rev});
      }).then(function () {
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
        || S.parentStale || (S.parentBlocking || []).length > 0;
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
    return flushAll().then(function (ok) {
      if (ok === false) throw new Error('还有未保存或冲突的内容');
      setParentSave('ok');
      if (reload) location.reload();
      return null;
    }).catch(function (err) {
      setParentSave('err');
      toast(err.message);
      throw err;
    });
  }

  function mutateParentList(section, value, reload) {
    if (!S.parentEditable || !S.parentDoc) return Promise.resolve();
    if (S.conflicts[section]) {
      toast('这部分有冲突，请先处理');
      return Promise.resolve();
    }
    return flushAll().then(function (ok) {
      if (ok === false) throw new Error('请先处理未保存或冲突的内容');
      return patchSection(section, value);
    }).then(function () {
      setParentSave('ok');
      if (reload) location.reload();
    }).catch(function (err) {
      setParentSave('err');
      toast(err.message);
    });
  }

  function markFamilySeen(index) {
    if (!S.parentEditable || !S.parentDoc || S.revoked || !S.canEdit) return Promise.resolve();
    /* 先把家庭建议自身的修改保存掉，再确认；否则 ack 的 hash 会与服务器
       最新内容不符。 */
    return flushSection('parent.family').then(function (ok) {
      if (ok === false) {
        toast('请先保存或处理家庭建议的修改，再点「已看过」');
        return false;
      }
      var target = parseInt(index, 10);
      var node = document.querySelector('[data-family="' + target + '"]');
      if (node && document.activeElement === node) {
        toast('请先移出家庭建议编辑框，再点「已看过」');
        return false;
      }
      /* 服务器已有更新正文但界面还没显示时，禁止用旧 hash 确认。 */
      if (familyRemoteDiffers(target)) {
        toast('家庭建议已在别处更新，正在载入最新内容…');
        refreshFamilyAdvice();
        return false;
      }
      var seen = (S.familySeen || [false, false]).slice();
      if (index !== undefined && index !== null) seen[parseInt(index, 10)] = true;
      else seen = [true, true];
      /* 只确认当前真正显示出来的那两个 hash，绝不使用服务器最新 hash。 */
      var hashes = (S.familyHashes || []).slice();
      if (hashes.length !== 2 || hashes.some(function (item) { return !item; })) {
        toast('家庭建议状态未就绪，请刷新后再确认');
        return false;
      }
      /* family 正文变化会连带 bump family_seen 的依赖版本；确认内容由
         hashes 校验，因此这里用已知最新版本，让后端直接返回
         stale_family_ack 或接受，而不是先以 stale_section 建冲突卡片。 */
      var ackVersion = Math.max(Number(S.sections['parent.family_seen']) || 0,
                                Number(S.knownVersions['parent.family_seen']) || 0);
      var ackPatch = {seen: seen, hashes: hashes};
      var ackKey = idemKey('parent.family_seen');
      return patchSection('parent.family_seen', ackPatch, ackKey, {
        patch: ackPatch,
        expected_version: ackVersion,
        document_version: S.docVersion,
        idempotency_key: ackKey
      })
        .then(function () {
          S.familySeen = seen;
          updateFamilyBadges();
          setParentSave('ok');
          return true;
        }).catch(function (err) {
          var payload = err.payload || {};
          if (payload.code === 'stale_family_ack') {
            /* handlePatchError 已触发 refreshFamilyAdvice；这里不采纳新 hash、
               不自动确认，等界面显示最新建议后由用户再次点击。 */
            return false;
          }
          toast(err.message);
          return false;
        });
    });
  }

  if (parentDocEl && S.parentEditable) {
    parentDocEl.querySelectorAll('[data-ppath]').forEach(function (field) {
      field.addEventListener('input', function () {
        var path = field.getAttribute('data-ppath');
        set(S.parentDoc, path, {text: field.textContent || '', src: 'edited'});
        stageField(field, false);
      });
      field.addEventListener('focusout', function () {
        var path = field.getAttribute('data-ppath') || '';
        var match = /^family\.(\d+)$/.exec(path);
        if (match) adoptFamilyRemoteIfClean(parseInt(match[1], 10));
      });
    });
  }

  document.querySelectorAll('[data-family-seen]').forEach(function (button) {
    button.addEventListener('click', function () {
      markFamilySeen(parseInt(button.getAttribute('data-family-seen'), 10));
    });
  });

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
      mutateParentList('parent.practice', picks, false);
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
      mutateParentList('parent.review', rows, true);
    });
  }

  document.querySelectorAll('[data-pp-del-review]').forEach(function (button) {
    button.addEventListener('click', function () {
      if (!S.parentEditable || !S.parentDoc) return;
      var rows = S.parentDoc.review || [];
      if (rows.length <= 2) { toast('至少保留 2 项成长观察'); return; }
      rows.splice(parseInt(button.getAttribute('data-pp-del-review'), 10), 1);
      mutateParentList('parent.review', rows, true);
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
      flushDirect().then(function () {
        return flushAll();
      }).then(function (ok) {
        if (ok === false) throw new Error('还有未保存或冲突的内容');
        return releaseAll();
      }).then(function () {
        return request('POST', API + '/parent/confirm', {rev: S.rev});
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
      flushDirect().then(function () {
        return flushAll();
      }).then(function (ok) {
        if (ok === false) throw new Error('还有未保存或冲突的内容');
        return releaseAll();
      }).then(function () {
        return request('POST', API + '/parent/export', {rev: S.rev});
      }).then(function (data) {
        parentSetStatus((data.plan || {}).parent_status || 'exported');
        window.open(parentPrintUrl() + '?print=1', '_blank');
        location.reload();
      }).catch(function (err) {
        toast(err.message === '请求失败' ? '导出失败，请重试' : err.message);
        updateParentActions();
      });
    });
  }

  updateParentActions();
  renderParentChecks();
})();
