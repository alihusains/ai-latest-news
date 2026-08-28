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
  - `base-url.js` — resolves `BASE_URL` for subpath-safe fetches
  - `data.js` — data layer with caching and helpers
  - `search.js` — command-palette search overlay
  - `story.js` — hash-routed story modal
  - `main.js` — theme toggle, mobile nav, boot

## Adding a Page

1. Create a new `.md` file with front matter: `layout: platform`
2. Add a `<script>` block that calls `Data.fetch()` and renders into a container
3. Use `render.card(s)` or `render.listItem(s)` helpers from existing pages
