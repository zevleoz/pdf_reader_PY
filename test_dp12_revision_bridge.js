'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const direct = require('./static/m1/direct_inputs.js');

const pause = () => new Promise(resolve => setImmediate(resolve));

async function main() {
  const browserWindow = {};
  const documentStub = {
    readyState: 'loading',
    addEventListener() {},
    getElementById() { return null; },
    querySelector() { return null; }
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'static/m1/direct_inputs.js'), 'utf8'), {
    window: browserWindow,
    document: documentStub,
    Promise,
    setTimeout,
    clearTimeout,
    CustomEvent: function CustomEvent() {}
  });
  assert.equal(typeof browserWindow.M1DirectInputs.createWriteBridge, 'function');
  assert.equal(typeof browserWindow.M1DirectInputs.directGateBlockers, 'function');
  assert.deepEqual(
    Array.from(browserWindow.M1DirectInputs.directGateBlockers([], {
      brief_revision: 2,
      brief_confirmed_revision: null,
      teaching_brief: {learning_need: {text: 'need', use_for_teaching: true}}
    })),
    ['请确认当前教学简报', '请补充并授权用于教学：当前情境、当前反应'],
    'browser-global gate helper must block an unconfirmed brief'
  );

  let rev = 10;
  const bridge = browserWindow.M1DirectInputs.createWriteBridge(rev, value => { rev = value; });
  const writes = [];
  let releaseFirstDuration;
  let firstDurationStarted;
  const firstStarted = new Promise(resolve => { firstDurationStarted = resolve; });

  async function write(kind, payload) {
    const sentRev = bridge.getRev();
    writes.push({kind, payload, sentRev});
    if (kind === 'duration' && payload[0] === 40) {
      firstDurationStarted();
      await new Promise(resolve => { releaseFirstDuration = resolve; });
    }
    bridge.setRev(sentRev + 1);
    return sentRev + 1;
  }

  let liveDurations = [40, 60, 60];
  const saveDurationChange = () => bridge.enqueue(() => write('duration', liveDurations.slice()));
  const durationRuns = [saveDurationChange()];
  await firstStarted;
  liveDurations = [45, 60, 60];
  durationRuns.push(saveDurationChange());
  liveDurations = [50, 60, 60];
  durationRuns.push(saveDurationChange());

  // These model direct brief autosave, header, goal and internal document
  // saves from their respective editor queues; all share dispatch-time rev.
  const concurrent = [
    bridge.enqueue(() => write('direct-brief', {learning_need: 'edited'})),
    bridge.enqueue(() => write('header', {period_start: '2026-09-02'})),
    bridge.enqueue(() => write('goal', {goal: 'edited'})),
    bridge.enqueue(() => write('internal', {mentor_notes: 'keep local edit'}))
  ];
  releaseFirstDuration();
  await Promise.all([...durationRuns, ...concurrent]);

  assert.deepEqual(writes.filter(row => row.kind === 'duration').map(row => row.payload), [
    [40, 60, 60], [50, 60, 60], [50, 60, 60]
  ], 'serialized duration changes read the latest field values at dispatch');
  assert.deepEqual(writes.map(row => row.sentRev), [10, 11, 12, 13, 14, 15, 16]);
  assert.equal(bridge.getRev(), 17);
  assert.equal(rev, 17, 'responses must synchronize revision back to the plan editor');

  const required = ['learning_need', 'current_situation', 'current_response'];
  const confirmed = Object.fromEntries(required.map(key => [key, {
    text: 'confirmed ' + key, use_for_teaching: true
  }]));
  const base = ['报告仍需读取'];
  const plan = {brief_revision: 2, brief_confirmed_revision: 2, teaching_brief: confirmed};
  assert.deepEqual(browserWindow.M1DirectInputs.directGateBlockers(base, plan), base,
    'a confirmed brief clears only brief blockers');

  plan.brief_revision = 3; // editing the brief invalidates confirmation
  assert.deepEqual(browserWindow.M1DirectInputs.directGateBlockers(base, plan), [
    '报告仍需读取', '请确认当前教学简报'
  ]);
  plan.brief_confirmed_revision = 3;
  assert.deepEqual(browserWindow.M1DirectInputs.directGateBlockers(base, plan), base,
    'reconfirmation clears the gate again on the same page');

  const planJs = fs.readFileSync(path.join(__dirname, 'static/m1/plan.js'), 'utf8');
  assert.match(planJs, /input\.addEventListener\('change', function \(\) \{ if \(S\.step1\) saveDurations\(\); \}\)/,
    'the real duration change handler must enter the serialized save path');
  assert.match(planJs, /return patchSection\('durations', \{session_durations: values\}\)/,
    'the duration save must use the leased section-patch path and read values at dispatch');
  assert.doesNotMatch(planJs, /if\s*\(reload\)\s*setTimeout\([^\n]*location\.reload/,
    'save errors including 409 must not reload away local edits');
  assert.doesNotMatch(planJs, /durationReloadTimer/,
    'duration saves must never schedule an automatic reload');
  await pause();
  process.stdout.write('DP12 revision bridge regressions passed\n');
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
