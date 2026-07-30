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

## Resume packages page

`packages.html` sits beside the board: a sidebar of every compiled package in
`../resume-kit/output/`, and clicking a document shows its LaTeX source and
rendered PDF side by side. Each package carries its session-file status, and a
**stale** badge appears when a `.tex` was edited after its PDF was built.

```
python3 scripts/build_packages_page.py
```

That copies each PDF and a first-page thumbnail into `packages/` and embeds the
`.tex` source in the page. Rerun it whenever a package is added or recompiled
outside the page.

### The editor

`vendor/editor.js` is a committed **CodeMirror 6** bundle — the same editor
core Overleaf uses, MIT licensed. It gives LaTeX syntax highlighting, line
numbers, code folding, bracket matching, undo history, and Cmd-F search. If the
bundle is missing the page falls back to a plain textarea rather than breaking.
See `vendor/README.md` to rebuild it.

Tick **auto** in the editor header for Overleaf-style recompile-on-pause: about
a second and a half after you stop typing, it saves and compiles. It is off by
default because every run writes the `.tex` to disk, and it needs the local
server since only that can run `tectonic`.

Overleaf itself is not vendored — it is AGPL-3.0 and needs MongoDB and Redis.
Only the shared open-source editor foundation is used here.

### Saving

**The editor is always typeable.** There is no mode to switch on. Change a
bullet you do not like and press Cmd-S; the status beside the buttons always
names where a save will land. Saves take the first route available:

| Route | Needs | Notes |
|---|---|---|
| Local server | `packages_server.py` running | No permission prompt, any browser. The default when working locally. |
| Folder handle | Chrome/Edge, one grant | Writes the file directly. The only route on the published site. Remembered in IndexedDB. |
| Download | nothing | Firefox/Safari with no server. Lands in `~/Downloads`; copy it over yourself. |

On the deployed page the first save prompts for a folder — pick
`resume-kit/output` and it writes straight to disk from the browser. There is
no database anywhere in this: the `.tex` on disk is the only copy, which is
what `tectonic` compiles and what git versions.

Compiling is the one thing that always needs `packages_server.py`, because a
browser cannot run `tectonic`.

**Only compiling needs a local process**, because a browser cannot run
`tectonic`. That is the whole reason `packages_server.py` exists:

```
python3 scripts/packages_server.py
open http://localhost:8765/email_dashboard/packages.html
```

It binds to 127.0.0.1 only and refuses any path that is not a `.tex` inside
`resume-kit/output` — it writes files and runs a compiler, so do not put it on
a network interface. The char-count format comes from the `\documentclass`, not
the filename: the Danish Embassy package is called `..._cv.tex` but is built on
`resume.cls` and must be measured against resume limits.

**Cmd-S** saves. **Cmd-Enter** saves and compiles.

### This page is public

`packages.html` and everything in `packages/` ship to
<https://zeppyclown.github.io/email_dashboard/packages.html>, which means the
full resume PDFs and the list of live applications are publicly downloadable.
That is deliberate (decided 2026-07-30), not an oversight. Re-run the generator
and commit after each compile, or the published copy goes stale.

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
