(() => {
  'use strict';

  const SCRIPT_VERSION = 5;
  if (globalThis.__jobdiscoAutofillInstalled === SCRIPT_VERSION) return;
  globalThis.__jobdiscoAutofillInstalled = SCRIPT_VERSION;

  const UNSAFE_INPUT_TYPES = new Set(['button', 'file', 'hidden', 'image', 'password',
    'reset', 'search', 'submit', 'checkbox']);
  const BLOCKED_LABEL_WORDS = ['password', 'passcode', 'security code',
    'social security', 'ssn', 'passport number', 'driver license', 'signature',
    'i certify', 'i agree', 'acknowledge', 'consent', 'terms and conditions',
    'privacy policy', 'captcha', 'verification code'];
  let nextControlId = 1;
  let captureQueue = Promise.resolve();

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
    for (let node = element.parentElement, depth = 0; node && depth < 5; node = node.parentElement, depth += 1) {
      const candidate = node.querySelector(':scope > label, :scope > legend, :scope > [data-automation-id="formLabel"]');
      if (candidate && cleanText(candidate.textContent)) return cleanText(candidate.textContent);
    }
    return cleanText(element.getAttribute('placeholder'));
  }

  function sectionLabel(element) {
    const fieldset = element.closest('fieldset');
    if (fieldset) {
      const headings = Array.from(fieldset.querySelectorAll('h1, h2, h3, h4'))
        .filter(heading => heading.compareDocumentPosition(element)
          & Node.DOCUMENT_POSITION_FOLLOWING);
      if (headings.length) return cleanText(headings[headings.length - 1].textContent);
      const legend = fieldset.querySelector(':scope > legend');
      if (legend && cleanText(legend.textContent)) return cleanText(legend.textContent);
    }
    for (let node = element.parentElement, depth = 0; node && depth < 8; node = node.parentElement, depth += 1) {
      const heading = node.querySelector(':scope > h1, :scope > h2, :scope > h3, :scope > h4, :scope > [data-automation-id="sectionTitle"]');
      if (heading && cleanText(heading.textContent)) return cleanText(heading.textContent);
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
    if (element.disabled || (element.readOnly && element.type !== 'radio')
      || element.getAttribute('aria-disabled') === 'true') return false;
    if (element instanceof HTMLInputElement && UNSAFE_INPUT_TYPES.has(element.type)) return false;
    if (element.getAttribute('role') === 'combobox'
      && !(element.getAttribute('aria-controls')
        && element.closest('[class*="select-module_select-wrapper"]'))) return false;
    const style = getComputedStyle(element);
    return style.display !== 'none' && style.visibility !== 'hidden';
  }

  function radioLabel(element) {
    const explicit = element.id
      && document.querySelector(`label[for="${CSS.escape(element.id)}"]`);
    return cleanText(explicit && explicit.textContent) || nearbyLabel(element)
      || cleanText(element.value);
  }

  function blockedLabel(label) {
    const normalized = label.toLocaleLowerCase();
    return BLOCKED_LABEL_WORDS.some(word => normalized.includes(word));
  }

  function describeRadioGroup(first, members, includeValues) {
    const fieldset = first.closest('fieldset');
    const legend = fieldset && fieldset.querySelector(':scope > legend');
    const group = first.closest('[role="radiogroup"]');
    const groupLabel = group && (cleanText(group.getAttribute('aria-label'))
      || textFromIds(group.getAttribute('aria-labelledby')));
    const aria = cleanText(first.getAttribute('aria-label'));
    const option = radioLabel(first);
    const composite = aria.startsWith(`${option}, `) ? aria.slice(option.length + 2) : '';
    const label = groupLabel || composite || cleanText(legend && legend.textContent)
      || nearbyLabel(first);
    if (!label || blockedLabel(label)) return null;
    const selected = members.find(item => item.checked);
    return {
      control_id: controlId(first),
      label,
      section: sectionLabel(first),
      kind: 'radio',
      options: members.map(radioLabel).filter(Boolean),
      ...(includeValues ? {value: selected ? radioLabel(selected) : ''} : {})
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
      const realOptions = Array.from(element.options).filter(option => !option.disabled && option.value !== '');
      options = realOptions.map(option => cleanText(option.textContent)).filter(Boolean);
      value = element.multiple
        ? Array.from(element.selectedOptions).map(option => cleanText(option.textContent))
        : (element.selectedOptions[0] && !element.selectedOptions[0].disabled
          && element.selectedOptions[0].value !== ''
          ? cleanText(element.selectedOptions[0].textContent) : '');
    } else if (element.getAttribute('role') === 'combobox') {
      kind = 'combobox';
      value = element.getAttribute('aria-expanded') === 'true' ? '' : element.value;
    } else if (element instanceof HTMLInputElement && element.type === 'number') {
      kind = 'number';
      value = element.value === '' ? '' : Number(element.value);
    } else if (element instanceof HTMLInputElement && element.type === 'checkbox') {
      kind = 'checkbox';
      value = element.checked;
    }
    return {
      control_id: controlId(element), label, section: sectionLabel(element), kind, options,
      ...(includeValues ? {value} : {})
    };
  }

  function scan(includeValues = false) {
    const controls = [];
    const radios = new Map();
    document.querySelectorAll('input, textarea, select').forEach(element => {
      if (!isUsable(element)) return;
      if (element instanceof HTMLInputElement && element.type === 'radio') {
        const key = element.name || controlId(element.closest('fieldset') || element);
        if (!radios.has(key)) radios.set(key, []);
        radios.get(key).push(element);
        return;
      }
      const described = describeControl(element, includeValues);
      if (described) controls.push(described);
    });
    radios.forEach(members => {
      const described = describeRadioGroup(members[0], members, includeValues);
      if (described) controls.push(described);
    });
    return {site: location.href, position_id: positionId(), controls};
  }

  function normalized(value) {
    return String(value || '').normalize('NFKC').toLocaleLowerCase()
      .replace(/\s+/g, ' ').trim().replace(/[ *:]+$/, '').trim();
  }

  function radioMembers(element) {
    return element.name
      ? Array.from(document.querySelectorAll(`input[type="radio"][name="${CSS.escape(element.name)}"]`))
      : [element];
  }

  function captureFromElement(element) {
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

  function rememberControl(element) {
    const control = captureFromElement(element);
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

  function rememberFinalValue(event) {
    if (event.isTrusted) rememberControl(event.target);
  }

  document.addEventListener('change', rememberFinalValue, true);
  document.addEventListener('blur', rememberFinalValue, true);
  document.addEventListener('click', event => {
    if (!event.isTrusted || !(event.target instanceof Element)) return;
    const option = event.target.closest('[role="option"]');
    const list = option && option.closest('[role="listbox"]');
    if (!list || !list.id) return;
    const input = document.querySelector(`input[role="combobox"][aria-controls="${CSS.escape(list.id)}"]`);
    if (input && input.closest('[class*="select-module_select-wrapper"]')) {
      setTimeout(() => rememberControl(input), 0);
    }
  }, true);

  function positionId() {
    const current = new URL(location.href);
    const requisition = current.searchParams.get('pid');
    if (requisition && /^[A-Za-z0-9-]+$/.test(requisition)) return requisition;
    const canonical = document.querySelector('link[rel="canonical"]');
    const value = canonical ? canonical.href : location.href;
    const parsed = new URL(value);
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
    if (match.status === 'requires_review' && !match.allow_review) return 'review';
    if (match.status !== 'ready' && match.status !== 'requires_review') return 'unavailable';
    if (element instanceof HTMLInputElement && element.type === 'radio') {
      const radios = radioMembers(element);
      if (radios.some(item => item.checked)) return 'occupied';
      const target = radios.find(item => radioLabel(item) === String(match.answer));
      if (!target) return 'option_mismatch';
      if (!target.checked) target.click();
      return 'filled';
    }
    if (element.getAttribute('role') === 'combobox') {
      if (element.value) return 'occupied';
      const listId = element.getAttribute('aria-controls');
      if (!listId || !element.closest('[class*="select-module_select-wrapper"]')) {
        return 'unavailable';
      }
      element.click();
      await new Promise(resolve => setTimeout(resolve, 0));
      const list = document.getElementById(listId);
      const options = list && Array.from(list.querySelectorAll('[role="option"]'))
        .filter(option => cleanText(option.textContent) === String(match.answer));
      if (!options || options.length !== 1) {
        element.blur();
        return 'option_mismatch';
      }
      options[0].click();
      await new Promise(resolve => setTimeout(resolve, 0));
      return cleanText(element.value) === String(match.answer) ? 'filled' : 'option_mismatch';
    }
    if (element instanceof HTMLSelectElement) {
      const current = Array.from(element.selectedOptions)
        .filter(option => !option.disabled && option.value !== '');
      if (current.length) return 'occupied';
      const answers = Array.isArray(match.answer) ? match.answer : [match.answer];
      let selected = 0;
      Array.from(element.options).forEach(option => {
        const choose = answers.includes(cleanText(option.textContent));
        option.selected = choose;
        if (choose) selected += 1;
      });
      if (selected !== answers.length) return 'option_mismatch';
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
      if (message.action === 'scan_v5') {
        captureQueue.then(() => respond(scan(Boolean(message.includeValues))))
          .catch(error => respond({error: error.message}));
        return true;
      } else if (message.action === 'fill_v5') {
        (async () => {
          const outcomes = [];
          for (const result of message.results) {
            outcomes.push(await fillOne({...result, allow_review: message.allowReview}));
          }
          return outcomes;
        })().then(outcomes =>
          respond({filled: outcomes.filter(value => value === 'filled').length,
            occupied: outcomes.filter(value => value === 'occupied').length}))
          .catch(error => respond({error: error.message}));
        return true;
      }
    } catch (error) {
      respond({error: error.message});
    }
    return false;
  });
})();
