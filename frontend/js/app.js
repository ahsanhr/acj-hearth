import { api, clearSession, login, logout, refreshSession, register } from './api.js';
import { enableNoteMovement, fitCanvas, placeNote } from './notes.js';

const $ = (id) => document.getElementById(id);
const modal = $('modal-view');
let user = null;
let boards = [];
let activeBoard = null;
let loadVersion = 0;
let boardsLoadVersion = 0;
const noteObserver = new ResizeObserver(() => fitCanvas($('lists')));

function showError(error) {
  const target = $(modal.open ? 'auth-error' : 'app-error');
  target.textContent = error.message || 'Unable to connect. Please try again.';
  target.hidden = false;
}

function clearErrors() {
  $('auth-error').hidden = true;
  $('app-error').hidden = true;
}

function showSection(id) {
  ['view-welcome', 'view-login', 'view-signup'].forEach((view) => {
    $(view).hidden = view !== id;
  });
  clearErrors();
}

function showLogin(message) {
  clearSession();
  user = null;
  boards = [];
  activeBoard = null;
  loadVersion += 1;
  boardsLoadVersion += 1;
  $('workspace').hidden = true;
  noteObserver.disconnect();
  $('lists').replaceChildren();
  $('board-cards').replaceChildren();
  $('board-heading').textContent = 'Hearth';
  $('app-status').textContent = '';
  $('invitation-link').value = '';
  if (!modal.open) modal.showModal();
  showSection('view-login');
  if (message) showError(new Error(message));
}

// Disable controls while an operation is pending to prevent duplicate writes.
async function run(container, work) {
  clearErrors();
  const controls = container.matches('button, input, select')
    ? [container]
    : [...container.querySelectorAll('button, input, select, textarea')];
  const enabled = controls.filter((control) => !control.disabled);
  enabled.forEach((control) => { control.disabled = true; });
  try {
    await work();
  } catch (error) {
    showError(error);
  } finally {
    enabled.forEach((control) => { control.disabled = false; });
  }
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function button(text, action) {
  const node = element('button', text, 'pill-btn');
  node.type = 'button';
  node.addEventListener('click', action);
  return node;
}

function field(form, labelText, name, value = '', type = 'text') {
  const label = element('label', labelText);
  const input = element(type === 'textarea' ? 'textarea' : 'input');
  if (type !== 'textarea') input.type = type;
  input.name = name;
  input.value = value || '';
  label.append(input);
  form.append(label);
  return input;
}

function renderTask(task, editable) {
  const row = element('li');
  row.dataset.taskId = task._id;
  const label = element('label', undefined, 'task-label');
  const checkbox = element('input');
  checkbox.type = 'checkbox';
  checkbox.checked = task.completed;
  checkbox.disabled = !editable;
  const title = element('span', task.title);
  title.classList.toggle('completed', task.completed);
  label.append(checkbox, title);
  row.append(label);
  if (task.description) row.append(element('p', task.description));
  if (task.dueDate) row.append(element('p', `Due: ${task.dueDate}`));

  checkbox.addEventListener('change', () => run(checkbox, async () => {
    try {
      const updated = await api(`/tasks/${task._id}`, {
        method: 'PATCH', body: { completed: checkbox.checked },
      });
      task.completed = updated.completed;
      title.classList.toggle('completed', task.completed);
    } catch (error) {
      checkbox.checked = task.completed;
      throw error;
    }
  }));

  if (editable) {
    const editor = element('form', undefined, 'task-editor');
    editor.hidden = true;
    const titleInput = field(editor, 'Title', 'title', task.title);
    titleInput.required = true;
    const description = field(editor, 'Description', 'description', task.description, 'textarea');
    const dueDate = field(editor, 'Due date', 'dueDate', task.dueDate, 'date');
    const save = element('button', 'Save', 'pill-btn');
    save.type = 'submit';
    editor.append(save, button('Cancel', () => { editor.hidden = true; }));
    editor.addEventListener('submit', (event) => {
      event.preventDefault();
      run(editor, async () => {
        const updated = await api(`/tasks/${task._id}`, {
          method: 'PATCH',
          body: {
            title: titleInput.value.trim(),
            description: description.value,
            dueDate: dueDate.value || null,
          },
        });
        row.replaceWith(renderTask(updated, editable));
      });
    });
    row.append(button('Edit', () => { editor.hidden = !editor.hidden; }),
      button('Delete', (event) => {
        if (!window.confirm(`Delete “${task.title}”?`)) return;
        run(event.currentTarget, async () => {
          await api(`/tasks/${task._id}`, { method: 'DELETE' });
          row.remove();
        });
      }), editor);
  }
  return row;
}

function renderList(list, tasks, board) {
  const note = element('section', undefined, 'sticky-note list-note');
  note.dataset.listId = list._id;
  const editable = [list.ownerID, board.createdBy].includes(user.id);
  if (editable) {
    const handle = button('⠿ Move note', () => {});
    handle.className = 'note-handle';
    handle.setAttribute('aria-label', `Move ${list.title}`);
    handle.setAttribute('aria-describedby', 'move-help');
    note.append(handle);
  }
  note.append(element('h2', list.title));
  note.append(element('p', list.ownerID === user.id ? 'Your list' : 'Member’s list'));
  const taskList = element('ul', undefined, 'task-list');
  tasks.forEach((task) => taskList.append(renderTask(task, editable)));
  note.append(taskList);
  if (editable) {
    const form = element('form', undefined, 'task-editor');
    const title = field(form, 'New task', 'title');
    title.required = true;
    const description = field(form, 'Description', 'description', '', 'textarea');
    const dueDate = field(form, 'Due date', 'dueDate', '', 'date');
    const submit = element('button', 'Add task', 'pill-btn');
    submit.type = 'submit';
    form.append(submit);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      run(form, async () => {
        const task = await api(`/lists/${list._id}/tasks/`, {
          method: 'POST',
          body: {
            title: title.value.trim(), description: description.value,
            dueDate: dueDate.value || null,
          },
        });
        taskList.append(renderTask(task, editable));
        form.reset();
      });
    });
    note.append(form);
  }
  return note;
}

