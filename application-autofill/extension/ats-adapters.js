(function (root) {
  'use strict';
  const clean = value => String(value || '').replace(/\s+/g, ' ').replace(/\s*[*:]\s*$/, '').trim();
  const hostMatches = (host, domain) => host === domain || host.endsWith('.' + domain);
  const adapters = [
    {id: 'workday', domains: ['myworkdayjobs.com', 'myworkday.com', 'myworkdaysite.com'],
      wrapper: '[data-automation-id^="formField-"]',
      label: 'label, [data-automation-id="formLabel"]',
      section: '[data-automation-id="sectionTitle"], h2, h3, h4'},
    {id: 'greenhouse', domains: ['greenhouse.io'], wrapper: '.field, .application--field',
      label: 'label, .field-label', section: 'legend, h2, h3, h4'},
    {id: 'lever', domains: ['lever.co'], wrapper: '.application-question, .application-field',
      label: '.application-label, label', section: 'legend, h2, h3, h4'}
  ];

  function detect(url) {
    const host = new URL(url).hostname.toLowerCase();
    return adapters.find(adapter => adapter.domains.some(domain => hostMatches(host, domain)))
      || {id: 'generic', wrapper: null};
  }

  function metadata(element, url) {
    const adapter = detect(url);
    const wrapper = adapter.wrapper && element.closest(adapter.wrapper);
    const label = wrapper && wrapper.querySelector(adapter.label);
    // Metadata describes the DOM; it never authorizes an answer by itself.
    return {ats: adapter.id, label: clean(label?.textContent),
      field_hint: wrapper?.getAttribute('data-automation-id') || element.name || element.id || '',
      input_type: element.type || element.tagName.toLowerCase(),
      autocomplete: element.getAttribute('autocomplete') || '',
      required: element.required || element.getAttribute('aria-required') === 'true'};
  }

  const api = {adapters, detect, metadata};
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.JobdiscoATS = api;
})(globalThis);
