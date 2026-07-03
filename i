#!/usr/bin/env bash
set -euo pipefail

REPO="${CURSOR_VIBEMODE_REPO:-OlegGorsky/cursor-vibemode}"
REF="${CURSOR_VIBEMODE_REF:-main}"
ARCHIVE_URL="https://github.com/${REPO}/archive/refs/heads/${REF}.tar.gz"

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

curl -fsSL "$ARCHIVE_URL" | tar -xz -C "$tmp" --strip-components=1
chmod +x "$tmp/cursor-vibemode"
"$tmp/cursor-vibemode" setup "$@"
