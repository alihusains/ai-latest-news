---
layout: platform
title: At a Glance
---

<div class="hero">
  <div class="container">
    <h1 class="hero-title">At a Glance</h1>
    <p id="glance-stats" class="hero-subtitle">Loading...</p>
  </div>
</div>

<div class="container">
  <div id="glance-content"></div>
</div>

<script>
(function() {
  const layouts = ['full', 'split', 'split-reverse', 'compact'];
  let layoutIndex = 0;
  const nextLayout = () => layouts[layoutIndex++ % layouts.length];

  const render = {
    biggest(s) {
      return `<div class="card" style="margin-bottom:var(--space-2xl)">
        ${s.image ? `<img class="card-image" src="${s.image}" alt="" loading="lazy" style="aspect-ratio:21/9;max-height:420px">` : ''}
        <div class="card-body">
          <span class="card-category" data-cat="${s.category}">${s.category}</span>
          <h2 class="card-title" style="font-size:var(--text-section)"><a href="#/story/${s.id}">${s.headline}</a></h2>
          <p class="card-subtitle">${s.subheadline || ''}</p>
          <p style="color:var(--color-text-secondary);line-height:1.6;margin:0 0 var(--space-md)">${s.why_it_matters}</p>
          <div class="card-meta">
            <span>${s.reading_time}</span>
            <span>${Data.formatDate(s.published_at)}</span>
            <span>${s.sources.map(x => x.name).join(', ')}</span>
          </div>
        </div>
      </div>`;
    },
    card(s) {
      const layout = nextLayout();
      if (layout === 'full') return `<div class="card" style="margin-bottom:var(--space-lg)">${s.image ? `<img class="card-image" src="${s.image}" alt="" loading="lazy">` : ''}<div class="card-body"><span class="card-category" data-cat="${s.category}">${s.category}</span><h3 class="card-title"><a href="#/story/${s.id}">${s.headline}</a></h3><p class="card-subtitle">${s.subheadline || ''}</p><p style="color:var(--color-text-secondary);line-height:1.5;margin:0 0 var(--space-sm)">${s.why_it_matters}</p><div class="card-meta"><span>${s.reading_time}</span><span>${Data.formatDate(s.published_at)}</span><span>${s.sources.map(x => x.name).join(', ')}</span></div></div></div>`;
      if (layout === 'split') return `<div class="card card--split" style="margin-bottom:var(--space-lg)"><div class="card-body"><span class="card-category" data-cat="${s.category}">${s.category}</span><h3 class="card-title"><a href="#/story/${s.id}">${s.headline}</a></h3><p class="card-subtitle">${s.subheadline || ''}</p><p style="color:var(--color-text-secondary);line-height:1.5;margin:0 0 var(--space-sm)">${s.why_it_matters}</p><div class="card-meta"><span>${s.reading_time}</span><span>${Data.formatDate(s.published_at)}</span></div></div>${s.image ? `<img class="card-image" src="${s.image}" alt="" loading="lazy">` : ''}</div>`;
      if (layout === 'split-reverse') return `<div class="card card--split-reverse" style="margin-bottom:var(--space-lg)">${s.image ? `<img class="card-image" src="${s.image}" alt="" loading="lazy">` : ''}<div class="card-body"><span class="card-category" data-cat="${s.category}">${s.category}</span><h3 class="card-title"><a href="#/story/${s.id}">${s.headline}</a></h3><p class="card-subtitle">${s.subheadline || ''}</p><p style="color:var(--color-text-secondary);line-height:1.5;margin:0 0 var(--space-sm)">${s.why_it_matters}</p><div class="card-meta"><span>${s.reading_time}</span><span>${Data.formatDate(s.published_at)}</span></div></div></div>`;
      return `<div class="card card--compact" style="margin-bottom:var(--space-lg)">${s.image ? `<img class="card-image" src="${s.image}" alt="" loading="lazy">` : ''}<div class="card-body"><span class="card-category" data-cat="${s.category}">${s.category}</span><h3 class="card-title"><a href="#/story/${s.id}">${s.headline}</a></h3><p class="card-subtitle">${s.subheadline || ''}</p><div class="card-meta"><span>${s.reading_time}</span><span>${Data.formatDate(s.published_at)}</span></div></div></div>`;
    },
    group(title, stories) {
      if (!stories.length) return '';
      return `<div class="section"><div class="section-header"><h2 class="section-title">${title}</h2></div><div>${stories.map(s => this.card(s)).join('')}</div></div>`;
    }
  };

  Data.fetch().then(data => {
    if (!data) { document.getElementById('glance-content').innerHTML = '<div class="error-state"><h2>News could not be refreshed.</h2><p>Try again later.</p></div>'; return; }
    const stats = data.stats || {};
    document.getElementById('glance-stats').textContent = `${data.stories.length} significant developments · ~${stats.reading_time_min || 16} min read`;
    const top = Data.getTop();
    const major = Data.getMajor();
    const whatChanged = [...top, ...major].slice(0, 5);
    const agents = Data.getByCategory('agents').filter(s => s.tier !== 'top');
    const models = Data.getByCategory('models').filter(s => s.tier !== 'top');
    const products = Data.getByCategory('products').filter(s => s.tier !== 'top');
    const business = Data.getByCategory('business').filter(s => s.tier !== 'top');
    const worth = data.stories.filter(s => s.tier === 'standard');
    let html = '';
    if (top.length) html += `<div class="section"><div class="section-header"><h2 class="section-title">The Biggest Story</h2></div>${render.biggest(top[0])}</div>`;
    html += render.group('What Changed', whatChanged);
    if (agents.length) html += render.group('Agents', agents);
    if (models.length) html += render.group('Models & Research', models);
    if (products.length) html += render.group('Products & Open Source', products);
    if (business.length) html += render.group('Business & Infrastructure', business);
    if (worth.length) html += render.group('Worth Knowing', worth);
    document.getElementById('glance-content').innerHTML = html;
  });
})();
</script>
