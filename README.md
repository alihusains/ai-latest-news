# AI Latest News

An automated AI news aggregator that collects headlines from a configurable set
of sources every day and renders them into a single Markdown digest.

## What it does

The pipeline is: **fetch → dedupe → classify → clean → summarize → render**.

1. **fetch** — pulls raw items from every active source in `sources.yaml`.
2. **dedupe** — removes duplicate URLs and near-duplicate titles (fuzzy match).
3. **classify** — buckets each item into one of:
   `IT`, `Hardware`, `Science`, `Medical`, `AI Research`, `Open Source`,
   `Acquisitions`, or `Community` (using the source `category_hint` plus
   keyword rules).
4. **clean** — strips HTML/boilerplate and normalizes whitespace.
5. **summarize** — trims each item to a short 1–2 line summary with a
   source link.
6. **render** — writes `content/daily/YYYY-MM-DD.md` with Jekyll front matter
   (required for GitHub Pages rendering and the index Liquid loop).

## Supported source types

| Type | Fetch method |
| --- | --- |
| `rss` | `feedparser` (stdlib XML/Atom fallback included). Also used for Reddit via `www.reddit.com/r/<sub>/new.rss` (the `.json` endpoints are now login-walled) |
| `web` | HTML scrape (GitHub Trending by default) |
| `hf_papers` | Hugging Face daily-papers JSON API |
| `hf_models` | Hugging Face trending-models JSON API (open-source tool signal) |
| `github_search` | GitHub repo search API; `{since}` in the query is replaced with the date 7 days ago |
| `hn_search` | Hacker News (Algolia) search API |

## Ranked feed list (`ai_news_feeds_ranked.csv`)

The RSS feed set is driven by a ranked CSV (exported from the OPML feed list).
Each row maps to an RSS source and carries a ranking that shapes the output:

| Column | Meaning |
| --- | --- |
| `rank` | 1–N, best first |
| `category` | OPML group (maps to a `category_hint`) |
| `feed_name` | Feed label |
| `feed_url` | RSS xmlUrl |
| `quality_score` | 1–10 authority/signal score |
| `priority` | `P1` (core), `P2` (important), `P3` (niche) |

How it drives the pipeline:

- `priority` scales the per-source item cap (P1 full, P2 ~65%, P3 ~40%), so
  high-quality feeds contribute more and niche feeds cannot flood the digest.
- `quality_score >= 9` and `P1` feeds get a small importance bonus in scoring.
- `sources.yaml` is still used for the **non-RSS** discovery/API sources
  (Reddit, HF papers/models, Product Hunt, GitHub Trending scrape, GitHub + HN
  search) that power the "AI Tool of the Day" and "New AI Agents" sections and
  are not part of the OPML. Identical RSS URLs in `sources.yaml` are ignored in
  favor of the CSV entry.

`--feeds <file.csv>` overrides the default ranked CSV; `--config` still points
at `sources.yaml`.

## Requirements

Python 3.10+. Dependencies are pinned in `requirements.txt`:

```
pip install -r requirements.txt
```

(`pyyaml` and `requests` are required; `feedparser` is optional — a stdlib
XML/Atom parser is used as a fallback if it is missing.)

## Running locally

```bash
python main.py
```

This writes the digest for today's date to `content/daily/YYYY-MM-DD.md`.

Useful flags:

| Flag | Purpose |
| --- | --- |
| `--date 2026-08-28` | Force a specific date for the output file |
| `--limit 5` | Cap items per source (default 25; `0` = no cap) |
| `--check` | Verify every source URL returns without error |
| `--config other.yaml` | Use an alternate API/discovery config |
| `--feeds other.csv` | Use an alternate ranked feed CSV |

Individual sources can also be sanity-checked with:

```bash
python main.py --check
```

## Adding or changing sources

To add/rank RSS feeds, edit `ai_news_feeds_ranked.csv` (see the section above).
`sources.yaml` now holds the **non-RSS** discovery/API sources plus any extra
RSS feeds that aren't already in the ranked CSV. Each entry has:

```yaml
- name: Short Label
  type: rss          # rss | web | hf_papers | hf_models | github_search | hn_search
  url: https://example.com/feed
  category_hint: news  # research | open-source | hardware | science | community | ...
  active: true
```

Set `active: false` to temporarily disable a source without deleting it.
Prune or add entries weekly as feeds rotate. `category_hint` gives the
classifier a starting point; keyword rules in `main.py` can still re-bucket
an item into a more specific category.

## Scheduled deployment

`.github/workflows/daily.yml` runs the pipeline every day at **03:00 UTC — 07:00
Asia/Dubai (GST)** — commits the generated Markdown/JSON, and pushes it back to
the repository. It uses `GITHUB_TOKEN` for authentication — no manual deploy step.

GitHub Pages serves the result: enable Pages on the repository (branch or
`docs/` source) as a one-time, separate repo setting. The workflow only
publishes `content/daily/*.md`.

## Newsletter (Buttondown)

Subscribers are collected and stored in **Buttondown**, not in this repo.

- The newsletter template is a clean, **Apple-style** email (system SF-like font
  stack, Apple-blue `#0071e3` accents, hairline dividers, pill CTAs) generated by
  `main.build_newsletter_html()` and written to `newsletter/<date>.html`.
- The site's subscribe form POSTs directly to
  `https://buttondown.com/api/emails/embed-subscribe/<username>` (native form, so
  Buttondown's double opt-in / CAPTCHA / GDPR flows work). Set
  `buttondown_username` in `_config.yml`.
- After the digest is generated, `push_buttondown.py` stages `newsletter/<date>.html`
  as a **draft** in Buttondown via the API. Review and **Send** from the dashboard.
- Required repo secret: `BUTTONDOWN_API_KEY` (optional — the step is skipped if unset).
- `subscribers.json` and `send_newsletter.py` were removed; `subscribers.json` is
  git-ignored so a real list can never be committed publicly.


## Notes

- Summaries are **extractive** (cleaned + truncated), not LLM-generated — no
  API key or network model dependency is required.
- Reddit RSS is throttled to ~1 request / 20 s per IP; `fetch_all` spaces the
  calls and retries once on a transient 429. A failed source is skipped and the
  rest of the pipeline continues.
- Discovery sections are driven by story flags written into `data/latest.json`:
  `is_new_agent` (GitHub/HN/r/AI_Agents + agent launches), `is_whats_new`
  (launch/release/open-source/benchmark/breakthrough), and the dual
  `tool_of_day_opensource` / `tool_of_day_freemium` picks.
