#!/usr/bin/env python3
"""Find and remove cards whose CareerAxis listing has been withdrawn.

`/services/students/jobs/<id>?studentSiteId=1` answers 404 once a listing is
withdrawn. **Only a 404 means gone.** A 401, a redirect, or a non-JSON body
means the borrowed NTU session expired — treating that as "withdrawn" would
mark an entire run for deletion, so this aborts instead.

Cards merely *past their deadline* are never touched. The board hides those
behind a toggle, because a closed listing is still evidence of what you were
interested in and sender_feedback still counts it.

    export CAREERAXIS_COOKIE='ASP.NET_SessionId=...; .AspNet.ApplicationCookie=...'
    python3 scripts/audit_internships.py --check           # report only
    python3 scripts/audit_internships.py --check --apply   # delete withdrawn
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).parent))
from _common import ConfigError, careeraxis_id, clean, delete_ids, die, select  # noqa: E402

JOB_API = "https://careeraxis.ntu.edu.sg/services/students/jobs/{job_id}?studentSiteId=1"

LIVE, WITHDRAWN, UNKNOWN = "live", "withdrawn", "unknown"


class SessionExpired(RuntimeError):
    pass


def check_one(job_id: str, cookie: str) -> str:
    r = requests.get(
        JOB_API.format(job_id=job_id),
        headers={"Cookie": cookie, "User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        timeout=30,
        allow_redirects=False,
    )
    if r.status_code == 404:
        return WITHDRAWN
    if r.status_code in (301, 302, 401, 403):
        raise SessionExpired(f"job {job_id} returned {r.status_code}")
    if r.status_code >= 500:
        return UNKNOWN                        # server hiccup, not a verdict
    try:
        r.json()
    except ValueError:
        # HTML where JSON belongs is the classic expired-session signature.
        raise SessionExpired(f"job {job_id} returned a non-JSON body")
    return LIVE


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", required=True,
                    help="query CareerAxis for each careeraxis-sourced card")
    ap.add_argument("--apply", action="store_true",
                    help="actually delete the withdrawn cards (default: report only)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=1.0)
    a = ap.parse_args()

    cookie = os.environ.get("CAREERAXIS_COOKIE", "").strip()
    if not cookie:
        die("CAREERAXIS_COOKIE is not set — see the docstring at the top of this file.")

    try:
        rows = select("digest_items", {
            "select": "id,title,link,status,deadline_date",
            "source": "eq.careeraxis",
            "order": "digest_date.desc",
        })
    except ConfigError as e:
        die(str(e))

    rows = [r for r in rows if careeraxis_id(r.get("link"))]
    if a.limit:
        rows = rows[: a.limit]
    if not rows:
        print("no careeraxis-sourced cards to audit")
        return 0

    print(f"checking {len(rows)} listing(s)\n")
    withdrawn: list[dict[str, Any]] = []
    live = unknown = 0

    for i, row in enumerate(rows, 1):
        job = careeraxis_id(row["link"])
        try:
            verdict = check_one(job, cookie)
        except SessionExpired as e:
            die(f"{e} — session expired.\n"
                f"Stopped after {i - 1} of {len(rows)} checks; nothing was deleted. "
                f"Re-copy CAREERAXIS_COOKIE from a signed-in browser and re-run.")
        except requests.RequestException as e:
            print(f"  [{i}/{len(rows)}] {job}: request failed ({e})")
            unknown += 1
            time.sleep(a.delay)
            continue

        if verdict == WITHDRAWN:
            withdrawn.append(row)
            print(f"  [{i}/{len(rows)}] {job}: WITHDRAWN — {clean(row['title'])[:56]}")
        elif verdict == UNKNOWN:
            unknown += 1
        else:
            live += 1
        time.sleep(a.delay)

    print(f"\nlive {live} · withdrawn {len(withdrawn)} · inconclusive {unknown}")

    if not withdrawn:
        return 0

    # A card you already triaged carries a decision worth keeping; say so
    # before removing it, so an --apply run is never a silent loss.
    triaged = [r for r in withdrawn if r.get("status") not in (None, "new")]
    if triaged:
        print(f"\n{len(triaged)} of these were already triaged:")
        for r in triaged:
            print(f"  [{r['status']}] {clean(r['title'])[:64]}")

    if not a.apply:
        print(f"\nreport only — re-run with --apply to delete {len(withdrawn)} card(s)")
        return 0

    delete_ids([r["id"] for r in withdrawn])
    print(f"\ndeleted {len(withdrawn)} withdrawn card(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
