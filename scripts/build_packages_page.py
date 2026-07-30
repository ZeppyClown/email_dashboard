"""Generate `packages.html` — a visual index of the compiled resume packages.

Scans `resume-kit/output/<Company>/` for `.tex` files that have a compiled
`.pdf` beside them, renders page thumbnails inline as data URIs, and writes a
single page that sits alongside the Hermes board.

The thumbnails are embedded so the page renders even with nothing served; the
full-size viewer is an <iframe> at a relative path, so the page only works when
the server root is `/Volumes/T9/resume` (see PATHS below), not the dashboard
folder on its own.

    cd /Volumes/T9/resume && npx serve .
    open http://localhost:3000/email_dashboard/packages.html

`packages.html` is gitignored on purpose: `email_dashboard` is a public repo
deployed to GitHub Pages, and the list of live applications is not public data.

    python3 scripts/build_packages_page.py
"""
from __future__ import annotations

import base64
import html
import re
from datetime import datetime
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover - dependency is present on this machine
    raise SystemExit("PyMuPDF is required: python3 -m pip install pymupdf")

# --- paths -----------------------------------------------------------------
# scripts/ -> email_dashboard/ -> resume/
DASHBOARD = Path(__file__).resolve().parent.parent
ROOT = DASHBOARD.parent
OUTPUT_DIR = ROOT / "resume-kit" / "output"
PAGE = DASHBOARD / "packages.html"

# Served from ROOT, so a package file is reachable one level up from the board.
HREF_PREFIX = "../resume-kit/output"

THUMB_DPI = 46
# Anything else in a package folder is scaffolding, not a deliverable.
SKIP_STEMS = ("resume.cls",)


def doc_kind(stem: str) -> str:
    """Label a .tex by what it actually is, from the filename alone."""
    low = stem.lower()
    if "cover_letter" in low or low.endswith("_cl"):
        return "Cover letter"
    if low.endswith("_cv") or "_cv_" in low:
        return "CV"
    if "resume" in low:
        return "Resume"
    return "Document"


