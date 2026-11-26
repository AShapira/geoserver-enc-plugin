'use strict';
const el = id => document.getElementById(id);
let library, providerId, selectedJob, editing, revision, submitting = false;
let refreshSequence = 0;
const labels = {acquire: 'Acquire exchange', prepare: 'Prepare catalog', export: 'Export for transfer'};
const date = text => new Date(text).toLocaleString();
function node(tag, text, style) {
  const item = document.createElement(tag);
  item.textContent = text;
  if (style) item.className = style;
  return item;
}
function button(text, click, disabled = false) {
  const item = node('button', text);
  item.onclick = click;
  item.disabled = disabled;
  return item;
}
async function request(url, body) {
  const options = body ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)} : {};
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw Error(data.error);
  return data;
}
function error(text, id = 'error') {
  el(id).textContent = text;
  el(id).hidden = !text;
}
function current() { return library.providers.find(p => p.id === providerId); }
function showForm(edit) {
  editing = edit;
  el('formTitle').textContent = edit ? 'Edit provider' : 'Add provider';
  el('location').value = edit ? current().location : '';
  el('displayName').value = edit ? current().name : '';
  error('', 'formError');
  el('location').oninput();
  el('dialog').showModal();
}
el('location').oninput = () => {
  let path = el('location').value.trim();
  if (/^https?:\/\//i.test(path)) {
    try { const url = new URL(path); path = url.pathname.replace(/\/$/, '') || url.hostname; }
    catch { path = ''; }
  }
  el('displayName').placeholder = path.split('/').filter(Boolean).pop()?.replace(/\.zip$/i, '') || '';
};
el('add').onclick = () => showForm(false);
el('edit').onclick = () => showForm(true);
el('cancel').onclick = () => el('dialog').close();
el('providerForm').onsubmit = async event => {
  event.preventDefault();
  const body = {location:el('location').value, name:el('displayName').value};
  if (editing) body.id = providerId;
  const save = event.submitter;
  save.disabled = true;
  try {
    const result = await request('/api/providers', body);
    providerId = result.id;
    selectedJob = null;
    el('dialog').close();
    await refresh();
  } catch (e) { error(e.message, 'formError'); }
  finally { save.disabled = false; }
};
async function start(action, snapshot) {
  if (submitting) return;
  submitting = true;
  error('');
  try {
    const body = {action, provider:providerId};
    if (snapshot) body.snapshot = snapshot;
    selectedJob = (await request('/api/jobs', body)).id;
    await refresh();
  } catch (e) { error(e.message); }
  finally { submitting = false; }
}
function render() {
  const p = current();
  localStorage.setItem('enc.manager.provider', providerId);
  const active = library.jobs.find(j => j.status === 'running');
  el('activity').textContent = active ? 'Job running' : '';
  const nav = el('providers');
  nav.replaceChildren();
  for (const source of library.providers) {
    const choice = button(source.name, () => {
      providerId = source.id; selectedJob = null; error(''); render(); refresh();
    });
    choice.setAttribute('aria-current', String(source.id === providerId));
    nav.append(choice);
  }
  el('detail').hidden = false;
  el('name').textContent = p.name;
  el('source').textContent = p.location;
  el('credit').textContent = p.attribution || '';
  el('edit').hidden = p.kind === 'builtin';
  el('acquire').textContent = p.kind === 'local' ? 'Import exchange' : 'Download exchange';
  el('acquire').disabled = Boolean(active);
  el('acquire').onclick = () => start('acquire');
  const list = el('snapshots');
  list.replaceChildren();
  const snapshots = library.snapshots.filter(s => s.provider === providerId);
  if (!snapshots.length) list.append(node('p', 'No saved exchanges for this provider.', 'empty'));
  for (const s of snapshots) {
    const item = node('div', '', 'entry'), row = node('div', '', 'row');
    row.append(node('strong', date(s.created)), node('small', s.generation ? 'Ready · '+s.cells+' cells' : 'Saved'));
    const details = node('details', '');
    details.append(node('summary', 'File locations and checksum'),
                   node('p', 'Saved exchange'), node('code', library.dataDir+'/snapshots/'+s.id),
                   node('p', 'Exchange SHA-256'), node('code', s.digest));
    if (s.generation) {
      details.append(node('p', 'Prepared catalog'), node('code', library.dataDir+'/catalogues/'+p.id+'/'+s.generation));
    }
    item.append(row, node('p', s.location, 'muted'), details);
    const actions = node('div', '', 'actions');
    actions.append(button('Prepare catalog', () => start('prepare', s.id), Boolean(active)));
    if (s.generation) actions.append(button('Export for transfer', () => start('export', s.id), Boolean(active)));
    if (s.package) {
      item.append(node('p', 'Transfer package · '+(s.bytes / 1048576).toFixed(1)+' MiB'),
                  node('code', s.package), node('p', 'SHA-256'), node('code', s.checksum));
    }
    item.append(actions); list.append(item);
  }
  const history = el('jobs');
  history.replaceChildren();
  const jobs = library.jobs.filter(j => j.provider === providerId);
  if (!jobs.length) history.append(node('p', 'No jobs for this provider.', 'empty'));
  if (!jobs.some(j => j.id === selectedJob)) selectedJob = jobs[0]?.id;
  for (const job of jobs) {
    const entry = button('', () => { selectedJob = job.id; render(); refresh(); });
    entry.className = 'job';
    entry.setAttribute('aria-pressed', String(selectedJob === job.id));
    entry.append(node('span', labels[job.action]+' · '+date(job.created)), node('span', job.status));
    history.append(entry);
    if (job.id === selectedJob && job.error) {
      history.append(node('p', job.error, 'problem'),
                     button('Retry', () => start(job.action, job.snapshot), Boolean(active)));
    }
  }
  el('logPanel').hidden = !selectedJob;
}
async function refresh() {
  const seq = ++refreshSequence;
  try {
    const data = await request('/api/state');
    if (seq !== refreshSequence) return;
    library = data;
    if (!providerId) {
      const saved = localStorage.getItem('enc.manager.provider');
      providerId = data.providers.find(p => p.id === saved)?.id
        || data.jobs.find(j => j.status === 'running')?.provider || data.providers[0].id;
    }
    const key = JSON.stringify([providerId, data]);
    if (revision !== key) { revision = key; render(); }
    const job = selectedJob;
    if (job) {
      const result = await request('/api/logs/'+job);
      if (seq === refreshSequence && selectedJob === job) el('log').textContent = result.log || 'Starting…';
    }
  } catch (e) { if (seq === refreshSequence) error(e.message); }
}
async function poll() { await refresh(); setTimeout(poll, 1800); }
poll();
