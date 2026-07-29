"""Shared helpers for the digest-board scripts.

Talks to Supabase over PostgREST with `requests` rather than the `supabase`
client, so the only dependency is one that is already installed.

Secrets come from ``~/.hermes/.env`` (the file Hermes itself loads, per
cli.py:216). Nothing here reads a key from the repo.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import requests
from dotenv import load_dotenv

HERMES_ENV = Path.home() / ".hermes" / ".env"
TIMEOUT = 30

CATEGORIES = {"deadline", "internship", "hackathon", "scholarship", "course", "other"}

# Columns the board owns. Never send these on an upsert — a re-sent listing
# must not reset a card you already triaged, or erase the note explaining why.
BOARD_OWNED = ("status", "note")


class ConfigError(RuntimeError):
    """Raised when required credentials are absent."""


def load_config() -> tuple[str, str]:
    """Return (supabase_url, service_role_key), or explain what is missing."""
    if HERMES_ENV.exists():
        load_dotenv(HERMES_ENV)

    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    missing = [n for n, v in (("SUPABASE_URL", url), ("SUPABASE_SERVICE_ROLE_KEY", key)) if not v]
    if missing:
        raise ConfigError(
            f"Missing {', '.join(missing)} in {HERMES_ENV}.\n"
            "  SUPABASE_URL              → Supabase → Project Settings → API\n"
            "  SUPABASE_SERVICE_ROLE_KEY → same page, the *secret* key (sb_secret_…)\n"
            "Add them there, not to this repo."
        )
    return url, key


def _headers(key: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    h = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def select(table: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
    url, key = load_config()
    r = requests.get(
        f"{url}/rest/v1/{table}",
        headers=_headers(key),
        params=params or {},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def upsert(rows: list[dict[str, Any]], *, dry_run: bool = False) -> int:
    """Insert-or-update on `id`, leaving board-owned columns untouched.

    PostgREST's merge-duplicates only writes the columns present in the
    payload, so omitting status/note is what protects them — there is no
    "update these columns only" flag to set.
    """
    rows = [{k: v for k, v in r.items() if k not in BOARD_OWNED} for r in rows]
    if not rows:
        return 0
    if dry_run:
        return len(rows)

    url, key = load_config()
    r = requests.post(
        f"{url}/rest/v1/digest_items",
        headers=_headers(key, {"Prefer": "resolution=merge-duplicates,return=minimal"}),
        params={"on_conflict": "id"},
        json=rows,
        timeout=TIMEOUT,
    )
    if r.status_code >= 400:
        # A 400 here is usually a column or CHECK that only exists in schema.sql
        # and was never applied — PostgREST cannot run DDL, so say so plainly.
        raise RuntimeError(
            f"Upsert failed [{r.status_code}]: {r.text[:400]}\n"
            "If this names an unknown column or violates a CHECK, paste "
            "schema.sql into the Supabase SQL editor — it is idempotent."
        )
    return len(rows)


def patch_rows(rows: list[dict[str, Any]], *, dry_run: bool = False) -> int:
    """Update existing cards column-by-column, one request per row.

    Use this — not `upsert` — whenever a row is partial. PostgREST's
    merge-duplicates is an INSERT ... ON CONFLICT under the hood, so it still
    requires every NOT NULL column (digest_date, category, title) even when
    the row already exists. A `{id, details}` patch sent that way fails with
    23502. PATCH is a true UPDATE and touches only what you send.

    Board-owned columns are stripped here as well, so a patch can never
    clobber a triage decision.
    """
    url, key = load_config()
    written = 0
    for row in rows:
        row_id = row.get("id")
        if not row_id:
            raise ValueError("patch_rows needs an 'id' on every row")
        body = {k: v for k, v in row.items() if k not in BOARD_OWNED and k != "id"}
        if not body:
            continue
        if dry_run:
            written += 1
            continue
        r = requests.patch(
            f"{url}/rest/v1/digest_items",
            headers=_headers(key, {"Prefer": "return=minimal"}),
            params={"id": f"eq.{row_id}"},
            json=body,
            timeout=TIMEOUT,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Patch failed for {row_id} [{r.status_code}]: {r.text[:300]}")
        written += 1
    return written


def delete_ids(ids: Iterable[str], *, dry_run: bool = False) -> int:
    ids = list(ids)
    if not ids or dry_run:
        return len(ids)
    url, key = load_config()
    r = requests.delete(
        f"{url}/rest/v1/digest_items",
        headers=_headers(key, {"Prefer": "return=minimal"}),
        params={"id": f"in.({','.join(ids)})"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return len(ids)


# ---------------------------------------------------------------- identity ---

CAREERAXIS_JOB = re.compile(r"careeraxis\.ntu\.edu\.sg/students/jobs/(\d+)")


def careeraxis_id(link: str | None) -> str | None:
    """NTU's own job id, when the link is a real CareerAxis listing."""
    if not link:
        return None
    m = CAREERAXIS_JOB.search(link)
    return m.group(1) if m else None


def stable_id(link: str | None, fallback: str = "") -> str:
    """Idempotency key. Prefer NTU's job id so a re-sent listing reuses its card."""
    job = careeraxis_id(link)
    if job:
        return f"careeraxis-{job}"
    seed = (link or fallback).strip().lower()
    if not seed:
        raise ValueError("stable_id needs a link or a fallback seed")
    return hashlib.sha1(seed.encode()).hexdigest()


def classify(link: str | None) -> tuple[str, str]:
    """Return (category, source).

    A card only earns `internship` when there is a job description behind it —
    in practice a CareerAxis listing, the one source with a scraper that can
    fill details and meta. A one-line email mention with a careers-homepage
    link is a real opening but an empty card, so it lands in `other`.
    """
    return ("internship", "careeraxis") if careeraxis_id(link) else ("other", "ntu-email")


# -------------------------------------------------------------------- dates ---

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y",
                 "%b %d, %Y", "%d-%b-%y", "%d/%m/%y")


def parse_date(value: Any) -> str | None:
    """Best-effort date → ISO string. Returns None rather than guessing wrong."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def clean(value: Any) -> str | None:
    """Trim a spreadsheet cell to a usable string, or None if it is empty."""
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def build_meta(pairs: list[tuple[str, Any]]) -> dict[str, str]:
    """Drop empty facts, keep the given order.

    NOTE: `meta` is jsonb, and Postgres normalises jsonb key order (by key
    length, then bytewise). The order written here is therefore *not* the
    order the board renders. If insertion order matters, change the column to
    `json` in schema.sql — see the docstring in the board's README.
    """
    return {k: v for k, v in ((k, clean(v)) for k, v in pairs) if v}


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)
