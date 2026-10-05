let state = {pending: [], backlog: [], applied: [], skipped: [], labels: []};
// Rows the list draws at a time; Show more draws as many again.
const PAGE = 75;
let tab = 'pending', selected = null, busy = false, detailVersion = 0, visibleLimit = PAGE;
// The sort is remembered in this browser; a private window or blocked storage
// simply starts from the default.
const SORT_KEY = 'review-sort';
let sortMode = 'fit-desc';
try { sortMode = localStorage.getItem(SORT_KEY) || sortMode; } catch { /* no storage */ }
const checkedJobs = new Set();
let downloading = false;
// Asked for on 2026-10-04: a list of 2,000 is submitted in batches of 200-300.
// A batch is a slice of the list on screen, in its order; picking one selects
// exactly it, and the download is named after it.
const BATCH = 250;
let batchName = '';
function batchOptions(total) {
  const select = $('#batch');
  const count = Math.ceil(total / BATCH);
  const chosen = select.value;
  const options = ['<option value="">of 250&hellip;</option>'];
  for (let i = 0; i < count; i++) {
    const first = i * BATCH + 1, last = Math.min(total, (i + 1) * BATCH);
    options.push(`<option value="${i}">${first}&ndash;${last}</option>`);
  }
  select.innerHTML = options.join('');
  select.value = chosen !== '' && Number(chosen) < count ? chosen : '';
  select.disabled = total === 0;
}
function updateSelection() {
  const valid = new Set(allGroups().map(group => group.id));
  for (const id of checkedJobs) if (!valid.has(id)) checkedJobs.delete(id);
  const matches = filtered();
  batchOptions(matches.length);
  if ($('#batch').value !== '') {
    const index = Number($('#batch').value);
    const members = matches.slice(index * BATCH, (index + 1) * BATCH);
    // Still the batch only while the selection is exactly it.
    if (members.length !== checkedJobs.size || !members.every(group => checkedJobs.has(group.id))) {
      $('#batch').value = ''; batchName = '';
    }
  }
  const count = matches.filter(group => checkedJobs.has(group.id)).length;
  $('#select-matching').checked = matches.length > 0 && count === matches.length;
  $('#select-matching').indeterminate = count > 0 && count < matches.length;
  $('#download-selected').textContent = `Download selected Excel (${checkedJobs.size})`;
  $('#download-selected').disabled = downloading || checkedJobs.size === 0;
  document.querySelectorAll('.section-check').forEach(check => {
    const members = matches.filter(group => sectionOf.get(group.id) === check.dataset.section);
    const selectedCount = members.filter(group => checkedJobs.has(group.id)).length;
    check.checked = members.length > 0 && selectedCount === members.length;
    check.indeterminate = selectedCount > 0 && selectedCount < members.length;
  });
}
// Two refreshes can be in flight -- a click on Refresh, a decision saving, a
// slow first request -- and they do not answer in the order they were asked.
// The later answer is the current one; an earlier one arriving after it used
// to put the queue back to a state the user had already moved on from.
let queueVersion = 0;
let queueRetry;
// Nothing is known until the first queue arrives. The state above is a
// placeholder, and rendering it -- which a tab click or a keystroke in the
// search box did while a cold build was still running -- drew an empty queue
// and "All done for today" over a queue holding hundreds of postings.
let loaded = false;
// The group the skip dialog was opened for. A refresh landing while the dialog
// is open can change which group is selected, and the reason typed for one
// posting was then filed against another.
let skipTarget = null;
// The description last fetched, for the group it belongs to. Re-rendering the
// list re-renders the detail -- a keystroke in the search box, a Show more,
// picking the same posting again -- and each of those asked the server for a
// description it had just been given. Cleared by `refresh`, so it never
// outlives the queue it was read against.
let described = {key: null, text: null};
// A keystroke should not cost a full render of the list. Typing eight
// characters rendered eight times, each one laying out up to seventy-five
// rows, and only the last of them was ever seen.
let searchTimer = null;
// The band names come from the server so `ranking.LABELS` stays the only place
// they are written down; a queue that predates them simply shows no chip.
const band = group => Number.isInteger(group.bucket) ? group.bucket : 4;
const bandLabel = group => state.labels?.[band(group)] ?? '';
const bandChip = group => bandLabel(group)
  ? `<span class="band band-${band(group)}">${escapeText(bandLabel(group))}</span>` : '';
