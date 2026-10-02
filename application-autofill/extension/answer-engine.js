(function (root) {
  'use strict';
  const normalize = value => String(value ?? '').normalize('NFKC').toLowerCase()
    .replace(/\s+/g, ' ').trim().replace(/[ *:]+$/, '').trim();
  const SAFE_SECTIONS = new Set(['', 'contact information', 'personal information',
    'applicant information', 'about you', 'contact information section', 'my information',
    'legal name', 'address', 'basic information', 'personal details', 'contact details',
    'candidate information', 'applicant details', 'your information', 'profile',
    'application', 'apply for this job']);
  // Questions, not personal answers. Negation, country and time qualifiers stay exact.
  const basicQuestions = [
    ['name.first', 'First name', 'text', 'fill', ['First name', 'Given name']],
    ['name.last', 'Last name', 'text', 'fill', ['Last name', 'Surname', 'Family name']],
    ['name.legal_full', 'Legal full name', 'text', 'fill', ['Legal full name', 'Full legal name']],
    ['name.preferred', 'Preferred name', 'text', 'fill', ['Preferred name']],
    ['contact.email', 'Email address', 'text', 'fill', ['Email', 'Email address']],
    ['contact.phone', 'Phone number', 'text', 'fill', ['Phone', 'Phone number']],
    ['address.street', 'Street address', 'text', 'fill', ['Street address', 'Street name', 'Address line 1']],
    ['address.city', 'City', 'text', 'fill', ['City']],
    ['address.state', 'State / region', 'choice', 'review', []],
    ['address.postal_code', 'Postal code', 'text', 'fill', ['Postal code', 'ZIP code', 'Zip/Postal Code']],
    ['address.country', 'Country', 'choice', 'review', []],
    ['education.current_school', 'Current school', 'text', 'review', ['Current school', 'Current university']],
    ['education.current_major', 'Current major', 'text', 'review', ['Current major', 'Current field of study']],
    ['education.current_degree', 'Current degree level', 'choice', 'review', ['Current degree level']],
    ['education.graduation_month', 'Expected graduation month', 'choice', 'review', ['Expected graduation month']],
    ['education.graduation_year', 'Expected graduation year', 'integer', 'review', ['Expected graduation year']],
    ['education.previous_school', 'Previous school', 'text', 'review', ['Previous school', 'Previous university']],
    ['education.previous_major', 'Previous major', 'text', 'review', ['Previous major']],
    ['education.previous_degree', 'Previous degree level', 'choice', 'review', ['Previous degree level']],
    ['education.previous_graduation_month', 'Previous graduation month', 'choice', 'review', ['Previous graduation month']],
    ['education.previous_graduation_year', 'Previous graduation year', 'integer', 'review', ['Previous graduation year']],
    ['eligibility.us_work_authorized', 'Are you currently authorized to work in the United States?', 'choice', 'review',
      ['Are you currently authorized to work in the United States?', 'Are you legally authorized to work in the United States?']],
    ['eligibility.us_sponsorship_now', 'Do you currently require employer sponsorship to work in the United States?', 'choice', 'review',
      ['Do you currently require employer sponsorship to work in the United States?']],
    ['eligibility.us_sponsorship_future', 'Will you require employer sponsorship to work in the United States in the future?', 'choice', 'review',
      ['Will you require employer sponsorship to work in the United States in the future?']],
    ['eligibility.us_sponsorship_any', 'Will you now or in the future require sponsorship for employment visa status?', 'choice', 'review',
      ['Will you now or in the future require sponsorship for employment visa status?']]
  ].map(([key, label, type, policy, aliases]) => ({key, label, type, policy, aliases}));

  function initializeProfile(profile = {version: 1, fields: {}, questions: {}}) {
    if (profile.version !== 1 || !profile.fields || Array.isArray(profile.fields)
      || !profile.questions || Array.isArray(profile.questions)
      || typeof profile.fields !== 'object' || typeof profile.questions !== 'object') {
      throw new Error('Local answer profile is damaged.');
    }
    basicQuestions.forEach(({key, ...definition}) => {
      if (!profile.fields[key]) profile.fields[key] = {...definition, answer: null, updated_at: null};
    });
    profile.preferences ||= {};
    // The user explicitly requested automatic filling of every known compatible answer.
    profile.preferences.fill_known_review ??= true;
    return profile;
  }

  function compatible(field, question) {
    return (question.kind === 'text' && ['text', 'choice', 'integer'].includes(field.type))
      || (question.kind === 'number' && field.type === 'integer')
      || (['select', 'radio'].includes(question.kind) && ['text', 'choice', 'integer'].includes(field.type))
      || (question.kind === 'multiselect' && field.type === 'multi_choice');
  }

  function valueMatchesType(type, value) {
    if (['text', 'choice'].includes(type)) return typeof value === 'string' && Boolean(value.trim());
    if (type === 'integer') return Number.isSafeInteger(value);
    if (type === 'multi_choice') return Array.isArray(value) && value.length > 0
      && value.every(item => typeof item === 'string' && item.trim()) && new Set(value).size === value.length;
    return false;
  }

  function aliasCandidates(profile, control) {
    if (control.repeat_context) return [];
    const label = normalize(control.label);
    // A field the page declares (see ats-adapters.js) is one more exact alias.
    // A provider's own identifier names the applicant's field wherever it sits,
    // so it needs no section check; an autocomplete token gets the same check a
    // label does. A label naming another field makes two candidates, which is
    // ambiguous and fills nothing.
    const declared = control.declared_field;
    const byProvider = Boolean(declared) && control.declared_by !== 'autocomplete';
    return Object.entries(profile.fields).filter(([key, field]) => {
      if (!compatible(field, control)) return false;
      if (key === declared && byProvider) return true;
      const identityField = /^(name|contact|address)\./.test(key);
      if (identityField && !SAFE_SECTIONS.has(normalize(control.section))) return false;
      if (key === declared) return true;
      const defaults = basicQuestions.find(item => item.key === key)?.aliases || [];
      return [...(field.aliases || []), ...defaults].some(alias => normalize(alias) === label);
    }).map(([key]) => key);
  }

  function assessKnownAnswer(profile, question, positionId = null, context = {}) {
    const candidates = question.field_key ? [question.field_key] : aliasCandidates(profile, question);
    const base = {field_key: candidates.length === 1 ? candidates[0] : null,
      known_answer: false, answer: null, status: 'unknown',
      match_type: question.field_key ? (question.binding || 'confirmed') : 'exact_alias',
      explanation: 'No confirmed mapping or exact approved alias matches this question.'};
    const reject = (status, explanation) => ({...base, status, explanation});
    if (!candidates.length) return base;
    if (candidates.length > 1) return reject('ambiguous', 'More than one saved field matches. Choose its meaning first.');
    if (question.required_position_id && question.required_position_id !== positionId) {
      return reject('position_context_required', 'This mapping belongs to another position.');
    }
    const field = profile.fields[base.field_key];
    if (!field || field.answer === null || field.answer === undefined) {
      return reject('missing_answer', 'The question is recognized, but its answer has not been supplied.');
    }
    if (field.reuse_scope === 'site' && field.source_site !== question.site) {
      return reject('scope_mismatch', 'The answer is approved only for a different site.');
    }
    if (field.reuse_scope === 'position' && (!positionId || field.source_position_id !== positionId
      || field.source_site !== question.site)) {
      return reject('position_context_required', 'The answer needs its original site and position.');
    }
    let answer = field.answer;
    if (field.context_answers) {
      if (!context.work_route || !Object.hasOwn(field.context_answers, context.work_route)) {
        return reject('context_required', 'Choose CPT or Other for this position before answering current sponsorship.');
      }
      answer = field.context_answers[context.work_route];
    }
    if (answer === null || answer === undefined) return reject('missing_answer', 'No answer is saved for this context.');
    if (!compatible(field, question) || !valueMatchesType(field.type, answer)) {
      return reject('incompatible_control', 'The saved answer does not match this control type.');
    }
    const aliases = typeof answer === 'string' ? [answer, ...(field.answer_aliases || [])] : [];
    if (['select', 'radio', 'multiselect'].includes(question.kind) && !question.options_deferred) {
      const selected = Array.isArray(answer) ? answer : [answer];
      const matched = selected.map(value => {
        const permitted = selected.length === 1 && aliases.length ? aliases : [value];
        const exact = (question.options || []).filter(option => normalize(option) === normalize(value));
        const options = exact.length ? exact
          : (question.options || []).filter(option => permitted.some(alias => normalize(alias) === normalize(option)));
        return options.length === 1 ? options[0] : null;
      });
      if (matched.some(value => value === null)) {
        return reject('option_mismatch', 'The saved answer is absent from the actual option labels.');
      }
      answer = Array.isArray(field.answer) ? matched : matched[0];
    }
    return {...base, known_answer: true, answer, answer_aliases: aliases,
      needs_review: field.policy === 'review',
      status: question.options_deferred ? 'verify_options' : field.policy === 'review' ? 'requires_review' : 'ready',
      explanation: question.options_deferred ? 'Known answer; verify the dynamic dropdown options before selecting.'
        : 'Known answer: exact mapping, valid scope, compatible type and actual options.',
      reuse_scope: field.reuse_scope || (question.binding === 'builtin' ? 'global' : 'site'),
      position_id: positionId};
  }

  const api = {normalize, basicQuestions, initializeProfile, compatible,
    valueMatchesType, aliasCandidates, assessKnownAnswer};
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.JobdiscoAnswers = api;
})(globalThis);
