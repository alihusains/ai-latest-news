#!/usr/bin/env python3
"""Provider-agnostic newsletter sender (Python stdlib only).

Reads ``subscribers.json`` and today's ``newsletter/<YYYY-MM-DD>.html`` from the
repo root, then delivers the digest through the configured provider's HTTP API
(Resend or SendGrid) using ``urllib``.

Design goals:
  * Never fail the CI workflow over email. Missing subscribers or a missing
    ``NEWSLETTER_API_KEY`` both exit 0 with an explanatory message.
  * No third-party dependencies and no credentials in code. Everything sensitive
    comes from the environment (``NEWSLETTER_API_KEY``).

Environment variables:
  NEWSLETTER_API_KEY    Required to actually send. If unset, send is skipped.
  NEWSLETTER_PROVIDER   "resend" (default) or "sendgrid".
  FROM_EMAIL            Sender address (default: newsletter@signal-ai.example).
  SUBJECT_PREFIX        Subject prefix (default: "The AI Daily \u2014").

Usage:
  python3 send_newsletter.py [--date YYYY-MM-DD] [--dry-run]

  --dry-run  Parse the newsletter HTML and print the subject + recipient count
             without making any network call. Exits 0.
"""

import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

# The repo root is the directory containing this script (the workflow runs it
# from the repository root, but anchoring to __file__ keeps it robust).
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

PROVIDERS = {
    "resend": "https://api.resend.com/emails",
    "sendgrid": "https://api.sendgrid.com/v3/mail/send",
}

DEFAULT_FROM = "newsletter@signal-ai.example"
DEFAULT_PREFIX = "The AI Daily \u2014"


def load_subscribers(path):
    """Return a clean list of subscriber emails, or [] on any problem."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []
    subs = data.get("subscribers", []) if isinstance(data, dict) else []
    if not isinstance(subs, list):
        return []
    return [s.strip() for s in subs if isinstance(s, str) and s.strip()]


def find_newsletter_html(date_str):
    """Return the path to newsletter/<date>.html if it exists, else None."""
    path = os.path.join(REPO_ROOT, "newsletter", "{}.html".format(date_str))
    return path if os.path.exists(path) else None


def build_subject(prefix, date_str):
    return "{} {}".format(prefix, date_str)


def _post_json(url, payload, extra_headers):
    """POST a JSON payload; return (http_status_or_None, response_body_text)."""
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return exc.code, body
    except urllib.error.URLError as exc:
        return None, str(exc.reason)
    except Exception as exc:  # noqa: BLE001 - report any transport failure
        return None, str(exc)


def send_resend(api_key, from_email, to_list, subject, html):
    payload = {
        "from": from_email,
        "to": to_list,
        "subject": subject,
        "html": html,
    }
    return _post_json(PROVIDERS["resend"], payload, {"Authorization": "Bearer " + api_key})


def send_sendgrid(api_key, from_email, to_list, subject, html):
    payload = {
        "personalizations": [{"to": [{"email": e} for e in to_list]}],
        "from": {"email": from_email},
        "subject": subject,
        "content": [{"type": "text/html", "value": html}],
    }
    return _post_json(PROVIDERS["sendgrid"], payload, {"Authorization": "Bearer " + api_key})


def main():
    parser = argparse.ArgumentParser(description="Send the daily AI newsletter.")
    parser.add_argument("--date", help="Digest date YYYY-MM-DD (default: today, UTC).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse the HTML and print subject + recipient count; no network call.",
    )
    args = parser.parse_args()

    date_str = args.date or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    from_email = os.environ.get("FROM_EMAIL", DEFAULT_FROM)
    subject_prefix = os.environ.get("SUBJECT_PREFIX", DEFAULT_PREFIX)
    provider = os.environ.get("NEWSLETTER_PROVIDER", "resend").strip().lower()
    api_key = os.environ.get("NEWSLETTER_API_KEY", "").strip()

    subscribers = load_subscribers(os.path.join(REPO_ROOT, "subscribers.json"))
    html_path = find_newsletter_html(date_str)
    subject = build_subject(subject_prefix, date_str)

    # --- Self-check: no network, just parse + report. ---
    if args.dry_run:
        if html_path is not None:
            try:
                with open(html_path, "r", encoding="utf-8") as fh:
                    html = fh.read()
                print("[dry-run] Parsed {} ({} bytes).".format(html_path, len(html)))
            except OSError as exc:
                print("[dry-run] Could not read {}: {}".format(html_path, exc))
        else:
            print("[dry-run] No newsletter file found for {} (looked in newsletter/).".format(date_str))
        print("[dry-run] Subject: {}".format(subject))
        print("[dry-run] Recipients: {}".format(len(subscribers)))
        return 0

    # --- Real send path. Never fail the workflow over email. ---
    if not subscribers:
        print("No subscribers configured, skipping send.")
        return 0

    if not api_key:
        print("NEWSLETTER_API_KEY not set, skipping send (newsletter remains available on the site).")
        return 0

    if html_path is None:
        print("No newsletter HTML found for {}; nothing to send.".format(date_str))
        return 0

    if provider not in PROVIDERS:
        print("Unknown NEWSLETTER_PROVIDER '{}'. Use 'resend' or 'sendgrid'.".format(provider))
        return 1

    try:
        with open(html_path, "r", encoding="utf-8") as fh:
            html = fh.read()
    except OSError as exc:
        print("Failed to read {}: {}".format(html_path, exc))
        return 1

    sender = send_resend if provider == "resend" else send_sendgrid
    status, body = sender(api_key, from_email, subscribers, subject, html)

    ok = status is not None and 200 <= status < 300
    for recipient in subscribers:
        if ok:
            print("sent -> {} (HTTP {})".format(recipient, status))
        else:
            print("FAILED -> {} (HTTP {}): {}".format(recipient, status, (body or "")[:200]))

    # Exit 1 only on a hard API error after a real send attempt with a key present.
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
