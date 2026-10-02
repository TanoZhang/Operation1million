(() => {
  'use strict';

  const status = document.getElementById('status');
  const reviewPanel = document.getElementById('review-panel');
  const reviewItems = document.getElementById('review-items');
  const fillReviewButton = document.getElementById('fill-review');
  const buttons = Array.from(document.querySelectorAll('button'));

  function normalize(value) {
    return String(value || '').normalize('NFKC').toLocaleLowerCase()
      .replace(/\s+/g, ' ').trim().replace(/[ *:]+$/, '').trim();
  }

  function origin(url) {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:') throw new Error('Open an HTTPS application page first.');
    return parsed.origin;
  }

  function sameOptions(left, right) {
    const ordered = value => Array.from(new Set(value || [])).sort();
    return JSON.stringify(ordered(left)) === JSON.stringify(ordered(right));
  }

  function questionSignature(control) {
    const options = Array.from(new Set((control.options || []).map(normalize))).sort();
    return JSON.stringify([normalize(control.label), control.kind, options]);
  }

  function setBusy(value) {
    buttons.forEach(button => { button.disabled = value; });
    if (!value) updateReviewButton();
  }

  function show(message) {
    status.textContent = message;
  }

  function displayAnswer(value) {
    return Array.isArray(value) ? value.join(', ') : String(value);
  }

  function selectedReviewItems() {
    return new Map(Array.from(reviewItems.querySelectorAll('input:checked'))
      .map(input => [input.value, input.closest('.review-item')
        .querySelector('.review-scope').value]));
  }

  function updateReviewButton() {
    fillReviewButton.disabled = selectedReviewItems().size === 0;
  }

  function needsReview(item) {
    return item.status === 'requires_review' || item.status === 'verify_options' && item.needs_review;
  }

  function renderReview(results) {
    const review = results.filter(needsReview);
    reviewItems.replaceChildren();
    review.forEach(item => {
      const row = document.createElement('div');
      row.className = 'review-item';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.value = item.question_id;
      checkbox.setAttribute('aria-label', `Select ${item.label}`);
      checkbox.addEventListener('change', updateReviewButton);
      const question = document.createElement('span');
      question.className = 'review-label';
      question.textContent = item.label;
      const answer = document.createElement('span');
      answer.className = 'review-answer';
      answer.textContent = displayAnswer(item.answer);
      const scope = document.createElement('select');
      scope.className = 'review-scope';
      scope.setAttribute('aria-label', `Reuse scope for ${item.label}`);
      [['global', 'All sites'], ['site', 'This site'],
        ['position', 'This position']].forEach(([value, label]) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        option.disabled = value === 'position' && !item.position_id;
        scope.append(option);
      });
      scope.value = item.reuse_scope || 'site';
      row.append(checkbox, question, answer, scope);
      reviewItems.append(row);
    });
    reviewPanel.hidden = review.length === 0;
    fillReviewButton.disabled = true;
  }

  async function loadProfile() {
    const stored = await chrome.storage.local.get(['answerProfile', 'answerCaptures']);
    let profile = stored.answerProfile;
    if (!profile) {
      const response = await fetch(chrome.runtime.getURL('local-profile.json'), {cache: 'no-store'});
      if (!response.ok && response.status !== 404) throw new Error('Cannot read the local answer profile.');
      profile = response.ok ? await response.json() : undefined;
    }
    profile = JobdiscoAnswers.initializeProfile(profile);
    const learned = absorbCaptures(profile, Object.values(stored.answerCaptures || {}));
    await chrome.storage.local.set({answerProfile: profile, answerCaptures: {}});
    return {profile, learned};
  }

  async function saveProfile(profile) {
    await chrome.storage.local.set({answerProfile: profile});
  }

  async function activeTab() {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    if (!tab || !/^https:\/\//i.test(tab.url || '')) {
      throw new Error('Open an HTTPS application page first.');
    }
    return tab;
  }

  async function pageScan(includeValues = false) {
    const tab = await activeTab();
    await chrome.scripting.executeScript({target: {tabId: tab.id}, files: ['ats-adapters.js', 'content.js']});
    const payload = await chrome.tabs.sendMessage(tab.id, {action: 'scan', includeValues});
    if (!payload || payload.error) throw new Error(payload && payload.error || 'Cannot read this page.');
    return {tab, payload};
  }

  function findQuestion(profile, site, control, positionId) {
    const siteOrigin = origin(site);
    return Object.entries(profile.questions).find(([, question]) =>
      question.site === siteOrigin
      && (!question.required_position_id
        || question.required_position_id === positionId)
      && normalize(question.section) === normalize(control.section)
      && question.normalized === normalize(control.label)
      && question.kind === control.kind
      && (question.repeat_context || '') === (control.repeat_context || '')
      && Boolean(question.options_deferred) === Boolean(control.options_deferred)
      && sameOptions(question.options, control.options));
  }

  function reusableField(profile, site, control, positionId) {
    if (control.repeat_context) return null;
    const siteOrigin = origin(site);
    const signature = questionSignature(control);
    const groups = ['position', 'site', 'global'].map(scope =>
      Object.entries(profile.fields).filter(([, field]) => {
        if (field.reuse_scope !== scope || field.reuse_signature !== signature) return false;
        if (field.answer === null || field.answer === undefined) return false;
        if (scope === 'site') return field.source_site === siteOrigin;
        if (scope === 'position') {
          return field.source_site === siteOrigin
            && field.source_position_id === positionId;
        }
        return true;
      }));
    const candidates = groups.find(group => group.length) || [];
    return candidates.length === 1 ? candidates[0][0] : null;
  }

  function builtinField(profile, control) {
    const matches = JobdiscoAnswers.aliasCandidates(profile, control);
    return matches.length === 1 ? matches[0] : null;
  }

  function observe(profile, site, control, positionId = null) {
    let found = findQuestion(profile, site, control, positionId);
    if (!found) {
      const questionId = crypto.randomUUID();
      const builtinKey = builtinField(profile, control);
      const fieldKey = builtinKey || reusableField(profile, site, control, positionId);
      profile.questions[questionId] = {
        site: origin(site), section: control.section || '', label: control.label,
        normalized: normalize(control.label), kind: control.kind,
        options: Array.from(new Set(control.options || [])).sort(), field_key: fieldKey,
        options_deferred: Boolean(control.options_deferred),
        repeat_context: control.repeat_context || '', repeat_label: control.repeat_label || '',
        binding: builtinKey ? 'builtin' : (fieldKey ? 'reused' : null),
        first_seen: new Date().toISOString(),
        last_seen: new Date().toISOString(), observations: 0,
        observed_position_id: positionId
      };
      found = [questionId, profile.questions[questionId]];
    }
    // An unknown question can have been observed before a reusable mapping was
    // approved elsewhere. Reconsider it without replacing an existing binding.
    if (!found[1].field_key) {
      const builtinKey = builtinField(profile, control);
      const fieldKey = builtinKey || reusableField(profile, site, control, positionId);
      if (fieldKey) {
        found[1].field_key = fieldKey;
        found[1].binding = builtinKey ? 'builtin' : 'reused';
      }
    }
    found[1].last_seen = new Date().toISOString();
    found[1].observations += 1;
    return found;
  }

  function resolve(profile, questionId, question, positionId, context = {}) {
    return {question_id: questionId, label: question.label,
      ...JobdiscoAnswers.assessKnownAnswer(profile, question, positionId, context)};
  }

  function renderAssessments(payload, results) {
    const report = document.getElementById('question-report');
    if (!report) return;
    report.replaceChildren();
    const platform = document.createElement('p');
    platform.textContent = `Detected form: ${payload.ats || 'generic'}`;
    report.append(platform);
    results.forEach(item => {
      const row = document.createElement('p');
      row.textContent = `${item.label}: ${item.known_answer ? 'known answer' : item.status}. ${item.explanation}`;
      report.append(row);
    });
  }

  async function resolvePage(payload) {
    const {profile, learned} = await loadProfile();
    const contextKey = JSON.stringify([origin(payload.site), payload.position_id]);
    const context = profile.position_contexts?.[contextKey] || {};
    const route = document.getElementById('application-route');
    if (route) route.value = context.work_route || '';
    const results = payload.controls.map(control => {
      const [questionId, question] = observe(profile, payload.site, control,
        payload.position_id);
      return {...resolve(profile, questionId, question, payload.position_id, context),
        control_id: control.control_id};
    });
    await saveProfile(profile);
    return {results, learned, profile};
  }

  const valueMatchesType = JobdiscoAnswers.valueMatchesType;

  function controlType(kind) {
    return {text: 'text', number: 'integer', select: 'choice', radio: 'choice',
      multiselect: 'multi_choice'}[kind];
  }

  function absorbCaptures(profile, captures) {
    const summary = {saved: 0, unchanged: 0, conflicts: 0, ignored: 0};
    captures.forEach(control => {
      if (!valueMatchesType(controlType(control.kind), control.value)) {
        summary.ignored += 1;
        return;
      }
      const [questionId, question] = observe(profile, control.site, control,
        control.position_id);
      if (question.required_position_id
        && question.required_position_id !== control.position_id) {
        summary.ignored += 1;
        return;
      }
      if (!question.field_key) {
        question.field_key = `learned.q_${questionId.replaceAll('-', '').slice(0, 20)}`;
        question.binding = 'learned';
        profile.fields[question.field_key] = {label: question.label,
          type: controlType(question.kind), policy: 'review', aliases: [],
          answer: null, updated_at: null, reuse_scope: 'site',
          reuse_signature: questionSignature(question), source_site: question.site,
          source_position_id: null};
      }
      const field = profile.fields[question.field_key];
      if (!field || !valueMatchesType(field.type, control.value)) {
        summary.ignored += 1;
      } else if (field.answer === null || field.answer === undefined) {
        field.answer = control.value;
        field.updated_at = control.captured_at || new Date().toISOString();
        summary.saved += 1;
      } else if (JSON.stringify(field.answer) === JSON.stringify(control.value)) {
        summary.unchanged += 1;
      } else {
        summary.conflicts += 1;
      }
    });
    return summary;
  }

  async function fillKnown() {
    const {tab, payload} = await pageScan(false);
    const {results, learned, profile} = await resolvePage(payload);
    renderReview(profile.preferences.fill_known_review ? [] : results);
    renderAssessments(payload, results);
    const allowReview = profile.preferences.fill_known_review;
    const outcome = await chrome.tabs.sendMessage(tab.id,
      {action: 'fill', results, allowReview});
    if (outcome.error) throw new Error(outcome.error);
    const review = allowReview ? 0 : results.filter(needsReview).length;
    const unknown = results.filter(item => !item.known_answer).length;
    const learnedText = learned.saved ? ` Remembered ${learned.saved} new answer${learned.saved === 1 ? '' : 's'}.` : '';
    const conflictText = learned.conflicts ? ` Kept ${learned.conflicts} conflicting answer${learned.conflicts === 1 ? '' : 's'} unchanged.` : '';
    show(`Filled ${outcome.filled} known field${outcome.filled === 1 ? '' : 's'}; left ${outcome.occupied} existing value${outcome.occupied === 1 ? '' : 's'} untouched; ${review} need review; ${unknown} unknown or missing context; ${outcome.unresolved || 0} unfilled.${learnedText}${conflictText}`);
  }

  function applyReuseScopes(profile, results, selected) {
    results.forEach(item => {
      if (!selected.has(item.question_id)) return;
      const question = profile.questions[item.question_id];
      const field = question && profile.fields[question.field_key];
      if (!field) return;
      let scope = selected.get(item.question_id);
      if (!['global', 'site', 'position'].includes(scope)) scope = 'site';
      if (scope === 'position' && !item.position_id) scope = 'site';
      field.reuse_scope = scope;
      field.reuse_signature = questionSignature(question);
      field.source_site = question.site;
      field.source_position_id = scope === 'position' ? item.position_id : null;
      if (scope === 'position') question.required_position_id = item.position_id;
      else delete question.required_position_id;
      item.reuse_scope = scope;
    });
  }

  async function fillSelectedReview() {
    const selected = selectedReviewItems();
    if (!selected.size) return;
    const {tab, payload} = await pageScan(false);
    const {results, profile} = await resolvePage(payload);
    applyReuseScopes(profile, results, selected);
    await saveProfile(profile);
    const chosen = results.filter(item => needsReview(item)
      && selected.has(item.question_id));
    const outcome = await chrome.tabs.sendMessage(tab.id,
      {action: 'fill', results: chosen, allowReview: true});
    if (outcome.error) throw new Error(outcome.error);
    renderReview(results);
    show(`Filled ${outcome.filled} selected answer${outcome.filled === 1 ? '' : 's'}; left ${outcome.occupied} existing value${outcome.occupied === 1 ? '' : 's'} untouched.`);
  }

  async function run(operation) {
    setBusy(true);
    try {
      await operation();
    } catch (error) {
      show(error.message);
    } finally {
      setBusy(false);
    }
  }

  document.getElementById('fill-known').addEventListener('click', () => run(fillKnown));
  document.getElementById('edit-answers')?.addEventListener('click', () => chrome.runtime.openOptionsPage());
  document.getElementById('application-route')?.addEventListener('change', event => {
    const workRoute = event.target.value;
    run(async () => {
      const {payload} = await pageScan(false);
      if (!payload.position_id) throw new Error('This page has no position identity. Leave contextual answers manual.');
      const {profile} = await loadProfile();
      profile.position_contexts ||= {};
      profile.position_contexts[JSON.stringify([origin(payload.site), payload.position_id])] = {work_route: workRoute};
      await saveProfile(profile);
      await fillKnown();
    });
  });
  fillReviewButton.addEventListener('click', () => run(fillSelectedReview));
  run(fillKnown);
})();
