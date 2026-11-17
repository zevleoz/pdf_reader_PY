/* DP13-C：计划编辑器的纯函数层。
 *
 * 负责把模板里的 data-path / data-ppath 映射成协作契约里的 section key，
 * 并根据本地文档构造最小 patch。这里不访问 DOM 或网络，便于 Node 回归测试。
 */
(function (root) {
  'use strict';

  function textOf(value) {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      return value.text == null ? '' : String(value.text);
    }
    return value == null ? '' : String(value);
  }

  function field(value) {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      return {text: textOf(value), src: value.src || 'edited'};
    }
    return {text: textOf(value), src: 'edited'};
  }

  /* 未编辑的兄弟项要保留原始 src，不能因为整列表重发而改成 edited。 */
  function keepField(value) {
    return field(value);
  }

  function richListPatch(rows, index, key, value) {
    return (rows || []).map(function (row, i) {
      var copy = Object.assign({}, row);
      if (i === index && key === 'title') copy.title = field(value);
      else copy.title = keepField(row.title);
      if (i === index && key === 'text') copy.text = field(value);
      else copy.text = keepField(row.text);
      if (i === index && key === 'frequency') copy.frequency = field(value);
      else copy.frequency = keepField(row.frequency);
      return copy;
    });
  }

  function number(value) {
    var parsed = parseInt(value, 10);
    return isNaN(parsed) ? 0 : parsed;
  }

  function sessionNumber(index) {
    return parseInt(index, 10) + 1;
  }

  function internalSection(doc, path) {
    var parts = String(path || '').split('.');
    if (!parts.length) return null;
    if (parts[0] === 'overview') {
      return {section: 'internal.overview', field: 'overview'};
    }
    if (parts[0] === 'mentor_notes') {
      return {section: 'internal.mentor_notes', field: 'mentor_notes'};
    }
    if (parts[0] !== 'sessions') return null;
    var sessionIndex = parseInt(parts[1], 10);
    if (isNaN(sessionIndex)) return null;
    var n = sessionNumber(sessionIndex);
    if (parts[2] === 'activities') {
      var activityIndex = parseInt(parts[3], 10);
      var activity = (((doc || {}).sessions || [])[sessionIndex] || {}).activities || [];
      var item = activity[activityIndex];
      if (!item || !item.id) return null;
      return {section: 'internal.session.' + n + '.activity.' + item.id,
              field: parts.slice(4).join('.')};
    }
    if (parts[2] === 'practice') {
      var practiceIndex = parseInt(parts[3], 10);
      var practice = (((doc || {}).sessions || [])[sessionIndex] || {}).practice || [];
      var entry = practice[practiceIndex];
      if (!entry || !entry.id) return null;
      return {section: 'internal.session.' + n + '.practice.' + entry.id,
              field: parts.slice(4).join('.')};
    }
    return {section: 'internal.session.' + n, field: parts.slice(2).join('.')};
  }

  function parentSection(parentDoc, path) {
    var parts = String(path || '').split('.');
    if (!parts.length) return null;
    if (parts[0] === 'intro' || parts[0] === 'transition') {
      return {section: 'parent.' + parts[0], field: parts[0]};
    }
    if (parts[0] === 'goals') {
      var goalIndex = parseInt(parts[1], 10);
      var goal = ((parentDoc || {}).goals || [])[goalIndex];
      if (!goal || !goal.code) return null;
      return {section: 'parent.goal.' + goal.code, field: 'text'};
    }
    if (parts[0] === 'sessions') {
      var sessionIndex = parseInt(parts[1], 10);
      return {section: 'parent.session.' + sessionNumber(sessionIndex),
              field: parts.slice(2).join('.')};
    }
    if (parts[0] === 'practice_options') {
      return {section: 'parent.practice_options', field: parts.slice(2).join('.')};
    }
    if (parts[0] === 'family') {
      return {section: 'parent.family', field: 'family'};
    }
    if (parts[0] === 'review') {
      return {section: 'parent.review', field: 'review'};
    }
    return null;
  }

  function internalPatch(doc, path, value) {
    var target = internalSection(doc, path);
    if (!target) return null;
    var parts = String(path).split('.');
    var fieldName = target.field;
    var patch = {};
    if (parts[0] === 'overview') {
      /* 契约：internal.overview 的 patch 就是字段本身，不再包一层 key。 */
      patch = field(value);
    } else if (parts[0] === 'mentor_notes') {
      patch = field(value);
    } else if (parts[2] === 'activities') {
      var activityIndex = parseInt(parts[3], 10);
      var activity = doc.sessions[parseInt(parts[1], 10)].activities[activityIndex];
      var key = parts[4];
      if (key === 'minutes') {
        patch = {minutes: number(value)};
      } else if (key === 'source') {
        patch = {source: Object.assign({}, activity.source || {})};
      } else {
        patch = {};
        patch[key] = field(value);
      }
    } else if (parts[2] === 'practice') {
      var practiceIndex = parseInt(parts[3], 10);
      var practice = doc.sessions[parseInt(parts[1], 10)].practice[practiceIndex];
      var practiceKey = parts[4];
      if (practiceKey === 'code' || practiceKey === 'platform') {
        patch = {};
        patch[practiceKey] = practice[practiceKey] || '';
      } else {
        patch = {};
        patch[practiceKey] = field(value);
      }
    } else if (parts[2] === 'title' || parts[2] === 'evidence' ||
               parts[2] === 'next_prep') {
      patch = {};
      patch[parts[2]] = field(value);
    } else if (parts[2] === 'review') {
      var session = doc.sessions[parseInt(parts[1], 10)];
      patch = {review: (session.review || []).map(function (row) {
        return field(row);
      })};
    } else if (parts[2] === 'focus') {
      if (parts[3] === 'text') {
        patch = {focus: {text: field(value)}};
      } else {
        patch = {focus: {}};
        patch.focus[parts[3]] = value;
      }
    } else if (parts[2] === 'content') {
      var contentKey = parts[3];
      if (contentKey === 'mindsets' || contentKey === 'skills' ||
          contentKey === 'techniques') {
        patch = {content: {}};
        patch.content[contentKey] = field(value);
      } else {
        return null;
      }
    } else {
      return null;
    }
    return {section: target.section, patch: patch};
  }

  function parentPatch(parentDoc, path, value) {
    var target = parentSection(parentDoc, path);
    if (!target) return null;
    var parts = String(path).split('.');
    var patch;
    if (parts[0] === 'intro' || parts[0] === 'transition') {
      /* 契约：parent.intro / parent.transition 的 patch 就是字段本身。 */
      patch = field(value);
    } else if (parts[0] === 'goals') {
      patch = {text: field(value)};
    } else if (parts[0] === 'sessions') {
      patch = {};
      patch[parts[2]] = field(value);
    } else if (parts[0] === 'practice_options') {
      patch = richListPatch(parentDoc.practice_options, parseInt(parts[1], 10),
                            parts[2], value).map(function (row) {
        row.ref = String(row.ref || '');
        row.platform = String(row.platform || '');
        return row;
      });
    } else if (parts[0] === 'family') {
      var familyIndex = parseInt(parts[1], 10);
      patch = (parentDoc.family || []).slice(0, 2).map(function (row, index) {
        return index === familyIndex ? field(value) : keepField(row);
      });
      while (patch.length < 2) patch.push(field(''));
    } else if (parts[0] === 'review') {
      patch = (parentDoc.review || []).map(function (row, index) {
        return {
          label: index === parseInt(parts[1], 10) && parts[2] === 'label'
            ? field(value) : keepField(row.label),
          text: index === parseInt(parts[1], 10) && parts[2] === 'text'
            ? field(value) : keepField(row.text)
        };
      });
    } else {
      return null;
    }
    return {section: target.section, patch: patch};
  }

  function get(obj, path) {
    return String(path).split('.').reduce(function (node, key) {
      return node === undefined || node === null ? undefined : node[key];
    }, obj);
  }

  function set(obj, path, value) {
    var keys = String(path).split('.');
    var last = keys.pop();
    var node = keys.reduce(function (cur, key) {
      if (cur[key] === undefined || cur[key] === null) cur[key] = {};
      return cur[key];
    }, obj);
    node[last] = value;
  }

  function parentListOf(section) {
    if (section === 'parent.practice_options' || section === 'parent.family' ||
        section === 'parent.review') return section;
    return null;
  }

  function dependencyParent(section) {
    var match = /^internal\.session\.(\d+)\.(activity|practice)\./.exec(section || '');
    if (match) {
      return 'internal.session.' + match[1] +
        (match[2] === 'activity' ? '.activities' : '.practice');
    }
    return null;
  }

  function sectionLabel(section) {
    if (!section) return '';
    if (section === 'internal.overview') return '概览与目标';
    if (section === 'internal.mentor_notes') return '导师备注';
    var match = /^internal\.session\.(\d+)(?:\.(activities|activity|practice))?/.exec(section);
    if (match) {
      var suffix = match[2];
      if (suffix === 'activity') return '第 ' + match[1] + ' 节 · 教学活动';
      if (suffix === 'practice') return '第 ' + match[1] + ' 节 · 在家练习';
      if (suffix === 'activities') return '第 ' + match[1] + ' 节 · 活动列表';
      return '第 ' + match[1] + ' 节';
    }
    if (section === 'parent.intro') return '家长版 · 开场';
    if (section === 'parent.transition') return '家长版 · 过渡语';
    if (section.indexOf('parent.goal.') === 0) {
      return '家长版 · 目标 ' + section.slice('parent.goal.'.length);
    }
    if (section.indexOf('parent.session.') === 0) {
      return '家长版 · 第 ' + section.slice('parent.session.'.length) + ' 节';
    }
    if (section === 'parent.practice_options') return '家长版 · 在家练习';
    if (section === 'parent.family') return '家长版 · 家庭建议';
    if (section === 'parent.family_seen') return '家长版 · 家庭建议确认';
    if (section === 'parent.review') return '家长版 · 成长观察';
    if (section === 'header') return '计划表头';
    if (section === 'durations') return '每节时长';
    if (section === 'inputs') return '学生资料';
    if (section === 'brief') return '教学简报';
    if (section === 'goals') return '发展目标';
    if (section === 'personal') return '导师备注';
    return section;
  }

  /* 冲突卡片只显示可读文字，不把 section 结构直接丢给导师。 */
  function previewText(value) {
    if (value == null) return '';
    if (Array.isArray(value)) {
      return value.map(previewText).filter(Boolean).join(' / ');
    }
    if (typeof value === 'object') {
      if (value.text !== undefined) return textOf(value.text);
      var labels = ['title', 'label', 'name', 'ref'];
      for (var i = 0; i < labels.length; i += 1) {
        if (value[labels[i]] !== undefined) return textOf(value[labels[i]]);
      }
      return Object.keys(value).map(function (key) {
        return previewText(value[key]);
      }).filter(Boolean).join(' / ');
    }
    return String(value);
  }

  function conflictPreview(value, limit) {
    limit = limit || 90;
    var text = previewText(value).replace(/\s+/g, ' ').trim();
    return text.length > limit ? text.slice(0, limit) + '…' : text;
  }

  /* stale_section 返回的 current 是整个 section；按本地 patch 的字段裁剪，
     避免把整节活动 JSON 当作当前标题展示。 */
  function conflictCurrent(patch, current, limit) {
    if (current == null) return '';
    if (Array.isArray(patch) || !patch || typeof patch !== 'object' ||
        patch.text !== undefined) {
      return conflictPreview(current, limit);
    }
    var picked = {};
    Object.keys(patch).forEach(function (key) {
      if (current[key] !== undefined) picked[key] = current[key];
    });
    return conflictPreview(picked, limit);
  }

  var api = {
    textOf: textOf,
    field: field,
    get: get,
    set: set,
    internalSection: internalSection,
    parentSection: parentSection,
    internalPatch: internalPatch,
    parentPatch: parentPatch,
    dependencyParent: dependencyParent,
    parentListOf: parentListOf,
    sectionLabel: sectionLabel,
    conflictPreview: conflictPreview,
    conflictCurrent: conflictCurrent
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.M1PlanCollabCore = api;
})(typeof window !== 'undefined' ? window : globalThis);
