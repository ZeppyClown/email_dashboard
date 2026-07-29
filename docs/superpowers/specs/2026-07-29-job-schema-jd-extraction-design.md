# Job Schema + JD Extraction — Design

**Date:** 2026-07-29
**Status:** Approved (design), pending implementation plan
**Sub-project:** 1 of 6 in the job-application agent

---

## Context

The long-term goal is an end-to-end job application agent: discovery → analysis →
evidence matching → tailoring → application → email lifecycle tracking → analytics.
That is six independent subsystems and cannot be one spec. This document covers
**sub-project 1 only**: the canonical job schema and the structured extraction pass
that fills it.

Everything downstream reads or writes these tables, which is why this goes first
regardless of what is most interesting to build.

### What already exists

| Asset | Location | State |
|---|---|---|
| JD markdown corpus | `resume-kit/JDs/**/*.md` | 79 files (78 processable; 1 in `_duplicates`), YAML frontmatter, hand-curated in Obsidian |
| Deterministic detectors | `resume-kit/scraper/job_scraper.py` | `detect_degree_gate`, `detect_grad_window`, `detect_availability`, `extract_tech_stack`, `categorize_job` |
| Supabase helper | `email_dashboard/scripts/_common.py` | PostgREST over `requests`, secrets from `~/.hermes/.env` |
| Triage board | `digest_items` table + static dashboard | Working; internships carry full CareerAxis payload in `meta` |
| File ↔ board link | `board_id` in JD frontmatter | Already written back by `push_jds_to_board.py` |
| Career knowledge base | `resume-kit/resume_builder/support/skills_taxonomy.md` | 47 skills with proficiency, evidence, resume weight |

The gap is narrower than it first appears. Frontmatter already carries `company`,
`title`, `location`, `date_posted`, `employment_type`, `source_url`, `apply_url`,
`deadline`, `degree_gate`, `availability`. This sub-project promotes those into real
columns and adds the one thing nothing currently produces: **the required vs.
preferred skill split, and responsibilities.**

---

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | New `jobs` table; `digest_items` unchanged | `digest_items` is a daily triage inbox. A job being tracked is a different thing from "something I was told about", and one job will eventually have many applications. |
| 2 | Skills stored as raw text **and** nullable canonical id | Preserves the exact employer phrasing while making analytics groupable. Critically, it keeps skills employers want that Victor does not have — the most valuable signal, and the one a forced-canonical mapping would discard. |
| 3 | Markdown files authoritative for text; DB authoritative for structure | Victor edits JDs in Obsidian and `/make-resume` reads them from disk. A DB-authoritative design would clobber hand edits. DB stores a sha256 mirror so re-runs are free and off-machine agents can still read the JD. |
| 4 | Single-shot structured output, schema-validated | Cost is negligible at this scale (~170k input tokens total), so optimise for not silently getting it wrong. A verify pass is deferred until the required/preferred split is measured as unreliable. |
| 5 | Deterministic pre-parse for dates, salary, YOE | Regex can fail to match but cannot hallucinate. `job_scraper.py` already implements most of it. |
| 6 | One model: `gpt-5.4-mini` | `OPENAI_API_KEY` already lives in `~/.hermes/.env` beside the Supabase keys. No second credential path, no new SDK. The cheap/expensive model split from the original plan buys nothing at 78 JDs; `extractor_version` preserves the option to route a bulk pass elsewhere later. |
| 7 | `extraction_status` on the row, not a log table | The question that matters is "did every JD get processed". One column answers it, and a failed job stays visible instead of silently not existing. |
| 8 | Service-role writes only, no public read (RLS) | Unlike `digest_items`, this is not board content. `jd_markdown` mirrors scraped text and `skills` encodes Victor's own proficiency self-assessment. Locking it now costs nothing; un-publishing later is harder. |
| 9 | Code lives in `email_dashboard/scripts/` | `resume-kit/scraper/` already re-implements the Supabase helper inline in three scripts. A fourth copy makes it worse. `email_dashboard` owns `_common.py` and `schema.sql`, and is the repo with a GitHub remote. |

---

## Architecture

```
resume-kit/JDs/**/*.md          ← Victor edits here (Obsidian). Never overwritten.
        │
        ├── frontmatter ─────────> deterministic fields
        │                          (reuse job_scraper.py detectors + _common.parse_date)
        │
        ├── sha256(body) ────────> unchanged AND extractor_version current → skip, no API call
        │
        └── body ────────────────> gpt-5.4-mini, strict json_schema
                                        │
                                        ▼
                                   skills (required|preferred),
                                   responsibilities, seniority, min_yoe
                                        │
                                        ▼
          jobs ──< job_requirements >── skills ──< skill_aliases
              └──< job_responsibilities
              └──> digest_items(id)   [nullable link, via existing board_id]
```

