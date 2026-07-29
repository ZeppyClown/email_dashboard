# Job Schema + JD Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn 78 hand-curated JD markdown files into queryable structured rows in Supabase, including the required-vs-preferred skill split that nothing currently produces.

**Architecture:** JD markdown files stay authoritative for text; Supabase owns structure. A CLI walks the JD corpus, parses frontmatter deterministically, skips unchanged files via sha256, and sends only the body to `gpt-5.4-mini` with a strict JSON schema for the fuzzy fields (skills, responsibilities, seniority). Skill phrases are stored raw plus a nullable canonical id resolved against an alias table.

**Tech Stack:** Python 3, `requests` (PostgREST, no Supabase SDK), `python-dotenv`, `openai`, `pytest`. Postgres via Supabase.

**Spec:** `docs/superpowers/specs/2026-07-29-job-schema-jd-extraction-design.md`

## Global Constraints

- **Repo:** all new code lives in `/Volumes/T9/resume/email_dashboard/`. Never write into `resume-kit/` except reading JD files.
- **Secrets:** only from `~/.hermes/.env`. Never a key in the repo, never a key in a commit, never printed to stdout.
- **Supabase access:** PostgREST over `requests`, following `scripts/_common.py`. Do not add the `supabase` SDK.
- **DDL:** PostgREST cannot run DDL. Every schema change goes in a `.sql` file that Victor pastes into the Supabase SQL editor. Scripts must fail with a message saying so.
- **Idempotency:** every script is safe to re-run. Re-running with no source changes must make zero API calls and zero writes.
- **Model:** `gpt-5.4-mini` for all LLM calls.
- **JD corpus root:** `../resume-kit/JDs` relative to `email_dashboard/`. Skip `_duplicates/` and `_non_technical/`. **Include `_unsorted/`.** Corpus is **79 files → 78 processable** (the one `_duplicates/` file is the withdrawn Tencent role). `_non_technical/` was deleted from `resume-kit` on 2026-07-29; the skip stays as a guard because the sibling `claude-resume-kit` checkout still has one.
- **CLI convention:** every script supports `--dry-run` and prints a processed/skipped/failed summary, matching `upsert_internships.py`.
- **Never write `digest_items.note` or `digest_items.status`.** This plan should not write `digest_items` at all.

---

## File Structure

| File | Responsibility |
|---|---|
| `requirements.txt` | **Create.** Repo currently has none. |
| `schema_jobs.sql` | **Create.** DDL for `jobs`, `skills`, `skill_aliases`, `job_requirements`, `job_responsibilities`. |
| `scripts/_common.py` | **Modify.** Add `openai_key()`. Nothing else changes. |
| `scripts/jd_parse.py` | **Create.** Pure functions: frontmatter, body, sha256, job id, salary, min_yoe. No network, no DB. |
| `scripts/extract_llm.py` | **Create.** The `gpt-5.4-mini` call, JSON schema, response validation. |
| `scripts/jobs_db.py` | **Create.** PostgREST writers for the five new tables + alias resolution. |
| `scripts/seed_skills.py` | **Create.** `skills_taxonomy.md` → `skills` table. |
| `scripts/extract_jobs.py` | **Create.** CLI orchestration. |
| `tests/test_jd_parse.py` | **Create.** Pure-function tests. |
| `tests/test_extract_llm.py` | **Create.** Schema validation against a recorded response. |
| `tests/test_seed_skills.py` | **Create.** Taxonomy parser tests. |
| `tests/fixtures/` | **Create.** One tricky JD + one recorded model response. |

Split by responsibility, not layer: `jd_parse` is pure and testable offline, `extract_llm` owns the one external API, `jobs_db` owns the one database, `extract_jobs` only wires them together. This keeps every file small enough to hold in context and means the expensive-to-test parts are the smallest parts.

---

### Task 1: Test scaffolding and the OpenAI credential

**Files:**
- Create: `email_dashboard/requirements.txt`
- Create: `email_dashboard/tests/__init__.py` (empty)
- Create: `email_dashboard/tests/test_common.py`
- Modify: `email_dashboard/scripts/_common.py` (append at end of the config section, after `load_config`)

**Interfaces:**
- Consumes: `_common.HERMES_ENV`, `_common.ConfigError` (already exist)
- Produces: `openai_key() -> str` — returns the key or raises `ConfigError` with a message naming `~/.hermes/.env`

- [ ] **Step 1: Create `requirements.txt`**

```
requests>=2.31
python-dotenv>=1.0
openai>=1.40
pytest>=8.0
```

- [ ] **Step 2: Write the failing test**

Create `email_dashboard/tests/test_common.py`:

```python
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import _common


def test_openai_key_returns_value(monkeypatch):
    monkeypatch.setattr(_common, "HERMES_ENV", Path("/nonexistent"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
    assert _common.openai_key() == "sk-test-123"


def test_openai_key_raises_when_missing(monkeypatch):
    monkeypatch.setattr(_common, "HERMES_ENV", Path("/nonexistent"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(_common.ConfigError) as exc:
        _common.openai_key()
    assert ".hermes" in str(exc.value)


def test_openai_key_not_leaked_in_error(monkeypatch):
    """The error explains where to put the key, never echoes one."""
    monkeypatch.setattr(_common, "HERMES_ENV", Path("/nonexistent"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(_common.ConfigError) as exc:
        _common.openai_key()
    assert "sk-" not in str(exc.value)
```

- [ ] **Step 3: Run it and confirm it fails**

```bash
cd /Volumes/T9/resume/email_dashboard && python3 -m pytest tests/test_common.py -v
```

Expected: FAIL — `AttributeError: module '_common' has no attribute 'openai_key'`

- [ ] **Step 4: Implement `openai_key`**

Append to `scripts/_common.py`, immediately after `load_config`:

```python
def openai_key() -> str:
    """Return OPENAI_API_KEY, or explain where it belongs.

    Same source as the Supabase keys — Hermes' own env file — so there is one
    credential path for the whole pipeline, not two.
    """
    if HERMES_ENV.exists():
        load_dotenv(HERMES_ENV)

    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise ConfigError(
            f"Missing OPENAI_API_KEY in {HERMES_ENV}.\n"
            "Add it there, not to this repo."
        )
    return key
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Volumes/T9/resume/email_dashboard && python3 -m pytest tests/test_common.py -v
```

Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
cd /Volumes/T9/resume/email_dashboard
git add requirements.txt tests/__init__.py tests/test_common.py scripts/_common.py
git commit -m "feat: add openai_key() and test scaffolding

Reads OPENAI_API_KEY from ~/.hermes/.env alongside the Supabase keys, so the
pipeline has one credential path rather than two."
```

---

### Task 2: JD parsing (pure functions)

**Files:**
- Create: `email_dashboard/scripts/jd_parse.py`
- Create: `email_dashboard/tests/test_jd_parse.py`
- Create: `email_dashboard/tests/fixtures/sample_jd.md`

**Interfaces:**
- Consumes: nothing (deliberately dependency-free — no network, no DB, no env)
- Produces:
  - `frontmatter(text: str) -> dict[str, str]`
  - `body(text: str) -> str`
  - `body_sha256(text: str) -> str`
  - `job_id(fm: dict[str, str]) -> str`
  - `salary_raw(body_text: str) -> str | None`
  - `min_yoe(body_text: str) -> int | None`
  - `role_category(text: str) -> str | None`

**Note on duplication:** `frontmatter` and `body` are ported from
`resume-kit/scraper/push_jds_to_board.py`. They are copied, not imported, because
`resume-kit` is a separate git repo with no remote and a `sys.path` hack across that
boundary would make this repo unrunnable on its own. The docstring must say so.

- [ ] **Step 1: Create the fixture**

Create `email_dashboard/tests/fixtures/sample_jd.md`:

```markdown
---
tags:
  - type/jd
  - role/ai_engineer
  - status/new
