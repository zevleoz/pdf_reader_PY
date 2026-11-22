/* M1R-P6：报告预览里直接修改；需要核对的地方逐处提示。 */
(function () {
  'use strict';
  var dataNode = document.getElementById('editData');
  if (!dataNode) return;
  var data = JSON.parse(dataNode.textContent);
  var checks = data.checks || [];
  var targets = [];
  var current = -1;
  var reportSave = window.M1ReportSave;
  var pendingFields = new Set();
  var pendingTags = new Map();
  var lockedControls = new Map();
  var reloadNeeded = false;
  var locked = false;
  var exporting = false;
  var host = null;
  var saves;

  var bar = {
    saved: document.getElementById('editSaved'),
    retry: document.getElementById('editRetry'),
    export: document.getElementById('editExport'),
    msg: document.getElementById('editMsg'),
    ack: document.getElementById('editAck'),
    count: document.getElementById('editCount'),
    prev: document.getElementById('editPrev'),
    next: document.getElementById('editNext'),
    more: document.getElementById('editMore'),
    banner: document.getElementById('editBanner')
  };

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function setSaved(text, bad) {
    bar.saved.textContent = text;
    bar.saved.style.color = bad ? '#b42318' : '';
  }

  function pathOf(node) {
    return JSON.parse(node.getAttribute('data-path') || node.getAttribute('data-tags-path') || '[]');
  }

  function startsWith(path, prefix) {
    if (!prefix.length || prefix.length > path.length) return false;
    for (var i = 0; i < prefix.length; i += 1) {
      if (String(path[i]) !== String(prefix[i])) return false;
    }
    return true;
  }

  function onUnload(event) {
    event.preventDefault();
    event.returnValue = '';
  }

  function sync(snapshot, parentAction) {
    if (!host) {
      if (snapshot.dirty || snapshot.pending) window.addEventListener('beforeunload', onUnload);
      else window.removeEventListener('beforeunload', onUnload);
    }
    if (snapshot.fault) setSaved(snapshot.fault.message || '保存失败', true);
    else if (snapshot.saving) setSaved('保存中…');
    else setSaved(snapshot.dirty ? '有未保存的修改' : '已保存');
    bar.retry.hidden = !snapshot.fault || snapshot.fault.status === 409;
    if (reloadNeeded && !exporting && !parentAction && !snapshot.pending
        && !snapshot.dirty && !snapshot.saving && !snapshot.fault) {
      reloadNeeded = false;
      if (host) host.refresh();
      else window.location.reload();
    }
  }

  function refresh() {
    reloadNeeded = true;
  }

  function lock(value) {
    if (value === locked) return;
    locked = value;
    document.querySelectorAll('[data-path]').forEach(function (node) {
      node.contentEditable = locked ? 'false' : node.__editableMode;
    });
    if (locked) {
      document.querySelectorAll('article button, article select, article input, #editExport')
        .forEach(function (control) {
          lockedControls.set(control, control.disabled);
          control.disabled = true;
        });
    } else {
      lockedControls.forEach(function (disabled, control) { control.disabled = disabled; });
      lockedControls.clear();
    }
  }

  function updateChecks(next) {
    checks = next;
    render();
  }

  function render() {
    var nodes = Array.prototype.slice.call(document.querySelectorAll('[data-path],[data-tags-path]'));
    nodes.forEach(function (node) { node.classList.remove('needs-check', 'current'); node.__checks = null; });
    var banner = [];
    var reviews = [];
    targets = [];
    checks.forEach(function (check) {
      if (check.level !== 'block') { reviews.push(check); return; }
      var path = check.path || [];
      var best = null;
      var bestLength = 0;
      nodes.forEach(function (node) {
        var prefix = pathOf(node);
        if (startsWith(path, prefix) && prefix.length > bestLength) { best = node; bestLength = prefix.length; }
      });
      if (!best) { banner.push(check); return; }
      if (!best.__checks) { best.__checks = []; targets.push(best); }
      best.__checks.push(check);
    });
    targets.sort(function (a, b) {
      return a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
    });
    targets.forEach(function (node) { node.classList.add('needs-check'); });

    bar.banner.textContent = '';
    banner.forEach(function (check) { bar.banner.appendChild(el('div', '', check.message || '')); });
    bar.banner.hidden = banner.length === 0;

    bar.more.hidden = reviews.length === 0;
    bar.more.textContent = '其他提示 ' + reviews.length + ' 条（仅供参考）';
    bar.more.onclick = function () {
      var open = bar.banner.getAttribute('data-reviews') === '1';
      bar.banner.setAttribute('data-reviews', open ? '0' : '1');
      render();
    };
    if (bar.banner.getAttribute('data-reviews') === '1') {
      reviews.forEach(function (check) { bar.banner.appendChild(el('div', 'sub', '提示：' + (check.message || ''))); });
      bar.banner.hidden = bar.banner.childNodes.length === 0;
    }

    if (current >= targets.length) current = targets.length - 1;
    showCurrent(false);
  }

  function showCurrent(scroll) {
    var total = targets.length;
    bar.count.textContent = total ? ('报告还不完整：' + total + ' 处') : '没有必须补全的地方';
    bar.prev.disabled = !total;
    bar.next.disabled = !total;
    targets.forEach(function (node) { node.classList.remove('current'); });
    bar.ack.hidden = true;
    if (current < 0 || !targets[current]) { bar.msg.textContent = ''; return; }
    var node = targets[current];
    node.classList.add('current');
    bar.msg.textContent = '第 ' + (current + 1) + '/' + total + ' 处：' +
      node.__checks.map(function (c) { return c.message; }).join('；');
    if (scroll) node.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }

  function step(delta) {
    if (!targets.length) return;
    current = (current + delta + targets.length) % targets.length;
    showCurrent(true);
  }

  function send(url, method, body) {
    return saves.add(url, method, body).then(function (json) {
      updateChecks(json.checks || []);
      return json;
    });
  }

  function planValue() {
    var rows = {};
    document.querySelectorAll('[data-plan-key]').forEach(function (node) {
      var index = node.getAttribute('data-plan-index');
      rows[index] = rows[index] || {};
      rows[index][node.getAttribute('data-plan-key')] = node.innerText.trim();
    });
    document.querySelectorAll('[data-plan-ability-select]').forEach(function (node) {
      var index = node.getAttribute('data-plan-index');
      rows[index] = rows[index] || {};
      rows[index].ability = node.value;
    });
    return Object.keys(rows).sort(function (a, b) { return a - b; }).map(function (k) { return rows[k]; });
  }

  function savePlan(plan) {
    return send('/doc', 'PUT', { changes: [{ path: ['plan'], value: plan || planValue() }] });
  }

  function flushField(node) {
    pendingFields.delete(node);
    var text = node.innerText.trim();
    if (text !== node.__lastQueued) {
      node.__lastQueued = text;
      if (node.hasAttribute('data-plan-index')) savePlan();
      else send('/doc', 'PUT', { changes: [{ path: pathOf(node), value: text }] });
    }
    saves.setDirty(node, false);
  }

  function collect() {
    var active = document.activeElement;
    if (active && active.hasAttribute('data-path')) flushField(active);
    pendingFields.forEach(flushField);
    pendingTags.forEach(function (save) { save(); });
  }

  document.querySelectorAll('[data-plan-ability-select]').forEach(function (node) {
    node.addEventListener('change', function () {
      refresh();
      var index = node.getAttribute('data-plan-index');
      document.querySelectorAll('[data-plan-key][data-plan-index="' + index + '"]').forEach(
        function (cell) { cell.setAttribute('data-plan-ability', node.value); });
      savePlan();
    });
  });

  document.querySelectorAll('.plan-del').forEach(function (button) {
    button.addEventListener('click', function () {
      if (button.disabled) return;
      refresh();
      var plan = planValue();
      plan.splice(Number(button.getAttribute('data-plan-index')), 1);
      savePlan(plan);
    });
  });

  var addButton = document.getElementById('planAdd');
  if (addButton) {
    addButton.addEventListener('click', function () {
      if (addButton.disabled) return;
      addButton.disabled = true;
      collect();
      refresh();
      var plan = planValue();
      plan.push({ ability: 'R1.1', goal: '', mentor: '', family: '', evidence: '' });
      savePlan(plan);
    });
  }

  document.querySelectorAll('[data-path]').forEach(function (node) {
    node.__lastQueued = node.innerText.trim();
    node.__editableMode = node.contentEditable;
    node.addEventListener('focus', function () { node.__before = node.innerText.trim(); });
    node.addEventListener('input', function () {
      var changed = node.innerText.trim() !== node.__lastQueued;
      if (changed) pendingFields.add(node);
      else pendingFields.delete(node);
      saves.setDirty(node, changed);
    });
    node.addEventListener('blur', function () { flushField(node); });
    node.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') { node.innerText = node.__before || ''; node.blur(); }
    });
  });

  document.querySelectorAll('[data-tags-path]').forEach(function (cell) {
    var button = el('button', 'tag-edit', '改标签');
    button.type = 'button';
    cell.appendChild(button);
    button.addEventListener('click', function () {
      var open = cell.querySelector('.tag-pop');
      if (open) {
        pendingTags.delete(open);
        saves.setDirty(open, false);
        open.remove();
        return;
      }
      var chosen = JSON.parse(cell.getAttribute('data-tags') || '[]');
      var pop = el('div', 'tag-pop');
      (data.tags || []).forEach(function (tag) {
        var label = el('label');
        var box = el('input');
        box.type = 'checkbox';
        box.value = tag;
        box.checked = chosen.indexOf(tag) >= 0;
        label.appendChild(box);
        label.appendChild(document.createTextNode(' ' + tag));
        pop.appendChild(label);
      });
      var save = el('button', 'tag-edit', '保存标签');
      save.type = 'button';
      function selectedTags() {
        return Array.from(pop.querySelectorAll('input:checked')).map(function (box) {
          return box.value;
        });
      }
      function saveTags() {
        var value = selectedTags();
        var changed = value.length !== chosen.length || value.some(function (tag) {
          return chosen.indexOf(tag) === -1;
        });
        if (changed) {
          refresh();
          send('/doc', 'PUT', { changes: [{ path: pathOf(cell), value: value }] });
          chosen = value;
          cell.setAttribute('data-tags', JSON.stringify(value));
        }
        pendingTags.delete(pop);
        saves.setDirty(pop, false);
      }
      pop.addEventListener('change', function () {
        pendingTags.set(pop, saveTags);
        saves.setDirty(pop, true);
      });
      save.addEventListener('click', saveTags);
      pop.appendChild(save);
      cell.appendChild(pop);
    });
  });

  try {
    if (window.parent !== window && window.parent.location.origin === window.location.origin
        && window.parent.M1ReportWorkspace) {
      host = window.parent.M1ReportWorkspace.attach(window, data, {
        collect: collect, lock: lock, sync: sync, checks: updateChecks, refresh: refresh
      });
    }
  } catch (error) { /* A cross-origin embed uses the standalone save queue. */ }
  saves = host ? host.saves : reportSave.create(data.api, sync);
  if (!host) saves.reset(data.rev, data.version_id);
  sync(saves.snapshot(), false);

  bar.retry.addEventListener('click', saves.retry);
  bar.export.addEventListener('mousedown', function (event) {
    // Collect the focused field in the click handler. A blur on pointer down can
    // change the save status and move the toolbar before the click is delivered.
    if (event.button === 0 && document.activeElement.hasAttribute('data-path')) {
      event.preventDefault();
    }
  });
  bar.export.addEventListener('click', async function (event) {
    if (exporting || event.detail > 1) return;
    if (host) {
      host.exportReport();
      return;
    }
    exporting = true;
    var popup = null;
    try {
      popup = reportSave.openPrintTab();
      collect();
      lock(true);
      var pin = await saves.flush();
      popup.location.replace(reportSave.printUrl(bar.export.dataset.exportUrl, pin));
    } catch (error) {
      if (popup) popup.close();
      setSaved(error.message || '保存失败，无法导出。', true);
    } finally {
      exporting = false;
      lock(false);
    }
  });

  bar.prev.addEventListener('click', function () { step(-1); });
  bar.next.addEventListener('click', function () { step(1); });
  render();
  if (targets.length) { current = 0; showCurrent(false); }
})();
