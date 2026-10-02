'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const ext = path.join(__dirname, '..', 'application-autofill/extension');
const engine = require(path.join(ext, 'answer-engine.js'));
const ats = require(path.join(ext, 'ats-adapters.js'));
const question = (label, extra = {}) => ({label, kind: 'text', section: '', site: 'https://example.test', options: [], ...extra});

async function profileFixture(seed = null, saved = null) {
  const html = fs.readFileSync(path.join(ext, 'profile.html'), 'utf8');
  const dom = new JSDOM(html, {url: 'https://extension.test/profile.html', runScripts: 'outside-only'});
  const w = dom.window;
  const storage = {answerProfile: saved};
  w.chrome = {runtime: {getURL: name => 'https://extension.test/' + name}, storage: {local: {
    get: async () => JSON.parse(JSON.stringify(storage)),
    set: async value => Object.assign(storage, JSON.parse(JSON.stringify(value)))}}};
  w.fetch = async () => ({ok: Boolean(seed), status: seed ? 200 : 404, json: async () => JSON.parse(JSON.stringify(seed))});
  w.eval(fs.readFileSync(path.join(ext, 'answer-engine.js'), 'utf8'));
  w.eval(fs.readFileSync(path.join(ext, 'profile.js'), 'utf8'));
  await new Promise(resolve => setTimeout(resolve, 5));
  return {w, storage, close: () => w.close(), settle: () => new Promise(resolve => setTimeout(resolve, 5))};
}

function fixture(html, url = 'https://sample.myworkdayjobs.com/jobs/one') {
  const dom = new JSDOM(html, {url, runScripts: 'outside-only'});
  const w = dom.window;
  w.CSS = {escape: String};
  let listener;
  w.chrome = {runtime: {onMessage: {addListener: value => {listener = value;}}}};
  for (const file of ['ats-adapters.js', 'content.js']) w.eval(fs.readFileSync(path.join(ext, file), 'utf8'));
  return {w, close: () => w.close(), message: message => new Promise(resolve => listener(message, {}, resolve))};
}

