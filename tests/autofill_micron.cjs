const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const crypto = require('node:crypto');

const source = fs.readFileSync(path.join(__dirname, '..', 'application-autofill',
  'extension', 'content.js'), 'utf8');
const popupSource = fs.readFileSync(path.join(__dirname, '..', 'application-autofill',
  'extension', 'popup.js'), 'utf8');

function loadContent(url) {
  class Input {
    constructor({type = 'text', role = null, readOnly = false, label = '', value = '',
      checked = false, name = 'group'} = {}) {
      Object.assign(this, {type, readOnly, value, checked, name, id: '', disabled: false,
        dataset: {}, parentElement: null});
      this.attributes = {'aria-label': label, role};
    }
    getAttribute(name) { return this.attributes[name] ?? null; }
    closest() { return null; }
  }
  class Textarea {}
  class Select {}
  const document = {
    addEventListener() {},
    querySelectorAll() { return []; },
    querySelector() { return null; },
    getElementById() { return null; }
  };
  const context = {document, location: new URL(url), URL, setTimeout, HTMLInputElement: Input,
    HTMLTextAreaElement: Textarea, HTMLSelectElement: Select,
    getComputedStyle: () => ({display: 'block', visibility: 'visible'}),
    chrome: {runtime: {onMessage: {addListener() {}}}}, CSS: {escape: x => x}};
  vm.runInNewContext(source.replace(/\}\)\(\);\s*$/, `globalThis.testApi = {
    isUsable, radioLabel, describeRadioGroup, positionId, describeControl, fillOne
  };\n})();`), context);
  return {api: context.testApi, Input, document};
}

test('Micron read-only radios and listbox comboboxes are recognized', () => {
  const {api, Input} = loadContent('https://careers.micron.com/careers/apply?pid=44547378');
  assert.equal(api.isUsable(new Input({type: 'radio', readOnly: true})), true);
  const combo = new Input({role: 'combobox'});
  combo.attributes['aria-controls'] = 'list-20';
  combo.closest = () => ({});
  assert.equal(api.isUsable(combo), true);
});

test('Micron radio question and short option labels are kept separate', () => {
  const {api, Input, document} = loadContent('https://careers.micron.com/careers/apply?pid=44547378');
  const first = new Input({type: 'radio', readOnly: true,
    label: 'Yes, Have you previously been employed by any Micron Company?'});
  const second = new Input({type: 'radio', readOnly: true,
    label: 'No, Have you previously been employed by any Micron Company?', checked: true});
  first.id = 'yes'; second.id = 'no';
  const fieldset = {querySelectorAll: () => [],
    querySelector: () => ({textContent: 'Application questions'})};
  const group = {getAttribute: () => null};
  first.closest = selector => selector === 'fieldset' ? fieldset
    : selector === '[role="radiogroup"]' ? group : null;
  const labels = {yes: 'Yes', no: 'No'};
  document.querySelector = selector => {
    const id = selector.match(/label\[for="([^"]+)"\]/)?.[1];
    return id && labels[id] ? {textContent: labels[id]} : null;
  };
  const result = api.describeRadioGroup(first, [first, second], true);
  assert.equal(result.label, 'Have you previously been employed by any Micron Company?');
  assert.deepEqual(Array.from(result.options), ['Yes', 'No']);
  assert.equal(result.value, 'No');
});

test('Micron position is scoped by pid rather than shared apply path', () => {
  const {api} = loadContent('https://careers.micron.com/careers/apply?pid=44547378&domain=micron.com');
  assert.equal(api.positionId(), '44547378');
});

test('opening the popup remembers already selected answers', async () => {
  const stored = {answerProfile: {version: 1, fields: {}, questions: {}},
    answerCaptures: {}};
  const document = {
    getElementById() { return {addEventListener() {}, replaceChildren() {}}; },
    querySelectorAll() { return []; }
  };
  const chrome = {storage: {local: {
    async get() { return stored; },
    async set(update) { Object.assign(stored, update); }
  }}};
  const context = {document, chrome, URL, crypto};
  vm.runInNewContext(popupSource.replace('run(fillKnown);',
    'globalThis.testApi = {resolvePage};'), context);
  const payload = {site: 'https://careers.micron.com/careers/apply?pid=44547378',
    position_id: '44547378', controls: [
      {control_id: 'one', label: 'Are you at least 18 years old?',
        section: 'Position Specific Questions', kind: 'combobox', options: [], value: 'Yes'},
      {control_id: 'two', label: 'Have you previously been employed by Micron?',
        section: 'My Information', kind: 'radio', options: ['Yes', 'No'], value: 'No'}
    ]};
  const result = await context.testApi.resolvePage(payload);
  assert.equal(result.learned.saved, 2);
  assert.deepEqual(Object.values(stored.answerProfile.fields).map(field => field.answer).sort(),
    ['No', 'Yes']);
  assert.ok(result.results.every(item => item.status === 'requires_review'));
});

test('Micron combobox fills only a verified exact option', async () => {
  const {api, Input, document} = loadContent('https://careers.micron.com/careers/apply?pid=44547378');
  const input = new Input({role: 'combobox'});
  input.attributes['aria-controls'] = 'list-20';
  input.closest = () => ({});
  input.click = () => {};
  input.blur = () => {};
  let clicked = 0;
  const options = ['Yes', 'No'].map(value => ({textContent: value, click() {
    clicked += 1; input.value = value;
  }}));
  document.querySelector = () => input;
  document.getElementById = () => ({querySelectorAll: () => options});
  assert.equal(await api.fillOne({control_id: 'one', status: 'requires_review',
    allow_review: true, answer: 'Maybe'}), 'option_mismatch');
  assert.equal(clicked, 0);
  assert.equal(await api.fillOne({control_id: 'one', status: 'requires_review',
    allow_review: true, answer: 'Yes'}), 'filled');
  assert.equal(clicked, 1);
});
