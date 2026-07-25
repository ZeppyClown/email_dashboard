import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import { SUPABASE_URL, SUPABASE_ANON_KEY } from "./config.js";

// persistSession + autoRefreshToken keep you signed in across visits/reloads
// (stored in this browser's localStorage); detectSessionInUrl handles the
// redirect back from Google.
const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
});

const STATUSES = ["new", "interested", "done", "not_interested"];
const CATEGORIES = ["deadline", "internship", "scholarship", "course", "other"];

let items = [];
let session = null;
let activeCategory = "all";

const boardEl = document.getElementById("board");
const filtersEl = document.getElementById("filters");
const authEl = document.getElementById("auth");
const hintEl = document.getElementById("hint");

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
        options: { redirectTo: window.location.origin + window.location.pathname },
      });
    };
    authEl.appendChild(btn);
  }
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
    el.appendChild(a);
  }

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
  await loadItems();

  supabase
    .channel("digest_items_changes")
    .on("postgres_changes", { event: "*", schema: "public", table: "digest_items" }, () => {
      loadItems();
    })
    .subscribe();
}

init();
