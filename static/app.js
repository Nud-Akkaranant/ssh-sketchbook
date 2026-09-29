const state = { entries: [], statuses: new Map(), editingId: null, openingAll: false, sessions: new Map(), activeSessionId: null, openingSession: false };
let sessionPollTimer;
let sessionPollBusy = false;
let resizeTimer;
let workspaceResizeObserver;
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
  $('#terminal-view').hidden = view !== 'terminal';
  $('#breadcrumb-page').textContent = { home: 'MY MACHINES', settings: 'CONFIGURE', terminal: 'TERMINAL' }[view];
  document.querySelectorAll('.nav-link').forEach(link => {
    const active = link.dataset.view === view;
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  window.scrollTo(0, 0);
  if (view === 'terminal') requestAnimationFrame(fitActiveTerminal);
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
    const connect = element('button', 'button button-outline', '↗  Windows Terminal');
    connect.type = 'button';
    connect.setAttribute('aria-label', `Connect to ${entry.name} in Windows Terminal`);
    connect.addEventListener('click', async () => {
      connect.disabled = true;
      try { await call('connect', entry.id); notice(`Opening ${entry.name} in Windows Terminal...`); }
      catch (error) { notice(error.message, true); }
      finally { connect.disabled = false; }
    });
    const inApp = element('button', 'button button-dark', '⌘  Connect via app');
    inApp.type = 'button';
    inApp.setAttribute('aria-label', `Connect to ${entry.name} inside the app`);
    inApp.addEventListener('click', async () => {
      inApp.disabled = true;
      try { await openSession(entry.id); }
      catch (error) { notice(error.message, true); }
      finally { inApp.disabled = false; }
    });
    const edit = element('button', 'edit-link', 'Edit details');
    edit.type = 'button';
    edit.addEventListener('click', () => editEntry(entry.id));
    actions.append(inApp, connect, edit);
    card.append(actions);
    grid.append(card);
  }
}

function renderTerminalChoices() {
  const select = $('#terminal-machine');
  const selected = select.value;
  select.replaceChildren();
  for (const entry of state.entries) {
    const option = element('option', '', entry.name);
    option.value = entry.id;
    select.append(option);
  }
  if (state.entries.some(entry => entry.id === selected)) select.value = selected;
  select.disabled = !state.entries.length;
  $('#terminal-connect-button').disabled = !state.entries.length || state.openingSession;
}

function renderTerminalTabs() {
  const tabs = $('#terminal-tabs');
  tabs.replaceChildren();
  $('#terminal-empty').hidden = state.sessions.size !== 0;
  $('#terminal-workspace').hidden = state.sessions.size === 0;
  for (const session of state.sessions.values()) {
    const wrapper = element('div', `terminal-tab ${session.id === state.activeSessionId ? 'selected' : ''}`);
    const select = element('button', 'terminal-tab-select', session.name + (session.running ? '' : ' · ended'));
    select.type = 'button';
    select.id = `tab-${session.id}`;
    select.setAttribute('role', 'tab');
    select.setAttribute('aria-selected', String(session.id === state.activeSessionId));
    select.setAttribute('aria-controls', `panel-${session.id}`);
    select.title = session.name;
    select.addEventListener('click', () => selectSession(session.id));
    const close = element('button', 'terminal-tab-close', '×');
    close.type = 'button';
    close.setAttribute('aria-label', `Close ${session.name} terminal tab`);
    close.addEventListener('click', () => closeSession(session.id));
    wrapper.append(select, close);
    tabs.append(wrapper);
    session.panel.hidden = session.id !== state.activeSessionId;
    session.panel.setAttribute('aria-labelledby', select.id);
  }
}

function fitActiveTerminal() {
  if ($('#terminal-view').hidden) return;
  const session = state.sessions.get(state.activeSessionId);
  if (!session || session.panel.hidden) return;
  session.fit.fit();
  session.terminal.scrollToBottom();
  const { cols, rows } = session.terminal;
  if (session.cols === cols && session.rows === rows) return;
  session.cols = cols;
  session.rows = rows;
  if (session.running) call('resize_session', session.id, cols, rows).catch(error => notice(error.message, true));
}

