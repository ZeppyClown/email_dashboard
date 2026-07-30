"""Generate `packages.html` — sidebar of compiled packages, LaTeX + PDF beside it.

Scans `resume-kit/output/<Package>/` for `.tex` files with a compiled `.pdf`,
copies each PDF and a small first-page thumbnail into `packages/` next to this
dashboard, embeds the `.tex` source in the page, and writes the viewer.

The page works in three layers, each adding to the one below:

  1. Nothing running        view the embedded .tex and the PDF, read-only.
                            Works from the published Pages site too.
  2. Folder access granted  the page reads the .tex live off disk and can save
                            it back, via the File System Access API. Chrome and
                            Edge only; no server involved.
  3. packages_server.py up  the Compile button works, because only a local
                            process can run `tectonic`.

    python3 scripts/build_packages_page.py

Assets are real files rather than inline data URIs so an unchanged PDF produces
byte-identical output and git stores no new blob for it.
"""
from __future__ import annotations

import html
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover - dependency is present on this machine
    raise SystemExit("PyMuPDF is required: python3 -m pip install pymupdf")

DASHBOARD = Path(__file__).resolve().parent.parent
ROOT = DASHBOARD.parent
OUTPUT_DIR = ROOT / "resume-kit" / "output"
ASSETS = DASHBOARD / "packages"
PAGE = DASHBOARD / "packages.html"

THUMB_DPI = 30          # sidebar icon only; the preview is the real PDF
SKIP = {"resume.cls", "cv.cls"}


def doc_kind(stem: str) -> str:
    low = stem.lower()
    if "cover_letter" in low or low.endswith("_cl"):
        return "Cover letter"
    if low.endswith("_cv") or "_cv_" in low:
        return "CV"
    if "resume" in low:
        return "Resume"
    return "Document"


