const Search = {
  overlay: null,
  input: null,
  results: null,
  open() {
    this.overlay = document.getElementById('search-overlay');
    this.input = document.getElementById('search-input');
    this.results = document.getElementById('search-results');
    if (!this.overlay) return;
    this.overlay.classList.add('open');
    this.input.value = '';
    this.input.focus();
    this.render([], '');
    document.addEventListener('keydown', this._onKey);
  },
  close() {
    if (!this.overlay) return;
    this.overlay.classList.remove('open');
    document.removeEventListener('keydown', this._onKey);
  },
  _onKey(e) {
    if (e.key === 'Escape') this.close();
  },
  async query(q) {
    const data = await Data.fetch();
    if (!data) return [];
    const term = q.toLowerCase().trim();
    if (!term) return [];
    const results = [];
    data.stories.forEach(s => {
      const text = [s.headline, s.subheadline, s.summary, ...s.tags].join(' ').toLowerCase();
      if (text.includes(term)) {
        results.push({ story: s, score: text.split(term).length });
      }
    });
    results.sort((a, b) => b.score - a.score);
    return results.slice(0, 20);
  },
  async render(results, q) {
    if (!this.results) return;
    if (!q) { this.results.innerHTML = '<div class="search-empty">Type to search stories...</div>'; return; }
    if (results.length === 0) { this.results.innerHTML = '<div class="search-empty">No results found.</div>'; return; }
    const grouped = {};
    results.forEach(r => {
      const cat = r.story.category || 'other';
      if (!grouped[cat]) grouped[cat] = [];
      grouped[cat].push(r);
    });
    let html = '';
    Object.keys(grouped).sort().forEach(cat => {
      html += `<div class="search-group-title">${cat}</div>`;
      grouped[cat].forEach(r => {
        html += `<div class="search-result-item" data-id="${r.story.id}">
          <div class="search-result-title">${this.escape(r.story.headline)}</div>
          <div class="search-result-meta">${r.story.reading_time || ''} · ${Data.formatDate(r.story.published_at)}</div>
        </div>`;
      });
    });
    this.results.innerHTML = html;
    this.results.querySelectorAll('.search-result-item').forEach(el => {
      el.addEventListener('click', () => {
        this.close();
        Story.open(el.dataset.id);
      });
    });
  },
  escape(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }
};

document.addEventListener('DOMContentLoaded', () => {
  const searchToggle = document.querySelector('.search-toggle');
  if (searchToggle) searchToggle.addEventListener('click', () => Search.open());
  const searchOverlay = document.getElementById('search-overlay');
  if (searchOverlay) {
    searchOverlay.addEventListener('click', e => { if (e.target === searchOverlay) Search.close(); });
    const input = document.getElementById('search-input');
    if (input) {
      input.addEventListener('input', e => {
        const q = e.target.value;
        Search.query(q).then(results => Search.render(results, q));
      });
    }
  }
  document.addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); Search.open(); }
  });
});