company: "Acme Labs"
title: "AI Engineer Intern"
location: "Singapore"
date_posted: "2026-07-14"
employment_type: "Temporary"
deadline: "2026-09-09"
board_id: "abc123def456"
apply_url: "https://example.com/jobs/1"
---

# AI Engineer Intern at Acme Labs

- **Company:** Acme Labs

---

## 🛠️ Detected Tech Stack & Keywords
`Python`

---

## 📖 Full Job Details & Description

We need 3+ years of software engineering experience.
Python is required; exposure to Rust is a plus.
Salary: SGD 1,200 - 1,800 per month.
```

- [ ] **Step 2: Write the failing tests**

Create `email_dashboard/tests/test_jd_parse.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import jd_parse

FIXTURE = (Path(__file__).parent / "fixtures" / "sample_jd.md").read_text()


def test_frontmatter_reads_quoted_values():
    fm = jd_parse.frontmatter(FIXTURE)
    assert fm["company"] == "Acme Labs"
    assert fm["title"] == "AI Engineer Intern"
    assert fm["board_id"] == "abc123def456"


def test_frontmatter_skips_tag_list_items():
    fm = jd_parse.frontmatter(FIXTURE)
    assert "- type/jd" not in fm
    assert "tags" not in fm


def test_frontmatter_empty_when_absent():
    assert jd_parse.frontmatter("# Just a heading\n") == {}


def test_body_starts_after_full_details_heading():
    b = jd_parse.body(FIXTURE)
    assert b.startswith("We need 3+ years")
    assert "Detected Tech Stack" not in b


def test_body_sha256_is_stable_and_ignores_frontmatter():
    """Editing frontmatter must not trigger re-extraction; editing the posting must."""
    edited_fm = FIXTURE.replace('status/new', 'status/applied')
    assert jd_parse.body_sha256(FIXTURE) == jd_parse.body_sha256(edited_fm)

    edited_body = FIXTURE.replace("exposure to Rust", "exposure to Go")
    assert jd_parse.body_sha256(FIXTURE) != jd_parse.body_sha256(edited_body)


def test_job_id_prefers_board_id():
    assert jd_parse.job_id({"board_id": "abc123", "apply_url": "https://x/1"}) == "abc123"


def test_job_id_falls_back_to_apply_url_hash():
    got = jd_parse.job_id({"apply_url": "https://example.com/jobs/1"})
    assert len(got) == 40          # sha1 hex
    assert got == jd_parse.job_id({"apply_url": "https://example.com/jobs/1"})


def test_job_id_raises_without_either():
    import pytest
    with pytest.raises(ValueError):
        jd_parse.job_id({})


def test_salary_raw_captures_range():
    assert jd_parse.salary_raw(jd_parse.body(FIXTURE)) == "SGD 1,200 - 1,800 per month"


def test_salary_raw_none_when_absent():
    assert jd_parse.salary_raw("No pay information here at all.") is None


def test_salary_raw_does_not_invent_from_prose():
    """'competitive' is not a salary. Returning None beats returning a guess."""
    assert jd_parse.salary_raw("We offer a competitive salary package.") is None


def test_min_yoe_reads_years():
    assert jd_parse.min_yoe(jd_parse.body(FIXTURE)) == 3


def test_min_yoe_none_when_absent():
    assert jd_parse.min_yoe("An internship for current students.") is None


def test_role_category_from_tag():
    assert jd_parse.role_category(FIXTURE) == "ai_engineer"


def test_role_category_none_for_unsorted():
    assert jd_parse.role_category("---\ntags:\n  - type/jd\n---\n\nbody") is None
```

- [ ] **Step 3: Run and confirm failure**

```bash
cd /Volumes/T9/resume/email_dashboard && python3 -m pytest tests/test_jd_parse.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'jd_parse'`

- [ ] **Step 4: Implement `jd_parse.py`**

```python
"""Pure parsing of JD markdown. No network, no database, no environment.

`frontmatter` and `body` are ported from resume-kit/scraper/push_jds_to_board.py
rather than imported: resume-kit is a separate git repo with no remote, and a
sys.path hack across that boundary would leave this repo unable to run alone.
Copied deliberately — if the JD format changes, both need updating.
"""
from __future__ import annotations

import hashlib
import re

# 3+ years of X experience. Allows words between "years" and the noun, so
# "8+ years of software engineering experience" and bare "5+ years software
# engineering" both register. Ported from job_scraper.detect_degree_gate.
_YOE = re.compile(
    r"(\d+)\s*\+?\s*years?(?:\s+of)?(?:\s+[\w/-]+){0,4}?"
    r"\s*(?:experience|engineering|developing|building)",
    re.I,
)

# Only a currency symbol or code next to digits counts. "Competitive salary"
# deliberately does not match — a None is honest, a guess is not.
_SALARY = re.compile(
    r"((?:SGD|USD|MYR|S\$|US\$|\$|£|€)\s*[\d,]+(?:\.\d+)?"
    r"(?:\s*(?:-|–|to)\s*(?:(?:SGD|USD|MYR|S\$|US\$|\$|£|€)\s*)?[\d,]+(?:\.\d+)?)?"
    r"(?:\s*(?:per|/)\s*(?:month|mth|annum|year|hour|hr))?)",
    re.I,
)

_ROLE_TAG = re.compile(r"^\s*-\s*role/([\w_]+)\s*$", re.M)