def read_status(folder: Path) -> list[tuple[str, str]]:
    sessions = sorted(folder.glob("session_*.md"))
    if not sessions:
        return []
    text = sessions[0].read_text(encoding="utf-8", errors="replace")
    block = re.search(r"^## Status\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not block:
        return []
    rows = []
    for line in block.group(1).splitlines():
        m = re.match(r"^-\s+(?:\*\*)?([^:*]+?)(?:\*\*)?:\s*(.+?)\s*$", line.strip())
        if m and m.group(1).strip().lower() not in {"next", "next critique"}:
            rows.append((m.group(1).strip(), re.sub(r"\*\*(.+?)\*\*", r"\1", m.group(2).strip())))
    return rows


def read_deadline(folder: Path) -> str:
    for md in folder.glob("*.md"):
        if md.name.startswith(("session_", "critique_", "FIT_BRIEF")):
            continue
        m = re.search(r'^deadline:\s*"?([\d-]+)"?',
                      md.read_text(encoding="utf-8", errors="replace")[:1200], re.M)
        if m:
            return m.group(1)
    return ""


def collect() -> list[dict]:
    if ASSETS.exists():
        shutil.rmtree(ASSETS)          # drop assets for packages that went away
    packages = []
    if not OUTPUT_DIR.is_dir():
        return packages

    for folder in sorted(p for p in OUTPUT_DIR.iterdir() if p.is_dir()):
        docs = []
        for tex in sorted(folder.glob("*.tex")):
            if tex.name in SKIP:
                continue
            pdf = tex.with_suffix(".pdf")
            doc = {
                "pkg": folder.name,
                "kind": doc_kind(tex.stem),
                "tex": tex.name,
                "source": tex.read_text(encoding="utf-8", errors="replace"),
                "pdf": "", "thumb": "", "pages": 0, "built": "", "stale": False,
            }
            if pdf.exists():
                dest = ASSETS / folder.name
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(pdf, dest / pdf.name)
                with fitz.open(pdf) as d:
                    doc["pages"] = d.page_count
                    (dest / f"{tex.stem}-p1.png").write_bytes(
                        d[0].get_pixmap(dpi=THUMB_DPI).tobytes("png"))
                doc["pdf"] = f"packages/{folder.name}/{pdf.name}"
                doc["thumb"] = f"packages/{folder.name}/{tex.stem}-p1.png"
                doc["built"] = datetime.fromtimestamp(pdf.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                # A .tex touched after its PDF means the preview is not the
                # document any more. That is how a corrected resume gets sent
                # in its uncorrected form.
                doc["stale"] = tex.stat().st_mtime > pdf.stat().st_mtime
            docs.append(doc)

        if docs:
            packages.append({"name": folder.name, "docs": docs,
                             "status": read_status(folder),
                             "deadline": read_deadline(folder)})
    return packages


CSS = """
:root{--bg:#f7f6f3;--panel:#fff;--text:#37352f;--muted:#6b6b6b;--border:#e3e2de;
--accent:#2f6fed;--warn:#eb5757;--ok:#219653}
@media (prefers-color-scheme:dark){:root{--bg:#191919;--panel:#232323;--text:#e9e9e7;
--muted:#9b9b9b;--border:#373737}}
*{box-sizing:border-box}
body{margin:0;height:100vh;display:flex;flex-direction:column;overflow:hidden;
font-family:-apple-system,"Segoe UI",Roboto,sans-serif;font-size:14px;
background:var(--bg);color:var(--text)}
.topbar{display:flex;align-items:center;gap:12px;padding:10px 18px;
border-bottom:1px solid var(--border);flex:none;flex-wrap:wrap}
.topbar h1{font-size:17px;margin:0}
.topbar a{color:var(--muted);text-decoration:none;font-size:13px;padding:3px 10px;
border:1px solid var(--border);border-radius:999px;background:var(--panel)}
.topbar a.here{color:var(--text);border-color:var(--text)}
.caps{margin-left:auto;display:flex;gap:6px;align-items:center}
.cap{font-size:11px;padding:2px 8px;border-radius:999px;border:1px solid var(--border);
color:var(--muted)}
.cap.on{border-color:var(--ok);color:var(--ok)}

.main{flex:1;display:grid;grid-template-columns:250px minmax(0,1fr) minmax(0,1fr);
min-height:0}
@media (max-width:1150px){.main{grid-template-columns:220px minmax(0,1fr)}
.pane.pdf{display:none}.pane.pdf.show{display:flex;grid-column:2}}

/* --- sidebar --- */
.side{border-right:1px solid var(--border);overflow-y:auto;padding:10px}
.pkg{margin-bottom:6px}
.pkg>h2{margin:0;font-size:12px;text-transform:uppercase;letter-spacing:.04em;
color:var(--muted);padding:8px 8px 4px}
.pkg .dl{font-size:11px;color:var(--muted);padding:0 8px 4px}
.doc{display:flex;gap:9px;align-items:center;width:100%;text-align:left;padding:7px 8px;
border:1px solid transparent;border-radius:6px;background:none;color:inherit;
font:inherit;cursor:pointer}
.doc:hover{background:var(--panel)}
.doc[aria-current="true"]{background:var(--panel);border-color:var(--accent)}
.doc img{width:26px;border:1px solid var(--border);border-radius:2px;display:block;
background:#fff;flex:none}
.doc .k{font-weight:600;font-size:13px}
.doc .s{color:var(--muted);font-size:11px}
.badge{display:inline-block;margin-left:5px;padding:0 5px;border-radius:999px;
font-size:10px;background:var(--warn);color:#fff;vertical-align:1px}
.status{margin:4px 8px 10px;padding-top:6px;border-top:1px solid var(--border);
list-style:none;padding-left:0}
.status li{display:flex;justify-content:space-between;gap:8px;font-size:11px;
color:var(--muted);padding:1px 0}
.fail{color:var(--warn)}
.pass{color:var(--ok)}

/* --- panes --- */
.pane{display:flex;flex-direction:column;min-width:0;min-height:0;
border-right:1px solid var(--border)}
.pane:last-child{border-right:none}
.head{display:flex;align-items:center;gap:8px;padding:8px 12px;flex:none;
border-bottom:1px solid var(--border);flex-wrap:wrap}
.head h3{margin:0;font-size:13px;font-weight:600}
.head .meta{color:var(--muted);font-size:11px}
.btn{padding:4px 10px;border-radius:6px;border:1px solid var(--border);
background:var(--panel);color:var(--text);font-size:12px;cursor:pointer}
.btn:hover:not(:disabled){border-color:var(--accent);color:var(--accent)}
.btn.primary:not(:disabled){background:var(--accent);border-color:var(--accent);color:#fff}
.btn:disabled{opacity:.45;cursor:default}
.spacer{margin-left:auto}
.dirty{color:var(--warn)}
.cm{flex:1;min-height:0;overflow:hidden;background:var(--bg)}
.cm .cm-editor{height:100%}
.cm .cm-gutters{color:var(--muted)}
.cm .cm-activeLine{background:rgba(127,127,127,.07)}
.cm .cm-activeLineGutter{background:transparent;color:var(--text)}
.cm .cm-cursor{border-left-color:var(--text)}
.cm .cm-selectionBackground,.cm .cm-content ::selection{background:rgba(47,111,237,.22)!important}
.cm .cm-searchMatch{background:rgba(235,87,87,.25)}
.auto{display:flex;align-items:center;gap:4px;font-size:11px;color:var(--muted);
cursor:pointer;user-select:none}
.auto input{margin:0}
iframe{flex:1;width:100%;border:none;background:#fff}
.log{flex:none;max-height:150px;overflow:auto;padding:8px 12px;
border-top:1px solid var(--border);font-family:"SF Mono",Menlo,monospace;
font-size:11px;line-height:1.5;white-space:pre-wrap;color:var(--muted)}
.log:empty{display:none}
.log.bad{color:var(--warn)}
.log.good{color:var(--ok)}
.stalebar{flex:none;background:var(--warn);color:#fff;font-size:11px;padding:5px 12px}
.blank{flex:1;display:flex;align-items:center;justify-content:center;
color:var(--muted);font-size:13px;padding:20px;text-align:center}
"""

JS = r"""
const DATA = JSON.parse(document.getElementById('data').textContent);
const $ = id => document.getElementById(id);
const frame=$('frame'), log=$('log'), state=$('state'),
      title=$('title'), meta=$('meta'), stale=$('stale'),
      saveB=$('save'), compB=$('compile'), grantB=$('grant'),
      capFs=$('capFs'), capSrv=$('capSrv'), autoBox=$('auto');

let cur=null, saved='', dirRoot=null, live=false, autoTimer=null;

/* CodeMirror 6 — the editor core Overleaf is built on. Falls back to a plain
   textarea if the vendored bundle is missing, so the page never dies on it. */
const dark = matchMedia('(prefers-color-scheme: dark)').matches;
const ed = (() => {
  const host = $('ed');
  if (window.CMEditor) {
    const cm = CMEditor.create({parent: host, doc: '', dark, onChange: changed});
    return {get: () => cm.getValue(), set: t => cm.setValue(t), focus: () => cm.focus()};
  }
  host.innerHTML = "<textarea id='fallback' spellcheck='false' style='width:100%;"
    + "height:100%;border:none;outline:none;padding:12px;background:var(--bg);"
    + "color:var(--text);font:12px/1.55 Menlo,monospace'></textarea>";
  const ta = $('fallback');
  ta.addEventListener('input', changed);
  return {get: () => ta.value, set: t => { ta.value = t; }, focus: () => ta.focus()};
})();

const dirty = () => cur && ed.get() !== saved;

function changed(){
  setState();
  // Overleaf's habit: recompile once you pause. Off by default, because each
  // run writes the .tex to disk before compiling.
  if(!autoBox.checked || !live || !cur) return;
  clearTimeout(autoTimer);
  autoTimer = setTimeout(() => { if(dirty()) compile(); }, 1500);
}

/* ---------- capability 2: File System Access ---------- */
const FS_OK = 'showDirectoryPicker' in window;
const DB='pkgfs', KEY='outputDir';

function idb(mode, fn){
  return new Promise((res,rej)=>{
    const r=indexedDB.open(DB,1);
    r.onupgradeneeded=()=>r.result.createObjectStore('h');
    r.onerror=()=>rej(r.error);
    r.onsuccess=()=>{const tx=r.result.transaction('h',mode);
      const q=fn(tx.objectStore('h')); tx.oncomplete=()=>res(q&&q.result);
      tx.onerror=()=>rej(tx.error);};
  });
}
const putDir = h => idb('readwrite', s=>s.put(h,KEY));
const getDir = () => idb('readonly',  s=>s.get(KEY));

async function usable(h){
  if(!h) return false;
  const opts={mode:'readwrite'};
  if(await h.queryPermission(opts)==='granted') return true;
  return await h.requestPermission(opts)==='granted';
}

async function grant(){
  try{
    const h=await window.showDirectoryPicker({mode:'readwrite'});
    if(!await usable(h)) return;
    dirRoot=h; await putDir(h); marks();
    say('Folder connected. The editor now reads and writes the real files.','good');
    // Only re-read from disk when there is nothing to lose. Connecting the
    // folder is also the first step of a save, and that save is carrying the
    // edits that prompted it.
    if(cur && !dirty()) select(document.querySelector('.doc[aria-current="true"]'), true);
  }catch(e){ if(e.name!=='AbortError') say('Could not open folder: '+e.message,'bad'); }
}

async function handleFor(doc, create){
  if(!dirRoot) return null;
  const dir=await dirRoot.getDirectoryHandle(doc.pkg,{create:false});
  return dir.getFileHandle(doc.tex,{create:!!create});
}

/* ---------- capability 3: the compile server ---------- */
async function api(path,opts){
  const r=await fetch(path,opts);
  const d=await r.json().catch(()=>({error:'bad response'}));
  if(!r.ok||d.error) throw new Error(d.error||('HTTP '+r.status));
  return d;
}

/* ---------- ui ---------- */
/* Where a save would land, best first. The server needs no permission at all,
   so when it is up the folder grant is pure ceremony. */
const target = () => dirRoot ? 'folder' : live ? 'server' : FS_OK ? 'ask' : 'none';

/* packages/ holds a snapshot taken by build_packages_page.py, which is all the
   published site has. Locally the server can reach the real file, and that is
   the one that changes when you compile — so prefer it, or the preview quietly
   keeps showing a PDF from whenever the page was last generated. */
const pdfUrl = d => !d.pdf ? ''
  : live ? '/resume-kit/output/' + d.pkg + '/' + d.tex.replace(/\.tex$/, '.pdf')
         : d.pdf;

function marks(){
  capFs.className='cap'+(dirRoot?' on':'');
  capFs.textContent=dirRoot?'folder connected':(FS_OK?'folder not connected':'no folder API');
  capSrv.className='cap'+(live?' on':'');
  capSrv.textContent=live?'compiler ready':'compiler offline';
  grantB.hidden=!FS_OK||!!dirRoot;
  setState();
}
function setState(){
  const t=target();
  // Always typeable; the editor never gates on a permission click.
  state.textContent = !cur ? ''
    : dirty() ? 'unsaved'
    : t==='folder' ? 'saves to the file'
    : t==='server' ? 'saves via the local server'
    : t==='ask'    ? 'connect a folder to save'
    : 'no save target — download only';
  state.className = dirty() ? 'meta dirty' : 'meta';
  saveB.disabled=!dirty();
  saveB.textContent = t==='none' ? 'Download' : 'Save';
  compB.disabled=!live||!cur;
}
function say(m,k){ log.textContent=m||''; log.className='log'+(k?' '+k:''); }

async function select(btn, keep){
  if(!btn) return;
  if(!keep && dirty() && !confirm('Discard unsaved changes to '+cur.tex+'?')) return;
  document.querySelectorAll('.doc').forEach(b=>b.setAttribute('aria-current','false'));
  btn.setAttribute('aria-current','true');
  const d = cur = DATA[btn.dataset.id];

  title.textContent=d.tex;
  meta.textContent=d.kind+' · '+d.pkg+(d.pages?' · '+d.pages+'p':'')+(d.built?' · built '+d.built:'');
  stale.hidden=!d.stale;
  frame.src = d.pdf ? pdfUrl(d)+'?t='+Date.now() : 'about:blank';
  if(!keep) say('');

  // Prefer the file on disk; the embedded copy is only a fallback.
  ed.set(saved = d.source);
  if(dirRoot){
    try{ const fh=await handleFor(d); ed.set(saved = await (await fh.getFile()).text()); }
    catch(e){ say('Showing the embedded copy — could not read '+d.tex+' from the folder ('+e.message+').'); }
  }
  setState();
}

function download(){
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([ed.get()],{type:'text/x-tex'}));
  a.download=cur.tex; a.click(); URL.revokeObjectURL(a.href);
  say('Downloaded '+cur.tex+' — this browser cannot write files in place, so '
     +'copy it over '+cur.pkg+'/'+cur.tex+' yourself.');
}

async function save(){
  if(!cur||!dirty()) return true;
  const text=ed.get();
  let t=target();

  if(t==='ask'){                      // first save doubles as the folder prompt
    await grant();
    t=target();
    if(t==='ask'){ say('Not saved — no folder connected.','bad'); return false; }
  }

  try{
    if(t==='folder'){
      const w=await (await handleFor(cur,true)).createWritable();
      await w.write(text); await w.close();
      saved=text; stale.hidden=false; setState();
      say('Saved '+cur.tex+'. The PDF is unchanged until you compile.','good');
      return true;
    }
    if(t==='server'){
      await api('/api/tex',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({path:cur.pkg+'/'+cur.tex,text})});
      saved=text; stale.hidden=false; setState();
      say('Saved '+cur.tex+' via the server. The PDF is unchanged until you compile.','good');
      return true;
    }
    download(); return false;         // nothing wrote to disk, so not "saved"
  }catch(e){ say('Save failed: '+e.message,'bad'); return false; }
}

async function compile(){
  if(!await save()) return;
  compB.disabled=true; say('Compiling…');
  try{
    const r=await api('/api/compile',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({path:cur.pkg+'/'+cur.tex})});
    say((r.ok?'Compiled.':'Compile FAILED.')+'\n\n'+r.log+'\n\nChar count: '+r.checks,
        r.ok?'good':'bad');
    if(r.ok){
      // The server rewrote resume-kit/output; this page serves its own copy.
      frame.src=pdfUrl(cur)+'?t='+Date.now();
      stale.hidden=true;
      const b=document.querySelector('.doc[aria-current="true"] .badge'); if(b) b.remove();
      say(log.textContent+'\n\nRerun build_packages_page.py to refresh the stored copy.',
          r.ok?'good':'bad');
    }
  }catch(e){ say('Compile failed: '+e.message,'bad'); }
  setState();
}

saveB.addEventListener('click',save);
compB.addEventListener('click',compile);
grantB.addEventListener('click',grant);
document.addEventListener('keydown',e=>{
  if((e.metaKey||e.ctrlKey)&&e.key==='s'){e.preventDefault();save();}
  if((e.metaKey||e.ctrlKey)&&e.key==='Enter'){e.preventDefault();if(!compB.disabled)compile();}
});
addEventListener('beforeunload',e=>{if(dirty())e.preventDefault();});
document.querySelectorAll('.doc').forEach(b=>b.addEventListener('click',()=>select(b)));

(async () => {
  if(FS_OK){ const h=await getDir().catch(()=>null); if(h&&await usable(h)) dirRoot=h; }
  live = await fetch('/api/tex?path=').then(r=>r.status===400).catch(()=>false);
  marks();
  select(document.querySelector('.doc'), true);
})();
"""


def render(packages: list[dict]) -> str:
    e = html.escape
    flat: list[dict] = []
    side: list[str] = []

    for pkg in packages:
        side.append("<div class='pkg'>")
        side.append(f"<h2>{e(pkg['name'])}</h2>")
        if pkg["deadline"]:
            side.append(f"<div class='dl'>deadline {e(pkg['deadline'])}</div>")
        for doc in pkg["docs"]:
            idx = len(flat)
            flat.append(doc)
            img = f"<img src='{e(doc['thumb'])}' alt=''>" if doc["thumb"] else ""
            sub = f"{doc['pages']} pages" if doc["pdf"] else "not compiled"
            badge = "<span class='badge'>stale</span>" if doc["stale"] else ""
            side.append(
                f"<button class='doc' data-id='{idx}'>{img}<span>"
                f"<span class='k'>{e(doc['kind'])}{badge}</span><br>"
                f"<span class='s'>{e(sub)}</span></span></button>"
            )
        if pkg["status"]:
            side.append("<ul class='status'>")
            for label, value in pkg["status"]:
                up = value.upper()
                cls = " class='fail'" if ("FAIL" in up or "NOT COMPILED" in up) else (
                    " class='pass'" if ("DONE" in up or "PASS" in up) else "")
                side.append(f"<li><span>{e(label)}</span><span{cls}>{e(value)}</span></li>")
            side.append("</ul>")
        side.append("</div>")

    if not flat:
        side.append("<p class='blank'>No compiled packages in resume-kit/output.</p>")

    data = json.dumps(flat).replace("</", "<\\/")
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Resume Packages — Hermes</title>"
        f"<style>{CSS}</style></head><body>"
        "<div class='topbar'><h1>Hermes</h1>"
        "<a href='index.html'>Digest board</a>"
        "<a class='here' href='packages.html'>Resume packages</a>"
        "<span class='caps'>"
        # So "is what I am looking at the version I just pushed?" is answerable
        # by looking, instead of by guessing about caches.
        f"<span class='cap' title='page build time'>built {datetime.now():%b %d %H:%M}</span>"
        "<button class='btn' id='grant' hidden>Connect output folder</button>"
        "<span class='cap' id='capFs'></span><span class='cap' id='capSrv'></span>"
        "</span></div>"
        "<div class='main'>"
        f"<div class='side'>{''.join(side)}</div>"
        "<div class='pane'><div class='head'><h3 id='title'>—</h3>"
        "<span class='meta' id='meta'></span><span class='spacer'></span>"
        "<span class='meta' id='state'></span>"
        "<label class='auto' title='Recompile a moment after you stop typing. "
        "Each run saves the .tex first.'>"
        "<input type='checkbox' id='auto'>auto</label>"
        "<button class='btn' id='save' disabled>Save</button>"
        "<button class='btn primary' id='compile' disabled>Compile</button>"
        "</div><div class='cm' id='ed'></div>"
        "<div class='log' id='log'></div></div>"
        "<div class='pane pdf show'><div class='head'><h3>PDF</h3>"
        "<span class='meta'>rendered output</span></div>"
        "<div class='stalebar' id='stale' hidden>The .tex has changed since this PDF "
        "was built — press Compile to update it.</div>"
        "<iframe id='frame' title='PDF preview'></iframe></div>"
        "</div>"
        f"<script type='application/json' id='data'>{data}</script>"
        "<script src='vendor/editor.js'></script>"
        f"<script>{JS}</script></body></html>"
    )


def main() -> None:
    packages = collect()
    PAGE.write_text(render(packages), encoding="utf-8")
    docs = [d for p in packages for d in p["docs"]]
    built = [d for d in docs if d["pdf"]]
    assets = sum(f.stat().st_size for f in ASSETS.rglob("*") if f.is_file()) / 1024 if ASSETS.exists() else 0
    print(f"{PAGE.name}: {len(packages)} packages, {len(built)}/{len(docs)} compiled, "
          f"{PAGE.stat().st_size/1024:.0f} KB page + {assets:.0f} KB assets")
    for d in docs:
        if not d["pdf"]:
            print(f"  not compiled: {d['pkg']}/{d['tex']}")
        elif d["stale"]:
            print(f"  STALE (.tex newer than .pdf): {d['pkg']}/{d['tex']}")


if __name__ == "__main__":
    main()
