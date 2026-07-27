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
const CATEGORIES = ["deadline", "internship", "scholarship", "course", "other"];

let items = [];
let session = null;
let activeCategory = "all";

const boardEl = document.getElementById("board");
const filtersEl = document.getElementById("filters");
const authEl = document.getElementById("auth");
const hintEl = document.getElementById("hint");
const drawerEl = document.getElementById("drawer");
const drawerContentEl = document.getElementById("drawerContent");
const backdropEl = document.getElementById("backdrop");

function renderFilters() {
  filtersEl.innerHTML = "";
  const all = ["all", ...CATEGORIES];
  for (const cat of all) {
    const chip = document.createElement("button");
    chip.className = "chip" + (cat === activeCategory ? " active" : "");
    chip.textContent = cat === "all" ? "All" : cat;
    chip.onclick = () => {
      activeCategory = cat;
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

function openDrawer(item) {
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
  dateRow.textContent = `Digest date: ${item.digest_date}` + (item.deadline_date ? ` · Due ${item.deadline_date}` : "");

  // `meta` is an object of plain key/value facts (Remuneration, Vacancies, …).
  // The order has to be imposed here, not by the writer: the column is `jsonb`,
  // and Postgres normalises jsonb key order (shortest key first, then
  // bytewise), so whatever order Hermes inserted them in is already lost by the
  // time they come back. Keys below render in this order — the JOB-BLAST
  // spreadsheet's own column order, so a card reads like its source row.
  // Anything not listed renders after, alphabetically, so a new key added by a
  // future writer still shows up instead of silently vanishing.
  // Location and Start Date come from the listing page rather than the
  // spreadsheet, and sit next to their coarser spreadsheet equivalents
  // (Country, Commences) rather than replacing them: Country says "Australia",
  // Location says "Fully remote".
  const FIELD_ORDER = [
    "Position", "Employer", "Employer site", "Industry",
    "Country", "Location", "Address", "Work model",
    "Commences", "Start Date", "Remuneration", "Vacancies",
    "Hours", "Contract type", "Residency",
    "Published", "Closes", "Added",
    "Occupation", "Contact", "CareerAxis ID",
  ];
  const entries = Object.entries(item.meta || {}).sort(([a], [b]) => {
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
    dd.textContent = String(v);
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

  if (item.link) {
    const a = document.createElement("a");
    a.href = item.link;
    a.textContent = "Open link ↗";
    a.target = "_blank";
    a.className = "drawer-link";
    drawerContentEl.appendChild(a);
  }

  drawerEl.classList.add("open");
  backdropEl.classList.add("open");
}

function closeDrawer() {
  drawerEl.classList.remove("open");
  backdropEl.classList.remove("open");
}

function cardEl(item) {
  const el = document.createElement("div");
  el.className = "card";
  el.draggable = !!session;
  el.dataset.id = item.id;

  const tag = document.createElement("span");
  tag.className = `tag ${item.category}`;
  tag.textContent = item.category;

  const title = document.createElement("div");
  title.className = "title";
  title.textContent = item.title;

  const summary = document.createElement("div");
  summary.className = "summary";
  summary.textContent = item.summary || "";

  const meta = document.createElement("div");
  meta.className = "meta";
  const left = document.createElement("span");
  left.textContent = item.sender || "";
  const right = document.createElement("span");
  right.textContent = item.deadline_date ? `Due ${item.deadline_date}` : item.digest_date;
  meta.appendChild(left);
  meta.appendChild(right);

  el.appendChild(tag);
  el.appendChild(title);
  if (item.summary) el.appendChild(summary);
  el.appendChild(meta);

  if (item.link) {
    const a = document.createElement("a");
    a.href = item.link;
    a.textContent = "Open link";
    a.target = "_blank";
    a.style.fontSize = "12px";
    a.style.display = "inline-block";
    a.style.marginTop = "6px";
    a.addEventListener("click", (e) => e.stopPropagation());
    el.appendChild(a);
  }

  el.addEventListener("click", () => openDrawer(item));

  el.addEventListener("dragstart", (e) => {
    e.dataTransfer.setData("text/plain", item.id);
    el.classList.add("dragging");
  });
  el.addEventListener("dragend", () => el.classList.remove("dragging"));

  return el;
}

function renderBoard() {
  for (const status of STATUSES) {
    const col = boardEl.querySelector(`.cards[data-status="${status}"]`);
    col.innerHTML = "";
    const filtered = items
      .filter((i) => i.status === status)
      .filter((i) => activeCategory === "all" || i.category === activeCategory)
      .sort((a, b) => (a.deadline_date || "9999").localeCompare(b.deadline_date || "9999"));
    for (const item of filtered) col.appendChild(cardEl(item));
  }
  hintEl.textContent = session
    ? "Drag a card between columns to update its status."
    : "Sign in (top right) to drag cards — the board is read-only until then.";
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
  document.getElementById("drawerClose").addEventListener("click", closeDrawer);
  backdropEl.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDrawer();
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
