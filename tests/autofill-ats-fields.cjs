'use strict';
// Provider field ids and HTML autocomplete tokens as exact field meaning
// (2026-10-02). Fictional forms and answers only; the ids are the ones the
// providers publish or render, with sources in docs/autofill-framework.md.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const ext = path.join(__dirname, '..', 'application-autofill/extension');
const engine = require(path.join(ext, 'answer-engine.js'));

function page(html, url) {
  const dom = new JSDOM(html, {url, runScripts: 'outside-only'});
  const w = dom.window;
  w.CSS = {escape: String};
  let listener;
  w.chrome = {runtime: {onMessage: {addListener: value => {listener = value;}}}};
  for (const file of ['ats-adapters.js', 'content.js']) w.eval(fs.readFileSync(path.join(ext, file), 'utf8'));
  return {close: () => w.close(), scan: () => new Promise(resolve => listener({action: 'scan'}, {}, resolve))};
}

function profile() {
  const p = engine.initializeProfile();
  Object.assign(p.fields['name.first'], {answer: 'Ada'});
  Object.assign(p.fields['name.last'], {answer: 'Example'});
  Object.assign(p.fields['name.legal_full'], {answer: 'Ada Example'});
  Object.assign(p.fields['name.preferred'], {answer: 'Ada'});
  Object.assign(p.fields['contact.email'], {answer: 'ada@example.test'});
  Object.assign(p.fields['contact.phone'], {answer: '555-0100'});
  Object.assign(p.fields['address.city'], {answer: 'Springfield'});
  return p;
}

// What each scanned control would be bound to, by its label.
async function bindings(html, url) {
  const fixture = page(html, url);
  try {
    const {controls} = await fixture.scan();
    const p = profile();
    return Object.fromEntries(controls.map(control => {
      const keys = engine.aliasCandidates(p, control);
      return [control.label, keys.length === 1 ? keys[0] : null];
    }));
  } finally {fixture.close();}
}

const cases = {
  async workday_form_kit_paths() {
    // Workday's current form-kit renders "Given Name(s)" and "Family Name",
    // which no label alias matched; the local-script names are other fields.
    const found = await bindings(
      '<h3>Legal Name</h3>'
      + '<div data-fkit-id="name--legalName--firstName"><label for="name--legalName--firstName">Given Name(s)</label>'
      + '<input id="name--legalName--firstName"></div>'
      + '<div data-fkit-id="name--legalName--lastName"><label for="name--legalName--lastName">Family Name</label>'
      + '<input id="name--legalName--lastName"></div>'
      + '<div data-fkit-id="name--legalName--firstNameLocal"><label for="name--legalName--firstNameLocal">Local Given Name(s)</label>'
      + '<input id="name--legalName--firstNameLocal"></div>'
      + '<h3>Phone</h3><div data-fkit-id="phoneNumber--phoneNumber"><label for="phoneNumber--phoneNumber">Phone Number</label>'
      + '<input id="phoneNumber--phoneNumber"></div>'
      + '<div data-fkit-id="phoneNumber--extension"><label for="phoneNumber--extension">Phone Extension</label>'
      + '<input id="phoneNumber--extension"></div>',
      'https://acme.wd5.myworkdayjobs.com/en-US/External/job/Austin/RTL_R1/apply');
    assert.deepEqual(found, {'Given Name(s)': 'name.first', 'Family Name': 'name.last',
      'Local Given Name(s)': null, 'Phone Number': 'contact.phone', 'Phone Extension': null});
  },
  async workday_automation_ids() {
    const found = await bindings(
      '<div data-automation-id="formField-legalNameSection_firstName"><label>First Name</label>'
      + '<input data-automation-id="legalNameSection_firstName"></div>'
      + '<div data-automation-id="formField-addressSection_city"><label>City</label>'
      + '<input data-automation-id="addressSection_city"></div>',
      'https://acme.myworkdayjobs.com/External/apply');
    assert.deepEqual(found, {'First Name': 'name.first', 'City': 'address.city'});
  },
  async a_wrapper_holding_two_inputs_names_neither() {
    const found = await bindings(
      '<div data-automation-id="formField-phone-number"><label>Phone</label>'
      + '<input aria-label="Country code"><input aria-label="Number"></div>',
      'https://acme.myworkdayjobs.com/External/apply');
    assert.deepEqual(found, {'Country code': null, 'Number': null});
  },
  async greenhouse_application_fields() {
    const found = await bindings(
      '<div class="field"><label for="first_name">Legal First Name</label>'
      + '<input id="first_name" name="job_application[first_name]"></div>'
      + '<div class="field"><label for="phone">Mobile</label><input id="phone" name="job_application[phone]"></div>'
      + '<div class="field"><label for="question_123">Name of a reference</label>'
      + '<input id="question_123" name="job_application[answers_attributes][0][text_value]"></div>',
      'https://job-boards.greenhouse.io/acme/jobs/123');
    assert.deepEqual(found, {'Legal First Name': 'name.first', 'Mobile': 'contact.phone',
      'Name of a reference': null});
  },
  async lever_and_ashby_full_name() {
    const lever = await bindings(
      '<div class="application-question"><div class="application-label">Full name</div>'
      + '<input name="name" aria-label="Full name"></div>'
      + '<input name="email" aria-label="Email address">',
      'https://jobs.lever.co/acme/1234/apply');
    assert.deepEqual(lever, {'Full name': 'name.legal_full', 'Email address': 'contact.email'});
    const ashby = await bindings(
      '<div class="_fieldEntry_x1"><label for="_systemfield_name">Name</label>'
      + '<input id="_systemfield_name" name="_systemfield_name"></div>',
      'https://jobs.ashbyhq.com/acme/1234/application');
    assert.deepEqual(ashby, {'Name': 'name.legal_full'});
    // The same names on a host that is not the provider mean nothing.
    const elsewhere = await bindings('<input name="name" aria-label="Name">', 'https://example.test/apply');
    assert.deepEqual(elsewhere, {'Name': null});
  },
  async autocomplete_tokens() {
    const found = await bindings(
      '<input autocomplete="given-name" aria-label="Prénom">'
      + '<input autocomplete="shipping given-name" aria-label="Recipient">'
      + '<input autocomplete="work email" aria-label="E-mail">'
      + '<input autocomplete="address-level2" aria-label="Town">'
      + '<input autocomplete="off" aria-label="Nickname">',
      'https://careers.example.test/apply');
    assert.deepEqual(found, {'Prénom': 'name.first', 'Recipient': null, 'E-mail': 'contact.email',
      'Town': 'address.city', 'Nickname': null});
  },
  async other_peoples_sections_stay_guarded() {
    // An autocomplete token on an emergency contact names someone else.
    const found = await bindings(
      '<fieldset><legend>Emergency contact</legend>'
      + '<input autocomplete="given-name" aria-label="Contact first name"></fieldset>',
      'https://careers.example.test/apply');
    assert.deepEqual(found, {'Contact first name': null});
  },
  async a_label_that_disagrees_is_ambiguous() {
    const found = await bindings(
      '<label for="name--legalName--firstName">Preferred name</label><input id="name--legalName--firstName">',
      'https://acme.myworkdayjobs.com/External/apply');
    assert.deepEqual(found, {'Preferred name': null});
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