function setTerminalFullscreen(enabled) {
  const workspace = $('#terminal-workspace');
  const button = $('#terminal-fullscreen');
  workspace.classList.toggle('terminal-fullscreen', enabled);
  button.setAttribute('aria-pressed', String(enabled));
  button.setAttribute('aria-label', enabled ? 'Exit full screen terminal' : 'Full screen terminal');
  button.title = enabled ? 'Exit full screen terminal' : 'Full screen terminal';
  button.querySelector('span').textContent = enabled ? 'Exit full screen' : 'Full screen';
  requestAnimationFrame(fitActiveTerminal);
}

function toggleTerminalFullscreen() {
  const workspace = $('#terminal-workspace');
  if (workspace.classList.contains('terminal-fullscreen')) {
    if (document.fullscreenElement === workspace) document.exitFullscreen().catch(() => {});
    setTerminalFullscreen(false);
  } else {
    setTerminalFullscreen(true);
    if (workspace.requestFullscreen) workspace.requestFullscreen().catch(() => {});
  }
}

function selectSession(id) {
  if (!state.sessions.has(id)) return;
  state.activeSessionId = id;
  renderTerminalTabs();
  showView('terminal');
  requestAnimationFrame(() => {
    fitActiveTerminal();
    state.sessions.get(id)?.terminal.focus();
  });
}

async function copyTerminalSelection(terminal) {
  const text = terminal.getSelection();
  try {
    await call('clipboard_set', text);
  } catch (error) {
    notice(error.message || 'Could not copy terminal text to the clipboard.', true);
  } finally {
    terminal.focus();
  }
}

async function pasteTerminalClipboard(terminal) {
  try {
    const text = await call('clipboard_get');
    if (text) terminal.paste(text);
  } catch (error) {
    notice(error.message || 'Could not read text from the clipboard.', true);
  }
}

async function openSession(entryId) {
  if (state.openingSession) return;
  state.openingSession = true;
  renderTerminalChoices();
  showView('terminal');
  try {
    const opened = await call('start_session', entryId, 80, 24);
    let session;
    try {
      const terminal = new Terminal({ cursorBlink: true, fontFamily: 'Cascadia Mono, Consolas, monospace', fontSize: 14, scrollback: 2000, theme: { background: '#11191b', foreground: '#e8eee6', cursor: '#efb56d', selectionBackground: '#587d7688' } });
      const fit = new FitAddon.FitAddon();
      terminal.loadAddon(fit);
      const panel = element('div', 'terminal-panel');
      panel.id = `panel-${opened.id}`;
      panel.setAttribute('role', 'tabpanel');
      panel.hidden = true;
      $('#terminal-panels').append(panel);
      terminal.open(panel);
      terminal.attachCustomKeyEventHandler(event => {
        if (event.type !== 'keydown' || !(event.ctrlKey || event.metaKey)) return true;
        const key = event.key.toLowerCase();
        if (key === 'c' && terminal.hasSelection()) {
          copyTerminalSelection(terminal).catch(() => notice('Could not copy terminal text to the clipboard.', true));
          return false;
        }
        if (key === 'v') {
          pasteTerminalClipboard(terminal);
          return false;
        }
        return true;
      });
      session = { id: opened.id, name: opened.name, terminal, fit, panel, running: true, cols: 80, rows: 24, pendingWrite: Promise.resolve() };
      terminal.onData(data => {
        if (!session.running) return;
        terminal.scrollToBottom();
        session.pendingWrite = session.pendingWrite.then(() => call('write_session', session.id, data)).catch(error => {
          if (session.running) notice(error.message, true);
        });
      });
      state.sessions.set(session.id, session);
      selectSession(session.id);
      if (!sessionPollTimer) sessionPollTimer = setInterval(pollSessions, 180);
      await pollSessions();
    } catch (error) {
      if (!session) await call('close_session', opened.id).catch(() => {});
      throw error;
    }
  } finally {
    state.openingSession = false;
    renderTerminalChoices();
  }
}

function writeTerminalOutput(session, text) {
  const buffer = session.terminal.buffer.active;
  const followOutput = session.id === state.activeSessionId && buffer.viewportY >= buffer.baseY - 1;
  session.terminal.write(text, () => {
    if (followOutput && session.id === state.activeSessionId) session.terminal.scrollToBottom();
  });
}

