(function () {
  'use strict';

  var doc = typeof document !== 'undefined' ? document : null;
  var root = doc ? doc.getElementById('m1StudentHub') : null;

  // Pure helpers are exported for focused page tests (Node, no DOM needed).
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
      planStep: planStep,
      planLabel: planLabel,
      planHref: planHref,
      sourceLabel: sourceLabel,
      nextStepFor: nextStepFor
    };
  }
  if (!root) return;

  var studentId = Number(root.dataset.studentId);
  var state = { data: null };

  var ARROW = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>';
  var DAYS = ['日', '一', '二', '三', '四', '五', '六'];

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function api(path, opts) {
    var init = Object.assign({headers: {}}, opts || {});
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

  function chip(pair) {
    return el('span', 'st ' + pair[0], pair[1]);
  }

  function sourceLabel(plan) {
    return plan && plan.source_mode === 'mentor_inputs' ? '直接创建' : '从会后报告创建';
  }

  function planStep(action) {
    if (action === 'poll_job' || action === 'review_internal') return 'internal';
    if (action === 'generate_parent' || action === 'confirm_parent' ||
        action === 'export_parent' || action === 'view_parent') return 'parent';
    return 'inputs';
  }

  function planLabel(plan) {
    var action = (plan.next_action || {}).action;
    if (action === 'supply_brief') return '填写教学简报';
    if (action === 'confirm_brief') return '确认教学简报';
    if (action === 'complete_inputs_and_goals') return '补充资料与目标';
    if (action === 'generate_internal') return '生成内部版';
    if (action === 'poll_job') {
      return plan.status === 'generating' ? '查看生成进度' : '查看家长版生成';
    }
    if (action === 'review_internal') return '审阅内部版';
    if (action === 'generate_parent') return '生成家长版';
    if (action === 'confirm_parent') return '确认家长版';
    if (action === 'export_parent') return '导出家长版';
    if (action === 'view_parent') return '打开家长版';
    if (plan.status === 'inputs') return '继续发展计划';
    return '打开';
  }

  function planHref(plan) {
    var action = (plan.next_action || {}).action;
    return '/m1/plans/' + plan.id + '#step=' + planStep(action);
  }

  function createHref(studentIdValue) {
    return '/m1/plans?new_student=' + studentIdValue + '&mode=direct';
  }

  function activePlan(plans) {
    var open = (plans || []).filter(function (plan) {
      return plan.parent_status !== 'exported';
    });
    return open[0] || (plans || [])[0] || null;
  }

  function nextStepFor(overview) {
    var plans = overview.plans || [];
    var plan = activePlan(plans);
    if (!plan) {
      return {
        sentence: '可以直接创建教案，不需要 First Meeting。',
        label: '直接创建教案',
        href: createHref(overview.student.id)
      };
    }
    var label = planLabel(plan);
    var block = 'Block ' + plan.block_no;
    if ((plan.next_action || {}).action === 'view_parent') {
      return { sentence: block + ' 的家长版已导出。', label: label, href: planHref(plan) };
    }
    return { sentence: block + '：' + label, label: label, href: planHref(plan) };
  }

  function planChip(plan) {
    if (plan.parent_version_id && plan.parent_stale) return ['s2', '家长版 已过期'];
    if (plan.status === 'approved') {
      return plan.parent_status === 'exported' ? ['s0', '已导出'] : ['s0', '已批准'];
    }
    if (plan.status === 'review') return ['s1', '待批准'];
    if (plan.status === 'generating') return ['s1', '生成中'];
    return ['s1', plan.status_label || '资料与目标'];
  }

  function briefLabel(plan) {
    if (plan.source_mode !== 'mentor_inputs') return '';
    if (!plan.brief_revision) return '教学简报未填写';
    if (plan.brief_confirmed_revision === plan.brief_revision) {
      return '教学简报已确认 · 第 ' + plan.brief_revision + ' 版';
    }
    return '教学简报待确认 · 第 ' + plan.brief_revision + ' 版';
  }

  function renderHead(data) {
    var step = nextStepFor(data);
    var text = doc.getElementById('m1HubNextText');
    var link = doc.getElementById('m1HubNextBtn');
    if (text) text.textContent = step.sentence;
    if (link) {
      link.textContent = step.label;
      link.href = step.href;
      link.innerHTML = step.label + ' ' + ARROW;
    }
    var heading = doc.querySelector('#m1HubHead h1');
    if (heading && data.student && data.student.name) {
      heading.textContent = data.student.name;
    }
    var sub = doc.querySelector('#m1HubHead .sub');
    if (sub && data.student) {
      sub.textContent = [data.student.student_code, data.student.grade, data.student.school]
        .filter(Boolean).join(' · ');
    }
  }

  function renderPlanCard(plan) {
    var card = el('section', 'tc');
    card.style.marginTop = '12px';

    var title = el('div', 'tt');
    title.appendChild(el('b', null, 'Block ' + plan.block_no));
    title.appendChild(chip(planChip(plan)));
    title.appendChild(el('span', 'st sn', sourceLabel(plan)));
    card.appendChild(title);

    var co = teamNames((state.data || {}).team);
    var meta = [plan.period_start + (plan.period_end ? ' 至 ' + md(plan.period_end) : ''),
      plan.sessions + ' 节课',
      plan.credits ? '学分 ' + plan.credits : '',
      plan.mentor_name ? '负责导师 ' + plan.mentor_name : '',
      co.length ? '共同导师 ' + co.join('、') : ''].filter(Boolean).join(' · ');
    card.appendChild(el('p', null, meta || '阶段周期待定'));

    var dl = el('dl', 'kv');
    dl.appendChild(el('dt', null, '发展目标'));
    var goals = plan.goals || [];
    var goalCell = el('dd');
    if (goals.length) {
      var chips = el('span', 'chips');
      goals.forEach(function (item) {
        var wrap = el('span', 'chip');
        wrap.appendChild(el('code', null, item.code));
        wrap.appendChild(document.createTextNode(item.locked ? '已确认' : '待确认'));
        chips.appendChild(wrap);
      });
      goalCell.appendChild(chips);
    } else {
      goalCell.className = 'mu';
      goalCell.textContent = '还没有选目标';
    }
    dl.appendChild(goalCell);

    if (plan.source_mode === 'mentor_inputs') {
      dl.appendChild(el('dt', null, '教学简报'));
      var brief = briefLabel(plan);
      dl.appendChild(el('dd', brief.indexOf('未填写') !== -1 ? 'mu' : null, brief));
    }

    dl.appendChild(el('dt', null, '内部版'));
    dl.appendChild(el('dd', plan.status === 'inputs' ? 'mu' : null,
      plan.status === 'approved' ? '已批准' : (plan.status_label || '待生成')));

    dl.appendChild(el('dt', null, '家长版'));
    var parentText = plan.parent_label || '—';
    dl.appendChild(el('dd', parentText === '—' ? 'mu' : null, parentText));
    card.appendChild(dl);

    var acts = el('div', 'acts');
    var link = el('a', 'btn p', planLabel(plan));
    link.href = planHref(plan);
    link.innerHTML = planLabel(plan) + ' ' + ARROW;
    acts.appendChild(link);
    card.appendChild(acts);
    return card;
  }

  function teamNames(team) {
    return ((team || {}).co_mentors || []).map(function (row) { return row.name; }).filter(Boolean);
  }

  function renderTeam(data) {
    var host = doc.getElementById('m1HubTeam');
    if (!host) return;
    host.innerHTML = '';
    var team = data.team || {};
    var action = doc.getElementById('m1HubTeamAction');
    if (action) action.innerHTML = '';
    var card = el('section', 'tc');
    card.style.padding = '16px 18px';
    var head = el('div', 'tt');
    head.appendChild(el('b', null, '负责与共同导师'));
    head.appendChild(el('span', 'st sn',
      '共同导师只共享这个学生的 M1 计划，不含会前准备或报告原文'));
    card.appendChild(head);

    var dl = el('dl', 'kv');
    dl.appendChild(el('dt', null, '负责导师'));
    var primaryCell = el('dd');
    var primaries = team.primaries || [];
    if (primaries.length) {
      var chips = el('span', 'chips');
      primaries.forEach(function (row) {
        var chipNode = el('span', 'chip');
        var blocks = (row.block_numbers || []).filter(function (n, i, arr) {
          return arr.indexOf(n) === i;
        }).sort();
        chipNode.appendChild(document.createTextNode(row.name || '导师'));
        if (blocks.length) chipNode.appendChild(el('code', null, 'Block ' + blocks.join('/')));
        chips.appendChild(chipNode);
      });
      primaryCell.appendChild(chips);
    } else {
      primaryCell.className = 'mu';
      primaryCell.textContent = '还没有分配负责导师';
    }
    dl.appendChild(primaryCell);

    dl.appendChild(el('dt', null, '共同导师'));
    var coCell = el('dd');
    var coMentors = team.co_mentors || [];
    if (coMentors.length) {
      var coChips = el('span', 'chips');
      coMentors.forEach(function (row) {
        var wrap = el('span', 'chip');
        wrap.appendChild(document.createTextNode((row.name || '导师') +
          (row.is_active ? '' : '（已停用）')));
        if (data.can_manage_team && row.is_active) {
          var remove = el('button', 'x', '移除');
          remove.type = 'button';
          remove.addEventListener('click', function () {
            removeCoMentor(data, row, remove);
          });
          wrap.appendChild(remove);
        }
        coChips.appendChild(wrap);
      });
      coCell.appendChild(coChips);
    } else {
      coCell.className = 'mu';
      coCell.textContent = '没有共同导师';
    }
    dl.appendChild(coCell);
    card.appendChild(dl);
    host.appendChild(card);
    if (data.can_manage_team) renderTeamPicker(data, action);
  }

  function existingIds(team) {
    var ids = {};
    ((team || {}).primaries || []).forEach(function (row) { ids[row.user_id] = true; });
    ((team || {}).co_mentors || []).forEach(function (row) { ids[row.user_id] = true; });
    return ids;
  }

  function renderTeamPicker(data, action) {
    if (!action) return;
    api('/api/m1/mentors').then(function (body) {
      var taken = existingIds(data.team);
      var options = (body.mentors || []).filter(function (row) { return !taken[row.id]; });
      if (!options.length) {
        action.appendChild(el('span', 'hint', '没有可添加的导师账号'));
        return;
      }
      var select = doc.createElement('select');
      select.id = 'm1TeamPick';
      select.className = 'sel';
      options.forEach(function (row) {
        var option = doc.createElement('option');
        option.value = String(row.id);
        option.textContent = row.display_name || ('账号 ' + row.id);
        select.appendChild(option);
      });
      var add = el('button', 'btn s', '添加共同导师');
      add.type = 'button';
      add.addEventListener('click', function () {
        var id = Number(select.value);
        var name = (select.options[select.selectedIndex] || {}).textContent || '该导师';
        var studentName = (data.student || {}).name || '该学生';
        var ok = window.confirm('将 ' + name + ' 添加为 ' + studentName +
          ' 的共同导师？\n\n权限范围：仅该学生的 M1 计划（查看与编辑）；' +
          '不包含会前准备、报告原文或其他学生。');
        if (!ok) return;
        add.disabled = true;
        api('/api/m1/students/' + studentId + '/team', {
          method: 'POST',
          body: {user_id: id}
        }).then(function (body) {
          state.data.team = body.team;
          renderTeam(state.data);
          if (window.v2Toast) window.v2Toast('已添加共同导师');
        }).catch(function (error) {
          add.disabled = false;
          if (window.v2Toast) window.v2Toast(error.message || '添加失败');
        });
      });
      action.appendChild(select);
      action.appendChild(add);
    }).catch(function (error) {
      if (window.v2Toast) window.v2Toast(error.message || '无法载入导师名单');
    });
  }

  function removeCoMentor(data, row, button) {
    var studentName = (data.student || {}).name || '该学生';
    var ok = window.confirm('将 ' + (row.name || '该导师') + ' 从 ' + studentName +
      ' 的 M1 团队移除？\n\n移除后，这位导师将失去该学生 M1 计划的查看与编辑权限；' +
      '其他学生和会前准备不受影响。');
    if (!ok) return;
    button.disabled = true;
    api('/api/m1/students/' + studentId + '/team/' + row.user_id, {method: 'DELETE'})
      .then(function (body) {
        state.data.team = body.team;
        renderTeam(state.data);
        if (window.v2Toast) window.v2Toast('已移除共同导师');
      }).catch(function (error) {
        button.disabled = false;
        if (window.v2Toast) window.v2Toast(error.message || '移除失败');
      });
  }

  function renderPlans(data) {
    var host = doc.getElementById('m1HubPlans');
    if (!host) return;
    host.innerHTML = '';
    var plans = data.plans || [];
    if (!plans.length) {
      var empty = el('div', 'panel');
      empty.style.padding = '18px';
      empty.appendChild(el('p', null,
        '还没有发展计划。可以直接创建教案，不需要 First Meeting、会后报告或参考年级。'));
      var cta = el('a', 'btn p', '直接创建教案');
      cta.href = createHref(data.student.id);
      empty.appendChild(cta);
      host.appendChild(empty);
      return;
    }
    plans.slice().sort(function (a, b) { return a.block_no - b.block_no; })
      .forEach(function (plan) { host.appendChild(renderPlanCard(plan)); });
  }

  function renderPreps(data) {
    var host = doc.getElementById('m1HubPreps');
    if (!host) return;
    host.innerHTML = '';
    var preps = data.preps || [];
    if (!preps.length) {
      host.appendChild(el('p', 'hint', '还没有 First Meeting。发展计划不依赖会议记录。'));
      return;
    }
    preps.forEach(function (prep) {
      var card = el('section', 'tc');
      var title = el('div', 'tt');
      title.appendChild(el('b', null, meetingLabel(prep.meeting_date)));
      title.appendChild(chip(prep.status === 'final' ? ['s0', '已定稿']
        : (prep.status === 'generating' ? ['s1', '生成中'] : ['sn', '待生成'])));
      card.appendChild(title);
      var dl = el('dl', 'kv');
      dl.appendChild(el('dt', null, 'Mentor'));
      dl.appendChild(el('dd', null, prep.mentor_name || '—'));
      dl.appendChild(el('dt', null, '会后报告'));
      var report = prep.report || {};
      dl.appendChild(el('dd', null, report.label || (report.started ? '已开始' : '未开始')));
      card.appendChild(dl);
      var acts = el('div', 'acts');
      var link = el('a', 'btn', '打开');
      link.href = '/m1/preps/' + prep.id;
      acts.appendChild(link);
      card.appendChild(acts);
      host.appendChild(card);
    });
  }

  function render(data) {
    state.data = data;
    renderHead(data);
    renderTeam(data);
    renderPlans(data);
    renderPreps(data);
  }

  function load() {
    return api('/api/m1/students/' + studentId + '/overview').then(render)
      .catch(function (error) {
        if (window.v2Toast) window.v2Toast(error.message || '加载失败');
      });
  }

  load();
})();
