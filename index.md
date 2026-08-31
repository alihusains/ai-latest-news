---
layout: platform
title: Home
---

<div id="home-hero" class="hero">
  <div class="container">
    <div id="hero-content">
      <div class="skeleton skeleton-title"></div>
      <div class="skeleton skeleton-text"></div>
      <div class="skeleton skeleton-text" style="width:60%"></div>
    </div>
  </div>
</div>

<div class="container">
  <div id="signal-box" class="signal-box" style="display:none"></div>

  <div id="section-top" class="section" style="display:none">
    <div class="section-header">
      <h2 class="section-title">Top AI</h2>
      <a href="/top" class="section-link">View all →</a>
    </div>
    <div id="top-grid" class="grid grid--2"></div>
  </div>

  <div id="section-agents" class="section" style="display:none">
    <div class="section-header">
      <h2 class="section-title">Agents</h2>
      <a href="/agents" class="section-link">View all →</a>
    </div>
    <div id="agents-list" class="list"></div>
  </div>

  <div id="section-models" class="section" style="display:none">
    <div class="section-header">
      <h2 class="section-title">Models & Research</h2>
      <a href="/models" class="section-link">View all →</a>
    </div>
    <div id="models-list" class="list"></div>
  </div>

  <div id="section-products" class="section" style="display:none">
    <div class="section-header">
      <h2 class="section-title">Products & Open Source</h2>
      <a href="/products" class="section-link">View all →</a>
    </div>
    <div id="products-feature"></div>
    <div id="products-list" class="list mt-lg"></div>
  </div>

  <div id="section-newagents" class="section" style="display:none">
    <div class="section-header">
      <h2 class="section-title">New AI Agents</h2>
      <a href="/new-agents" class="section-link">View all →</a>
    </div>
    <div id="newagents-list" class="list"></div>
  </div>

  <div id="section-business" class="section" style="display:none">
    <div class="section-header">
      <h2 class="section-title">Business & Infrastructure</h2>
      <a href="/business" class="section-link">View all →</a>
    </div>
    <div id="business-list" class="list"></div>
  </div>

  <div id="section-early" class="section" style="display:none">
    <div class="section-header">
      <h2 class="section-title">Early Signal</h2>
    </div>
    <div id="early-list" class="list"></div>
  </div>

  {% include subscribe.html %}
</div>

