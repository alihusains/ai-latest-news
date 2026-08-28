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

  <div class="newsletter-box">
    <h2>Never miss what changed in AI.</h2>
    <p>Get The AI Daily delivered to your inbox every morning. Curated, summarized, and ready in under 5 minutes.</p>
    <form class="newsletter-form" onsubmit="event.preventDefault(); this.querySelector('.newsletter-status').textContent='Delivery coming soon.'">
      <input type="email" placeholder="you@example.com" required aria-label="Email address">
      <button type="submit">Get the AI Daily</button>
    </form>
    <p class="newsletter-status"></p>
  </div>
</div>

<script>
(function() {
  const render = {
    hero(s) {
      return `<div class="hero-category">${s.category}</div>
        <h1 class="hero-title"><a href="#/story/${s.id}">${s.headline}</a></h1>
        <p class="hero-subtitle">${s.subheadline || s.summary.slice(0, 140) + '...'}</p>
        <div class="hero-meta">
          <span>${s.reading_time}</span>
          <span>·</span>
          <span>${Data.formatDate(s.published_at)}</span>
          <span>·</span>
          <span>${s.sources.map(x => x.name).join(', ')}</span>
        </div>
        <div class="mt-lg"><a href="#/story/${s.id}" class="section-link" style="font-weight:600">Read story →</a></div>`;
    },
    card(s, variant) {
      const img = s.image ? `<img class="card-image" src="${s.image}" alt="" loading="lazy">` : '';
      const body = `<div class="card-body">
        <span class="card-category" data-cat="${s.category}">${s.category}</span>
        <h3 class="card-title"><a href="#/story/${s.id}">${s.headline}</a></h3>
        <p class="card-subtitle">${s.subheadline || ''}</p>
        <div class="card-meta">
          <span>${s.reading_time}</span>
          <span>·</span>
          <span>${Data.formatDate(s.published_at)}</span>
          <span>·</span>
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
            <span>·</span>
            <span>${Data.formatDate(s.published_at)}</span>
            <span>·</span>
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
    const agents = Data.getByCategory('agents').filter(s => s.tier !== 'top').sort((a,b) => b.importance - a.importance);
    const models = Data.getByCategory('models').filter(s => s.tier !== 'top').sort((a,b) => b.importance - a.importance);
    const products = Data.getByCategory('products').filter(s => s.tier !== 'top').sort((a,b) => b.importance - a.importance);
    const business = Data.getByCategory('business').filter(s => s.tier !== 'top').sort((a,b) => b.importance - a.importance);
    const early = data.stories.filter(s => s.is_early_signal && s.tier !== 'top');
    const tool = Data.getToolOfDay();

    if (top.length) {
      const hero = document.getElementById('home-hero');
      hero.querySelector('.container').innerHTML = render.hero(top[0]);
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
      if (tool) {
        document.getElementById('products-feature').innerHTML = `<div class="feature-card">
          <div class="feature-label">AI Tool of the Day</div>
          <h3 class="feature-title"><a href="#/story/${tool.id}">${tool.headline}</a></h3>
          <p class="feature-summary">${tool.subheadline || tool.summary.slice(0, 200) + '...'}</p>
          <div class="feature-meta">${tool.reading_time} · ${Data.formatDate(tool.published_at)}</div>
        </div>`;
      }
      document.getElementById('products-list').innerHTML = products.slice(0, 5).map(s => render.listItem(s)).join('');
    }

    if (business.length) {
      document.getElementById('section-business').style.display = 'block';
      document.getElementById('business-list').innerHTML = business.slice(0, 5).map(s => render.listItem(s)).join('');
    }

    if (early.length) {
      document.getElementById('section-early').style.display = 'block';
      document.getElementById('early-list').innerHTML = early.map(s => render.listItem(s)).join('');
    }
  });
})();
</script>
