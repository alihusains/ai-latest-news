---
layout: home
title: Home
---

<div class="home-hero">
  <h1>AI Latest News</h1>
  <p>
    A daily AI news digest, aggregated, deduped, classified, and summarized with citations.
    Sources include RSS feeds, Reddit JSON, GitHub trending, and Nitter for X accounts.
  </p>
</div>

<h2 class="home-section-title">Latest Digests</h2>
{% assign daily_pages = site.pages | where_exp: "item", "item.path contains 'content/daily'" | sort: "date" | reverse %}
<ul class="home-digest-list">
  {% for p in daily_pages %}
    <li class="home-digest-item">
      <span class="home-digest-date">{{ p.date | date: "%Y-%m-%d" }}</span>
      <a class="home-digest-title" href="{{ p.url | relative_url }}">{{ p.title }}</a>
    </li>
  {% endfor %}
</ul>