// Admitted on what the posting says rather than on what it is called, so it is
// worth a second look rather than a second thought.
const flagChip = group => group.flagged
  ? '<span class="flagged" title="The title alone did not qualify this posting; its description carried the vocabulary.">Adjacent</span>' : '';
// Not a warning: an internship already served is a qualification. It is shown
// because the word appears in a posting that is not itself an internship, and
// a reader who has one should see that the posting asks for it.
const internChip = group => group.internship_experience
  ? '<span class="flagged" title="This posting asks for internship experience someone has already done.">Internship experience</span>' : '';
const appliedDate = group => group.at
  ? `Applied ${asDate(group.at).toLocaleDateString(undefined, {year:'numeric', month:'short', day:'numeric'})}`
  : 'Applied date unavailable';
const topBadge = group => tab === 'applied'
  ? `<span class="applied-date">${escapeText(appliedDate(group))}</span>` : chips(group);
// All three, the same in the list and in the detail.
const chips = group => `${bandChip(group)}${flagChip(group)}${internChip(group)}${group.jobs.some(thirdParty) ? '<span class="third-party-warning">Third-party site</span>' : ''}`;
const $ = selector => document.querySelector(selector);
const escapeText = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const safeLink = value => { try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? escapeText(url.href) : '#'; } catch { return '#'; } };
// A link that opens in a new tab, which gets no hold on this page.
const newTab = (href, text) => `<a href="${safeLink(href)}" target="_blank" rel="noopener noreferrer">${text} &#8599;</a>`;
// A bare `2026-09-20` is a calendar day, and `new Date` reads it as UTC
// midnight -- which is the day before, everywhere west of Greenwich. Every
// date this page shows was arriving a day early in Los Angeles.
const asDate = value => {
  const bare = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value ?? ''));
  return bare ? new Date(+bare[1], +bare[2] - 1, +bare[3]) : new Date(value);
};
const date = value => value ? asDate(value).toLocaleDateString(undefined, {month:'short', day:'numeric'}) : 'Unknown';
const clock = () => new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
const listings = count => `${count} listing${count === 1 ? '' : 's'}`;
const postedToday = job => job.posted_at && asDate(job.posted_at).toDateString() === new Date().toDateString();
// "30+ Days Ago" is a bound, and says so rather than claiming a day (#277).
const postedLabel = job => !job.posted_at
  ? (job.posted_before ? `Posted on or before ${date(job.posted_before)}` : 'Posting date unavailable')
  : postedToday(job) ? 'Posted today' : `Posted ${date(job.posted_at)}`;
