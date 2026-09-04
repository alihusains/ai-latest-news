#!/usr/bin/env python3
"""AI Latest News aggregator pipeline.

Fetches news from a ranked feed list (see ``ai_news_feeds_ranked.csv``) plus the
API/discovery sources in ``sources.yaml``, then runs:
fetch -> dedupe -> classify -> clean -> summarize -> render.

The ranked CSV is the source of truth for RSS feeds; its ``priority`` column
scales how many items each feed contributes and its ``quality_score`` nudges
importance. sources.yaml supplies the non-RSS discovery sources (Reddit, HF
papers/models, Product Hunt, GitHub Trending scrape, GitHub/HN search) that
power the AI Tool of the Day and New AI Agents sections.

Usage:
    python main.py                     # build today's digest
    python main.py --date 2026-08-28   # force a date
    python main.py --limit 5           # max items per source (quick tests)
    python main.py --config other.yaml # alternate API/discovery config
    python main.py --feeds other.csv   # alternate ranked feed list
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import email.utils
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import yaml

try:  # optional, but recommended for robust RSS parsing
    import feedparser
except ImportError:  # pragma: no cover
    feedparser = None

try:  # requests is pinned in requirements.txt; urllib used as fallback
    import requests
except ImportError:  # pragma: no cover
    requests = None

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT_DIR / "sources.yaml"
DAILY_DIR = ROOT_DIR / "content" / "daily"

USER_AGENT = "AI-News-Aggregator/1.0 (+https://github.com/example/ai-latest-news)"

# How many days of history to keep. RSS/API feeds return up to ~2 weeks of
# items; without a window the daily edition shows stale news (e.g. a 31st
# edition listing 26-Aug stories). Items with no parseable date are kept.
LOOKBACK_DAYS = 3

# AI summarization via Mistral. After feeds are collected, each story's summary
# is rewritten in plain English (<=120 chars, no em dashes), tagged, and given a
# category. Enabled only when MISTRAL_API_KEY is set; otherwise the pipeline
# falls back to the heuristic summary so CI never hard-fails on AI.
MISTRAL_BASE = os.environ.get("MISTRAL_BASE", "https://api.mistral.ai/v1")
MISTRAL_MODEL = os.environ.get("MISTRAL_MODEL", "ministral-8b-latest")
MISTRAL_BATCH = 10          # stories per API call
MISTRAL_TIMEOUT = 90        # per-request seconds
MISTRAL_MAX_CHARS = 120     # hard cap on the rewritten summary

# Canonical output categories.
CATEGORIES = [
    "IT",
    "Hardware",
    "Science",
    "Medical",
    "AI Research",
    "Open Source",
    "Acquisitions",
    "Community",
]

# Map the category_hint values used in sources.yaml to canonical categories.
HINT_MAP = {
    "research": "AI Research",
    "news": "IT",
    "newsletter": "IT",
    "engineering": "IT",
    "community": "Community",
    "open-source": "Open Source",
    "opensource": "Open Source",
    "hardware": "Hardware",
    "science": "Science",
    "medical": "Medical",
    "acquisitions": "Acquisitions",
}

# Keyword rules that override the source hint when they appear in the
# title/summary. Order matters: first match wins.
# Each rule is (category, exact_terms, prefix_stems).
#   exact_terms : matched with word boundaries (e.g. \bintel\b, \boss\b)
#   prefix_stems: matched as a prefix followed by any word chars (e.g. "therap")
OVERRIDE_RULES = [
    # Retail deals / discount / coupon content is consumer shopping, not tech
    # news: bucket it as Community. Checked first so a deal on a chip doesn't
    # get re-classified as Hardware.
    (
        "Community",
        [
            "coupon", "coupons", "promo", "promos", "discount", "discounts",
            "% off", "save up to", " off right now", "labor day",
            "black friday", "cyber monday", "price cut", "price cuts",
            "best deals", "savings",
        ],
        [],
    ),
    (
        "Medical",
        [
            "fda", "clinical", "disease", "patient", "drug", "biotech",
            "pharma", "hospital", "medtech", "healthcare", "vaccine",
            "cancer", "genome", "protein", "medical", "treatment",
        ],
        ["therap", "diagnos", "pharmaceuti"],
    ),
    (
        "Acquisitions",
        [
            "acquisition", "acquire", "acquires", "acquired", "acquiring",
            "merger", "mergers", "m&a", "buyout", "buy into", "to buy",
            "snaps up",
        ],
        [],
    ),
    (
        "Hardware",
        [
            "chip", "chipset", "gpu", "cpu", "processor", "semiconductor",
            "silicon", "transistor", "tpu", "nvidia", "amd", "intel", "asic",
            "hbm", "wafer", "lithograph", "supercomputer", "hardware",
        ],
        [],
    ),
    (
        "Open Source",
        [
            "open source", "open-source", "github", "repository", "repositories",
            "license", "self-hosted", "self hosted", "pull request", "oss",
            "open model", "open weights", "open-weights", "apache 2.0",
            "mit license",
        ],
        [],
    ),
    (
        "Science",
        # Only concrete scientific fields trigger Science; generic words like
        # "science"/"data science"/"space" pull in AI/data articles.
        [
            "physics", "chemistry", "biology", "quantum", "astronomy",
            "climate", "telescope", "particle", "nobel", "ecology", "geology",
            "neuroscience", "genetics", "astrophysics", "cosmology",
        ],
        [],
    ),
]

# Words that indicate an item is about AI/ML (used to upgrade generic news
# to "AI Research" when the source hint is neutral).
AI_SIGNALS = [
    "ai", "llm", "gpt", "claude", "gemini", "anthropic", "openai", "deepmind",
    "mistral", "transformer", "neural", "machine learning", "deep learning",
    "fine-tun", "inference", "agents", "agentic", "copilot", "chatbot",
    "multimodal", "rag", "diffusion", "pytorch", "tensorflow", "model",
    "reasoning", "benchmark", "open weights",
]

_TAG_RE = re.compile(r"<[^>]+>", re.S)
_WS_RE = re.compile(r"\s+")


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def http_get(url: str, timeout: int = 12) -> bytes:
    """Fetch a URL body as bytes, following redirects."""
    if requests is not None:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        resp.raise_for_status()
        return resp.content
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read()


def http_get_text(url: str, timeout: int = 12) -> str:
    raw = http_get(url, timeout=timeout)
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def response_ok(url: str) -> bool:
    """Lightweight health check: does the URL return without raising?"""
    try:
        http_get(url, timeout=8)
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Fetch: per source type
# --------------------------------------------------------------------------- #
def fetch_source(source: dict) -> list[dict]:
    """Returns raw items for one source; never raises."""
    stype = (source.get("type") or "").strip().lower()
    url = (source.get("url") or "").strip()
    if not url:
        return []
    try:
        if stype == "rss":
            items = _fetch_rss(url)
        elif stype == "web":
            items = _fetch_web(url)
        elif stype == "hf_papers":
            items = _fetch_hf_papers(url)
        elif stype == "hf_models":
            items = _fetch_hf_models(url)
        elif stype == "github_search":
            items = _fetch_github_search(url)
        elif stype == "hn_search":
            items = _fetch_hn_search(url)
        else:
            sys.stderr.write(f"[skip] unknown type {stype!r} for {source.get('name')}\n")
            return []
    except Exception as exc:  # keep the pipeline alive on any source failure
        sys.stderr.write(f"[warn] {source.get('name')} failed: {exc}\n")
        return []
    for it in items:
        it.setdefault("source", source.get("name", stype))
        it.setdefault("link", "")
    return items


def _parse_xml_items(feed_text: str) -> list[dict]:
    """Minimal RSS/Atom parser used as a feedparser fallback."""
    items: list[dict] = []
    try:
        root = ET.fromstring(feed_text)
    except ET.ParseError:
        return items
    for node in root.iter():
        if node.tag.endswith("item"):
            items.append(_xml_node_to_item(node, "item", "link", "title", "description"))
        elif node.tag.endswith("entry"):
            items.append(_xml_node_to_item(node, "entry", "link", "title", "summary"))
    return items


def _xml_node_to_item(node, kind: str, link_tag: str, title_tag: str, desc_tag: str) -> dict:
    def text(tag_name: str):
        for child in node.iter():
            if child.tag.endswith(tag_name):
                return (child.text or "").strip()
        return ""

    link = text(link_tag)
    if kind == "entry":  # Atom link is an attribute
        for child in node.iter():
            if child.tag.endswith("link"):
                link = child.attrib.get("href", link)
                break
    title = text(title_tag)
    desc = text(desc_tag)
    desc_raw = desc
    if not desc:
        # Atom feeds (e.g. Product Hunt) carry the blurb in <content> only.
        raw_content = text("content")
        if raw_content:
            desc_raw = raw_content
            desc = clean_text(raw_content)[:500]
    published = text("pubDate") or text("published") or text("updated")
    # media:thumbnail / media:content / enclosure carry the image URL.
    image = ""
    for child in node.iter():
        tag = child.tag
        url = child.attrib.get("url") or child.attrib.get("href") or ""
        if url and (tag.endswith("thumbnail") or tag.endswith("content") or tag.endswith("enclosure")):
            image = url
            break
    if not image:
        # WordPress feeds hide the hero <img> in <content:encoded>.
        image = _first_inline_image(desc_raw) or _first_inline_image(text("encoded")) or ""
    return {
        "title": title,
        "link": link.strip(),
        "summary": desc,
        "image": image or None,
        "published": _parse_time(published),
        "date": published,
    }


_INLINE_IMG_RE = re.compile(r'<img[^>]*\bsrc=["\'](https?:[^"\']+)', re.I)


def _first_inline_image(markup: str) -> str | None:
    """First absolute <img> URL inside an HTML description/content body.

    Many major feeds (MIT Technology Review, MarkTechPost, ...) carry the hero
    image inline in the article HTML rather than as media:thumbnail/enclosure,
    so a structured-only check under-counts their images.
    """
    if not markup:
        return None
    m = _INLINE_IMG_RE.search(markup) or _INLINE_IMG_RE.search(html.unescape(markup))
    return m.group(1) if m else None


def _feedparser_image(entry) -> str | None:
    """Pull the first usable image URL from feedparser media/enclosure fields."""
    candidates: list[str] = []
    for key in ("media_content", "media_thumbnail"):
        for media in entry.get(key, []) or []:
            url = media.get("url") or media.get("href") or ""
            if url:
                candidates.append(url)
    for enc in entry.get("enclosures", []) or []:
        url = enc.get("href") or enc.get("url") or ""
        if url:
            candidates.append(url)
    explicit = entry.get("image") or entry.get("media_image", {}).get("url", "")
    if explicit:
        candidates.append(explicit)
    return next((c for c in candidates if c), None)


def _fetch_rss(url: str) -> list[dict]:
    raw = http_get_text(url)
    items = []
    if feedparser is not None:
        parsed = feedparser.parse(raw)
        for entry in parsed.entries:
            link = entry.get("link", "")
            title = entry.get("title", "")
            content_html = ""
            if entry.get("content"):
                content_html = entry["content"][0].get("value", "") or ""
            summary = (
                entry.get("summary", "")
                or entry.get("description", "")
                or entry.get("subtitle", "")
                or content_html
            )
            published = entry.get("published", "") or entry.get("updated", "")
            item = {
                "title": title,
                "link": link,
                "summary": summary,
                # WordPress feeds (Verge, MIT Tech Review, MarkTechPost) hide the
                # hero <img> in content:encoded, so scan the body too.
                "image": (_feedparser_image(entry) or _first_inline_image(summary)
                          or _first_inline_image(content_html)),
                "published": _parse_time(published),
                "date": published,
            }
            items.append(item)
    else:
        items = _parse_xml_items(raw)
    return items


def _fetch_hf_papers(url: str) -> list[dict]:
    """Hugging Face daily papers JSON API."""
    raw = json.loads(http_get_text(url))
    items = []
    for entry in raw if isinstance(raw, list) else []:
        paper = entry.get("paper") or {}
        title = re.sub(r"\s+", " ", (paper.get("title") or "")).strip()
        pid = paper.get("id") or ""
        if not title or not pid:
            continue
        summary = clean_text(paper.get("summary", ""))[:600]
        repo = paper.get("githubRepo") or ""
        if repo:
            summary += f" Code: {repo}"
        date = entry.get("publishedAt") or paper.get("publishedAt") or ""
        items.append({
            "title": title,
            "link": f"https://huggingface.co/papers/{pid}",
            "summary": summary,
            "image": None,
            "published": _parse_time(date),
            "date": date,
        })
    return items


def _fetch_hf_models(url: str) -> list[dict]:
    """Hugging Face trending models API (open-source tool signal)."""
    raw = json.loads(http_get_text(url))
    items = []
    for m in raw if isinstance(raw, list) else []:
        mid = (m.get("modelId") or m.get("id") or "").strip()
        if not mid:
            continue
        likes = m.get("likes", 0) or 0
        downloads = m.get("downloads", 0) or 0
        created = m.get("createdAt") or ""
        summary = (
            f"Trending open model on Hugging Face: {downloads:,} downloads and "
            f"{likes:,} likes. {mid}"
        )
        items.append({
            "title": mid,
            "link": f"https://huggingface.co/{mid}",
            "summary": summary,
            "image": None,
            "published": _parse_time(created),
            "date": created,
        })
    return items


def _fetch_github_search(url: str) -> list[dict]:
    """GitHub repository search API. `{since}` in the query is replaced with
    the date 7 days ago so the window always covers fresh repos."""
    since = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    url = url.replace("{since}", since)
    raw = json.loads(http_get_text(url))
    items = []
    for r in raw.get("items", []) if isinstance(raw, dict) else []:
        full = r.get("full_name") or ""
        if not full:
            continue
        desc = clean_text(r.get("description") or "")
        stars = r.get("stargazers_count", 0) or 0
        summary = desc or f"A new AI agent repository on GitHub ({stars} stars in its first week)."
        if desc:
            summary += f" New repo with {stars} stars in its first week."
        created = r.get("created_at") or ""
        items.append({
            "title": full,
            "link": r.get("html_url") or f"https://github.com/{full}",
            "summary": summary,
            "image": None,
            "published": _parse_time(created),
            "date": created,
        })
    return items


def _fetch_hn_search(url: str) -> list[dict]:
    """Hacker News (Algolia) search API for agent stories."""
    raw = json.loads(http_get_text(url))
    items = []
    for h in raw.get("hits", []) if isinstance(raw, dict) else []:
        title = (h.get("title") or "").strip()
        if not title:
            continue
        oid = h.get("objectID", "")
        link = h.get("url") or f"https://news.ycombinator.com/item?id={oid}"
        pts = h.get("points", 0) or 0
        ncom = h.get("num_comments", 0) or 0
        created = h.get("created_at") or ""
        items.append({
            "title": title,
            "link": link,
            "summary": f"Discussed on Hacker News: {pts} points, {ncom} comments.",
            "image": None,
            "published": float(h.get("created_at_i") or 0) or _parse_time(created),
            "date": created,
        })
    return items


def _fetch_web(url: str) -> list[dict]:
    """GitHub Trending HTML scrape."""
    text = http_get_text(url)
    items = []
    if "github.com" in url:
        items = _scrape_github_trending(text)
    if not items:
        items = _scrape_generic_links(text, url)
    return items


def _scrape_github_trending(text: str):
    """Parse GitHub Trending article rows (owner/repo + description)."""
    repos = re.findall(r'<h2[^>]*>\s*<a[^>]*href="/([^"/]+/[^"/]+)"', text)
    descs = re.findall(
        r'<p class="col-9[^"]*color-fg-muted[^"]*"[^>]*>(.*?)</p>', text, re.S
    )
    items = []
    for i, repo in enumerate(repos):
        desc = clean_text(descs[i]) if i < len(descs) else ""
        items.append(
            {
                "title": f"{repo}",
                "link": f"https://github.com/{repo}",
                "summary": desc,
                # GitHub Trending has no per-repo publish date; these are
                # literally "trending today", so stamp them with the run time
                # instead of leaving them undated (which breaks chronological
                # sorting on the site).
                "published": time.time(),
                "date": "",
            }
        )
    return items


def _scrape_generic_links(text: str, base_url: str) -> list[dict]:
    """Generic page fallback: anchor texts + hrefs."""
    base_host = urllib.parse.urlparse(base_url).netloc
    links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', text, re.S)
    items = []
    seen = set()
    for href, anchor in links:
        anchor = clean_text(anchor)
        if len(anchor) < 8 or base_host not in base_url:
            continue
        if href.startswith("javascript:"):
            continue
        full = urllib.parse.urljoin(base_url, href)
        if full in seen:
            continue
        seen.add(full)
        items.append(
            {
                "title": anchor,
                "link": full,
                "summary": anchor,
                "published": 0,
                "date": "",
            }
        )
    return items


# --------------------------------------------------------------------------- #
# Processing stages
# --------------------------------------------------------------------------- #
def _parse_time(value: str) -> float:
    if not value:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    value = value.strip()
    # epoch seconds as string
    if re.fullmatch(r"\d+", value):
        try:
            return float(value)
        except ValueError:
            return 0.0
    # ISO 8601
    if re.match(r"^\d{4}-\d{2}-\d{2}", value):
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    # RFC 822 / email date
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        return parsed.timestamp()
    except (TypeError, ValueError):
        return 0.0


def _truncate(text: str, limit: int) -> str:
    text = _WS_RE.sub(" ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(".,;:") + "…"


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = _TAG_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def normalize_title(title: str) -> str:
    """Lowercase + strip punctuation for robust similarity comparison."""
    title = clean_text(title).lower()
    return re.sub(r"[^a-z0-9 ]+", " ", title)


def dedupe(items: list[dict]) -> list[dict]:
    """Remove duplicate URLs and near-duplicate titles (fuzzy match)."""
    seen_urls: set[str] = set()
    # Inverted index: token -> set of indices into the seen-title list, so
    # fuzzy comparisons only run against titles that share a word (O(n) not O(n^2)).
    seen: list[tuple[str, set[str]]] = []
    index: dict[str, set[int]] = defaultdict(set)
    out: list[dict] = []
    for item in items:
        link = (item.get("link") or "").strip().lower().rstrip("/")
        link_key = urllib.parse.urlparse(link)
        url_key = link_key._replace(query="", fragment="").geturl()
        if url_key:
            if url_key in seen_urls:
                continue
            seen_urls.add(url_key)
        title = normalize_title(item.get("title", ""))
        if title:
            tokens = {tok for tok in title.split() if len(tok) >= 4}
            candidates: set[int] = set()
            for tok in tokens:
                candidates |= index.get(tok, set())
            if any(
                difflib.SequenceMatcher(None, title, seen[i][0]).ratio() >= 0.90
                for i in candidates
            ):
                continue
            pos = len(seen)
            seen.append((title, tokens))
            for tok in tokens:
                index[tok].add(pos)
        out.append(item)
    return out


def is_ai(text: str) -> bool:
    text = " " + text.lower() + " "
    for signal in AI_SIGNALS:
        pattern = r"\b" + re.escape(signal) + r"\b"
        if signal == "ai":  # word boundary with leading letter guards
            pattern = r"(?<![a-z])ai(?![a-z])"
        if re.search(pattern, text):
            return True
    return False


def _rule_matches(text_l: str, exact: list[str], stems: list[str]) -> bool:
    for kw in exact:
        if re.search(r"\b" + re.escape(kw) + r"\b", text_l):
            return True
    for stem in stems:
        if re.search(r"\b" + re.escape(stem) + r"\w*", text_l):
            return True
    return False


def classify(title: str, summary: str, hint: str | None) -> str:
    text = clean_text(title) + " " + clean_text(summary)
    text_l = text.lower()

    # Specific topics override the source hint (first rule wins).
    for category, exact, stems in OVERRIDE_RULES:
        if _rule_matches(text_l, exact, stems):
            return category

    hinted = HINT_MAP.get((hint or "").strip().lower())
    if hinted:
        return hinted

    if is_ai(text_l):
        return "AI Research"
    # A web/unknown link that has any real content is IT by default.
    return "IT"


def summarize(item: dict, limit: int = 260) -> str:
    """Extractive summary: cleaned text trimmed to ~1-2 lines."""
    body = (
        clean_text(item.get("summary", ""))
        or clean_text(item.get("description", ""))
        or clean_text(item.get("title", ""))
    )
    if not body:
        return ""
    # Drop boilerplate cruft.
    body = re.sub(r"\bcontinue reading\b", "", body, flags=re.I)
    body = _WS_RE.sub(" ", body).strip()
    return _truncate(body, limit)


def render(items: list[dict], date_str: str) -> str:
    # Jekyll/GitHub Pages front matter so the markdown renders as a page and the
    # index.html Liquid loop (which sorts site.pages by `date`) can list it.
    front = (
        "---\n"
        f'title: "AI Latest News — {date_str}"\n'
        f"date: {date_str}\n"
        "layout: digest\n"
        "---\n\n"
    )

    groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        groups[item.get("category", "IT")].append(item)

    lines = [f"# AI Latest News — {date_str}", ""]
    lines.append(f"**{len(items)} items across {len(groups)} categories**.")
    lines.append("")

    for cat in CATEGORIES:
        if cat not in groups:
            continue
        cat_items = sorted(
            groups[cat], key=lambda it: it.get("published", 0) or 0, reverse=True
        )
        lines.append(f"## {cat}")
        lines.append("")
        for item in cat_items:
            title = item.get("title") or "(untitled)"
            source = item.get("source", "news")
            link = item.get("link", "")
            lines.append(f"- **{title}** — *{source}*")
            summary = item.get("summary_text", "")
            if summary:
                lines.append(f"  {summary}")
            if link:
                lines.append(f"  [read ↗]({link})")
            lines.append("")
        lines.append("")
    return front + "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# Pipeline v2: AI-only editorial engine
# --------------------------------------------------------------------------- #
NEW_CATEGORIES = ["agents", "models", "products", "business"]

CATEGORY_LABELS = {
    "agents": "Agents",
    "models": "Models & Research",
    "products": "Products & Open Source",
    "business": "Business & Infrastructure",
}

# Deterministic taxonomy scoring: category -> list of (term, weight).
CATEGORY_SCORES = {
    "business": [
        ("raises", 3), ("raised", 3), ("funding", 3), ("series ", 3),
        ("valuation", 3), ("investment", 3), ("investor", 3), ("raised funding", 3),
        ("acquisition", 3), ("acquire", 3), ("acquires", 3), ("acquired", 3),
        ("merger", 3), ("m&a", 3), ("buyout", 3), ("snaps up", 3), ("to buy", 2),
        ("buy into", 2), ("partnership", 2), ("partner", 2), ("collaborat", 2),
        ("teams with", 2), ("joins forces", 2), ("nvidia", 2), ("chip", 2),
        ("gpu", 2), ("tpu", 2), ("data center", 2), ("datacenter", 2),
        ("semiconductor", 2), ("infrastructur", 2), ("enterprise", 2),
        ("compute", 1), ("round", 1), ("deal", 1), ("cfo", 1),
    ],
    "agents": [
        ("agent", 3), ("agentic", 3), ("multi-agent", 3), ("ai agents", 3),
        ("computer use", 3), ("orchestrat", 3), ("autonomous agent", 3),
        ("coding agent", 3), ("copilot", 2), ("mcp", 2), ("tool use", 2),
        ("tool calling", 2), ("swarm", 2), ("workflow", 2), ("reasoning agent", 3),
        ("auto", 2), ("automation", 2), ("autonomous", 2),
    ],
    "models": [
        ("model", 3), ("llm", 3), ("gpt", 3), ("claude", 3), ("gemini", 3),
        ("reasoning", 2), ("multimodal", 2), ("benchmark", 2), ("fine-tun", 2),
        ("training", 2), ("inference", 2), ("alignment", 2), ("open weights", 2),
        ("parameter", 2), ("transformer", 2), ("pytorch", 2), ("preview", 1),
        ("research", 1), ("state-of-the-art", 2), ("ag", 1), ("diffusion", 1),
    ],
    "products": [
        ("app", 2), ("sdk", 2), ("api", 2), ("product", 2), ("launch", 2),
        ("releases", 2), ("github", 2), ("repository", 2), ("framework", 2),
        ("dataset", 2), ("plugin", 2), ("extension", 2), ("open source", 2),
        ("open-source", 2), ("opensource", 2), ("tool", 2), ("openai", 1),
        ("available", 1), ("toolkit", 2), ("library", 1), ("sdks", 2),
    ],
}
# Tie-break priority when two categories score equally.
CATEGORY_PRIORITY = ["business", "agents", "models", "products"]

TOPIC_TAGS = {
    "Reasoning": ["reasoning", "chain-of-thought"],
    "Multimodal": ["multimodal", "vision-language", "text-to-image", "vlm"],
    "Coding": ["coding", "code generation", "code assistant", "code completion", "programming"],
    "Inference": ["inference", "latency", "quantization", "serving", "speculative decoding"],
    "Robotics": ["robot", "robotic", "robotics", "embodied", "humanoid"],
    "AI Safety": ["safety", "alignment", "interpretability", "jailbreak", "red team", "guardrail"],
    "Agents": ["agent", "agentic", "multi-agent", "computer use", "orchestration"],
    "LLMs": ["llm", "large language model", "language model", "gpt", "model"],
    "Training": ["training", "pretrain", "fine-tun", "distill", "synthetic data"],
    "Open Source": ["open source", "open-source", "open weights", "github", "repo"],
    "Speech": ["speech", "transcription", "tts", "voice", "audio", "asr"],
    "Vision": ["vision", "image", "video generation", "computer vision", "diffusion"],
    "Benchmarks": ["benchmark", "leaderboard", "state of the art", "state-of-the-art", "evals", "evaluation"],
    "Edge": ["edge", "on-device", "local model", "mobile", "small model"],
}
TOPIC_COUNT = 3

INDUSTRY_TAGS = {
    "Healthcare": ["health", "medical", "clinical", "fda", "patient", "hospital", "drug", "biotech", "pharma"],
    "Finance": ["finance", "financial", "bank", "trading", "insurance", "payment", "fintech"],
    "Legal": ["legal", "law", "lawyer", "court", "judge", "litigation", "compliance"],
    "Education": ["education", "school", "student", "teacher", "university", "classroom"],
    "Retail": ["retail", "e-commerce", "ecommerce", "commerce", "shopping", "advertis"],
    "Manufacturing": ["manufactur", "factory", "supply chain", "industrial", "warehouse", "logistics"],
    "Automotive": ["autonomous driving", "electric vehicle", "self-driving", "automotive", "vehicle"],
    "Government": ["government", "policy", "regulation", "lawmaker", "public sector", "defense"],
    "Security": ["security", "cyber", "hack", "breach", "ransomware", "vulnerability"],
    "Energy": ["energy", "power grid", "solar", "battery", "climate"],
    "Media": ["media", "publishing", "journalism", "newsroom"],
}
INDUSTRY_COUNT = 2

# Priority order matters: most specific first so e.g. "raises" -> Funding.
STORY_TYPE_RULES = [
    ("Acquisition", ["acquire", "acquisition", "acquired", "merger", "m&a", "buyout", "snaps up", "to buy"]),
    ("Funding", ["raises", "raised", "series ", "funding", "valuation", "investment round", "venture round"]),
    ("Hardware", ["chip", "gpu", "tpu", "nvidia", "silicon", "processor", "semiconductor", "data center", "compute cluster", "wafer"]),
    ("Partnership", ["partnership", "partner", "collaborat", "teams with", "joins forces", "alliance"]),
    ("Security", ["security", "hack", "breach", "vulnerability", "ransomware", "exploit", "jailbreak", "rogue", "malicious"]),
    ("Policy", ["regulation", "regulator", "government", "lawsuit", "court", "ban", "executive order", "ai act", "law"]),
    ("Breakthrough", ["breakthrough", "state-of-the-art", "state of the art", "milestone", "world's first", "solves"]),
    ("Benchmark", ["benchmark", "leaderboard", "sota", "outperform", "beats", "top of the"]),
    ("Research", ["research", "paper", "study", "experiment", "researchers", "preprint", "arxiv"]),
    ("Open Source", ["open source", "open-source", "open weights", "open-sourced", "open model", "open-weights"]),
    ("Repository", ["github", "repository", "trending", "repo"]),
    ("Release", ["releases", "release", "released", "out now", "publicly available", "rolls out"]),
    ("Launch", ["launch", "launches", "launched", "unveil", "debut", "introduces", "now available", "ship"]),
    ("Product Update", ["update", "adds", "adds support", "feature", "improves", "now lets", "upgrade"]),
]
DEFAULT_STORY_TYPE = "Product Update"

# Non-AI consumer/gaming content is always dropped, even from AI-branded feeds.
DROP_TERMS = [
    "coupon", "coupons", "promo", "promos", "discount", "discounts", "% off",
    "save up to", " off right now", "labor day", "black friday", "cyber monday",
    "price cut", "price cuts", "best deals", "savings", "deals", "promo code",
    "discount code", "coupon code", "video game", "videogame", "gameplay",
    "xbox", "playstation", "nintendo", "gaming", "console game",
]

# Source-name based trust levels for the AI-only gate. Feeds not in either list
# are keyword-gated on the item text.
TRUSTED_AI_FEEDS = {
    "techcrunch ai", "the verge ai", "mit tech review ai", "unite ai",
    "ai weekly", "ai news", "towards data science", "analytics vidhya",
    "kdnuggets", "synced review", "jiqizhixin", "reddit machinelearning",
    "reddit artificial", "reddit localllama", "reddit ai agents",
    "tldr ai", "the rundown ai", "latent space", "ben's bites",
    "hugging face daily papers", "hf trending models", "new agent repos",
    "hn agent stories", "marktechpost",
}
OFFICIAL_BLOGS = {
    "openai blog", "deepmind blog", "google ai blog", "hugging face blog",
}

# Source-name buckets powering the discovery sections (tool of the day,
# new agents). Matched case-insensitively against story source names.
# "New agents" = actual launches: fresh GitHub repos, agent stories trending on
# HN, and agent-category Launch/Release/Open-Source coverage. Reddit r/AI_Agents
# is community discussion (questions, showcase threads), so it feeds the general
# Agents category but is deliberately NOT a new-agent source.
NEW_AGENT_SOURCES = {"new agent repos", "hn agent stories"}
TOOL_OS_SOURCES = {"hf trending models", "github trending", "reddit localllama", "new agent repos"}
TOOL_FREEMIUM_SOURCES = {"product hunt"}

# Source weight buckets for importance scoring.
SOURCE_WEIGHTS = [
    (["openai", "deepmind", "anthropic", "hugging face", "huggingface", "google ai", "google deepmind"], 5),
    (["techcrunch", "the verge", "arstechnica", "ars technica", "mit technology review", "wired", "zdnet", "infoq"], 3),
]


def _source_weight(source_name: str) -> int:
    name = (source_name or "").lower()
    base = 2
    for prefixes, weight in SOURCE_WEIGHTS:
        if any(p in name for p in prefixes):
            base = weight
            break
    # Ranked-feed bonus: P1 sources are weighted a touch higher, and feeds with a
    # quality score >= 9 contribute a small extra nudge so the CSV ranking is
    # felt in the importance/tiering that drives the top of the digest.
    priority, quality = SOURCE_PRIORITY_BONUS.get(name, ("", 0))
    if priority == "P1":
        base += 1
    if quality >= 9:
        base += 1
    return max(1, min(6, base))


def _is_trusted_ai_feed(source_name: str, hint: str | None) -> bool:
    name = (source_name or "").strip().lower()
    hint = (hint or "").strip().lower()
    if hint == "research":
        return True
    if name in OFFICIAL_BLOGS or name in TRUSTED_AI_FEEDS:
        return True
    return False


def _is_droppable(text_l: str) -> bool:
    for term in DROP_TERMS:
        if re.search(r"\b" + re.escape(term) + r"\b", text_l):
            return True
    return False


def _passes_ai_gate(item: dict, source_name: str, hint: str | None) -> bool:
    """Absolute AI-only rule. Drop non-AI; keep AI-relevant or AI-branded feeds."""
    text_l = (item.get("title", "") + " " + item.get("summary", "")).lower()
    if _is_droppable(text_l):
        return False
    if _is_trusted_ai_feed(source_name, hint):
        return True
    return is_ai(item.get("title", "") + " " + item.get("summary", ""))


def _category_score(text_l: str) -> str:
    scores = {}
    for cat, rules in CATEGORY_SCORES.items():
        total = 0
        for term, weight in rules:
            if re.search(r"\b" + re.escape(term) + r"\b", text_l):
                total += weight
        scores[cat] = total
    best = max(scores.values())
    if best == 0:
        return "models"  # default: an AI story is usually about models
    for cat in CATEGORY_PRIORITY:  # priority order on ties
        if scores[cat] == best:
            return cat
    return "models"


def _extract_tags(text_l: str) -> list[str]:
    tags = []
    for tag, terms in TOPIC_TAGS.items():
        if any(t in text_l for t in terms):
            tags.append(tag)
        if len(tags) >= TOPIC_COUNT:
            break
    return tags


def _extract_industry(text_l: str) -> list[str]:
    found = []
    for tag, terms in INDUSTRY_TAGS.items():
        if any(t in text_l for t in terms):
            found.append(tag)
        if len(found) >= INDUSTRY_COUNT:
            break
    return found


def _story_type(text_l: str) -> str:
    for stype, terms in STORY_TYPE_RULES:
        if any(re.search(r"\b" + re.escape(t) + r"\b", text_l) for t in terms):
            return stype
    return DEFAULT_STORY_TYPE


def _importance(source_weight: int, source_count: int, text_l: str) -> int:
    score = source_weight
    if source_count >= 3:
        score += 2
    elif source_count == 2:
        score += 1
    boosts = ["release", "launch", "raises", "acquire", "breakthrough",
              "state-of-the-art", "state of the art"]
    hits = sum(1 for b in boosts if b in text_l)
    if hits >= 1:
        score += 1
    if hits >= 3:
        score += 1
    return max(1, min(5, score))


def canonical_url(url: str) -> str:
    link = (url or "").strip().lower().rstrip("/")
    parsed = urllib.parse.urlparse(link)
    return parsed._replace(query="", fragment="").geturl()


def cluster_items(items: list[dict]) -> list[list[dict]]:
    """Merge near-duplicate titles (across sources) into cluster groups."""
    clusters: list[list[dict]] = []
    labels: list[str] = []
    idx: dict[str, set[int]] = defaultdict(set)
    THRESHOLD = 0.78
    for item in items:
        nt = normalize_title(item.get("title", ""))
        url = canonical_url(item.get("link", ""))
        tokens = {t for t in nt.split() if len(t) >= 4}
        candidates: set[int] = set()
        for tok in tokens:
            candidates |= idx.get(tok, set())
        match = None
        for ci in candidates:
            if nt and difflib.SequenceMatcher(None, nt, labels[ci]).ratio() >= THRESHOLD:
                match = ci
                break
        if match is None and url:
            for ci, cluster in enumerate(clusters):
                if any(canonical_url(c.get("link", "")) == url for c in cluster):
                    match = ci
                    break
        if match is None:
            match = len(clusters)
            clusters.append([])
            labels.append(nt)
        clusters[match].append(item)
        for tok in tokens:
            idx[tok].add(match)
    return clusters


def _clean_body(item: dict) -> str:
    return clean_text(item.get("summary", "")) or clean_text(item.get("description", "")) or ""


def _iso_ts(epoch) -> str:
    try:
        epoch = float(epoch or 0)
    except (TypeError, ValueError):
        return ""
    if epoch <= 0:
        return ""
    return dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _fit_words(text: str, lo: int = 60, hi: int = 80) -> str:
    text = _WS_RE.sub(" ", text).strip().rstrip(".")
    words = text.split()
    if not words:
        return ""
    if len(words) <= hi:
        return text
    acc = []
    count = 0
    for sent in _sentences(text):
        n = len(sent.split())
        if count + n > hi and count >= lo:
            break
        acc.append(sent)
        count += n
    result = " ".join(acc).strip().rstrip(".")
    wlen = len(result.split())
    if wlen < lo or wlen > hi:  # no clean sentence boundary -> hard word cap
        result = " ".join(words[:hi]).rstrip(".,;:")
    return result


def _build_summary(cluster: list[dict]) -> str:
    pieces: list[str] = []
    for it in cluster:
        for field in ("summary", "description", "subtitle"):
            body = clean_text(it.get(field, ""))
            if body and len(body.split()) >= 5:
                pieces.append(body)
    if not pieces:  # rare: everything terse; use the longest available body
        all_bodies = [clean_text(it.get(f, "")) for it in cluster for f in ("summary", "description")]
        all_bodies = [b for b in all_bodies if b]
        if all_bodies:
            pieces.append(max(all_bodies, key=lambda b: len(b.split())))
    pieces.sort(key=lambda p: len(p.split()), reverse=True)
    kept: list[str] = []
    for p in pieces:
        if any(
            difflib.SequenceMatcher(None, normalize_title(p), normalize_title(q)).ratio() > 0.92
            for q in kept
        ):
            continue
        kept.append(p)
        if len(" ".join(kept).split()) >= 74:
            break
    if not kept:  # absolute fallback
        kept.append(clean_text(cluster[0].get("title", "")))
    return _fit_words(" ".join(kept), 60, 80)


def _subheadline(summary: str, headline: str) -> str:
    sents = _sentences(summary)
    base = sents[0] if sents else headline
    if len(base.split()) > 18:
        base = " ".join(base.split()[:18]).rstrip(".,;:")
    return base


def _pick_image(cluster: list[dict]) -> str | None:
    ordered = sorted(
        cluster,
        key=lambda it: _source_weight(it.get("source", "")),
        reverse=True,
    )
    for it in ordered:
        if it.get("image"):
            return it["image"]
    return None


def _slugify(text: str, seen: set[str]) -> str:
    base = normalize_title(text).replace(" ", "-").strip("-")[:48] or "story"
    slug = base
    n = 2
    while slug in seen:
        slug = f"{base}-{n}"
        n += 1
    seen.add(slug)
    return slug


def _why_it_matters(story_type: str, category: str) -> str:
    label = CATEGORY_LABELS[category]
    templates = {
        "Funding": f"Fresh capital reflects sustained investor appetite for {label}, which reshapes the competitive landscape.",
        "Acquisition": f"The deal consolidates {label} and signals how AI assets are now being valued.",
        "Hardware": f"Compute supply and infrastructure decisions here determine which {label} products become viable.",
        "Partnership": f"This alliance should expand where and how {label} is deployed for real users.",
        "Security": f"This exposes live risk surfaces for AI systems, raising the stakes on governance and safety.",
        "Policy": f"Regulatory movement sets the boundaries within which {label} can scale commercially.",
        "Breakthrough": f"A step change like this resets expectations for what is achievable in {label}.",
        "Benchmark": f"New results push the bar on what counts as the state of the art in {label}.",
        "Research": f"The work advances the {label} frontier, with downstream implications for real products.",
        "Open Source": f"An open release lowers adoption barriers and speeds iteration across the {label} ecosystem.",
        "Repository": f"A trending repository signals strong developer interest and rapid adoption within {label}.",
        "Release": f"A mainstream release broadens the practical reach of {label} beyond research circles.",
        "Launch": f"This launch expands the practical surface of {label} for everyday users and teams.",
        "Product Update": f"An incremental update keeps {label} capability moving forward for existing users.",
    }
    return templates.get(story_type, f"This is a signal of continued momentum in {label}.")


def _story_from_cluster(cluster: list[dict], seen_ids: set[str]) -> dict:
    def keyf(it):
        return (_source_weight(it.get("source", "")), len(clean_text(it.get("title", ""))))

    best = max(cluster, key=keyf)
    text_l = " ".join(
        clean_text(it.get("title", "")) + " " + _clean_body(it) for it in cluster
    ).lower()

    headline = clean_text(best.get("title", "")) or clean_text(cluster[-1].get("title", "")) or "Untitled story"
    summary = _build_summary(cluster)
    subheadline = _subheadline(summary, headline)
    category = _category_score(text_l)
    story_type = _story_type(text_l)
    tags = _extract_tags(text_l)
    industry = _extract_industry(text_l)
    source_count = len(cluster)
    importance = _importance(_source_weight(best.get("source", "")), source_count, text_l)

    sources = [
        {"name": it.get("source", ""), "url": it.get("link", ""), "published": _iso_ts(it.get("published", 0))}
        for it in cluster
        if it.get("link")
    ] or [{"name": best.get("source", ""), "url": best.get("link", ""), "published": _iso_ts(best.get("published", 0))}]

    published_epochs = [it.get("published", 0) for it in cluster]
    published_epochs = [e for e in published_epochs if e]
    first_epoch = min(published_epochs) if published_epochs else best.get("published", 0)

    sid = _slugify(headline, seen_ids)
    return {
        "id": sid,
        "headline": headline,
        "subheadline": subheadline,
        "summary": summary,
        "why_it_matters": _why_it_matters(story_type, category),
        "category": category,
        "tags": tags,
        "industry": industry,
        "story_type": story_type,
        "importance": importance,
        "tier": "standard",
        "sources": sources,
        "source_count": source_count,
        "image": _pick_image(cluster),
        "url": best.get("link", ""),
        "published_at": _iso_ts(first_epoch),
        "reading_time": f"{max(1, round(len(summary.split()) / 180))} min",
        "is_tool_of_day": False,
        "is_early_signal": False,
        "is_new_agent": (
            (category == "agents" and story_type in {"Launch", "Release", "Repository", "Open Source"})
            or any((x.get("name", "").lower() in NEW_AGENT_SOURCES) for x in sources)
        ),
        "is_whats_new": story_type in {
            "Launch", "Release", "Open Source", "Repository",
            "Benchmark", "Breakthrough",
        },
    }


def _pick_tools_of_day(stories: list[dict]) -> tuple[str | None, str | None]:
    """Pick the open-source and freemium 'AI Tool of the Day' stories."""
    tool_types = {"Repository", "Open Source", "Release", "Launch", "Product Update"}

    def src_in(s: dict, names: set) -> bool:
        return any((x.get("name", "").lower() in names) for x in s["sources"])

    pool = [s for s in stories if s["category"] == "products" and s["story_type"] in tool_types]
    os_c = [s for s in pool if src_in(s, TOOL_OS_SOURCES) or s["story_type"] in {"Open Source", "Repository"}]
    os_id = max(os_c, key=lambda s: s["importance"])["id"] if os_c else None
    fm_c = [s for s in pool if s["id"] != os_id and (src_in(s, TOOL_FREEMIUM_SOURCES) or s["story_type"] == "Launch")]
    fm_id = max(fm_c, key=lambda s: s["importance"])["id"] if fm_c else None
    return os_id, fm_id


def _pick_early_signal(stories: list[dict], exclude: str | None) -> str | None:
    candidates = []
    for s in stories:
        if s["id"] == exclude:
            continue
        if s["story_type"] in {"Benchmark", "Repository"}:
            candidates.append(s)
        elif s["importance"] >= 4 and s["source_count"] >= 2:
            candidates.append(s)
    if not candidates:
        return None
    return max(candidates, key=lambda s: s["importance"])["id"]


def _canonical_sort(stories: list[dict]) -> None:
    """In-place canonical order: grouped by category, real news before community
    chatter, each newest-first. Two stable sorts preserve reverse-chrono."""
    order = {c: i for i, c in enumerate(NEW_CATEGORIES)}
    stories.sort(key=lambda s: s.get("published_at") or "", reverse=True)
    stories.sort(key=lambda s: (order.get(s["category"], 9), 1 if s.get("is_community") else 0))


def _clean_plain(text: str, limit: int = MISTRAL_MAX_CHARS) -> str:
    """Enforce the plain-English contract: no em/en dashes, single line, and
    <=limit characters cut on a word boundary (ellipsis only if we trimmed)."""
    t = _WS_RE.sub(" ", (text or "")).strip()
    t = t.replace("\u2014", ",").replace("\u2013", "-")  # em dash -> comma, en dash -> hyphen
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > limit:
        cut = t[:limit].rsplit(" ", 1)[0].rstrip(" ,.:;")
        t = (cut + "\u2026") if len(cut) > 40 else cut
        if len(t) > limit:
            t = t[: limit - 1].rstrip(" ,.:;") + "\u2026"
    return t


def _mistral_chat(api_key: str, system: str, user: str) -> str | None:
    """One Mistral chat completion returning assistant text, or None on failure.
    Retries transient errors (429/5xx) with backoff, honoring Retry-After."""
    payload = {
        "model": MISTRAL_MODEL,
        "temperature": 0.2,
        "max_tokens": 1800,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    data = json.dumps(payload).encode("utf-8")
    url = MISTRAL_BASE.rstrip("/") + "/chat/completions"
    for attempt in range(3):
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=MISTRAL_TIMEOUT) as resp:
                body = json.loads(resp.read().decode("utf-8", "replace"))
            return body["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as exc:
            ra = exc.headers.get("Retry-After") if exc.headers else None
            if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(float(ra) if (ra or "").isdigit() else 3 * (attempt + 1))
                continue
            sys.stderr.write(f"[ai] Mistral HTTP {exc.code}\n")
            return None
        except Exception as exc:  # noqa: BLE001 - never fail the pipeline on AI
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            sys.stderr.write(f"[ai] Mistral error: {exc}\n")
            return None
    return None


_AI_SYSTEM = (
    "You rewrite AI news so a non-technical adult can understand it. Use simple, "
    "everyday words. No jargon or unexplained acronyms, and NEVER use em dashes or "
    "en dashes (use commas or periods instead). Be factual and neutral. Output only "
    "valid JSON, nothing else."
)


def _ai_batch_prompt(batch: list[dict]) -> str:
    lines = [
        "Rewrite each numbered item in plain English.",
        "'summary': one sentence, 120 characters or fewer, simple words, no em dashes.",
        "'tags': 3 to 5 short lowercase topic tags.",
        "'category': exactly one of agents, models, products, business.",
        'Return JSON shaped like: {"items":[{"i":0,"summary":"...",'
        '"tags":["..."],"category":"..."}]}',
        "Include one object per item with the matching integer i.",
        "",
        "Items:",
    ]
    for i, s in enumerate(batch):
        lines.append(f"[{i}] HEADLINE: {s.get('headline', '')}")
        ctx = _truncate(s.get("summary") or "", 280)
        if ctx:
            lines.append(f"    CONTEXT: {ctx}")
    return "\n".join(lines)


def apply_ai_summaries(stories: list[dict]) -> bool:
    """Rewrite summaries and add tags/labels/category via Mistral. Returns True
    if at least one batch succeeded. No-ops (keeping heuristic text) without a key."""
    api_key = os.environ.get("MISTRAL_API_KEY", "").strip()
    if not api_key:
        sys.stderr.write("[ai] MISTRAL_API_KEY not set; keeping heuristic summaries.\n")
        return False
    valid_cats = set(NEW_CATEGORIES)
    ok_any = False
    done = 0
    batches = [stories[i:i + MISTRAL_BATCH] for i in range(0, len(stories), MISTRAL_BATCH)]
    for bi, batch in enumerate(batches):
        content = _mistral_chat(api_key, _AI_SYSTEM, _ai_batch_prompt(batch))
        if not content:
            continue
        try:
            parsed = json.loads(content)
            items = parsed.get("items") if isinstance(parsed, dict) else parsed
            if not isinstance(items, list):
                continue
        except ValueError:
            sys.stderr.write(f"[ai] batch {bi} unparseable JSON; skipping.\n")
            continue
        by_i = {it["i"]: it for it in items if isinstance(it, dict) and isinstance(it.get("i"), int)}
        for i, s in enumerate(batch):
            it = by_i.get(i)
            if not it:
                continue
            summary = _clean_plain(it.get("summary", ""))
            if not summary:
                continue
            s["summary_original"] = s.get("summary", "")
            s["summary"] = summary
            s["subheadline"] = summary
            tags = [str(t).strip().lower() for t in (it.get("tags") or []) if str(t).strip()]
            if tags:
                s["tags"] = list(dict.fromkeys(tags))[:5]
            cat = (it.get("category") or "").strip().lower()
            if cat in valid_cats:
                s["category"] = cat
            # Always carry a label derived from the final category, even if the
            # model returned an out-of-enum value (we keep the heuristic one).
            s["labels"] = [s["category"]]
            ok_any = True
            done += 1
        time.sleep(0.4)  # gentle pacing between calls
    sys.stderr.write(
        f"[ai] rewrote {done}/{len(stories)} summaries via {MISTRAL_MODEL} (ok={ok_any}).\n"
    )
    return ok_any


def build_stories(items: list[dict]) -> tuple[list[dict], int, str | None, str | None]:
    """Apply the AI-only gate, cluster into stories, score + tier, pick highlights."""
    kept: list[dict] = []
    dropped = 0
    cutoff = time.time() - LOOKBACK_DAYS * 86400
    for it in items:
        pub = it.get("published", 0) or 0
        if pub and pub < cutoff:  # dated but outside the lookback window
            dropped += 1
            continue
        if _passes_ai_gate(it, it.get("source", ""), it.get("category_hint")):
            kept.append(it)
        else:
            dropped += 1

    clusters = cluster_items(kept)
    seen_ids: set[str] = set()
    stories = [_story_from_cluster(c, seen_ids) for c in clusters if c]

    # Community chatter (Reddit-only stories) is signal for discovery sections
    # but noise at the top of the news lists; flag it so lists can demote it
    # below real news while still ordering each group newest-first.
    for s in stories:
        srcs = s.get("sources") or []
        s["is_community"] = bool(srcs) and all(
            "reddit" in (x.get("name", "").lower()) for x in srcs
        )
        # Strip em/en dashes from headlines too, so all visible news prose is
        # dash-free (matches the plain-English summaries).
        s["headline"] = re.sub(r"\s+", " ", s["headline"].replace("\u2014", ",")
                               .replace("\u2013", "-")).replace(" ,", ",").strip()

    # Top-3 by importance are always "top" regardless of raw score.
    top3 = {s["id"] for s in sorted(stories, key=lambda s: s["importance"], reverse=True)[:3]}
    for s in stories:
        if s["importance"] >= 5 or s["id"] in top3:
            s["tier"] = "top"
        elif s["importance"] >= 4:
            s["tier"] = "major"
        else:
            s["tier"] = "standard"

    tool_os_id, tool_fm_id = _pick_tools_of_day(stories)
    tool_id = tool_fm_id or tool_os_id
    early_id = _pick_early_signal(stories, exclude=tool_id)
    for s in stories:
        s["is_tool_of_day"] = s["id"] == tool_id
        s["is_tool_opensource"] = s["id"] == tool_os_id
        s["is_tool_freemium"] = s["id"] == tool_fm_id
        s["is_early_signal"] = s["id"] == early_id

    _canonical_sort(stories)
    return stories, dropped, tool_id, early_id, tool_os_id, tool_fm_id


def write_json_output(stories: list[dict], tool_id, early_id, tool_os_id, tool_fm_id, date_str: str) -> Path:
    total_words = sum(len((s.get("summary") or "").split()) for s in stories)
    data = {
        "date": date_str,
        "edition": "The AI Daily",
        "platform": "SIGNAL",
        "stats": {"total": len(stories), "reading_time_min": max(1, round(total_words / 200))},
        "stories": stories,
        "tool_of_day": tool_id,
        "tool_of_day_opensource": tool_os_id,
        "tool_of_day_freemium": tool_fm_id,
        "early_signal": early_id,
    }
    data_dir = ROOT_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    daily_path = data_dir / f"{date_str}.json"
    daily_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    (data_dir / "latest.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return daily_path


FOOTER_TEXT = "made by Ali Husain Sorathiya's AI News Agent"

# Apple-inspired email palette + system SF-like font stack (web-safe fallbacks).
NL_FONT = "-apple-system,BlinkMacSystemFont,'SF Pro Text','Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"
NL_INK = "#1d1d1f"
NL_INK_SOFT = "#6e6e73"
NL_MUTED = "#86868b"
NL_ACCENT = "#0071e3"
NL_ACCENT_HOVER = "#0077ed"
NL_HAIRLINE = "#e8e8ed"
NL_HAIRLINE_STRONG = "#d2d2d7"
NL_BG = "#f5f5f7"
NL_CARD = "#ffffff"

# A single reusable cell style for the soft "surface" used behind feature blocks.
_NL_CARD = (
    f'border:1px solid {NL_HAIRLINE};border-radius:16px;'
    f'background:{NL_CARD};'
)


def _h(text) -> str:
    return html.escape(text or "")


def _section_label(category: str) -> str:
    return {
        "agents": "Agents",
        "models": "Models & Research",
        "products": "Products & Open Source",
        "business": "Business & Infrastructure",
    }.get(category, category.replace("_", " ").title())


def _nl_link(text: str, url: str, weight: int = 600) -> str:
    """Apple-style inline action link: blue, medium weight, no underline."""
    return (
        f'<a href="{_h(url)}" style="color:{NL_ACCENT};text-decoration:none;'
        f'font-weight:{weight};">{_h(text)}&nbsp;&rarr;</a>'
    )


def _newsletter_image(src: str, alt: str, w: int = 640) -> str:
    if not src:
        return ""
    return (
        f'<img src="{_h(src)}" width="{w}" alt="{_h(alt)}" '
        f'style="display:block;width:100%;max-width:{w}px;height:auto;border:0;border-radius:0;">'
    )


def _newsletter_caption(text: str) -> str:
    if not text:
        return ""
    return (
        f'<tr><td style="padding:10px 0 0 0;font-family:{NL_FONT};font-size:11px;'
        f'color:{NL_MUTED};line-height:1.4;">{_h(text)}</td></tr>'
    )


def _newsletter_story_block(story: dict, show_image: bool = True, numbered: bool = False) -> str:
    img = _newsletter_image(story.get("image", ""), story["headline"]) if show_image else ""
    img_rows = f'<tr><td style="padding:0 0 14px 0;">{img}</td></tr>' if img else ""
    caption = _newsletter_caption(story.get("headline", "")) if img else ""
    number = f'{story.get("importance", 0)}. ' if numbered else ''
    return (
        f"{img_rows}"
        f"{caption}"
        f'<tr><td style="padding:0 0 4px 0;font-family:{NL_FONT};font-size:15px;line-height:1.45;color:{NL_INK};font-weight:600;">'
        f'{_h(number)}{_h(story["headline"])}</td></tr>'
        f'<tr><td style="padding:0 0 6px 0;font-family:{NL_FONT};font-size:14px;line-height:1.55;color:{NL_INK_SOFT};">'
        f"{_h(story.get('summary',''))}</td></tr>"
        f'<tr><td style="padding:0 0 12px 0;font-family:{NL_FONT};font-size:12px;line-height:1.4;color:{NL_MUTED};">'
        f"<strong>Why it matters:</strong> {_h(story.get('why_it_matters',''))}</td></tr>"
        f'<tr><td style="padding:0 0 0 0;font-family:{NL_FONT};font-size:13px;line-height:1.4;">'
        f'{_nl_link("Read story", story.get("url", ""))}'
        f'<span style="color:{NL_HAIRLINE_STRONG};margin:0 8px;">&middot;</span>'
        f'<span style="color:{NL_INK_SOFT};">{_h(story.get("sources", [{}])[0].get("name", ""))}</span>'
        f'<span style="color:{NL_HAIRLINE_STRONG};margin:0 8px;">&middot;</span>'
        f'<span style="color:{NL_INK_SOFT};">{_h(story.get("reading_time", ""))}</span></td></tr>'
    )


def _newsletter_section_label(text: str) -> str:
    # Must be a <div>, not a <tr><td>: every call site embeds this inside an
    # open cell, and a <tr> inside a <td> breaks Gmail's table parser.
    return (
        f'<div style="margin:0 0 12px 0;font-family:{NL_FONT};font-size:12px;'
        f'letter-spacing:1.4px;color:{NL_ACCENT};font-weight:600;text-transform:uppercase;">{_h(text)}</div>'
    )


def _newsletter_meta_row(s: dict) -> str:
    return (
        f'<div style="font-family:{NL_FONT};font-size:12px;line-height:1.4;margin-top:10px;">'
        f'{_nl_link("Read story", s.get("url", ""))}'
        f'<span style="color:{NL_HAIRLINE_STRONG};margin:0 8px;">&middot;</span>'
        f'<span style="color:{NL_MUTED};">{_h(s.get("reading_time",""))}</span></div>'
    )


def build_newsletter_html(date: dt.date, stories: list[dict], tool_id, early_id) -> str:
    by_id = {s["id"]: s for s in stories}
    ordered = sorted(stories, key=_readability_key)
    big = ordered[0] if ordered else None
    used = {big["id"]} if big else set()
    if tool_id:
        used.add(tool_id)
    if early_id:
        used.add(early_id)

    top5 = [s for s in ordered if s["id"] not in used][:5]

    highlights_by_cat = {}
    for cat in NEW_CATEGORIES:
        cands = [s for s in ordered if s["category"] == cat and s["id"] not in used]
        if not cands:
            continue
        if cat == "products" and tool_id and tool_id in by_id:
            highlights_by_cat[cat] = by_id[tool_id]
        else:
            highlights_by_cat[cat] = cands[0]

    early = by_id.get(early_id) if early_id else None
    whats_next = [
        s for s in stories
        if _future_phrases((s.get("headline", "") + " " + s.get("summary", "")).lower())
        and s["id"] not in used
    ][:2]

    date_str = date.strftime("%B %d, %Y")
    lines: list[str] = []
    a = lines.append

    # Preheader
    a('<div style="display:none;font-size:1px;color:#ffffff;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;">')
    a(f'The AI Daily — {date_str}. Your daily briefing on what changed in AI.')
    a('</div>')

    # Top bar (translucent-feeling light strip)
    a(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{NL_CARD};border-bottom:1px solid {NL_HAIRLINE};">')
    a('<tr><td align="center" style="padding:14px 0;">')
    a('<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="width:640px;max-width:640px;">')
    a(f'<tr><td style="font-family:{NL_FONT};font-size:13px;color:{NL_INK_SOFT};">')
    a(f'{date_str} &nbsp;&middot;&nbsp; <a href="https://alihusains.github.io/ai-latest-news/" style="color:{NL_ACCENT};text-decoration:none;font-weight:500;">Read online</a>')
    a('</td></tr></table></td></tr></table>')

    # Main container
    a(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{NL_BG};padding:28px 0;">')
    a('<tr><td align="center">')
    a('<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="width:640px;max-width:640px;">')

    # Masthead
    a(f'<tr><td style="padding:0 24px 20px 24px;">')
    a('<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
      f'<tr><td style="font-family:{NL_FONT};font-size:26px;font-weight:700;letter-spacing:-0.5px;color:{NL_INK};">'
      'THE&nbsp;AI&nbsp;DAILY'
      f'<span style="color:{NL_ACCENT};">.</span></td></tr>'
      f'<tr><td style="font-family:{NL_FONT};font-size:14px;color:{NL_MUTED};padding-top:4px;">'
      'Know what changed in AI, in five minutes.</td></tr></table>')
    a('</td></tr>')

    # Big story
    if big:
        a('<tr><td style="padding:0 24px 24px 24px;">')
        a(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="{_NL_CARD}">')
        if big.get("image"):
            a(f'<tr><td style="padding:0;">{_newsletter_image(big.get("image",""), big["headline"], w=640)}</td></tr>')
        a(f'<tr><td style="padding:22px 24px 24px 24px;">')
        a(_newsletter_section_label("The Big Story"))
        a(f'<div style="font-family:{NL_FONT};font-size:22px;font-weight:600;line-height:1.2;color:{NL_INK};letter-spacing:-0.3px;margin-bottom:10px;">{_h(big["headline"])}</div>')
        a(f'<div style="font-family:{NL_FONT};font-size:15px;line-height:1.55;color:{NL_INK_SOFT};margin-bottom:12px;">{_h(big.get("summary",""))}</div>')
        a(f'<div style="font-family:{NL_FONT};font-size:13px;line-height:1.5;color:{NL_MUTED};margin-bottom:14px;"><strong>Why it matters:</strong> {_h(big.get("why_it_matters",""))}</div>')
        a(f'<div style="font-family:{NL_FONT};font-size:13px;line-height:1.4;">{_nl_link("Read the full story", big.get("url",""), 600)}'
          f'<span style="color:{NL_HAIRLINE_STRONG};margin:0 8px;">&middot;</span>'
          f'<span style="color:{NL_INK_SOFT};">{_h(big.get("reading_time",""))}</span>'
          f'<span style="color:{NL_HAIRLINE_STRONG};margin:0 8px;">&middot;</span>'
          f'<span style="color:{NL_INK_SOFT};">{_h(big.get("sources",[{}])[0].get("name",""))}</span></div>')
        a('</td></tr></table></td></tr>')

    # 5 THINGS
    if top5:
        a('<tr><td style="padding:0 24px 20px 24px;">')
        a(_newsletter_section_label("5 Things You Should Know"))
        a('</td></tr>')
        for i, s in enumerate(top5, 1):
            a('<tr><td style="padding:0 24px 14px 24px;">')
            a(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="{_NL_CARD}">')
            a('<tr><td style="padding:18px 22px;">')
            a(f'<div style="font-family:{NL_FONT};font-size:15px;font-weight:600;color:{NL_INK};margin-bottom:6px;">{i}. {_h(s["headline"])}</div>')
            a(f'<div style="font-family:{NL_FONT};font-size:13px;line-height:1.55;color:{NL_INK_SOFT};">{_h(s.get("summary",""))}</div>')
            a(_newsletter_meta_row(s))
            a('</td></tr></table></td></tr>')

    # Category highlights
    for cat in NEW_CATEGORIES:
        s = highlights_by_cat.get(cat)
        if not s:
            continue
        a('<tr><td style="padding:0 24px 20px 24px;">')
        a(_newsletter_section_label(_section_label(cat)))
        a('</td></tr>')
        a('<tr><td style="padding:0 24px 24px 24px;">')
        a(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="{_NL_CARD}">')
        if s.get("image"):
            a(f'<tr><td style="padding:0;">{_newsletter_image(s.get("image",""), s["headline"], w=640)}</td></tr>')
        a('<tr><td style="padding:18px 22px 20px 22px;">')
        a(f'<div style="font-family:{NL_FONT};font-size:16px;font-weight:600;color:{NL_INK};margin-bottom:6px;">{_h(s["headline"])}</div>')
        a(f'<div style="font-family:{NL_FONT};font-size:13px;line-height:1.55;color:{NL_INK_SOFT};">{_h(s.get("summary",""))}</div>')
        a(_newsletter_meta_row(s))
        a('</td></tr></table></td></tr>')

    # New AI agents
    new_agents = [s for s in ordered if s.get("is_new_agent") and s["id"] not in used][:3]
    if new_agents:
        a('<tr><td style="padding:0 24px 20px 24px;">')
        a(_newsletter_section_label("New AI Agents"))
        a('</td></tr>')
        for s in new_agents:
            a('<tr><td style="padding:0 24px 14px 24px;">')
            a(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="{_NL_CARD}">')
            a('<tr><td style="padding:16px 22px;">')
            a(f'<div style="font-family:{NL_FONT};font-size:14px;font-weight:600;color:{NL_INK};margin-bottom:4px;">{_h(s["headline"])}</div>')
            a(f'<div style="font-family:{NL_FONT};font-size:12px;line-height:1.4;">{_nl_link("Read story", s.get("url",""))}</div>')
            a('</td></tr></table></td></tr>')

    # Early signal
    if early:
        a('<tr><td style="padding:0 24px 20px 24px;">')
        a(_newsletter_section_label("Early Signal"))
        a('</td></tr>')
        a('<tr><td style="padding:0 24px 24px 24px;">')
        a(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="{_NL_CARD}">')
        a('<tr><td style="padding:18px 22px;">')
        a(f'<div style="font-family:{NL_FONT};font-size:15px;font-weight:600;color:{NL_INK};margin-bottom:6px;">{_h(early["headline"])}</div>')
        a(f'<div style="font-family:{NL_FONT};font-size:13px;line-height:1.55;color:{NL_INK_SOFT};">{_h(early.get("why_it_matters",""))}</div>')
        a('</td></tr></table></td></tr>')

    # What's next
    if whats_next:
        a('<tr><td style="padding:0 24px 20px 24px;">')
        a(_newsletter_section_label("What's Next"))
        a('</td></tr>')
        for s in whats_next:
            a(f'<tr><td style="padding:0 24px 10px 24px;font-family:{NL_FONT};font-size:14px;color:{NL_INK};line-height:1.5;">')
            a(f'&bull; <a href="{_h(s.get("url",""))}" style="color:{NL_ACCENT};text-decoration:none;font-weight:600;">{_h(s["headline"])}</a>')
            a('</td></tr>')

    # Footer
    a(f'<tr><td style="padding:8px 24px 0 24px;border-top:1px solid {NL_HAIRLINE};">')
    a(f'<div style="font-family:{NL_FONT};font-size:11px;color:{NL_INK_SOFT};line-height:1.6;padding-top:20px;">{FOOTER_TEXT}</div>')
    a(f'<div style="font-family:{NL_FONT};font-size:11px;color:{NL_MUTED};line-height:1.6;margin-top:6px;padding-bottom:28px;">')
    a(f'&copy; {date.year} SIGNAL. All rights reserved.')  # Buttondown's Portal auto-adds the real unsubscribe link
    a('</div></td></tr>')

    a('</table>')
    a('</td></tr>')
    a('</table>')

    return "\n".join(lines)


def _newsletter_button(url: str, label: str = "Read story") -> str:
    # Apple-style pill button (blue fill, white text, full-radius).
    return (
        '<tr><td style="padding:14px 40px 0 40px;">'
        '<table role="presentation" cellspacing="0" cellpadding="0"><tr><td '
        f'style="border-radius:999px;background:{NL_ACCENT};">'
        f'<a href="{_h(url)}" style="display:inline-block;padding:11px 24px;color:#ffffff;'
        f'font-family:{NL_FONT};font-size:14px;font-weight:600;text-decoration:none;border-radius:999px;">{_h(label)}</a>'
        f"</td></tr></table></td></tr>"
    )


def _future_phrases(text: str) -> bool:
    return any(
        p in text
        for p in [
            "will", "next week", "next month", "upcoming", "expected",
            "set to", "later this", "on the horizon", "plans to", "scheduled",
            "in the coming", "due to",
        ]
    )


def _readability_key(s: dict):
    """Rank for newsletter display: prefer stories with 60-80-word summaries
    so featured items read well (spec: each featured item is 60-80 words)."""
    w = len(s.get("summary", "").split())
    band = 0 if 60 <= w <= 80 else (1 if w >= 40 else 2)
    return (band, -s.get("importance", 0), -w)


def write_newsletter(date: dt.date, stories: list[dict], tool_id, early_id) -> Path:
    html_str = build_newsletter_html(date, stories, tool_id, early_id)
    doc = (
        '<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml">'
        '<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="x-apple-disable-message-reformatting">'
        '<title>THE AI DAILY</title></head>'
        f'<body style="margin:0;padding:0;background:{NL_BG};">{html_str}</body></html>'
    )
    news_dir = ROOT_DIR / "newsletter"
    news_dir.mkdir(parents=True, exist_ok=True)
    path = news_dir / f"{date.isoformat()}.html"
    path.write_text(doc, encoding="utf-8")
    return path


def _priority_cap(per_source_limit: int, source: dict) -> int | None:
    """Resolve the per-source item cap for one source.

    ``0`` means "no cap" (return None). Otherwise the base limit is scaled by
    the ranking priority (P1 full, P2 ~2/3, P3 ~40%) so the ranked feed CSV
    actively shapes content volume; API/discovery sources keep the base limit.
    """
    if per_source_limit == 0:
        return None
    base = per_source_limit if per_source_limit else DEFAULT_PER_SOURCE
    if source.get("csv"):
        mult = PRIORITY_MULT.get((source.get("priority") or "P2").strip().upper(), 1.0)
        return max(3, int(base * mult))
    return base


def fetch_all(config_path: Path, per_source_limit: int | None,
              feeds_csv: Path | None = None) -> list[dict]:
    sources = load_sources(config_path, feeds_csv or RANKED_FEEDS_CSV)
    items: list[dict] = []
    last_reddit = 0.0
    for source in sources:
        name = source.get("name", "?")
        sys.stderr.write(f"[fetch] {name}\n")
        if "reddit.com" in (source.get("url") or ""):
            # Reddit throttles unauthenticated feeds to ~1 request / 10 s / IP.
            wait = 20 - (time.time() - last_reddit)
            if wait > 0:
                time.sleep(wait)
            last_reddit = time.time()
        fetched = fetch_source(source)
        if not fetched and "reddit.com" in (source.get("url") or ""):
            # One polite retry after a longer backoff (transient 429s).
            time.sleep(30)
            last_reddit = time.time()
            fetched = fetch_source(source)
        cap = _priority_cap(per_source_limit, source)
        if cap:
            fetched = fetched[:cap]
        for it in fetched:
            it["category_hint"] = source.get("category_hint")
            it["feed_priority"] = source.get("priority")
            it["feed_quality"] = source.get("quality_score")
            items.append(it)
    return items


# --------------------------------------------------------------------------- #
# Source loading: ranked OPML feed CSV (ai_news_feeds_ranked.csv) + sources.yaml
# --------------------------------------------------------------------------- #
# Canonical config files.
RANKED_FEEDS_CSV = ROOT_DIR / "ai_news_feeds_ranked.csv"

# OPML group -> category_hint used by the classifier.
_GROUP_HINTS = {
    "01_core_labs_and_model_releases": "research",
    "02_editorial_and_news_aggregators": "news",
    "03_research_and_papers": "research",
    "04_medical_and_health_ai": "medical",
    "05_ai_for_science": "science",
    "06_incidents_safety_policy": "community",
    "07_ai_engineer_and_newsletters": "newsletter",
    "08_devtools_and_github_trending": "open-source",
}

# Priority -> per-source fetch cap multiplier. P1 feeds are allowed to
# contribute more items; P3 (niche/specialised) feeds contribute fewer so they
# cannot flood the digest with low-signal items.
PRIORITY_MULT = {"P1": 1.0, "P2": 0.65, "P3": 0.4}

# Populated by load_sources_from_csv: source name -> (priority, quality_score).
# Used by _source_weight so high-priority / high-quality feeds nudge importance.
SOURCE_PRIORITY_BONUS: dict[str, tuple[str, int]] = {}


def _csv_int(value: str | int | float, default: int) -> int:
    if isinstance(value, (int, float)):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default
    try:
        return int(float((value or "").strip()))
    except (TypeError, ValueError):
        return default


def _register_source_ranking(csv_sources: list[dict]) -> None:
    """Record CSV priority/quality per source name for downstream weighting."""
    SOURCE_PRIORITY_BONUS.clear()
    for s in csv_sources:
        name = (s.get("name") or "").strip().lower()
        if not name:
            continue
        SOURCE_PRIORITY_BONUS[name] = (
            (s.get("priority") or "P2").strip().upper(),
            max(1, min(10, _csv_int(s.get("quality_score"), 7))),
        )


def load_sources_from_csv(csv_path: Path) -> list[dict]:
    """Build source entries from the ranked OPML feed CSV.

    Every row is a feed URL; they map 1:1 to an RSS source. The rank,
    quality_score and priority columns are attached so the pipeline can apply
    priority-based caps and weight importance accordingly.
    """
    import csv as _csv

    sources: list[dict] = []
    text = csv_path.read_text(encoding="utf-8")
    rows = list(_csv.DictReader(text.splitlines()))
    for n, row in enumerate(rows, 1):
        name = (row.get("feed_name") or "").strip() or f"Feed {n}"
        url = (row.get("feed_url") or "").strip()
        if not url:
            continue
        group = " ".join((row.get("category") or row.get("group") or "").replace("_", " ").lower().split())
        sources.append({
            "name": name,
            "type": "rss",
            "url": url,
            "category_hint": _GROUP_HINTS.get(group.replace(" ", "_"), "news"),
            "priority": (row.get("priority") or "P2").strip().upper(),
            "quality_score": max(1, min(10, _csv_int(row.get("quality_score"), 7))),
            "rank": max(1, _csv_int(row.get("rank"), n)),
            "csv": True,
            "active": True,
        })
    _register_source_ranking(sources)
    return sources


def load_sources(config_path: Path, feeds_csv: Path | None = RANKED_FEEDS_CSV) -> list[dict]:
    """Merge the ranked OPML feed CSV with the API/web sources in sources.yaml.

    - The CSV is the source of truth for RSS feeds (ranked, priority-weighted).
    - sources.yaml supplies the non-RSS discovery/API sources (Reddit, HF
      papers/models, Product Hunt, GitHub Trending scrape, GitHub + HN search)
      that power the "AI Tool of the Day" and "New AI Agents" sections and are
      not part of the OPML. Any RSS source in sources.yaml that duplicates a
      CSV feed URL is dropped (the CSV ranking wins).
    """
    yaml_sources: list[dict] = []
    if config_path.exists():
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        yaml_sources = [s for s in data.get("sources", []) if s.get("active", True)]

    csv_sources = load_sources_from_csv(feeds_csv) if feeds_csv and feeds_csv.exists() else []

    csv_urls = {canonical_url(s.get("url", "")) for s in csv_sources}
    merged = list(csv_sources)
    for s in yaml_sources:
        if (s.get("type") or "").strip().lower() != "rss":
            merged.append(s)  # API/discovery sources are always kept
            continue
        if canonical_url(s.get("url", "")) in csv_urls:
            continue  # CSV feed wins for identical RSS URLs
        merged.append(s)
    return merged


def build_legacy_digest_items(items: list[dict]) -> list[dict]:
    """Keep the old 8-category markdown digest working during the transition."""
    deduped = dedupe(items)
    for item in deduped:
        item["category"] = normalize_category(
            classify(item.get("title", ""), item.get("summary", ""), item.get("category_hint"))
        )
        item["summary_text"] = summarize(item)
    return deduped


# Default cap of items taken per source so feeds with a long archive don't
# flood the digest. `--limit 0` disables the cap (fetch everything).
DEFAULT_PER_SOURCE = 25


def normalize_category(cat: str) -> str:
    cat = (cat or "").strip()
    # map any non-canonical hint-like value to its canonical form
    canonical = HINT_MAP.get(cat.lower())
    if canonical:
        return canonical
    # title-case cleanups e.g. "open source" -> "Open Source"
    for c in CATEGORIES:
        if cat.lower() == c.lower():
            return c
    return "IT"


def write_digest(items: list[dict], date: dt.date) -> Path:
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    path = DAILY_DIR / f"{date.isoformat()}.md"
    path.write_text(render(items, date.isoformat()), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI news aggregator pipeline")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--feeds", type=Path, default=RANKED_FEEDS_CSV,
                        help="ranked OPML feed CSV (default: ai_news_feeds_ranked.csv)")
    parser.add_argument("--date", help="override date as YYYY-MM-DD")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_PER_SOURCE,
        help=f"max items per source (default {DEFAULT_PER_SOURCE}; 0 = no limit)",
    )
    parser.add_argument("--check", action="store_true", help="verify source URLs return 200")
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="skip Mistral plain-English rewriting (use heuristic summaries)",
    )
    args = parser.parse_args(argv)

    if args.check:
        total = 0
        ok = 0
        for source in load_sources(args.config, args.feeds):
            name = source.get("name", "?")
            url = source.get("url", "")
            total += 1
            good = response_ok(url)
            ok += good
            print(f"{'OK ' if good else 'FAIL'} {name}: {url}")
        print(f"\n{ok}/{total} sources reachable")
        return 0 if ok == total else 1

    date = dt.date.today()
    if args.date:
        date = dt.date.fromisoformat(args.date)

    items = fetch_all(args.config, args.limit, args.feeds)

    # Legacy markdown digest (keep working during transition).
    legacy = build_legacy_digest_items(items)
    md_path = write_digest(legacy, date)
    sys.stderr.write(f"[done] wrote markdown {md_path} ({len(legacy)} items)\n")

    # Pipeline v2: AI-only filter, clustering, ranking, JSON, newsletter.
    stories, dropped, tool_id, early_id, tool_os_id, tool_fm_id = build_stories(items)

    # AI pass: plain-English summaries (<=120 chars), tags, labels, category.
    # Re-sort afterwards because the model may refine a story's category.
    if not args.no_ai:
        if apply_ai_summaries(stories):
            _canonical_sort(stories)

    json_path = write_json_output(stories, tool_id, early_id, tool_os_id, tool_fm_id, date.isoformat())
    news_path = write_newsletter(date, stories, tool_id, early_id)

    counts: dict[str, int] = defaultdict(int)
    for s in stories:
        counts[s["category"]] += 1
    per_cat = ", ".join(f"{c}={counts.get(c, 0)}" for c in NEW_CATEGORIES)
    print(f"Wrote markdown {md_path} ({len(legacy)} items).")
    print(f"Wrote JSON {json_path} (stories={len(stories)}, dropped_by_filter={dropped}).")
    print(f"Wrote newsletter {news_path}.")
    print(f"Category breakdown: {per_cat}")
    sys.stderr.write(
        f"[done] stories={len(stories)} dropped={dropped} "
        f"tool_of_day={tool_id} early_signal={early_id}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
