#!/usr/bin/env python3
"""Push today's digest to Buttondown as a SCHEDULED email (stdlib only).

The daily pipeline runs ~03:00 UTC (07:00 Asia/Dubai). This script schedules
the newsletter for 05:30 UTC (09:00 Asia/Dubai) so subscribers get it in the
morning. If a late backup run fires after 05:30 UTC, the email is scheduled a
few minutes out (sent as soon as possible) instead of being lost.

Design goals:
  * Never fail the CI workflow. A missing key or missing file exits 0 with an
    explanatory message.
  * No third-party dependencies. Everything sensitive comes from the
    environment.

Environment variables:
  BUTTONDOWN_API_KEY   Required to push. If unset, the step is skipped.
  BUTTONDOWN_SEND_AT   Optional: explicit ISO-8601 UTC target (overrides the
                       default 05:30 UTC logic). Used for manual dispatch runs.
  SUBJECT_PREFIX       Subject prefix (default: "The AI Daily:").

Usage:
  python3 push_buttondown.py [--date YYYY-MM-DD] [--dry-run]
"""

import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
API_URL = "https://api.buttondown.com/v1/emails"
DEFAULT_PREFIX = "The AI Daily:"
SITE_URL = "https://alihusains.github.io/ai-latest-news/"
SEND_HOUR, SEND_MINUTE = 5, 30  # 05:30 UTC == 09:00 Asia/Dubai (UTC+4)


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def dubai_date(now=None):
    """The edition day in the reader's timezone (Asia/Dubai, UTC+4, no DST)."""
    now = now or _utcnow()
    return (now + datetime.timedelta(hours=4)).date()


def find_newsletter_html(date_str):
    path = os.path.join(REPO_ROOT, "newsletter", "{}.html".format(date_str))
    return path if os.path.exists(path) else None


def top_headline(date_str):
    """Big-story headline from data/<date>.json (or latest.json) for the subject."""
    for name in ("data/{}.json".format(date_str), "data/latest.json"):
        path = os.path.join(REPO_ROOT, name)
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            stories = data.get("stories") or []
            if not stories:
                continue
            top = sorted(stories, key=lambda s: s.get("importance", 0), reverse=True)[0]
            headline = (top.get("headline") or "").strip()
            if headline:
                return headline
        except (ValueError, OSError):
            continue
    return None


def build_subject(prefix, date_str, headline):
    if headline:
        hook = headline if len(headline) <= 52 else headline[:52].rsplit(" ", 1)[0]
        return "{} {}".format(prefix, hook)
    return "{} {}".format(prefix, date_str)


def resolve_send_at(explicit):
    """Return (publish_at_utc, mode) where mode is 'scheduled' or 'asap'."""
    if explicit:
        try:
            return datetime.datetime.fromisoformat(explicit.replace("Z", "+00:00")), "scheduled"
        except ValueError:
            print("WARNING: unparseable BUTTONDOWN_SEND_AT {!r}; falling back to 05:30 UTC logic.".format(explicit))
    now = _utcnow()
    target = now.replace(hour=SEND_HOUR, minute=SEND_MINUTE, second=0, microsecond=0)
    if now < target:
        return target, "scheduled"
    # Late backup slot: send as soon as possible (a few minutes out).
    return now + datetime.timedelta(minutes=5), "asap"


def push_email(api_key, subject, html, publish_at, mode):
    # Force Buttondown's "fancy" (rich HTML) editor mode so our full HTML
    # document is used as-is instead of being treated as Markdown.
    body = "<!-- buttondown-editor-mode: fancy -->\n" + html
    payload = {
        "subject": subject,
        "body": body,
        "status": "scheduled",
        "publish_date": publish_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=data,
        headers={"Authorization": "Token " + api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return exc.code, body
    except Exception as exc:  # noqa: BLE001 - report any transport failure
        return None, str(exc)


def main():
    parser = argparse.ArgumentParser(description="Schedule today's digest in Buttondown for 09:00 Dubai.")
    parser.add_argument("--date", help="Edition date YYYY-MM-DD (default: today, Asia/Dubai).")
    parser.add_argument("--send-at", help="Explicit ISO-8601 UTC send time (overrides 05:30 UTC logic).")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be pushed; no network call.")
    args = parser.parse_args()

    now = _utcnow()
    date_str = args.date or dubai_date(now).isoformat()
    prefix = os.environ.get("SUBJECT_PREFIX", DEFAULT_PREFIX)
    api_key = os.environ.get("BUTTONDOWN_API_KEY", "").strip()
    explicit_at = os.environ.get("BUTTONDOWN_SEND_AT", "").strip() or args.send_at
    html_path = find_newsletter_html(date_str)

    publish_at, mode = resolve_send_at(explicit_at)

    if args.dry_run:
        subject = build_subject(prefix, date_str, top_headline(date_str))
        print("[dry-run] Would push to Buttondown (status=scheduled, mode={}).".format(mode))
        print("[dry-run] Edition date: {} (now UTC: {})".format(date_str, now.strftime("%Y-%m-%dT%H:%M:%SZ")))
        print("[dry-run] Publish at:   {}".format(publish_at.strftime("%Y-%m-%dT%H:%M:%SZ")))
        print("[dry-run] Subject:      {}".format(subject))
        if html_path:
            with open(html_path, "r", encoding="utf-8") as fh:
                print("[dry-run] Body: {} bytes from {}".format(len(fh.read()), html_path))
        else:
            print("[dry-run] No newsletter file for {} (looked in newsletter/).".format(date_str))
        return 0

    if not api_key:
        print("BUTTONDOWN_API_KEY not set; skipping scheduled send. Subscribers and sending are handled in Buttondown.")
        return 0
    if html_path is None:
        print("No newsletter HTML for {}; nothing to schedule.".format(date_str))
        return 0

    with open(html_path, "r", encoding="utf-8") as fh:
        html = fh.read()
    subject = build_subject(prefix, date_str, top_headline(date_str))

    status, body = push_email(api_key, subject, html, publish_at, mode)
    ok = status is not None and 200 <= status < 300
    if ok:
        try:
            email_id = (json.loads(body) or {}).get("id", "")
        except ValueError:
            email_id = ""
        print("Scheduled Buttondown email '{}' for {} UTC ({}) — subscribers receive it at 09:00 Dubai.".format(
            subject, publish_at.strftime("%Y-%m-%dT%H:%M:%S"), email_id or "id unknown"))
    else:
        print("FAILED to schedule email (HTTP {}): {}".format(status, (body or "")[:300]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
