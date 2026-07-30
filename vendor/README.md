# vendor/

`editor.js` is a prebuilt bundle of **CodeMirror 6** — the same editor core
Overleaf uses — exposing a single global, `CMEditor.create()`. It is committed
rather than pulled from a CDN so the page works offline and on GitHub Pages
without an external dependency, and so this repo keeps its "static site, no
build step" property.

All bundled packages are **MIT licensed** (`codemirror`, `@codemirror/*`,
`@lezer/*`, `@marijn/*`). Copyright (C) by Marijn Haverbeke and others.
See <https://github.com/codemirror/dev> for the upstream sources.

Overleaf itself is **not** vendored here. It is AGPL-3.0 and is a server
application requiring MongoDB and Redis; only the editor component's
open-source foundation is shared.

## Rebuilding

```bash
mkdir cmbuild && cd cmbuild && npm init -y
npm i codemirror@6 @codemirror/legacy-modes @codemirror/language \
      @codemirror/view @codemirror/state @codemirror/search esbuild
# entry.js as documented in scripts/build_packages_page.py
./node_modules/.bin/esbuild entry.js --bundle --format=iife \
      --global-name=CMEditor --minify --outfile=editor.js
```
