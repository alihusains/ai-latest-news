---
layout: platform
title: Brief
---

<div class="hero">
  <div class="container">
    <p class="eyebrow" style="--dot:var(--color-accent)">The Brief</p>
    <h1 class="hero-title">Today, in five minutes.</h1>
    <p id="brief-subtitle" class="hero-subtitle">Loading your briefing…</p>
  </div>
</div>

<div class="container">
  <div id="brief-content"></div>
  {% include subscribe.html %}
</div>

<script>
(function() {
  const esc = Data.escape;
  Data.fetch().then(data => {
    if (!data) { document.getElementById('brief-content').innerHTML = '<div class="error-state"><h2>News could not be refreshed.</h2><p>Try again later.</p></div>'; return; }
    const top = Data.getTop();
    const topStory = top[0];
    const highlights = data.stories.filter(s => s.tier === 'major' || s.tier === 'top').slice(0, 7);
    const early = data.stories.filter(s => s.is_early_signal);
    const sub = document.getElementById('brief-subtitle');
    if (sub) sub.textContent = data.stories.length + ' developments, ranked by what will actually matter. ' +
      (data.stats && data.stats.reading_time_min ? 'About ' + data.stats.reading_time_min + ' minutes of reading.' : '');
    let html = '';
    if (topStory) {
      html += `<div class="section"><div class="section-header"><h2 class="section-title">The Big Story</h2></div>
        <div class="card">
          ${topStory.image ? `<img class="card-image" src="${esc(topStory.image)}" alt="" loading="lazy" style="aspect-ratio:21/9;max-height:360px">` : ''}
          <div class="card-body">
            <span class="card-category" data-cat="${esc(topStory.category)}">${esc(topStory.category)}</span>
            <h2 class="card-title" style="font-size:var(--text-section)"><a href="#/story/${esc(topStory.id)}">${esc(topStory.headline)}</a></h2>
            <p class="card-subtitle">${esc(topStory.subheadline || '')}</p>
            ${topStory.why_it_matters ? `<p style="color:var(--color-text-secondary);line-height:1.6;margin:0 0 var(--space-md)">${esc(topStory.why_it_matters)}</p>` : ''}
            <div class="card-meta"><span>${esc(topStory.reading_time)}</span><span>${Data.formatDate(topStory.published_at)}</span><span>${topStory.sources.map(x => esc(x.name)).join(', ')}</span></div>
          </div>
        </div></div>`;
    }
    html += `<div class="section"><div class="section-header"><h2 class="section-title">5 Things You Should Know</h2></div><div class="brief-five">`;
    highlights.slice(1, 6).forEach((s, i) => {
      html += `<a class="brief-five-item" href="#/story/${esc(s.id)}">
        <span class="brief-five-num">${i + 1}</span>
        <span class="brief-five-body">
          <span class="card-category" data-cat="${esc(s.category)}">${esc(s.category)}</span>
          <h3 class="list-item-title">${esc(s.headline)}</h3>
          <p class="list-item-summary">${esc(s.subheadline || s.summary.slice(0, 160) + '…')}</p>
        </span>
      </a>`;
    });
    html += '</div></div>';
    if (early.length) {
      html += `<div class="section"><div class="section-header"><h2 class="section-title">Early Signal</h2><span class="section-note">Young stories worth tracking</span></div><div class="list">`;
      early.forEach(s => { html += `<div class="list-item"><div class="list-item-body"><span class="card-category" data-cat="${esc(s.category)}">${esc(s.category)}</span><h3 class="list-item-title"><a href="#/story/${esc(s.id)}">${esc(s.headline)}</a></h3><p class="list-item-summary">${esc(s.why_it_matters)}</p></div></div>`; });
      html += '</div></div>';
    }
    const future = data.stories.filter(s => /will|next week|next month|upcoming|expected|set to|plans to|scheduled/i.test((s.headline || '') + ' ' + (s.summary || ''))).slice(0, 3);
    html += `<div class="section"><div class="section-header"><h2 class="section-title">What's Next</h2></div>
      <div class="signal-box"><div class="signal-grid" style="grid-template-columns:1fr">
        ${future.map(s => `<div class="signal-item"><h4>On the horizon</h4><p><a href="#/story/${esc(s.id)}">${esc(s.headline)}</a></p></div>`).join('') || '<div class="signal-item"><h4>On the horizon</h4><p>Nothing flagged for the coming days yet.</p></div>'}
      </div></div></div>`;
    const el = document.getElementById('brief-content');
    el.innerHTML = html;
    if (window.Reveal) window.Reveal.refresh();
  });
})();
</script>
