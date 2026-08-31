#!/usr/bin/env python3
"""Stage today's digest in Buttondown as a draft email (stdlib only).

The site collects and stores subscribers in Buttondown (see the subscribe form
on the site). Buttondown also handles delivery, so this script does NOT send
anything: it uploads the generated ``newsletter/<YYYY-MM-DD>.html`` as a
*draft* via the Buttondown API. You review it in the Buttondown dashboard and
click Send. Keeping the human in the loop avoids unattended sends to a live
list.

Design goals:
  * Never fail the CI workflow. A missing key or missing file exits 0 with an
    explanatory message.
  * No third-party dependencies. Everything sensitive comes from the
    environment.

Environment variables:
  BUTTONDOWN_API_KEY   Required to push. If unset, the step is skipped.
  BUTTONDOWN_STATUS    "draft" (default) or "scheduled".
  BUTTONDOWN_SEND_AT   ISO-8601 UTC time, required only when STATUS=scheduled
                       (e.g. 2026-09-01T03:00:00Z).
  SUBJECT_PREFIX       Subject prefix (default: "The AI Daily —").

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
DEFAULT_PREFIX = "The AI Daily —"


def find_newsletter_html(date_str):
    path = os.path.join(REPO_ROOT, "newsletter", "{}.html".format(date_str))
    return path if os.path.exists(path) else None


def build_subject(prefix, date_str):
    return "{} {}".format(prefix, date_str)


def push_draft(api_key, subject, html):
    # Force Buttondown's "fancy" (rich HTML) editor mode so our full HTML
    # document is used as-is instead of being treated as Markdown.
    body = "<!-- buttondown-editor-mode: fancy -->\n" + html
    payload = {"subject": subject, "body": body, "status": os.environ.get("BUTTONDOWN_STATUS", "draft").strip().lower()}
    if payload["status"] == "scheduled":
        send_at = os.environ.get("BUTTONDOWN_SEND_AT", "").strip()
        if send_at:
            payload["publish_date"] = send_at
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
    parser = argparse.ArgumentParser(description="Stage the daily digest in Buttondown as a draft.")
    parser.add_argument("--date", help="Digest date YYYY-MM-DD (default: today, UTC).")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be pushed; no network call.")
    args = parser.parse_args()

    date_str = args.date or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    prefix = os.environ.get("SUBJECT_PREFIX", DEFAULT_PREFIX)
    api_key = os.environ.get("BUTTONDOWN_API_KEY", "").strip()
    html_path = find_newsletter_html(date_str)

    if args.dry_run:
        if html_path:
            with open(html_path, "r", encoding="utf-8") as fh:
                html = fh.read()
            subject = build_subject(prefix, date_str)
            print("[dry-run] Would push draft to Buttondown (status={}).".format(os.environ.get("BUTTONDOWN_STATUS", "draft")))
            print("[dry-run] Subject: {}".format(subject))
            print("[dry-run] Body: {} bytes from {}".format(len(html), html_path))
        else:
            print("[dry-run] No newsletter file for {} (looked in newsletter/).".format(date_str))
        return 0

    if not api_key:
        print("BUTTONDOWN_API_KEY not set; skipping draft push. Subscribers and sending are handled in Buttondown.")
        return 0
    if html_path is None:
        print("No newsletter HTML for {}; nothing to stage.".format(date_str))
        return 0

    with open(html_path, "r", encoding="utf-8") as fh:
        html = fh.read()
    subject = build_subject(prefix, date_str)

    status, body = push_draft(api_key, subject, html)
    ok = status is not None and 200 <= status < 300
    if ok:
        print("Staged Buttondown draft: '{}' (HTTP {}). Review and send in the dashboard.".format(subject, status))
    else:
        print("FAILED to stage draft (HTTP {}): {}".format(status, (body or "")[:300]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
