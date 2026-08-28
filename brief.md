---
layout: platform
title: Brief
---

<div class="hero">
  <div class="container">
    <h1 class="hero-title">Brief</h1>
    <p class="hero-subtitle">Your quick daily briefing on what happened in AI.</p>
  </div>
</div>

<div class="container">
  <div id="brief-content"></div>
</div>

<script>
(function() {
  Data.fetch().then(data => {
    if (!data) { document.getElementById('brief-content').innerHTML = '<div class="error-state"><h2>News could not be refreshed.</h2><p>Try again later.</p></div>'; return; }
    const top = Data.getTop();
    const topStory = top[0];
    const highlights = data.stories.filter(s => s.tier === 'major' || s.tier === 'top').slice(0, 7);
    const early = data.stories.filter(s => s.is_early_signal);
    let html = '';
    if (topStory) {
      html += `<div class="section"><div class="section-header"><h2 class="section-title">The Big Story</h2></div>
        <div class="card">
          ${topStory.image ? `<img class="card-image" src="${topStory.image}" alt="" loading="lazy" style="aspect-ratio:21/9;max-height:360px">` : ''}
          <div class="card-body">
            <span class="card-category" data-cat="${topStory.category}">${topStory.category}</span>
            <h2 class="card-title" style="font-size:var(--text-section)"><a href="#/story/${topStory.id}">${topStory.headline}</a></h2>
            <p class="card-subtitle">${topStory.subheadline || ''}</p>
            <p style="color:var(--color-text-secondary);line-height:1.6;margin:0 0 var(--space-md)">${topStory.why_it_matters}</p>
            <div class="card-meta"><span>${topStory.reading_time}</span><span>·</span><span>${Data.formatDate(topStory.published_at)}</span><span>·</span><span>${topStory.sources.map(x => x.name).join(', ')}</span></div>
          </div>
        </div></div>`;
    }
    html += `<div class="section"><div class="section-header"><h2 class="section-title">5 Things You Should Know</h2></div><ul class="list">`;
    highlights.slice(1, 6).forEach(s => {
      html += `<li class="list-item" style="padding:var(--space-md) 0;border-bottom:1px solid var(--color-border)">
        <div class="list-item-body" style="padding:0">
          <span class="card-category" data-cat="${s.category}">${s.category}</span>
          <h3 class="list-item-title" style="font-size:var(--text-body)"><a href="#/story/${s.id}">${s.headline}</a></h3>
        </div>
      </li>`;
    });
    html += '</ul></div>';
    if (early.length) {
      html += `<div class="section"><div class="section-header"><h2 class="section-title">Early Signal</h2></div><div class="list">`;
      early.forEach(s => { html += `<div class="list-item"><div class="list-item-body"><span class="card-category" data-cat="${s.category}">${s.category}</span><h3 class="list-item-title"><a href="#/story/${s.id}">${s.headline}</a></h3><p class="list-item-summary">${s.why_it_matters}</p></div></div>`; });
      html += '</div></div>';
    }
    html += `<div class="section"><div class="section-header"><h2 class="section-title">What's Next</h2></div>
      <div class="signal-box"><div class="signal-grid">
        <div class="signal-item"><h4>Watch</h4><p>Anthropic's Nscale compute ramp and OpenAI's agent safety follow-up.</p></div>
        <div class="signal-item"><h4>Expect</h4><p>Chinese labs' price responses and enterprise evaluation shifts.</p></div>
        <div class="signal-item"><h4>Read</h4><p>Our analysis of why frontier model pricing is becoming a commodity play.</p></div>
      </div></div></div>`;
    html += `<div class="newsletter-box">
      <h2>Never miss what changed in AI.</h2>
      <p>Get The AI Daily delivered to your inbox every morning.</p>
      <form class="newsletter-form" onsubmit="event.preventDefault(); this.querySelector('.newsletter-status').textContent='Delivery coming soon.'">
        <input type="email" placeholder="you@example.com" required aria-label="Email address">
        <button type="submit">Get the AI Daily</button>
      </form>
      <p class="newsletter-status"></p>
    </div>`;
    document.getElementById('brief-content').innerHTML = html;
  });
})();
</script>
