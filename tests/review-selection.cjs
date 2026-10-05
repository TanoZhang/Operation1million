'use strict';
const fs = require('node:fs');
const assert = require('node:assert/strict');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const assets = path.join(__dirname, '../src/jobdisco/review_static');
const dom = new JSDOM(fs.readFileSync(path.join(assets, 'index.html'), 'utf8'),
  {url: 'http://localhost:8765', runScripts: 'outside-only'});
const w = dom.window;
const group = id => ({id, company: 'Example Semiconductor', title: 'RTL Engineer ' + id,
  confidence: 80, bucket: 2, jobs: [{url: 'https://example.test/' + id, location: 'Example City'}]});
const state = {pending: [group('a'), group('b')], backlog: [], applied: [{...group('done'), at: '2026-10-01T18:00:00Z'}], skipped: [], token: 'fixture'};
let downloadIds;
let manualRequest;
let clicked = false;
w.URL.createObjectURL = () => 'blob:fixture';
w.URL.revokeObjectURL = () => {};
w.HTMLAnchorElement.prototype.click = function () {clicked = this.download === 'selected-positions.xlsx';};
w.fetch = async (url, options) => {
  if (url === '/api/manual') {
    manualRequest = JSON.parse(options.body);
    assert.equal(options.headers['X-Review-Token'], 'fixture');
    return {ok: true, json: async () => ({id: 'a', created: false, confidence: 80, status: manualRequest.status})};
  }
  if (url === '/api/export/download') {
    downloadIds = JSON.parse(options.body).ids;
    assert.equal(options.headers['X-Review-Token'], 'fixture');
    return {ok: true, blob: async () => new w.Blob(['fixture'])};
  }
  return {ok: true, json: async () => url === '/api/queue' ? state : {description: ''}};
};
async function main() {
  w.eval(fs.readFileSync(process.env.REVIEW_APP_SOURCE || path.join(assets, 'app.js'), 'utf8'));
  await new Promise(resolve => setTimeout(resolve, 15));
  const boxes = w.document.querySelectorAll('.job-check');
  assert.equal(boxes.length, 2);
  boxes[0].click();
  assert.match(w.document.getElementById('download-selected').textContent, /\(1\)/);
  w.document.getElementById('sort').value = 'oldest';
  w.document.getElementById('sort').dispatchEvent(new w.Event('change'));
  assert.equal(w.document.querySelectorAll('.job-check:checked').length, 1);
  w.document.getElementById('download-selected').click();
  await new Promise(resolve => setTimeout(resolve, 15));
  assert.deepEqual(downloadIds, ['a']);
  assert.equal(clicked, true);
  w.document.getElementById('select-matching').click();
  assert.equal(w.document.querySelectorAll('.job-check:checked').length, 2);
  w.document.getElementById('clear-selection').click();
  assert.equal(w.document.querySelectorAll('.job-check:checked').length, 0);
  assert.equal(w.document.getElementById('download-selected').disabled, true);
  w.document.getElementById('export').click();
  await new Promise(resolve => setTimeout(resolve, 15));
  assert.deepEqual(downloadIds, ['a', 'b']);
  state.backlog.push(group('old'));
  w.document.getElementById('refresh').click();
  await new Promise(resolve => setTimeout(resolve, 15));
  w.document.querySelector('.section-check[data-section=recent]').click();
  w.document.getElementById('download-selected').click();
  await new Promise(resolve => setTimeout(resolve, 15));
  assert.deepEqual(downloadIds, ['a', 'b']);
  assert.equal(w.document.querySelector('.job-check[data-group-id=old]').checked, false);
  w.document.querySelector('.job-check[data-group-id=a]').click();
  assert.equal(w.document.querySelector('.section-check[data-section=recent]').indeterminate, true);
  w.document.getElementById('clear-selection').click();
  state.pending.push(...Array.from({length:80}, (_, i) => group('extra'+i)));
  w.document.getElementById('refresh').click();
  await new Promise(resolve => setTimeout(resolve, 15));
  w.document.querySelector('.section-check[data-section=recent]').click();
  w.document.getElementById('download-selected').click();
  await new Promise(resolve => setTimeout(resolve, 15));
  assert.equal(downloadIds.length, 82);
  assert.equal(downloadIds.includes('old'), false);
  state.pending.splice(2); state.backlog.pop();
  w.document.getElementById('refresh').click();
  await new Promise(resolve => setTimeout(resolve, 15));
  w.document.getElementById('clear-selection').click();
  w.document.getElementById('manual-url').value = 'https://example.test/a';
  w.document.getElementById('manual-applied').click();
  await new Promise(resolve => setTimeout(resolve, 15));
  assert.equal(manualRequest.status, 'applied');
  assert.equal(manualRequest.url, 'https://example.test/a');
  assert.match(w.document.getElementById('manual-result').textContent, /Marked applied/);
  assert.equal(w.document.getElementById('manual-applied').disabled, false);
  w.document.querySelector('.job-check').click();
  w.document.querySelector('[data-tab=applied]').click();
  assert.equal(w.document.querySelectorAll('.job-check:checked').length, 0);
  assert.equal(w.document.getElementById('download-selected').disabled, true);
  assert.match(w.document.querySelector('.job > div:first-child .applied-date').textContent, /Applied.*2026/);
  assert.equal(w.document.querySelector('.job > div:first-child .band'), null);
  assert.match(w.document.querySelector('#detail > div:first-child .applied-date').textContent, /Applied.*2026/);
  assert.equal(w.document.getElementById('manual-applied').hidden, true);
  const add = w.document.querySelector('#manual-form button[type=submit]:not(#manual-applied)');
  assert.equal(add.textContent, 'Add to Applied');
  w.document.getElementById('manual-url').value = 'https://example.test/b';
  add.click();
  await new Promise(resolve => setTimeout(resolve, 15));
  assert.equal(manualRequest.status, 'applied');
  w.document.querySelector('[data-tab=pending]').click();
  assert.equal(w.document.getElementById('manual-applied').hidden, false);
  assert.equal(add.textContent, 'Add job and score');
  await new Promise(resolve => setTimeout(resolve, 15));
  dom.window.close();
  await checkLoadingTimeout();
  await checkPreparingMessage();
  await checkBatches();
  await checkOutcomes();
  console.log('Review checkbox and download interactions OK');
}
main().catch(error => {console.error(error); dom.window.close(); process.exitCode = 1;});