// A paid listing links to wherever Google Jobs found the posting, which is
// usually a third-party site. Say so, and offer the employer's own copy: a
// search of the employer's site for the exact title, since the provider gives
// no direct link to it.
const companySearch = (job, title) => {
  try {
    const host = new URL(job.employer_site).hostname.replace(/^www\./, '');
    return 'https://www.google.com/search?q=' + encodeURIComponent(`site:${host} "${title}"`);
  } catch { return null; }
};
// A third-party listing can be given the company's own link once it is found
// (asked for on 2026-10-02); it is kept beside the ledger and leads the row.
const thirdParty = job => job.third_party_site === true;
const listingRow = (job, title) => {
  const via = job.official_link ? 'company link added by you'
    : job.publisher ? `via ${job.publisher}${thirdParty(job) ? ' (third-party site)' : ''}` : job.provider_key;
  const search = job.employer_site && !job.official_link ? companySearch(job, title) : null;
  const url = escapeText(job.url);
  const links = job.official_link
    ? newTab(job.official_link, 'Open company listing')
      + newTab(job.url, 'Third-party listing')
      + `<button type="button" class="link-button" data-company-link="${url}">Change</button>`
      + `<button type="button" class="link-button" data-company-link="${url}" data-remove="1">Remove</button>`
    : (search ? newTab(search, 'Find on company site') : '')
      + newTab(job.url, 'Open listing')
      + (thirdParty(job) ? `<button type="button" class="link-button" data-company-link="${url}">Use company link</button>` : '');
  return `<div class="location-row"><span>${escapeText(job.location || 'Location not listed')}<br><span class="muted">${escapeText(via)}</span></span><div class="listing-links">${links}</div></div>`;
};
const allGroups = () => [...state.pending, ...state.backlog, ...state.applied, ...state.skipped];
async function setCompanyLink(url, remove) {
  const current = allGroups().flatMap(group => group.jobs).find(job => job.url === url)?.official_link || '';
  const link = remove ? '' : prompt("Paste the company's own link for this posting", current);
  if (link === null) return;
  try {
    const written = await post('/api/link', {url, link});
    allGroups().forEach(group => group.jobs.forEach(job => {
      if (job.url !== url) return;
      if (written.link) job.official_link = written.link; else delete job.official_link;
    }));
    error('');
    render();
  } catch (err) { error(err.message); }
}
function error(message) { $('#error').textContent = message; $('#error').hidden = !message; }
async function api(path, options) {
  const controller = new AbortController();
  const timer = !options?.method ? setTimeout(() => controller.abort(), 25000) : null;
  try {
    const response = await fetch(path, {...options, ...(!options?.method ? {signal: controller.signal} : {})});
    const body = await response.json();
    if (!response.ok) {
      const failure = new Error(body.error || 'Request failed');
      failure.status = response.status; throw failure;
    }
    return body;
  } catch (err) {
    if (err.name === 'AbortError') throw new Error('Queue connection timed out. Check the SSH tunnel; retrying shortly');
    throw err;
  } finally { clearTimeout(timer); }
}
// A write, with the token that shows this page was served by this server.
const post = (path, body) => api(path, {method:'POST', headers:{'Content-Type':'application/json', 'X-Review-Token':state.token}, body:JSON.stringify(body)});
async function refresh() {
  const version = ++queueVersion;
  clearTimeout(queueRetry);
  try {
    const next = await api('/api/queue');
    if (version !== queueVersion) return;
    described = {key: null, text: null};
    state = next; loaded = true; error(''); render();
  } catch (err) {
    if (version !== queueVersion) return;
    if (err.status === 503) {
      error('');
      if (!loaded) $('#list').innerHTML = '<div class="empty">Preparing the job queue. This page will update automatically.</div>';
    } else {
      error(err.message);
      if (!loaded) $('#list').innerHTML = `<div class="empty">${escapeText(err.message)}. Retrying shortly; you can also use Refresh.</div>`;
    }
    queueRetry = setTimeout(refresh, 10000);
  }
}
// When a group was published -- its newest listing's posting date, or where
// no listing states one, the newest day we first saw one, as the server ranks
// it. Null when neither is known.
const groupTime = group => {
  const read = field => (group.jobs || []).map(job => job[field]).filter(Boolean)
    .map(value => asDate(value).getTime()).filter(Number.isFinite);
  // A stated "30+ days" bound before the day we first saw it (#277).
  const stamps = [read('posted_at'), read('posted_before'), read('first_seen')].find(found => found.length) || [];
  return stamps.length ? Math.max(...stamps) : null;
};
const score = group => typeof group.confidence === 'number' && Number.isFinite(group.confidence)
  ? group.confidence : null;
// Each sort is a list of (key, direction) read in turn; asked for on
// 2026-10-01: by date either way, and by fit with the date breaking ties.
const SORTS = {
  'fit-desc': [['fit', -1], ['time', -1]],
  'fit-desc-oldest': [['fit', -1], ['time', 1]],
  'fit-asc': [['fit', 1], ['time', -1]],
  'newest': [['time', -1]],
  'oldest': [['time', 1]],
};
// An unknown value goes last in either direction.
const compareKnown = (left, right, direction) => left === null ? (right === null ? 0 : 1)
  : right === null ? -1 : direction * (left - right);
