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
    (
        "Medical",
        [
            "fda", "clinical", "disease", "patient", "drug", "biotech",
            "pharma", "hospital", "medtech", "healthcare", "vaccine",
            "cancer", "genome", "protein", "medical", "health",
            "treatment",
        ],
        ["therap", "diagnos", "pharmaceuti"],
    ),
    (
        "Acquisitions",
        [
            "acquisition", "acquire", "acquires", "acquired", "acquiring",
            "merger", "mergers", "m&a", "buyout", "takeover", "take over",
            "buy into", "to buy", "snaps up",
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
        [
            "physics", "chemistry", "biology", "quantum", "space", "astronomy",
            "climate", "telescope", "particle", "nobel", "experiment",
            "discovery", "science",
        ],
        ["scien"],
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
        elif stype == "reddit":
            items = _fetch_reddit(url)
        elif stype == "web":
            items = _fetch_web(url)
        elif stype == "x":
            items = _fetch_x(url)
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
    published = text("pubDate") or text("published") or text("updated")
    return {
        "title": title,
        "link": link.strip(),
        "summary": desc,
        "published": _parse_time(published),
        "date": published,
    }


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
            published = entry.get("published", "") or entry.get("updated", "")
            items.append(
                {
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "published": _parse_time(published),
                    "date": published,
                }
            )
    else:
        items = _parse_xml_items(raw)
    return items


def _fetch_reddit(url: str) -> list[dict]:
    raw = json.loads(http_get_text(url))
    children = (raw.get("data", {}).get("children", []) if isinstance(raw, dict) else [])
    items = []
    for child in children:
        data = child.get("data", {}) if isinstance(child, dict) else {}
        title = data.get("title", "")
        permalink = data.get("permalink", "")
        link = data.get("url", "") or permalink
        if permalink.startswith("/r/"):
            link = "https://old.reddit.com" + permalink
        created = data.get("created_utc", 0)
        items.append(
            {
                "title": title,
                "link": link,
                "summary": data.get("selftext", "") or data.get("title", ""),
                "published": float(created),
                "date": _epoch_to_date(created),
            }
        )
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


def _fetch_x(url: str) -> list[dict]:
    """Fetch a Nitter profile.

    Tries the per-user RSS feed first (`/<user>/rss`, which nitter instances
    that still support it return), then falls back to scraping the profile HTML
    for tweet text + status links. Instances are fragile; silently empty on
    failure is acceptable and handled by the caller.
    """
    items = _fetch_x_rss(url)
    if items:
        return items
    items = _fetch_x_html(url)
    return items


def _fetch_x_rss(url: str) -> list[dict]:
    """Try <host>/<user>/rss; nitter may return HTTP 410 (gone) on old feeds."""
    parsed = urllib.parse.urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return []
    user = parts[0]
    rss_url = f"{parsed.scheme}://{parsed.netloc}/{user}/rss"
    try:
        raw = http_get_text(rss_url)
    except Exception:
        return []
    # `_parse_xml_items` tolerates non-XML bodies and returns [] on parse error.
    return _parse_xml_items(raw)


def _fetch_x_html(url: str) -> list[dict]:
    """Scrape the profile HTML for tweet content + status links."""
    text = http_get_text(url)
    items = []
    tweets = re.findall(r'<div class="tweet-content"[^>]*>(.*?)</div>', text, re.S)
    statuses = re.findall(r'href="(/[^"]+/status/\d+)"', text)
    host = urllib.parse.urlparse(url).netloc
    for i, tweet in enumerate(tweets):
        content = clean_text(tweet)
        if not content:
            continue
        status = statuses[i] if i < len(statuses) else ""
        link = f"https://{host}{status}" if status else url
        items.append(
            {
                "title": _truncate(content, 120),
                "link": link,
                "summary": content,
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


def _epoch_to_date(epoch: float) -> str:
    try:
        return dt.datetime.utcfromtimestamp(epoch).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return ""


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
        "layout: page\n"
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
# Entry point
# --------------------------------------------------------------------------- #
def load_sources(config_path: Path) -> list[dict]:
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    sources = data.get("sources", [])
    return [s for s in sources if s.get("active", True)]


def run_pipeline(config_path: Path, date: dt.date, per_source_limit: int | None) -> list[dict]:
    sources = load_sources(config_path)
    all_items: list[dict] = []
    for source in sources:
        name = source.get("name", "?")
        sys.stderr.write(f"[fetch] {name}\n")
        items = fetch_source(source)
        if per_source_limit:
            items = items[:per_source_limit]
        hint = source.get("category_hint")
        for item in items:
            item["category"] = classify(
                item.get("title", ""), item.get("summary", ""), hint
            )
        all_items.extend(items)

    all_items = dedupe(all_items)
    for item in all_items:
        item["category"] = normalize_category(item["category"])
        item["summary_text"] = summarize(item)
    return all_items


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
    items = run_pipeline(args.config, date, args.limit)
    path = write_digest(items, date)
    sys.stderr.write(f"[done] wrote {path} ({len(items)} items)\n")
    print(f"Wrote {path} with {len(items)} items.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
