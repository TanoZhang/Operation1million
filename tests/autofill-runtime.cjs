// Offline DOM regressions. Install jsdom@22.1.0 under .local/audit-node.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const extension = path.join(__dirname, '..', 'application-autofill', 'extension');

function page(html, url = 'https://example.test/jobs/one') {
  const dom = new JSDOM(html, {url, runScripts: 'outside-only'});
  const w = dom.window;
  w.CSS = {escape: value => String(value).replace(/["\\]/g, '\\$&')};
  let listener;
  w.chrome = {runtime: {onMessage: {addListener: callback => {listener = callback;}}}};
  w.eval(fs.readFileSync(path.join(extension, 'ats-adapters.js'), 'utf8'));
  w.eval(fs.readFileSync(path.join(extension, 'content.js'), 'utf8'));
  return {w, close: () => w.close(),
    message: message => new Promise(resolve => listener(message, {}, resolve))};
}

async function scan(p) {
  const result = await p.message({action: 'scan'});
  assert.equal(result.error, undefined);
  return result;
}

async function fill(p, control, answer) {
  return p.message({action: 'fill', results: [{control_id: control.control_id,
    status: 'ready', answer}], allowReview: false});
}

const cases = {
  async hidden_ancestor() {
    const p = page('<div style="display:none"><input aria-label="Email"></div>');
    try {assert.equal((await scan(p)).controls.length, 0);} finally {p.close();}
  },
  async disabled_fieldset() {
    const p = page('<fieldset disabled><legend>Contact</legend><input aria-label="Email"></fieldset>');
    try {
      assert.equal((await scan(p)).controls.length, 0);
      // The first legend is exempt from a disabled fieldset in HTML.
      p.w.document.body.innerHTML = '<fieldset disabled><legend><input aria-label="Email"></legend></fieldset>';
      assert.equal((await scan(p)).controls.length, 1);
      p.w.document.body.innerHTML = '<fieldset disabled><legend>Contact</legend>'
        + '<legend><input aria-label="Email"></legend></fieldset>';
      assert.equal((await scan(p)).controls.length, 0);
    } finally {p.close();}
  },
  async radio_form_scope() {
    const p = page('<form id="one"><fieldset><legend>Work authorization</legend>'
      + '<label><input type="radio" name="answer" value="yes">Yes</label>'
      + '<label><input type="radio" name="answer" value="no">No</label></fieldset></form>'
      + '<form id="two"><fieldset><legend>Relocation</legend>'
      + '<label><input type="radio" name="answer" value="yes" checked>Yes</label>'
      + '<label><input type="radio" name="answer" value="no">No</label></fieldset></form>');
    try {
      const {controls} = await scan(p);
      assert.equal(controls.length, 2);
      assert.equal((await fill(p, controls[0], 'No')).filled, 1);
      assert.equal(p.w.document.querySelector('#one input[value="no"]').checked, true);
      assert.equal(p.w.document.querySelector('#two input[value="yes"]').checked, true);
      // Form ownership can come from form= rather than DOM ancestry.
      p.w.document.body.innerHTML = '<form id="one"></form><form id="two"></form>'
        + '<input type="radio" form="one" name="answer" aria-label="Yes">'
        + '<input type="radio" form="two" name="answer" aria-label="No">';
      assert.equal((await scan(p)).controls.length, 2);
    } finally {p.close();}
  },
  async unnamed_radios() {
    const p = page('<fieldset><legend>Availability</legend>'
      + '<label><input type="radio" value="one">One</label>'
      + '<label><input type="radio" value="two">Two</label></fieldset>');
    try {
      const {controls} = await scan(p);
      assert.equal(controls.length, 2);
      assert.equal(controls[0].options.length, 1);
      assert.equal(controls[1].options.length, 1);
    } finally {p.close();}
  },
  async disabled_optgroup() {
    const p = page('<select aria-label="Location"><option value="">Choose</option>'
      + '<optgroup disabled><option value="a">Austin</option></optgroup>'
      + '<option value="b">Boston</option></select>');
    try {
      const {controls} = await scan(p);
      assert.deepEqual(Array.from(controls[0].options), ['Boston']);
      assert.equal((await fill(p, controls[0], 'Austin')).filled, 0);
      assert.equal(p.w.document.querySelector('select').value, '');
      assert.equal((await fill(p, controls[0], 'Boston')).filled, 1);
      assert.equal(p.w.document.querySelector('select').value, 'b');
    } finally {p.close();}
  },
  async select_mismatch_atomic() {
    const p = page('<select multiple aria-label="Locations"><option value="a">Austin</option>'
      + '<option value="b">Boston</option></select>');
    try {
      const {controls} = await scan(p);
      assert.equal((await fill(p, controls[0], ['Austin', 'Absent'])).filled, 0);
      assert.equal(p.w.document.querySelector('select').selectedOptions.length, 0);
      let changes = 0;
      p.w.document.querySelector('select').addEventListener('change', () => changes++);
      assert.equal((await fill(p, controls[0], ['Austin', 'Boston'])).filled, 1);
      assert.deepEqual(Array.from(p.w.document.querySelector('select').selectedOptions, o => o.value), ['a', 'b']);
      assert.equal(changes, 1);
      // A single select cannot accept more than one answer either.
      p.w.document.querySelector('select').multiple = false;
      p.w.document.querySelector('select').selectedIndex = -1;
      const single = (await scan(p)).controls[0];
      assert.equal((await fill(p, single, ['Austin', 'Boston'])).filled, 0);
      assert.equal(p.w.document.querySelector('select').selectedIndex, -1);
    } finally {p.close();}
  },
  async duplicate_option_labels() {
    const p = page('<select multiple aria-label="Locations"><option value="a">Remote</option>'
      + '<option value="b">Remote</option></select>');
    try {
      const {controls} = await scan(p);
      assert.equal((await fill(p, controls[0], ['Remote'])).filled, 0);
      assert.equal(p.w.document.querySelector('select').selectedOptions.length, 0);
      p.w.document.querySelector('select').multiple = false;
      p.w.document.querySelector('select').selectedIndex = -1;
      const single = (await scan(p)).controls[0];
      assert.equal((await fill(p, single, 'Remote')).filled, 0);
      assert.equal(p.w.document.querySelector('select').selectedIndex, -1);
    } finally {p.close();}
  },
  async changed_control() {
    for (const mutation of [input => {input.disabled = true;},
      input => {input.setAttribute('aria-label', 'Passport number');},
      input => {input.parentElement.style.display = 'none';},
      input => {input.readOnly = true;}, input => {input.type = 'password';}]) {
      const p = page('<div><input aria-label="Email"></div>');
      try {
        const {controls} = await scan(p);
        const input = p.w.document.querySelector('input');
        mutation(input);
        assert.equal((await fill(p, controls[0], 'sample@example.test')).filled, 0);
        assert.equal(input.value, '');
      } finally {p.close();}
    }
  },
  async query_position_identity() {
    for (const query of ['gh_jid', 'jobId', 'requisitionId']) {
      const p = page('<link rel="canonical" href="https://example.test/apply">',
        `https://example.test/apply?${query}=123`);
      try {
        const one = (await scan(p)).position_id;
        p.w.history.replaceState({}, '', `/apply?${query}=456`);
        const two = (await scan(p)).position_id;
        assert.notEqual(one, two);
        assert.ok(one && two);
        p.w.history.replaceState({}, '', `/apply?${query}=456&utm_source=changed`);
        assert.equal((await scan(p)).position_id, two);
      } finally {p.close();}
    }
  },
  async reuse_existing_unknown() {
    const dom = new JSDOM('<div id="status"></div><div id="review-panel"></div>'
      + '<div id="review-items"></div><button id="fill-review"></button>'
      + '<button id="fill-known"></button>', {url: 'https://extension.test', runScripts: 'outside-only'});
    const w = dom.window;
    try {
      // Expose functions only in this isolated test VM; the shipped popup stays private.
      const source = fs.readFileSync(path.join(extension, 'popup.js'), 'utf8')
        .replace('  run(fillKnown);', '  globalThis.testAPI = {observe, resolve, questionSignature};');
      w.eval(fs.readFileSync(path.join(extension, 'answer-engine.js'), 'utf8'));
      w.eval(source);
      const api = w.testAPI;
      const profile = {version: 1, fields: {}, questions: {}};
      const control = {label: 'Available for relocation?', section: '', kind: 'select', options: ['Yes', 'No']};
      const [id, unknown] = api.observe(profile, 'https://second.test/apply', control);
      assert.equal(unknown.field_key, null);
      // Simulate an explicit All sites approval later made on another site.
      profile.fields['learned.relocation'] = {type: 'choice', answer: 'Yes', policy: 'review',
        reuse_scope: 'global', reuse_signature: api.questionSignature(control), source_site: 'https://first.test'};
      const [again, question] = api.observe(profile, 'https://second.test/apply', control);
      assert.equal(again, id);
      assert.equal(question.field_key, 'learned.relocation');
      assert.equal(api.resolve(profile, id, question).status, 'requires_review');
      // Approved reuse must not change an existing manual binding.
      question.field_key = 'manual.relocation';
      question.binding = 'confirmed';
      assert.equal(api.observe(profile, 'https://second.test/apply', control)[1].field_key, 'manual.relocation');
      // Site and position scopes do not authorize an unrelated site.
      for (const scope of ['site', 'position']) {
        profile.fields['learned.relocation'].reuse_scope = scope;
        profile.fields['learned.relocation'].source_position_id = 'original';
        const [, unrelated] = api.observe(profile, `https://${scope}.test/apply`, control, 'different');
        assert.equal(unrelated.field_key, null);
      }
    } finally {w.close();}
  },
  async ordinary_fill_preserves_values() {
    const p = page('<input aria-label="Email"><textarea aria-label="Cover letter"></textarea>'
      + '<input type="number" aria-label="Graduation year">'
      + '<select aria-label="Location"><option value="">Choose</option><option value="a">Austin</option></select>'
      + '<input type="checkbox" aria-label="I agree"><input type="password" aria-label="Password">');
    try {
      const {controls} = await scan(p);
      assert.equal(controls.length, 4);
      for (const [control, answer] of controls.map((control, i) => [control, ['sample@example.test', 'Sample text', 2028, 'Austin'][i]])) {
        assert.equal((await fill(p, control, answer)).filled, 1);
        assert.equal((await fill(p, control, 'Different')).occupied, 1);
      }
      assert.equal(p.w.document.querySelector('input[type="number"]').value, '2028');
      assert.equal(p.w.document.querySelector('input[type="checkbox"]').checked, false);
      assert.equal(p.w.document.querySelector('input[type="password"]').value, '');
    } finally {p.close();}
  },
  async stale_page_and_options() {
    const p = page('<select aria-label="Location"><option value="">Choose</option>'
      + '<option value="a">Austin</option></select>');
    try {
      const {controls} = await scan(p);
      p.w.document.querySelector('option[value="a"]').textContent = 'Boston';
      assert.equal((await fill(p, controls[0], 'Austin')).filled, 0);
      assert.equal(p.w.document.querySelector('select').value, '');
      p.w.document.body.innerHTML = '<input aria-label="Email">';
      const control = (await scan(p)).controls[0];
      p.w.history.replaceState({}, '', '/jobs/two');
      assert.equal((await fill(p, control, 'sample@example.test')).filled, 0);
      assert.equal(p.w.document.querySelector('input').value, '');
    } finally {p.close();}
  }
};

async function main() {
  const selected = process.argv[2] ? [process.argv[2]] : Object.keys(cases);
  let failures = 0;
  for (const name of selected) {
    try {await cases[name](); console.log(`PASS ${name}`);}
    catch (error) {failures++; console.error(`FAIL ${name}: ${error.stack}`);}
  }
  process.exitCode = failures ? 1 : 0;
}
main().catch(error => {console.error(error); process.exitCode = 1;});
