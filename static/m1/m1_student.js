(function () {
  'use strict';

  var root = document.getElementById('m1Student');
  if (!root) return;

  var prepId = Number(root.dataset.prepId);
  var state = { data: null, editing: false };

  var ARROW = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>';
  var EDIT = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20l1-4L16 5l3 3L8 19z"/></svg>';
  var DOWNLOAD = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v11M7 11l5 5 5-5M5 20h14"/></svg>';
  var UPLOAD = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V8M7 13l5-5 5 5M5 4h14"/></svg>';
  var DAYS = ['日', '一', '二', '三', '四', '五', '六'];

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function api(path, options) {
    var init = Object.assign({ headers: {} }, options || {});
    if (init.body && typeof init.body !== 'string') {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(init.body);
    }
    return fetch(path, init).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (body) {
        if (!res.ok || body.ok === false) {
          throw new Error(body.reason || body.error || ('请求失败（' + res.status + '）'));
        }
        return body;
      });
    });
  }

  function today() {
    var d = new Date();
    return [d.getFullYear(),
      String(d.getMonth() + 1).padStart(2, '0'),
      String(d.getDate()).padStart(2, '0')].join('-');
  }

  function md(value) {
    return value ? String(value).slice(5, 10) : '';
  }

  function weekday(value) {
    if (!value) return '';
    var parts = String(value).slice(0, 10).split('-');
    var d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    return '周' + DAYS[d.getDay()];
  }

  function meetingLabel(value) {
    if (!value) return '日期待定';
    return String(value).slice(0, 10) + ' ' + weekday(value);
  }

  function timeLabel(value) {
    return value ? String(value).slice(11, 16) : '';
  }

  function prepChip(part) {
    if (part.status === 'generating') return ['s1', '生成中'];
    if (part.status === 'final') return ['s0', '已定稿'];
    if (part.has_doc) return ['s1', 'AI 初稿 · 待定稿'];
    return ['sn', '待生成'];
  }

  function reportChip(part) {
    if (!part.started) return ['sn', '未开始'];
    if (part.status === 'published') return ['s0', '已发布'];
    if (part.status === 'generating') return ['s1', '生成中'];
    if (part.status === 'draft') return ['s1', '待生成'];
    return ['s1', '草稿 · 待发布'];
  }

  function chip(pair) {
    return el('span', 'st ' + pair[0], pair[1]);
  }

  function openPrint(prep) {
    var tab = window.open('', '_blank');
    api('/api/m1/preps/' + prep.id + '/export', { method: 'POST' }).then(function () {
      var url = '/m1/preps/' + prep.id + '/print';
      if (tab) tab.location.href = url;
      else window.open(url, '_blank', 'noopener');
    }).catch(function (error) {
      if (tab) tab.close();
      if (window.v2Toast) window.v2Toast(error.message || '导出失败');
    });
  }

  function nextStep(data) {
    var prep = data.prep;
    var prepPart = data.prep_part;
    var reportPart = data.report_part;
    var base = '/m1/preps/' + prep.id;
    if (!prepPart.has_doc) {
      return { sentence: '生成会前准备 AI 初稿', button: '开始会前准备', href: base + '/prep' };
    }
    if (prepPart.status !== 'final') {
      return { sentence: '审阅并定稿会前准备', button: '去定稿',
        href: base + '/prep#step=review' };
    }
    if (!reportPart.started) {
      return { sentence: '上传 First Meeting 逐字稿，生成会后报告', button: '开始会后报告',
        href: base + '/report' };
    }
    if (reportPart.status !== 'published') {
      return { sentence: '核对并正式发布会后报告', button: '核对发布',
        href: base + '/report#step=review' };
    }
    return { sentence: '会后报告已发布', button: '查看会后报告',
      href: base + '/report#step=review' };
  }

  function renderHead(data) {
    var host = document.getElementById('m1Ph');
    var prep = data.prep;
    host.innerHTML = '';

    var left = el('div');
    left.appendChild(el('h1', null, prep.student_name || '未命名学生'));
    var sub = [prep.student_code, prep.grade, prep.school].filter(Boolean);
    if (prep.mentor_name) sub.push('心有灵析 Mentor ' + prep.mentor_name);
    left.appendChild(el('p', 'sub', sub.join(' · ')));
    host.appendChild(left);

    var step = nextStep(data);
    var right = el('div', 'nx');
    right.appendChild(el('small', null, '下一步'));
    right.appendChild(el('b', null, step.sentence));
    var link = el('a', 'btn p');
    link.href = step.href;
    link.innerHTML = step.button + ' ' + ARROW;
    right.appendChild(link);
    host.appendChild(right);
  }

  function renderTrack(data) {
    var host = document.getElementById('m1Track');
    var prep = data.prep;
    var prepPart = data.prep_part;
    var reportPart = data.report_part;
    var y4 = data.auto.y4;

    var cells = [
      { title: 'Y4', small: y4.date ? md(y4.date) : '—', done: true },
      { title: '会前准备', small: prepPart.label +
          (prepPart.status === 'final' && prepPart.finalized_at
            ? ' · ' + md(prepPart.finalized_at) : ''),
        done: prepPart.status === 'final' },
      { title: 'First Meeting',
        small: prep.meeting_date ? md(prep.meeting_date) : '日期待定',
        done: !!prep.meeting_date && prep.meeting_date <= today() },
      { title: '会后报告', small: reportPart.label, done: !!reportPart.has_version },
      { title: '发布', small: reportPart.status === 'published'
          ? md(reportPart.updated_at) : '—',
        done: reportPart.status === 'published' }
    ];

    var nextIndex = cells.findIndex(function (cell) { return !cell.done; });
    host.innerHTML = '';
    cells.forEach(function (cell, index) {
      var cls = cell.done ? 'd' : (index === nextIndex ? 'n' : 'x');
      var box = el('div', cls);
      box.appendChild(el('b', null, cell.title));
      box.appendChild(el('small', null, cell.small));
      host.appendChild(box);
    });
  }

  function renderPrepCard(data) {
    var host = document.getElementById('m1PrepCard');
    var prep = data.prep;
    var part = data.prep_part;
    host.innerHTML = '';

    var title = el('div', 'tt');
    title.appendChild(el('b', null, '会前准备'));
    title.appendChild(chip(prepChip(part)));
    host.appendChild(title);
    host.appendChild(el('p', null,
      '会议用的提纲：四维初步画像、重点确认能力、会议流程和备用提问。'));

    var versionText;
    if (part.status === 'final') {
      versionText = '第 ' + part.version_n + ' 版 · ' + md(part.finalized_at) +
        ' ' + timeLabel(part.finalized_at) + ' 定稿';
    } else if (part.has_doc) {
      versionText = '第 ' + part.version_n + ' 版 · 草稿';
    } else {
      versionText = '还没有生成';
    }
    var durationText = part.duration + ' 分钟 · ' +
      (part.duration === 60 ? '标准版' : '延长版');

    var dl = el('dl', 'kv');
    dl.appendChild(el('dt', null, '版本'));
    dl.appendChild(el('dd', null, versionText));
    dl.appendChild(el('dt', null, '时长'));
    dl.appendChild(el('dd', null, durationText));
    dl.appendChild(el('dt', null, '重点能力'));
    var priority = el('dd');
    if (part.priority && part.priority.length) {
      var chips = el('span', 'chips');
      part.priority.forEach(function (item) {
        var wrap = el('span', 'chip');
        wrap.appendChild(el('code', null, item.code));
        wrap.appendChild(document.createTextNode(item.name));
        chips.appendChild(wrap);
      });
      priority.appendChild(chips);
    } else {
      priority.textContent = '—';
    }
    dl.appendChild(priority);
    dl.appendChild(el('dt', null, '资料'));
    dl.appendChild(el('dd', null, (part.materials || []).join('、') || '—'));
    host.appendChild(dl);

    var acts = el('div', 'acts');
    var open = el('a', 'btn p', '打开');
    open.href = '/m1/preps/' + prep.id + '/prep';
    acts.appendChild(open);
    if (part.has_doc) {
      var download = el('button', 'btn');
      download.type = 'button';
      download.innerHTML = DOWNLOAD + '下载 PDF';
      download.addEventListener('click', function () { openPrint(prep); });
      acts.appendChild(download);
    }
    host.appendChild(acts);
  }

  function renderReportCard(data) {
    var host = document.getElementById('m1ReportCard');
    var prep = data.prep;
    var part = data.report_part;
    host.innerHTML = '';

    var title = el('div', 'tt');
    title.appendChild(el('b', null, '会后报告'));
    title.appendChild(chip(reportChip(part)));
    host.appendChild(title);
    host.appendChild(el('p', null,
      '给家长的《首次情绪力分析报告》。上传 First Meeting 逐字稿即可生成，随时可以开始。资料和会前准备分开：Y4、First Touch 自动读取，其他要单独上传。'));

    var dl = el('dl', 'kv');
    dl.appendChild(el('dt', null, '逐字稿'));
    dl.appendChild(el('dd', part.transcript_filename ? null : 'mu',
      part.transcript_filename || '未上传'));
    dl.appendChild(el('dt', null, '资料'));
    dl.appendChild(el('dd', null, (part.materials || []).join('、') || '—'));
    dl.appendChild(el('dt', null, '状态'));
    dl.appendChild(el('dd', null, part.label || '未开始'));
    host.appendChild(dl);

    var acts = el('div', 'acts');
    var link = el('a', 'btn p');
    link.href = '/m1/preps/' + prep.id + '/report';
    if (!part.started) {
      link.innerHTML = UPLOAD + '上传逐字稿';
    } else {
      link.textContent = '打开';
    }
    acts.appendChild(link);
    if (part.has_version) {
      var exported = el('a', 'btn', '导出 PDF');
      exported.href = '/m1/preps/' + prep.id + '/report/print?print=1';
      exported.target = '_blank';
      acts.appendChild(exported);
    }
    host.appendChild(acts);
  }

  function renderMeeting(data) {
    var host = document.getElementById('m1Meeting');
    var prep = data.prep;
    host.innerHTML = '';

    var heading = el('h3', 'h2', 'First Meeting');
    if (!state.editing) {
      var right = el('span', 'r');
      var edit = el('button', 'btn s');
      edit.type = 'button';
      edit.innerHTML = EDIT + '修改';
      edit.addEventListener('click', function () {
        state.editing = true;
        renderMeeting(state.data);
      });
      right.appendChild(edit);
      heading.appendChild(right);
    }
    host.appendChild(heading);

    var rows = el('div', 'rows');
    if (state.editing) {
      var dateRow = el('div');
      var dateLabel = el('span', 'mu', '日期');
      dateLabel.style.flex = 'none';
      dateLabel.style.whiteSpace = 'nowrap';
      dateRow.appendChild(dateLabel);
      var dateInput = el('input', 'inp');
      dateInput.type = 'date';
      dateInput.value = prep.meeting_date || '';
      dateRow.appendChild(dateInput);
      rows.appendChild(dateRow);

      var mentorRow = el('div');
      var mentorLabel = el('span', 'mu', '心有灵析 Mentor');
      mentorLabel.style.flex = 'none';
      mentorLabel.style.whiteSpace = 'nowrap';
      mentorRow.appendChild(mentorLabel);
      mentorRow.appendChild(el('b', null, prep.mentor_name || '—'));
      rows.appendChild(mentorRow);

      var peopleRow = el('div');
      var peopleLabel = el('span', 'mu', '参会人员');
      peopleLabel.style.flex = 'none';
      peopleLabel.style.whiteSpace = 'nowrap';
      peopleRow.appendChild(peopleLabel);
      var peopleInput = el('input', 'inp');
      peopleInput.value = (prep.attendees || []).join('、');
      peopleInput.placeholder = '用、分隔';
      peopleRow.appendChild(peopleInput);
      rows.appendChild(peopleRow);

      var acts = el('div');
      acts.style.display = 'flex';
      acts.style.gap = '8px';
      acts.style.marginTop = '10px';
      var save = el('button', 'btn p', '保存');
      save.type = 'button';
      save.addEventListener('click', function () {
        save.disabled = true;
        var attendees = peopleInput.value.split(/[、,，]/)
          .map(function (part) { return part.trim(); })
          .filter(Boolean);
        api('/api/m1/preps/' + prep.id, {
          method: 'PATCH',
          body: { meeting_date: dateInput.value, attendees: attendees }
        }).then(function () {
          state.editing = false;
          load();
        }).catch(function (error) {
          save.disabled = false;
          if (window.v2Toast) window.v2Toast(error.message || '保存失败');
        });
      });
      var cancel = el('button', 'btn', '取消');
      cancel.type = 'button';
      cancel.addEventListener('click', function () {
        state.editing = false;
        renderMeeting(state.data);
      });
      acts.appendChild(save);
      acts.appendChild(cancel);
    } else {
      var dateRowView = el('div');
      dateRowView.appendChild(el('span', 'mu', '日期'));
      dateRowView.appendChild(el('b', null, meetingLabel(prep.meeting_date)));
      rows.appendChild(dateRowView);

      var mentorRowView = el('div');
      mentorRowView.appendChild(el('span', 'mu', '心有灵析 Mentor'));
      mentorRowView.appendChild(el('b', null, prep.mentor_name || '—'));
      rows.appendChild(mentorRowView);

      var peopleRowView = el('div');
      peopleRowView.appendChild(el('span', 'mu', '参会人员'));
      peopleRowView.appendChild(el('b', null, (prep.attendees || []).join('、') || '—'));
      rows.appendChild(peopleRowView);
    }
    host.appendChild(rows);
    if (state.editing) host.appendChild(acts);
  }

  function renderActivity(data) {
    var host = document.getElementById('m1Activity');
    host.innerHTML = '';
    host.appendChild(el('h3', 'h2', '记录'));
    var items = data.activity || [];
    if (!items.length) {
      host.appendChild(el('p', 'hint', '还没有记录。'));
      return;
    }
    items.forEach(function (item) {
      var row = el('div', 'tlr' + (item.auto ? ' auto' : ''));
      row.appendChild(el('span', 'dt', md(item.at)));
      row.appendChild(el('i'));
      row.appendChild(el('span', null,
        item.auto ? item.text : [item.actor, item.text].filter(Boolean).join(' ')));
      host.appendChild(row);
    });
  }

  function render(data) {
    state.data = data;
    document.title = (data.prep.student_name || '心有灵析') + ' · 心有灵析 · 凭远';
    renderHead(data);
    renderTrack(data);
    renderPrepCard(data);
    renderReportCard(data);
    renderMeeting(data);
    renderActivity(data);
  }

  function load() {
    return api('/api/m1/preps/' + prepId + '/overview').then(render).catch(function (error) {
      if (window.v2Toast) window.v2Toast(error.message || '加载失败');
    });
  }

  load();
})();
