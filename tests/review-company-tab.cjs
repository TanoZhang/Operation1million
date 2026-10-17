'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '../src/operation1million/review_static');
const script = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
assert.match(html, /data-tab="companies"/);
assert.match(html, /data-tab="companies"[^>]*>referalble /);
assert.match(html, /Tesla, TikTok, ByteDance, NVIDIA, Renesas, Cisco and Amazon/);
const routing = script.slice(script.indexOf('const selectedCompany = group =>'), script.indexOf('// Bands 0 and 1'));
const groups = [
  {id: 'tesla', referalble: true, company: 'Tesla', early_career: false, asia: false, less_related: false},
  {id: 'tiktok', referalble: true, company: 'TikTok', early_career: true, asia: false, less_related: false},
  {id: 'nvidia', referalble: true, company: 'NVIDIA', early_career: false, asia: true, less_related: false},
  {id: 'renesas', referalble: true, company: 'Renesas', early_career: false, asia: false, less_related: true},
  {id: 'cisco', referalble: true, company: 'Cisco', early_career: false, asia: false, less_related: false},
  {id: 'amazon', referalble: true, company: 'Amazon', early_career: false, asia: false, less_related: false},
  {id: 'other', company: 'Other Semiconductor', early_career: false, asia: false, less_related: false},
  {id: 'fake', company: 'NVIDIA Staffing', early_career: false, asia: false, less_related: false},
];
const context = {state: {pending: groups.slice(0, 3).concat(groups.slice(4)), backlog: [groups[3]],
                          applied: [], skipped: []}, sectionOf: new Map(), sorted: rows => rows,
                 $: () => ({value: ''}), tab: 'companies'};
vm.createContext(context);
vm.runInContext(routing + '\nthis.filtered = filtered;', context);
const ids = () => Array.from(context.filtered(), group => group.id);
assert.deepEqual(ids(), ['tiktok', 'tesla', 'nvidia', 'cisco', 'amazon', 'renesas']);
for (const tab of ['pending', 'early', 'backlog', 'asia', 'less']) {
  context.tab = tab;
  assert.equal(ids().some(id => ['tesla', 'tiktok', 'nvidia', 'renesas', 'cisco', 'amazon'].includes(id)), false, tab);
}
context.tab = 'companies';
context.$ = () => ({value: 'rtl'});
context.state.pending[0].title = 'RTL Design Engineer';
assert.deepEqual(ids(), ['tesla']);
console.log('Review company tab routing OK');
