const state = { entries: [], statuses: new Map(), editingId: null, openingAll: false };
const $ = (selector) => document.querySelector(selector);
const form = $('#connection-form');
let toastTimer;

function notice(message, error = false) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.toggle('error', error);
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 5500);
}

async function call(method, ...args) {
  if (!window.pywebview?.api) throw new Error('Open this page using the SSH Sketchbook launcher.');
  const result = await window.pywebview.api[method](...args);
  if (!result.ok) throw new Error(result.error || 'Something went wrong.');
  return result.data;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function showView(view) {
  $('#home-view').hidden = view !== 'home';
  $('#settings-view').hidden = view !== 'settings';
  $('#breadcrumb-page').textContent = view === 'home' ? 'MY MACHINES' : 'CONFIGURE';
  document.querySelectorAll('.nav-link').forEach(link => {
    const active = link.dataset.view === view;
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  window.scrollTo(0, 0);
}

function machineIcon() {
  const wrapper = element('div', 'machine-icon');
  wrapper.innerHTML = '<svg viewBox="0 0 30 30" fill="none" aria-hidden="true"><rect x="4" y="5" width="22" height="17" rx="2.5" stroke="currentColor" stroke-width="1.8"/><path d="m9 11 4 4-4 4m8 0h5M12 25h6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  return wrapper;
}

function statusChip(status) {
  if (!status) return element('span', 'status-chip', 'Not checked');
  return element('span', `status-chip ${status.ssh_port ? 'reachable' : 'unreachable'}`, status.ssh_port ? 'SSH ready' : 'SSH closed');
}

function renderHome() {
  const grid = $('#machine-grid');
  grid.replaceChildren();
  $('#machine-count').textContent = state.entries.length;
  $('#open-all-button').disabled = !state.entries.length || state.openingAll;
  $('#home-empty').hidden = state.entries.length !== 0;
  for (const entry of state.entries) {
    const status = state.statuses.get(entry.id);
    const card = element('article', 'machine-card');
    const top = element('div', 'card-top');
    top.append(machineIcon(), statusChip(status));
    card.append(top, element('h3', '', entry.name), element('p', 'description', entry.description || 'No note added yet.'));
    card.append(element('div', 'address', `${entry.username}@${entry.host}  ·  port ${entry.port}`));
    card.append(element('p', 'card-status-detail', status ? `Ping: ${status.ping ? 'reachable' : 'no reply'}  ·  SSH port: ${status.ssh_port ? 'open' : 'closed'}` : 'Run a status check to see if it is reachable.'));
    const actions = element('div', 'card-actions');
    const connect = element('button', 'button button-dark', '↗  Connect');
    connect.type = 'button';
    connect.setAttribute('aria-label', `Connect to ${entry.name}`);
    connect.addEventListener('click', async () => {
      connect.disabled = true;
      try { await call('connect', entry.id); notice(`Opening ${entry.name} in Windows Terminal...`); }
      catch (error) { notice(error.message, true); }
      finally { connect.disabled = false; }
    });
    const edit = element('button', 'edit-link', 'Edit details');
    edit.type = 'button';
    edit.addEventListener('click', () => editEntry(entry.id));
    actions.append(connect, edit);
    card.append(actions);
    grid.append(card);
  }
}

function renderSaved() {
  const list = $('#saved-list');
  list.replaceChildren();
  $('#saved-count').textContent = state.entries.length;
  if (!state.entries.length) list.append(element('p', 'saved-empty', 'No machines saved yet. Add one on the left.'));
  for (const entry of state.entries) {
    const item = element('div', 'saved-item');
    item.append(element('span', 'saved-item-icon', '>_'));
    const info = element('div', 'saved-item-info');
    info.append(element('strong', '', entry.name), element('small', '', `${entry.username}@${entry.host}:${entry.port}`));
    const actions = element('div', 'saved-actions');
    const edit = element('button', 'icon-button', '✎');
    edit.type = 'button';
    edit.title = `Edit ${entry.name}`;
    edit.setAttribute('aria-label', edit.title);
    edit.addEventListener('click', () => editEntry(entry.id));
    const remove = element('button', 'icon-button delete', '×');
    remove.type = 'button';
    remove.title = `Delete ${entry.name}`;
    remove.setAttribute('aria-label', remove.title);
    remove.addEventListener('click', async () => {
      if (!window.confirm(`Delete "${entry.name}"? This cannot be undone.`)) return;
      try {
        await call('delete_connection', entry.id);
        if (state.editingId === entry.id) resetForm();
        await loadEntries();
        notice(`${entry.name} was deleted.`);
      } catch (error) { notice(error.message, true); }
    });
    actions.append(edit, remove);
    item.append(info, actions);
    list.append(item);
  }
}

function render() { renderHome(); renderSaved(); }

async function loadEntries() {
  state.entries = await call('list_connections');
  state.statuses.clear();
  render();
}

function resetForm() {
  form.reset();
  state.editingId = null;
  $('#form-title').textContent = 'Add a machine';
  $('#save-button').textContent = '＋ Save machine';
  $('#cancel-edit').hidden = true;
  $('#form-error').hidden = true;
  $('.advanced').open = false;
}

function editEntry(id) {
  const entry = state.entries.find(item => item.id === id);
  if (!entry) return;
  state.editingId = id;
  for (const field of ['name', 'description', 'host', 'username', 'port', 'key_path', 'jump_host', 'timeout']) {
    form.elements[field].value = entry[field] ?? '';
  }
  $('#form-title').textContent = 'Edit this machine';
  $('#save-button').textContent = '✓ Save changes';
  $('#cancel-edit').hidden = false;
  $('#form-error').hidden = true;
  $('.advanced').open = !!(entry.key_path || entry.jump_host || entry.timeout !== 10);
  showView('settings');
  $('#name').focus();
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const errorBox = $('#form-error');
  errorBox.hidden = true;
  const data = {
    name: form.elements.name.value.trim(), description: form.elements.description.value.trim(),
    host: form.elements.host.value.trim(), username: form.elements.username.value.trim(),
    port: Number(form.elements.port.value), key_path: form.elements.key_path.value.trim(),
    jump_host: form.elements.jump_host.value.trim(), timeout: Number(form.elements.timeout.value),
  };
  if (!data.name || !data.host || !data.username || !form.elements.port.value || !form.elements.timeout.value) {
    errorBox.textContent = 'Please fill in the name, username, host, port, and timeout.';
    errorBox.hidden = false;
    return;
  }
  const button = $('#save-button');
  button.disabled = true;
  try {
    const editing = state.editingId !== null;
    await call('save_connection', data, state.editingId);
    resetForm();
    await loadEntries();
    notice(editing ? 'Machine updated.' : 'Machine added to your sketchbook.');
    showView('home');
  } catch (error) { errorBox.textContent = error.message; errorBox.hidden = false; }
  finally { button.disabled = false; }
});

$('#open-all-button').addEventListener('click', async () => {
  if (!state.entries.length || state.openingAll) return;
  state.openingAll = true;
  const button = $('#open-all-button');
  button.disabled = true;
  try {
    const count = await call('connect_all');
    notice(`Opening ${count} SSH ${count === 1 ? 'tab' : 'tabs'} in Windows Terminal...`);
  } catch (error) { notice(error.message, true); }
  finally { state.openingAll = false; button.disabled = !state.entries.length; }
});

$('#refresh-button').addEventListener('click', async () => {
  const button = $('#refresh-button');
  button.disabled = true;
  button.textContent = '↻  Checking...';
  try {
    const statuses = await call('refresh_status');
    state.statuses = new Map(statuses.map(item => [item.id, item]));
    renderHome();
    notice('Status check finished.');
  } catch (error) { notice(error.message, true); }
  finally { button.disabled = false; button.innerHTML = '<span class="refresh-icon" aria-hidden="true">↻</span> Refresh status'; }
});

$('#cancel-edit').addEventListener('click', resetForm);
$('#add-home').addEventListener('click', () => { resetForm(); showView('settings'); $('#name').focus(); });
$('#add-empty').addEventListener('click', () => { resetForm(); showView('settings'); $('#name').focus(); });
document.querySelectorAll('.nav-link').forEach(link => link.addEventListener('click', () => showView(link.dataset.view)));

let initialized = false;
function initialize() {
  if (initialized || !window.pywebview?.api) return;
  initialized = true;
  loadEntries().catch(error => notice(error.message, true));
}
document.addEventListener('pywebviewready', initialize);
initialize();
const bridgeTimer = setInterval(() => {
  initialize();
  if (initialized) clearInterval(bridgeTimer);
}, 100);
setTimeout(() => {
  if (!initialized) {
    clearInterval(bridgeTimer);
    notice('Could not start the desktop connection service. Restart the app.', true);
  }
}, 5000);
