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
| `rss` | `feedparser` (stdlib XML/Atom fallback included) |
| `reddit` | `old.reddit.com` JSON endpoint |
| `web` | HTML scrape (GitHub Trending by default) |
| `x` | Nitter profile scrape (RSS if available) |

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
| `--config other.yaml` | Use an alternate source config |

Individual sources can also be sanity-checked with:

```bash
python main.py --check
```

## Adding or changing sources

Edit `sources.yaml`. Each source has:

```yaml
- name: Short Label
  type: rss          # rss | reddit | web | x
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
- Nitter instances used for `x`-type sources are fragile and may go down
  without notice; a failed source is skipped and the rest of the pipeline
  continues.
