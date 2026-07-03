#!/usr/bin/env bash
set -euo pipefail

REPO="${CURSOR_VIBEMODE_REPO:-OlegGorsky/cursor-vibemode}"
REF="${CURSOR_VIBEMODE_REF:-main}"
ARCHIVE_URL="https://github.com/${REPO}/archive/refs/heads/${REF}.tar.gz"
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
