/* M1 首页：会前准备列表 + 新建（学生选择器）。 */
(function () {
  'use strict';

  var root = document.getElementById('m1Home');
  if (!root) return;

  var prepRows = document.getElementById('prepRows');
  var newBtn = document.getElementById('newPrep');
  var preselected = root.getAttribute('data-student-id') || '';
  var state = { preps: [], students: [] };

  var STATUS = {
    draft: { label: '草稿', cls: 'warn' },
    generating: { label: '生成中', cls: 'info' },
    review: { label: '待审阅', cls: 'brand' },
    final: { label: '已定稿', cls: 'ok' }
  };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
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

  function fmtDate(value) {
    return value ? String(value).slice(0, 10) : '';
  }

  function sortPreps(rows) {
    return rows.slice().sort(function (a, b) {
      var da = a.meeting_date || '9999-99-99';
      var db = b.meeting_date || '9999-99-99';
      if (da !== db) return da < db ? -1 : 1;
      return String(b.updated_at || '').localeCompare(String(a.updated_at || ''));
    });
  }

  function openPrint(prep) {
    var tab = window.open('', '_blank');
    api('/api/m1/preps/' + prep.id + '/export', { method: 'POST' }).then(function () {
      var url = '/m1/preps/' + prep.id + '/print';
      if (tab) tab.location.href = url;
      else window.open(url, '_blank', 'noopener');
    }).catch(function (error) {
      if (tab) tab.close();
      toast(error.message, 'error');
    });
  }

  function renderRows() {
    prepRows.textContent = '';
    if (!state.preps.length) {
      var empty = el('tr');
      var td = el('td', 'sub', '还没有会前准备。点右上角「＋ 新建会前准备」开始。');
      td.setAttribute('colspan', '6');
      td.style.padding = '16px';
      empty.appendChild(td);
      prepRows.appendChild(empty);
      return;
    }
    sortPreps(state.preps).forEach(function (prep) {
      var status = STATUS[prep.status] || { label: prep.status, cls: '' };
      var tr = el('tr', 'click');
      tr.setAttribute('data-prep', prep.id);
      tr.setAttribute('data-status', prep.status);

      var who = el('td', 'who');
      who.appendChild(el('b', '', prep.student_name || ''));
      who.appendChild(el('small', '', [prep.grade, prep.school].filter(Boolean).join(' · ')));
      tr.appendChild(who);

      var dateTd = el('td');
      if (prep.meeting_date) dateTd.textContent = fmtDate(prep.meeting_date);
      else dateTd.appendChild(el('span', 'sub', '未安排'));
      tr.appendChild(dateTd);

      tr.appendChild(el('td', '', prep.mentor_name || '—'));

      var statusTd = el('td');
      var pill = el('span', 'pill ' + status.cls);
      if (status.cls) pill.appendChild(el('span', 'dot'));
      pill.appendChild(document.createTextNode(status.label));
      statusTd.appendChild(pill);
      tr.appendChild(statusTd);

      tr.appendChild(el('td', 'sub', window.y4FmtDT ? window.y4FmtDT(prep.updated_at) : (prep.updated_at || '—')));

      var actionTd = el('td');
      actionTd.style.textAlign = 'right';
      var action = el('button', 'btn sm' + (prep.status === 'final' ? '' : ' pri'),
        prep.status === 'final' ? '预览 / 下载 PDF' : (prep.status === 'review' ? '查看' : '继续'));
      action.setAttribute('type', 'button');
      action.addEventListener('click', function (event) {
        event.stopPropagation();
        if (prep.status === 'final') openPrint(prep);
        else window.location.href = '/m1/preps/' + prep.id;
      });
      actionTd.appendChild(action);
      tr.appendChild(actionTd);

      tr.addEventListener('click', function () {
        if (prep.status === 'final') openPrint(prep);
        else window.location.href = '/m1/preps/' + prep.id;
      });
      prepRows.appendChild(tr);
    });
  }

  function closeModal() {
    var host = document.getElementById('m1ModalHost');
    if (host) host.textContent = '';
    document.removeEventListener('keydown', onKey);
  }

  function onKey(event) {
    if (event.key === 'Escape') closeModal();
  }

  function openPicker() {
    var host = document.getElementById('m1ModalHost');
    host.textContent = '';
    var scrim = el('div', 'm1-scrim');
    scrim.id = 'm1Scrim';
    var modal = el('div', 'modal');
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-labelledby', 'pkH');
    modal.style.width = 'min(520px, 100%)';

    var head = el('div', 'head');
    head.appendChild(el('h2', '', '为哪位学生准备？')).id = 'pkH';
    modal.appendChild(head);

    var body = el('div', 'body');
    body.style.display = 'grid';
    body.style.gap = '10px';
    var search = el('input', 'inp modal-search');
    search.setAttribute('placeholder', '搜索姓名或 Y4 编号');
    search.setAttribute('aria-label', '搜索学生');
    body.appendChild(search);

    var list = el('div');
    list.style.display = 'grid';
    list.style.gap = '8px';
    body.appendChild(list);
    modal.appendChild(body);

    var foot = el('div', 'foot');
    var cancel = el('button', 'btn', '取消');
    cancel.setAttribute('type', 'button');
    cancel.addEventListener('click', closeModal);
    foot.appendChild(cancel);
    modal.appendChild(foot);
    scrim.appendChild(modal);

    function renderList() {
      list.textContent = '';
      var query = search.value.trim().toLowerCase();
      var rows = state.students.filter(function (student) {
        if (!query) return true;
        var blob = [student.name, student.student_code, student.grade, student.school]
          .join(' ').toLowerCase();
        return blob.indexOf(query) !== -1;
      });
      if (!rows.length) {
        list.appendChild(el('div', 'sub', '没有匹配的学生。'));
        return;
      }
      rows.forEach(function (student) {
        var item = el('button', 'file');
        item.setAttribute('type', 'button');
        item.style.textAlign = 'left';
        item.style.background = 'var(--surface)';
        if (!student.y4_complete) item.disabled = true;

        var name = el('span', 'nm', student.name + ' ');
        name.appendChild(el('span', 'sub',
          [student.grade, student.school].filter(Boolean).join(' · ')));
        item.appendChild(name);

        if (student.y4_complete) {
          var pill = el('span', 'pill ' + (student.has_prep ? 'warn' : 'ok'),
            student.has_prep ? '已有草稿' : 'Y4 已完成');
          item.appendChild(pill);
        } else {
          item.appendChild(el('span', 'pill', '不可开始'));
          var meta = el('span', 'meta', student.reason || 'Y4 尚未完成');
          item.appendChild(meta);
        }

        item.addEventListener('click', function () {
          startPrep(student);
        });
        list.appendChild(item);
      });
    }

    function startPrep(student) {
      api('/api/m1/preps', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ student_id: student.id })
      }).then(function (body) {
        window.location.href = '/m1/preps/' + body.prep.id;
      }).catch(function (error) {
        toast(error.message, 'error');
      });
    }

    search.addEventListener('input', renderList);
    host.appendChild(scrim);
    scrim.addEventListener('click', function (event) {
      if (event.target === scrim) closeModal();
    });
    document.addEventListener('keydown', onKey);
    renderList();
    search.focus();

    if (preselected) {
      var match = state.students.filter(function (s) {
        return String(s.id) === String(preselected);
      })[0];
      if (match) search.value = match.name;
      renderList();
    }
  }

  function load() {
    Promise.all([api('/api/m1/preps'), api('/api/m1/students')]).then(function (results) {
      state.preps = results[0].preps || [];
      state.students = results[1].students || [];
      renderRows();
      if (preselected) {
        var existing = state.preps.filter(function (prep) {
          return String(prep.student_id) === String(preselected);
        })[0];
        if (existing) window.location.replace('/m1/preps/' + existing.id);
        else openPicker();
      }
    }).catch(function (error) {
      toast(error.message, 'error');
      prepRows.textContent = '';
      var tr = el('tr');
      var td = el('td', 'sub', error.message);
      td.setAttribute('colspan', '6');
      tr.appendChild(td);
      prepRows.appendChild(tr);
    });
  }

  newBtn.addEventListener('click', openPicker);
  load();
})();
