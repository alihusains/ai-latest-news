const Story = {
  modal: null,
  open(id) {
    Data.fetch().then(data => {
      const story = Data.getById(id);
      if (!story || !this.modal) return;
      const related = Data.getRelated(story);
      const esc = Data.escape;
      const bullets = (story.summary_original && story.summary_original !== story.summary
        ? story.summary_original : story.summary)
        .split('. ')
        .map(x => x.trim()).filter(x => x.length > 12)
        .slice(0, 4)
        .map(s => `<li>${esc(s)}.</li>`).join('');
      let html = `<div class="story-modal-content">
        <div class="reading-progress" aria-hidden="true"></div>
        <button class="story-modal-close" aria-label="Close">&times;</button>
        ${story.image ? `<img class="story-modal-hero" src="${esc(story.image)}" alt="" loading="lazy">` : ''}
        <div class="story-modal-body">
          <span class="story-modal-category" data-cat="${esc(story.category)}">${esc(story.category)}</span>
          <h1 class="story-modal-title">${esc(story.headline)}</h1>
          ${story.subheadline ? `<p class="story-modal-subtitle">${esc(story.subheadline)}</p>` : ''}
          ${bullets ? `<div class="story-modal-section">
            <h3>In 30 seconds</h3>
            <ul>${bullets}</ul>
          </div>` : ''}
          ${story.why_it_matters ? `<div class="story-modal-section">
            <h3>Why it matters</h3>
            <p>${esc(story.why_it_matters)}</p>
          </div>` : ''}
          <div class="story-modal-section">
            <h3>What happened</h3>
            <p>${esc(story.summary)}</p>
          </div>
          <div class="story-modal-section">
            <h3>Sources</h3>
            <div class="story-modal-sources">
              ${story.sources.map(src => `<div class="story-modal-source">
                <span class="badge">REPORTED</span>
                <a href="${esc(src.url)}" target="_blank" rel="noopener">${esc(src.name)}</a>
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
              ${related.map(r => `<a href="#/story/${esc(r.id)}" data-story-id="${esc(r.id)}">${esc(r.headline)}</a>`).join('')}
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
      const content = this.modal.querySelector('.story-modal-content');
      const bar = this.modal.querySelector('.reading-progress');
      if (content && bar) {
        const onScroll = () => {
          const max = content.scrollHeight - content.clientHeight;
          bar.style.width = (max > 0 ? (content.scrollTop / max) * 100 : 0) + '%';
        };
        content.addEventListener('scroll', onScroll, { passive: true });
        onScroll();
      }
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