async function checkLoadingTimeout() {
  const stalled = new JSDOM(fs.readFileSync(path.join(assets, 'index.html'), 'utf8'),
    {url:'http://localhost:8765', runScripts:'outside-only'});
  const view = stalled.window;
  const schedule = view.setTimeout.bind(view);
  view.setTimeout = (callback, ms) => schedule(callback, ms === 25000 ? 5 : ms);
  view.fetch = (url, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new view.DOMException('timeout', 'AbortError')));
  });
  try {
    view.eval(fs.readFileSync(path.join(assets, 'app.js'), 'utf8'));
    await new Promise(resolve => setTimeout(resolve, 25));
    assert.match(view.document.getElementById('list').textContent, /timed out/);
    assert.match(view.document.getElementById('list').textContent, /Retrying/);
  } finally {stalled.window.close();}
}

async function checkPreparingMessage() {
  const preparing = new JSDOM(fs.readFileSync(path.join(assets, 'index.html'), 'utf8'),
    {url:'http://localhost:8765', runScripts:'outside-only'});
  const view = preparing.window;
  view.fetch = async () => ({ok:false, status:503, json:async () => ({error:'Preparing the job queue'})});
  try {
    view.eval(fs.readFileSync(path.join(assets, 'app.js'), 'utf8'));
    await new Promise(resolve => setTimeout(resolve, 15));
    assert.equal(view.document.getElementById('error').hidden, true);
    assert.equal(view.document.getElementById('list').textContent,
      'Preparing the job queue. This page will update automatically.');
  } finally {preparing.window.close();}
}

