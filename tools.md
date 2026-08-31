---
layout: platform
title: Tools
---

<div class="hero">
  <div class="container">
    <h1 class="hero-title">AI Tool of the Day</h1>
    <p class="hero-subtitle">One open-source project and one freemium product worth your time today — picked from Hugging Face, GitHub, Reddit and Product Hunt launches.</p>
  </div>
</div>

<div class="container">
  <div id="tools-duo"></div>
  <div id="tools-list"></div>
</div>

<script>
(function() {
  Data.fetch().then(data => {
    const duo = document.getElementById('tools-duo');
    const list = document.getElementById('tools-list');
    if (!data) { duo.innerHTML = '<div class="error-state"><h2>News could not be refreshed.</h2><p>Try again later.</p></div>'; return; }
    const tools = Data.getToolsOfDay();
    const card = (t, kind, label) => t ? `<div class="feature-card tool-card tool-card--${kind}">
      <div class="feature-label"><span class="tool-badge">${label}</span> AI Tool of the Day</div>
      <h3 class="feature-title"><a href="#/story/${t.id}">${t.headline}</a></h3>
      <p class="feature-summary">${t.subheadline || t.summary.slice(0, 220) + '...'}</p>
      <div class="feature-meta"><span>${t.reading_time}</span><span>${Data.formatDate(t.published_at)}</span><span>${t.sources.map(x => x.name).join(', ')}</span></div>
    </div>` : '';
    const duoHtml = card(tools.freemium, 'fm', 'Freemium') + card(tools.opensource, 'os', 'Open Source');
    if (duoHtml) duo.innerHTML = `<div class="tool-duo">${duoHtml}</div>`;

    const stories = Data.getByCategory('products')
      .filter(s => !s.is_tool_of_day)
      .sort(byNewsFirst);
    if (!stories.length) { if (!duoHtml) list.innerHTML = '<div class="empty-state"><h2>No tool launches yet today.</h2></div>'; return; }
    let html = '<h2 class="section-title" style="margin-top:var(--space-2xl)">More tools &amp; launches</h2><div class="list">';
    stories.forEach(s => {
      html += `<div class="list-item">
        ${s.image ? `<img class="list-item-image" src="${s.image}" alt="" loading="lazy">` : '<div class="list-item-image"></div>'}
        <div class="list-item-body">
          <span class="card-category" data-cat="${s.category}">${s.category}</span>
          <h3 class="list-item-title"><a href="#/story/${s.id}">${s.headline}</a></h3>
          <p class="list-item-summary">${s.subheadline || s.summary.slice(0, 180) + '...'}</p>
          <div class="list-item-meta"><span>${s.reading_time}</span><span>${Data.formatDate(s.published_at)}</span><span>${s.sources.map(x => x.name).join(', ')}</span></div>
        </div>
      </div>`;
    });
    html += '</div>';
    list.innerHTML = html;
    if (window.Reveal) window.Reveal.refresh();
  });
})();
</script>
