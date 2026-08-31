---
layout: platform
title: Top AI
---

<div class="hero">
  <div class="container">
    <h1 class="hero-title">Top AI</h1>
    <p class="hero-subtitle">The most important AI developments right now.</p>
  </div>
</div>

<div class="container">
  <div id="top-content"></div>
</div>

<script>
(function() {
  const labels = { 5: 'Essential', 4: 'Major', 3: 'Important' };
  Data.fetch().then(data => {
    if (!data) { document.getElementById('top-content').innerHTML = '<div class="error-state"><h2>News could not be refreshed.</h2><p>Try again later.</p></div>'; return; }
    const stories = data.stories.filter(s => s.tier === 'top' || s.tier === 'major').sort((a, b) => new Date(b.published_at) - new Date(a.published_at));
    if (!stories.length) { document.getElementById('top-content').innerHTML = '<div class="empty-state"><h2>No major AI developments yet.</h2></div>'; return; }
    let html = '<div class="list">';
    stories.forEach(s => {
      const label = labels[s.importance] || 'Important';
      html += `<div class="list-item">
        ${s.image ? `<img class="list-item-image" src="${s.image}" alt="" loading="lazy">` : '<div class="list-item-image" style="background:var(--color-surface-raised)"></div>'}
        <div class="list-item-body">
          <span class="card-category" data-cat="${s.tier}">${label}</span>
          <h3 class="list-item-title"><a href="#/story/${s.id}">${s.headline}</a></h3>
          <p class="list-item-summary">${s.subheadline || s.summary.slice(0, 180) + '...'}</p>
          <div class="list-item-meta"><span>${s.reading_time}</span><span>${Data.formatDate(s.published_at)}</span><span>${s.sources.map(x => x.name).join(', ')}</span></div>
        </div>
      </div>`;
    });
    html += '</div>';
    document.getElementById('top-content').innerHTML = html;
  });
})();
</script>