// The sort the menu asks for, over one section. Equal keys keep server order,
// and state is never mutated.
function sorted(groups) {
  const keys = SORTS[sortMode];
  if (!keys) return groups;
  return groups.map(group => ({group, fit: score(group), time: groupTime(group)}))
    .sort((a, b) => {
      for (const [key, direction] of keys) {
        const order = compareKnown(a[key], b[key], direction);
        if (order) return order;
      }
      return 0;
    })
    .map(item => item.group);
}
// Which section each listed group was placed in, for the dividers.
let sectionOf = new Map();
const SECTION_NAMES = {recent: 'New in the last 72 hours', backlog: 'Backlog',
                       less: 'Low relevance'};
// Asked for on 2026-09-22: one list to work down -- what is new, then the
// backlog. Since 2026-09-24 what is barely related, new or old, is on a tab of
// its own and nowhere else, and Remaining does not count it. The server says
// which groups those are (`less_related`); the order inside each section is
// the menu's. Since 2026-09-25 To review is two tabs: a title naming an
// intern, a new grad or the early career (the server's `early_career`) on
// Early career, and everything else -- "Master's plus 2 years" -- on To review.
// Since 2026-09-26 the Backlog tab leaves early career postings to their tab.
const related = group => !group.less_related;
const early = group => related(group) && group.early_career;
const experienced = group => related(group) && !group.early_career;
function filtered() {
  const text = $('#search').value.trim().toLowerCase();
  const match = group => `${group.company} ${group.title}`.toLowerCase().includes(text);
  let sections;
  if (tab === 'pending') {
    sections = [['recent', state.pending.filter(experienced)], ['backlog', state.backlog.filter(experienced)]];
  } else if (tab === 'early') {
    sections = [['recent', state.pending.filter(early)], ['backlog', state.backlog.filter(early)]];
  } else if (tab === 'backlog') {
    sections = [['backlog', state.backlog.filter(experienced)]];
  } else if (tab === 'less') {
    sections = [['less', [...state.pending, ...state.backlog].filter(group => group.less_related)]];
  } else {
    sections = [[null, state[tab]]];
  }
  sectionOf = new Map();
  return sections.flatMap(([name, groups]) => sorted(groups.filter(match)).map(group => {
    sectionOf.set(group.id, name);
    return group;
  }));
}
// Bands 0 and 1 are both early-career openings and read as one number here,
// even though a core one still leads an adjacent one in the list itself.
function bandSummary(groups) {
  const counts = [0, 0, 0, 0, 0];
  groups.forEach(group => counts[band(group)]++);
  const parts = [['intern / new grad', counts[0] + counts[1]], ['core VLSI', counts[2]],
                 ['related hardware', counts[3]], ['other', counts[4]]];
  const text = parts.filter(([, total]) => total).map(([name, total]) => `${total} ${name}`).join(' · ');
  return text ? ' · ' + text : '';
}
function render() {
  if (!loaded) return;
  const open = [...state.pending, ...state.backlog].filter(related);
  $('#remaining').textContent = open.length;
  $('#applied').textContent = state.applied.length;
  $('#skipped').textContent = state.skipped.length;
  $('#pending-count').textContent = open.filter(experienced).length;
  $('#early-count').textContent = open.filter(early).length;
  $('#backlog-count').textContent = state.backlog.filter(experienced).length;
  $('#less-count').textContent = state.pending.length + state.backlog.length - open.length;
  const groups = filtered();
  const appliedMode = tab === 'applied';
  $('#manual-form button[type=submit]:not(#manual-applied)').textContent = appliedMode ? 'Add to Applied' : 'Add job and score';
  $('#manual-applied').hidden = appliedMode;
  updateSelection();
  if (!groups.some(group => group.id === selected)) selected = groups[0]?.id ?? null;
  $('#count').textContent = `${groups.length} positions` + bandSummary(groups);
  $('#list').replaceChildren();
  if (!groups.length) {
    $('#list').innerHTML = '<div class="empty">No matching positions</div>';
  }
  groups.slice(0, visibleLimit).forEach((group, index) => {
    const section = sectionOf.get(group.id);
    if (section && section !== sectionOf.get(groups[index - 1]?.id)) {
      const divider = document.createElement('div');
      divider.className = 'list-divider';
      const members = groups.filter(item => sectionOf.get(item.id) === section);
      const label = document.createElement('label');
      const check = document.createElement('input');
      check.type = 'checkbox'; check.className = 'section-check'; check.dataset.section = section;
      check.setAttribute('aria-label', `Select all ${SECTION_NAMES[section]}`);
      const count = members.filter(item => checkedJobs.has(item.id)).length;
      check.checked = count === members.length; check.indeterminate = count > 0 && count < members.length;
      check.onchange = () => {
        for (const member of members) {
          if (check.checked) checkedJobs.add(member.id); else checkedJobs.delete(member.id);
        }
        render();
      };
      label.append(check, ` ${SECTION_NAMES[section]} · ${members.length}`);
      divider.append(label);
      $('#list').append(divider);
    }
    const button = document.createElement('button');
    button.className = 'job' + (group.id === selected ? ' selected' : '');
    button.setAttribute('aria-pressed', group.id === selected);
    const locations = [...new Set(group.jobs.map(job => job.location).filter(Boolean))];
    button.innerHTML = `<div>${topBadge(group)}</div><div class="company">${escapeText(group.company)}</div><div class="job-title">${escapeText(group.title)}</div><span class="score">${Math.round(group.confidence)}</span><div class="job-meta">${escapeText(locations.length > 1 ? `${locations.length} locations` : locations[0] || 'Location not listed')} &middot; ${listings(group.jobs.length)}</div>`;
    if (group.jobs.some(postedToday)) {
      const mark = document.createElement('span');
      mark.className = 'posted-today';
      mark.textContent = 'Posted today';
      button.querySelector('.job-meta').append(' \u00b7 ', mark);
    }
    button.onclick = () => { selected = group.id; render(); };
    const row = document.createElement('div');
    row.className = 'job-row';
    const check = document.createElement('input');
    check.type = 'checkbox'; check.className = 'job-check';
    check.checked = checkedJobs.has(group.id);
    check.setAttribute('aria-label', `Select ${group.company}: ${group.title}`);
    check.dataset.groupId = group.id;
    check.onchange = () => {
      if (check.checked) checkedJobs.add(group.id); else checkedJobs.delete(group.id);
      updateSelection();
    };
    row.append(check, button);
    $('#list').append(row);
  });
  if (groups.length > visibleLimit) {
    const more = document.createElement('button');
    more.textContent = 'Show more';
    more.className = 'load-more';
    more.onclick = () => { visibleLimit += PAGE; render(); };
    $('#list').append(more);
  }
  renderDetail(groups.find(group => group.id === selected));
}
async function renderDetail(group) {
  const version = ++detailVersion;
  if (!group) {
    $('#detail').innerHTML = ['pending', 'early'].includes(tab) && ![...state.pending, ...state.backlog].some(tab === 'early' ? early : experienced)
      ? '<div class="empty"><span class="done">&#10003;</span><h2>All done</h2><p>No unreviewed positions left.</p></div>'
      : '<div class="empty">No position selected</div>';
    return;
  }
  const first = group.jobs[0];
  $('#detail').innerHTML = `<div>${topBadge(group)}</div><div class="company">${escapeText(group.company)}</div><h2>${escapeText(group.title)}</h2><div class="detail-meta"><span>Fit ${Math.round(group.confidence)}</span><span>Discovered ${date(first.first_seen)}</span>${group.at ? `<span class="${tab === 'applied' ? 'applied-date' : ''}">${tab === 'applied' ? 'Applied' : 'Skipped'} ${asDate(group.at).toLocaleDateString(undefined, {year:'numeric', month:'short', day:'numeric'})}</span>` : ''}</div><div class="actions">${['pending', 'early', 'backlog', 'less'].includes(tab) ? '<button class="primary" id="mark-applied">Mark applied</button><button id="skip">Skip</button>' : '<button id="reopen">Move to review</button>'}</div>${group.reason ? `<p style="margin-top:18px">${escapeText(group.reason)}</p>` : ''}<div class="locations"><h3 class="section-title">LOCATIONS &amp; LISTINGS</h3>${group.jobs.map(job => listingRow(job, group.title)).join('')}</div><h3 class="section-title description-head">DESCRIPTION</h3><div id="description" class="description">Loading description...</div>`;
  const posted = document.createElement('span');
  posted.textContent = postedLabel(first);
  posted.className = postedToday(first) ? 'posted-today' : '';
  $('#detail .detail-meta').append(posted);
  document.querySelectorAll('.location-row > span').forEach((element, index) => {
    const stamp = document.createElement('div');
    stamp.className = 'muted';
    stamp.textContent = postedLabel(group.jobs[index]);
    element.append(stamp);
  });
  if ($('#mark-applied')) $('#mark-applied').onclick = () => decide('applied');
  document.querySelectorAll('[data-company-link]').forEach(button => {
    button.onclick = () => setCompanyLink(button.dataset.companyLink, Boolean(button.dataset.remove));
  });
  if ($('#skip')) $('#skip').onclick = () => { skipTarget = group.id; $('#reason').value = ''; $('#skip-dialog').showModal(); $('#reason').focus(); };
  if ($('#reopen')) $('#reopen').onclick = () => decide('pending');
  const key = `${first.url}\u0000${group.id}`;
  if (described.key === key) { $('#description').textContent = described.text; return; }
  try {
    // Whether the posting moved or was replaced is decided on the server, from
    // the decision's own snapshot; the page sends only which one it is showing.
    const body = await api('/api/job?url=' + encodeURIComponent(first.url)
      + '&id=' + encodeURIComponent(group.id));
    // A teaser is not the whole description, and the paid listing's text is
    // not the company's own; each says so rather than passing for the full one.
    const note = {excerpt: 'Excerpt only. The full description is on the original listing.\n\n',
                  discovery: 'From the listing this posting was first found in.\n\n'}[body.kind] ?? '';
    const text = body.replaced
      ? 'This address now advertises a different requisition, so the description published here is not the one this decision was about.'
      : (body.description ? note + body.description : 'Description unavailable. Open the original listing.');
    if (version === detailVersion) { described = {key, text}; $('#description').textContent = text; }
  } catch (err) { if (version === detailVersion) $('#description').textContent = err.message; }
}
// The saved posting leaves the list the moment the server has it, and the next
// one in the list is selected. It used to stay put until the refresh after the
// save came back, which on the live queue was a full rebuild. The refresh still
// follows, and replaces this local move with the server's own answer.
function moveDecided(id, written) {
  const visible = filtered();
  const at = visible.findIndex(group => group.id === id);
  const from = ['pending', 'backlog', 'applied', 'skipped'].find(name => state[name].some(group => group.id === id));
  if (!from) return;
  const group = state[from].find(item => item.id === id);
  state[from] = state[from].filter(item => item.id !== id);
  // Moved back to review: whether it belongs in the recent tab or the backlog
  // is the server's call, and the refresh that follows makes it.
  const {at: _at, reason: _reason, ...undecided} = group;
  state[written.status] = [written.status === 'pending' ? undecided
    : {...group, at: written.at, reason: written.reason ?? ''}, ...state[written.status]];
  if (selected === id) {
    const rest = visible.filter(item => item.id !== id);
    selected = rest[Math.min(at, rest.length - 1)]?.id ?? null;
  }
  described = {key: null, text: null};
  render();
}
// The decision buttons, held while one decision is saving.
const lockActions = locked => document.querySelectorAll('.actions button, .dialog-actions button').forEach(button => button.disabled = locked);
async function decide(status, reason = '', target = null) {
  const id = target ?? selected;
  if (busy || !id) return;
  busy = true;
  lockActions(true);
  try {
    const written = await post('/api/decision', {id,status,reason});
    $('#skip-dialog').close();
    skipTarget = null;
    $('#saved').textContent = `Saved locally at ${clock()}`;
    moveDecided(id, written);
    refresh();
  } catch (err) { error(err.message); }
  finally { busy = false; lockActions(false); }
}
document.querySelectorAll('[data-tab]').forEach(button => button.onclick = () => {
  if (busy) return;
  checkedJobs.clear();
  tab = button.dataset.tab; selected = null; visibleLimit = PAGE;
  document.querySelectorAll('[data-tab]').forEach(item => item.setAttribute('aria-pressed', item === button));
  render();
});
$('#refresh').onclick = refresh;
// The list on screen -- this tab, this search, this order -- into the one
// Browser download: selected positions, or the current filtered list.
async function exportView() {
  const ids = checkedJobs.size ? [...checkedJobs] : filtered().map(group => group.id);
  return downloadWorkbook(ids);
}
$('#export').onclick = exportView;
$('#select-matching').onchange = event => {
  for (const group of filtered()) {
    if (event.target.checked) checkedJobs.add(group.id); else checkedJobs.delete(group.id);
  }
  render();
};
$('#clear-selection').onclick = () => {checkedJobs.clear(); render();};
$('#batch').onchange = event => {
  checkedJobs.clear();
  batchName = '';
  if (event.target.value !== '') {
    const index = Number(event.target.value);
    const members = filtered().slice(index * BATCH, (index + 1) * BATCH);
    members.forEach(group => checkedJobs.add(group.id));
    const first = index * BATCH + 1;
    batchName = `review-batch-${index + 1}-${first}-${first + members.length - 1}.xlsx`;
  }
  render();
};
async function downloadWorkbook(ids) {
  if (!loaded || downloading || !ids.length) return;
  downloading = true; $('#export').disabled = true; updateSelection();
  try {
    const response = await fetch('/api/export/download', {method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Review-Token': state.token},
      body: JSON.stringify({ids})});
    if (!response.ok) throw new Error((await response.json()).error || 'Download failed');
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement('a');
    anchor.href = url; anchor.download = batchName || 'selected-positions.xlsx';
    document.body.append(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    error(''); $('#saved').textContent = `Downloaded ${ids.length} positions at ${clock()}`;
  } catch (err) {error(err.message);}
  finally {downloading = false; $('#export').disabled = false; updateSelection();}
}
$('#download-selected').onclick = () => downloadWorkbook([...checkedJobs]);
document.addEventListener('keydown', event => {
  if (event.key !== 'e' && event.key !== 'E') return;
  if (event.ctrlKey || event.metaKey || event.altKey || event.repeat) return;
  if (event.target.closest?.('input, textarea, select, [contenteditable]') || $('#skip-dialog').open) return;
  event.preventDefault();
  exportView();
});
$('#sort').value = SORTS[sortMode] || sortMode === 'recommended' ? sortMode : 'fit-desc';
sortMode = $('#sort').value;
$('#sort').onchange = event => {
  sortMode = event.target.value;
  try { localStorage.setItem(SORT_KEY, sortMode); } catch { /* no storage */ }
  selected = null;
  visibleLimit = PAGE;
  $('#list').scrollTop = 0;
  render();
};
$('#search').oninput = () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { visibleLimit = PAGE; render(); }, 120);
};
$('#cancel-skip').onclick = () => { skipTarget = null; $('#skip-dialog').close(); };
$('#skip-form').onsubmit = event => { event.preventDefault(); decide('skipped', $('#reason').value, skipTarget); };
refresh();

$('#manual-form').onsubmit = async event => {
  event.preventDefault();
  const buttons = $('#manual-form').querySelectorAll('button');
  buttons.forEach(button => button.disabled = true);
  $('#manual-result').textContent = 'Reading link...';
  try {
    const written = await post('/api/manual', {
      official: $('#manual-official').checked, url: $('#manual-url').value, company: $('#manual-company').value,
      title: $('#manual-title').value, location: $('#manual-location').value,
      description: $('#manual-description').value, source_job_id: $('#manual-id').value,
      status: tab === 'applied' || event.submitter?.id === 'manual-applied' ? 'applied' : 'pending'
    });
    $('#manual-form').reset();
    $('#manual-result').textContent = written.status === 'applied' ? 'Marked applied' :
      `${written.replaced ? 'Replaced third-party listing' : written.created ? 'Added job' : 'Already in queue'} - Fit ${written.confidence}`;
    error(''); await refresh();
  } catch (err) { $('#manual-result').textContent = ''; error(err.message); }
  finally { buttons.forEach(button => button.disabled = false); }
};
