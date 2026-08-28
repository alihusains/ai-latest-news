---
layout: home
title: Home
---

<div class="home">
  <h1>AI Latest News</h1>
  <p class="lead">
    A daily AI news digest, aggregated, deduped, classified, and summarized with citations.
    Sources include RSS feeds, Reddit JSON, GitHub trending, and Nitter for X accounts.
  </p>

  <h2>Latest Digests</h2>
  {% assign daily_pages = site.pages | where_exp: "item", "item.path contains 'content/daily'" | sort: "date" | reverse %}
  <ul class="post-list">
    {% for p in daily_pages %}
      <li>
        <span class="post-date">{{ p.date | date: "%Y-%m-%d" }}</span>
        <a href="{{ p.url | relative_url }}">{{ p.title }}</a>
      </li>
    {% endfor %}
  </ul>
</div>
