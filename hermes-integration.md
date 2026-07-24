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
  "sender": "JOB-BLAST@ntu.edu.sg",
  "link": "https://careeraxis.ntu.edu.sg/students/jobs/861104",
  "deadline_date": "2026-08-07"
}
```

Use `id` as a stable idempotency key (hash the link, or use NTU's own job ID
when present) so the same recurring listing doesn't spawn duplicate cards
every week, and so a listing you already dismissed doesn't resurface as new.
Upsert with `on_conflict=id` and **do not overwrite `status`** on conflict —
only update the content columns, so your board state survives re-sends.

## 3. Keep the Markdown digest too

Nothing here replaces `EmailDigests/YYYY-MM-DD-digest.md` — keep generating
it as the human-readable archive. The structured `digest_items` rows are an
additional, parallel output for the board.
