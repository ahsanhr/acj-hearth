const modal = document.getElementById('modal-view');

// Views
const viewWelcome = document.getElementById('view-welcome');
const viewLogin = document.getElementById('view-login');
const viewSignup = document.getElementById('view-signup');
const viewWelcomeBack = document.getElementById('view-welcome-back');

// Buttons
const btnGotoLogin = document.getElementById('btn-goto-login');
const btnGotoSignup = document.getElementById('btn-goto-signup');
const btnLoginBackWelcome = document.getElementById('btn-login-back-welcome');
const btnSignupBackWelcome = document.getElementById('btn-signup-back-welcome');
const btnEnterHearth = document.getElementById('btn-enter-hearth');

// Form & Inputs
const formSignup = document.getElementById('form-signup');
const inputName = document.getElementById('signup-name');

// Target Elements for Name Injection
const userDisplayName = document.getElementById('user-display-name');
const boardOwnerName = document.getElementById('board-owner-name');

function showSection(targetSection) {
  [viewWelcome, viewLogin, viewSignup].forEach((section) => {
    section.hidden = true;
  });
  targetSection.hidden = false;
}

formSignup.addEventListener('submit', (e) => {
  e.preventDefault();

  const enteredName = inputName.value.trim();
  const fallbackName = enteredName.length > 0 ? enteredName : 'Friend';

  userDisplayName.textContent = fallbackName;
  boardOwnerName.textContent = fallbackName;

  formSignup.reset();

  showSection(viewWelcomeBack);
});

btnEnterHearth.addEventListener('click', () => {
  modal.close();
});

window.addEventListener('DOMContentLoaded', () => {
  modal.showModal();
});

btnGotoLogin.addEventListener('click', () => {
  showSection(viewLogin);
});

btnGotoSignup.addEventListener('click', () => {
  showSection(viewSignup);
});

btnLoginBackWelcome.addEventListener('click', () => {
  showSection(viewWelcome);
});

btnSignupBackWelcome.addEventListener('click', () => {
  showSection(viewWelcome);
});