async function selectBoard(boardId) {
  boardsLoadVersion += 1;
  const version = ++loadVersion;
  activeBoard = boards.find((board) => board._id === boardId) || null;
  noteObserver.disconnect();
  $('lists').replaceChildren();
  $('invite-result').hidden = true;
  $('invitation-link').value = '';
  $('board-content').hidden = !activeBoard;
  $('home-page').hidden = !!activeBoard;
  $('nav-home').toggleAttribute('aria-current', !activeBoard);
  if (!activeBoard) $('nav-home').setAttribute('aria-current', 'page');
  $('board-select').value = activeBoard?._id || '';
  $('form-list').hidden = true;
  $('btn-invite').hidden = true;
  $('board-heading').textContent = activeBoard?.boardName || 'Your Hearth';
  if (!activeBoard) {
    $('app-status').textContent = '';
    return;
  }
  const board = activeBoard;
  $('app-status').textContent = 'Loading lists…';
  try {
    const lists = await api(`/boards/${board._id}/lists/`);
    const tasks = await Promise.all(lists.map((list) => api(`/lists/${list._id}/tasks/`)));
    if (version !== loadVersion) return;
    $('lists').replaceChildren(...lists.map((list, index) => renderList(list, tasks[index], board)));
    const columnBottoms = [24, 24, 24];
    [...$('lists').children].forEach((note, index) => {
      noteObserver.observe(note);
      const list = lists[index];
      const column = index % 3;
      const position = list.position || { x: 24 + column * 360, y: columnBottoms[column] };
      placeNote(note, position);
      columnBottoms[column] = Math.max(columnBottoms[column], position.y + note.offsetHeight + 32);
      const handle = note.querySelector('.note-handle');
      if (handle) enableNoteMovement(note, handle, position, {
        save: (next) => api(`/lists/${list._id}`, { method: 'PATCH', body: { position: next } }),
        onError: (error) => { if (note.isConnected) showError(error); },
        onStatus: (message) => {
          if (note.isConnected) $('app-status').textContent = message;
        },
      });
    });
    fitCanvas($('lists'));
    $('form-list').hidden = lists.some((list) => list.ownerID === user.id);
    $('btn-invite').hidden = board.createdBy !== user.id;
    $('app-status').textContent = lists.length ? '' : 'No lists yet. Create yours below.';
  } finally {
    if (version === loadVersion && $('app-status').textContent === 'Loading lists…') {
      $('app-status').textContent = '';
    }
  }
}

function routeBoardId() {
  const hash = window.location.hash.slice(1);
  return hash.startsWith('board=') ? new URLSearchParams(hash).get('board') : null;
}

async function showRoute() {
  if (!user) return;
  const id = routeBoardId();
  await selectBoard(id);
  if (id && !activeBoard) {
    window.history.replaceState(null, '', '#home');
    showError(new Error('That board is unavailable or you no longer have access.'));
  }
}

async function navigate(boardId) {
  const hash = boardId ? `#board=${encodeURIComponent(boardId)}` : '#home';
  if (window.location.hash !== hash) window.history.pushState(null, '', hash);
  await showRoute();
}

function renderHome() {
  $('home-empty').hidden = boards.length > 0;
  $('board-cards').replaceChildren(...boards.map((board) => {
    const card = element('a', undefined, 'board-card');
    card.href = `#board=${encodeURIComponent(board._id)}`;
    card.dataset.boardId = board._id;
    card.append(element('h3', board.boardName));
    card.append(element('p', board.createdBy === user.id ? 'Owned by you' : 'Shared with you'));
    card.append(element('span', 'Open board →'));
    return card;
  }));
}

