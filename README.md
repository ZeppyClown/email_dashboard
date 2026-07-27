# Hermes Digest Board

A Notion-style Kanban board for the daily Hermes email digest. Static
site (no build step) meant for GitHub Pages, backed by Supabase.

## Setup

1. **Supabase**
   - Open your existing Supabase project's SQL editor and run `schema.sql`.
     It's idempotent — re-run it after pulling changes to pick up new columns
     (the `meta` facts column was added this way).
   - In **Authentication → Providers**, make sure Email (magic link) is enabled.
   - In **Authentication → URL Configuration**, add your GitHub Pages URL
     (e.g. `https://yourname.github.io/repo/`) as a redirect URL, or the
     magic link will bounce back somewhere unexpected.
   - Copy your project's **URL** and **anon/public key** (Project Settings →
     API) into `config.js`. This key is *meant* to be public — commit it.
     Do **not** ever put the `service_role` key here.

2. **GitHub Pages**
   - Push this `dashboard/` folder to a GitHub repo.
   - Repo Settings → Pages → deploy from the branch/folder containing this
     folder. No Actions/build step needed, it's plain static files.

3. **Hermes side** — see `hermes-integration.md` for how the local digest
   job should read preferences and write items into Supabase using the
   `service_role` key (kept local, never committed).

## Local preview

ES modules need to be served over HTTP, not opened as a `file://` URL:

```
npx serve .
```

## Board mechanics

- Reading the board requires no login (public data, per RLS in `schema.sql`).
- Dragging a card between columns requires signing in via the email field
  top-right (magic link, no password). This stops random visitors from
  messing with your board while keeping the content itself public.
- Columns: **New → Interested / Not interested → Done**. Category chips
  (internship/hackathon/course/deadline/scholarship/other) filter the board,
  each showing a live count.
- Cards are one-line rows: a category dot, the title, and the due date. The
  chevron expands the summary in place; clicking the card opens the full
  drawer. Columns scroll internally so the page stays one screen tall however
  many cards there are.
- Rows are grouped by urgency — Overdue / This week / This month / Later / No
  deadline — and the last two start folded. Fold state persists per browser.
- **Search** (`/` focuses it) matches title, summary, details, employer and
  your notes. **Hide past deadlines** is on by default.
- With the `hackathon` chip active, a **team size** selector appears: pick the
  number of people you have and it shows the events you can enter. Events whose
  organiser never published a size stay visible.
- Each card has a **note** field in the drawer — why it is or isn't for you.
  Notes save on blur, are searchable, mark the card with `✎`, and are what
  Hermes reads (via the `feedback_notes` view) to learn from. `status` alone
  can't distinguish "Y3+ only" from "not interested in finance".
- Card status changes sync live across open tabs/devices via Supabase
  realtime — no refresh needed.