def frontmatter(text: str) -> dict[str, str]:
    """YAML-ish frontmatter as a flat dict. List items and `tags:` are skipped."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).split("\n"):
        if line.startswith(("  -", "tags:")) or ":" not in line:
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"')
    return out


def body(text: str) -> str:
    """The posting itself — everything under the Full Job Details heading."""
    m = re.search(r"##\s*📖[^\n]*\n(.*)", text, re.S)
    out = m.group(1) if m else text
    out = re.split(r"\n---\s*\n##\s*Application Tracking", out)[0]
    return out.strip()


def body_sha256(text: str) -> str:
    """Hash of the posting only.

    Frontmatter is excluded on purpose: `board_status` and `tags` change as
    Victor triages, and those edits must not trigger a paid re-extraction.
    """
    return hashlib.sha256(body(text).encode("utf-8")).hexdigest()


def job_id(fm: dict[str, str]) -> str:
    """Stable key. Reuses board_id so files, cards and job rows share one id."""
    board = (fm.get("board_id") or "").strip()
    if board:
        return board
    url = (fm.get("apply_url") or fm.get("source_url") or "").strip().lower()
    if not url:
        raise ValueError("job_id needs board_id, apply_url or source_url")
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def salary_raw(body_text: str) -> str | None:
    """Verbatim salary string, or None. Never inferred, only matched."""
    m = _SALARY.search(body_text)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


def min_yoe(body_text: str) -> int | None:
    """Minimum years of experience demanded, or None if unstated."""
    m = _YOE.search(body_text)
    return int(m.group(1)) if m else None


def role_category(text: str) -> str | None:
    """The `role/*` frontmatter tag. None for _unsorted JDs, which is valid."""
    m = _ROLE_TAG.search(text)
    return m.group(1) if m else None
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Volumes/T9/resume/email_dashboard && python3 -m pytest tests/test_jd_parse.py -v
```

Expected: 15 passed. If `test_salary_raw_captures_range` fails on the trailing
`per month`, adjust `_SALARY` — do not weaken
`test_salary_raw_does_not_invent_from_prose`, which is the test that matters.

- [ ] **Step 6: Commit**

```bash
cd /Volumes/T9/resume/email_dashboard
git add scripts/jd_parse.py tests/test_jd_parse.py tests/fixtures/sample_jd.md
git commit -m "feat: pure JD markdown parsing

Frontmatter, body, content hash, stable id, and regex-only salary/YOE.
Hash covers the posting body only, so triage edits to frontmatter do not
trigger a paid re-extraction."
```

---

### Task 3: Database schema

**Files:**
- Create: `email_dashboard/schema_jobs.sql`

**Interfaces:**
- Consumes: `digest_items(id)` and `set_updated_at()` from the existing `schema.sql`
- Produces: tables `jobs`, `skills`, `skill_aliases`, `job_requirements`, `job_responsibilities`

This task has no automated test — PostgREST cannot run DDL, so verification is
Victor pasting it into the Supabase SQL editor and it running clean twice.

- [ ] **Step 1: Write `schema_jobs.sql`**

```sql
-- Job-application agent — canonical job schema (sub-project 1).
-- Run in the Supabase SQL editor, after schema.sql. Idempotent: safe to re-run.
--
-- Separate from schema.sql on purpose. digest_items is a public triage board;
-- these tables are private working data and carry the opposite RLS posture.

-- ------------------------------------------------------------------- jobs ---

create table if not exists jobs (
  id text primary key,          -- board_id when the JD has one, else sha1(apply_url)
  company text not null,
  title text not null,
  role_category text,           -- null is valid: _unsorted JDs have no role tag
  location text,
  employment_type text,
  apply_url text,
  source_url text,
  posted_at date,
  closes_at date,
  degree_gate text,
  availability text,
  seniority text,
  min_yoe int,
  salary_raw text,              -- verbatim. Currencies/ranges/periods vary too
                                -- much across sources for a min/max pair to be
                                -- right often enough to trust. Parse it when
                                -- something actually needs to filter on it.
  jd_path text not null,        -- relative to --jds-root
  jd_sha256 text not null,      -- of the posting body, NOT the frontmatter
  jd_markdown text,             -- mirror, so a run off this machine does not
                                -- need the T9 drive mounted
  extracted_at timestamptz,
  extractor_version text,       -- 'gpt-5.4-mini@<prompt_hash>'. Bumping this
                                -- re-extracts everything without a manual purge.
  extraction_status text not null default 'pending'
    check (extraction_status in ('pending','ok','failed')),
  extraction_error text,
  digest_item_id text references digest_items(id) on delete set null,
                                -- equals `id` when the JD has a board_id. Kept
                                -- separate because a JD that never reached the
                                -- board has a sha1 id and a null here, and
                                -- collapsing them makes "is this on the board?"
                                -- unanswerable.
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table jobs add column if not exists salary_raw text;
alter table jobs add column if not exists seniority text;

create index if not exists idx_jobs_company on jobs(company);
create index if not exists idx_jobs_role_category on jobs(role_category);
create index if not exists idx_jobs_extraction_status on jobs(extraction_status);
create index if not exists idx_jobs_closes_at on jobs(closes_at);

drop trigger if exists trg_jobs_updated_at on jobs;
create trigger trg_jobs_updated_at
before update on jobs
for each row execute function set_updated_at();

-- ----------------------------------------------------------------- skills ---

create table if not exists skills (
  id bigserial primary key,
  name text not null unique,
  category text,
  my_proficiency text check (my_proficiency in ('expert','proficient','familiar')),
                                -- NULL is the important case: a skill employers
                                -- ask for that Victor does not have yet. That row
                                -- is the point of this table, not a defect in it.
  my_evidence text,
  resume_weight text check (resume_weight in ('HIGH','MED','LOW')),
  created_at timestamptz not null default now()
);

create table if not exists skill_aliases (
  alias text primary key,       -- lowercased
  skill_id bigint not null references skills(id) on delete cascade
);

-- --------------------------------------------------------- job → skills ---

create table if not exists job_requirements (
  id bigserial primary key,
  job_id text not null references jobs(id) on delete cascade,
  raw_text text not null,       -- the employer's exact phrasing, always kept
  skill_id bigint references skills(id) on delete set null,
  kind text not null check (kind in ('required','preferred')),
  confidence real,
  resolved_by text not null default 'unresolved'
    check (resolved_by in ('alias','embedding','manual','unresolved'))
                                -- 'embedding' is unused in sub-project 1. It
                                -- exists so stage 2 needs no migration.
);

create index if not exists idx_job_requirements_job on job_requirements(job_id);
create index if not exists idx_job_requirements_skill on job_requirements(skill_id);
create index if not exists idx_job_requirements_unresolved
  on job_requirements(resolved_by) where resolved_by = 'unresolved';

create table if not exists job_responsibilities (
  id bigserial primary key,
  job_id text not null references jobs(id) on delete cascade,
  text text not null,
  ordinal int not null
);

create index if not exists idx_job_responsibilities_job on job_responsibilities(job_id);

-- -------------------------------------------------------------------- RLS ---
-- Opposite posture to digest_items. That board is public content; this is not.
-- jd_markdown mirrors scraped postings and `skills` encodes Victor's own
-- proficiency self-assessment. No policies are created, so anon/authenticated
-- have no access at all; only the service_role key (which bypasses RLS) writes.

alter table jobs                 enable row level security;
alter table skills               enable row level security;
alter table skill_aliases        enable row level security;
alter table job_requirements     enable row level security;
alter table job_responsibilities enable row level security;

revoke all on jobs                 from anon, authenticated;
revoke all on skills               from anon, authenticated;
revoke all on skill_aliases        from anon, authenticated;
revoke all on job_requirements     from anon, authenticated;
revoke all on job_responsibilities from anon, authenticated;
```

- [ ] **Step 2: Apply it**

Paste the whole file into the Supabase SQL editor and run. **Then run it a second
time.** The second run must also succeed — that is the idempotency check, and it is
the only way to catch a missing `if not exists` before it bites during a later edit.

- [ ] **Step 3: Verify the tables exist and are locked down**

```bash
cd /Volumes/T9/resume/email_dashboard && python3 -c "
import sys; sys.path.insert(0, 'scripts')
import _common
for t in ('jobs','skills','skill_aliases','job_requirements','job_responsibilities'):
    print(t, len(_common.select(t)))
"
```

Expected: each prints `0`. An error naming an unknown relation means the SQL was not
applied.

- [ ] **Step 4: Commit**

```bash
cd /Volumes/T9/resume/email_dashboard
git add schema_jobs.sql
git commit -m "feat: schema for jobs, skills and requirements

Private counterpart to schema.sql: RLS on with no policies, so only the
service_role key reaches these tables. Skill rows keep raw employer phrasing
alongside a nullable canonical id."
```

---

### Task 4: Seed the skills table from the taxonomy

**Files:**
- Create: `email_dashboard/scripts/seed_skills.py`
- Create: `email_dashboard/tests/test_seed_skills.py`

**Interfaces:**
- Consumes: `_common.select`, `_common.load_config`
- Produces: `parse_taxonomy(text: str) -> list[dict]` with keys
  `name, category, my_proficiency, my_evidence, resume_weight`

- [ ] **Step 1: Write the failing test**

Create `email_dashboard/tests/test_seed_skills.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import seed_skills

SAMPLE = """# Skills Taxonomy — Victor Chua

## Summary Stats
- Total unique skills: 2

---

## Category 1: AI / LLM

