'use strict';
// How the scanner names a question and its section (bug hunt, 2026-10-02).
// Fictional forms; each case was red on 0.5.1.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const ext = path.join(__dirname, '..', 'application-autofill/extension');

async function scan(html, url = 'https://careers.example.test/apply') {
  const dom = new JSDOM(html, {url, runScripts: 'outside-only'});
  const w = dom.window;
  w.CSS = {escape: String};
  let listener;
  w.chrome = {runtime: {onMessage: {addListener: value => {listener = value;}}}};
  for (const file of ['ats-adapters.js', 'content.js']) w.eval(fs.readFileSync(path.join(ext, file), 'utf8'));
  // Copied out of the page's realm, whose arrays deepEqual will not accept.
  try {return JSON.parse(JSON.stringify(await new Promise(resolve => listener({action: 'scan'}, {}, resolve))));}
  finally {w.close();}
}

const cases = {
  async the_heading_before_a_field_is_its_section() {
    // The first heading in the block named both fields, so an emergency
    // contact's name read as the applicant's own.
    const {controls} = await scan('<div><h2>Personal information</h2><input aria-label="First name">'
      + '<h2>Emergency contact</h2><input aria-label="First name"></div>');
    assert.deepEqual(controls.map(control => control.section), ['Personal information', 'Emergency contact']);
  },
  async a_radio_group_is_named_by_its_question() {
    // Named by its first option, two Yes/No questions on one page were one
    // question, and an answer to one was filled into the other.
    const {controls} = await scan(
      '<div class="q"><p>Will you require sponsorship?</p><label><input type="radio" name="a" value="y">Yes</label>'
      + '<label><input type="radio" name="a" value="n">No</label></div>'
      + '<div class="q"><p>Are you authorized to work in the US?</p><label><input type="radio" name="b" value="y">Yes</label>'
      + '<label><input type="radio" name="b" value="n">No</label></div>');
    assert.deepEqual(controls.map(control => control.label),
      ['Will you require sponsorship?', 'Are you authorized to work in the US?']);
  },
  async a_lever_radio_question() {
    const {controls} = await scan(
      '<li class="application-question"><div class="application-label">Will you now or in the future require sponsorship?</div>'
      + '<div class="application-field"><ul><li><label><input type="radio" name="cards[x][field0]" value="Yes">Yes</label></li>'
      + '<li><label><input type="radio" name="cards[x][field0]" value="No">No</label></li></ul></div></li>',
      'https://jobs.lever.co/acme/1/apply');
    assert.deepEqual(controls.map(control => control.label), ['Will you now or in the future require sponsorship?']);
  },
  async a_radio_group_with_no_question_text_is_left_alone() {
    const {controls} = await scan('<label><input type="radio" name="c" value="y">Yes</label>'
      + '<label><input type="radio" name="c" value="n">No</label>');
    assert.deepEqual(controls, []);
  },
  async boxes_without_a_legend_are_not_repeated_rows() {
    const {controls} = await scan('<fieldset><input aria-label="First name"></fieldset>'
      + '<fieldset><input aria-label="Email"></fieldset>');
    assert.deepEqual(controls.map(control => control.repeat_context || null), [null, null]);
  },
  async untitled_rows_with_the_same_questions_still_are() {
    const {controls} = await scan('<fieldset><input aria-label="School"><input aria-label="Degree"></fieldset>'
      + '<fieldset><input aria-label="School"><input aria-label="Degree"></fieldset>');
    assert.equal(new Set(controls.map(control => control.repeat_context)).size, 2);
    assert.ok(controls.every(control => control.repeat_context));
  },
  async a_punctuated_placeholder_is_not_an_answer() {
    // #275: "Select..." and "-- Select --" read as answers, and the dropdown
    // was reported occupied and never filled.
    for (const placeholder of ['Select...', '-- Select --', 'Choose an option…', 'Please select an option']) {
      const dom = new JSDOM('<label id="l">Current degree level</label><button aria-labelledby="l" aria-haspopup="listbox" '
        + 'aria-controls="box" aria-expanded="false">' + placeholder + '</button><ul role="listbox" id="box" hidden>'
        + '<li role="option">Bachelor of Science</li><li role="option">Master of Science</li></ul>',
        {url: 'https://careers.example.test/apply', runScripts: 'outside-only'});
      const w = dom.window;
      w.CSS = {escape: String};
      let listener;
      w.chrome = {runtime: {onMessage: {addListener: value => {listener = value;}}}};
      for (const file of ['ats-adapters.js', 'content.js']) w.eval(fs.readFileSync(path.join(ext, file), 'utf8'));
      const button = w.document.querySelector('button');
      const list = w.document.querySelector('ul');
      button.onclick = () => {list.hidden = !list.hidden; button.setAttribute('aria-expanded', String(!list.hidden));};
      for (const option of list.children) option.onclick = () => {
        button.textContent = option.textContent; list.hidden = true; button.setAttribute('aria-expanded', 'false');
      };
      try {
        const {controls} = await new Promise(resolve => listener({action: 'scan'}, {}, resolve));
        const outcome = await new Promise(resolve => listener({action: 'fill', results: [
          {...controls[0], status: 'verify_options', answer: 'Master of Science', answer_aliases: []}]}, {}, resolve));
        assert.equal(outcome.filled, 1, placeholder);
        assert.equal(button.textContent, 'Master of Science');
      } finally {w.close();}
    }
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
