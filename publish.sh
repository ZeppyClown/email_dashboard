#!/usr/bin/env bash
# Regenerate the packages page and put it on the live site in one step.
#
#   ./publish.sh                 regenerate, commit, push, wait for the deploy
#   ./publish.sh -m "message"    with a commit message of your own
#   ./publish.sh --dry-run       regenerate and show what would be committed
#
# Compiling from the page rewrites resume-kit/output, but the published copy is
# a snapshot taken by build_packages_page.py. Without this the live page keeps
# serving yesterday's PDF.
set -euo pipefail

cd "$(dirname "$0")"

MSG=""
DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    -m|--message) MSG="${2:-}"; shift 2 ;;
    -n|--dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

echo "==> regenerating packages.html"
BUILD=$(python3 scripts/build_packages_page.py)
echo "$BUILD"

# A stale PDF is the one failure this whole page exists to catch, so refuse to
# publish one rather than quietly shipping a resume that is not the .tex.
if printf '%s' "$BUILD" | grep -q STALE; then
  echo
  echo "refusing to publish: a .tex is newer than its PDF (listed above)."
  echo "compile it first, from the page or with:"
  echo "    cd ../resume-kit/output/<Package> && tectonic <file>.tex"
  exit 1
fi

if [ -z "$(git status --porcelain -- packages.html packages vendor README.md scripts publish.sh)" ]; then
  echo "==> nothing changed; the live page is already current"
  exit 0
fi

git add -A -- packages.html packages vendor README.md scripts publish.sh
echo
echo "==> staged"
git status --short -- packages.html packages vendor README.md scripts publish.sh

if [ "$DRY" = 1 ]; then
  echo
  echo "dry run — not committing. Undo staging with: git reset"
  exit 0
fi

git commit -q -m "${MSG:-chore: refresh published resume packages}"

echo "==> pushing"
git push -q origin main

LOCAL=$(shasum -a 256 packages.html | cut -c1-16)
URL=https://zeppyclown.github.io/email_dashboard/packages.html
echo "==> waiting for Pages to serve $LOCAL"
for _ in $(seq 1 40); do
  if [ "$(curl -s "$URL" | shasum -a 256 | cut -c1-16)" = "$LOCAL" ]; then
    echo "==> live: $URL"
    exit 0
  fi
  sleep 6
done

echo "pushed, but the live page still differs after 4 minutes."
echo "GitHub Pages can lag; check https://github.com/ZeppyClown/email_dashboard/actions"
exit 1
