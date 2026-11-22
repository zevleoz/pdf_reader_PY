/* Report write queue shared by the workspace and its same-origin print editor. */
(function () {
  'use strict';

  var conflictMessage = '报告已在别处更新。请复制未保存的文字，刷新后重新核对。';

  async function request(url, options) {
    var response;
    try {
      response = await fetch(url, options);
    } catch (cause) {
      var networkError = new Error('无法连接服务器，尚未确认保存结果。请重试。');
      networkError.uncertain = true;
      throw networkError;
    }
    var body = await response.json().catch(function () { return {}; });
    if (!response.ok || body.ok !== true) {
      var error = new Error(body.error || '无法确认服务器已保存，请重试。');
      error.status = response.status;
      error.uncertain = response.ok || response.status >= 500;
      error.body = body;
      throw error;
    }
    return body;
  }

  function json(method, body) {
    return {
      method: method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    };
  }

  function writeId() {
    if (crypto.randomUUID) return crypto.randomUUID();
    var bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    var hex = Array.from(bytes, function (byte) { return byte.toString(16).padStart(2, '0'); }).join('');
    return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16),
            hex.slice(16, 20), hex.slice(20)].join('-');
  }

  function editKey(endpoint, body) {
    if (endpoint === '/doc') return endpoint + JSON.stringify(body.changes[0].path);
    return endpoint;
  }

  function canCorrect(fault) {
    return fault && (fault.status === 400 || fault.status === 413 || fault.status === 422);
  }

  function create(api, onChange, onSaved) {
    var pin;
    var queue = [];
    var dirty = new Set();
    var work = null;
    var fault = null;

    function snapshot() {
      return { pin: pin, saving: work !== null, pending: queue.length > 0,
               dirty: dirty.size > 0, fault: fault };
    }

    function signal() {
      onChange(snapshot());
    }

    function conflict() {
      fault = new Error(conflictMessage);
      fault.status = 409;
      signal();
    }

    function reset(rev, versionId) {
      if (work || queue.length || dirty.size || fault) return false;
      pin = { expected_rev: rev, version_id: versionId };
      return true;
    }

    function setDirty(source, changed) {
      if (changed) dirty.add(source);
      else dirty.delete(source);
      signal();
    }

    function sameReport(body) {
      var current = body.report;
      return current && current.rev === pin.expected_rev
        && (current.current_version_id || null) === (pin.version_id || null);
    }

    function send(item) {
      var fields = { rev: pin.expected_rev, write_id: item.id };
      if (item.body instanceof FormData) {
        item.body.set('rev', fields.rev);
        item.body.set('write_id', fields.write_id);
        return request(api + item.endpoint, { method: item.method, body: item.body });
      }
      return request(api + item.endpoint, json(item.method, Object.assign({}, item.body, fields)));
    }

    async function sendOrReconcile(item) {
      if (!item.uncertain) return send(item);
      var saved = await request(api + '?write_id=' + encodeURIComponent(item.id), { cache: 'no-store' });
      if (!saved.can_edit) {
        var denied = new Error('编辑权限已变更，请保留未保存的文字。');
        denied.status = 403;
        throw denied;
      }
      if (saved.write_rev != null && saved.write_rev === saved.report.rev
          && (saved.report.current_version_id || null) === (pin.version_id || null)) {
        return saved;
      }
      if (saved.write_rev != null || !sameReport(saved)) {
        var changed = new Error(conflictMessage);
        changed.status = 409;
        throw changed;
      }
      try {
        return await send(item);
      } catch (error) {
        if (error.status !== 409) throw error;
        // The original request may have finished between reading its receipt and retrying.
        var latest = await request(api + '?write_id=' + encodeURIComponent(item.id),
                                   { cache: 'no-store' });
        if (latest.can_edit && latest.write_rev === latest.report.rev
            && (latest.report.current_version_id || null) === (pin.version_id || null)) {
          return latest;
        }
        throw error;
      }
    }

    async function drain() {
      while (queue.length && !fault) {
        var item = queue[0];
        var body;
        try {
          body = await sendOrReconcile(item);
          var rev = body.report ? body.report.rev : body.rev;
          var versionId = body.report ? body.report.current_version_id : (body.version_id || pin.version_id);
          if (rev !== pin.expected_rev + 1 || (versionId || null) !== (pin.version_id || null)) {
            throw new Error('服务器未确认预期的保存修订，请重试。');
          }
        } catch (error) {
          item.uncertain = item.uncertain || !error.status || error.uncertain;
          fault = error;
          if (fault.status === 409) fault.message = conflictMessage;
          break;
        }
        pin = { expected_rev: rev, version_id: versionId };
        var result = Object.assign({}, body, {
          rev: pin.expected_rev,
          status: body.report ? body.report.status : body.status,
          version_id: pin.version_id
        });
        queue.shift();
        if (onSaved) onSaved(result, item);
        item.resolve(result);
      }
    }

    function start() {
      if (work || fault || !queue.length) return;
      work = Promise.resolve().then(drain).finally(function () {
        work = null;
        signal();
        var rejected = fault && queue[0];
        if (rejected && rejected.onFailure) {
          rejected.onFailure(fault, canCorrect(fault) && !rejected.uncertain);
        }
      });
      signal();
    }

    function add(endpoint, method, body, onFailure) {
      return new Promise(function (resolve) {
        var key = editKey(endpoint, body);
        var item = { endpoint: endpoint, method: method, body: body, key: key,
                     id: writeId(), resolve: resolve, onFailure: onFailure };
        if (canCorrect(fault) && queue[0].key === key && !queue[0].uncertain) {
          // A corrected field supersedes its rejected value. A write with an
          // uncertain commit must be reconciled with its original payload.
          var replaced = queue.filter(function (entry) { return entry.key === key; });
          queue = [item].concat(queue.filter(function (entry) { return entry.key !== key; }));
          item.resolve = function (result) {
            replaced.forEach(function (entry) { entry.resolve(result); });
            resolve(result);
          };
          fault = null;
        } else {
          queue.push(item);
        }
        start();
        signal();
      });
    }

    async function flush() {
      while (work) await work;
      if (fault) throw fault;
      if (queue.length || dirty.size) throw new Error('还有未保存的内容。');
      return pin;
    }

    function retry() {
      if (!fault || fault.status === 409) return;
      fault = null;
      start();
    }

    return { add: add, conflict: conflict, flush: flush, reset: reset,
             retry: retry, setDirty: setDirty, snapshot: snapshot };
  }

  function openPrintTab() {
    var tab = window.open('', '_blank');
    if (!tab) throw new Error('请允许打开打印预览窗口。');
    tab.document.title = '正在准备打印预览…';
    var status = tab.document.createElement('p');
    status.textContent = '正在保存并准备打印预览…';
    status.style.cssText = 'font: 16px system-ui; margin: 40px';
    tab.document.body.appendChild(status);
    tab.opener = null;
    return tab;
  }

  function printUrl(url, pin) {
    var destination = new URL(url, window.location.origin);
    destination.searchParams.set('expected_rev', pin.expected_rev);
    destination.searchParams.set('version_id', pin.version_id);
    return destination.href;
  }

  window.M1ReportSave = { create: create, json: json, request: request,
                          openPrintTab: openPrintTab, printUrl: printUrl };
})();
