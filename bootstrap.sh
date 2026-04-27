#!/usr/bin/env bash
# bootstrap.sh — one-liner entrypoint for x-ui-hybrid.
#
# Use:
#   curl -fsSL https://raw.githubusercontent.com/kaiserproger/x-ui-hybrid/main/bootstrap.sh \
#       | sudo bash -s -- vpn.example.org --admin-tg myhandle [--bot-token 8000:AAA…] [--email me@x]
#
# All it does: download the latest tarball of the repo, untar to a tempdir,
# and exec install.sh inside it with whatever arguments came after `--`.
#
# Override the source tarball:
#   HUH_REPO=other/fork HUH_REF=v1.2.3 curl … | sudo bash -s -- …

set -euo pipefail

REPO="${HUH_REPO:-kaiserproger/x-ui-hybrid}"
REF="${HUH_REF:-main}"
TARBALL="https://github.com/${REPO}/archive/refs/heads/${REF}.tar.gz"

red()   { printf '\033[0;31m%s\033[0m\n' "$*" >&2; }
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }

[[ $EUID -ne 0 ]] && { red "Run as root (sudo bash …)."; exit 1; }
command -v curl >/dev/null 2>&1 || { red "curl is required."; exit 1; }
command -v tar  >/dev/null 2>&1 || { red "tar is required.";  exit 1; }

WORK="$(mktemp -d -t x-ui-hybrid-XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

green ">>> Fetching $TARBALL"
curl -fsSL "$TARBALL" | tar -xz -C "$WORK" --strip-components=1

cd "$WORK"
[[ -f install.sh ]] || { red "install.sh missing in tarball — bad ref '$REF'?"; exit 1; }

chmod +x install.sh bot/install-bot.sh
exec bash install.sh "$@"
