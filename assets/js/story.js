const Story = {
  modal: null,
  open(id) {
    Data.fetch().then(data => {
      const story = Data.getById(id);
      if (!story || !this.modal) return;
      const related = Data.getRelated(story);
      const catClass = `card-category[data-cat="${story.category}"]`;
      let html = `<div class="story-modal-content">
        <button class="story-modal-close" aria-label="Close">&times;</button>
        ${story.image ? `<img class="story-modal-hero" src="${story.image}" alt="" loading="lazy">` : ''}
        <div class="story-modal-body">
          <span class="story-modal-category ${catClass}" data-cat="${story.category}">${story.category}</span>
          <h1 class="story-modal-title">${story.headline}</h1>
          ${story.subheadline ? `<p class="story-modal-subtitle">${story.subheadline}</p>` : ''}
          <div class="story-modal-section">
            <h3>In 30 seconds</h3>
            <ul>${story.summary.split('. ').filter(s => s.trim()).map(s => `<li>${s.trim()}.</li>`).join('')}</ul>
          </div>
          <div class="story-modal-section">
            <h3>Why it matters</h3>
            <p>${story.why_it_matters}</p>
          </div>
          <div class="story-modal-section">
            <h3>What happened</h3>
            <p>${story.summary}</p>
          </div>
          <div class="story-modal-section">
            <h3>Sources</h3>
            <div class="story-modal-sources">
              ${story.sources.map(src => `<div class="story-modal-source">
                <span class="badge">REPORTED</span>
                <a href="${src.url}" target="_blank" rel="noopener">${src.name}</a>
                <span>· ${Data.formatDate(src.published)}</span>
              </div>`).join('')}
              <div class="story-modal-source">
                <span class="badge">AI SYNTHESIS</span>
                <span>Summary generated from ${story.source_count} source${story.source_count !== 1 ? 's' : ''}</span>
              </div>
            </div>
          </div>
          ${related.length ? `<div class="story-modal-section">
            <h3>Related</h3>
            <div class="story-modal-related">
              ${related.map(r => `<a href="#/story/${r.id}" data-story-id="${r.id}">${r.headline}</a>`).join('')}
            </div>
          </div>` : ''}
        </div>
      </div>`;
      this.modal.innerHTML = html;
      this.modal.classList.add('open');
      this.modal.querySelector('.story-modal-close').addEventListener('click', () => this.close());
      this.modal.querySelectorAll('[data-story-id]').forEach(el => {
        el.addEventListener('click', e => { e.preventDefault(); this.open(el.dataset.storyId); });
      });
      this.modal.addEventListener('click', e => { if (e.target === this.modal) this.close(); });
      history.pushState(null, '', `#/story/${id}`);
    });
  },
  close() {
    if (!this.modal) return;
    this.modal.classList.remove('open');
    history.pushState(null, '', window.location.pathname + window.location.search);
  },
  init() {
    this.modal = document.getElementById('story-modal');
    if (!this.modal) return;
    window.addEventListener('hashchange', () => {
      const hash = window.location.hash;
      if (hash.startsWith('#/story/')) { this.open(hash.replace('#/story/', '')); }
      else { this.close(); }
    });
    if (window.location.hash.startsWith('#/story/')) { this.open(window.location.hash.replace('#/story/', '')); }
  }
};
