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
