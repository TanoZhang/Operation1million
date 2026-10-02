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
const state = {pending: [group('a'), group('b')], backlog: [], applied: [], skipped: [], token: 'fixture'};
let downloadIds;
let clicked = false;
w.URL.createObjectURL = () => 'blob:fixture';
w.URL.revokeObjectURL = () => {};
w.HTMLAnchorElement.prototype.click = function () {clicked = this.download === 'selected-positions.xlsx';};
w.fetch = async (url, options) => {
  if (url === '/api/export/download') {
    downloadIds = JSON.parse(options.body).ids;
    assert.equal(options.headers['X-Review-Token'], 'fixture');
    return {ok: true, blob: async () => new w.Blob(['fixture'])};
  }
  return {ok: true, json: async () => url === '/api/queue' ? state : {description: ''}};
};
async function main() {
  w.eval(fs.readFileSync(path.join(assets, 'app.js'), 'utf8'));
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
  dom.window.close();
  console.log('Review checkbox and download interactions OK');
}
main().catch(error => {console.error(error); dom.window.close(); process.exitCode = 1;});
