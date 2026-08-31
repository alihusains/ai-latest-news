#!/usr/bin/env python3
"""AI Latest News aggregator pipeline.

Fetches news from configured sources (RSS, Reddit, web scrape, X/nitter),
then runs: fetch -> dedupe -> classify -> clean -> summarize -> render markdown.

Usage:
    python main.py                     # build today's digest
    python main.py --date 2026-08-28   # force a date
    python main.py --limit 5           # max items per source (quick tests)
    python main.py --config other.yaml # alternate source config
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import email.utils
import html
import json
import re
import sys
import time
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
    if not desc:
        # Atom feeds (e.g. Product Hunt) carry the blurb in <content> only.
        raw_content = text("content")
        if raw_content:
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
    return {
        "title": title,
        "link": link.strip(),
        "summary": desc,
        "image": image or None,
        "published": _parse_time(published),
        "date": published,
    }


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
            summary = (
                entry.get("summary", "")
                or entry.get("description", "")
                or entry.get("subtitle", "")
            )
            if not summary and entry.get("content"):
                summary = entry["content"][0].get("value", "")
            published = entry.get("published", "") or entry.get("updated", "")
            item = {
                "title": title,
                "link": link,
                "summary": summary,
                "image": _feedparser_image(entry),
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
                "published": 0,
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
NEW_AGENT_SOURCES = {"new agent repos", "hn agent stories", "reddit ai agents"}
TOOL_OS_SOURCES = {"hf trending models", "github trending", "reddit localllama", "new agent repos"}
TOOL_FREEMIUM_SOURCES = {"product hunt"}

# Source weight buckets for importance scoring.
SOURCE_WEIGHTS = [
    (["openai", "deepmind", "anthropic", "hugging face", "huggingface", "google ai", "google deepmind"], 5),
    (["techcrunch", "the verge", "arstechnica", "ars technica", "mit technology review", "wired", "zdnet", "infoq"], 3),
]


def _source_weight(source_name: str) -> int:
    name = (source_name or "").lower()
    for prefixes, weight in SOURCE_WEIGHTS:
        if any(p in name for p in prefixes):
            return weight
    return 2


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


def build_stories(items: list[dict]) -> tuple[list[dict], int, str | None, str | None]:
    """Apply the AI-only gate, cluster into stories, score + tier, pick highlights."""
    kept: list[dict] = []
    dropped = 0
    for it in items:
        if _passes_ai_gate(it, it.get("source", ""), it.get("category_hint")):
            kept.append(it)
        else:
            dropped += 1

    clusters = cluster_items(kept)
    seen_ids: set[str] = set()
    stories = [_story_from_cluster(c, seen_ids) for c in clusters if c]

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

    order = {c: i for i, c in enumerate(NEW_CATEGORIES)}
    stories.sort(key=lambda s: (order.get(s["category"], 9), -s["importance"]))
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


def _h(text) -> str:
    return html.escape(text or "")


def _section_label(category: str) -> str:
    return {
        "agents": "AGENTS",
        "models": "MODELS & RESEARCH",
        "products": "PRODUCTS & OPEN SOURCE",
        "business": "BUSINESS & INFRASTRUCTURE",
    }.get(category, category.upper())


def _newsletter_image(src: str, alt: str, w: int = 640) -> str:
    if not src:
        return ""
    return (
        f'<img src="{_h(src)}" width="{w}" alt="{_h(alt)}" '
        f'style="display:block;width:100%;max-width:{w}px;height:auto;border:0;border-radius:12px;">'
    )


def _newsletter_caption(text: str) -> str:
    if not text:
        return ""
    return (
        f'<tr><td style="padding:8px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:11px;'
        f'color:#6b7280;font-style:italic;line-height:1.4;">{_h(text)}</td></tr>'
    )


def _newsletter_story_block(story: dict, show_image: bool = True, numbered: bool = False) -> str:
    img = _newsletter_image(story.get("image", ""), story["headline"]) if show_image else ""
    img_rows = f'<tr><td style="padding:16px 0 0 0;">{img}</td></tr>' if img else ""
    caption = _newsletter_caption(story.get("headline", "")) if img else ""
    number = f'{story.get("importance", 0)}. ' if numbered else ''
    return (
        f"{img_rows}"
        f"{caption}"
        f'<tr><td style="padding:12px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5;color:#111827;">'
        f'<strong>{_h(number)}{_h(story["headline"])}</strong></td></tr>'
        f'<tr><td style="padding:6px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5;color:#374151;">'
        f"{_h(story.get('summary',''))}</td></tr>"
        f'<tr><td style="padding:8px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.4;color:#6b7280;">'
        f"<strong>Why it matters:</strong> {_h(story.get('why_it_matters',''))}</td></tr>"
        f'<tr><td style="padding:8px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.4;">'
        f'<a href="{_h(story.get("url", ""))}" style="color:#146DE9;text-decoration:none;font-weight:600;">Read story →</a>'
        f'<span style="color:#9ca3af;margin:0 6px;">·</span>'
        f'<span style="color:#6b7280;">{_h(story.get("sources", [{}])[0].get("name", ""))}</span>'
        f'<span style="color:#9ca3af;margin:0 6px;">·</span>'
        f'<span style="color:#6b7280;">{_h(story.get("reading_time", ""))}</span></td></tr>'
    )


def _newsletter_section_label(text: str) -> str:
    # Must be a <div>, not a <tr><td>: every call site embeds this inside an
    # open cell, and a <tr> inside a <td> breaks Gmail's table parser.
    return (
        f'<div style="margin:0 0 8px 0;font-family:Arial,Helvetica,sans-serif;font-size:11px;'
        f'letter-spacing:1.5px;color:#008A37;font-weight:bold;text-transform:uppercase;">{_h(text)}</div>'
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

    # Top bar
    a('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;border-bottom:1px solid #e5e7eb;">')
    a('<tr><td align="center" style="padding:12px 0;">')
    a('<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="width:640px;max-width:640px;">')
    a('<tr><td style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#374151;">')
    a(f'{date_str} &nbsp;&middot;&nbsp; <a href="https://alihusains.github.io/ai-latest-news/" style="color:#146DE9;text-decoration:none;">Read online</a>')
    a('</td></tr></table></td></tr></table>')

    # Main container
    a('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f9fafb;padding:24px 0;">')
    a('<tr><td align="center">')
    a('<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="width:640px;max-width:640px;background:#ffffff;border:1px solid #CFD9DF;border-radius:12px;overflow:hidden;">')

    # Masthead
    a('<tr><td style="padding:28px 24px 20px 24px;border-bottom:1px solid #e5e7eb;">')
    a('<div style="font-family:Georgia,serif;font-size:28px;font-weight:bold;letter-spacing:2px;color:#111827;">THE AI DAILY</div>')
    a('<div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#6b7280;margin-top:6px;">Know what changed in AI.</div>')
    a('</td></tr>')

    # Big story
    if big:
        a('<tr><td style="padding:24px 24px 0 24px;">')
        a('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #CFD9DF;border-radius:12px;overflow:hidden;">')
        if big.get("image"):
            a(f'<tr><td style="padding:0;">{_newsletter_image(big.get("image",""), big["headline"], w=640)}</td></tr>')
        a('<tr><td style="padding:20px 20px 16px 20px;">')
        a(_newsletter_section_label("THE BIG STORY"))
        a(f'<div style="font-family:Georgia,serif;font-size:22px;font-weight:bold;line-height:1.25;color:#111827;margin-top:8px;">{_h(big["headline"])}</div>')
        a(f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5;color:#374151;margin-top:10px;">{_h(big.get("summary",""))}</div>')
        a(f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.4;color:#6b7280;margin-top:10px;"><strong>Why it matters:</strong> {_h(big.get("why_it_matters",""))}</div>')
        a(f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.4;margin-top:12px;">')
        a(f'<a href="{_h(big.get("url",""))}" style="color:#146DE9;text-decoration:none;font-weight:600;">Read the full story →</a>')
        a(f'<span style="color:#9ca3af;margin:0 8px;">·</span>')
        a(f'<span style="color:#6b7280;">{_h(big.get("reading_time",""))}</span>')
        a(f'<span style="color:#9ca3af;margin:0 8px;">·</span>')
        a(f'<span style="color:#6b7280;">{_h(big.get("sources",[{}])[0].get("name",""))}</span>')
        a('</div></td></tr></table></td></tr>')

    # 5 THINGS
    if top5:
        a('<tr><td style="padding:24px 24px 0 24px;">')
        a(_newsletter_section_label("5 THINGS YOU SHOULD KNOW"))
        a('</td></tr>')
        for i, s in enumerate(top5, 1):
            a('<tr><td style="padding:0 24px;">')
            a('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #CFD9DF;border-radius:12px;overflow:hidden;margin-bottom:12px;">')
            a('<tr><td style="padding:16px 20px;">')
            a(f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;font-weight:bold;color:#111827;margin-bottom:6px;">{i}. {_h(s["headline"])}</div>')
            a(f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.5;color:#374151;">{_h(s.get("summary",""))}</div>')
            a(f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.4;margin-top:8px;">')
            a(f'<a href="{_h(s.get("url",""))}" style="color:#146DE9;text-decoration:none;font-weight:600;">Read story →</a>')
            a(f'<span style="color:#9ca3af;margin:0 6px;">·</span>')
            a(f'<span style="color:#6b7280;">{_h(s.get("reading_time",""))}</span>')
            a('</div></td></tr></table></td></tr>')

    # Category highlights
    for cat in NEW_CATEGORIES:
        s = highlights_by_cat.get(cat)
        if not s:
            continue
        a('<tr><td style="padding:24px 24px 0 24px;">')
        a(_newsletter_section_label(_section_label(cat)))
        a('</td></tr>')
        a('<tr><td style="padding:0 24px 24px 24px;">')
        a('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #CFD9DF;border-radius:12px;overflow:hidden;">')
        if s.get("image"):
            a(f'<tr><td style="padding:0;">{_newsletter_image(s.get("image",""), s["headline"], w=640)}</td></tr>')
        a('<tr><td style="padding:16px 20px;">')
        a(f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;font-weight:bold;color:#111827;margin-bottom:6px;">{_h(s["headline"])}</div>')
        a(f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.5;color:#374151;">{_h(s.get("summary",""))}</div>')
        a(f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.4;margin-top:8px;">')
        a(f'<a href="{_h(s.get("url",""))}" style="color:#146DE9;text-decoration:none;font-weight:600;">Read story →</a>')
        a(f'<span style="color:#9ca3af;margin:0 6px;">·</span>')
        a(f'<span style="color:#6b7280;">{_h(s.get("reading_time",""))}</span>')
        a('</div></td></tr></table></td></tr>')

    # New AI agents
    new_agents = [s for s in ordered if s.get("is_new_agent") and s["id"] not in used][:3]
    if new_agents:
        a('<tr><td style="padding:24px 24px 0 24px;">')
        a(_newsletter_section_label("NEW AI AGENTS"))
        a('</td></tr>')
        for s in new_agents:
            a('<tr><td style="padding:0 24px;">')
            a('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
              'style="border:1px solid #CFD9DF;border-radius:12px;overflow:hidden;margin-bottom:12px;">')
            a('<tr><td style="padding:14px 20px;">')
            a(f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;font-weight:bold;'
              f'color:#111827;margin-bottom:4px;">{_h(s["headline"])}</div>')
            a(f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.4;">'
              f'<a href="{_h(s.get("url",""))}" style="color:#146DE9;text-decoration:none;font-weight:600;">'
              f'Read story →</a></div>')
            a('</td></tr></table></td></tr>')

    # Early signal
    if early:
        a('<tr><td style="padding:24px 24px 0 24px;">')
        a(_newsletter_section_label("EARLY SIGNAL"))
        a('</td></tr>')
        a('<tr><td style="padding:0 24px 24px 24px;">')
        a('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #CFD9DF;border-radius:12px;overflow:hidden;">')
        a('<tr><td style="padding:16px 20px;">')
        a(f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;font-weight:bold;color:#111827;margin-bottom:6px;">{_h(early["headline"])}</div>')
        a(f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.5;color:#374151;">{_h(early.get("why_it_matters",""))}</div>')
        a('</td></tr></table></td></tr>')

    # What's next
    if whats_next:
        a('<tr><td style="padding:24px 24px 0 24px;">')
        a(_newsletter_section_label("WHAT'S NEXT"))
        a('</td></tr>')
        for s in whats_next:
            a('<tr><td style="padding:0 24px 24px 24px;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#111827;line-height:1.5;">')
            a(f'&bull; <a href="{_h(s.get("url",""))}" style="color:#146DE9;text-decoration:none;font-weight:600;">{_h(s["headline"])}</a>')
            a('</td></tr>')

    # Footer
    a('<tr><td style="padding:24px 24px 28px 24px;border-top:1px solid #e5e7eb;margin-top:16px;">')
    a(f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#6b7280;line-height:1.6;">{FOOTER_TEXT}</div>')
    a('<div style="font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#9ca3af;line-height:1.6;margin-top:6px;">')
    a(f'&copy; {date.year} SIGNAL. All rights reserved.')  # Buttondown's Portal auto-adds the real unsubscribe link
    a('</div></td></tr>')

    a('</table>')
    a('</td></tr>')
    a('</table>')

    return "\n".join(lines)


def _newsletter_button(url: str, label: str = "Read story") -> str:
    return (
        '<tr><td style="padding:14px 40px 0 40px;">'
        f'<table role="presentation" cellspacing="0" cellpadding="0"><tr><td '
        f'style="border-radius:6px;background:#2563eb;">'
        f'<a href="{_h(url)}" style="display:inline-block;padding:11px 22px;color:#ffffff;'
        f'font-family:Arial,Helvetica,sans-serif;font-size:14px;font-weight:bold;text-decoration:none;">{_h(label)}</a>'
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
        f'<body style="margin:0;padding:0;background:#f2f4f7;">{html_str}</body></html>'
    )
    news_dir = ROOT_DIR / "newsletter"
    news_dir.mkdir(parents=True, exist_ok=True)
    path = news_dir / f"{date.isoformat()}.html"
    path.write_text(doc, encoding="utf-8")
    return path


def fetch_all(config_path: Path, per_source_limit: int | None) -> list[dict]:
    sources = load_sources(config_path)
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
        if per_source_limit:
            fetched = fetched[:per_source_limit]
        for it in fetched:
            it["category_hint"] = source.get("category_hint")
            items.append(it)
    return items


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def load_sources(config_path: Path) -> list[dict]:
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    sources = data.get("sources", [])
    return [s for s in sources if s.get("active", True)]


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
    parser.add_argument("--date", help="override date as YYYY-MM-DD")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_PER_SOURCE,
        help=f"max items per source (default {DEFAULT_PER_SOURCE}; 0 = no limit)",
    )
    parser.add_argument("--check", action="store_true", help="verify source URLs return 200")
    args = parser.parse_args(argv)

    if args.check:
        total = 0
        ok = 0
        for source in load_sources(args.config):
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

    items = fetch_all(args.config, args.limit)

    # Legacy markdown digest (keep working during transition).
    legacy = build_legacy_digest_items(items)
    md_path = write_digest(legacy, date)
    sys.stderr.write(f"[done] wrote markdown {md_path} ({len(legacy)} items)\n")

    # Pipeline v2: AI-only filter, clustering, ranking, JSON, newsletter.
    stories, dropped, tool_id, early_id, tool_os_id, tool_fm_id = build_stories(items)
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
