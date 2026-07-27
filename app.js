import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import { SUPABASE_URL, SUPABASE_ANON_KEY } from "./config.js";

// persistSession + autoRefreshToken keep you signed in across visits/reloads
// (stored in this browser's localStorage); detectSessionInUrl handles the
// redirect back from Google.
const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
});

// Hardcoded (not derived from window.location) so it always matches exactly
// what's in Supabase's Redirect URLs allow-list — a URL missing/gaining a
// trailing slash on first load is enough for Supabase to reject it and
// silently fall back to the default Site URL instead.
const REDIRECT_URL = "https://zeppyclown.github.io/email_dashboard/";

const STATUSES = ["new", "interested", "done", "not_interested"];
const CATEGORIES = ["internship", "hackathon", "course", "deadline", "scholarship", "other"];

let items = [];
let session = null;
let activeCategory = "all";
let query = "";
let hideExpired = true;
let teamSize = "";
// Which urgency groups are folded away. Shared across the four columns on
// purpose — "Later" means the same thing in each, and per-column state would
// mean twelve toggles to manage a board you only triage one way.
let collapsedGroups = loadCollapsed();

const boardEl = document.getElementById("board");
const filtersEl = document.getElementById("filters");
const authEl = document.getElementById("auth");
const hintEl = document.getElementById("hint");
const drawerEl = document.getElementById("drawer");
const drawerContentEl = document.getElementById("drawerContent");
const backdropEl = document.getElementById("backdrop");
const searchEl = document.getElementById("search");
const hideExpiredEl = document.getElementById("hideExpired");
const teamSizeEl = document.getElementById("teamSize");
const teamSizeWrapEl = document.getElementById("teamSizeWrap");
const countEl = document.getElementById("count");

const COLLAPSE_KEY = "hermes.collapsedGroups";

function loadCollapsed() {
  try {
    const raw = localStorage.getItem(COLLAPSE_KEY);
    // First visit opens on the two near-term groups only: 119 cards in one
    // flat list tells you nothing about what is actually pressing.
    if (!raw) return new Set(["Later", "No deadline"]);
    return new Set(JSON.parse(raw));
  } catch {
    return new Set(["Later", "No deadline"]);
  }
}

function saveCollapsed() {
  try {
    localStorage.setItem(COLLAPSE_KEY, JSON.stringify([...collapsedGroups]));
  } catch {
    /* private mode — the board still works, the folds just don't persist */
  }
}

// ---- date helpers -------------------------------------------------------

// Cards store `deadline_date` as a plain ISO day. Comparing those as strings
// avoids timezone drift entirely: `new Date("2026-08-01")` is UTC midnight,
// which in SGT is already the 1st but in UTC-5 is still the 31st.
function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function addDaysISO(days) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const GROUP_ORDER = ["Overdue", "This week", "This month", "Later", "No deadline"];

function groupOf(item) {
  if (!item.deadline_date) return "No deadline";
  const today = todayISO();
  if (item.deadline_date < today) return "Overdue";
  if (item.deadline_date <= addDaysISO(7)) return "This week";
  if (item.deadline_date <= addDaysISO(30)) return "This month";
  return "Later";
}