<script>
(function() {
  const render = {
    hero(list) {
      const s = list[0];
      const sec = list.slice(1, 4);
      const lead = `<article class="hero-lead">
        <p class="eyebrow" style="--dot:var(--cat-${s.category}, var(--color-accent))">${s.category}</p>
        <h1 class="hero-title"><a href="#/story/${s.id}">${s.headline}</a></h1>
        <p class="hero-subtitle">${s.subheadline || s.summary.slice(0, 160) + '…'}</p>
        <div class="hero-meta"><span>${s.reading_time}</span><span>${Data.formatDate(s.published_at)}</span><span>${s.sources.map(x => x.name).join(', ')}</span></div>
        <div class="hero-cta"><a class="btn-solid" href="#/story/${s.id}">Read the story →</a></div>
      </article>`;
      const aside = sec.length ? `<aside class="hero-secondary">
        <p class="eyebrow eyebrow--plain">Also leading</p>
        ${sec.map(x => `<div class="hero-sec-item">
          <span class="card-category" data-cat="${x.category}">${x.category}</span>
          <h3 class="hero-sec-title"><a href="#/story/${x.id}">${x.headline}</a></h3>
          <div class="hero-sec-meta">${x.reading_time} · ${Data.formatDate(x.published_at)}</div>
        </div>`).join('')}
      </aside>` : '';
      return `<div class="hero-grid">${lead}${aside}</div>`;
    },
    card(s, variant) {
      const img = s.image ? `<img class="card-image" src="${s.image}" alt="" loading="lazy">` : '';
      const body = `<div class="card-body">
        <span class="card-category" data-cat="${s.category}">${s.category}</span>
        <h3 class="card-title"><a href="#/story/${s.id}">${s.headline}</a></h3>
        <p class="card-subtitle">${s.subheadline || ''}</p>
        <div class="card-meta">
          <span>${s.reading_time}</span>
          <span>${Data.formatDate(s.published_at)}</span>
          <span>${s.sources.map(x => x.name).join(', ')}</span>
        </div>
      </div>`;
      if (variant === 'split') return `<div class="card card--split">${body}${img}</div>`;
      if (variant === 'split-reverse') return `<div class="card card--split-reverse">${img}${body}</div>`;
      return `<div class="card">${img}${body}</div>`;
    },
    listItem(s) {
      const img = s.image ? `<img class="list-item-image" src="${s.image}" alt="" loading="lazy">` : '';
      return `<div class="list-item">
        ${img}
        <div class="list-item-body">
          <span class="card-category" data-cat="${s.category}">${s.category}</span>
          <h3 class="list-item-title"><a href="#/story/${s.id}">${s.headline}</a></h3>
          <p class="list-item-summary">${s.subheadline || s.summary.slice(0, 180) + '...'}</p>
          <div class="list-item-meta">
            <span>${s.reading_time}</span>
            <span>${Data.formatDate(s.published_at)}</span>
            <span>${s.sources.map(x => x.name).join(', ')}</span>
          </div>
        </div>
      </div>`;
    }
  };

  Data.fetch().then(data => {
    if (!data) { document.getElementById('home-hero').innerHTML = '<div class="empty-state"><h2>News could not be refreshed.</h2><p>Try again later.</p></div>'; return; }
    const top = Data.getTop();
    const major = Data.getMajor();
    const agents = Data.getByCategory('agents').filter(s => s.tier !== 'top').sort((a, b) => new Date(b.published_at) - new Date(a.published_at));
    const models = Data.getByCategory('models').filter(s => s.tier !== 'top').sort((a, b) => new Date(b.published_at) - new Date(a.published_at));
    const products = Data.getByCategory('products').filter(s => s.tier !== 'top').sort((a, b) => new Date(b.published_at) - new Date(a.published_at));
    const business = Data.getByCategory('business').filter(s => s.tier !== 'top').sort((a, b) => new Date(b.published_at) - new Date(a.published_at));
    const early = data.stories.filter(s => s.is_early_signal && s.tier !== 'top');
    const tools = Data.getToolsOfDay();
    const newAgents = Data.getNewAgents().filter(s => s.tier !== 'top').slice(0, 4);

    if (top.length) {
      const hero = document.getElementById('home-hero');
      hero.querySelector('.container').innerHTML = render.hero(top);
      hero.style.borderBottom = '1px solid var(--color-border)';
      hero.style.paddingBottom = 'var(--space-2xl)';
    }

    const stats = data.stats || {};
    const total = data.stories.length;
    const mins = stats.reading_time_min || 16;
    document.getElementById('signal-box').innerHTML = `<h2 class="signal-box-title">Today's AI Signal</h2>
      <div class="signal-grid">
        <div class="signal-item"><h4>What changed</h4><p>${total} significant developments across agents, models, products, and business.</p></div>
        <div class="signal-item"><h4>Why it matters</h4><p>Frontier labs are scaling infrastructure while grappling with governance gaps. The tension between capability and safety is the story of the week.</p></div>
        <div class="signal-item"><h4>What happens next</h4><p>Watch for Anthropic's Nscale compute ramp, OpenAI's agent safety follow-up, and Chinese labs' price responses.</p></div>
      </div>`;
    document.getElementById('signal-box').style.display = 'block';

    if (top.length) {
      document.getElementById('section-top').style.display = 'block';
      document.getElementById('top-grid').innerHTML = top.slice(0, 3).map(s => render.card(s, 'split')).join('');
    }

    if (agents.length) {
      document.getElementById('section-agents').style.display = 'block';
      document.getElementById('agents-list').innerHTML = agents.slice(0, 5).map(s => render.listItem(s)).join('');
    }

    if (models.length) {
      document.getElementById('section-models').style.display = 'block';
      document.getElementById('models-list').innerHTML = models.slice(0, 5).map(s => render.listItem(s)).join('');
    }

    if (products.length) {
      document.getElementById('section-products').style.display = 'block';
      const toolCard = (t, kind, label) => t ? `<div class="feature-card tool-card tool-card--${kind}">
        <div class="feature-label"><span class="tool-badge">${label}</span> AI Tool of the Day</div>
        <h3 class="feature-title"><a href="#/story/${t.id}">${t.headline}</a></h3>
        <p class="feature-summary">${t.subheadline || t.summary.slice(0, 200) + '...'}</p>
        <div class="feature-meta">${t.reading_time} · ${Data.formatDate(t.published_at)}</div>
      </div>` : '';
      const duo = toolCard(tools.freemium, 'fm', 'Freemium') + toolCard(tools.opensource, 'os', 'Open Source');
      if (duo) document.getElementById('products-feature').innerHTML = `<div class="tool-duo">${duo}</div>`;
      document.getElementById('products-list').innerHTML = products.slice(0, 5).map(s => render.listItem(s)).join('');
    }

    if (newAgents.length) {
      document.getElementById('section-newagents').style.display = 'block';
      document.getElementById('newagents-list').innerHTML = newAgents.map(s => render.listItem(s)).join('');
    }

    if (business.length) {
      document.getElementById('section-business').style.display = 'block';
      document.getElementById('business-list').innerHTML = business.slice(0, 5).map(s => render.listItem(s)).join('');
    }

    if (early.length) {
      document.getElementById('section-early').style.display = 'block';
      document.getElementById('early-list').innerHTML = early.map(s => render.listItem(s)).join('');
    }
    if (window.Reveal) window.Reveal.refresh();
  });
})();
</script>
