// Sign-in gate shared by index.html and packages.html.
//
// Hides the page until a Google session exists whose email is on ALLOWED, and
// shows a sign-in screen otherwise. Import it before anything else on a page,
// and pair it with the `#authgate` markup plus the `:root:not(.authed)` rule
// that hides content — the CSS has to be inline in the page, or there is a
// visible flash of the UI before this module loads.
//
// SCOPE, PLAINLY: this gates the *interface*, not the *data*. These pages are
// static files on GitHub Pages, so anyone can still fetch a file directly —
// `packages/<Pkg>/<file>.pdf`, `packages.html`, `app.js` — without ever
// executing this code. Board rows are readable with the anon key too, because
// `schema.sql` grants public select. What is genuinely enforced is *writing*:
// the RLS policy checks the JWT email server-side, where it cannot be bypassed.
//
// So: good for keeping the UI to yourself and stopping casual browsing. Not a
// way to make the resume PDFs private. For that, stop publishing them.
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import { SUPABASE_URL, SUPABASE_ANON_KEY } from "./config.js";

const ALLOWED = ["victorchua865@gmail.com"];

// Must match an entry in Supabase → Authentication → URL Configuration →
// Redirect URLs exactly, trailing slash included, or Supabase silently falls
// back to the Site URL after the Google round trip.
const REDIRECTS = {
  "zeppyclown.github.io": "https://zeppyclown.github.io/email_dashboard/",
  localhost: "http://localhost:8765/email_dashboard/",
  "127.0.0.1": "http://127.0.0.1:8765/email_dashboard/",
};
const redirectTo = REDIRECTS[location.hostname] || REDIRECTS["zeppyclown.github.io"];

const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
});

const gate = document.getElementById("authgate");
const allowed = (s) => !!s && ALLOWED.includes((s.user?.email || "").toLowerCase());

function render(session) {
  if (allowed(session)) {
    document.documentElement.classList.add("authed");
    if (gate) gate.hidden = true;
    return;
  }
  document.documentElement.classList.remove("authed");
  if (!gate) return;
  gate.hidden = false;

  const wrong = !!session && !allowed(session);
  gate.innerHTML = `
    <div class="gate-card">
      <h1>Hermes</h1>
      <p class="gate-sub">${wrong
        ? `Signed in as <b>${escapeHtml(session.user.email)}</b>, which is not
           authorised for this dashboard.`
        : "Sign in to continue."}</p>
      <button class="gate-btn" id="gateBtn">
        ${wrong ? "Sign in as someone else" : "Sign in with Google"}
      </button>
      <p class="gate-foot">Access is limited to one account.</p>
    </div>`;

  document.getElementById("gateBtn").onclick = async () => {
    if (wrong) await supabase.auth.signOut();
    supabase.auth.signInWithOAuth({ provider: "google", options: { redirectTo } });
  };
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const { data } = await supabase.auth.getSession();
render(data.session);
supabase.auth.onAuthStateChange((_e, s) => render(s));

export { supabase, allowed };
