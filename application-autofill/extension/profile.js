(() => {
  'use strict';
  const engine = JobdiscoAnswers;
  const status = document.getElementById('status');
  const controls = new Map();

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
          await chrome.storage.local.set({answerProfile: latest});
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
      await chrome.storage.local.set({answerProfile: profile});
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
      await chrome.storage.local.set({answerProfile: profile});
      renderBasics(profile);
      renderUnknown(profile);
      status.textContent = 'Saved local answers imported. Existing question mappings were preserved.';
    } catch (error) {status.textContent = error.message;}
  });

  loadProfile().then(profile => {renderBasics(profile); renderUnknown(profile);})
    .catch(error => {status.textContent = error.message;});
})();
