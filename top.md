---
layout: platform
title: Top AI
---

<div class="hero">
  <div class="container">
    <h1 class="hero-title">Top AI</h1>
    <p class="hero-subtitle">The most important AI developments right now.</p>
    <p class="tier-legend"><span class="chip">Essential</span> must-read &nbsp;·&nbsp; <span class="chip">Major</span> important &nbsp;·&nbsp; ranked by source strength and coverage</p>
  </div>
</div>

<div class="container">
  <div id="top-content"></div>
</div>

<script>
(function() {
  const esc = Data.escape;
  const labels = { 5: 'Essential', 4: 'Major', 3: 'Important' };
  Data.fetch().then(data => {
    const el = document.getElementById('top-content');
    if (!data) { el.innerHTML = '<div class="error-state"><h2>News could not be refreshed.</h2><p>Try again later.</p></div>'; return; }
    const stories = data.stories.filter(s => s.tier === 'top' || s.tier === 'major').sort((a, b) => new Date(b.published_at) - new Date(a.published_at));
    if (!stories.length) { el.innerHTML = '<div class="empty-state"><h2>No major AI developments yet.</h2></div>'; return; }
    let html = '<div class="list">';
    stories.slice(0, 20).forEach(s => {
      const label = labels[s.importance] || 'Important';
      html += `<div class="list-item">
        ${s.image ? `<img class="list-item-image" src="${esc(s.image)}" alt="" loading="lazy">` : '<div class="list-item-image"></div>'}
        <div class="list-item-body">
          <span class="card-category" data-cat="${esc(s.tier)}">${esc(label)}</span>
          <span class="chip">${esc(s.category)}</span>
          <h3 class="list-item-title"><a href="#/story/${esc(s.id)}">${esc(s.headline)}</a></h3>
          <p class="list-item-summary">${esc(s.subheadline || s.summary.slice(0, 180) + '...')}</p>
          <div class="list-item-meta"><span>${esc(s.reading_time)}</span><span>${Data.formatRelative(s.published_at)}</span><span>${s.sources.map(x => esc(x.name)).join(', ')}</span></div>
        </div>
      </div>`;
    });
    html += '</div>';
    if (stories.length > 20) html += `<div class="list-footnote">${stories.length - 20} more stories in the full feed</div>`;
    el.innerHTML = html;
    if (window.Reveal) window.Reveal.refresh();
  });
})();
</script>
