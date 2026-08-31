---
layout: platform
title: Products & Open Source
---

<div class="hero">
  <div class="container">
    <h1 class="hero-title">Products & Open Source</h1>
    <p class="hero-subtitle">Tools, apps, hardware, and open-source releases shaping how we use AI.</p>
  </div>
</div>

<div class="container">
  <div class="section">
    <div class="section-header">
      <h2 class="section-title">Filter</h2>
    </div>
    <div class="filter-tabs" role="tablist">
      <button class="filter-btn active" data-filter="all">All</button>
      <button class="filter-btn" data-filter="open">Open Source</button>
      <button class="filter-btn" data-filter="premium">Premium</button>
      <button class="filter-btn" data-filter="tool">Tool of the Day</button>
      <button class="filter-btn" data-filter="dev">Developer</button>
    </div>
  </div>

  <div id="repo-radar" class="section" style="display:none">
    <div class="section-header"><h2 class="section-title">AI Repo Radar</h2></div>
    <div id="repo-grid" class="grid grid--3"></div>
  </div>

  <div id="products-content"></div>
</div>

<script>
(function() {
  const repoTypes = new Set(['Repository', 'Open Source']);
  Data.fetch().then(data => {
    if (!data) { document.getElementById('products-content').innerHTML = '<div class="error-state"><h2>News could not be refreshed.</h2><p>Try again later.</p></div>'; return; }
    let stories = Data.getByCategory('products').sort((a, b) => b.importance - a.importance);
    const repos = stories.filter(s => repoTypes.has(s.story_type));
    stories = stories.filter(s => !repoTypes.has(s.story_type));
    if (repos.length) {
      document.getElementById('repo-radar').style.display = 'block';
      const labels = { 5: 'Breakout', 4: 'Rising', 3: 'New' };
      document.getElementById('repo-grid').innerHTML = repos.map(s => `<div class="card">
        ${s.image ? `<img class="card-image" src="${s.image}" alt="" loading="lazy">` : ''}
        <div class="card-body">
          <span class="card-category" data-cat="models">${labels[s.importance] || 'New'}</span>
          <h3 class="card-title"><a href="#/story/${s.id}">${s.headline}</a></h3>
          <p class="card-subtitle">${s.subheadline || ''}</p>
          <div class="card-meta"><span>${s.reading_time}</span><span>${Data.formatDate(s.published_at)}</span></div>
        </div>
      </div>`).join('');
    }
    const tool = Data.getToolOfDay();
    const toolHtml = tool ? `<div class="feature-card">
      <div class="feature-label">AI Tool of the Day</div>
      <h3 class="feature-title"><a href="#/story/${tool.id}">${tool.headline}</a></h3>
      <p class="feature-summary">${tool.subheadline || tool.summary.slice(0, 200) + '...'}</p>
      <div class="feature-meta">${tool.reading_time} · ${Data.formatDate(tool.published_at)}</div>
    </div>` : '';
    document.getElementById('products-content').innerHTML = toolHtml + '<div id="products-feed" class="list mt-lg"></div>';
    const renderItem = s => `<div class="list-item" data-tags="${(s.tags || []).join(',')}" data-tool="${s.is_tool_of_day ? '1' : '0'}" data-type="${s.story_type || ''}">
      ${s.image ? `<img class="list-item-image" src="${s.image}" alt="" loading="lazy">` : '<div class="list-item-image" style="background:var(--color-surface-raised)"></div>'}
      <div class="list-item-body">
        <span class="card-category" data-cat="${s.category}">${s.category}</span>
        <h3 class="list-item-title"><a href="#/story/${s.id}">${s.headline}</a></h3>
        <p class="list-item-summary">${s.subheadline || s.summary.slice(0, 180) + '...'}</p>
        <div class="list-item-meta"><span>${s.reading_time}</span><span>${Data.formatDate(s.published_at)}</span><span>${s.sources.map(x => x.name).join(', ')}</span></div>
      </div>
    </div>`;
    const feed = document.getElementById('products-feed');
    feed.innerHTML = stories.map(renderItem).join('');
    const filterMap = { all: () => true, open: s => (s.tags || []).includes('Open Source'), premium: s => s.tier === 'top' || s.tier === 'major', tool: s => s.is_tool_of_day, dev: s => ['Repository', 'Open Source', 'Developer'].includes(s.story_type) };
    document.querySelectorAll('.filter-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const f = btn.dataset.filter;
        const test = filterMap[f] || (() => true);
        feed.querySelectorAll('.list-item').forEach(el => {
          const tags = el.dataset.tags.split(',');
          const obj = { tags, is_tool_of_day: el.dataset.tool === '1', story_type: el.dataset.type };
          el.style.display = test(obj) ? '' : 'none';
        });
      });
    });
  });
})();
</script>