async function checkBatches() {
  // 2026-10-04: a long list is downloaded 250 at a time, in the order shown.
  const page = new JSDOM(fs.readFileSync(path.join(assets, 'index.html'), 'utf8'),
    {url:'http://localhost:8765', runScripts:'outside-only'});
  const view = page.window;
  const many = {pending: Array.from({length: 600}, (_, i) => group('g' + String(i).padStart(3, '0'))),
    backlog: [], applied: [], skipped: [], token: 'fixture'};
  let ids, name;
  view.URL.createObjectURL = () => 'blob:fixture';
  view.URL.revokeObjectURL = () => {};
  view.HTMLAnchorElement.prototype.click = function () {name = this.download;};
  view.fetch = async (url, options) => {
    if (url === '/api/export/download') {
      ids = JSON.parse(options.body).ids;
      return {ok: true, blob: async () => new view.Blob(['fixture'])};
    }
    return {ok: true, json: async () => url === '/api/queue' ? many : {description: ''}};
  };
  try {
    view.eval(fs.readFileSync(path.join(assets, 'app.js'), 'utf8'));
    await new Promise(resolve => setTimeout(resolve, 15));
    const batch = view.document.getElementById('batch');
    assert.deepEqual([...batch.options].slice(1).map(o => o.textContent), ['1–250', '251–500', '501–600']);
    view.document.getElementById('sort').value = 'oldest';
    view.document.getElementById('sort').dispatchEvent(new view.Event('change'));
    const order = [...view.document.querySelectorAll('.job-check')].map(box => box.dataset.groupId);
    batch.value = '1';
    batch.dispatchEvent(new view.Event('change'));
    assert.match(view.document.getElementById('download-selected').textContent, /\(250\)/);
    view.document.getElementById('download-selected').click();
    await new Promise(resolve => setTimeout(resolve, 15));
    assert.equal(ids.length, 250);
    assert.equal(name, 'review-batch-2-251-500.xlsx');
    assert.equal(new Set(ids).has(order[0]), false);
    // A selection changed by hand is no longer the batch.
    view.document.getElementById('clear-selection').click();
    assert.equal(batch.value, '');
  } finally {page.window.close();}
}

async function checkOutcomes() {
  // 2026-10-05: the Applied tab in Passed, Declined and Waiting sections, a
  // menu to show one, and the status in large type above the company.
  const page = new JSDOM(fs.readFileSync(path.join(assets, 'index.html'), 'utf8'),
    {url:'http://localhost:8765', runScripts:'outside-only'});
  const view = page.window;
  const done = {pending: [], backlog: [], skipped: [], token: 'fixture',
    applied: [{...group('x'), at: '2026-10-01T18:00:00Z'},
              {...group('y'), at: '2026-09-30T18:00:00Z', outcome: 'declined', outcome_by: 'gmail'}]};
  const sent = [];
  view.fetch = async (url, options) => {
    if (url === '/api/outcome') {
      const body = JSON.parse(options.body);
      sent.push(body);
      return {ok: true, json: async () => ({...body, at: '2026-10-05T00:00:00Z'})};
    }
    return {ok: true, json: async () => url === '/api/queue' ? done : {description: ''}};
  };
  try {
    view.eval(fs.readFileSync(path.join(assets, 'app.js'), 'utf8'));
    await new Promise(resolve => setTimeout(resolve, 15));
    assert.equal(view.document.querySelector('.outcome-control').hidden, true);
    view.document.querySelector('[data-tab=applied]').click();
    assert.equal(view.document.querySelector('.outcome-control').hidden, false);
    const cards = () => [...view.document.querySelectorAll('.job')];
    const sections = () => [...view.document.querySelectorAll('.list-divider')].map(item => item.textContent.trim());
    assert.deepEqual(sections(), ['Declined · 1', 'Waiting for a reply · 1']);
    assert.match(cards()[0].className, /outcome-declined/);
    assert.match(cards()[0].querySelector('.status-badge').textContent, /^DECLINED from Gmail/);
    assert.equal(cards()[1].querySelector('.status-badge'), null);
    // Pick the waiting one and mark it Passed: it moves to the top section.
    cards()[1].click();
    view.document.getElementById('outcome-passed').click();
    await new Promise(resolve => setTimeout(resolve, 15));
    assert.deepEqual(sent.at(-1), {id: 'x', outcome: 'passed'});
    assert.deepEqual(sections(), ['Passed · 1', 'Declined · 1']);
    assert.match(cards()[0].className, /outcome-passed/);
    assert.equal(view.document.querySelector('#detail .status-badge').textContent, 'PASSED');
    // The menu shows one section.
    const menu = view.document.getElementById('outcome-filter');
    menu.value = 'passed';
    menu.dispatchEvent(new view.Event('change'));
    assert.equal(cards().length, 1);
    assert.deepEqual(sections(), ['Passed · 1']);
    menu.value = '';
    menu.dispatchEvent(new view.Event('change'));
    // Clicking the marked one again clears it.
    view.document.getElementById('outcome-passed').click();
    await new Promise(resolve => setTimeout(resolve, 15));
    assert.deepEqual(sent.at(-1), {id: 'x', outcome: ''});
    assert.deepEqual(sections(), ['Declined · 1', 'Waiting for a reply · 1']);
    // Not offered outside the Applied tab.
    view.document.querySelector('[data-tab=skipped]').click();
    assert.equal(view.document.getElementById('outcome-passed'), null);
  } finally {page.window.close();}
}
