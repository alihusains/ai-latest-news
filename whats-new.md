---
layout: platform
title: What's New
---

<div class="hero">
  <div class="container">
    <h1 class="hero-title">What's New in AI</h1>
    <p class="hero-subtitle">Every launch, release, update and open-source drop the pipeline saw today — newest first.</p>
  </div>
</div>

<div class="container">
  <div id="whats-new-content"></div>
</div>

<script>
(function() {
  const esc = Data.escape;
  Data.fetch().then(data => {
    const el = document.getElementById('whats-new-content');
    if (!data) { el.innerHTML = '<div class="error-state"><h2>News could not be refreshed.</h2><p>Try again later.</p></div>'; return; }
    const stories = Data.getWhatsNew();
    if (!stories.length) { el.innerHTML = '<div class="empty-state"><h2>Nothing new yet today.</h2></div>'; return; }
    let html = '<div class="list">';
    stories.slice(0, 20).forEach(s => {
      html += `<div class="list-item">
        ${s.image ? `<img class="list-item-image" src="${esc(s.image)}" alt="" loading="lazy">` : '<div class="list-item-image"></div>'}
        <div class="list-item-body">
          <span class="card-category" data-cat="${esc(s.category)}">${esc(s.story_type || s.category)}</span>
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