async function loadBoards(preferredId = routeBoardId()) {
  const currentUser = user;
  const version = ++boardsLoadVersion;
  const loaded = await api('/boards/');
  if (user !== currentUser || !user || version !== boardsLoadVersion) return;
  boards = loaded;
  renderHome();
  const homeOption = element('option', 'Choose a board…');
  homeOption.value = '';
  $('board-select').replaceChildren(homeOption, ...boards.map((board) => {
    const option = element('option', board.boardName);
    option.value = board._id;
    return option;
  }));
  $('board-select').disabled = boards.length === 0;
  await navigate(preferredId);
}

async function enterWorkspace() {
  user = await api('/users/me');
  $('user-display-name').textContent = user.name;
  $('workspace').hidden = false;
  modal.close();
  await loadBoards();
}

$('btn-goto-login').addEventListener('click', () => showSection('view-login'));
$('btn-goto-signup').addEventListener('click', () => showSection('view-signup'));
$('btn-login-back-welcome').addEventListener('click', () => showSection('view-welcome'));
$('btn-signup-back-welcome').addEventListener('click', () => showSection('view-welcome'));
modal.addEventListener('cancel', (event) => event.preventDefault());

$('form-login').addEventListener('submit', (event) => {
  event.preventDefault();
  run(event.currentTarget, async () => {
    await login($('login-email').value, $('login-password').value);
    $('form-login').reset();
    await enterWorkspace();
  });
});

$('form-signup').addEventListener('submit', (event) => {
  event.preventDefault();
  run(event.currentTarget, async () => {
    const email = $('signup-email').value;
    const password = $('signup-password').value;
    const name = $('signup-name').value.trim();
    await register(email, password);
    // Registration does not accept a name or create a session.
    $('form-signup').reset();
    showSection('view-login');
    $('login-email').value = email;
    try {
      await login(email, password);
      await api('/users/me', {
        method: 'PATCH', body: { name, current_password: password },
      });
      await enterWorkspace();
    } catch (error) {
      showError(new Error(`Account created. ${error.message} Sign in to continue.`));
    }
  });
});

$('btn-logout').addEventListener('click', (event) => run(event.currentTarget, async () => {
  try {
    await logout();
    window.history.replaceState(null, '', '#home');
    showLogin();
  } catch (error) {
    showLogin('Could not confirm logout on the server. Retry signing in and logging out.');
    throw error;
  }
}));
window.addEventListener('sessionexpired', (event) => {
  showLogin(event.detail.message || 'Your session expired. Please sign in again.');
});

window.addEventListener('hashchange', () => run($('board-select'), showRoute));
$('board-select').addEventListener('change', (event) => {
  run(event.currentTarget, () => navigate(event.target.value));
});
$('btn-refresh').addEventListener('click', (event) => run(event.currentTarget, () => loadBoards()));
$('form-board').addEventListener('submit', (event) => {
  event.preventDefault();
  run(event.currentTarget, async () => {
    const board = await api('/boards/', {
      method: 'POST',
      body: { boardName: $('board-name').value.trim(), createdBy: user.id, members: [] },
    });
    $('form-board').reset();
    await loadBoards(board._id);
  });
});
$('form-list').addEventListener('submit', (event) => {
  event.preventDefault();
  const boardId = activeBoard._id;
  run(event.currentTarget, async () => {
    await api(`/boards/${boardId}/lists/`, {
      method: 'POST', body: { ownerID: user.id, title: $('list-title').value.trim() },
    });
    $('form-list').reset();
    if (activeBoard?._id === boardId) await selectBoard(boardId);
  });
});
$('btn-invite').addEventListener('click', (event) => {
  const boardId = activeBoard._id;
  run(event.currentTarget, async () => {
    const invitation = await api(`/boards/${boardId}/invitations`, { method: 'POST' });
    if (activeBoard?._id !== boardId) return;
    const link = new URL(window.location.pathname, window.location.origin);
    link.searchParams.set('invite', invitation.token);
    link.hash = 'home';
    $('invitation-link').value = link.href;
    $('invite-result').hidden = false;
  });
});
$('form-invitation').addEventListener('submit', (event) => {
  event.preventDefault();
  run(event.currentTarget, async () => {
    let token = $('invitation-token').value.trim();
    if (token.startsWith('https://') || token.startsWith('http://')) {
      token = new URL(token).searchParams.get('invite');
    }
    if (!token) throw new Error('Enter a valid invitation token or link.');
    const result = await api(`/boards/invitations/${encodeURIComponent(token)}/accept`, { method: 'POST' });
    $('form-invitation').reset();
    const url = new URL(window.location.href);
    url.searchParams.delete('invite');
    window.history.replaceState(null, '', url);
    await loadBoards(result.boardID);
  });
});

async function start() {
  const invitation = new URL(window.location.href).searchParams.get('invite');
  if (invitation) $('invitation-token').value = invitation;
  // Do not flash the login dialog while restoring an existing session.
  $('app-status').textContent = 'Restoring session…';
  try {
    await refreshSession();
  } catch (error) {
    showLogin(error.status === 401 ? undefined : error.message);
    if (error.status === 401) showSection('view-welcome');
    return;
  }
  try {
    await enterWorkspace();
  } catch (error) {
    if (!user) showLogin(error.message);
    else showError(error);
  }
}

start();