function dueLabel(iso) {
  if (!iso) return "";
  const [, m, d] = iso.split("-");
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${d.replace(/^0/, "")} ${months[Number(m) - 1]}`;
}

// ---- filtering ----------------------------------------------------------

function matchesTeamSize(item) {
  if (!teamSize) return true;
  const n = Number(teamSize);
  const min = item.meta?.["Team min"];
  const max = item.meta?.["Team max"];
  // An event whose organiser never published a size stays visible rather than
  // being filtered out — absence of a number is not evidence you don't fit.
  if (min == null || max == null) return true;
  return n >= min && n <= max;
}

function matchesQuery(item) {
  if (!query) return true;
  const haystack = [
    item.title,
    item.summary,
    item.details,
    item.sender,
    item.note,
    item.meta?.Employer,
    item.meta?.Position,
    item.meta?.Event,
  ].filter(Boolean).join(" ").toLowerCase();
  return haystack.includes(query);
}

function visible(item) {
  if (activeCategory !== "all" && item.category !== activeCategory) return false;
  // Expired cards are hidden, never deleted — a closed listing is still
  // evidence of what you were interested in.
  if (hideExpired && item.deadline_date && item.deadline_date < todayISO()) return false;
  if (!matchesQuery(item)) return false;
  if (activeCategory === "hackathon" && !matchesTeamSize(item)) return false;
  return true;
}

// ---- chrome -------------------------------------------------------------

function renderFilters() {
  filtersEl.innerHTML = "";
  for (const cat of ["all", ...CATEGORIES]) {
    const chip = document.createElement("button");
    chip.className = "chip" + (cat === activeCategory ? " active" : "");
    chip.textContent = cat === "all" ? "All" : cat;

    const n = document.createElement("span");
    n.className = "chip-n";
    n.textContent = cat === "all" ? items.length : items.filter((i) => i.category === cat).length;
    chip.appendChild(n);

    chip.onclick = () => {
      activeCategory = cat;
      teamSizeWrapEl.hidden = cat !== "hackathon";
      if (cat !== "hackathon") { teamSize = ""; teamSizeEl.value = ""; }
      renderFilters();
      renderBoard();
    };
    filtersEl.appendChild(chip);
  }
}

function renderAuth() {
  authEl.innerHTML = "";
  if (session) {
    const span = document.createElement("span");
    span.textContent = `Signed in as ${session.user.email}`;
    span.style.fontSize = "12px";
    span.style.color = "var(--muted)";
    const signOutBtn = document.createElement("button");
    signOutBtn.textContent = "Sign out";
    signOutBtn.onclick = () => supabase.auth.signOut();
    authEl.appendChild(span);
    authEl.appendChild(signOutBtn);
  } else {
    const btn = document.createElement("button");
    btn.textContent = "Sign in with Google";
    btn.onclick = () => {
      supabase.auth.signInWithOAuth({
        provider: "google",
        options: { redirectTo: REDIRECT_URL },
      });
    };
    authEl.appendChild(btn);
  }
}

// ---- drawer -------------------------------------------------------------

// `meta` is an object of plain key/value facts (Remuneration, Vacancies, …).
// The order has to be imposed here, not by the writer: the column is `jsonb`,
// and Postgres normalises jsonb key order (shortest key first, then bytewise),
// so whatever order Hermes inserted them in is already lost by the time they
// come back. Keys below render in this order — job keys follow the JOB-BLAST
// spreadsheet's own column order so a card reads like its source row, then the
// hackathon keys. Anything not listed renders after, alphabetically, so a new
// key added by a future writer still shows up instead of silently vanishing.
const FIELD_ORDER = [
  "Position", "Employer", "Employer site", "Industry",
  "Country", "Location", "Address", "Work model",
  "Commences", "Start Date", "Remuneration", "Vacancies",
  "Hours", "Contract type", "Residency",
  "Published", "Closes", "Added",
  "Occupation", "Contact", "CareerAxis ID",
  // hackathons
  "Event", "Organiser", "Format", "Team size", "Eligibility",
  "Event dates", "Venue", "Registration closes", "Brief released",
  "Proposal due", "Requirement", "Problem statements", "Judging",
  "Prize pool", "Prizes", "1st prize", "2nd prize", "3rd prize",
  "4th/5th prize", "Special award", "Perks", "Support", "Workshops",
  "Competition", "Track record", "Register", "Info site",
];

// Numeric helpers for the team-size filter — useful to the machine, noise on
// screen, since "Team size" already says "Teams of 3–5" in the organiser's
// own words right above them.
const HIDDEN_META = new Set(["Team min", "Team max"]);

function openDrawer(item, { focusNote = false } = {}) {
  drawerContentEl.innerHTML = "";

  const tag = document.createElement("span");
  tag.className = `tag ${item.category}`;
  tag.textContent = item.category;

  const title = document.createElement("h3");
  title.textContent = item.title;

  const senderRow = document.createElement("div");
  senderRow.className = "meta-row";
  senderRow.textContent = item.sender ? `From ${item.sender}` : "";

  const dateRow = document.createElement("div");
  dateRow.className = "meta-row";
  dateRow.textContent = `Digest date: ${item.digest_date}`
    + (item.deadline_date ? ` · Due ${item.deadline_date}` : "")
    + (item.source ? ` · via ${item.source}` : "");

  const entries = Object.entries(item.meta || {})
    .filter(([k]) => !HIDDEN_META.has(k))
    .sort(([a], [b]) => {
      const ia = FIELD_ORDER.indexOf(a);
      const ib = FIELD_ORDER.indexOf(b);
      if (ia !== -1 && ib !== -1) return ia - ib;
      if (ia !== -1) return -1;
      if (ib !== -1) return 1;
      return a.localeCompare(b);
    });

  const facts = document.createElement("dl");
  facts.className = "facts";
  for (const [k, v] of entries) {
    if (v === null || v === undefined || v === "") continue;
    const dt = document.createElement("dt");
    dt.textContent = k;
    const dd = document.createElement("dd");
    // Hackathon facts carry Register/Info site URLs; make them clickable
    // instead of printing a bare string nobody can use.
    if (typeof v === "string" && /^https?:\/\//.test(v)) {
      const a = document.createElement("a");
      a.href = v;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = v.replace(/^https?:\/\//, "").replace(/\/$/, "");
      dd.appendChild(a);
    } else {
      dd.textContent = String(v);
    }
    facts.appendChild(dt);
    facts.appendChild(dd);
  }

  const body = document.createElement("div");
  body.className = "details-text";
  body.textContent = item.details || item.summary || "No further detail recorded for this item.";

  drawerContentEl.appendChild(tag);
  drawerContentEl.appendChild(title);
  if (item.sender) drawerContentEl.appendChild(senderRow);
  drawerContentEl.appendChild(dateRow);
  if (facts.childElementCount) drawerContentEl.appendChild(facts);
  drawerContentEl.appendChild(body);
  const note = noteBox(item, focusNote);
  drawerContentEl.appendChild(note);

  if (item.link) {
    const a = document.createElement("a");
    a.href = item.link;
    a.textContent = "Open link ↗";
    a.target = "_blank";
    a.rel = "noopener";
    a.className = "drawer-link";
    drawerContentEl.appendChild(a);
  }

  drawerEl.classList.add("open");
  backdropEl.classList.add("open");

  // Dropping a card into Not interested opens straight into the reason box —
  // the moment you know why is the moment you just made the decision, and a
  // note written a day later is a note never written.
  if (focusNote) {
    const ta = note.querySelector("textarea");
    if (ta && !ta.disabled) ta.focus();
  }
}

function noteBox(item, highlight = false) {
  const wrap = document.createElement("div");
  wrap.className = "note-box" + (highlight ? " prompt" : "");

  const label = document.createElement("label");
  label.textContent = highlight
    ? "Why aren't you interested? Hermes reads this to stop sending similar items."
    : "Your note — why this is (or isn't) for you";
  label.htmlFor = "noteInput";

  const ta = document.createElement("textarea");
  ta.id = "noteInput";
  ta.value = item.note || "";
  ta.placeholder = session
    ? "e.g. Y3+ only · pay too low · wrong domain, keep for next year"
    : "Sign in to write notes.";
  ta.disabled = !session;
  // Blur-to-save alone would lose a note if the drawer is closed with Escape
  // straight after typing, which is exactly what happens after a drag.
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) ta.blur();
    if (e.key === "Escape") e.stopPropagation();
  });

  const status = document.createElement("div");
  status.className = "note-status";

  // Saved on blur rather than on every keystroke: this is prose, and a PATCH
  // per character would be both wasteful and racy.
  let last = item.note || "";
  ta.addEventListener("blur", async () => {
    const value = ta.value.trim();
    if (value === last) return;
    status.textContent = "Saving…";
    const err = await saveNote(item.id, value);
    if (!err) {
      last = value;
      status.textContent = value ? "Saved." : "Note cleared.";
    } else if (/note/.test(err.message || "") && err.code === "42703") {
      // The column hasn't been created yet — say so plainly rather than
      // blaming the session, which is the other reason a write fails.
      status.textContent = "The `note` column doesn't exist yet — run the schema.sql migration.";
    } else {
      status.textContent = "Couldn't save — are you still signed in?";
    }
  });

  wrap.appendChild(label);
  wrap.appendChild(ta);
  wrap.appendChild(status);
  return wrap;
}

// Returns null on success, or the Supabase error so the caller can tell a
// missing column apart from an expired session.
async function saveNote(id, note) {
  const { error } = await supabase
    .from("digest_items")
    .update({ note: note || null })
    .eq("id", id);
  if (error) return error;
  items = items.map((i) => (i.id === id ? { ...i, note: note || null } : i));
  renderBoard();
  return null;
}

function closeDrawer() {
  drawerEl.classList.remove("open");
  backdropEl.classList.remove("open");
}

// ---- cards --------------------------------------------------------------

function cardEl(item) {
  const el = document.createElement("div");
  el.className = "card";
  el.draggable = !!session;
  el.dataset.id = item.id;

  const row = document.createElement("div");
  row.className = "row";

  const dot = document.createElement("span");
  dot.className = `dot ${item.category}`;
  dot.title = item.category;

  const title = document.createElement("span");
  title.className = "row-title";
  title.textContent = item.title;
  title.title = item.title;   // full text on hover, since the row ellipsises

  const due = document.createElement("span");
  due.className = "row-due" + (groupOf(item) === "This week" || groupOf(item) === "Overdue" ? " soon" : "");
  due.textContent = item.deadline_date ? dueLabel(item.deadline_date) : "";

  row.appendChild(dot);
  row.appendChild(title);
  if (item.note) {
    const flag = document.createElement("span");
    flag.className = "has-note";
    flag.textContent = "✎";
    flag.title = item.note;
    row.appendChild(flag);
  }
  row.appendChild(due);

  // Expand shows the summary in place; the drawer stays one click further in
  // for the full description and fact table.
  const expand = document.createElement("button");
  expand.className = "expand";
  expand.innerHTML = '<span class="caret">▸</span>';
  expand.title = "Show summary";
  expand.addEventListener("click", (e) => {
    e.stopPropagation();
    el.classList.toggle("open");
    bodyEl.hidden = !el.classList.contains("open");
  });
  row.appendChild(expand);

  const bodyEl = document.createElement("div");
  bodyEl.className = "body";
  bodyEl.hidden = true;
  if (item.summary) {
    const s = document.createElement("span");
    s.textContent = item.summary;
    bodyEl.appendChild(s);
  }
  const sub = document.createElement("span");
  sub.textContent = [item.meta?.Employer || item.sender, item.meta?.["Team size"]]
    .filter(Boolean).join(" · ");
  if (sub.textContent) bodyEl.appendChild(sub);
  if (item.note) {
    const n = document.createElement("span");
    n.className = "note-flag";
    n.textContent = `“${item.note}”`;
    bodyEl.appendChild(n);
  }
  if (item.link) {
    const a = document.createElement("a");
    a.href = item.link;
    a.textContent = "Open link ↗";
    a.target = "_blank";
    a.rel = "noopener";
    a.addEventListener("click", (e) => e.stopPropagation());
    bodyEl.appendChild(a);
  }

  el.appendChild(row);
  el.appendChild(bodyEl);

  el.addEventListener("click", () => openDrawer(item));

  el.addEventListener("dragstart", (e) => {
    e.dataTransfer.setData("text/plain", item.id);
    el.classList.add("dragging");
  });
  el.addEventListener("dragend", () => el.classList.remove("dragging"));

  return el;
}

function groupHead(name, n, collapsed) {
  const btn = document.createElement("button");
  btn.className = "group-head" + (collapsed ? " collapsed" : "") + (name === "Overdue" ? " overdue" : "");
  btn.innerHTML = `<span class="caret">▾</span><span>${name}</span><span class="group-n">${n}</span>`;
  btn.addEventListener("click", () => {
    if (collapsedGroups.has(name)) collapsedGroups.delete(name);
    else collapsedGroups.add(name);
    saveCollapsed();
    renderBoard();
  });
  return btn;
}

function renderBoard() {
  let shown = 0;
  for (const status of STATUSES) {
    const col = boardEl.querySelector(`.cards[data-status="${status}"]`);
    col.innerHTML = "";
    const filtered = items
      .filter((i) => i.status === status)
      .filter(visible)
      .sort((a, b) => (a.deadline_date || "9999").localeCompare(b.deadline_date || "9999"));
    shown += filtered.length;

    boardEl.querySelector(`.col-count[data-count="${status}"]`).textContent = filtered.length || "";

    for (const name of GROUP_ORDER) {
      const inGroup = filtered.filter((i) => groupOf(i) === name);
      if (!inGroup.length) continue;
      const collapsed = collapsedGroups.has(name);
      col.appendChild(groupHead(name, inGroup.length, collapsed));
      if (collapsed) continue;
      for (const item of inGroup) col.appendChild(cardEl(item));
    }
  }

  const total = items.length;
  countEl.textContent = shown === total ? `${total} cards` : `${shown} of ${total} cards`;

  hintEl.textContent = session
    ? "Drag a card between columns to update its status · click a card for full detail and notes."
    : "Sign in (top right) to drag cards and write notes — the board is read-only until then.";
}

async function updateStatus(id, status) {
  const prev = items.find((i) => i.id === id)?.status;
  items = items.map((i) => (i.id === id ? { ...i, status } : i));
  renderBoard();
  const { error } = await supabase.from("digest_items").update({ status }).eq("id", id);
  if (error) {
    items = items.map((i) => (i.id === id ? { ...i, status: prev } : i));
    renderBoard();
    alert("Couldn't save that change — are you signed in? " + error.message);
    return;
  }
  // A rejection without a reason teaches Hermes nothing, so ask for one right
  // when the decision is made. Only on the way *into* not_interested, and only
  // when there is no note yet — re-filing a card you already explained
  // shouldn't nag you a second time.
  const item = items.find((i) => i.id === id);
  if (status === "not_interested" && prev !== "not_interested" && !item?.note) {
    openDrawer(item, { focusNote: true });
  }
}

function wireDropZones() {
  boardEl.querySelectorAll(".cards").forEach((zone) => {
    zone.addEventListener("dragover", (e) => {
      if (!session) return;
      e.preventDefault();
      zone.classList.add("drag-over");
    });
    zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
    zone.addEventListener("drop", (e) => {
      e.preventDefault();
      zone.classList.remove("drag-over");
      if (!session) return;
      const id = e.dataTransfer.getData("text/plain");
      updateStatus(id, zone.dataset.status);
    });
  });
}

function wireControls() {
  let timer;
  searchEl.addEventListener("input", () => {
    // Debounced so typing doesn't rebuild four columns per keystroke.
    clearTimeout(timer);
    timer = setTimeout(() => {
      query = searchEl.value.trim().toLowerCase();
      renderBoard();
    }, 120);
  });
  hideExpiredEl.addEventListener("change", () => {
    hideExpired = hideExpiredEl.checked;
    renderBoard();
  });
  teamSizeEl.addEventListener("change", () => {
    teamSize = teamSizeEl.value;
    renderBoard();
  });
}

async function loadItems() {
  const { data, error } = await supabase
    .from("digest_items")
    .select("*")
    .order("digest_date", { ascending: false });
  if (error) {
    hintEl.textContent = "Failed to load items: " + error.message;
    return;
  }
  items = data;
  renderFilters();
  renderBoard();
}

async function init() {
  const { data } = await supabase.auth.getSession();
  session = data.session;
  renderAuth();

  supabase.auth.onAuthStateChange((_event, newSession) => {
    session = newSession;
    renderAuth();
    renderBoard();
  });

  renderFilters();
  wireDropZones();
  wireControls();
  document.getElementById("drawerClose").addEventListener("click", closeDrawer);
  backdropEl.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDrawer();
    // "/" jumps to search the way it does on GitHub — the fastest way to find
    // one card among a hundred.
    if (e.key === "/" && document.activeElement !== searchEl) {
      e.preventDefault();
      searchEl.focus();
    }
  });
  await loadItems();

  supabase
    .channel("digest_items_changes")
    .on("postgres_changes", { event: "*", schema: "public", table: "digest_items" }, () => {
      loadItems();
    })
    .subscribe();
}

init();