async function pollSessions() {
  if (sessionPollBusy || !state.sessions.size) return;
  sessionPollBusy = true;
  try {
    await Promise.all([...state.sessions.values()].map(async session => {
      if (session.closing || !session.running) return;
      try {
        const result = await call('read_session', session.id);
        if (!state.sessions.has(session.id)) return;
        if (result.truncated) writeTerminalOutput(session, '\r\n[Earlier terminal output was discarded because the session produced too much data.]\r\n');
        if (result.output) writeTerminalOutput(session, result.output);
        if (result.error) writeTerminalOutput(session, `\r\n[Terminal I/O error: ${result.error}]\r\n`);
        if (!result.running) {
          session.running = false;
          writeTerminalOutput(session, `\r\n[SSH session ended${result.exit_code === null || result.exit_code === undefined ? '' : ` with code ${result.exit_code}`}. Close this tab when ready.]\r\n`);
          renderTerminalTabs();
        }
      } catch (error) {
        if (!session.closing) {
          session.running = false;
          writeTerminalOutput(session, `\r\n[Unable to read session: ${error.message}]\r\n`);
          renderTerminalTabs();
        }
      }
    }));
    if (![...state.sessions.values()].some(session => session.running)) {
      clearInterval(sessionPollTimer);
      sessionPollTimer = undefined;
    }
  } finally { sessionPollBusy = false; }
}

async function closeSession(id) {
  const session = state.sessions.get(id);
  if (!session || session.closing) return;
  session.closing = true;
  try { await call('close_session', id); }
  catch (error) { session.closing = false; notice(error.message, true); return; }
  session.terminal.dispose();
  session.panel.remove();
  state.sessions.delete(id);
  if (state.activeSessionId === id) state.activeSessionId = [...state.sessions.keys()].at(-1) || null;
  renderTerminalTabs();
  requestAnimationFrame(fitActiveTerminal);
  if (!state.sessions.size) {
    clearInterval(sessionPollTimer);
    sessionPollTimer = undefined;
    if ($('#terminal-workspace').classList.contains('terminal-fullscreen')) toggleTerminalFullscreen();
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

function render() { renderHome(); renderSaved(); renderTerminalChoices(); }

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

function restoreSavedEntry() {
  const entry = state.entries.find(item => item.id === state.editingId);
  if (!entry) return;
  for (const field of ['name', 'description', 'host', 'username', 'port', 'key_path', 'jump_host', 'timeout']) {
    form.elements[field].value = entry[field] ?? '';
  }
  $('#form-error').hidden = true;
  $('.advanced').open = !!(entry.key_path || entry.jump_host || entry.timeout !== 10);
}

function editEntry(id) {
  const entry = state.entries.find(item => item.id === id);
  if (!entry) return;
  state.editingId = id;
  restoreSavedEntry();
  $('#form-title').textContent = 'Edit this machine';
  $('#save-button').textContent = '✓ Save changes';
  $('#cancel-edit').hidden = false;
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

$('#terminal-connect-button').addEventListener('click', () => {
  const entryId = $('#terminal-machine').value;
  if (entryId) openSession(entryId).catch(error => notice(error.message, true));
});
$('#terminal-fullscreen').addEventListener('click', toggleTerminalFullscreen);
document.addEventListener('fullscreenchange', () => {
  if (document.fullscreenElement !== $('#terminal-workspace') && $('#terminal-workspace').classList.contains('terminal-fullscreen')) setTerminalFullscreen(false);
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !document.fullscreenElement && $('#terminal-workspace').classList.contains('terminal-fullscreen')) setTerminalFullscreen(false);
});
workspaceResizeObserver = new ResizeObserver(() => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(fitActiveTerminal, 80);
});
workspaceResizeObserver.observe($('#terminal-workspace'));
workspaceResizeObserver.observe($('#terminal-panels'));
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(fitActiveTerminal, 100);
});
$('#cancel-edit').addEventListener('click', restoreSavedEntry);
$('#clear-form').addEventListener('click', resetForm);
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
