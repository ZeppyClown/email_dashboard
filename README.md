# Hermes Digest Board

A Notion-style Kanban board for the daily Hermes email digest. Static
site (no build step) meant for GitHub Pages, backed by Supabase.

## Setup

1. **Supabase**
   - Open your existing Supabase project's SQL editor and run `schema.sql`.
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
  (deadline/internship/scholarship/course/other) filter the board.
- Card status changes sync live across open tabs/devices via Supabase
  realtime — no refresh needed.
