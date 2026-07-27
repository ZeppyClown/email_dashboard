# Wiring Hermes into the board

This is the piece that runs **locally**, as part of whatever already fires
Hermes at 6pm Tue–Sat (likely a nanoclaw `schedule_task`, per the CLAUDE.md
in `nanoclaw/groups/main/`). It needs the Supabase **service_role** key —
that key must live only in a local env var (e.g. `SUPABASE_SERVICE_ROLE_KEY`),
never in this repo, never in anything pushed to GitHub.

## 1. Before generating a digest — read learned preferences

Query the aggregate views from `schema.sql` and fold the result into the
digest-generation prompt as a short "known preferences" primer, e.g.:

```sql
select * from sender_feedback where total >= 3 order by not_interested_count desc;
select * from category_feedback;
```

Turn that into a couple of plain-English lines prepended to the prompt, e.g.:
"You've marked 5/5 emails from TLDR as not interested — keep those to one
line. You've marked 4/4 AI/ML internship listings as interested — surface
these prominently and in full detail."

## 2. After generating a digest — upsert structured items

For each discrete item extracted from the emails (one row per deadline,
internship listing, event, etc. — NOT one row per email), upsert into
`digest_items` using the service_role key (which bypasses RLS):

```json
{
  "id": "sha1(link or a stable source id, e.g. NTU job id 863414)",
  "digest_date": "2026-07-25",
  "category": "internship",
  "title": "AI Product Management Intern — Horizon Labs",
  "summary": "AI/ML product role, Y2 CS eligible.",
  "details": "Full context that doesn't fit the card face: why it matters, eligibility notes, related links, quoted specifics from the email (e.g. 'addressed to Y3 scholars — verify eligibility'). Shown in the board's slide-out detail panel when a card is clicked. This is where the richer prose from the old Markdown digest style belongs — don't just repeat `summary`.",
  "meta": {
    "Employer": "Horizon Labs",
    "Pay": "$500 – $1,000 Monthly",
    "Starts": "Jul/Aug-26",
    "Vacancies": "10",
    "Function": "Software / Multimedia / App Developer"
  },
  "sender": "JOB-BLAST@ntu.edu.sg",
  "link": "https://careeraxis.ntu.edu.sg/students/jobs/861104",
  "deadline_date": "2026-08-07"
}
```

`summary` stays a short one-liner for the compact card; `details` carries the fuller write-up — aim for the level of detail the old Markdown digests had per item (context, "why it matters", caveats), not just a repeat of the title.

`meta` is an open-ended object of short key/value facts, rendered as a table at
the top of the detail panel, in the order you write the keys. Use it for the
things that are a phrase rather than a paragraph — pay, vacancies, start date,
venue, duration. Keys differ per category and that's fine.

### Don't drop the spreadsheet columns

The JOB-BLAST xlsx attachments carry `Summary`, `Remuneration`, `Vacancies`,
`Commences`, `Occupation(s)`, `Industry` and `Contract type` per listing. Early
digests kept only title/employer/deadline/link, which is why the internship
cards opened to an empty panel. Those columns are the entire content of the
detail panel — carry `Summary` into `details` and the rest into `meta`.

Note what the spreadsheet does **not** have: a requirements column. Year of
study, GPA, tech stack and duration exist only on the CareerAxis listing page
(NTU login). Don't invent them — say they're on the listing and link it.

`scripts/upsert_internships.py` does exactly this for the internship sheet and
is the reference implementation; run it standalone to backfill, or fold its
`build_item()` mapping into the digest job.

Use `id` as a stable idempotency key (hash the link, or use NTU's own job ID
when present) so the same recurring listing doesn't spawn duplicate cards
every week, and so a listing you already dismissed doesn't resurface as new.
Upsert with `on_conflict=id` and **do not overwrite `status`** on conflict —
only update the content columns, so your board state survives re-sends.

## 3. Keep the Markdown digest too

Nothing here replaces `EmailDigests/YYYY-MM-DD-digest.md` — keep generating
it as the human-readable archive. The structured `digest_items` rows are an
additional, parallel output for the board.
