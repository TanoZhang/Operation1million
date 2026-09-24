(() => {
  'use strict';

  const status = document.getElementById('status');
  const reviewPanel = document.getElementById('review-panel');
  const reviewItems = document.getElementById('review-items');
  const fillReviewButton = document.getElementById('fill-review');
  const buttons = Array.from(document.querySelectorAll('button'));
  const SAFE_SECTIONS = new Set(['', 'contact information', 'personal information',
    'applicant information', 'about you', 'contact information section',
    'my information', 'legal name', 'address', 'basic information',
    'personal details', 'contact details', 'candidate information',
    'applicant details', 'your information', 'profile', 'application',
    'apply for this job']);
  const BUILTIN_ALIASES = {
    'name.first': ['First name', 'Given name'],
    'name.last': ['Last name', 'Surname', 'Family name'],
    'name.legal_full': ['Legal full name', 'Full legal name'],
    'name.preferred': ['Preferred name'],
    'contact.email': ['Email', 'Email address'],
    'contact.phone': ['Phone', 'Phone number'],
    'address.street': ['Street address', 'Street name', 'Address line 1'],
    'address.city': ['City'],
    'address.postal_code': ['Postal code', 'ZIP code', 'Zip/Postal Code']
  };

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

  function renderReview(results) {
    const review = results.filter(item => item.status === 'requires_review');
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
        option.disabled = (value === 'position' && !item.position_id)
          || (value === 'global' && item.kind === 'combobox');
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
      if (!response.ok) throw new Error('Local answer profile is missing.');
      profile = await response.json();
    }
    if (profile.version !== 1 || !profile.fields || !profile.questions) {
      throw new Error('Local answer profile is damaged.');
    }
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
    await chrome.scripting.executeScript({target: {tabId: tab.id}, files: ['content.js']});
    const payload = await chrome.tabs.sendMessage(tab.id, {action: 'scan_v5', includeValues});
    if (!payload || payload.error) throw new Error(payload && payload.error || 'Cannot read this page.');
    return {tab, payload};
  }

  function compatible(field, question) {
    return ((question.kind === 'text' && field.type === 'text')
      || (question.kind === 'number' && field.type === 'integer')
      || (['select', 'radio', 'combobox'].includes(question.kind)
        && ['text', 'choice'].includes(field.type))
      || (question.kind === 'multiselect' && field.type === 'multi_choice'));
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
      && sameOptions(question.options, control.options));
  }

  function reusableField(profile, site, control, positionId) {
    const siteOrigin = origin(site);
    const signature = questionSignature(control);
    const scopes = control.kind === 'combobox' ? ['position', 'site']
      : ['position', 'site', 'global'];
    const groups = scopes.map(scope =>
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
    if (control.kind !== 'text' || !SAFE_SECTIONS.has(normalize(control.section))) return null;
    const label = normalize(control.label);
    const matches = Object.entries(profile.fields).filter(([key, field]) => {
      const aliases = [...(field.aliases || []), ...(BUILTIN_ALIASES[key] || [])];
      return field.type === 'text' && aliases.some(alias => normalize(alias) === label);
    });
    return matches.length === 1 ? matches[0][0] : null;
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
        binding: builtinKey ? 'builtin' : (fieldKey ? 'reused' : null),
        first_seen: new Date().toISOString(),
        last_seen: new Date().toISOString(), observations: 0
      };
      found = [questionId, profile.questions[questionId]];
    }
    found[1].last_seen = new Date().toISOString();
    found[1].observations += 1;
    return found;
  }

  function resolve(profile, questionId, question, positionId) {
    const result = {question_id: questionId, label: question.label, kind: question.kind,
      field_key: question.field_key, status: 'unknown', answer: null};
    if (!question.field_key) return result;
    if (question.required_position_id && question.required_position_id !== positionId) {
      return {...result, status: 'position_context_required'};
    }
    const field = profile.fields[question.field_key];
    if (!field || field.answer === null || field.answer === undefined) {
      return {...result, status: 'missing_answer'};
    }
    if (field.reuse_scope === 'site' && field.source_site !== question.site) {
      return {...result, status: 'scope_mismatch'};
    }
    if (field.reuse_scope === 'position'
      && (field.source_site !== question.site
        || field.source_position_id !== positionId)) {
      return {...result, status: 'position_context_required'};
    }
    if (!compatible(field, question)) return {...result, status: 'incompatible_control'};
    if (['select', 'radio', 'multiselect'].includes(question.kind)) {
      const selected = Array.isArray(field.answer) ? field.answer : [field.answer];
      if (selected.some(value => !question.options.includes(value))) {
        return {...result, status: 'option_mismatch'};
      }
    }
    const defaultScope = question.binding === 'builtin' ? 'global' : 'site';
    return {...result, status: field.policy === 'review' ? 'requires_review' : 'ready',
      answer: field.answer, reuse_scope: field.reuse_scope || defaultScope,
      position_id: positionId};
  }

  async function resolvePage(payload) {
    const {profile, learned} = await loadProfile();
    const current = absorbCaptures(profile, payload.controls.filter(control =>
      control.value !== null && control.value !== undefined && control.value !== '')
      .map(control => ({...control, site: origin(payload.site),
        position_id: payload.position_id, captured_at: new Date().toISOString()})));
    Object.keys(learned).forEach(key => { learned[key] += current[key]; });
    const results = payload.controls.map(control => {
      const [questionId, question] = observe(profile, payload.site, control,
        payload.position_id);
      return {...resolve(profile, questionId, question, payload.position_id),
        control_id: control.control_id};
    });
    await saveProfile(profile);
    return {results, learned, profile};
  }

  function valueMatchesType(type, value) {
    if (type === 'text' || type === 'choice') return typeof value === 'string' && value.trim();
    if (type === 'integer') return Number.isInteger(value);
    if (type === 'multi_choice') return Array.isArray(value) && value.length
      && value.every(item => typeof item === 'string' && item.trim());
    return false;
  }

  function controlType(kind) {
    return {text: 'text', number: 'integer', select: 'choice', radio: 'choice',
      combobox: 'choice',
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
    const {tab, payload} = await pageScan(true);
    const {results, learned} = await resolvePage(payload);
    renderReview(results);
    const outcome = await chrome.tabs.sendMessage(tab.id,
      {action: 'fill_v5', results, allowReview: false});
    if (outcome.error) throw new Error(outcome.error);
    const review = results.filter(item => item.status === 'requires_review').length;
    const unknown = results.filter(item => item.status !== 'ready'
      && item.status !== 'requires_review').length;
    const learnedText = learned.saved ? ` Remembered ${learned.saved} new answer${learned.saved === 1 ? '' : 's'}.` : '';
    const conflictText = learned.conflicts ? ` Kept ${learned.conflicts} conflicting answer${learned.conflicts === 1 ? '' : 's'} unchanged.` : '';
    show(`Filled ${outcome.filled} known field${outcome.filled === 1 ? '' : 's'}; left ${outcome.occupied} existing value${outcome.occupied === 1 ? '' : 's'} untouched; ${review} need review; ${unknown} unknown.${learnedText}${conflictText}`);
  }

  function applyReuseScopes(profile, results, selected) {
    results.forEach(item => {
      if (!selected.has(item.question_id)) return;
      const question = profile.questions[item.question_id];
      const field = question && profile.fields[question.field_key];
      if (!field) return;
      let scope = selected.get(item.question_id);
      if (!['global', 'site', 'position'].includes(scope)) scope = 'site';
      if (scope === 'global' && question.kind === 'combobox') scope = 'site';
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
    const chosen = results.filter(item => item.status === 'requires_review'
      && selected.has(item.question_id));
    const outcome = await chrome.tabs.sendMessage(tab.id,
      {action: 'fill_v5', results: chosen, allowReview: true});
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
  fillReviewButton.addEventListener('click', () => run(fillSelectedReview));
  run(fillKnown);
})();
