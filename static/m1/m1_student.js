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
    if (state.data.can_edit === false) {
      window.open('/m1/preps/' + prep.id + '/print', '_blank', 'noopener');
      return;
    }
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

    var step = (data.work || {}).next;
    var right = el('div', 'nx');
    right.appendChild(el('small', null, '下一步'));
    right.appendChild(el('b', null, step && step.owner || (step ? '学生文档' : '当前没有待办')));
    if (step && step.href) {
      var link = el('a', 'btn p', step.label);
      link.href = step.href;
      link.insertAdjacentHTML('beforeend', ' ' + ARROW);
      right.appendChild(link);
    }
    host.appendChild(right);
  }

  function planTrackLabel(plan) {
    if (plan.parent_version_id && plan.parent_stale) return '家长版 已过期';
    if (plan.status !== 'approved') return plan.status_label || '';
    var parent = plan.parent_status;
    if (parent === 'draft') return '家长版待确认';
    if (parent === 'confirmed') return '家长版已确认';
    if (parent === 'generating') return '家长版生成中';
    if (parent === 'exported') return '已导出';
    return '已批准';
  }

  function parentTrackLabel(plan) {
    if (!plan) return '—';
    if (plan.parent_version_id && plan.parent_stale) return '已过期';
    if (!plan.parent_status || plan.parent_status === 'none') return '—';
    if (plan.parent_status === 'exported') {
      return '已导出' + (plan.parent_exported_at ? ' · ' + md(plan.parent_exported_at) : '');
    }
    return plan.parent_label || plan.parent_status;
  }

  function renderTrack(data) {
    var host = document.getElementById('m1Track');
    var prep = data.prep;
    var prepPart = data.prep_part;
    var reportPart = data.report_part;
    var plan = (data.plans || [])[0];
    var exported = !!plan && plan.parent_status === 'exported';

    var cells = [
      { title: '会前准备', small: prepPart.label +
          (prepPart.status === 'final' && prepPart.finalized_at
            ? ' · ' + md(prepPart.finalized_at) : ''),
        done: prepPart.status === 'final' },
      { title: 'First Meeting',
        small: (prep.meeting_date ? md(prep.meeting_date) + ' · ' : '') + data.meeting_label,
        done: false },
      { title: '会后报告', small: reportPart.status === 'published'
          ? '已发布' + (reportPart.published_at ? ' · ' + md(reportPart.published_at) : '')
          : reportPart.label,
        done: reportPart.status === 'published' },
      { title: '发展计划', small: plan
          ? 'Block ' + plan.block_no + ' · ' + planTrackLabel(plan) : '—',
        done: exported },
      { title: '家长版', small: parentTrackLabel(plan), done: exported }
    ];

    var next = (data.work || {}).next;
    var nextIndex = next && next.actionable
      ? { prep: 0, report: 2, plan: 3 }[next.kind]
      : -1;
    if (nextIndex === 3 && plan && plan.status === 'approved') nextIndex = 4;
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
      '给家长的《首次情绪力分析报告》。发展计划从这份报告读取学生资料，有 AI 草稿就可以开始。'));

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
    if (data.report_can_edit === false) {
      link.textContent = '查看会后报告（只读）';
    } else if (!part.started) {
      link.innerHTML = UPLOAD + '上传逐字稿';
    } else {
      link.textContent = '打开';
    }
    acts.appendChild(link);
    if (part.has_version) {
      var exported = el('a', 'btn', ['approved', 'published'].indexOf(part.status) >= 0
        ? '下载正式报告（家长）' : '下载报告草稿（内部审阅）');
      exported.href = '/m1/preps/' + prep.id + '/report/print?print=1';
      exported.target = '_blank';
      acts.appendChild(exported);
    }
    host.appendChild(acts);
  }

  function planCardChip(plan) {
    var tone = plan.parent_status === 'exported' ? 's0'
      : (plan.parent_stale ? 's2' : (plan.status === 'approved' ? 's0' : 's1'));
    return [tone, planTrackLabel(plan)];
  }

  function renderPlanCard(plan, prep) {
    var card = el('section', 'tc');
    card.style.marginTop = '12px';

    var title = el('div', 'tt');
    title.appendChild(el('b', null, 'Block ' + plan.block_no));
    title.appendChild(chip(planCardChip(plan)));
    card.appendChild(title);
    card.appendChild(el('p', null,
      '三节课的内部教学计划，批准后生成给家长的《情绪力阶段成长计划》（PDF）。'));

    var dl = el('dl', 'kv');
    dl.appendChild(el('dt', null, '阶段'));
    dl.appendChild(el('dd', null,
      [plan.period_start + (plan.period_end ? ' 至 ' + md(plan.period_end) : ''),
        plan.sessions + ' 节课',
        plan.credits ? '学分 ' + plan.credits : ''].filter(Boolean).join(' · ')));

    dl.appendChild(el('dt', null, '发展目标'));
    var goals = plan.goals || [];
    var goalCell = el('dd');
    if (goals.length) {
      var chips = el('span', 'chips');
      goals.forEach(function (item) {
        var wrap = el('span', 'chip');
        wrap.appendChild(el('code', null, item.code));
        wrap.appendChild(document.createTextNode(
          (plan.goal_names && plan.goal_names[item.code]) || ''));
        chips.appendChild(wrap);
      });
      goalCell.appendChild(chips);
    } else {
      goalCell.className = 'mu';
      goalCell.textContent = '还没有选目标';
    }
    dl.appendChild(goalCell);

    dl.appendChild(el('dt', null, '内部版'));
    var internalText = '还没有生成';
    if (plan.status === 'approved') {
      internalText = '已批准' + (plan.approved_at ? ' · ' + md(plan.approved_at) : '');
    } else if (plan.status === 'review') {
      internalText = '待批准';
    } else if (plan.status === 'generating') {
      internalText = '生成中';
    }
    dl.appendChild(el('dd', plan.status === 'inputs' ? 'mu' : null, internalText));

    dl.appendChild(el('dt', null, '家长版'));
    var parentText = parentTrackLabel(plan);
    dl.appendChild(el('dd', parentText === '—' ? 'mu' : null, parentText));
    card.appendChild(dl);

    var acts = el('div', 'acts');
    var link = el('a', 'btn p', plan.parent_status === 'exported' ? '打开' : '继续');
    link.href = plan.parent_status === 'exported'
      ? '/m1/plans/' + plan.id : plan.step_url;
    acts.appendChild(link);
    card.appendChild(acts);
    return card;
  }

  function renderPlans(data) {
    var host = document.getElementById('m1Plans');
    var prep = data.prep;
    host.innerHTML = '';

    var heading = el('h3', 'h2', '发展计划');
    var right = el('span', 'r');
    if (data.can_create_plan) {
      var create = el('a', 'btn s');
      create.href = '/m1/plans?new=' + prep.id;
      create.innerHTML = '+ 新建 Block';
      right.appendChild(create);
    }
    heading.appendChild(right);
    host.appendChild(heading);

    var plans = data.plans || [];
    if (!plans.length) {
      host.appendChild(el('p', 'hint', data.can_create_plan
        ? '可以使用已有的会后报告草稿创建发展计划。'
        : '会后报告生成草稿后，可以从报告创建发展计划。'));
      return;
    }
    plans.forEach(function (plan) { host.appendChild(renderPlanCard(plan, prep)); });
  }

  function renderMeeting(data) {
    var host = document.getElementById('m1Meeting');
    var prep = data.prep;
    host.innerHTML = '';

    var heading = el('h3', 'h2', 'First Meeting');
    if (!state.editing && data.can_edit !== false) {
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
    renderPlans(data);
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
