#!/usr/bin/env bash
set -euo pipefail

REPO="${CURSOR_VIBEMODE_REPO:-OlegGorsky/cursor-vibemode}"
REF="${CURSOR_VIBEMODE_REF:-main}"
CACHE_BUSTER="${CURSOR_VIBEMODE_CACHE_BUSTER:-$(date +%s)}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'Ошибка: нужна команда %s\n' "$1" >&2
    exit 1
  }
}

need curl
need tar
need python3

resolve_ref() {
  sha="$(
    curl -fsSL \
      -H 'Cache-Control: no-cache' \
      -H 'Pragma: no-cache' \
      "https://api.github.com/repos/${REPO}/commits/${REF}?v=${CACHE_BUSTER}" |
      sed -n 's/^[[:space:]]*"sha":[[:space:]]*"\([0-9a-f]\{40\}\)".*/\1/p' |
      head -n 1
  )" || sha=""
  if [ -n "$sha" ]; then
    printf '%s' "$sha"
  else
    printf '%s' "$REF"
  fi
}

RESOLVED_REF="${CURSOR_VIBEMODE_RESOLVED_REF:-$(resolve_ref)}"
ARCHIVE_URL="https://github.com/${REPO}/archive/${RESOLVED_REF}.tar.gz"

tmp="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp"
}
trap cleanup EXIT

curl -fsSL \
  -H 'Cache-Control: no-cache' \
  -H 'Pragma: no-cache' \
  "${ARCHIVE_URL}?v=${CACHE_BUSTER}" |
  tar -xz -C "$tmp" --strip-components=1
chmod +x "$tmp/cursor-vibemode"
"$tmp/cursor-vibemode" setup "$@"