const cases = {
  known_answer() {
    const p = engine.initializeProfile();
    p.fields['contact.email'].answer = 'fictional@example.test';
    const result = engine.assessKnownAnswer(p, question('Email address *'));
    assert.equal(result.known_answer, true);
    assert.equal(result.status, 'ready');
    assert.equal(result.field_key, 'contact.email');
  },
  unknown_and_missing() {
    const p = engine.initializeProfile();
    assert.equal(engine.assessKnownAnswer(p, question('Email')).status, 'missing_answer');
    assert.equal(engine.assessKnownAnswer(p, question('Why this company?')).known_answer, false);
    p.fields['eligibility.us_work_authorized'].answer = 'Yes';
    assert.equal(engine.assessKnownAnswer(p, question('Are you NOT currently authorized to work in the United States?', {kind: 'select'})).known_answer, false);
    assert.equal(engine.assessKnownAnswer(p, question('Are you currently authorized to work in Canada?', {kind: 'select'})).known_answer, false);
  },
  scope_and_ambiguity() {
    const p = engine.initializeProfile();
    p.fields['contact.email'].answer = 'fictional@example.test';
    p.fields['custom.email'] = {type: 'text', answer: 'other@example.test', aliases: ['Email']};
    assert.equal(engine.assessKnownAnswer(p, question('Email')).status, 'ambiguous');
    const q = question('Email', {field_key: 'contact.email', binding: 'confirmed', required_position_id: 'one'});
    assert.equal(engine.assessKnownAnswer(p, q, 'two').status, 'position_context_required');
    p.fields['contact.email'].reuse_scope = 'site';
    p.fields['contact.email'].source_site = 'https://other.test';
    assert.equal(engine.assessKnownAnswer(p, q, 'one').status, 'scope_mismatch');
    assert.equal(engine.assessKnownAnswer(p, question('Email', {section: 'Emergency contact'})).field_key, 'custom.email');
  },
  degree_major_and_school_aliases() {
    const p = engine.initializeProfile();
    p.fields['education.current_school'].answer = 'Sample University';
    p.fields['education.current_school'].answer_aliases = ['SU'];
    p.fields['education.current_degree'].answer = 'Master of Science';
    p.fields['education.current_major'].answer = 'Electrical Engineering';
    p.fields['education.graduation_year'].answer = 2030;
    const school = engine.assessKnownAnswer(p, question('Current school', {kind: 'select', options: ['SU', 'Other']}));
    assert.equal(school.answer, 'SU');
    assert.equal(engine.assessKnownAnswer(p, question('Current degree level')).answer, 'Master of Science');
    assert.equal(engine.assessKnownAnswer(p, question('Current major')).answer, 'Electrical Engineering');
    assert.equal(engine.assessKnownAnswer(p, question('Expected graduation year', {kind: 'select', options: ['2030', '2031']})).answer, '2030');
    assert.equal(engine.assessKnownAnswer(p, question('Current school', {kind: 'select', options: ['SU', 'Sample University']})).answer, 'Sample University');
    assert.equal(engine.assessKnownAnswer(p, question('Current school', {kind: 'select', options: ['SU', 'SU']})).status, 'option_mismatch');
  },
  sponsorship_context() {
    const p = engine.initializeProfile();
    const field = p.fields['eligibility.us_sponsorship_now'];
    field.answer = 'Yes';
    field.context_answers = {cpt: 'No', other: 'Yes'};
    const q = question(field.label, {kind: 'select', options: ['Yes', 'No']});
    assert.equal(engine.assessKnownAnswer(p, q).status, 'context_required');
    assert.equal(engine.assessKnownAnswer(p, q, null, {work_route: 'cpt'}).answer, 'No');
    assert.equal(engine.assessKnownAnswer(p, q, null, {work_route: 'other'}).answer, 'Yes');
    p.fields['eligibility.us_sponsorship_future'].answer = 'Yes';
    const future = question(p.fields['eligibility.us_sponsorship_future'].label, {kind: 'select', options: ['Yes', 'No']});
    assert.equal(engine.assessKnownAnswer(p, future).answer, 'Yes');
  },
  ats_detection_and_label() {
    assert.equal(ats.detect('https://acme.myworkdayjobs.com/en-US/External').id, 'workday');
    assert.equal(ats.detect('https://job-boards.greenhouse.io/example/jobs/123').id, 'greenhouse');
    assert.equal(ats.detect('https://jobs.eu.lever.co/acme/123').id, 'lever');
    assert.equal(ats.detect('https://myworkdayjobs.com.evil.test/').id, 'generic');
    const p = fixture('<div data-automation-id="formField-school"><label>Current school</label><div><input></div></div>');
    try {assert.equal(ats.metadata(p.w.document.querySelector('input'), p.w.location.href).label, 'Current school');}
    finally {p.close();}
  },
  async custom_dropdown() {
    const p = fixture('<div data-automation-id="formField-degree"><label>Current degree level</label>'
      + '<button aria-haspopup="listbox" aria-controls="degrees" aria-expanded="false">Select One</button></div>'
      + '<ul role="listbox" id="degrees" hidden><li role="option">Bachelor of Science</li>'
      + '<li role="option">Master of Science</li></ul>');
    try {
      const button = p.w.document.querySelector('button');
      const list = p.w.document.querySelector('ul');
      button.onclick = () => {list.hidden = !list.hidden; button.setAttribute('aria-expanded', String(!list.hidden));};
      for (const option of list.children) option.onclick = () => {
        button.textContent = option.textContent; list.hidden = true; button.setAttribute('aria-expanded', 'false');
      };
      const {controls, ats} = await p.message({action: 'scan'});
      assert.equal(ats, 'workday');
      assert.equal(controls.length, 1);
      assert.equal(controls[0].options_deferred, true);
      const result = await p.message({action: 'fill', results: [{control_id: controls[0].control_id,
        status: 'verify_options', answer: 'Master of Science', needs_review: true}], allowReview: true});
      assert.equal(result.filled, 1);
      assert.equal(button.textContent, 'Master of Science');
    } finally {p.close();}
  },
  async searchable_dropdown() {
    const p = fixture('<div data-automation-id="formField-school"><label>Current school</label>'
      + '<input role="combobox" aria-controls="schools" aria-expanded="false"></div>'
      + '<ul role="listbox" id="schools" hidden></ul>');
    try {
      const input = p.w.document.querySelector('input');
      const list = p.w.document.querySelector('ul');
      input.onclick = () => {list.hidden = !list.hidden; input.setAttribute('aria-expanded', String(!list.hidden));};
      input.oninput = () => {
        list.replaceChildren();
        const option = p.w.document.createElement('li');
        option.setAttribute('role', 'option'); option.textContent = 'Sample University';
        option.onclick = () => {input.value = option.textContent; list.hidden = true; input.setAttribute('aria-expanded', 'false');};
        list.append(option);
      };
      const {controls} = await p.message({action: 'scan'});
      const result = await p.message({action: 'fill', results: [{control_id: controls[0].control_id,
        status: 'verify_options', answer: 'Sample University'}], allowReview: true});
      assert.equal(result.filled, 1);
      assert.equal(input.value, 'Sample University');
      const again = await p.message({action: 'fill', results: [{control_id: controls[0].control_id,
        status: 'verify_options', answer: 'Other University'}], allowReview: true});
      assert.equal(again.occupied, 1);
    } finally {p.close();}
  },
  async dropdown_failure_preserves_value() {
    const p = fixture('<label>Current school<input role="combobox" aria-controls="schools" aria-expanded="false"></label>'
      + '<ul role="listbox" id="schools" hidden><li role="option">Other</li></ul>');
    try {
      const input = p.w.document.querySelector('input'); const list = p.w.document.querySelector('ul');
      input.onclick = () => {list.hidden = !list.hidden; input.setAttribute('aria-expanded', String(!list.hidden));};
      const {controls} = await p.message({action: 'scan'});
      const result = await p.message({action: 'fill', results: [{control_id: controls[0].control_id,
        status: 'verify_options', answer: 'Missing University'}], allowReview: true});
      assert.equal(result.filled, 0);
      assert.equal(input.value, '');
      assert.equal(list.hidden, true);
    } finally {p.close();}
  },
  initialize_preserves_answers() {
    const p = {version: 1, fields: {'name.first': {type: 'text', answer: 'Fictional'}}, questions: {}};
    engine.initializeProfile(p);
    assert.equal(p.fields['name.first'].answer, 'Fictional');
    assert.equal(p.fields['name.last'].answer, null);
    assert.equal(p.preferences.fill_known_review, true);
    assert.throws(() => engine.initializeProfile({version: 1, fields: [], questions: {}}));
  },
  async basic_question_editor() {
    const p = await profileFixture();
    try {
      assert.ok(p.w.document.getElementById('education.current_school'));
      p.w.document.getElementById('education.current_school').value = 'Sample University';
      p.w.document.getElementById('education.current_degree').value = 'Master of Science';
      p.w.document.getElementById('education.current_major').value = 'Electrical Engineering';
      p.w.document.getElementById('education.graduation_year').value = '2030';
      p.w.document.getElementById('profile-form').dispatchEvent(new p.w.Event('submit', {cancelable: true}));
      await p.settle();
      assert.equal(p.storage.answerProfile.fields['education.current_degree'].answer, 'Master of Science');
      assert.equal(p.storage.answerProfile.fields['education.current_major'].answer, 'Electrical Engineering');
      assert.equal(p.storage.answerProfile.fields['education.graduation_year'].answer, 2030);
      assert.equal(p.storage.answerProfile.fields['name.first'].answer, null);
      assert.equal(p.storage.answerProfile.preferences.fill_known_review, true);
    } finally {p.close();}
  },
  async seed_import_preserves_learned_mapping() {
    const seed = engine.initializeProfile();
    seed.fields['education.current_school'].answer = 'Sample University';
    const saved = engine.initializeProfile();
    saved.fields['name.first'].answer = 'Fictional';
    saved.questions.saved = question('Custom wording', {field_key: 'name.first', binding: 'confirmed'});
    saved.fields['learned.custom'] = {type: 'text', answer: 'Fictional'};
    const p = await profileFixture(seed, saved);
    try {
      p.w.document.getElementById('import-seed').click();
      await p.settle();
      assert.equal(p.storage.answerProfile.fields['education.current_school'].answer, 'Sample University');
      assert.equal(p.storage.answerProfile.fields['learned.custom'].answer, 'Fictional');
      assert.equal(p.storage.answerProfile.fields['name.first'].answer, 'Fictional');
      assert.equal(p.storage.answerProfile.questions.saved.field_key, 'name.first');
    } finally {p.close();}
  },
  async confirm_unknown_meaning() {
    const saved = engine.initializeProfile();
    saved.fields['education.current_school'].answer = 'Sample University';
    saved.questions.saved = question('School', {field_key: null});
    const p = await profileFixture(null, saved);
    try {
      const select = p.w.document.querySelector('#unknown-questions select');
      select.value = 'education.current_school';
      p.w.document.querySelector('#unknown-questions button').click();
      await p.settle();
      assert.equal(p.storage.answerProfile.questions.saved.field_key, 'education.current_school');
      assert.equal(p.storage.answerProfile.questions.saved.binding, 'confirmed');
    } finally {p.close();}
    const contextual = engine.initializeProfile();
    contextual.fields['eligibility.us_sponsorship_now'].answer = 'Yes';
    contextual.fields['eligibility.us_sponsorship_now'].context_answers = {cpt: 'No', other: 'Yes'};
    contextual.questions.contextual = question('Current employer sponsorship?', {kind: 'select',
      options: ['Yes', 'No'], field_key: null, observed_position_id: 'one'});
    contextual.position_contexts = {[JSON.stringify(['https://example.test', 'one'])]: {work_route: 'cpt'}};
    const c = await profileFixture(null, contextual);
    try {
      c.w.document.querySelector('#unknown-questions select').value = 'eligibility.us_sponsorship_now';
      c.w.document.querySelector('#unknown-questions button').click();
      await c.settle();
      assert.equal(c.storage.answerProfile.questions.contextual.field_key, 'eligibility.us_sponsorship_now');
    } finally {c.close();}
  },
  async review_policy_switch() {
    const p = fixture('<label>Current school<input role="combobox" aria-controls="schools" aria-expanded="false"></label>'
      + '<ul role="listbox" id="schools" hidden></ul>');
    try {
      const {controls} = await p.message({action: 'scan'});
      const result = await p.message({action: 'fill', results: [{control_id: controls[0].control_id,
        status: 'verify_options', answer: 'Sample University', needs_review: true}], allowReview: false});
      assert.equal(result.filled, 0);
      assert.equal(p.w.document.querySelector('input').getAttribute('aria-expanded'), 'false');
    } finally {p.close();}
  },
  async repeated_education_identity() {
    const p = fixture('<fieldset><legend>Education</legend><input aria-label="Current school"></fieldset>'
      + '<fieldset><legend>Education</legend><input aria-label="Current school"></fieldset>');
    try {
      const {controls} = await p.message({action: 'scan'});
      assert.equal(controls.length, 2);
      assert.ok(controls[0].repeat_context);
      assert.notEqual(controls[0].repeat_context, controls[1].repeat_context);
      const saved = engine.initializeProfile();
      saved.fields['education.current_school'].answer = 'Sample University';
      assert.equal(engine.assessKnownAnswer(saved, controls[0]).known_answer, false);
      const again = await p.message({action: 'scan'});
      assert.equal(again.controls[0].repeat_context, controls[0].repeat_context);
      p.w.document.querySelector('fieldset').outerHTML = '<fieldset><legend>Education</legend><input aria-label="Current school"></fieldset>';
      const replaced = await p.message({action: 'scan'});
      assert.notEqual(replaced.controls[0].repeat_context, controls[0].repeat_context);
    } finally {p.close();}
  }
};

(async () => {
  let failed = 0;
  for (const name of process.argv[2] ? [process.argv[2]] : Object.keys(cases)) {
    try {await cases[name](); console.log('PASS ' + name);}
    catch (error) {failed++; console.error('FAIL ' + name + ': ' + error.stack);}
  }
  process.exitCode = failed ? 1 : 0;
})();
