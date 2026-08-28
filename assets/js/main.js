document.addEventListener('DOMContentLoaded', () => {
  Story.init();
  const themeToggle = document.querySelector('.theme-toggle');
  if (themeToggle) {
    const stored = localStorage.getItem('signal-theme');
    if (stored) document.documentElement.setAttribute('data-theme', stored);
    themeToggle.addEventListener('click', () => {
      const current = document.documentElement.getAttribute('data-theme');
      const next = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('signal-theme', next);
    });
  }
  const navToggle = document.querySelector('.nav-toggle');
  const mainNav = document.querySelector('.main-nav');
  if (navToggle && mainNav) {
    navToggle.addEventListener('click', () => {
      const expanded = navToggle.getAttribute('aria-expanded') === 'true';
      navToggle.setAttribute('aria-expanded', String(!expanded));
      mainNav.classList.toggle('open');
    });
  }
});