### Identity

`jobs.id` reuses the JD's `board_id` when present, else `sha1(apply_url)`. This keeps
files, board cards, and job rows on one key, and makes re-runs idempotent. It mirrors
the existing `_common.stable_id` convention rather than inventing a second scheme.

---

## Schema

New file `email_dashboard/schema_jobs.sql`, idempotent in the same style as
`schema.sql` (`create table if not exists` + explicit `alter table … add column if
not exists` for later additions, because `if not exists` is a no-op on an existing
table).

### `jobs`

| Column | Type | Notes |
|---|---|---|
| `id` | text PK | `board_id`, else `sha1(apply_url)` |
| `company` | text not null | |
| `title` | text not null | |
| `role_category` | text | from frontmatter `role/*` tag |
| `location` | text | |
| `employment_type` | text | |
| `apply_url` | text | |
| `source_url` | text | |
| `posted_at` | date | |
| `closes_at` | date | frontmatter `deadline` |
| `degree_gate` | text | from `detect_degree_gate` |
| `availability` | text | from `detect_availability` |
| `seniority` | text | LLM-extracted |
| `min_yoe` | int | regex first, LLM fallback |
| `salary_raw` | text | verbatim, regex-matched only — never LLM-inferred |
| `jd_path` | text not null | relative to `--jds-root` |
| `jd_sha256` | text not null | of the body, not the frontmatter |
| `jd_markdown` | text | mirror, so off-machine readers do not need T9 mounted |
| `extracted_at` | timestamptz | |
| `extractor_version` | text | `gpt-5.4-mini@<prompt_hash>` |
| `extraction_status` | text not null default `'pending'` | check in (`pending`,`ok`,`failed`) |
| `extraction_error` | text | truncated |
| `digest_item_id` | text | FK → `digest_items(id)`, nullable |
| `created_at` / `updated_at` | timestamptz | `set_updated_at()` trigger, reused from `schema.sql` |

`salary_raw` is stored verbatim rather than parsed into min/max. Currencies, ranges,
"competitive", and per-month vs per-annum are inconsistent enough across sources that
a structured pair would be wrong often enough to distrust. Parse it when something
actually needs to filter on it.

When a JD has a `board_id`, `id` and `digest_item_id` hold the same value. The column
is kept separate because a JD scraped without ever reaching the board has a
`sha1(apply_url)` id and a null `digest_item_id` — collapsing them would make "is this
job on the board?" unanswerable.

Indexes on `company`, `role_category`, `extraction_status`, `closes_at`.

### `skills`

Canonical vocabulary, seeded from `skills_taxonomy.md`.

| Column | Type | Notes |
|---|---|---|
| `id` | bigserial PK | |
| `name` | text not null unique | |
| `category` | text | the taxonomy's 7 categories |
| `my_proficiency` | text | `expert` / `proficient` / `familiar`, **nullable** |
| `my_evidence` | text | |
| `resume_weight` | text | `HIGH` / `MED` / `LOW` |

A null `my_proficiency` is meaningful: a skill employers ask for that Victor does not
have yet. That row is the point of the table, not a defect in it.

### `skill_aliases`

| Column | Type |
|---|---|
| `alias` | text PK (lowercased) |
| `skill_id` | bigint → `skills(id)` |

### `job_requirements`

| Column | Type | Notes |
|---|---|---|
| `id` | bigserial PK | |
| `job_id` | text → `jobs(id)` on delete cascade | |
| `raw_text` | text not null | exact employer phrasing |
| `skill_id` | bigint → `skills(id)`, nullable | |
| `kind` | text not null | check in (`required`,`preferred`) |
| `confidence` | real | model-reported, 0–1 |
| `resolved_by` | text not null | check in (`alias`,`embedding`,`manual`,`unresolved`) |

Embedding resolution is **out of scope** here; the enum value exists so stage 2 needs
no migration.

### `job_responsibilities`

| Column | Type |
|---|---|
| `id` | bigserial PK |
| `job_id` | text → `jobs(id)` on delete cascade |
| `text` | text not null |
| `ordinal` | int not null |

### RLS

```sql
alter table jobs                 enable row level security;
alter table skills               enable row level security;
alter table skill_aliases        enable row level security;
alter table job_requirements     enable row level security;
alter table job_responsibilities enable row level security;
```

