---
layout: platform
title: About
permalink: /about/
---

<div class="hero">
  <div class="container">
    <h1 class="hero-title">About SIGNAL</h1>
    <p class="hero-subtitle">Know what changed in AI. A daily editorial digest of the most significant developments in artificial intelligence.</p>
  </div>
</div>

<div class="container">
  <div class="section">
    <div class="section-header"><h2 class="section-title">How it works</h2></div>
    <p style="font-size:var(--text-body);color:var(--color-text-secondary);line-height:1.7;max-width:720px">
      SIGNAL aggregates stories from RSS feeds, Reddit JSON, GitHub trending, and Nitter for X accounts. A Python pipeline deduplicates, classifies, and summarizes each story with citations. The result is a clean, scannable daily brief designed to be read in under 5 minutes.
    </p>
  </div>

  <div class="section">
    <div class="section-header"><h2 class="section-title">Categories</h2></div>
    <div class="grid grid--2">
      <div class="card"><div class="card-body"><span class="card-category" data-cat="agents">Agents</span><p style="color:var(--color-text-secondary);margin:var(--space-sm) 0 0">Autonomous systems, tool use, and agentic workflows.</p></div></div>
      <div class="card"><div class="card-body"><span class="card-category" data-cat="models">Models</span><p style="color:var(--color-text-secondary);margin:var(--space-sm) 0 0">New releases, research papers, and benchmark results.</p></div></div>
      <div class="card"><div class="card-body"><span class="card-category" data-cat="products">Products</span><p style="color:var(--color-text-secondary);margin:var(--space-sm) 0 0">Apps, hardware, open-source tools, and developer platforms.</p></div></div>
      <div class="card"><div class="card-body"><span class="card-category" data-cat="business">Business</span><p style="color:var(--color-text-secondary);margin:var(--space-sm) 0 0">Funding, policy, compute deals, and market shifts.</p></div></div>
    </div>
  </div>

  <div class="section">
    <div class="section-header"><h2 class="section-title">Adding Sources</h2></div>
    <p style="font-size:var(--text-body);color:var(--color-text-secondary);line-height:1.7;max-width:720px">
      Sources are defined in <code>sources.yaml</code> in the repository. To add a new source, edit the file and add the source name, type, URL, and category hint. The pipeline will pick it up on the next run.
    </p>
  </div>

  {% include subscribe.html %}
</div>
