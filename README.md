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

## Resume packages page (local only)

`packages.html` is a three-pane workbench over the compiled resume packages in
`../resume-kit/output/`: the package list, a `.tex` editor, and a live PDF
preview. It shows the session-file status per package and a **stale** badge
whenever a `.tex` was edited after its PDF was built.

Build the page, then run the server that backs it:

```
python3 scripts/build_packages_page.py     # rescan output/, rebuild the list
python3 scripts/packages_server.py         # serve + the save/compile API
open http://localhost:8765/email_dashboard/packages.html
```

- **Cmd-S** saves the `.tex`. **Cmd-Enter** saves, runs `tectonic`, reloads the
  preview, and reports the kit's own char-count gate.
- The format for the char-count gate comes from the `\documentclass`, not the
  filename — the Danish Embassy package is called `..._cv.tex` but is built on
  `resume.cls` and must be measured against resume limits.
- Rerun `build_packages_page.py` after adding a *new* package; editing an
  existing one needs only the server.

Use `packages_server.py`, not `npx serve`/`http.server`. It roots itself at
`/Volumes/T9/resume` so the PDFs one level up resolve, and it adds the API the
editor needs. Without it the page still opens, read-only. The server binds to
127.0.0.1 only, and every API path is resolved and checked to be a `.tex`
inside `resume-kit/output` before it is read, written, or compiled — it writes
files and runs a compiler, so do not put it on a network interface.

`packages.html` is **gitignored on purpose.** This repo is public and deployed
to GitHub Pages; a list of live job applications is not public data. The link
in the board's topbar therefore 404s on the deployed site, by design.

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
