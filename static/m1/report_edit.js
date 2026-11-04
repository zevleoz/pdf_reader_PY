/* M1R-P6：报告预览里直接修改；需要核对的地方逐处提示。 */
(function () {
  'use strict';
  var dataNode = document.getElementById('editData');
  if (!dataNode) return;
  var data = JSON.parse(dataNode.textContent);
  var rev = data.rev;
  var checks = data.checks || [];
  var targets = [];
  var current = -1;
  var queue = Promise.resolve();

  var bar = {
    saved: document.getElementById('editSaved'),
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

  function notifyParent() {
    if (window.parent && window.parent !== window) {
      window.parent.postMessage({ type: 'm1-report-edit', rev: rev }, window.location.origin);
    }
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
    queue = queue.then(function () {
      setSaved('保存中…');
      body.rev = rev;
      return fetch(url, {
        method: method, credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
      }).then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (json) {
          if (res.ok && json.ok) {
            rev = json.rev;
            checks = json.checks || [];
            setSaved('已保存');
            render();
            notifyParent();
            return json;
          }
          if (res.status === 409 && json.rev) {
            setSaved('这份报告刚在别处改过，请刷新页面后再改。', true);
          } else {
            setSaved(json.error || '保存失败', true);
          }
          return null;
        });
      }).catch(function () {
        setSaved('保存失败，请检查网络后再试。', true);
        return null;
      });
    });
    return queue;
  }

  function planValue() {
    var rows = {};
    document.querySelectorAll('[data-plan-index]').forEach(function (node) {
      var index = node.getAttribute('data-plan-index');
      rows[index] = rows[index] || { ability: node.getAttribute('data-plan-ability') };
      rows[index][node.getAttribute('data-plan-key')] = node.innerText.trim();
    });
    return Object.keys(rows).sort(function (a, b) { return a - b; }).map(function (k) { return rows[k]; });
  }

  document.querySelectorAll('[data-path]').forEach(function (node) {
    node.addEventListener('focus', function () { node.__before = node.innerText.trim(); });
    node.addEventListener('blur', function () {
      var text = node.innerText.trim();
      if (text === node.__before) return;
      node.__before = text;
      if (node.hasAttribute('data-plan-index')) {
        send(data.api + '/doc', 'PUT', { changes: [{ path: ['plan'], value: planValue() }] });
      } else {
        send(data.api + '/doc', 'PUT', { changes: [{ path: pathOf(node), value: text }] });
      }
    });
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
      if (open) { open.remove(); return; }
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
      save.addEventListener('click', function () {
        var value = Array.prototype.slice.call(pop.querySelectorAll('input:checked'))
          .map(function (box) { return box.value; });
        send(data.api + '/doc', 'PUT', { changes: [{ path: pathOf(cell), value: value }] })
          .then(function (json) { if (json) window.location.reload(); });
      });
      pop.appendChild(save);
      cell.appendChild(pop);
    });
  });

  var exportBtn = document.getElementById('editExport');
  if (exportBtn) {
    exportBtn.addEventListener('click', function () {
      if (exportBtn.disabled) return;
      exportBtn.disabled = true;
      var active = document.activeElement;
      if (active && active.hasAttribute && active.hasAttribute('data-path')) active.blur();
      var pending = queue;
      pending.then(function (json) {
        if (json === null) {
          exportBtn.disabled = false;
          return;
        }
        window.location.href = exportBtn.getAttribute('data-export-url');
      }, function () {
        exportBtn.disabled = false;
      });
    });
  }

  bar.prev.addEventListener('click', function () { step(-1); });
  bar.next.addEventListener('click', function () { step(1); });
  render();
  if (targets.length) { current = 0; showCurrent(false); }
})();
