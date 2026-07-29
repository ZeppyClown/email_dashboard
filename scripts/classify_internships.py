#!/usr/bin/env python3
"""Fill in `Role Category` on internship cards that have none.

Most cards reached the board via CareerAxis rather than push_jds_to_board.py, so
the role tag their JD frontmatter carries never made it into `meta`. Without it
the board cannot be filtered by role — every JD card just says "internship".

Classification reuses job_scraper.categorize_job, with two changes:

1. The company is stripped off the title first. Board titles are
   "Position — Company", and company names poison title matching: "WeChat -
   Data Science Intern — TENCENT CLOUD SERVICE PTE. LTD." reads as a cloud role
   and "UI/UX Software Engineer (C++) — DConstruct Robotics" as robotics, when
   neither is.

2. Five categories the kit's taxonomy lacks are matched first. They belong in
   job_scraper.py eventually; they live here for now so resume-kit (a separate
   repo, mid-edit, no remote) stays untouched.

Cards that already carry a Role Category are never overwritten — a tag derived
from a real JD file beats a regex guess.

    python3 scripts/classify_internships.py --dry-run
    python3 scripts/classify_internships.py
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "resume-kit" / "scraper"))

import _common  # noqa: E402

try:
    from job_scraper import categorize_job  # noqa: E402
except ImportError:  # pragma: no cover
    _common.die(
        "cannot import job_scraper from ../resume-kit/scraper "
        "(is the T9 drive mounted?)"
    )

# Checked before job_scraper's rules, so these win where they overlap.
# Ordered: a genuine engineering title should beat a broader label.
EXTRA_TITLE_RULES = [
    # "Site Reliability Engineer" would otherwise fall to software_engineer.
    ("cloud_devops",      r"\bcloud (engineer|architect|intern)|devops|kubernetes|site reliability|\bsre\b|platform engineer|infrastructure engineer"),
    # Narrow on purpose: the CSA communications role is a campaign job, not
    # engineering, and must not land here.
    ("cybersecurity",     r"cyber ?security (engineer|analyst|intern|engineering)|penetration test|\bsoc analyst\b|information security"),
    ("robotics_autonomy", r"\brobotics? (intern|engineer|software)|autonomy engineer|autonomous (vehicle|system)|\bslam\b|drone engineer"),
    # Requires "design" as the role noun, so "UI/UX Software Engineer" stays a
    # software job rather than becoming a design one.
    ("design_ux",         r"(ui/ux|\bux\b|\bui\b|product|creative|graphic) design(er)? (intern|lead)?|design intern"),
    ("product_management", r"product (management|manager|owner)\b"),
]

_COMPANY_SPLIT = re.compile(r"\s+[—–]\s+")
_INELIGIBLE = re.compile(r"^\[INELIGIBLE\]\s*")


def position_only(board_title: str) -> str:
    """Drop the '— Company' suffix and the [INELIGIBLE] prefix.

    Board titles are "Position — Company". Matching the whole string files jobs
    under their employer's industry instead of their own role.
    """
    title = _INELIGIBLE.sub("", board_title or "")
    return _COMPANY_SPLIT.split(title)[0].strip()


def classify(board_title: str, details: str) -> str:
    """Role category for a board card. '_unsorted' when nothing matches."""
    position = position_only(board_title)

    for cat, pattern in EXTRA_TITLE_RULES:
        if re.search(pattern, position, re.I):
            return cat

    return categorize_job(position, details or "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--show", action="store_true", help="print every card and its label")
    args = ap.parse_args()

    rows = [r for r in _common.select("digest_items")
            if r.get("category") == "internship"]

    todo = [r for r in rows if not (r.get("meta") or {}).get("Role Category")]

    patches, counts = [], collections.Counter()
    for r in todo:
        cat = classify(r.get("title"), r.get("details"))
        counts[cat] += 1
        if args.show:
            print(f"  {cat:22} {position_only(r.get('title'))[:60]}")
        if cat == "_unsorted":
            # Writing '_unsorted' would be indistinguishable from a real
            # decision. Leaving it absent keeps "never classified" visible.
            continue
        meta = dict(r.get("meta") or {})       # copy: never mutate the fetched row
        meta["Role Category"] = cat
        patches.append({"id": r["id"], "meta": meta})

    print(f"\ninternships: {len(rows)} · already tagged: {len(rows)-len(todo)} · "
          f"classified now: {len(patches)} · left unsorted: {counts['_unsorted']}\n")
    for cat, n in counts.most_common():
        print(f"  {cat:24} {n}")

    written = _common.patch_rows(patches, dry_run=args.dry_run)
    print(f"\n{'would patch' if args.dry_run else 'patched'} {written} card(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
