(() => {
  'use strict';

  if (globalThis.__jobdiscoAutofillInstalled) return;
  globalThis.__jobdiscoAutofillInstalled = true;

  const UNSAFE_INPUT_TYPES = new Set(['button', 'file', 'hidden', 'image', 'password',
    'reset', 'search', 'submit', 'checkbox']);
  const BLOCKED_LABEL_WORDS = ['password', 'passcode', 'security code',
    'social security', 'ssn', 'passport number', 'driver license', 'signature',
    'i certify', 'i agree', 'acknowledge', 'consent', 'terms and conditions',
    'privacy policy', 'captcha', 'verification code'];
  let nextControlId = 1;
  let captureQueue = Promise.resolve();
  const scannedControls = new Map();
  const repeatIds = new WeakMap();

  // The questions a row asks, for telling untitled rows apart.
  function rowQuestions(group) {
    return Array.from(group.querySelectorAll('input, select, textarea'))
      .map(control => normalized(cleanText(control.getAttribute('aria-label')) || control.name || control.type))
      .join('|');
  }

  function repeatContext(element) {
    const selector = 'fieldset, [data-automation-id="educationSection"], [data-automation-id="workExperienceSection"]';
    const group = element.closest(selector);
    if (!group) return {};
    const titleOf = peer => cleanText(peer.querySelector('legend, h2, h3, h4')?.textContent)
      || peer.getAttribute('data-automation-id') || '';
    const title = titleOf(group);
    // An untitled box repeats another only when it asks the same questions:
    // a page's two plain fieldsets, one holding a name and one an email, were
    // read as rows of one section, and nothing in either was matched (2026-10-02).
    const questions = title ? null : rowQuestions(group);
    const peers = Array.from(document.querySelectorAll(selector)).filter(peer =>
      titleOf(peer) === title && (title || rowQuestions(peer) === questions));
    if (peers.length < 2) return {};
    // A repeated row has no known education meaning merely because it is first.
    // Keep explicit mappings tied to this DOM row; do not reuse them after replacement.
    if (!repeatIds.has(group)) repeatIds.set(group, crypto.randomUUID());
    return {repeat_context: repeatIds.get(group), repeat_label: `${title || 'Repeated section'} ${peers.indexOf(group) + 1}`};
  }

  function cleanText(value) {
    return (value || '').replace(/\s+/g, ' ').replace(/\s*[*:]\s*$/, '').trim();
  }

  function textFromIds(value) {
    return (value || '').split(/\s+/).map(id => document.getElementById(id))
      .filter(Boolean).map(node => cleanText(node.textContent)).filter(Boolean).join(' ');
  }

  function nearbyLabel(element) {
    const aria = cleanText(element.getAttribute('aria-label'));
    if (aria) return aria;
    const labelled = textFromIds(element.getAttribute('aria-labelledby'));
    if (labelled) return labelled;
    if (element.id) {
      const explicit = document.querySelector(`label[for="${CSS.escape(element.id)}"]`);
      if (explicit && cleanText(explicit.textContent)) return cleanText(explicit.textContent);
    }
    const wrapping = element.closest('label');
    if (wrapping && cleanText(wrapping.textContent)) return cleanText(wrapping.textContent);
    const atsLabel = globalThis.JobdiscoATS?.metadata(element, location.href).label;
    if (atsLabel) return atsLabel;
    for (let node = element.parentElement, depth = 0; node && depth < 5; node = node.parentElement, depth += 1) {
      const candidate = node.querySelector(':scope > label, :scope > legend, :scope > [data-automation-id="formLabel"]');
      if (candidate && cleanText(candidate.textContent)) return cleanText(candidate.textContent);
    }
    return cleanText(element.getAttribute('placeholder'));
  }

  function sectionLabel(element) {
    const fieldset = element.closest('fieldset');
    if (fieldset) {
      const legend = fieldset.querySelector(':scope > legend');
      if (legend && cleanText(legend.textContent)) return cleanText(legend.textContent);
    }
    for (let node = element.parentElement, depth = 0; node && depth < 8; node = node.parentElement, depth += 1) {
      // The last heading before the field, not the first in its block: a block
      // holding "Personal information" and then "Emergency contact" filed the
      // contact's name under the applicant's section (2026-10-02).
      const before = Array.from(node.querySelectorAll(':scope > h1, :scope > h2, :scope > h3, :scope > h4, :scope > [data-automation-id="sectionTitle"]'))
        .filter(heading => cleanText(heading.textContent)
          && heading.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING);
      if (before.length) return cleanText(before[before.length - 1].textContent);
    }
    return '';
  }

  function controlId(element) {
    if (!element.dataset.jobdiscoControlId) {
      element.dataset.jobdiscoControlId = `jobdisco-${nextControlId++}`;
    }
    return element.dataset.jobdiscoControlId;
  }

  function isUsable(element) {
    // :disabled includes inheritance from a fieldset, with its first-legend exception.
    if (element.matches(':disabled') || element.readOnly || element.getAttribute('aria-disabled') === 'true') return false;
    if (element instanceof HTMLInputElement && UNSAFE_INPUT_TYPES.has(element.type)
      && !(element.type === 'search' && isCustomChoice(element))) return false;
    if (element.getAttribute('role') === 'combobox' && !isCustomChoice(element)) return false;
    const style = getComputedStyle(element);
    if (style.visibility === 'hidden' || style.visibility === 'collapse') return false;
    for (let node = element; node; node = node.parentElement) {
      if (node.hidden || node.hasAttribute('inert') || getComputedStyle(node).display === 'none') return false;
    }
    return true;
  }

  function usableOption(option) {
    const group = option.closest('optgroup');
    return !option.disabled && !(group && group.disabled) && option.value !== '';
  }

  function isCustomChoice(element) {
    return !(element instanceof HTMLSelectElement)
      && (element.getAttribute('role') === 'combobox' || element.getAttribute('aria-haspopup') === 'listbox')
      && Boolean(element.getAttribute('aria-controls') || element.getAttribute('aria-owns'))
      && element.getAttribute('aria-multiselectable') !== 'true';
  }

  function customValue(element) {
    const value = element instanceof HTMLInputElement ? element.value
      : element.getAttribute('aria-valuetext') || cleanText(element.textContent);
    return /^(select(?: one| an option)?|choose(?: one| an option)?|please select|search)?$/i.test(value.trim()) ? '' : value;
  }

  function describeCustomControl(element, includeValues) {
    const label = nearbyLabel(element);
    if (!label || blockedLabel(label)) return null;
    return {control_id: controlId(element), label, section: sectionLabel(element),
      kind: 'select', options: [], options_deferred: true,
      ...repeatContext(element),
      ...(includeValues ? {value: customValue(element)} : {})};
  }

  function ownedListbox(element) {
    const ids = (element.getAttribute('aria-controls') || element.getAttribute('aria-owns') || '').split(/\s+/);
    const boxes = ids.map(id => document.getElementById(id)).filter(box => box?.getAttribute('role') === 'listbox');
    return boxes.length === 1 ? boxes[0] : null;
  }

  function waitFor(predicate, milliseconds = 800) {
    return new Promise(resolve => {
      let observer;
      let timer;
      const finish = value => {observer?.disconnect(); clearTimeout(timer); resolve(value);};
      const check = () => {const result = predicate(); if (result) finish(result);};
      observer = new MutationObserver(check);
      observer.observe(document.body, {subtree: true, childList: true, attributes: true, characterData: true});
      timer = setTimeout(() => finish(null), milliseconds);
      check();
    });
  }

  async function fillCustomChoice(element, match) {
    if (customValue(element)) return 'occupied';
    const originalValue = element instanceof HTMLInputElement ? element.value : null;
    const openedHere = element.getAttribute('aria-expanded') !== 'true';
    const aliases = Array.from(new Set([String(match.answer), ...(match.answer_aliases || [])]));
    if (openedHere) element.click();
    try {
      for (const query of aliases.slice(0, 4)) {
        const search = element instanceof HTMLInputElement ? element
          : ownedListbox(element)?.querySelector('input[type="text"], input[type="search"]');
        if (search) {
          setNativeValue(search, query);
          search.dispatchEvent(new Event('input', {bubbles: true}));
        }
        const options = await waitFor(() => {
          const box = ownedListbox(element);
          if (!box || getComputedStyle(box).display === 'none' || box.hidden) return null;
          const members = Array.from(box.querySelectorAll('[role="option"]'))
            .filter(option => option.getAttribute('aria-disabled') !== 'true' && isUsable(option));
          const exact = members.filter(option => normalized(match.answer) === normalized(option.textContent));
          const candidates = exact.length ? exact
            : members.filter(option => aliases.some(alias => normalized(alias) === normalized(option.textContent)));
          return candidates.length ? candidates : null;
        });
        if (!options) continue;
        if (options.length !== 1) return 'option_mismatch';
        const current = describeCustomControl(element, false);
        if (!isUsable(element) || !current || scannedControls.get(match.control_id) !== controlSignature(current)
          || !options[0].isConnected) return 'unavailable';
        const label = cleanText(options[0].textContent);
        options[0].click();
        const accepted = await waitFor(() => element.getAttribute('aria-expanded') === 'false'
          && normalized(customValue(element)) === normalized(label));
        if (accepted) return 'filled';
        return 'unavailable';
      }
      return 'option_mismatch';
    } finally {
      if (element.getAttribute('aria-expanded') === 'true') {
        if (originalValue !== null) {
          setNativeValue(element, originalValue);
          element.dispatchEvent(new Event('input', {bubbles: true}));
        }
        if (openedHere) element.click();
      }
    }
  }

  function radioLabel(element) {
    return nearbyLabel(element) || cleanText(element.value);
  }

  function blockedLabel(label) {
    const normalized = label.toLocaleLowerCase();
    return BLOCKED_LABEL_WORDS.some(word => normalized.includes(word));
  }

  // The question a radio group asks, where no legend or radiogroup names it:
  // the first text before the options in the block holding them all. An
  // option's own label ("Yes") is never the question -- named by its first
  // option, every Yes/No question on a page was one question, and an answer
  // to one was filled into the next (2026-10-02). None found means the group
  // is left alone.
  function groupQuestion(first, members) {
    const options = new Set(members.map(member => normalized(radioLabel(member))));
    const candidates = [globalThis.JobdiscoATS?.metadata(first, location.href).label, nearbyLabel(first)];
    let node = first.parentElement;
    while (node && !members.every(member => node.contains(member))) node = node.parentElement;
    for (let depth = 0; node && depth < 3; node = node.parentElement, depth += 1) {
      for (const child of node.children) {
        if (members.some(member => child.contains(member))) break;
        candidates.push(cleanText(child.textContent));
      }
    }
    return candidates.find(text => text && !options.has(normalized(text))) || '';
  }

  function describeRadioGroup(first, members, includeValues) {
    const fieldset = first.closest('fieldset');
    const legend = fieldset && fieldset.querySelector(':scope > legend');
    const group = first.closest('[role="radiogroup"]');
    const groupLabel = group && (cleanText(group.getAttribute('aria-label'))
      || textFromIds(group.getAttribute('aria-labelledby')));
    const label = cleanText(legend && legend.textContent) || groupLabel || groupQuestion(first, members);
    if (!label || blockedLabel(label)) return null;
    const selected = members.find(item => item.checked);
    return {
      control_id: controlId(first),
      label,
      section: sectionLabel(first),
      kind: 'radio',
      ...repeatContext(first),
      options: members.filter(isUsable).map(radioLabel).filter(Boolean),
      ...(includeValues ? {value: selected && isUsable(selected) ? radioLabel(selected) : ''} : {})
    };
  }

  function describeControl(element, includeValues) {
    const label = nearbyLabel(element);
    if (!label || blockedLabel(label)) return null;
    let kind = 'text';
    let options = [];
    let value = element.value;
    if (element instanceof HTMLSelectElement) {
      kind = element.multiple ? 'multiselect' : 'select';
      const realOptions = Array.from(element.options).filter(usableOption);
      options = realOptions.map(option => cleanText(option.textContent)).filter(Boolean);
      value = element.multiple
        ? Array.from(element.selectedOptions).filter(usableOption).map(option => cleanText(option.textContent))
        : (element.selectedOptions[0] && usableOption(element.selectedOptions[0])
          ? cleanText(element.selectedOptions[0].textContent) : '');
    } else if (element instanceof HTMLInputElement && element.type === 'number') {
      kind = 'number';
      value = element.value === '' ? '' : Number(element.value);
    } else if (element instanceof HTMLInputElement && element.type === 'checkbox') {
      kind = 'checkbox';
      value = element.checked;
    }
    return {
      control_id: controlId(element), section: sectionLabel(element), kind, options,
      ...(globalThis.JobdiscoATS ? JobdiscoATS.metadata(element, location.href) : {}),
      label,
      ...repeatContext(element),
      ...(includeValues ? {value} : {})
    };
  }

  function scan(includeValues = false) {
    const controls = [];
    const radios = new Set();
    document.querySelectorAll('input, textarea, select, [role="combobox"], button[aria-haspopup="listbox"]').forEach(element => {
      if (!isUsable(element)) return;
      if (isCustomChoice(element)) {
        const described = describeCustomControl(element, includeValues);
        if (described) controls.push(described);
        return;
      }
      if (!(element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement)) return;
      if (element instanceof HTMLInputElement && element.type === 'radio') {
        if (radios.has(element)) return;
        const members = radioMembers(element);
        members.forEach(member => radios.add(member));
        const described = describeRadioGroup(element, members, includeValues);
        if (described) controls.push(described);
        return;
      }
      const described = describeControl(element, includeValues);
      if (described) controls.push(described);
    });
    scannedControls.clear();
    controls.forEach(control => scannedControls.set(control.control_id, controlSignature(control)));
    return {site: location.href, position_id: positionId(),
      ats: globalThis.JobdiscoATS?.detect(location.href).id || 'generic', controls};
  }

  function normalized(value) {
    return String(value || '').normalize('NFKC').toLocaleLowerCase()
      .replace(/\s+/g, ' ').trim().replace(/[ *:]+$/, '').trim();
  }

  function radioMembers(element) {
    // HTML groups radios by name, form owner and tree, not by fieldset.
    // A radio with no name has no group, even beside another unnamed radio.
    return element.name
      ? Array.from(element.getRootNode().querySelectorAll('input[type="radio"]'))
        .filter(member => member.name === element.name && member.form === element.form)
      : [element];
  }

  function controlSignature(control) {
    return JSON.stringify([normalized(control.label), normalized(control.section),
      control.kind, Array.from(control.options || []).sort(), positionId(), control.repeat_context || '']);
  }

  function captureFromElement(element) {
    if (!(element instanceof Element)) return null;
    if (isCustomChoice(element) && isUsable(element)) return describeCustomControl(element, true);
    if (!(element instanceof HTMLInputElement
      || element instanceof HTMLTextAreaElement
      || element instanceof HTMLSelectElement) || !isUsable(element)) return null;
    if (element instanceof HTMLInputElement && element.type === 'radio') {
      return describeRadioGroup(element, radioMembers(element), true);
    }
    return describeControl(element, true);
  }

  function hasValue(value) {
    if (Array.isArray(value)) return value.length > 0;
    return value !== null && value !== undefined && value !== '';
  }

  function captureIdentity(capture) {
    return JSON.stringify([capture.site, normalized(capture.section),
      normalized(capture.label), capture.kind,
      Array.from(new Set(capture.options || [])).sort(), capture.position_id]);
  }

  function rememberFinalValue(event) {
    if (!event.isTrusted) return;
    const control = captureFromElement(event.target);
    if (!control || !hasValue(control.value)) return;
    const capture = {...control, site: location.origin, position_id: positionId(),
      captured_at: new Date().toISOString()};
    delete capture.control_id;
    captureQueue = captureQueue.then(async () => {
      const stored = await chrome.storage.local.get('answerCaptures');
      const captures = stored.answerCaptures || {};
      captures[captureIdentity(capture)] = capture;
      const newest = Object.entries(captures)
        .sort((left, right) => String(right[1].captured_at).localeCompare(String(left[1].captured_at)))
        .slice(0, 300);
      await chrome.storage.local.set({answerCaptures: Object.fromEntries(newest)});
    }).catch(() => {});
  }

  document.addEventListener('change', rememberFinalValue, true);
  document.addEventListener('blur', rememberFinalValue, true);

  function positionId() {
    const canonical = document.querySelector('link[rel="canonical"]');
    const value = canonical ? canonical.href : location.href;
    const parsed = new URL(value);
    // Some ATS hosts use one /apply path for every requisition. Canonical links
    // often drop the query, so read the actual page's explicit job ID first.
    for (const page of [new URL(location.href), parsed]) {
      for (const key of ['gh_jid', 'jobId', 'job_id', 'requisitionId', 'requisition_id']) {
        const id = page.searchParams.get(key);
        if (id && id.trim()) return JSON.stringify([page.pathname, key, id]);
      }
    }
    const last = parsed.pathname.split('/').filter(Boolean).pop() || '';
    const match = last.match(/_([A-Za-z0-9-]+)$/);
    return match ? match[1] : (parsed.pathname.replace(/\/+$/, '') || null);
  }

  function elementForId(id) {
    return document.querySelector(`[data-jobdisco-control-id="${CSS.escape(id)}"]`);
  }

  function setNativeValue(element, value) {
    const prototype = element instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(prototype, 'value').set;
    setter.call(element, String(value));
  }

  function dispatchChange(element) {
    element.dispatchEvent(new Event('input', {bubbles: true}));
    element.dispatchEvent(new Event('change', {bubbles: true}));
    element.dispatchEvent(new Event('blur', {bubbles: true}));
  }

  async function fillOne(match) {
    const element = elementForId(match.control_id);
    if (!element || match.answer === null || match.answer === undefined) return 'missing';
    if (!isUsable(element)) return 'unavailable';
    const currentControl = isCustomChoice(element) ? describeCustomControl(element, false)
      : element instanceof HTMLInputElement && element.type === 'radio'
      ? describeRadioGroup(element, radioMembers(element), false) : describeControl(element, false);
    if (!currentControl || scannedControls.get(match.control_id) !== controlSignature(currentControl)) {
      return 'unavailable';
    }
    if (match.status === 'requires_review' && !match.allow_review) return 'review';
    if (match.status === 'verify_options' && match.needs_review && !match.allow_review) return 'review';
    if (!['ready', 'requires_review', 'verify_options'].includes(match.status)) return 'unavailable';
    if (isCustomChoice(element)) return fillCustomChoice(element, match);
    if (element instanceof HTMLInputElement && element.type === 'radio') {
      const radios = radioMembers(element);
      if (radios.some(item => item.checked)) return 'occupied';
      const targets = radios.filter(item => isUsable(item) && radioLabel(item) === String(match.answer));
      if (targets.length !== 1) return 'option_mismatch';
      const target = targets[0];
      if (!target.checked) target.click();
      return 'filled';
    }
    if (element instanceof HTMLSelectElement) {
      const current = Array.from(element.selectedOptions)
        .filter(usableOption);
      if (current.length) return 'occupied';
      const answers = Array.isArray(match.answer) ? match.answer : [match.answer];
      if (!answers.length || (!element.multiple && answers.length !== 1)
        || new Set(answers).size !== answers.length) return 'option_mismatch';
      const realOptions = Array.from(element.options).filter(usableOption);
      const selected = answers.map(answer => realOptions.filter(option => cleanText(option.textContent) === answer));
      // Verify the complete, unambiguous selection before changing any value.
      if (selected.some(options => options.length !== 1)) return 'option_mismatch';
      const targets = new Set(selected.map(options => options[0]));
      Array.from(element.options).forEach(option => {option.selected = targets.has(option);});
      dispatchChange(element);
      return 'filled';
    }
    if (element instanceof HTMLInputElement && element.type === 'checkbox') {
      if (element.checked !== Boolean(match.answer)) element.click();
      return 'filled';
    }
    if (element.value) return 'occupied';
    setNativeValue(element, match.answer);
    dispatchChange(element);
    return 'filled';
  }

  chrome.runtime.onMessage.addListener((message, _sender, respond) => {
    try {
      if (message.action === 'scan') {
        captureQueue.then(() => respond(scan(Boolean(message.includeValues))))
          .catch(error => respond({error: error.message}));
        return true;
      } else if (message.action === 'fill') {
        (async () => {
          const outcomes = [];
          // Dynamic dropdowns share transient DOM. Verify and fill one at a time.
          for (const result of message.results) outcomes.push(await fillOne({...result, allow_review: message.allowReview}));
          respond({filled: outcomes.filter(value => value === 'filled').length,
            occupied: outcomes.filter(value => value === 'occupied').length,
            unresolved: outcomes.filter(value => !['filled', 'occupied'].includes(value)).length});
        })().catch(error => respond({error: error.message}));
        return true;
      }
    } catch (error) {
      respond({error: error.message});
    }
    return false;
  });
})();