| Skill | Proficiency | Evidence | Resume Weight |
|-------|-------------|----------|---------------|
| RAG (retrieval-augmented generation) | Expert | Yap Motor production | HIGH |
| LangGraph | Familiar | Drum Hub agent design | MED |

---

## Category 2: Machine Learning

| Skill | Proficiency | Evidence | Resume Weight |
|-------|-------------|----------|---------------|
| PyTorch | Proficient | Drum Hub OMR training | HIGH |
"""


def test_parses_every_row():
    rows = seed_skills.parse_taxonomy(SAMPLE)
    assert len(rows) == 3


def test_skips_the_separator_row():
    names = [r["name"] for r in seed_skills.parse_taxonomy(SAMPLE)]
    assert not any(set(n) <= {"-", " "} for n in names)
    assert "Skill" not in names


def test_proficiency_is_lowercased_to_match_the_check_constraint():
    rows = {r["name"]: r for r in seed_skills.parse_taxonomy(SAMPLE)}
    assert rows["RAG (retrieval-augmented generation)"]["my_proficiency"] == "expert"
    assert rows["LangGraph"]["my_proficiency"] == "familiar"


def test_category_carries_down_from_the_heading():
    rows = {r["name"]: r for r in seed_skills.parse_taxonomy(SAMPLE)}
    assert rows["PyTorch"]["category"] == "Machine Learning"
    assert rows["LangGraph"]["category"] == "AI / LLM"


def test_resume_weight_preserved():
    rows = {r["name"]: r for r in seed_skills.parse_taxonomy(SAMPLE)}
    assert rows["PyTorch"]["resume_weight"] == "HIGH"
```

- [ ] **Step 2: Run and confirm failure**

```bash
cd /Volumes/T9/resume/email_dashboard && python3 -m pytest tests/test_seed_skills.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'seed_skills'`

- [ ] **Step 3: Implement `seed_skills.py`**

```python
#!/usr/bin/env python3
"""Seed the `skills` table from the resume kit's skills taxonomy.

The taxonomy markdown is the source of truth for what Victor can do and what
evidence backs it. This mirrors it into Postgres so job requirements have
something to resolve against.

    python3 scripts/seed_skills.py --dry-run
    python3 scripts/seed_skills.py
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402

DEFAULT_TAXONOMY = (
    Path(__file__).resolve().parents[2]
    / "resume-kit" / "resume_builder" / "support" / "skills_taxonomy.md"
)

_HEADING = re.compile(r"^##\s*Category\s*\d+:\s*(.+?)\s*$", re.M)
_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*$", re.M)

_VALID_PROFICIENCY = {"expert", "proficient", "familiar"}
_VALID_WEIGHT = {"HIGH", "MED", "LOW"}


