let state = {pending: [], backlog: [], applied: [], skipped: []};
let tab = 'pending', selected = null, busy = false, detailVersion = 0, visibleLimit = 75;
const $ = selector => document.querySelector(selector);
const escapeText = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const safeLink = value => { try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? escapeText(url.href) : '#'; } catch { return '#'; } };
const date = value => value ? new Date(value).toLocaleDateString(undefined, {month:'short', day:'numeric'}) : 'Unknown';
const postedToday = job => job.posted_at && new Date(job.posted_at).toDateString() === new Date().toDateString();
const postedLabel = job => !job.posted_at ? 'Posting date unavailable' : postedToday(job) ? 'Posted today' : `Posted ${date(job.posted_at)}`;
function error(message) { $('#error').textContent = message; $('#error').hidden = !message; }
async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'Request failed');
  return body;
}
async function refresh() {
  try { state = await api('/api/queue'); error(''); render(); }
  catch (err) { error(err.message); }
}
function filtered() {
  const text = $('#search').value.trim().toLowerCase();
  return state[tab].filter(group => `${group.company} ${group.title}`.toLowerCase().includes(text));
}
function render() {
  $('#remaining').textContent = state.pending.length;
  $('#applied').textContent = state.applied.length;
  $('#skipped').textContent = state.skipped.length;
  $('#pending-count').textContent = state.pending.length;
  $('#backlog-count').textContent = state.backlog.length;
  const groups = filtered();
  if (!groups.some(group => group.id === selected)) selected = groups[0]?.id ?? null;
  $('#count').textContent = `${groups.length} positions`;
  $('#list').replaceChildren();
  if (!groups.length) {
    $('#list').innerHTML = '<div class="empty">No matching positions</div>';
  }
  groups.slice(0, visibleLimit).forEach(group => {
    const button = document.createElement('button');
    button.className = 'job' + (group.id === selected ? ' selected' : '');
    button.setAttribute('aria-pressed', group.id === selected);
    const locations = [...new Set(group.jobs.map(job => job.location).filter(Boolean))];
    button.innerHTML = `<div class="company">${escapeText(group.company)}</div><div class="job-title">${escapeText(group.title)}</div><span class="score">${Math.round(group.confidence)}</span><div class="job-meta">${escapeText(locations.length > 1 ? `${locations.length} locations` : locations[0] || 'Location not listed')} &middot; ${group.jobs.length} listing${group.jobs.length === 1 ? '' : 's'}</div>`;
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
  $('#detail').innerHTML = `<div class="company">${escapeText(group.company)}</div><h2>${escapeText(group.title)}</h2><div class="detail-meta"><span>Fit ${Math.round(group.confidence)}</span><span>Discovered ${date(first.first_seen)}</span>${group.at ? `<span>${tab === 'applied' ? 'Applied' : 'Skipped'} ${date(group.at)}</span>` : ''}</div><div class="actions">${tab === 'pending' || tab === 'backlog' ? '<button class="primary" id="mark-applied">Mark applied</button><button id="skip">Skip</button>' : '<button id="reopen">Move to review</button>'}</div>${group.reason ? `<p style="margin-top:18px">${escapeText(group.reason)}</p>` : ''}<div class="locations"><h3 class="section-title">LOCATIONS &amp; LISTINGS</h3>${group.jobs.map(job => `<div class="location-row"><span>${escapeText(job.location || 'Location not listed')}<br><span class="muted">${escapeText(job.provider_key)}</span></span><a href="${safeLink(job.url)}" target="_blank" rel="noopener noreferrer">Open listing &#8599;</a></div>`).join('')}</div><h3 class="section-title description-head">DESCRIPTION</h3><div id="description" class="description">Loading description...</div>`;
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
  if ($('#skip')) $('#skip').onclick = () => { $('#reason').value = ''; $('#skip-dialog').showModal(); $('#reason').focus(); };
  if ($('#reopen')) $('#reopen').onclick = () => decide('pending');
  try {
    const body = await api('/api/job?url=' + encodeURIComponent(first.url));
    if (version === detailVersion) $('#description').textContent = body.description || 'Description unavailable. Open the original listing.';
  } catch (err) { if (version === detailVersion) $('#description').textContent = err.message; }
}
async function decide(status, reason = '') {
  if (busy || !selected) return;
  busy = true;
  const id = selected;
  document.querySelectorAll('.actions button, .dialog-actions button').forEach(button => button.disabled = true);
  try {
    await api('/api/decision', {method:'POST', headers:{'Content-Type':'application/json', 'X-Review-Token':state.token}, body:JSON.stringify({id,status,reason})});
    $('#skip-dialog').close();
    $('#saved').textContent = `Saved locally at ${new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}`;
    await refresh();
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
$('#search').oninput = () => { visibleLimit = 75; render(); };
$('#cancel-skip').onclick = () => $('#skip-dialog').close();
$('#skip-form').onsubmit = event => { event.preventDefault(); decide('skipped', $('#reason').value); };
refresh();
