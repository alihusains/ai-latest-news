---
layout: platform
title: Business & Infrastructure
---

<div class="hero">
  <div class="container">
    <h1 class="hero-title">Business & Infrastructure</h1>
    <p class="hero-subtitle">Deals, policy, compute, and the economics of AI.</p>
  </div>
</div>

<div class="container">
  <div id="business-content"></div>
</div>

<script>
(function() {
  Data.fetch().then(data => {
    if (!data) { document.getElementById('business-content').innerHTML = '<div class="error-state"><h2>News could not be refreshed.</h2><p>Try again later.</p></div>'; return; }
    const stories = Data.getByCategory('business').sort(byNewsFirst);
    if (!stories.length) { document.getElementById('business-content').innerHTML = '<div class="empty-state"><h2>No major AI developments yet.</h2></div>'; return; }
    let html = '<div class="list">';
    stories.forEach(s => {
      const who = (s.industry || []).slice(0, 2).join(', ');
      const what = s.story_type || 'Development';
      html += `<div class="list-item">
        ${s.image ? `<img class="list-item-image" src="${s.image}" alt="" loading="lazy">` : '<div class="list-item-image" style="background:var(--color-surface-raised)"></div>'}
        <div class="list-item-body">
          <span class="card-category" data-cat="${s.category}">${s.category}</span>
          <h3 class="list-item-title"><a href="#/story/${s.id}">${s.headline}</a></h3>
          <p class="list-item-summary">${s.subheadline || s.summary.slice(0, 180) + '...'}</p>
          <div class="list-item-meta">
            <span><strong>Who:</strong> ${who || '—'}</span>
            <span><strong>What:</strong> ${what}</span>
            <span>${s.reading_time}</span>
          </div>
        </div>
      </div>`;
    });
    html += '</div>';
    document.getElementById('business-content').innerHTML = html;
  });
})();
</script>
