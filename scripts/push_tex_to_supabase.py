#!/usr/bin/env python3
"""Push every package's .tex source into Supabase so the page reads it live.

`build_packages_page.py` bakes the .tex into packages.html and copies PDFs into
packages/. That snapshot is only as fresh as the last git push — which is how
the live site served a Jul 30 index for a week while Horizon Labs sat compiled
on disk.

Rows here need no rebuild and no push: run this after generating a package and
the published page picks it up on the next load.

    python3 scripts/push_tex_to_supabase.py --dry-run
    python3 scripts/push_tex_to_supabase.py

Scope: .tex source, which is text and belongs in a table. **PDFs are not
covered** — binary belongs in Storage, not a column. The page still gets its
PDF from the connected folder, the local compile server, or the published
snapshot, in that order.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

DASHBOARD = Path(__file__).resolve().parent.parent
ROOT = DASHBOARD.parent
OUTPUT_DIR = ROOT / "resume-kit" / "output"
JDS = ROOT / "resume-kit" / "JDs"
HERMES_ENV = Path.home() / ".hermes" / ".env"

SKIP = {"resume.cls", "cv.cls"}

DDL = """\
create table if not exists resume_docs (
  id        text primary key,          -- "<package>/<file.tex>"
  package   text not null,
  filename  text not null,
  kind      text not null,             -- Resume | CV | Cover letter | Document
  tex       text not null,
  pages     int,
  stale     boolean default false,     -- .tex newer than its .pdf
  tex_at    timestamptz,
  built_at  timestamptz,
  updated_at timestamptz default now()
);

alter table resume_docs enable row level security;

-- Same posture as digest_items: the world may read, only the service_role
-- key (used by these scripts, never the browser) may write.
drop policy if exists "public read" on resume_docs;
create policy "public read" on resume_docs for select using (true);

revoke insert, update, delete on resume_docs from anon, authenticated;
grant select on resume_docs to anon, authenticated;

create index if not exists idx_resume_docs_package on resume_docs(package);"""


def supabase() -> tuple[str, str]:
    if HERMES_ENV.exists():
        load_dotenv(HERMES_ENV)
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not (url and key):
        raise SystemExit(f"error: Supabase credentials missing from {HERMES_ENV}")
    return url, key


def kind_of(stem: str) -> str:
    low = stem.lower()
    if "cover_letter" in low or low.endswith("_cl"):
        return "Cover letter"
    if low.endswith("_cv") or "_cv_" in low:
        return "CV"
    if "resume" in low:
        return "Resume"
    return "Document"


def page_count(pdf: Path) -> int | None:
    try:
        import fitz
        with fitz.open(pdf) as d:
            return d.page_count
    except Exception:
        return None


def stamp(p: Path) -> str:
    return datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()


def collect() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not OUTPUT_DIR.is_dir():
        return rows
    for pkg in sorted(d for d in OUTPUT_DIR.iterdir() if d.is_dir()):
        for tex in sorted(pkg.glob("*.tex")):
            if tex.name in SKIP:
                continue
            pdf = tex.with_suffix(".pdf")
            has_pdf = pdf.is_file()
            rows.append({
                "id": f"{pkg.name}/{tex.name}",
                "package": pkg.name,
                "filename": tex.name,
                "kind": kind_of(tex.stem),
                "tex": tex.read_text(encoding="utf-8", errors="replace"),
                "pages": page_count(pdf) if has_pdf else None,
                "stale": bool(has_pdf and tex.stat().st_mtime > pdf.stat().st_mtime),
                "tex_at": stamp(tex),
                "built_at": stamp(pdf) if has_pdf else None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
    return rows


def push(rows: list[dict[str, Any]]) -> None:
    url, key = supabase()
    r = requests.post(
        f"{url}/rest/v1/resume_docs",
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "Prefer": "resolution=merge-duplicates,return=minimal"},
        params={"on_conflict": "id"}, json=rows, timeout=60)
    if r.status_code == 404 or (r.status_code == 400 and "resume_docs" in r.text):
        raise SystemExit(
            "The `resume_docs` table does not exist yet. PostgREST cannot create it.\n"
            "Paste this into the Supabase SQL editor, then re-run:\n\n"
            + "\n".join("    " + l for l in DDL.splitlines()) + "\n")
    if r.status_code >= 400:
        raise SystemExit(f"push failed [{r.status_code}]: {r.text[:400]}")


def prune(rows: list[dict[str, Any]]) -> int:
    """Drop rows for .tex files that no longer exist on disk."""
    url, key = supabase()
    h = {"apikey": key, "Authorization": f"Bearer {key}"}
    have = requests.get(f"{url}/rest/v1/resume_docs", headers=h,
                        params={"select": "id"}, timeout=30)
    if have.status_code >= 400:
        return 0
    live = {r["id"] for r in have.json()}
    gone = live - {r["id"] for r in rows}
    for gid in gone:
        requests.delete(f"{url}/rest/v1/resume_docs", headers=h,
                        params={"id": f"eq.{gid}"}, timeout=30)
    return len(gone)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    rows = collect()
    if not rows:
        print("no .tex files under resume-kit/output")
        return 0

    for r in rows:
        flag = "  STALE" if r["stale"] else ""
        pages = f"{r['pages']}p" if r["pages"] else "not compiled"
        print(f"  {r['kind']:13} {r['id'][:52]:52} {pages:>13}{flag}")

    if a.dry_run:
        print(f"\ndry run — would upsert {len(rows)} row(s)")
        return 0

    push(rows)
    dropped = prune(rows)
    print(f"\npushed {len(rows)} .tex row(s)"
          + (f", pruned {dropped} deleted" if dropped else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
