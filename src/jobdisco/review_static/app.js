let state = {pending: [], backlog: [], applied: [], skipped: [], labels: []};
let tab = 'pending', selected = null, busy = false, detailVersion = 0, visibleLimit = 75;
// Two refreshes can be in flight -- a click on Refresh, a decision saving, a
// slow first request -- and they do not answer in the order they were asked.
// The later answer is the current one; an earlier one arriving after it used
// to put the queue back to a state the user had already moved on from.
let queueVersion = 0;
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
const $ = selector => document.querySelector(selector);
const escapeText = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const safeLink = value => { try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? escapeText(url.href) : '#'; } catch { return '#'; } };
// A bare `2026-09-20` is a calendar day, and `new Date` reads it as UTC
// midnight -- which is the day before, everywhere west of Greenwich. Every
// date this page shows was arriving a day early in Los Angeles.
const asDate = value => {
  const bare = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value ?? ''));
  return bare ? new Date(+bare[1], +bare[2] - 1, +bare[3]) : new Date(value);
};
const date = value => value ? asDate(value).toLocaleDateString(undefined, {month:'short', day:'numeric'}) : 'Unknown';
const postedToday = job => job.posted_at && asDate(job.posted_at).toDateString() === new Date().toDateString();
const postedLabel = job => !job.posted_at ? 'Posting date unavailable' : postedToday(job) ? 'Posted today' : `Posted ${date(job.posted_at)}`;
function error(message) { $('#error').textContent = message; $('#error').hidden = !message; }
async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'Request failed');
  return body;
}
async function refresh() {
  const version = ++queueVersion;
  try {
    const next = await api('/api/queue');
    if (version !== queueVersion) return;
    described = {key: null, text: null};
    state = next; loaded = true; error(''); render();
  } catch (err) {
    if (version !== queueVersion) return;
    error(err.message);
    if (!loaded) $('#list').innerHTML = `<div class="empty">The queue could not be loaded: ${escapeText(err.message)}. Use Refresh to try again.</div>`;
  }
}
function filtered() {
  const text = $('#search').value.trim().toLowerCase();
  return state[tab].filter(group => `${group.company} ${group.title}`.toLowerCase().includes(text));
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
  $('#remaining').textContent = state.pending.length;
  $('#applied').textContent = state.applied.length;
  $('#skipped').textContent = state.skipped.length;
  $('#pending-count').textContent = state.pending.length;
  $('#backlog-count').textContent = state.backlog.length;
  const groups = filtered();
  if (!groups.some(group => group.id === selected)) selected = groups[0]?.id ?? null;
  $('#count').textContent = `${groups.length} positions` + bandSummary(groups);
  $('#list').replaceChildren();
  if (!groups.length) {
    $('#list').innerHTML = '<div class="empty">No matching positions</div>';
  }
  groups.slice(0, visibleLimit).forEach(group => {
    const button = document.createElement('button');
    button.className = 'job' + (group.id === selected ? ' selected' : '');
    button.setAttribute('aria-pressed', group.id === selected);
    const locations = [...new Set(group.jobs.map(job => job.location).filter(Boolean))];
    button.innerHTML = `<div>${bandChip(group)}${flagChip(group)}${internChip(group)}</div><div class="company">${escapeText(group.company)}</div><div class="job-title">${escapeText(group.title)}</div><span class="score">${Math.round(group.confidence)}</span><div class="job-meta">${escapeText(locations.length > 1 ? `${locations.length} locations` : locations[0] || 'Location not listed')} &middot; ${group.jobs.length} listing${group.jobs.length === 1 ? '' : 's'}</div>`;
    if (group.jobs.some(postedToday)) {
      const mark = document.createElement('span');
      mark.className = 'posted-today';
      mark.textContent = 'Posted today';
      button.querySelector('.job-meta').append(' \u00b7 ', mark);
    }
    button.onclick = () => { selected = group.id; render(); };
    $('#list').append(button);
  });
  if (groups.length > visibleLimit) {
    const more = document.createElement('button');
    more.textContent = 'Show more';
    more.className = 'load-more';
    more.onclick = () => { visibleLimit += 75; render(); };
    $('#list').append(more);
  }
  renderDetail(groups.find(group => group.id === selected));
}
async function renderDetail(group) {
  const version = ++detailVersion;
  if (!group) {
    $('#detail').innerHTML = tab === 'pending' && !state.pending.length
      ? '<div class="empty"><span class="done">&#10003;</span><h2>All done for today</h2><p>No unreviewed positions in the last 72 hours.</p></div>'
      : '<div class="empty">No position selected</div>';
    return;
  }
  const first = group.jobs[0];
  $('#detail').innerHTML = `<div>${bandChip(group)}${flagChip(group)}${internChip(group)}</div><div class="company">${escapeText(group.company)}</div><h2>${escapeText(group.title)}</h2><div class="detail-meta"><span>Fit ${Math.round(group.confidence)}</span><span>Discovered ${date(first.first_seen)}</span>${group.at ? `<span>${tab === 'applied' ? 'Applied' : 'Skipped'} ${date(group.at)}</span>` : ''}</div><div class="actions">${tab === 'pending' || tab === 'backlog' ? '<button class="primary" id="mark-applied">Mark applied</button><button id="skip">Skip</button>' : '<button id="reopen">Move to review</button>'}</div>${group.reason ? `<p style="margin-top:18px">${escapeText(group.reason)}</p>` : ''}<div class="locations"><h3 class="section-title">LOCATIONS &amp; LISTINGS</h3>${group.jobs.map(job => `<div class="location-row"><span>${escapeText(job.location || 'Location not listed')}<br><span class="muted">${escapeText(job.provider_key)}</span></span><a href="${safeLink(job.url)}" target="_blank" rel="noopener noreferrer">Open listing &#8599;</a></div>`).join('')}</div><h3 class="section-title description-head">DESCRIPTION</h3><div id="description" class="description">Loading description...</div>`;
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
  if ($('#skip')) $('#skip').onclick = () => { skipTarget = group.id; $('#reason').value = ''; $('#skip-dialog').showModal(); $('#reason').focus(); };
  if ($('#reopen')) $('#reopen').onclick = () => decide('pending');
  const key = `${first.url}\u0000${group.id}`;
  if (described.key === key) { $('#description').textContent = described.text; return; }
  try {
    const body = await api('/api/job?url=' + encodeURIComponent(first.url)
      + '&id=' + encodeURIComponent(group.id)
      + '&provider=' + encodeURIComponent(first.provider_key ?? '')
      + '&title=' + encodeURIComponent(group.title ?? ''));
    const text = body.replaced
      ? 'This address now advertises a different requisition, so the description published here is not the one this decision was about.'
      : (body.description || 'Description unavailable. Open the original listing.');
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
async function decide(status, reason = '', target = null) {
  const id = target ?? selected;
  if (busy || !id) return;
  busy = true;
  document.querySelectorAll('.actions button, .dialog-actions button').forEach(button => button.disabled = true);
  try {
    const written = await api('/api/decision', {method:'POST', headers:{'Content-Type':'application/json', 'X-Review-Token':state.token}, body:JSON.stringify({id,status,reason})});
    $('#skip-dialog').close();
    skipTarget = null;
    $('#saved').textContent = `Saved locally at ${new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}`;
    moveDecided(id, written);
    refresh();
  } catch (err) { error(err.message); }
  finally { busy = false; document.querySelectorAll('.actions button, .dialog-actions button').forEach(button => button.disabled = false); }
}
document.querySelectorAll('[data-tab]').forEach(button => button.onclick = () => {
  if (busy) return;
  tab = button.dataset.tab; selected = null; visibleLimit = 75;
  document.querySelectorAll('[data-tab]').forEach(item => item.setAttribute('aria-pressed', item === button));
  render();
});
$('#refresh').onclick = refresh;
$('#search').oninput = () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { visibleLimit = 75; render(); }, 120);
};
$('#cancel-skip').onclick = () => { skipTarget = null; $('#skip-dialog').close(); };
$('#skip-form').onsubmit = event => { event.preventDefault(); decide('skipped', $('#reason').value, skipTarget); };
refresh();
