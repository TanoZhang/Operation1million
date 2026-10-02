(function (root) {
  'use strict';
  const FORMAT = 'jobdisco-autofill-memory';
  const clone = value => JSON.parse(JSON.stringify(value));
  const equal = (left, right) => JSON.stringify(left) === JSON.stringify(right);
  const object = value => value && typeof value === 'object' && !Array.isArray(value);
  const unsafe_key = key => ['__proto__', 'prototype', 'constructor'].includes(key);

  function validate_profile(profile) {
    if (!object(profile) || profile.version !== 1 || !object(profile.fields) || !object(profile.questions)) {
      throw new Error('Expected a version 1 answer profile with fields and questions.');
    }
    if (profile.memory && (!object(profile.memory) || !Number.isInteger(profile.memory.revision)
      || profile.memory.revision < 0 || !Array.isArray(profile.memory.history)
      || !Array.isArray(profile.memory.conflicts))) throw new Error('Invalid memory history.');
    for (const [key, field] of Object.entries(profile.fields)) {
      if (unsafe_key(key) || !object(field) || typeof field.label !== 'string'
        || !['text', 'integer', 'boolean', 'choice', 'multi_choice'].includes(field.type)
        || !['fill', 'review'].includes(field.policy)) throw new Error(`Invalid field: ${key}`);
      const valid = value => value === null || value === undefined
        || (['text', 'choice'].includes(field.type) && typeof value === 'string')
        || (field.type === 'integer' && Number.isInteger(value))
        || (field.type === 'boolean' && typeof value === 'boolean')
        || (field.type === 'multi_choice' && Array.isArray(value) && value.every(item => typeof item === 'string'));
      if (!valid(field.answer) || field.context_answers && (!object(field.context_answers)
        || !Object.values(field.context_answers).every(valid))) throw new Error(`Invalid answer: ${key}`);
      if (field.reuse_scope && !['global', 'site', 'position'].includes(field.reuse_scope)) throw new Error(`Invalid scope: ${key}`);
    }
    for (const [key, question] of Object.entries(profile.questions)) {
      if (unsafe_key(key) || !object(question) || typeof question.label !== 'string'
        || typeof question.site !== 'string' || !question.site.startsWith('https://')
        || !['text', 'number', 'select', 'radio', 'multiselect', 'checkbox'].includes(question.kind)
        || !Array.isArray(question.options) || !question.options.every(item => typeof item === 'string')
        || question.field_key && !Object.hasOwn(profile.fields, question.field_key)) {
        throw new Error(`Invalid question: ${key}`);
      }
    }
    return profile;
  }

  function record_changes(before, profile, source, stamp = new Date().toISOString()) {
    profile.memory ||= {revision: 0, history: [], conflicts: []};
    const changes = [];
    for (const collection of ['fields', 'questions', 'education', 'employment', 'extensions', 'preferences', 'position_contexts']) {
      if (!equal(before?.[collection], profile[collection])) {
        changes.push({collection, before: before?.[collection] ?? null, after: profile[collection] ?? null});
      }
    }
    if (changes.length) {
      profile.memory.revision += 1;
      profile.memory.history.push({revision: profile.memory.revision, at: stamp, source, changes: clone(changes)});
    }
    return profile;
  }

  function export_memory(profile, captures = {}, stamp = new Date().toISOString()) {
    validate_profile(profile);
    return {format: FORMAT, schema_version: 1, exported_at: stamp,
      profile: clone(profile), pending_captures: clone(captures)};
  }

  function merge_memory(current, document, stamp = new Date().toISOString()) {
    const envelope = document.format === FORMAT;
    if (envelope && document.schema_version !== 1) throw new Error('Unsupported memory schema version.');
    const incoming = validate_profile(envelope ? document.profile : document);
    const profile = clone(validate_profile(current));
    const before = clone(profile);
    profile.memory ||= {revision: 0, history: [], conflicts: []};
    let added = 0;
    let conflicts = 0;
    // Existing facts, scopes, mappings and settings are never silently replaced.
    for (const collection of ['fields', 'questions']) {
      for (const [key, value] of Object.entries(incoming[collection])) {
        const previous = profile[collection][key];
        if (!Object.hasOwn(profile[collection], key)) {
          profile[collection][key] = clone(value); added += 1;
        } else if (collection === 'fields' && previous.answer == null && value.answer != null
          && previous.type === value.type && !previous.context_answers && !value.context_answers
          && equal(previous.reuse_scope, value.reuse_scope)
          && equal(previous.source_site, value.source_site)
          && equal(previous.source_position_id, value.source_position_id)) {
          previous.answer = clone(value.answer); previous.updated_at = stamp; added += 1;
        } else if (!equal(previous, value)) {
          const conflict = {collection, key, current: clone(previous), incoming: clone(value)};
          if (!profile.memory.conflicts.some(item => equal(item.conflict, conflict))) {
            profile.memory.conflicts.push({at: stamp, source: 'file-import', conflict});
            conflicts += 1;
          }
        }
      }
    }
    for (const collection of ['education', 'employment', 'extensions', 'position_contexts']) {
      if (incoming[collection] === undefined) continue;
      if (profile[collection] === undefined) profile[collection] = clone(incoming[collection]);
      else if (!equal(profile[collection], incoming[collection])) {
        profile.memory.conflicts.push({at: stamp, source: 'file-import', conflict: {
          collection, key: collection, current: clone(profile[collection]), incoming: clone(incoming[collection])}});
        conflicts += 1;
      }
    }
    // Preserve the complete source document, including its history, for lossless recovery.
    profile.memory.imports ||= [];
    profile.memory.imports.push({at: stamp, document: clone(document)});
    record_changes(before, profile, 'file-import', stamp);
    return {profile, added, conflicts};
  }

  const api = {validate_profile, record_changes, export_memory, merge_memory};
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.JobdiscoMemory = api;
})(globalThis);
