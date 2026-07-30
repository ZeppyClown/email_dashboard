"""Local dev server behind the resume packages page.

Serves `/Volumes/T9/resume` statically (so the board, the generated page and the
PDFs under `resume-kit/output` all resolve from one root) and adds a small API
so the page can read, save and recompile a `.tex` in place.

    python3 scripts/packages_server.py
    open http://localhost:8765/email_dashboard/packages.html

This writes files and runs a compiler, so it binds to 127.0.0.1 only and every
path is resolved and checked to be a `.tex` inside `resume-kit/output` before it
is touched. Do not expose it on a network interface.

API
    GET  /api/tex?path=<Folder>/<file>.tex     -> {"text": ...}
    POST /api/tex   {"path":..., "text":...}   -> {"saved": true, "bytes": n}
    POST /api/compile {"path":...}             -> {"ok":..., "log":..., "checks":...}
"""
from __future__ import annotations

import json
import shutil
import subprocess
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

DASHBOARD = Path(__file__).resolve().parent.parent
ROOT = DASHBOARD.parent
OUTPUT_DIR = (ROOT / "resume-kit" / "output").resolve()
KIT = ROOT / "resume-kit"
CHAR_COUNT = KIT / "resume_builder" / "helpers" / "char_count.py"
TEMPLATE_CLS = KIT / "resume_builder" / "templates" / "resume.cls"

PORT = 8765
COMPILE_TIMEOUT = 120
MAX_BODY = 2_000_000


class Rejected(ValueError):
    """A request asked for something outside the sandbox."""


def resolve_tex(rel: str) -> Path:
    """Map a client-supplied relative path to a .tex inside OUTPUT_DIR."""
    if not rel:
        raise Rejected("no path given")
    target = (OUTPUT_DIR / rel).resolve()
    if not target.is_relative_to(OUTPUT_DIR):
        raise Rejected("path escapes resume-kit/output")
    if target.suffix != ".tex":
        raise Rejected("only .tex files may be opened")
    if not target.is_file():
        raise Rejected("no such file")
    return target


def run_checks(tex: Path) -> str:
    """Run the kit's own char-count gate so edits get judged by its rules."""
    if not CHAR_COUNT.is_file():
        return "char_count.py not found — skipped."
    # Key off the document class, not the filename. The Danish Embassy package
    # is named `..._cv.tex` because that is what they asked for, but it is
    # built on resume.cls and must be measured against resume limits.
    head = tex.read_text(encoding="utf-8", errors="replace")[:2000]
    fmt = "cv" if "\\documentclass{cv}" in head else "resume"
    try:
        proc = subprocess.run(
            ["python3", str(CHAR_COUNT), "-f", fmt, str(tex)],
            capture_output=True, text=True, timeout=60, cwd=KIT,
        )
    except subprocess.TimeoutExpired:
        return "char_count.py timed out."
    out = (proc.stdout or "") + (proc.stderr or "")
    lines = [ln for ln in out.splitlines() if ln.strip()]
    over = [ln for ln in lines if "OVER" in ln]
    total = next((ln for ln in lines if ln.startswith("Total")), "")
    head = f"{len(over)} over limit" if over else "no bullets over limit"
    return "\n".join([head, total, *over]).strip()


def compile_tex(tex: Path) -> tuple[bool, str]:
    if not shutil.which("tectonic"):
        return False, "tectonic is not installed (brew install tectonic)."
    # The templates use a custom class that lives with the templates, not the
    # package folder, so make sure a copy is present before compiling.
    cls = tex.parent / "resume.cls"
    if not cls.exists() and TEMPLATE_CLS.is_file():
        shutil.copy(TEMPLATE_CLS, cls)
    try:
        proc = subprocess.run(
            ["tectonic", tex.name], cwd=tex.parent,
            capture_output=True, text=True, timeout=COMPILE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, f"tectonic timed out after {COMPILE_TIMEOUT}s."
    log = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode == 0, log or "(no output)"


class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # --- helpers ---
    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise Rejected("body too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def end_headers(self) -> None:
        # A recompiled PDF must not be served from cache, or the preview lies.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    # --- routes ---
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/tex":
            try:
                rel = (parse_qs(parsed.query).get("path") or [""])[0]
                tex = resolve_tex(rel)
            except Rejected as exc:
                return self._json({"error": str(exc)}, 400)
            return self._json({"text": tex.read_text(encoding="utf-8", errors="replace")})
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in ("/api/tex", "/api/compile"):
            return self._json({"error": "unknown endpoint"}, 404)
        try:
            data = self._body()
            tex = resolve_tex(data.get("path", ""))
        except Rejected as exc:
            return self._json({"error": str(exc)}, 400)
        except (ValueError, json.JSONDecodeError) as exc:
            return self._json({"error": f"bad request: {exc}"}, 400)

        if parsed.path == "/api/tex":
            text = data.get("text")
            if not isinstance(text, str):
                return self._json({"error": "text must be a string"}, 400)
            tex.write_text(text, encoding="utf-8")
            return self._json({"saved": True, "bytes": len(text.encode())})

        ok, log = compile_tex(tex)
        pdf = tex.with_suffix(".pdf")
        return self._json({
            "ok": ok,
            "log": log,
            "checks": run_checks(tex),
            "pdf": pdf.name if pdf.exists() else "",
        })

    def log_message(self, fmt: str, *args) -> None:
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)


def main() -> None:
    handler = partial(Handler, directory=str(ROOT))
    with ThreadingHTTPServer(("127.0.0.1", PORT), handler) as httpd:
        print(f"serving {ROOT} on http://localhost:{PORT}")
        print(f"  board    http://localhost:{PORT}/email_dashboard/index.html")
        print(f"  packages http://localhost:{PORT}/email_dashboard/packages.html")
        print("ctrl-c to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")


if __name__ == "__main__":
    main()
