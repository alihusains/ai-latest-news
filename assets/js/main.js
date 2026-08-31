document.addEventListener('DOMContentLoaded', () => {
  Story.init();

  /* ---- Theme toggle (head script already set the initial data-theme) ---- */
  const themeToggle = document.querySelector('.theme-toggle');
  if (themeToggle) {
    themeToggle.addEventListener('click', () => {
      const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem('signal-theme', next); } catch (e) {}
    });
  }

  /* ---- Mobile nav ---- */
  const navToggle = document.querySelector('.nav-toggle');
  const mainNav = document.querySelector('.main-nav');
  if (navToggle && mainNav) {
    navToggle.addEventListener('click', () => {
      const expanded = navToggle.getAttribute('aria-expanded') === 'true';
      navToggle.setAttribute('aria-expanded', String(!expanded));
      mainNav.classList.toggle('open');
    });
  }

  /* ---- Active nav link ---- */
  const here = location.pathname.replace(/\/index\.html$/, '/').replace(/\/$/, '') || '/';
  document.querySelectorAll('.nav-link').forEach(link => {
    const target = link.getAttribute('href').replace(/\/$/, '') || '/';
    if (target === here) link.classList.add('active');
  });

  /* ---- Edition date ---- */
  const edition = document.getElementById('edition-date');
  if (edition) {
    edition.textContent = new Date().toLocaleDateString('en-US', {
      weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'
    });
  }

  /* ---- Scroll reveal ---- */
  const SELECTORS = '.hero, .section, .signal-box, .subscribe, .feature-card';
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const io = ('IntersectionObserver' in window)
    ? new IntersectionObserver((entries) => {
        entries.forEach(entry => {
          if (entry.isIntersecting) { entry.target.classList.add('in'); io.unobserve(entry.target); }
        });
      }, { rootMargin: '0px 0px -8% 0px', threshold: 0.05 })
    : null;

  window.Reveal = {
    refresh() {
      if (reduce || !io) return;
      document.querySelectorAll(SELECTORS).forEach(el => {
        if (!el.classList.contains('reveal')) el.classList.add('reveal');
        if (!el.classList.contains('in')) io.observe(el);
      });
    }
  };
  window.Reveal.refresh();

  /* ---- Back to top ---- */
  const top = document.getElementById('back-to-top');
  if (top) {
    const onScroll = () => top.classList.toggle('show', window.scrollY > 640);
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
    top.addEventListener('click', () => window.scrollTo({ top: 0, behavior: reduce ? 'auto' : 'smooth' }));
  }
});
