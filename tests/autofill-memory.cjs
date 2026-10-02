'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const ext = path.join(__dirname, '../application-autofill/extension');
const engine = require(path.join(ext, 'answer-engine.js'));
const memory = require(path.join(ext, 'portable-memory.js'));
const copy = value => JSON.parse(JSON.stringify(value));

async function main() {
  const profile = engine.initializeProfile();
  profile.fields['contact.email'].answer = 'fictional@example.test';
  profile.education = [{id: 'example-degree', school: 'Example University', extension: {preserve: true}}];
  const captures = {one: {label: 'Example question', value: 'Example answer'}};
  const exported = memory.export_memory(profile, captures);
  assert.deepEqual(exported.profile, profile);
  assert.deepEqual(exported.pending_captures, captures);
  exported.profile.fields['contact.email'].answer = 'other@example.test';
  const merged = memory.merge_memory(profile, exported);
  assert.equal(merged.profile.fields['contact.email'].answer, 'fictional@example.test');
  assert.equal(merged.conflicts, 1);
  assert.equal(merged.profile.memory.conflicts[0].conflict.incoming.answer, 'other@example.test');
  assert.deepEqual(merged.profile.memory.imports[0].document, exported);
  assert.deepEqual(profile.fields['contact.email'].answer, 'fictional@example.test');
  const added = copy(profile);
  added.fields['links.github'].answer = 'https://example.test/code';
  const result = memory.merge_memory(profile, added);
  assert.equal(result.profile.fields['links.github'].answer, 'https://example.test/code');
  assert.equal(result.profile.memory.history[0].source, 'file-import');
  const before = copy(profile);
  const revised = copy(profile);
  revised.fields['contact.phone'].answer = '555-0100';
  memory.record_changes(before, revised, 'user-edited-answers');
  assert.equal(revised.memory.revision, 1);
  assert.equal(revised.memory.history.length, 1);
  memory.record_changes(copy(revised), revised, 'unchanged');
  assert.equal(revised.memory.history.length, 1);
  const invalid = copy(profile);
  invalid.fields['contact.phone'].type = 'executable';
  assert.throws(() => memory.merge_memory(profile, invalid), /Invalid field/);
  const hostile = JSON.parse('{"version":1,"fields":{"__proto__":{"label":"Bad","type":"text","policy":"fill"}},"questions":{}}');
  assert.throws(() => memory.merge_memory(profile, hostile), /Invalid field/);
  assert.throws(() => memory.merge_memory(profile, {...exported, schema_version: 99}), /Unsupported/);
  const scoped = copy(profile);
  scoped.fields['contact.email'].reuse_scope = 'global';
  const scopeResult = memory.merge_memory(profile, scoped);
  assert.equal(scopeResult.profile.fields['contact.email'].reuse_scope, undefined);
  assert.equal(scopeResult.conflicts, 1);

  // Actual settings page: ongoing local changes serialize to the chosen file.
  const dom = new JSDOM(fs.readFileSync(path.join(ext, 'profile.html'), 'utf8'),
    {url: 'https://extension.test/profile.html', runScripts: 'outside-only'});
  const w = dom.window;
  const storage = {answerProfile: copy(profile), answerCaptures: captures};
  let changed;
  let writes = [];
  w.chrome = {runtime: {getURL: name => name}, storage: {
    onChanged: {addListener: listener => {changed = listener;}},
    local: {get: async () => copy(storage), set: async data => Object.assign(storage, copy(data))}}};
  w.showSaveFilePicker = async () => ({createWritable: async () => ({
    write: async data => {writes.push(JSON.parse(data));}, close: async () => {}, abort: async () => {}})});
  for (const file of ['answer-engine.js', 'portable-memory.js', 'profile.js']) w.eval(fs.readFileSync(path.join(ext, file), 'utf8'));
  const settle = () => new Promise(resolve => setTimeout(resolve, 15));
  await settle();
  w.document.getElementById('connect-memory').click();
  await settle();
  assert.equal(writes.length, 1);
  assert.deepEqual(writes[0].pending_captures, captures);
  storage.answerProfile.fields['contact.phone'].answer = '555-0199';
  changed({answerProfile: {}}, 'local');
  await settle();
  assert.equal(writes.at(-1).profile.fields['contact.phone'].answer, '555-0199');
  const importInput = w.document.getElementById('import-memory');
  const update = copy(storage.answerProfile);
  update.fields['links.linkedin'].answer = 'https://example.test/profile';
  Object.defineProperty(importInput, 'files', {value: [{text: async () => JSON.stringify(memory.export_memory(update))}]});
  importInput.dispatchEvent(new w.Event('change'));
  await settle();
  assert.equal(storage.answerProfile.fields['links.linkedin'].answer, 'https://example.test/profile');
  assert.match(w.document.getElementById('memory-status').textContent, /Imported/);
  const kept = copy(storage);
  w.showSaveFilePicker = async () => ({createWritable: async () => {throw new Error('Example disk failure');}});
  w.document.getElementById('connect-memory').click();
  await settle();
  assert.match(w.document.getElementById('memory-status').textContent, /Example disk failure/);
  assert.deepEqual(storage, kept);
  dom.window.close();
  console.log('Portable memory: round-trip, conflicts, scopes, history, validation, continuous file and UI import OK');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
