(() => {
  'use strict';
  const engine = JobdiscoAnswers;
  const status = document.getElementById('status');
  const controls = new Map();
  let memory_file = null;
  let file_queue = Promise.resolve();

  function sync_memory_file() {
    if (!memory_file) return Promise.resolve();
    file_queue = file_queue.catch(() => {}).then(async () => {
      const profile = await loadProfile();
      const stored = await chrome.storage.local.get('answerCaptures');
      const data = JobdiscoMemory.export_memory(profile, stored.answerCaptures || {});
      const writable = await memory_file.createWritable();
      try {
        await writable.write(JSON.stringify(data, null, 2) + '\n');
        await writable.close();
      } catch (error) {
        await writable.abort().catch(() => {});
        throw error;
      }
      document.getElementById('memory-status').textContent = `Memory file updated at ${new Date().toLocaleTimeString()}. Keep this tab open.`;
    });
    return file_queue;
  }

  chrome.storage.onChanged?.addListener((changes, area) => {
    if (area === 'local' && (changes.answerProfile || changes.answerCaptures)) {
      sync_memory_file().catch(error => {document.getElementById('memory-status').textContent = `Memory file update failed: ${error.message}`;});
    }
  });

  async function save_profile(profile, source) {
    const stored = await chrome.storage.local.get('answerProfile');
    if (globalThis.JobdiscoMemory) JobdiscoMemory.record_changes(stored.answerProfile, profile, source);
    await chrome.storage.local.set({answerProfile: profile});
  }

  async function loadProfile() {
    const stored = await chrome.storage.local.get('answerProfile');
    if (stored.answerProfile) return engine.initializeProfile(stored.answerProfile);
    const response = await fetch(chrome.runtime.getURL('local-profile.json'));
    if (!response.ok && response.status !== 404) throw new Error('Cannot read the local profile seed.');
    return engine.initializeProfile(response.ok ? await response.json() : undefined);
  }

  function renderBasics(profile) {
    document.getElementById('fill-all').checked = profile.preferences.fill_known_review;
    const container = document.getElementById('basic-questions');
    container.replaceChildren();
    engine.basicQuestions.forEach(question => {
      const label = document.createElement('label');
      label.textContent = question.label;
      const input = document.createElement('input');
      input.type = question.type === 'integer' ? 'number' : 'text';
      input.id = question.key;
      input.value = profile.fields[question.key].answer ?? '';
      input.autocomplete = 'off';
      if (question.type === 'integer') input.step = '1';
      if (question.key.startsWith('eligibility.')) input.placeholder = 'Yes / No / leave blank if unknown';
      controls.set(question.key, input);
      label.append(input);
      container.append(label);
      for (const [route, value] of Object.entries(profile.fields[question.key].context_answers || {})) {
        const contextual = document.createElement('label');
        contextual.textContent = `${question.label} — ${route === 'cpt' ? 'CPT' : 'Other / non-CPT'}`;
        const editor = document.createElement('input');
        editor.type = 'text'; editor.value = value ?? '';
        editor.placeholder = 'Yes / No / leave blank if unknown';
        controls.set(`${question.key}::${route}`, editor);
        contextual.append(editor); container.append(contextual);
      }
    });
  }

  function renderUnknown(profile) {
    const container = document.getElementById('unknown-questions');
    container.replaceChildren();
    Object.entries(profile.questions).filter(([, question]) => !question.field_key).forEach(([id, question]) => {
      const row = document.createElement('div');
      row.className = 'question';
      const text = document.createElement('p');
      text.textContent = question.label;
      const context = document.createElement('p');
      context.textContent = `${question.site} · ${question.repeat_label || question.section || 'No section'} · ${question.kind}`;
      const select = document.createElement('select');
      select.setAttribute('aria-label', `Known answer for ${question.label}`);
      select.append(new Option('Choose its meaning…', ''));
      Object.entries(profile.fields).filter(([, field]) => engine.compatible(field, question)).forEach(([key, field]) => {
        select.append(new Option(field.label, key));
      });
      const button = document.createElement('button');
      button.textContent = 'Use this answer for this exact question';
      button.addEventListener('click', async () => {
        try {
          if (!select.value) throw new Error('Choose an answer field first.');
          const latest = await loadProfile();
          const target = latest.questions[id];
          if (!target || target.field_key) throw new Error('This mapping changed. Reload the page.');
          const assessment = engine.assessKnownAnswer(latest, {...target, field_key: select.value, binding: 'confirmed'},
            target.observed_position_id,
            latest.position_contexts?.[JSON.stringify([target.site, target.observed_position_id])] || {});
          if (!assessment.known_answer) throw new Error(assessment.explanation);
          target.field_key = select.value;
          target.binding = 'confirmed';
          await save_profile(latest, 'confirmed-question-mapping');
          renderUnknown(latest);
          status.textContent = 'Exact question mapping saved. Rescan the application to fill it.';
        } catch (error) {status.textContent = error.message;}
      });
      row.append(text, context, select, button);
      container.append(row);
    });
    if (!container.children.length) container.textContent = 'No unmatched questions recorded yet.';
  }

  document.getElementById('profile-form').addEventListener('submit', async event => {
    event.preventDefault();
    try {
      const profile = await loadProfile();
      for (const question of engine.basicQuestions) {
        const raw = controls.get(question.key).value.trim();
        const value = raw === '' ? null : question.type === 'integer' ? Number(raw) : raw;
        if (value !== null && !engine.valueMatchesType(profile.fields[question.key].type, value)) {
          throw new Error(`Invalid answer for ${question.label}`);
        }
        profile.fields[question.key].answer = value;
        profile.fields[question.key].updated_at = new Date().toISOString();
        for (const route of Object.keys(profile.fields[question.key].context_answers || {})) {
          const editor = controls.get(`${question.key}::${route}`);
          if (editor) profile.fields[question.key].context_answers[route] = editor.value.trim() || null;
        }
      }
      profile.preferences.fill_known_review = document.getElementById('fill-all').checked;
      await save_profile(profile, 'user-edited-answers');
      renderUnknown(profile);
      status.textContent = 'Answers saved locally. Rescan the application page to use them.';
    } catch (error) {status.textContent = error.message;}
  });

  document.getElementById('import-seed').addEventListener('click', async () => {
    try {
      const response = await fetch(chrome.runtime.getURL('local-profile.json'), {cache: 'no-store'});
      if (!response.ok) throw new Error('No saved local profile is available.');
      const seed = engine.initializeProfile(await response.json());
      const profile = await loadProfile();
      // This explicit import refreshes seed fields; preserve browser-learned mappings.
      Object.entries(seed.fields).forEach(([key, field]) => {
        if (!profile.fields[key] || field.answer !== null && field.answer !== undefined) profile.fields[key] = field;
      });
      if (seed.education) profile.education = seed.education;
      await save_profile(profile, 'local-seed-import');
      renderBasics(profile);
      renderUnknown(profile);
      status.textContent = 'Saved local answers imported. Existing question mappings were preserved.';
    } catch (error) {status.textContent = error.message;}
  });

  document.getElementById('export-memory').addEventListener('click', async () => {
    try {
      const profile = await loadProfile();
      const stored = await chrome.storage.local.get('answerCaptures');
      const memory = JobdiscoMemory.export_memory(profile, stored.answerCaptures || {});
      const url = URL.createObjectURL(new Blob([JSON.stringify(memory, null, 2) + '\n'], {type: 'application/json'}));
      const anchor = document.createElement('a');
      anchor.href = url; anchor.download = 'autofill-memory.json'; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      document.getElementById('memory-status').textContent = 'Latest memory exported, including pending learned values.';
    } catch (error) {status.textContent = error.message;}
  });

  document.getElementById('connect-memory').addEventListener('click', async () => {
    try {
      if (!window.showSaveFilePicker) throw new Error('Continuous file saving is unavailable in this browser. Use Export latest memory JSON.');
      memory_file = await window.showSaveFilePicker({suggestedName: 'autofill-memory.json',
        types: [{description: 'Autofill memory JSON', accept: {'application/json': ['.json']}}]});
      await sync_memory_file();
    } catch (error) {document.getElementById('memory-status').textContent = error.message;}
  });

  document.getElementById('import-memory').addEventListener('change', async event => {
    try {
      const file = event.target.files[0];
      if (!file) return;
      const result = JobdiscoMemory.merge_memory(await loadProfile(), JSON.parse(await file.text()));
      await chrome.storage.local.set({answerProfile: result.profile});
      renderBasics(result.profile); renderUnknown(result.profile);
      document.getElementById('memory-status').textContent = `Imported ${result.added} additions; preserved ${result.conflicts} conflicts. Existing answers were retained.`;
    } catch (error) {status.textContent = error.message;}
    finally {event.target.value = '';}
  });

  loadProfile().then(profile => {renderBasics(profile); renderUnknown(profile);})
    .catch(error => {status.textContent = error.message;});
})();
