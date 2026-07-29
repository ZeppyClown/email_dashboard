#!/usr/bin/env python3
"""Fill `details` and `meta` from a CareerAxis listing page.

The JOB-BLAST spreadsheet has no requirements column — year of study, GPA,
tech stack and duration exist only on the listing itself, behind an NTU login.
This reads them with a borrowed browser session and writes them onto the card.

Getting the cookie: sign in to careeraxis.ntu.edu.sg in a browser, open
DevTools → Application → Cookies, copy the whole cookie header, then

    export CAREERAXIS_COOKIE='ASP.NET_SessionId=...; .AspNet.ApplicationCookie=...'

Sessions expire in hours, not days. This script tells you plainly when yours
has, rather than writing empty details over good ones.

    python3 scripts/scrape_careeraxis.py --id 862076
    python3 scripts/scrape_careeraxis.py --missing-details --limit 20
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from _common import (ConfigError, build_meta, careeraxis_id, clean, die,  # noqa: E402
                     parse_date, patch_rows, select)

BASE = "https://careeraxis.ntu.edu.sg"
JOB_PAGE = BASE + "/students/jobs/{job_id}"
JOB_API = BASE + "/services/students/jobs/{job_id}?studentSiteId=1"

# Labels the listing uses, in the order we want them on the card.
FIELDS = ["Position", "Employer", "Industry", "Country", "Work model", "Commences",
          "Remuneration", "Vacancies", "Hours", "Contract type", "Published",
          "Closes", "Added", "Occupation"]


class SessionExpired(RuntimeError):
    """The borrowed NTU session is no longer valid."""


def cookie_header() -> str:
    c = os.environ.get("CAREERAXIS_COOKIE", "").strip()
    if not c:
        die("CAREERAXIS_COOKIE is not set — see the docstring at the top of this file.")
    return c


def fetch(job_id: str, cookie: str) -> str:
    r = requests.get(
        JOB_PAGE.format(job_id=job_id),
        headers={"Cookie": cookie,
                 "User-Agent": "Mozilla/5.0",
                 "Accept": "text/html"},
        timeout=30,
        allow_redirects=False,
    )
    # A login redirect means the session died. Treating that as "no content"
    # would blank out every card in the run.
    if r.status_code in (301, 302, 401, 403):
        raise SessionExpired(f"job {job_id} returned {r.status_code} — session expired")
    if r.status_code == 404:
        raise SessionExpired(f"job {job_id} returned 404 — withdrawn, run audit_internships.py")
    r.raise_for_status()
    if "login" in r.url.lower() or "<form" in r.text[:2000].lower() and "password" in r.text[:4000].lower():
        raise SessionExpired(f"job {job_id} served a login page — session expired")
    return r.text


def parse(html: str) -> tuple[str | None, dict[str, str]]:
    """Return (details, meta) scraped from a listing page."""
    soup = BeautifulSoup(html, "html.parser")

    # Facts render as label/value pairs; the markup has changed before, so try
    # definition lists, then table rows, then labelled divs.
    facts: dict[str, str] = {}
    for dt in soup.find_all(["dt", "th"]):
        label = clean(dt.get_text())
        sib = dt.find_next_sibling(["dd", "td"])
        if label and sib:
            facts.setdefault(label.rstrip(":"), clean(sib.get_text()) or "")
    for row in soup.select("tr"):
        cells = row.find_all("td")
        if len(cells) == 2:
            label = clean(cells[0].get_text())
            if label:
                facts.setdefault(label.rstrip(":"), clean(cells[1].get_text()) or "")

    # The description is the longest block of prose on the page.
    blocks = [clean(el.get_text(" ")) or "" for el in soup.select("div, section, article")]
    details = max(blocks, key=len, default="") if blocks else ""
    details = re.sub(r"\s{2,}", " ", details).strip()
    if len(details) < 80:
        details = ""

    meta = build_meta([(f, facts.get(f)) for f in FIELDS])
    return (details[:6000] or None), meta


def targets(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.id:
        return [{"id": f"careeraxis-{args.id}", "link": JOB_PAGE.format(job_id=args.id)}]
    rows = select("digest_items", {
        "select": "id,link,details,category",
        "source": "eq.careeraxis",
        "order": "digest_date.desc",
    })
    if args.missing_details:
        rows = [r for r in rows if not (r.get("details") or "").strip()]
    return rows[: args.limit] if args.limit else rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--id", help="a single CareerAxis job id, e.g. 862076")
    g.add_argument("--missing-details", action="store_true",
                   help="every careeraxis card whose details are empty")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between requests")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cookie = cookie_header()
    try:
        rows = targets(a)
    except ConfigError as e:
        die(str(e))

    if not rows:
        print("nothing to scrape")
        return 0
    print(f"{len(rows)} listing(s)\n")

    updates, skipped = [], 0
    for i, row in enumerate(rows, 1):
        job = careeraxis_id(row.get("link")) or str(row["id"]).replace("careeraxis-", "")
        try:
            details, meta = parse(fetch(job, cookie))
        except SessionExpired as e:
            # Abort the whole run: one expired session means every remaining
            # fetch is wrong too, and partial writes are worse than none.
            die(f"{e}\nRe-copy CAREERAXIS_COOKIE from a signed-in browser and re-run. "
                f"{len(updates)} row(s) parsed but not written.")
        except requests.RequestException as e:
            print(f"  [{i}/{len(rows)}] {job}: request failed ({e}) — skipped")
            skipped += 1
            continue

        if not details and not meta:
            print(f"  [{i}/{len(rows)}] {job}: nothing parsed — skipped")
            skipped += 1
            continue

        print(f"  [{i}/{len(rows)}] {job}: {len(details or '')} chars, {len(meta)} facts")
        patch: dict[str, Any] = {"id": row["id"]}
        if details:
            patch["details"] = details
        if meta:
            patch["meta"] = meta
        if closes := parse_date(meta.get("Closes")):
            patch["deadline_date"] = closes
        updates.append(patch)
        time.sleep(a.delay)

    if a.dry_run:
        print(f"\ndry run — {len(updates)} would be written, {skipped} skipped")
        return 0

    n = patch_rows(updates)
    print(f"\nupdated {n}, skipped {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
