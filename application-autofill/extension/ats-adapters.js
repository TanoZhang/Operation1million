(function (root) {
  'use strict';
  const clean = value => String(value || '').replace(/\s+/g, ' ').replace(/\s*[*:]\s*$/, '').trim();
  const hostMatches = (host, domain) => host === domain || host.endsWith('.' + domain);
  // `fields` maps a provider's own field identifier to the canonical field it
  // always means on that provider: the applicant's legal name, email, phone and
  // address. Exact identifiers only -- "name--legalName--firstNameLocal" is a
  // different field from "name--legalName--firstName". Sources, 2026-10-02:
  // Workday's form-kit paths and automation ids as rendered (Job App Filler,
  // application-autofiller, Workday_Automater), Greenhouse's documented
  // application fields, Lever's postings API apply fields, Ashby's documented
  // `_systemfield_*` paths. See docs/autofill-framework.md.
  const adapters = [
    {id: 'workday', domains: ['myworkdayjobs.com', 'myworkday.com', 'myworkdaysite.com'],
      // Two generations: `formField-<id>` wrappers, and form-kit wrappers whose
      // data-fkit-id is the field's path.
      wrapper: '[data-automation-id^="formField-"], [data-fkit-id]',
      label: 'label, [data-automation-id="formLabel"]',
      section: '[data-automation-id="sectionTitle"], h2, h3, h4',
      fields: {
        'name--legalName--firstName': 'name.first', 'legalNameSection_firstName': 'name.first',
        'name--legalName--lastName': 'name.last', 'legalNameSection_lastName': 'name.last',
        'email': 'contact.email', 'emailAddress': 'contact.email',
        'phoneNumber--phoneNumber': 'contact.phone', 'phone-number': 'contact.phone',
        'address--addressLine1': 'address.street', 'addressSection_addressLine1': 'address.street',
        'address--city': 'address.city', 'addressSection_city': 'address.city',
        'address--postalCode': 'address.postal_code', 'addressSection_postalCode': 'address.postal_code'}},
    {id: 'greenhouse', domains: ['greenhouse.io'], wrapper: '.field, .application--field',
      label: 'label, .field-label', section: 'legend, h2, h3, h4',
      fields: {
        'first_name': 'name.first', 'job_application[first_name]': 'name.first',
        'last_name': 'name.last', 'job_application[last_name]': 'name.last',
        'email': 'contact.email', 'job_application[email]': 'contact.email',
        'phone': 'contact.phone', 'job_application[phone]': 'contact.phone'}},
    {id: 'lever', domains: ['lever.co'], wrapper: '.application-question, .application-field',
      label: '.application-label, label', section: 'legend, h2, h3, h4',
      // Lever asks for one full name, not its halves.
      fields: {'name': 'name.legal_full', 'email': 'contact.email', 'phone': 'contact.phone'}},
    {id: 'ashby', domains: ['ashbyhq.com'], wrapper: '[class*="_fieldEntry"]',
      label: 'label', section: 'h2, h3, h4',
      // So does Ashby: `_systemfield_name` is one box titled "Name".
      fields: {'_systemfield_name': 'name.legal_full', '_systemfield_email': 'contact.email',
        '_systemfield_phone': 'contact.phone'}}
  ];

  // HTML's autocomplete field names: the page itself saying what a field is.
  // Only for the person filling the form in -- a section-, shipping or billing
  // token names an address group, and is not taken. "name" is the full name.
  const AUTOCOMPLETE = {
    'given-name': 'name.first', 'family-name': 'name.last', 'name': 'name.legal_full',
    'email': 'contact.email', 'tel': 'contact.phone', 'tel-national': 'contact.phone',
    'street-address': 'address.street', 'address-line1': 'address.street',
    'address-level2': 'address.city', 'address-level1': 'address.state',
    'postal-code': 'address.postal_code', 'country-name': 'address.country'};
  const CONTACT_KIND = new Set(['home', 'work', 'mobile']);

  function detect(url) {
    const host = new URL(url).hostname.toLowerCase();
    return adapters.find(adapter => adapter.domains.some(domain => hostMatches(host, domain)))
      || {id: 'generic', wrapper: null};
  }

  function autocompleteField(element) {
    const tokens = (element.getAttribute('autocomplete') || '').trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (!tokens.length || tokens.length > 2) return null;
    const name = tokens[tokens.length - 1];
    // "work email", "mobile tel": a kind of contact, still the applicant's.
    if (tokens.length === 2 && !(CONTACT_KIND.has(tokens[0]) && /^(email|tel)/.test(name))) return null;
    return AUTOCOMPLETE[name] || null;
  }

  // A wrapper speaks for a field only when it holds that one control: a phone
  // wrapper around a country code and a number names neither of them.
  function soleControl(wrapper, element) {
    if (!wrapper) return false;
    const controls = Array.from(wrapper.querySelectorAll('input, select, textarea'))
      .filter(control => control.type !== 'hidden');
    return controls.length === 1 && controls[0] === element;
  }

  function providerField(adapter, element, wrapper) {
    if (!adapter.fields) return null;
    const own = [element.id, element.getAttribute('name'), element.getAttribute('data-automation-id')];
    const wrapped = soleControl(wrapper, element)
      ? [wrapper.getAttribute('data-fkit-id'),
         (wrapper.getAttribute('data-automation-id') || '').replace(/^formField-/, '')] : [];
    const keys = new Set([...own, ...wrapped].filter(Boolean)
      .filter(id => Object.hasOwn(adapter.fields, id)).map(id => adapter.fields[id]));
    return keys.size === 1 ? [...keys][0] : null;
  }

  function metadata(element, url) {
    const adapter = detect(url);
    const wrapper = adapter.wrapper && element.closest(adapter.wrapper);
    const label = wrapper && wrapper.querySelector(adapter.label);
    // The field a provider identifier or an autocomplete token declares. It is
    // one more exact alias for the answer engine, not an answer: a label that
    // names a different field makes the question ambiguous, and nothing is filled.
    const provider = providerField(adapter, element, wrapper);
    const declared = provider || autocompleteField(element);
    return {ats: adapter.id, label: clean(label?.textContent),
      field_hint: wrapper?.getAttribute('data-automation-id') || element.name || element.id || '',
      input_type: element.type || element.tagName.toLowerCase(),
      autocomplete: element.getAttribute('autocomplete') || '',
      required: element.required || element.getAttribute('aria-required') === 'true',
      ...(declared ? {declared_field: declared, declared_by: provider ? adapter.id : 'autocomplete'} : {})};
  }

  const api = {adapters, detect, metadata, autocompleteField};
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.JobdiscoATS = api;
})(globalThis);
