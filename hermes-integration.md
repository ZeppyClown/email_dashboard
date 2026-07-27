# Wiring Hermes into the board

This is the piece that runs **locally**, as part of whatever already fires
Hermes at 6pm Tue–Sat (likely a nanoclaw `schedule_task`, per the CLAUDE.md
in `nanoclaw/groups/main/`). It needs the Supabase **service_role** key —
that key must live only in a local env var (e.g. `SUPABASE_SERVICE_ROLE_KEY`),
never in this repo, never in anything pushed to GitHub.

## 1. Before generating a digest — read learned preferences

Two layers. The counts say *what* Victor rejected; the notes say *why*, and the
why is what actually changes the next digest.

```sql
select * from sender_feedback where total >= 3 order by not_interested_count desc;
select * from category_feedback;
select * from feedback_notes limit 30;   -- free text, newest first
```

Turn that into a couple of plain-English lines prepended to the prompt, e.g.:
"You've marked 5/5 emails from TLDR as not interested — keep those to one
line. You've marked 4/4 AI/ML internship listings as interested — surface
these prominently and in full detail."

`feedback_notes` is the more valuable of the two and needs quoting, not
summarising: "not interested — Y3+ only" and "not interested — don't want
finance" are opposite lessons that the counts cannot tell apart. The first
means *keep sending these, just check eligibility*; the second means *stop
sending them*.

**Never write `note`.** It is the one column Victor owns — the board's textarea
is the only thing that should ever set it. Overwriting it destroys the only
record of his reasoning.

## 2. After generating a digest — upsert structured items

For each discrete item extracted from the emails (one row per deadline,
internship listing, event, etc. — NOT one row per email), upsert into
`digest_items` using the service_role key (which bypasses RLS):

```json
{
  "id": "sha1(link or a stable source id, e.g. NTU job id 863414)",
  "digest_date": "2026-07-25",
  "category": "internship",
  "source": "careeraxis",
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

## 3. Pick the category honestly

The board has six: `internship`, `hackathon`, `course`, `deadline`,
`scholarship`, `other`. Everything career-flavoured used to land in
`internship`, which made the category useless — 101 cards of which 28 were
company visits, career talks, resume workshops and hackathons.

The rule that fixed it, and that new writes must hold to:

- **`internship`** — an actual job posting, with a job description behind it.
  In practice that means a CareerAxis `/students/jobs/<id>` link, because that
  is the one source with a scraper (`scripts/scrape_careeraxis.py`) that can
  fill `details` and `meta`. A card that cannot say what the role involves is
  not an internship card.
- **`hackathon`** — hackathons, case competitions, build challenges,
  datathons. Anything you enter as a team and win a prize.
- **`other`** — company visits, open days, career fairs, talks, webinars,
  networking sessions, resume/interview workshops, and roles that arrived as a
  one-line email mention with only a careers-homepage link.

That last clause matters and is counter-intuitive: a genuine HSBC internship
whose card says only "Deadline 30 Oct 2026" belongs in `other`, not
`internship`. It is a real opening, but as a *card* it carries nothing to act
on. Eight such cards were moved out. When a scraper exists for those sites,
they can move back.

## 4. `source` — where the facts came from

New column. One slug per system the details were scraped from:

| value | meaning |
|---|---|
| `careeraxis` | NTU CareerAxis portal, scraped listing |
| `ntu-email` | parsed out of an NTU careers email, no portal behind it |
| *(future)* | `justpostedjob` and one slug per site added later |

Keep it a small, filterable set — don't mint a value per employer. `source` is
deliberately **not** `sender`: sender is who emailed you, source is which
system the facts were scraped from, and a single JOB-BLAST email yields cards
of both kinds.

## 5. Don't create a second card for the same thing

Several events are on the board twice — a "(registration)" card from one digest
day and a "(details)" card from another, with the URLs split one per card, so
whichever you opened the link you wanted was on the other. Before inserting,
check whether the event already has a card and update it instead.

When an event genuinely has two useful URLs, put **both in `meta`** as
`Register` and `Info site` rather than spending a card on each. The drawer
renders any `http(s)` meta value as a clickable link.

## 6. Hackathons need team size

Team size decides whether Victor can enter at all — a 3–5 person event needs a
squad lined up *before* the deadline. The board filters on it, so write:

- `Team size` — the organiser's own wording, e.g. `"Teams of 3–5"`
- `Team min` / `Team max` — integers, for the filter to compare against

Omit `Team min`/`Team max` when the organiser never published a number; the
filter treats unknown as "might fit" and keeps showing the card. Don't guess.

`scripts/enrich_hackathons.py` is the reference implementation and holds the
curated facts for the seven events currently on the board.

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
Upsert with `on_conflict=id` and **do not overwrite `status` or `note`** on
conflict — only update the content columns, so board state and Victor's
reasoning survive re-sends.

## 7. Expired listings

`scripts/audit_internships.py --check` asks CareerAxis which listings are still
live; `/services/students/jobs/<id>?studentSiteId=1` answers 404 once a listing
is withdrawn. Only a 404 means gone — a 401 or a non-JSON body means the
borrowed NTU session expired, and treating that as "withdrawn" would mark a
whole run for deletion.

Cards for withdrawn listings are deleted. Cards that are merely *past their
deadline* are not — the board hides them behind a toggle instead, because a
closed listing is still evidence of what Victor was interested in, and
`sender_feedback` still counts it.

## 8. Schema changes need a human

PostgREST cannot run DDL. Any new column or a widened CHECK constraint has to
be pasted into the Supabase SQL editor by Victor — this has blocked work three
times now (`meta`, `source`, then `note` + the `hackathon` category). Write the
`alter table ... if not exists` into `schema.sql`, print the exact statement
when a write 400s, and do everything else meanwhile rather than waiting.

## 9. Keep the Markdown digest too

Nothing here replaces `EmailDigests/YYYY-MM-DD-digest.md` — keep generating
it as the human-readable archive. The structured `digest_items` rows are an
additional, parallel output for the board.