def read_status(folder: Path) -> list[tuple[str, str]]:
    """Pull the `## Status` bullets out of a session file, if there is one."""
    sessions = sorted(folder.glob("session_*.md"))
    if not sessions:
        return []
    text = sessions[0].read_text(encoding="utf-8", errors="replace")
    block = re.search(r"^## Status\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not block:
        return []
    rows: list[tuple[str, str]] = []
    for line in block.group(1).splitlines():
        m = re.match(r"^-\s+(?:\*\*)?([^:*]+?)(?:\*\*)?:\s*(.+?)\s*$", line.strip())
        if m:
            label, value = m.group(1).strip(), m.group(2).strip()
            value = re.sub(r"\*\*(.+?)\*\*", r"\1", value)
            if label.lower() not in {"next", "next critique"}:
                rows.append((label, value))
    return rows


def read_deadline(folder: Path) -> str:
    """Deadline from a scraped JD's frontmatter, if the JD was copied in."""
    for md in folder.glob("*.md"):
        if md.name.startswith(("session_", "critique_", "FIT_BRIEF")):
            continue
        head = md.read_text(encoding="utf-8", errors="replace")[:1200]
        m = re.search(r'^deadline:\s*"?([\d-]+)"?', head, re.M)
        if m:
            return m.group(1)
    return ""


def thumbs(pdf: Path) -> tuple[int, list[str]]:
    """Return (page_count, [data-uri png per page])."""
    out: list[str] = []
    with fitz.open(pdf) as doc:
        for page in doc:
            png = page.get_pixmap(dpi=THUMB_DPI).tobytes("png")
            out.append("data:image/png;base64," + base64.b64encode(png).decode())
        return doc.page_count, out


def collect() -> list[dict]:
    packages: list[dict] = []
    if not OUTPUT_DIR.is_dir():
        return packages

    for folder in sorted(p for p in OUTPUT_DIR.iterdir() if p.is_dir()):
        docs = []
        for tex in sorted(folder.glob("*.tex")):
            if tex.name in SKIP_STEMS:
                continue
            pdf = tex.with_suffix(".pdf")
            entry = {
                "kind": doc_kind(tex.stem),
                "tex": tex.name,
                "pdf": pdf.name if pdf.exists() else "",
                "href": f"{HREF_PREFIX}/{folder.name}/{pdf.name}" if pdf.exists() else "",
                "pages": 0,
                "thumbs": [],
                "built": "",
                # A .tex edited after its .pdf means the preview below is not
                # what the .tex now says. Worth shouting about: it is exactly
                # how a corrected resume gets sent out in its uncorrected form.
                "stale": False,
            }
            if pdf.exists():
                entry["pages"], entry["thumbs"] = thumbs(pdf)
                entry["built"] = datetime.fromtimestamp(pdf.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                entry["stale"] = tex.stat().st_mtime > pdf.stat().st_mtime
            docs.append(entry)

        if docs:
            packages.append({
                "name": folder.name,
                "docs": docs,
                "status": read_status(folder),
                "deadline": read_deadline(folder),
            })
    return packages


# --- rendering --------------------------------------------------------------

CSS = """
:root{--bg:#f7f6f3;--panel:#fff;--text:#37352f;--muted:#6b6b6b;--border:#e3e2de;
--accent:#2f6fed;--warn:#eb5757;--ok:#219653}
@media (prefers-color-scheme:dark){:root{--bg:#191919;--panel:#232323;--text:#e9e9e7;
--muted:#9b9b9b;--border:#373737}}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,"Segoe UI",Roboto,sans-serif;
background:var(--bg);color:var(--text);font-size:14px}
.topbar{display:flex;align-items:center;gap:16px;padding:12px 24px;
border-bottom:1px solid var(--border);flex-wrap:wrap}
.topbar h1{font-size:18px;margin:0;white-space:nowrap}
.topbar nav{display:flex;gap:8px;flex:1}
.topbar a{color:var(--muted);text-decoration:none;font-size:13px;padding:4px 10px;
border:1px solid var(--border);border-radius:999px;background:var(--panel)}
.topbar a.here{color:var(--text);border-color:var(--text)}
.wrap{display:grid;grid-template-columns:300px minmax(0,1fr) minmax(0,1fr);gap:16px;
padding:16px 20px;align-items:start}
@media (max-width:1300px){.wrap{grid-template-columns:280px minmax(0,1fr)}
.editor{grid-column:2}}
@media (max-width:900px){.wrap{grid-template-columns:1fr}.editor{grid-column:1}}
.pkg{background:var(--panel);border:1px solid var(--border);border-radius:8px;
padding:14px;margin-bottom:14px}
.pkg h2{margin:0 0 2px;font-size:15px}
.meta{color:var(--muted);font-size:12px;margin-bottom:10px}
.doc{display:flex;gap:10px;align-items:flex-start;width:100%;text-align:left;
padding:8px;border:1px solid transparent;border-radius:6px;background:none;
color:inherit;font:inherit;cursor:pointer}
.doc:hover{background:var(--bg)}
.doc[aria-current="true"]{border-color:var(--accent);background:var(--bg)}
.doc img{width:44px;border:1px solid var(--border);border-radius:2px;display:block}
.doc .k{font-weight:600}
.doc .s{color:var(--muted);font-size:12px}
.status{margin:10px 0 0;padding-top:10px;border-top:1px solid var(--border);
list-style:none}
.status li{display:flex;justify-content:space-between;gap:10px;font-size:12px;
color:var(--muted);padding:1px 0}
.status b{font-weight:500;color:var(--text)}
.fail{color:var(--warn)}
.pass{color:var(--ok)}
.badge{display:inline-block;margin-left:6px;padding:0 6px;border-radius:999px;
font-size:11px;background:var(--warn);color:#fff;vertical-align:1px}
.stalebar{background:var(--warn);color:#fff;border-radius:6px;padding:8px 10px;
font-size:12px;margin-bottom:12px}
.viewer{background:var(--panel);border:1px solid var(--border);border-radius:8px;
padding:14px;position:sticky;top:20px}
.viewer h3{margin:0 0 2px;font-size:15px}
.viewer .meta{margin-bottom:12px}
.pages{display:flex;flex-wrap:wrap;gap:14px}
.pages figure{margin:0}
.pages img{max-width:100%;width:340px;border:1px solid var(--border);
box-shadow:0 1px 4px rgba(0,0,0,.08);background:#fff;display:block}
.pages figcaption{color:var(--muted);font-size:12px;padding-top:4px}
.open{display:inline-block;margin-top:12px;color:var(--accent);font-size:13px}
.empty{color:var(--muted);padding:40px 0;text-align:center}

/* --- editor --- */
.editor{background:var(--panel);border:1px solid var(--border);border-radius:8px;
padding:14px;position:sticky;top:16px;display:flex;flex-direction:column;
max-height:calc(100vh - 100px)}
.editor h3{margin:0 0 10px;font-size:15px}
.editor textarea{flex:1;min-height:340px;width:100%;resize:vertical;
font-family:"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;
line-height:1.5;tab-size:2;padding:10px;border:1px solid var(--border);
border-radius:6px;background:var(--bg);color:var(--text)}
.editor textarea:focus{outline:2px solid var(--accent);outline-offset:-1px}
.bar{display:flex;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap}
.btn{padding:5px 12px;border-radius:6px;border:1px solid var(--border);
background:var(--panel);color:var(--text);font-size:13px;cursor:pointer}
.btn:hover:not(:disabled){border-color:var(--accent);color:var(--accent)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.btn:disabled{opacity:.5;cursor:default}
.hint2{color:var(--muted);font-size:12px;margin-left:auto}
.dirty{color:var(--warn)}
.log{margin-top:10px;padding:8px 10px;border-radius:6px;background:var(--bg);
border:1px solid var(--border);font-family:"SF Mono",Menlo,monospace;
font-size:11px;line-height:1.5;white-space:pre-wrap;max-height:170px;
overflow:auto}
.log:empty{display:none}
.log.bad{border-color:var(--warn)}
.log.good{border-color:var(--ok)}
.frame{width:100%;height:78vh;border:1px solid var(--border);border-radius:4px;
background:#fff}
.note{color:var(--muted);font-size:12px;padding:0 24px 24px;max-width:760px}
code{background:var(--bg);border:1px solid var(--border);border-radius:3px;
padding:1px 5px;font-size:12px}
"""

JS = """
const viewer = document.getElementById('viewer');
const ed     = document.getElementById('ed');
const edHead = document.getElementById('edHead');
const saveB  = document.getElementById('save');
const compB  = document.getElementById('compile');
const state  = document.getElementById('state');
const log    = document.getElementById('log');

let current = null;      // the selected doc
let saved   = '';        // last known on-disk text
let live    = false;     // is packages_server.py behind us?

const dirty = () => current && ed.value !== saved;

function setState() {
  if (!live)        { state.textContent = 'read-only'; state.className = 'hint2'; }
  else if (dirty()) { state.textContent = 'unsaved changes'; state.className = 'hint2 dirty'; }
  else              { state.textContent = 'saved'; state.className = 'hint2'; }
  saveB.disabled = !live || !dirty();
  compB.disabled = !live || !current;
}

function say(msg, kind) {
  log.textContent = msg || '';
  log.className = 'log' + (kind ? ' ' + kind : '');
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  const d = await r.json().catch(() => ({ error: 'bad response' }));
  if (!r.ok || d.error) throw new Error(d.error || ('HTTP ' + r.status));
  return d;
}

async function select(btn) {
  if (dirty() && !confirm('Discard unsaved changes to ' + current.tex + '?')) return;
  document.querySelectorAll('.doc').forEach(b => b.setAttribute('aria-current', 'false'));
  btn.setAttribute('aria-current', 'true');
  const d = current = JSON.parse(btn.dataset.doc);

  viewer.innerHTML =
    '<h3>' + d.kind + ' &mdash; ' + d.pkg + '</h3>' +
    '<p class="meta" id="vmeta">' + d.pages + ' page' + (d.pages === 1 ? '' : 's') +
    (d.built ? ' &middot; built ' + d.built : '') + ' &middot; ' + d.tex + '</p>' +
    (d.stale ? '<div class="stalebar" id="stale">The .tex was edited after this PDF ' +
      'was built &mdash; the preview is out of date. Hit Compile.</div>' : '') +
    (d.href && location.protocol !== 'file:'
      ? '<iframe class="frame" id="frame" src="' + d.href + '" title="' + d.tex + '"></iframe>'
      : '<div class="pages">' + d.thumbs.map((t, i) =>
          '<figure><img src="' + t + '" alt="page ' + (i + 1) + '">' +
          '<figcaption>Page ' + (i + 1) + '</figcaption></figure>').join('') + '</div>') +
    (d.href ? '<a class="open" href="' + d.href + '" target="_blank" rel="noopener">' +
      'Open the PDF in a new tab &rarr;</a>' : '');

  edHead.textContent = d.tex;
  say('');
  if (!live) { ed.value = ''; ed.placeholder = readonlyMsg; setState(); return; }
  ed.value = 'loading…';
  try {
    const { text } = await api('/api/tex?path=' + encodeURIComponent(d.pkg + '/' + d.tex));
    ed.value = saved = text;
  } catch (e) {
    ed.value = ''; ed.placeholder = 'Could not read ' + d.tex + ': ' + e.message;
  }
  setState();
}

async function save() {
  if (!dirty()) return true;
  const text = ed.value;
  try {
    await api('/api/tex', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: current.pkg + '/' + current.tex, text }),
    });
    saved = text; setState(); say('Saved ' + current.tex + '.', 'good');
    return true;
  } catch (e) { say('Save failed: ' + e.message, 'bad'); return false; }
}

async function compile() {
  if (!await save()) return;
  compB.disabled = true; say('Compiling…');
  try {
    const r = await api('/api/compile', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: current.pkg + '/' + current.tex }),
    });
    say((r.ok ? 'Compiled.' : 'Compile FAILED.') + '\\n\\n' + r.log +
        '\\n\\nChar count: ' + r.checks, r.ok ? 'good' : 'bad');
    if (r.ok) {
      const f = document.getElementById('frame');
      if (f) f.src = current.href + '?t=' + Date.now();
      const s = document.getElementById('stale'); if (s) s.remove();
      document.querySelectorAll('.doc').forEach(b => {
        const d = JSON.parse(b.dataset.doc);
        if (d.pkg === current.pkg && d.tex === current.tex) {
          const badge = b.querySelector('.badge'); if (badge) badge.remove();
        }
      });
    }
  } catch (e) { say('Compile failed: ' + e.message, 'bad'); }
  setState();
}

const readonlyMsg =
  'Editing needs the local API. Stop any plain http.server and run:\\n\\n' +
  '  cd /Volumes/T9/resume/email_dashboard\\n' +
  '  python3 scripts/packages_server.py\\n\\n' +
  'then reload this page.';

ed.addEventListener('input', setState);
saveB.addEventListener('click', save);
compB.addEventListener('click', compile);
document.addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key === 's') { e.preventDefault(); save(); }
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); compile(); }
});
addEventListener('beforeunload', e => { if (dirty()) e.preventDefault(); });
document.querySelectorAll('.doc').forEach(b =>
  b.addEventListener('click', () => select(b)));

// Probe for the API once, then open the first document either way.
fetch('/api/tex?path=', { method: 'GET' })
  .then(r => { live = r.status === 400; })   // 400 = endpoint exists, path empty
  .catch(() => { live = false; })
  .finally(() => {
    if (!live) ed.placeholder = readonlyMsg;
    const first = document.querySelector('.doc');
    if (first) select(first); else setState();
  });
"""


def render(packages: list[dict]) -> str:
    e = html.escape
    parts: list[str] = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>Resume Packages — Hermes</title>",
        f"<style>{CSS}</style></head><body>",
        "<div class='topbar'><h1>Hermes</h1><nav>",
        "<a href='index.html'>Digest board</a>",
        "<a class='here' href='packages.html'>Resume packages</a>",
        "</nav></div>",
    ]

    if not packages:
        parts.append("<p class='empty'>No compiled packages found in resume-kit/output.</p>")
        parts.append("</body></html>")
        return "".join(parts)

    parts.append("<div class='wrap'><div>")
    for pkg in packages:
        built = [d for d in pkg["docs"] if d["pdf"]]
        parts.append("<div class='pkg'>")
        parts.append(f"<h2>{e(pkg['name'])}</h2>")
        bits = [f"{len(built)} of {len(pkg['docs'])} compiled"]
        if pkg["deadline"]:
            bits.append(f"deadline {e(pkg['deadline'])}")
        parts.append(f"<p class='meta'>{' &middot; '.join(bits)}</p>")

        for d in pkg["docs"]:
            payload = html.escape(
                __import__("json").dumps({**d, "pkg": pkg["name"]}), quote=True
            )
            thumb = d["thumbs"][0] if d["thumbs"] else ""
            sub = f"{d['pages']} pages" if d["pdf"] else "not compiled"
            img = f"<img src='{thumb}' alt=''>" if thumb else ""
            disabled = "" if d["pdf"] else " disabled"
            badge = "<span class='badge'>stale</span>" if d["stale"] else ""
            parts.append(
                f"<button class='doc' data-doc=\"{payload}\"{disabled}>{img}"
                f"<span><span class='k'>{e(d['kind'])}{badge}</span><br>"
                f"<span class='s'>{e(sub)}</span></span></button>"
            )

        if pkg["status"]:
            parts.append("<ul class='status'>")
            for label, value in pkg["status"]:
                cls = ""
                if "FAIL" in value.upper() or "NOT COMPILED" in value.upper():
                    cls = " class='fail'"
                elif "DONE" in value.upper() or "PASS" in value.upper():
                    cls = " class='pass'"
                parts.append(f"<li><b>{e(label)}</b><span{cls}>{e(value)}</span></li>")
            parts.append("</ul>")
        parts.append("</div>")

    parts.append("</div>")
    parts.append(
        "<div class='editor'>"
        "<h3 id='edHead'>Editor</h3>"
        "<textarea id='ed' spellcheck='false' wrap='off'></textarea>"
        "<div class='bar'>"
        "<button class='btn' id='save' disabled>Save</button>"
        "<button class='btn primary' id='compile' disabled>Save &amp; compile</button>"
        "<span class='hint2' id='state'></span>"
        "</div><div class='log' id='log'></div></div>"
    )
    parts.append("<div class='viewer' id='viewer'></div></div>")
    parts.append(
        "<p class='note'>Editing and compiling need the local API, so run "
        "<code>python3 scripts/packages_server.py</code> rather than a plain "
        "static server, then open "
        "<code>localhost:8765/email_dashboard/packages.html</code>. "
        "<b>Cmd-S</b> saves, <b>Cmd-Enter</b> saves and compiles; the preview "
        "reloads and the char-count gate runs on every compile. Without the "
        "API the page still works read-only. Regenerate the package list with "
        "<code>python3 scripts/build_packages_page.py</code>.</p>"
    )
    parts.append(f"<script>{JS}</script></body></html>")
    return "".join(parts)


def main() -> None:
    packages = collect()
    PAGE.write_text(render(packages), encoding="utf-8")
    docs = sum(len(p["docs"]) for p in packages)
    built = sum(1 for p in packages for d in p["docs"] if d["pdf"])
    size = PAGE.stat().st_size / 1024
    print(f"{PAGE.name}: {len(packages)} packages, {built}/{docs} compiled, {size:.0f} KB")
    for p in packages:
        for d in p["docs"]:
            if not d["pdf"]:
                print(f"  not compiled: {p['name']}/{d['tex']}")
            elif d["stale"]:
                print(f"  STALE (.tex newer than .pdf): {p['name']}/{d['tex']}")


if __name__ == "__main__":
    main()
