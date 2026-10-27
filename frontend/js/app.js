import { request, login, restoreSession, getProfile, saveName } from './api.js';

const element = (id) => document.getElementById(id);
const modal = element('modal-view');
const formSignup = element('form-signup');
const formLogin = element('form-login');
const views = [
  element('view-welcome'),
  element('view-login'),
  element('view-signup'),
  element('view-welcome-back'),
];

function showSection(id) {
  for (const view of views) view.hidden = view.id !== id;
}

function showAccount(user) {
  element('user-display-name').textContent = user.name;
  element('board-owner-name').textContent = user.name;
  showSection('view-welcome-back');
}

function setBusy(form, busy) {
  for (const control of form.elements) control.disabled = busy;
  form.setAttribute('aria-busy', String(busy));
}

function validateSignupPassword(password) {
  // Count Unicode code points, matching the backend's Python length check.
  const length = Array.from(password).length;
  if (
    length < 15 || length > 128 ||
    !/[0-9]/.test(password) || !/[\p{P}\p{S}]/u.test(password)
  ) {
    throw new Error(
      'Use 15–128 characters, including a digit and punctuation or a symbol.',
    );
  }
}

formSignup.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (formSignup.getAttribute('aria-busy') === 'true') return;

  const name = element('signup-name').value.trim();
  const email = element('signup-email').value.trim();
  const password = element('signup-password').value;
  const status = element('signup-status');
  status.textContent = '';

  try {
    validateSignupPassword(password);
  } catch (error) {
    status.textContent = error.message;
    return;
  }

  setBusy(formSignup, true);
  status.textContent = 'Creating your account…';
  let created = false;

  try {
    await request('/users', {
      method: 'POST',
      body: { email, password },
    });
    created = true;
    formSignup.reset();
    await login(email, password);
    let user = await getProfile();

    if (name) {
      try {
        user = await saveName(name, password);
      } catch (error) {
        if (error.status === 401) throw error;
        showAccount(user);
        element('welcome-status').textContent =
          'Your account was created, but saving your chosen name could not be confirmed.';
        return;
      }
    }

    element('welcome-status').textContent = '';
    showAccount(user);
  } catch (error) {
    if (created) {
      element('login-email').value = email;
      element('login-status').textContent =
        'Your account was created. Please sign in to continue.';
      showSection('view-login');
    } else if (
      error.code === 'network_error' ||
      error.code === 'operation_outcome_unknown'
    ) {
      status.textContent =
        'We could not confirm account creation. Try signing in before submitting again.';
    } else {
      status.textContent = error.message;
    }
  } finally {
    element('signup-password').value = '';
    setBusy(formSignup, false);
  }
});

formLogin.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (formLogin.getAttribute('aria-busy') === 'true') return;

  const email = element('login-email').value.trim();
  const password = element('login-password').value;
  element('login-status').textContent = 'Signing in…';
  setBusy(formLogin, true);

  try {
    await login(email, password);
    const user = await getProfile();
    formLogin.reset();
    element('welcome-status').textContent = '';
    showAccount(user);
  } catch (error) {
    element('login-status').textContent = error.message;
  } finally {
    element('login-password').value = '';
    setBusy(formLogin, false);
  }
});

const navigation = {
  'btn-goto-login': 'view-login',
  'btn-goto-signup': 'view-signup',
  'btn-login-back-welcome': 'view-welcome',
  'btn-signup-back-welcome': 'view-welcome',
};

for (const [buttonId, viewId] of Object.entries(navigation)) {
  element(buttonId).addEventListener('click', () => {
    formLogin.reset();
    formSignup.reset();
    element('login-status').textContent = '';
    element('signup-status').textContent = '';
    showSection(viewId);
  });
}

element('btn-enter-hearth').addEventListener('click', () => modal.close());

async function initialize() {
  showSection('view-welcome');
  modal.showModal();
  const buttons = [element('btn-goto-login'), element('btn-goto-signup')];
  buttons.forEach((button) => { button.disabled = true; });
  element('welcome-session-status').textContent = 'Checking your session…';

  try {
    await restoreSession();
    showAccount(await getProfile());
  } catch (error) {
    showSection('view-welcome');
    if (error.code === 'reauthentication_required') {
      element('login-status').textContent = error.message;
      showSection('view-login');
    } else if (error.status !== 401) {
      element('welcome-session-status').textContent = error.message;
    }
  } finally {
    if (element('welcome-session-status').textContent === 'Checking your session…') {
      element('welcome-session-status').textContent = '';
    }
    buttons.forEach((button) => { button.disabled = false; });
  }
}

initialize();
