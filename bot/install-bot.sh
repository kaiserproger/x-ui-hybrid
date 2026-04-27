#!/usr/bin/env bash
# bot/install-bot.sh
#
# Installs the x-ui-hybrid Telegram bot as a systemd service.
# Idempotent: re-running re-creates the venv and config.
#
# Usage (called from install.sh, but standalone use is fine too):
#   sudo bash bot/install-bot.sh --token <BOT_TOKEN> --admins myhandle \
#                                --meta /etc/x-ui-hybrid/install.json

set -euo pipefail

red()    { printf '\033[0;31m%s\033[0m\n' "$*" >&2; }
green()  { printf '\033[0;32m%s\033[0m\n' "$*"; }
die()    { red "ERROR: $*"; exit 1; }

[[ $EUID -ne 0 ]] && die "Run as root."

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
PARENT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

TOKEN=""
ADMINS=""
META="/etc/x-ui-hybrid/install.json"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --token)   TOKEN="$2";  shift 2 ;;
        --admins)  ADMINS="$2"; shift 2 ;;
        --meta)    META="$2";   shift 2 ;;
        -h|--help)
            sed -n '2,12p' "$0"
            exit 0 ;;
        *) die "unknown flag: $1" ;;
    esac
done

[[ -n "$TOKEN"  ]] || die "--token <BOT_TOKEN> is required"
[[ -n "$ADMINS" ]] || die "--admins <csv-of-usernames> is required"
[[ -f "$META"   ]] || die "--meta path does not exist: $META"

INSTALL_ROOT=/opt/x-ui-hybrid-bot
ETC_DIR=/etc/x-ui-hybrid
DB_PATH=/var/lib/x-ui-hybrid/bot.db
ENV_FILE="$ETC_DIR/bot.env"
UNIT_FILE=/etc/systemd/system/x-ui-hybrid-bot.service

mkdir -p "$INSTALL_ROOT" "$ETC_DIR" "$(dirname "$DB_PATH")"

# Copy bot package from the repo into the install root.
green ">>> Copying bot package to $INSTALL_ROOT"
rm -rf "$INSTALL_ROOT/bot"
cp -r "$SCRIPT_DIR" "$INSTALL_ROOT/bot"

# Build a virtualenv in /opt and install deps.
green ">>> Creating venv + installing deps"
if [[ ! -x "$INSTALL_ROOT/.venv/bin/python" ]]; then
    python3 -m venv "$INSTALL_ROOT/.venv"
fi
"$INSTALL_ROOT/.venv/bin/pip" install --upgrade pip >/dev/null
"$INSTALL_ROOT/.venv/bin/pip" install -r "$INSTALL_ROOT/bot/requirements.txt"

# Write the env file. chmod 600 — contains the bot token + admin list.
green ">>> Writing $ENV_FILE"
umask 077
cat > "$ENV_FILE" <<EOF
BOT_TOKEN=${TOKEN}
XUH_ADMINS=${ADMINS}
XUH_META=${META}
XUH_DB=${DB_PATH}
XUH_HOOK_HOST=127.0.0.1
XUH_HOOK_PORT=8765
XUH_LOG_LEVEL=INFO
EOF
chmod 600 "$ENV_FILE"

# Write the systemd unit.
green ">>> Writing $UNIT_FILE"
cat > "$UNIT_FILE" <<EOF
[Unit]
Description=x-ui-hybrid Telegram bot
After=network-online.target x-ui.service
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_ROOT}
EnvironmentFile=${ENV_FILE}
ExecStart=${INSTALL_ROOT}/.venv/bin/python -m bot.bot
Restart=on-failure
RestartSec=5s
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now x-ui-hybrid-bot.service
sleep 1
systemctl --no-pager --lines=8 status x-ui-hybrid-bot.service || true

green ">>> Done. Logs: journalctl -u x-ui-hybrid-bot -f"
