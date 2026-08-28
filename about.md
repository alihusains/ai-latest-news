---
layout: page
title: About
permalink: /about/
---

This site is a daily AI news digest. Articles are aggregated from multiple sources, deduped, classified into categories, and summarized with citations.

## How it works

### Sources

- **RSS feeds**: TechCrunch AI, The Verge, Ars Technica, MIT Technology Review, Wired, ZDNet, Hacker News, Towards Data Science, and more
- **Reddit JSON**: Public JSON endpoints from r/MachineLearning, r/artificial, r/LocalLLaMA, r/hardware, r/science
- **GitHub trending**: Daily trending repositories from GitHub
- **Nitter**: X.com (Twitter) accounts via Nitter instances

### Categories

- IT
- Hardware
- Science
- Medical
- AI Research
- Open Source
- Acquisitions
- Community

### Pipeline

A Python pipeline runs daily, fetching new content from all sources, deduplicating articles, classifying them into categories, and generating summaries with citations. The output is written as markdown files to `content/daily/`.

### Adding Sources

Sources are defined in <code>sources.yaml</code> in the repository. To add a new source:

1. Edit <code>sources.yaml</code>
2. Add the source name, type (rss, reddit, x, web), URL, and category hint
3. Commit the change

### Repository

This site is open source. View the code and contribute on [GitHub](https://github.com/yourusername/ai-latest-news).
