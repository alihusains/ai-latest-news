# Platform Docs

## Data Contract

The pipeline commits `data/latest.json` daily with the following schema:

- `date`: ISO date string
- `edition`: Edition name
- `platform`: Platform identifier
- `stats`: `{ total: number, reading_time_min: number }`
- `stories`: array of story objects
  - `id`, `headline`, `subheadline`, `summary`, `why_it_matters`
  - `category`: agents | models | products | business
  - `tags`, `industry`, `story_type`
  - `importance`: 1-5
  - `tier`: top | major | standard
  - `sources`: array of `{ name, url, published }`
  - `source_count`, `image`, `url`, `published_at`, `reading_time`
  - `is_tool_of_day`, `is_early_signal`
- `tool_of_day`: story id or null
- `early_signal`: story id or null

## Frontend Architecture

- Jekyll 4.4.1 on GitHub Pages
- Custom `_layouts/default.html` and `_layouts/platform.html`
- Design system: `assets/css/platform.css` (CSS custom properties, light/dark via `prefers-color-scheme` + `data-theme`)
- Vanilla JS modules in `assets/js/`:
  - `data.js` — data layer with caching and helpers (`BASE_URL` is set inline in
    `_layouts/default.html` + `platform.html` via `{{ '' | relative_url }}`, so
    fetches are subpath-safe from any page depth)
  - `search.js` — command-palette search overlay
  - `story.js` — hash-routed story modal
  - `main.js` — theme toggle, mobile nav, active-nav highlight, edition date, scroll reveal, back-to-top, boot

## Newsletter & Subscribers

Subscribers are collected and stored **in Buttondown**, never in this repository.

- The subscribe form (`_includes/subscribe.html`, used on Home / About / Brief) is a
  native HTML `<form>` that POSTs to
  `https://buttondown.com/api/emails/embed-subscribe/<username>`. Buttondown handles
  double opt-in, CAPTCHA, GDPR and the unsubscribe link.
- Set `buttondown_username` in `_config.yml`.
- Each morning the workflow generates `newsletter/<date>.html` and `push_buttondown.py`
  stages it as a **draft** in Buttondown (via `POST /v1/emails`, `Authorization: Token …`).
  You review and click **Send** in the Buttondown dashboard — sending is never fully
  unattended. The step is skipped when `BUTTONDOWN_API_KEY` is not set.
- There is intentionally **no `subscribers.json`** and **no `send_newsletter.py`** any more;
  `subscribers.json` is git-ignored so a real list can never be committed to the public repo.


## Adding a Page

1. Create a new `.md` file with front matter: `layout: platform`
2. Add a `<script>` block that calls `Data.fetch()` and renders into a container
3. Use `render.card(s)` or `render.listItem(s)` helpers from existing pages