No policies are created. The service-role key bypasses RLS; `anon` and
`authenticated` therefore have no access at all, which is the intent. Revoke all on
each table from `anon, authenticated` explicitly so the posture is stated rather than
implied.

---

## Extraction pipeline

`email_dashboard/scripts/extract_jobs.py`, one pass per file:

1. Walk `--jds-root` (default `../resume-kit/JDs`), skipping `_duplicates/` and
   `_non_technical/`. **`_unsorted/` is included** — those 22 files are real jobs that
   simply lack a role tag, and they get `role_category = null`. Excluding them would
   silently drop a quarter of the corpus.
2. Parse frontmatter → deterministic fields. Reuse `job_scraper.py` detectors and
   `_common.parse_date`. Do not re-derive what already exists.
3. Compute `sha256(body)`. If it matches stored `jd_sha256` **and** `extractor_version`
   is current → skip, no API call.
4. Upsert the `jobs` row from deterministic fields with `extraction_status='pending'`,
   **before** any LLM call. A crash mid-run then leaves a visible pending row rather
   than nothing.
5. One `gpt-5.4-mini` call, `response_format: {type: "json_schema", strict: true}` →
   skills (each tagged required/preferred, with confidence), responsibilities,
   seniority, `min_yoe`.
6. Resolve each skill phrase against `skill_aliases` (lowercased exact match).
   Unresolved phrases are stored with `resolved_by='unresolved'`, never dropped.
7. Delete-then-insert this job's `job_requirements` and `job_responsibilities`, so
   re-extraction cannot accumulate duplicates.
8. Set `extraction_status='ok'`, stamp `extracted_at` and `extractor_version`.

### CLI

Matches the conventions already used by every script in `scripts/`:

```
python3 scripts/extract_jobs.py --dry-run
python3 scripts/extract_jobs.py
python3 scripts/extract_jobs.py --only <jd-slug>
python3 scripts/extract_jobs.py --force
python3 scripts/extract_jobs.py --jds-root /path/to/JDs
```

### Failure handling

- Retry once on transport errors, 5xx, and schema-validation failure.
- A second failure writes `extraction_status='failed'` plus a truncated
  `extraction_error`, then continues. One bad JD never stops the run.
- Missing `OPENAI_API_KEY` fails fast with the same "add it to `~/.hermes/.env`, not
  this repo" message `_common.load_config` already produces for the Supabase keys.
- Every run prints a summary: processed / skipped / failed, and lists failed slugs.

### Pre-flight

Before the first full run, call the model **once** with the real schema and one JD to
confirm structured-output behaviour and rate limits. `gpt-5.4-mini`'s exact
constraints are not assumed here. This is a step in the implementation plan, not a
runtime feature.

---

## Seeding

`email_dashboard/scripts/seed_skills.py` parses the markdown tables in
`skills_taxonomy.md` into `skills`. Idempotent on `name`. Re-runnable when the
taxonomy changes. `skill_aliases` starts empty and grows as unresolved phrases are
reviewed.

---

## Testing

Neither repo has test infrastructure or a `requirements.txt`, so a coverage
percentage would be a number with nothing to measure it. Scoped instead to what is
worth building:

- **Unit, no network or DB:** frontmatter parsing, sha256/skip logic, alias
  resolution, `jobs.id` derivation.
- **One fixture JD** with a deliberately tricky split (`"Python required; exposure to
  Rust a plus"`) asserted against a recorded model response, so prompt changes surface
  as a diff rather than silent drift.
- **`--dry-run` across all 78 JDs** as the integration check.

A `requirements.txt` (`requests`, `python-dotenv`, `openai`, `pytest`) is added as
part of this work, since the repo currently has none.

---

## Out of scope

Named explicitly so the plan does not drift into them:

- Match scoring / strong-possible-stretch categorisation (sub-project 2)
- `applications` table and lifecycle states (sub-project 3)
- Embedding-based skill resolution (sub-project 2)
- Any change to `digest_items`, the dashboard, or `/make-resume`
- Browser automation of any kind (sub-project 6, deliberately last)

---

## Success criteria

1. `schema_jobs.sql` runs clean in the Supabase SQL editor, and is re-runnable.
2. All 47 taxonomy skills seeded.
3. All 78 JDs present in `jobs`; count of `extraction_status='failed'` is zero, or
   each failure has a stated reason.
4. Every job has at least one `job_requirements` row, or an explicit reason it does not.
5. A second immediate run makes zero API calls.
6. Editing one JD in Obsidian and re-running re-extracts exactly that job.
