#!/usr/bin/env python3
"""Attach team-size facts to hackathon cards.

Team size decides whether you can enter at all — a 3-5 person event needs a
squad lined up before the deadline, so the board filters on it. The filter
compares against `Team min` / `Team max`; `Team size` is the organiser's own
wording, shown on the card.

Omit min/max when the organiser never published a number. The board treats
unknown as "might fit" and keeps showing the card, which is the right default —
guessing a range hides events you could actually enter.

Curated facts live in FACTS below. Add an entry when a new hackathon lands,
keyed by any distinctive substring of the card title (matched case-insensitively).

    python3 scripts/enrich_hackathons.py --list
    python3 scripts/enrich_hackathons.py --dry-run
    python3 scripts/enrich_hackathons.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from _common import ConfigError, clean, die, patch_rows, select  # noqa: E402

# title substring → facts. `size` is the organiser's wording; min/max are
# integers for the filter. Leave min/max out when it was never published —
# the board treats unknown as "might fit" and keeps showing the card, which
# beats a guess that hides an event you could have entered.
#
# Seeded 2026-07-29 from the live board, so re-running is a no-op on these.
FACTS: dict[str, dict[str, Any]] = {
    "garena ai build":        {"size": "Teams of 3–5", "min": 3, "max": 5},
    "lta rail mobility":      {"size": "Teams of 3–4", "min": 3, "max": 4},
    "simplify agentic ai":    {"size": "Teams of 3–5", "min": 3, "max": 5},
    "simplifynext agentic":   {"size": "Teams of 3–5", "min": 3, "max": 5},
    "tech4city":              {"size": "Teams of 3–6", "min": 3, "max": 6},
    "schneider go green":     {"size": "Teams of up to 4", "min": 1, "max": 4},
    # Organiser never published a size — min/max deliberately omitted.
    "maritimeone case summit": {"size": "Team competition — size not stated"},
    "materials innovation":    {"size": "Team competition — size not stated"},
}


def match(title: str) -> dict[str, Any] | None:
    t = (title or "").lower()
    for needle, facts in FACTS.items():
        if needle in t:
            return facts
    return None


def patch_for(row: dict[str, Any]) -> dict[str, Any] | None:
    facts = match(row.get("title", ""))
    if not facts:
        return None

    meta = dict(row.get("meta") or {})
    wanted = {"Team size": facts["size"]}
    if "min" in facts:
        wanted["Team min"] = facts["min"]
    if "max" in facts:
        wanted["Team max"] = facts["max"]

    if all(str(meta.get(k, "")) == str(v) for k, v in wanted.items()):
        return None                      # already correct, don't churn updated_at

    meta.update(wanted)
    return {"id": row["id"], "meta": meta}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="show hackathon cards and their team facts")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    try:
        rows = select("digest_items", {
            "select": "id,title,meta,deadline_date",
            "category": "eq.hackathon",
            "order": "deadline_date.asc.nullslast",
        })
    except ConfigError as e:
        die(str(e))

    if not rows:
        print("no hackathon cards on the board")
        return 0

    if a.list:
        for r in rows:
            meta = r.get("meta") or {}
            size = meta.get("Team size") or "— unknown, filter keeps it visible"
            print(f"  {clean(r['title'])[:64]:64}  {size}")
        unmatched = [r for r in rows if not match(r.get("title", ""))]
        if unmatched:
            print(f"\n{len(unmatched)} card(s) have no FACTS entry — add one if you know the size:")
            for r in unmatched:
                print(f"  {clean(r['title'])[:70]}")
        return 0

    patches = [p for p in (patch_for(r) for r in rows) if p]
    print(f"{len(rows)} hackathon card(s), {len(patches)} need updating")
    for p in patches:
        print(f"  {p['id']}: {p['meta'].get('Team size')}")

    if a.dry_run:
        print("\ndry run — nothing written")
        return 0
    if patches:
        patch_rows(patches)
        print(f"\nupdated {len(patches)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
