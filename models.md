---
layout: platform
title: Models & Research
---

<div class="hero">
  <div class="container">
    <h1 class="hero-title">Models & Research</h1>
    <p class="hero-subtitle">New models, papers, and breakthroughs in AI research.</p>
  </div>
</div>

<div class="container">
  <div id="models-content"></div>
</div>

<script>
(function() {
  Data.fetch().then(data => {
    if (!data) { document.getElementById('models-content').innerHTML = '<div class="error-state"><h2>News could not be refreshed.</h2><p>Try again later.</p></div>'; return; }
    const stories = Data.getByCategory('models').sort((a, b) => b.importance - a.importance);
    if (!stories.length) { document.getElementById('models-content').innerHTML = '<div class="empty-state"><h2>No major AI developments yet.</h2></div>'; return; }
    let html = '<div class="list">';
    stories.forEach(s => {
      html += `<div class="list-item">
        ${s.image ? `<img class="list-item-image" src="${s.image}" alt="" loading="lazy">` : '<div class="list-item-image" style="background:var(--color-surface-raised)"></div>'}
        <div class="list-item-body">
          <span class="card-category" data-cat="${s.category}">${s.category}</span>
          <h3 class="list-item-title"><a href="#/story/${s.id}">${s.headline}</a></h3>
          <p class="list-item-summary">${s.subheadline || s.summary.slice(0, 180) + '...'}</p>
          <div class="list-item-meta"><span>${s.reading_time}</span><span>·</span><span>${Data.formatDate(s.published_at)}</span><span>·</span><span>${s.sources.map(x => x.name).join(', ')}</span></div>
        </div>
      </div>`;
    });
    html += '</div>';
    document.getElementById('models-content').innerHTML = html;
  });
})();
</script>
