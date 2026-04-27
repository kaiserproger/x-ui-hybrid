#!/usr/bin/env bash
# bootstrap.sh — one-liner entrypoint for x-ui-hybrid.
#
# Use:
#   curl -fsSL https://raw.githubusercontent.com/kaiserproger/x-ui-hybrid/main/bootstrap.sh \
#       | sudo bash -s -- vpn.example.org --admin-tg myhandle [--bot-token 8000:AAA…] [--email me@x]
#
# By default this resolves the latest GitHub release of the repo and pulls
# *that* tarball — so a fresh user always lands on a tagged, tested cut, not
# whatever HEAD happens to look like today.
#
# Pin a specific tag or branch:
#   HUH_REF=v0.1.0 curl … | sudo bash -s -- …
#   HUH_REF=main   curl … | sudo bash -s -- …    # follow main (dev)
# Or point at a fork:
#   HUH_REPO=other/fork HUH_REF=v1.2.3 curl … | sudo bash -s -- …

set -euo pipefail

REPO="${HUH_REPO:-kaiserproger/x-ui-hybrid}"
REF="${HUH_REF:-}"

red()   { printf '\033[0;31m%s\033[0m\n' "$*" >&2; }
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }

[[ $EUID -ne 0 ]] && { red "Run as root (sudo bash …)."; exit 1; }
command -v curl >/dev/null 2>&1 || { red "curl is required."; exit 1; }
command -v tar  >/dev/null 2>&1 || { red "tar is required.";  exit 1; }

# If the user didn't pin HUH_REF, ask GitHub for the latest release tag.
# Falls back to `main` if the repo has no releases yet (chicken-and-egg
# during the very first push, or if the network blocks api.github.com).
if [[ -z "$REF" ]]; then
    REF="$(curl -fsSL --max-time 6 \
              -H 'Accept: application/vnd.github+json' \
              "https://api.github.com/repos/${REPO}/releases/latest" 2>/dev/null \
        | grep -m1 '"tag_name":' \
        | sed -E 's/.*"tag_name"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/')"
    [[ -z "$REF" ]] && REF=main
fi

# `archive/<ref>.tar.gz` accepts both tags and branch names.
TARBALL="https://github.com/${REPO}/archive/${REF}.tar.gz"

WORK="$(mktemp -d -t x-ui-hybrid-XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

green ">>> Fetching ${REPO}@${REF}"
curl -fsSL "$TARBALL" | tar -xz -C "$WORK" --strip-components=1

cd "$WORK"
[[ -f install.sh ]] || { red "install.sh missing in tarball — bad ref '$REF'?"; exit 1; }

chmod +x install.sh bot/install-bot.sh
exec bash install.sh "$@"