def parse_taxonomy(text: str) -> list[dict[str, Any]]:
    """Markdown tables under `## Category N:` headings → skill rows."""
    rows: list[dict[str, Any]] = []

    # Split into (category, chunk) pairs so each row knows its heading.
    marks = [(m.group(1), m.end()) for m in _HEADING.finditer(text)]
    for i, (category, start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(text)
        chunk = text[start:end]

        for m in _ROW.finditer(chunk):
            name, prof, evidence, weight = (c.strip() for c in m.groups())

            if name.lower() == "skill":                 # header row
                continue
            if set(name) <= {"-", " ", ":"}:            # separator row
                continue
            if not name:
                continue

            prof_clean = prof.lower().strip("* ")
            weight_clean = weight.upper().strip("* ")

            rows.append({
                "name": re.sub(r"\\", "", name),
                "category": category,
                "my_proficiency": prof_clean if prof_clean in _VALID_PROFICIENCY else None,
                "my_evidence": re.sub(r"\\", "", evidence) or None,
                "resume_weight": weight_clean if weight_clean in _VALID_WEIGHT else None,
            })

    return rows


def upsert_skills(rows: list[dict[str, Any]], *, dry_run: bool = False) -> int:
    """Insert-or-update on `name`. Re-runnable when the taxonomy changes."""
    if not rows or dry_run:
        return len(rows)

    url, key = _common.load_config()
    r = requests.post(
        f"{url}/rest/v1/skills",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
        params={"on_conflict": "name"},
        json=rows,
        timeout=_common.TIMEOUT,
    )
    if r.status_code >= 400:
        raise RuntimeError(
            f"Seeding skills failed [{r.status_code}]: {r.text[:400]}\n"
            "If this names an unknown relation, paste schema_jobs.sql into the "
            "Supabase SQL editor — PostgREST cannot run DDL."
        )
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.taxonomy.exists():
        _common.die(f"taxonomy not found: {args.taxonomy}")

    rows = parse_taxonomy(args.taxonomy.read_text(encoding="utf-8"))
    if not rows:
        _common.die(f"no skill rows parsed from {args.taxonomy}")

    written = upsert_skills(rows, dry_run=args.dry_run)
    unrated = sum(1 for r in rows if r["my_proficiency"] is None)

    print(f"{'would seed' if args.dry_run else 'seeded'} {written} skills "
          f"({unrated} with no proficiency)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Volumes/T9/resume/email_dashboard && python3 -m pytest tests/test_seed_skills.py -v
```

Expected: 5 passed

- [ ] **Step 5: Dry-run against the real taxonomy**

```bash
cd /Volumes/T9/resume/email_dashboard && python3 scripts/seed_skills.py --dry-run
```

Expected: `would seed 47 skills (0 with no proficiency)`. If the count is not 47,
the table regex is missing rows — fix before writing anything.

- [ ] **Step 6: Seed for real and verify**

```bash
cd /Volumes/T9/resume/email_dashboard && python3 scripts/seed_skills.py
python3 -c "
import sys; sys.path.insert(0,'scripts'); import _common
print(len(_common.select('skills')))"
```

Expected: `47`. Run `seed_skills.py` once more — the count must stay 47, not double.

- [ ] **Step 7: Commit**

```bash
cd /Volumes/T9/resume/email_dashboard
git add scripts/seed_skills.py tests/test_seed_skills.py
git commit -m "feat: seed skills table from resume-kit taxonomy

Upserts on name so re-running after a taxonomy edit updates rather than
duplicates."
```

---

### Task 5: The extraction call

**Files:**
- Create: `email_dashboard/scripts/extract_llm.py`
- Create: `email_dashboard/tests/test_extract_llm.py`
- Create: `email_dashboard/tests/fixtures/recorded_response.json`

**Interfaces:**
- Consumes: `_common.openai_key` (Task 1)
- Produces:
  - `MODEL: str` = `"gpt-5.4-mini"`
  - `SCHEMA: dict` — the strict JSON schema
  - `extractor_version() -> str` — `"gpt-5.4-mini@<8-char prompt hash>"`
  - `validate(payload: dict) -> dict` — raises `ValueError` on violation
  - `extract(body_text: str, *, client=None) -> dict` — one call, one retry

- [ ] **Step 1: Pre-flight — confirm the model behaves as assumed**

Before writing anything, verify `gpt-5.4-mini` accepts a strict `json_schema`
response format. This is the one assumption in the spec that was explicitly not
taken on faith.

```bash
cd /Volumes/T9/resume/email_dashboard && python3 -c "
import sys; sys.path.insert(0,'scripts'); import _common
from openai import OpenAI
c = OpenAI(api_key=_common.openai_key())
r = c.chat.completions.create(
    model='gpt-5.4-mini',
    messages=[{'role':'user','content':'Say hi as JSON.'}],
    response_format={'type':'json_schema','json_schema':{
        'name':'probe','strict':True,
        'schema':{'type':'object','additionalProperties':False,
                  'properties':{'greeting':{'type':'string'}},
                  'required':['greeting']}}},
)
print(r.choices[0].message.content)
"
```

Expected: `{"greeting":"hi"}` or similar valid JSON.

**If this errors**, stop and report the error rather than working around it. Likely
adaptations: the model name differs, or this model wants the Responses API
(`client.responses.create` with `text.format`) instead of Chat Completions. Either
is a small change confined to `extract()` — but confirm which before writing it.

- [ ] **Step 2: Record a real response as a fixture**

```bash
cd /Volumes/T9/resume/email_dashboard && python3 -c "
import sys, json; sys.path.insert(0,'scripts')
import _common, jd_parse
from pathlib import Path
body = jd_parse.body(Path('tests/fixtures/sample_jd.md').read_text())
print(body)
"
```

After Task 5 Step 4 exists, re-run `extract()` on this body once and save the parsed
dict to `tests/fixtures/recorded_response.json`. Until then, hand-write the file with
the response the schema demands:

```json
{
  "seniority": "intern",
  "min_yoe": 3,
  "skills": [
    {"raw_text": "Python", "kind": "required", "confidence": 0.95},
    {"raw_text": "Rust", "kind": "preferred", "confidence": 0.8}
  ],
  "responsibilities": [
    "Build and maintain AI systems"
  ]
}
```

- [ ] **Step 3: Write the failing tests**

Create `email_dashboard/tests/test_extract_llm.py`:

```python
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import extract_llm

RECORDED = json.loads((Path(__file__).parent / "fixtures" / "recorded_response.json").read_text())


def test_recorded_response_validates():
    assert extract_llm.validate(RECORDED) == RECORDED


def test_required_and_preferred_are_distinguished():
    """The whole point of the extraction. If this blurs, match scores are wrong."""
    out = extract_llm.validate(RECORDED)
    by_kind = {s["raw_text"]: s["kind"] for s in out["skills"]}
    assert by_kind["Python"] == "required"
    assert by_kind["Rust"] == "preferred"


def test_rejects_unknown_kind():
    bad = json.loads(json.dumps(RECORDED))
    bad["skills"][0]["kind"] = "nice-to-have"
    with pytest.raises(ValueError, match="kind"):
        extract_llm.validate(bad)


def test_rejects_missing_skills_key():
    bad = {k: v for k, v in RECORDED.items() if k != "skills"}
    with pytest.raises(ValueError, match="skills"):
        extract_llm.validate(bad)


def test_rejects_absurd_yoe():
    bad = json.loads(json.dumps(RECORDED))
    bad["min_yoe"] = 60
    with pytest.raises(ValueError, match="min_yoe"):
        extract_llm.validate(bad)


def test_null_yoe_is_allowed():
    ok = json.loads(json.dumps(RECORDED))
    ok["min_yoe"] = None
    assert extract_llm.validate(ok)["min_yoe"] is None


def test_empty_skills_list_is_allowed():
    """A JD really can list no concrete skills. That is data, not an error."""
    ok = json.loads(json.dumps(RECORDED))
    ok["skills"] = []
    assert extract_llm.validate(ok)["skills"] == []


def test_extractor_version_is_stable_and_names_the_model():
    v = extract_llm.extractor_version()
    assert v == extract_llm.extractor_version()
    assert v.startswith("gpt-5.4-mini@")


def test_extract_retries_once_then_raises():
    class Boom:
        calls = 0

        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    Boom.calls += 1
                    raise RuntimeError("503")

    with pytest.raises(RuntimeError):
        extract_llm.extract("some body", client=Boom)
    assert Boom.calls == 2
```

- [ ] **Step 4: Run and confirm failure**

```bash
cd /Volumes/T9/resume/email_dashboard && python3 -m pytest tests/test_extract_llm.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'extract_llm'`

- [ ] **Step 5: Implement `extract_llm.py`**

```python
"""The one external LLM call: JD body → skills, responsibilities, seniority.

Deterministic fields (dates, salary, years) are parsed by jd_parse before this
runs. This module only handles what regex genuinely cannot: telling a required
skill from a preferred one, and reading responsibilities out of prose.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402

MODEL = "gpt-5.4-mini"

PROMPT = """You extract structured facts from a job description.

Rules:
- Use ONLY what the posting states. Never infer, never fill gaps from general
  knowledge about the company or role.
- `kind` is "required" only when the posting frames it as a must ("required",
  "must have", "you have", "essential"). Anything framed as "nice to have",
  "a plus", "bonus", "preferred", or "desirable" is "preferred". When the
  framing is genuinely ambiguous, choose "preferred" — over-stating a
  requirement wrongly rules a candidate out.
- `raw_text` is the employer's own wording for the skill, not a normalised name.
- `min_yoe` is the minimum years of experience demanded, or null if unstated.
- `seniority` is one of: intern, junior, mid, senior, lead, unspecified.
- `responsibilities` are the duties of the role, in the posting's order.
"""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["seniority", "min_yoe", "skills", "responsibilities"],
    "properties": {
        "seniority": {
            "type": "string",
            "enum": ["intern", "junior", "mid", "senior", "lead", "unspecified"],
        },
        "min_yoe": {"type": ["integer", "null"]},
        "skills": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["raw_text", "kind", "confidence"],
                "properties": {
                    "raw_text": {"type": "string"},
                    "kind": {"type": "string", "enum": ["required", "preferred"]},
                    "confidence": {"type": "number"},
                },
            },
        },
        "responsibilities": {"type": "array", "items": {"type": "string"}},
    },
}

_VALID_KIND = {"required", "preferred"}
_VALID_SENIORITY = {"intern", "junior", "mid", "senior", "lead", "unspecified"}


def extractor_version() -> str:
    """Model plus a hash of the prompt and schema.

    Bumping either re-extracts everything on the next run, with no manual purge
    and no chance of a table half-built by two different prompts.
    """
    seed = (PROMPT + json.dumps(SCHEMA, sort_keys=True)).encode("utf-8")
    return f"{MODEL}@{hashlib.sha256(seed).hexdigest()[:8]}"


def validate(payload: dict) -> dict:
    """Semantic checks the JSON schema cannot express.

    Structured output guarantees shape, not sense. A model can emit a
    schema-valid `min_yoe` of 60.
    """
    for key in ("seniority", "min_yoe", "skills", "responsibilities"):
        if key not in payload:
            raise ValueError(f"missing key: {key}")

    if payload["seniority"] not in _VALID_SENIORITY:
        raise ValueError(f"bad seniority: {payload['seniority']!r}")

    yoe = payload["min_yoe"]
    if yoe is not None:
        if not isinstance(yoe, int) or not 0 <= yoe <= 50:
            raise ValueError(f"implausible min_yoe: {yoe!r}")

    if not isinstance(payload["skills"], list):
        raise ValueError("skills must be a list")
    for s in payload["skills"]:
        if s.get("kind") not in _VALID_KIND:
            raise ValueError(f"bad kind: {s.get('kind')!r}")
        if not (s.get("raw_text") or "").strip():
            raise ValueError("empty raw_text in skills")

    if not isinstance(payload["responsibilities"], list):
        raise ValueError("responsibilities must be a list")

    return payload


def _client():
    from openai import OpenAI
    return OpenAI(api_key=_common.openai_key())


def extract(body_text: str, *, client=None) -> dict:
    """One extraction. Retries once, then raises for the caller to record."""
    c = client or _client()
    last: Exception | None = None

    for _ in range(2):
        try:
            resp = c.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": body_text[:60000]},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "jd", "strict": True, "schema": SCHEMA},
                },
            )
            return validate(json.loads(resp.choices[0].message.content))
        except Exception as exc:      # transport, 5xx, or validation
            last = exc

    raise RuntimeError(f"extraction failed after 2 attempts: {last}") from last
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd /Volumes/T9/resume/email_dashboard && python3 -m pytest tests/test_extract_llm.py -v
```

Expected: 9 passed

- [ ] **Step 7: Real call against the fixture, then re-record**

```bash
cd /Volumes/T9/resume/email_dashboard && python3 -c "
import sys, json; sys.path.insert(0,'scripts')
import jd_parse, extract_llm
from pathlib import Path
body = jd_parse.body(Path('tests/fixtures/sample_jd.md').read_text())
out = extract_llm.extract(body)
print(json.dumps(out, indent=2))
Path('tests/fixtures/recorded_response.json').write_text(json.dumps(out, indent=2))
"
```

Expected: Python tagged `required`, Rust tagged `preferred`. **If Rust comes back
`required`, stop** — that is the failure mode the whole design guards against, and it
means the prompt needs work before 78 JDs go through it.

Re-run the tests after re-recording; they must still pass.

- [ ] **Step 8: Commit**

```bash
cd /Volumes/T9/resume/email_dashboard
git add scripts/extract_llm.py tests/test_extract_llm.py tests/fixtures/recorded_response.json
git commit -m "feat: gpt-5.4-mini structured extraction of skills and duties

Strict json_schema guarantees shape; validate() catches what schemas cannot,
like a plausible-looking min_yoe of 60. Ambiguous framing resolves to
'preferred' — over-stating a requirement wrongly rules Victor out."
```

---

### Task 6: Database writers and alias resolution

**Files:**
- Create: `email_dashboard/scripts/jobs_db.py`
- Create: `email_dashboard/tests/test_jobs_db.py`

**Interfaces:**
- Consumes: `_common.load_config`, `_common.TIMEOUT`
- Produces:
  - `load_alias_map() -> dict[str, int]` — lowercased alias/name → `skill_id`
  - `resolve(raw_text: str, alias_map: dict[str, int]) -> tuple[int | None, str]`
    returning `(skill_id, resolved_by)`
  - `upsert_job(row: dict, *, dry_run: bool = False) -> None`
  - `replace_children(job_id: str, requirements: list[dict], responsibilities: list[dict], *, dry_run: bool = False) -> None`
  - `existing_state() -> dict[str, tuple[str, str]]` — `job_id → (jd_sha256, extractor_version)`

- [ ] **Step 1: Write the failing tests**

Create `email_dashboard/tests/test_jobs_db.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import jobs_db

ALIASES = {"python": 1, "pytorch": 2, "rag (retrieval-augmented generation)": 3}


def test_resolve_exact_name():
    assert jobs_db.resolve("Python", ALIASES) == (1, "alias")


def test_resolve_is_case_and_space_insensitive():
    assert jobs_db.resolve("  PYTHON  ", ALIASES) == (1, "alias")


def test_resolve_unknown_stays_unresolved_not_dropped():
    """An unmatched phrase must survive as a row. It is the gap signal."""
    assert jobs_db.resolve("Kubernetes", ALIASES) == (None, "unresolved")


def test_resolve_strips_trailing_punctuation():
    assert jobs_db.resolve("PyTorch.", ALIASES) == (2, "alias")


def test_resolve_empty_is_unresolved():
    assert jobs_db.resolve("   ", ALIASES) == (None, "unresolved")
```

- [ ] **Step 2: Run and confirm failure**

```bash
cd /Volumes/T9/resume/email_dashboard && python3 -m pytest tests/test_jobs_db.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'jobs_db'`

- [ ] **Step 3: Implement `jobs_db.py`**

```python
"""PostgREST writers for the job tables.

Follows _common.py's approach — requests against PostgREST, no Supabase SDK —
but targets the job tables rather than digest_items, so it does not reuse
_common.upsert (which is hardcoded to that table).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402


def _headers(key: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    h = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def _norm(text: str) -> str:
    """Lowercase, collapse whitespace, drop trailing punctuation."""
    return re.sub(r"\s+", " ", (text or "")).strip().strip(".,;:").lower()


# ------------------------------------------------------------------ reads ---

def load_alias_map() -> dict[str, int]:
    """Canonical names AND aliases, both normalised, mapped to skill_id."""
    out: dict[str, int] = {}
    for row in _common.select("skills", {"select": "id,name"}):
        out[_norm(row["name"])] = row["id"]
    for row in _common.select("skill_aliases", {"select": "alias,skill_id"}):
        out[_norm(row["alias"])] = row["skill_id"]
    return out


def existing_state() -> dict[str, tuple[str, str]]:
    """job_id → (jd_sha256, extractor_version). Drives the skip check."""
    rows = _common.select("jobs", {"select": "id,jd_sha256,extractor_version"})
    return {r["id"]: (r.get("jd_sha256") or "", r.get("extractor_version") or "")
            for r in rows}


def resolve(raw_text: str, alias_map: dict[str, int]) -> tuple[int | None, str]:
    """Map an employer phrase to a canonical skill id.

    Exact (normalised) match only. Embedding fallback is stage 2's job. An
    unmatched phrase is stored with resolved_by='unresolved', never dropped —
    those rows are exactly the skills Victor does not yet have.
    """
    key = _norm(raw_text)
    if not key:
        return (None, "unresolved")
    hit = alias_map.get(key)
    return (hit, "alias") if hit is not None else (None, "unresolved")


# ----------------------------------------------------------------- writes ---

def upsert_job(row: dict[str, Any], *, dry_run: bool = False) -> None:
    if dry_run:
        return
    url, key = _common.load_config()
    r = requests.post(
        f"{url}/rest/v1/jobs",
        headers=_headers(key, {"Prefer": "resolution=merge-duplicates,return=minimal"}),
        params={"on_conflict": "id"},
        json=[row],
        timeout=_common.TIMEOUT,
    )
    if r.status_code >= 400:
        raise RuntimeError(
            f"Upsert job {row.get('id')} failed [{r.status_code}]: {r.text[:400]}\n"
            "If this names an unknown relation or column, paste schema_jobs.sql "
            "into the Supabase SQL editor — PostgREST cannot run DDL."
        )


def mark_failed(job_id: str, error: str, *, dry_run: bool = False) -> None:
    """Record an extraction failure on the row instead of losing the job."""
    if dry_run:
        return
    url, key = _common.load_config()
    r = requests.patch(
        f"{url}/rest/v1/jobs",
        headers=_headers(key, {"Prefer": "return=minimal"}),
        params={"id": f"eq.{job_id}"},
        json={"extraction_status": "failed", "extraction_error": error[:500]},
        timeout=_common.TIMEOUT,
    )
    r.raise_for_status()


def _delete_children(table: str, job_id: str, key: str, url: str) -> None:
    r = requests.delete(
        f"{url}/rest/v1/{table}",
        headers=_headers(key, {"Prefer": "return=minimal"}),
        params={"job_id": f"eq.{job_id}"},
        timeout=_common.TIMEOUT,
    )
    r.raise_for_status()


def _insert(table: str, rows: list[dict[str, Any]], key: str, url: str) -> None:
    if not rows:
        return
    r = requests.post(
        f"{url}/rest/v1/{table}",
        headers=_headers(key, {"Prefer": "return=minimal"}),
        json=rows,
        timeout=_common.TIMEOUT,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Insert into {table} failed [{r.status_code}]: {r.text[:400]}")


def replace_children(
    job_id: str,
    requirements: list[dict[str, Any]],
    responsibilities: list[dict[str, Any]],
    *,
    dry_run: bool = False,
) -> None:
    """Delete then insert.

    Re-extraction must not accumulate duplicate requirement rows, and there is
    no natural unique key on (job_id, raw_text) worth enforcing — the same
    phrase can legitimately appear twice with different framing.
    """
    if dry_run:
        return
    url, key = _common.load_config()
    _delete_children("job_requirements", job_id, key, url)
    _delete_children("job_responsibilities", job_id, key, url)
    _insert("job_requirements", requirements, key, url)
    _insert("job_responsibilities", responsibilities, key, url)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Volumes/T9/resume/email_dashboard && python3 -m pytest tests/test_jobs_db.py -v
```

Expected: 5 passed

- [ ] **Step 5: Verify reads work against the live database**

```bash
cd /Volumes/T9/resume/email_dashboard && python3 -c "
import sys; sys.path.insert(0,'scripts'); import jobs_db
m = jobs_db.load_alias_map()
print(len(m), 'aliases')
print(jobs_db.resolve('PyTorch', m))
print(jobs_db.resolve('Kubernetes', m))
print(len(jobs_db.existing_state()), 'existing jobs')
"
```

Expected: 47 aliases (skills seeded, no aliases yet), `PyTorch` resolves,
`Kubernetes` is `(None, 'unresolved')`, 0 existing jobs.

- [ ] **Step 6: Commit**

```bash
cd /Volumes/T9/resume/email_dashboard
git add scripts/jobs_db.py tests/test_jobs_db.py
git commit -m "feat: PostgREST writers and alias resolution for job tables

Unresolved skill phrases are stored, not dropped — those rows are the record
of what employers want that Victor does not have. Children are replaced rather
than merged so re-extraction cannot duplicate."
```

---

### Task 7: The CLI

**Files:**
- Create: `email_dashboard/scripts/extract_jobs.py`

**Interfaces:**
- Consumes: `jd_parse` (Task 2), `extract_llm` (Task 5), `jobs_db` (Task 6), `_common`
- Produces: the `extract_jobs.py` CLI. Nothing imports this.

- [ ] **Step 1: Implement `extract_jobs.py`**

```python
#!/usr/bin/env python3
"""Turn the resume-kit JD corpus into structured rows in Supabase.

Frontmatter and regex handle everything deterministic; only the posting body
reaches the model, and only for what regex genuinely cannot do. A JD whose body
has not changed since the last run costs nothing.

    python3 scripts/extract_jobs.py --dry-run
    python3 scripts/extract_jobs.py
    python3 scripts/extract_jobs.py --only griffin_labs_private_limited_ai_engineer_intern
    python3 scripts/extract_jobs.py --force
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common      # noqa: E402
import extract_llm  # noqa: E402
import jd_parse     # noqa: E402
import jobs_db      # noqa: E402

DEFAULT_JDS = Path(__file__).resolve().parents[2] / "resume-kit" / "JDs"

# _unsorted is deliberately absent: those 22 files are real jobs that merely
# lack a role tag, and skipping them would silently drop a quarter of the corpus.
SKIP_DIRS = {"_duplicates", "_non_technical"}


def jd_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*.md")
        if not SKIP_DIRS & set(p.relative_to(root).parts)
    )


def build_job_row(path: Path, text: str, root: Path) -> dict[str, Any] | None:
    """Deterministic fields only. Returns None if the JD lacks an identity."""
    fm = jd_parse.frontmatter(text)
    body_text = jd_parse.body(text)

    try:
        job_id = jd_parse.job_id(fm)
    except ValueError:
        return None

    company = fm.get("company") or ""
    title = fm.get("title") or ""
    if not company or not title:
        return None

    return {
        "id": job_id,
        "company": company,
        "title": title,
        "role_category": jd_parse.role_category(text),
        "location": fm.get("location"),
        "employment_type": fm.get("employment_type"),
        "apply_url": fm.get("apply_url"),
        "source_url": fm.get("source_url"),
        "posted_at": _common.parse_date(fm.get("date_posted")),
        "closes_at": _common.parse_date(fm.get("deadline")),
        "degree_gate": fm.get("degree_gate"),
        "availability": fm.get("availability"),
        "min_yoe": jd_parse.min_yoe(body_text),
        "salary_raw": jd_parse.salary_raw(body_text),
        "jd_path": str(path.relative_to(root)),
        "jd_sha256": jd_parse.body_sha256(text),
        "jd_markdown": body_text,
        "extraction_status": "pending",
        "digest_item_id": fm.get("board_id") or None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jds-root", type=Path, default=DEFAULT_JDS)
    ap.add_argument("--only", help="process one JD by filename stem")
    ap.add_argument("--force", action="store_true", help="ignore the sha256 skip check")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = args.jds_root
    if not root.exists():
        _common.die(f"JD root not found: {root}  (is the T9 drive mounted?)")

    files = jd_files(root)
    if args.only:
        files = [p for p in files if p.stem == args.only]
        if not files:
            _common.die(f"no JD with stem {args.only!r} under {root}")

    version = extract_llm.extractor_version()
    state = jobs_db.existing_state()
    alias_map = jobs_db.load_alias_map()

    processed = skipped = failed = 0
    failures: list[str] = []

    for path in files:
        text = path.read_text(encoding="utf-8")
        row = build_job_row(path, text, root)
        if row is None:
            skipped += 1
            continue

        prev = state.get(row["id"])
        if not args.force and prev == (row["jd_sha256"], version):
            skipped += 1
            continue

        # Write the row before calling the model, so a crash mid-run leaves a
        # visible 'pending' job rather than no trace of the JD at all.
        jobs_db.upsert_job(row, dry_run=args.dry_run)

        if args.dry_run:
            processed += 1
            continue

        try:
            out = extract_llm.extract(row["jd_markdown"])
        except Exception as exc:
            jobs_db.mark_failed(row["id"], str(exc))
            failed += 1
            failures.append(path.stem)
            continue

        requirements = []
        for s in out["skills"]:
            skill_id, how = jobs_db.resolve(s["raw_text"], alias_map)
            requirements.append({
                "job_id": row["id"],
                "raw_text": s["raw_text"],
                "skill_id": skill_id,
                "kind": s["kind"],
                "confidence": s.get("confidence"),
                "resolved_by": how,
            })

        responsibilities = [
            {"job_id": row["id"], "text": t, "ordinal": i}
            for i, t in enumerate(out["responsibilities"])
        ]

        jobs_db.replace_children(row["id"], requirements, responsibilities)

        jobs_db.upsert_job({
            **row,
            "seniority": out["seniority"],
            "min_yoe": row["min_yoe"] if row["min_yoe"] is not None else out["min_yoe"],
            "extraction_status": "ok",
            "extraction_error": None,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "extractor_version": version,
        })
        processed += 1

    verb = "would process" if args.dry_run else "processed"
    print(f"{verb} {processed}, skipped {skipped}, failed {failed}")
    if failures:
        print("failed: " + ", ".join(failures))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Note `min_yoe`: regex wins when it matched, and the model only fills the gap. That
is the pre-parse decision made concrete — deterministic first, LLM as fallback.

- [ ] **Step 2: Dry-run over the whole corpus**

```bash
cd /Volumes/T9/resume/email_dashboard && python3 scripts/extract_jobs.py --dry-run
```

Expected: `would process 78, skipped N, failed 0`. A large `skipped` count means
`build_job_row` is returning `None` too often — inspect before proceeding, because
those JDs would silently never be extracted.

- [ ] **Step 3: Real run on one JD first**

```bash
cd /Volumes/T9/resume/email_dashboard
python3 scripts/extract_jobs.py --only griffin_labs_private_limited_ai_engineer_intern
python3 -c "
import sys; sys.path.insert(0,'scripts'); import _common
j = _common.select('jobs')[0]
print(j['company'], '|', j['title'], '|', j['extraction_status'], '|', j['seniority'])
for r in _common.select('job_requirements'):
    print(' ', r['kind'], r['raw_text'], '->', r['resolved_by'])
"
```

Expected: one `ok` job with requirements split across `required`/`preferred`, some
resolved to skill ids and some `unresolved`.

- [ ] **Step 4: Commit**

```bash
cd /Volumes/T9/resume/email_dashboard
git add scripts/extract_jobs.py
git commit -m "feat: extract_jobs CLI

Writes the job row before calling the model, so a crash leaves a visible
pending job rather than no trace. Regex min_yoe wins over the model's; the
model only fills the gap."
```

---

### Task 8: Full run and verification against the spec

**Files:**
- Modify: `email_dashboard/README.md` (add a section on the job pipeline)

- [ ] **Step 1: Run the full corpus**

```bash
cd /Volumes/T9/resume/email_dashboard && python3 scripts/extract_jobs.py
```

Expected: `processed 78, skipped N, failed 0`. Any failures print their slugs;
re-run those individually with `--only <slug>` and record why if they persist.

- [ ] **Step 2: Verify every success criterion from the spec**

```bash
cd /Volumes/T9/resume/email_dashboard && python3 -c "
import sys, collections; sys.path.insert(0,'scripts'); import _common

jobs = _common.select('jobs')
reqs = _common.select('job_requirements')
print('jobs:', len(jobs))
print('status:', collections.Counter(j['extraction_status'] for j in jobs))
print('skills seeded:', len(_common.select('skills')))

by_job = collections.Counter(r['job_id'] for r in reqs)
missing = [j['id'] for j in jobs if by_job[j['id']] == 0]
print('jobs with no requirements:', len(missing), missing[:5])

print('resolved:', collections.Counter(r['resolved_by'] for r in reqs))
print('kinds:', collections.Counter(r['kind'] for r in reqs))
"
```

Check against the spec:
1. `schema_jobs.sql` ran clean twice — done in Task 3.
2. Skills seeded == 47.
3. All JDs present; `failed` count is 0, or each failure has a stated reason.
4. Every job has ≥1 requirement, or an explicit reason it does not.
5. **Second run makes zero API calls** — verified in Step 3 below.
6. Editing a JD re-extracts only that job — verified in Step 4 below.

If `kinds` shows almost everything as `required`, the prompt is not doing its job.
Stop and fix it — that is the failure the design exists to prevent, and it silently
corrupts every match score in sub-project 2.

- [ ] **Step 3: Verify the skip path is free**

```bash
cd /Volumes/T9/resume/email_dashboard && time python3 scripts/extract_jobs.py
```

Expected: `processed 0, skipped 78, failed 0`, completing in seconds. A non-zero
`processed` means the sha256 or `extractor_version` comparison is broken and every
run will be paying for the whole corpus.

- [ ] **Step 4: Verify targeted re-extraction**

```bash
cd /Volumes/T9/resume/email_dashboard
JD=$(python3 -c "
import sys; sys.path.insert(0,'scripts'); import _common
print(_common.select('jobs', {'limit':'1','select':'jd_path'})[0]['jd_path'])")
echo "  (edited for re-extraction test)" >> "../resume-kit/JDs/$JD"
python3 scripts/extract_jobs.py
git -C ../resume-kit checkout -- "JDs/$JD"
```

Expected: `processed 1, skipped ~83`. Note the JD edit is reverted afterwards —
`resume-kit` has uncommitted changes already, so leave nothing new behind.

- [ ] **Step 5: Document it in the README**

Append to `email_dashboard/README.md`:

```markdown
## Job pipeline (sub-project 1)

Turns the `resume-kit/JDs/` markdown corpus into structured rows for the job
application agent. Markdown stays the source of truth for JD text; these tables
own the structure.

    python3 scripts/seed_skills.py          # skills_taxonomy.md -> skills
    python3 scripts/extract_jobs.py --dry-run
    python3 scripts/extract_jobs.py

Tables live in `schema_jobs.sql` — paste it into the Supabase SQL editor, like
`schema.sql`. They are private: RLS is on with no policies, so only the
service_role key reaches them.

Re-runs are free. A JD is re-extracted only when its posting body changes or
`extract_llm.extractor_version()` changes (i.e. the model or prompt changed).
Frontmatter edits from triage do not trigger a paid re-run.

Skill phrases employers use are stored verbatim alongside a nullable canonical
`skill_id`. Unmatched phrases stay as `resolved_by='unresolved'` — those are the
skills employers want that aren't in the taxonomy yet, which is the point.

    -- what employers ask for that Victor has no skill row for
    select raw_text, count(*) from job_requirements
    where resolved_by = 'unresolved' group by raw_text order by 2 desc;
```

- [ ] **Step 6: Run the whole test suite**

```bash
cd /Volumes/T9/resume/email_dashboard && python3 -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
cd /Volumes/T9/resume/email_dashboard
git add README.md
git commit -m "docs: document the job extraction pipeline

Includes the unresolved-skills query, which is the first thing sub-project 2
will need: what employers ask for that the taxonomy has no row for."
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| `jobs` table, all columns incl. `salary_raw` | 3 |
| `skills`, `skill_aliases`, `job_requirements`, `job_responsibilities` | 3 |
| RLS: service-role only, no policies | 3 |
| `id` = `board_id` else `sha1(apply_url)` | 2 (`job_id`), 7 |
| `digest_item_id` kept separate from `id` | 3, 7 |
| sha256 of body only; skip unchanged | 2 (`body_sha256`), 7 |
| `extractor_version` triggers re-extraction | 5, 7 |
| Deterministic pre-parse (dates, salary, YOE) | 2, 7 |
| Reuse `job_scraper.py` detector regexes | 2 (`_YOE` ported) |
| Single-shot `gpt-5.4-mini`, strict json_schema | 5 |
| Pre-flight before 78 calls | 5 Step 1 |
| Retry once, then `extraction_status='failed'` | 5 (`extract`), 6 (`mark_failed`), 7 |
| Row written before LLM call | 7 |
| Alias resolution; unresolved never dropped | 6 |
| Delete-then-insert children | 6 |
| Seed skills from taxonomy | 4 |
| `--dry-run`, `--only`, `--force`, summary | 7 |
| `_unsorted/` included | 7 (`SKIP_DIRS`) |
| `requirements.txt` created | 1 |
| Unit tests on pure functions | 2, 4, 6 |
| Fixture JD with tricky required/preferred split | 2, 5 |
| `--dry-run` over all 78 as integration check | 7 Step 2, 8 |
| All six success criteria | 8 Step 2–4 |

No gaps.

**Type consistency:** `jd_parse.job_id(fm)` takes the frontmatter dict, matching its
call in `build_job_row`. `jobs_db.resolve` returns `(int｜None, str)`, unpacked as
`skill_id, how` in Task 7. `extract_llm.extract` returns the validated dict with keys
`seniority`/`min_yoe`/`skills`/`responsibilities`, all four read in Task 7.
`existing_state()` returns `dict[str, tuple[str, str]]`, compared against the tuple
`(row["jd_sha256"], version)` — matching arity and order.

**Placeholders:** none. Every code step contains runnable code.

**One known soft spot:** Task 5 Step 1 is a genuine unknown — `gpt-5.4-mini`'s exact
structured-output API is verified at runtime rather than assumed. That step is
written to stop and report rather than improvise, because guessing there would
silently shape every downstream call.
