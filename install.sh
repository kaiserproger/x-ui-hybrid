#!/usr/bin/env bash
# x-ui-hybrid/install.sh
#
# Installs on a single Debian/Ubuntu server:
#   - 3x-ui (xray-core) panel
#   - Hysteria2 inbound on UDP/443 (native QUIC, ALPN h3)
#   - VLESS+XHTTP inbound on a unix socket, fronted by nginx on TCP/443
#     with DPI-evasive padding settings
#   - nginx on TCP/443 serving a generated artisan-business decoy site
#   - 3x-ui built-in subscription server, reverse-proxied at a secret prefix
#   - fail2ban, kernel tuning, automated backups, periodic healthcheck
#   - optional Telegram bot (whitelist with admin approve flow)
#
# Usage:
#   sudo ./install.sh <domain> [--email me@x] [--bot-token <BOT>] [--admin-tg <user>] [--skip-bot]
#   sudo ./install.sh --uninstall [domain] [--purge]
#
# Tested: Ubuntu 22.04/24.04, Debian 11/12.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

red()    { printf '\033[0;31m%s\033[0m\n' "$*"; }
green()  { printf '\033[0;32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
blue()   { printf '\033[0;34m%s\033[0m\n' "$*"; }

DIAGNOSTICS_RAN=0

run_failure_diagnostics() {
    local status="${1:-1}"
    local line="${2:-unknown}"
    local cmd="${3:-unknown}"

    [[ $DIAGNOSTICS_RAN -eq 1 ]] && return 0
    DIAGNOSTICS_RAN=1

    set +e
    red "ERROR: installer failed with exit code ${status} at line ${line}"
    red "ERROR: command: ${cmd}"
    yellow ">>> Diagnostics follow. Full log: ${INSTALL_LOG:-/var/log/x-ui-hybrid-install.log}"

    if command -v x-ui >/dev/null 2>&1; then
        yellow ">>> x-ui settings"
        x-ui settings
    else
        yellow ">>> x-ui binary is not installed or not in PATH"
    fi

    if [[ -f /etc/x-ui/x-ui.db ]] && command -v sqlite3 >/dev/null 2>&1; then
        yellow ">>> selected x-ui database settings"
        sqlite3 /etc/x-ui/x-ui.db \
            "SELECT key || '=' || value FROM settings WHERE key IN ('webPort','webBasePath','webListen','webCertFile','webKeyFile','subEnable','subPort','subPath','subListen','subURI') ORDER BY key;"
    fi

    if command -v systemctl >/dev/null 2>&1; then
        yellow ">>> service status: x-ui"
        systemctl status x-ui --no-pager
        yellow ">>> service status: nginx"
        systemctl status nginx --no-pager
    fi

    if command -v journalctl >/dev/null 2>&1; then
        yellow ">>> recent x-ui journal"
        journalctl -u x-ui -n 120 --no-pager
        yellow ">>> recent nginx journal"
        journalctl -u nginx -n 80 --no-pager
    fi

    if [[ -n "${DOMAIN:-}" ]]; then
        yellow ">>> nginx config test"
        nginx -t

        if [[ -f "/etc/nginx/sites-available/${DOMAIN}.conf" ]]; then
            yellow ">>> nginx site config: /etc/nginx/sites-available/${DOMAIN}.conf"
            while IFS= read -r line_text; do
                printf '    %s\n' "$line_text"
            done < "/etc/nginx/sites-available/${DOMAIN}.conf"
        fi

        yellow ">>> HTTP probe: decoy root via nginx bootstrap (port 80)"
        curl -sS --max-time 8 --resolve "${DOMAIN}:80:127.0.0.1" \
            -o /dev/null -w "http://${DOMAIN}/ -> HTTP %{http_code}, remote=%{remote_ip}:%{remote_port}, err=%{errormsg}\n" \
            "http://${DOMAIN}/"

        if ss -ltn 'sport = :443' | grep -q ':443'; then
            yellow ">>> HTTPS probe: decoy root via nginx TLS (port 443)"
            curl -ksS --max-time 8 --resolve "${DOMAIN}:443:127.0.0.1" \
                -o /dev/null -w "https://${DOMAIN}/ -> HTTP %{http_code}, remote=%{remote_ip}:%{remote_port}, err=%{errormsg}\n" \
                "https://${DOMAIN}/"
        else
            yellow ">>> HTTPS probe skipped: nothing is listening on TCP/443 yet (installer likely stopped before TLS config)"
        fi
    fi

    if [[ -n "${DOMAIN:-}" && -n "${PANEL_PATH:-}" ]] && ss -ltn 'sport = :443' | grep -q ':443'; then
        yellow ">>> HTTP probe: panel path via nginx"
        curl -ksS --max-time 8 --resolve "${DOMAIN}:443:127.0.0.1" \
            -o /dev/null -w "https://${DOMAIN}/${PANEL_PATH}/ -> HTTP %{http_code}, remote=%{remote_ip}:%{remote_port}, err=%{errormsg}\n" \
            "https://${DOMAIN}/${PANEL_PATH}/"
    fi

    if [[ -n "${PANEL_PORT:-}" && -n "${PANEL_PATH:-}" ]]; then
        yellow ">>> HTTP probe: panel directly on loopback"
        curl -ksS --max-time 8 \
            -o /dev/null -w "https://127.0.0.1:${PANEL_PORT}/${PANEL_PATH}/ -> HTTP %{http_code}, err=%{errormsg}\n" \
            "https://127.0.0.1:${PANEL_PORT}/${PANEL_PATH}/"

        yellow ">>> TCP listeners for panel port ${PANEL_PORT}"
        ss -ltnp "sport = :${PANEL_PORT}"
    fi

    yellow ">>> TCP/UDP listeners on 443"
    ss -ltnup 'sport = :443'
}

on_error() {
    local status="$1"
    local line="$2"
    local cmd="$3"
    trap - ERR
    run_failure_diagnostics "$status" "$line" "$cmd"
    exit "$status"
}

die() {
    red "ERROR: $*" >&2
    run_failure_diagnostics 1 "manual" "$*"
    exit 1
}

usage() {
    cat <<USAGE
Usage: sudo $0 <domain> [options]
       sudo $0 --uninstall [domain] [--purge] [--purge-certs]

Required:
  <domain>                 Public domain with an A/AAAA record on this server.
                           Optional for --uninstall if install.json still exists.

Options:
  --email <addr>           ACME contact email (default: admin@<domain>).
  --bot-token <token>      Telegram bot token (from @BotFather). Enables the bot.
  --admin-tg <username>    Admin Telegram @username (no @ prefix). REQUIRED — repeat
                           the flag for multiple admins. The first user with one of
                           these usernames to /start the bot is auto-promoted.
  --skip-bot               Do not install the bot even if --bot-token was given.
  --uninstall              Remove x-ui-hybrid services, configs and generated data.
  --purge                  With --uninstall, also purge nginx/fail2ban packages.
                            Certificates and acme.sh are preserved by default.
  --purge-certs            With --uninstall, also remove /etc/ssl/<domain> and
                            acme.sh certificate/account data. Destructive.
  -h, --help               This help.

Examples:
  sudo $0 vpn.example.org --admin-tg myhandle
  sudo $0 vpn.example.org --admin-tg myhandle --email me@example.org
  sudo $0 vpn.example.org --admin-tg me --admin-tg co-admin --bot-token 8000:AAA…
  sudo $0 --uninstall vpn.example.org --purge
  sudo $0 --uninstall vpn.example.org --purge --purge-certs
USAGE
}

uninstall_stack() {
    local domain="${1:-}"
    local purge="${2:-0}"
    local purge_certs="${3:-0}"
    local meta=/etc/x-ui-hybrid/install.json

    if [[ -z "$domain" && -f "$meta" ]] && command -v jq >/dev/null 2>&1; then
        domain="$(jq -r '.domain // empty' "$meta" 2>/dev/null || true)"
    fi

    green ">>> Stopping x-ui-hybrid services"
    systemctl disable --now x-ui-hybrid-bot.service 2>/dev/null || true
    systemctl disable --now x-ui.service 2>/dev/null || true
    systemctl stop nginx.service fail2ban.service 2>/dev/null || true

    green ">>> Removing systemd units and installed application files"
    rm -f /etc/systemd/system/x-ui-hybrid-bot.service
    rm -f /etc/systemd/system/x-ui.service
    systemctl daemon-reload
    systemctl reset-failed x-ui-hybrid-bot.service x-ui.service 2>/dev/null || true

    rm -rf /opt/x-ui-hybrid-bot
    rm -rf /usr/local/x-ui /etc/x-ui
    rm -f /usr/bin/x-ui

    green ">>> Removing x-ui-hybrid configs, jobs, backups and logs"
    rm -rf /etc/x-ui-hybrid /var/lib/x-ui-hybrid /var/backups/x-ui-hybrid /run/x-ui-hybrid
    rm -f /etc/cron.d/x-ui-hybrid
    rm -f /etc/sysctl.d/99-x-ui-hybrid.conf /etc/tmpfiles.d/x-ui-hybrid.conf
    rm -f /etc/fail2ban/jail.d/3x-ui.local /etc/fail2ban/filter.d/3x-ui.conf
    rm -f /usr/local/sbin/x-ui-hybrid-healthcheck /usr/local/sbin/x-ui-hybrid-backup
    rm -f /root/x-ui-hybrid-credentials.txt /var/log/x-ui-hybrid-health.log

    green ">>> Removing nginx site and webroot"
    if [[ -n "$domain" ]]; then
        rm -f "/etc/nginx/sites-enabled/${domain}.conf" "/etc/nginx/sites-available/${domain}.conf"
        rm -rf "/var/www/${domain}"

        if [[ "$purge_certs" -eq 1 ]]; then
            green ">>> Removing installed certificates for ${domain}"
            rm -rf "/etc/ssl/${domain}"
            if [[ -x /root/.acme.sh/acme.sh ]]; then
                /root/.acme.sh/acme.sh --remove -d "$domain" --ecc >/dev/null 2>&1 || true
                rm -rf "/root/.acme.sh/${domain}_ecc" "/root/.acme.sh/${domain}"
            fi
        else
            yellow ">>> Preserving certificates: /etc/ssl/${domain} and /root/.acme.sh"
        fi
    else
        yellow ">>> Domain was not provided and install.json is gone; skipping domain-specific nginx/webroot cleanup."
    fi
    rm -rf /var/www/_acme

    if [[ -f /etc/nginx/nginx.conf ]]; then
        nginx -t >/dev/null 2>&1 && systemctl reload nginx 2>/dev/null || true
    fi
    systemctl restart fail2ban 2>/dev/null || true
    sysctl --system >/dev/null 2>&1 || true

    if [[ "$purge" -eq 1 ]]; then
        green ">>> Purging nginx/fail2ban packages"
        systemctl disable --now nginx.service fail2ban.service 2>/dev/null || true
        if [[ "$purge_certs" -eq 1 && -x /root/.acme.sh/acme.sh ]]; then
            green ">>> Purging acme.sh"
            /root/.acme.sh/acme.sh --uninstall >/dev/null 2>&1 || true
            rm -rf /root/.acme.sh
        fi
        if command -v apt-get >/dev/null 2>&1; then
            apt-get purge -y nginx fail2ban >/dev/null
            apt-get autoremove -y >/dev/null
        fi
    fi

    green ">>> x-ui-hybrid uninstall complete."
}

# ---------- args ----------
DOMAIN=""
EMAIL=""
BOT_TOKEN=""
ADMINS=()
SKIP_BOT=0
UNINSTALL=0
PURGE=0
PURGE_CERTS=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --email)        EMAIL="$2"; shift 2 ;;
        --bot-token)    BOT_TOKEN="$2"; shift 2 ;;
        --admin-tg)     ADMINS+=("${2#@}"); shift 2 ;;
        --skip-bot)     SKIP_BOT=1; shift ;;
        --uninstall)    UNINSTALL=1; shift ;;
        --purge)        PURGE=1; shift ;;
        --purge-certs)  PURGE_CERTS=1; shift ;;
        -h|--help)      usage; exit 0 ;;
        -*)             die "Unknown flag: $1" ;;
        *)              [[ -z "$DOMAIN" ]] && DOMAIN="$1" || die "Unexpected positional arg: $1"; shift ;;
    esac
done
[[ $EUID -ne 0 ]] && die "Run as root."

INSTALL_LOG=/var/log/x-ui-hybrid-install.log
touch "$INSTALL_LOG"
chmod 600 "$INSTALL_LOG"
exec > >(tee -a "$INSTALL_LOG") 2>&1
trap 'on_error $? $LINENO "$BASH_COMMAND"' ERR

green ">>> x-ui-hybrid installer started at $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
green ">>> Full install log: $INSTALL_LOG"

if [[ $UNINSTALL -eq 1 ]]; then
    uninstall_stack "$DOMAIN" "$PURGE" "$PURGE_CERTS"
    exit 0
fi

[[ -z "$DOMAIN" ]] && { usage; die "domain is required"; }
[[ ${#ADMINS[@]} -eq 0 ]] && { usage; die "at least one --admin-tg <username> is required"; }
[[ -z "$EMAIL" ]] && EMAIL="admin@${DOMAIN}"

[[ "$DOMAIN" =~ ^([A-Za-z0-9](-*[A-Za-z0-9])*\.)+[A-Za-z]{2,}$ ]] \
    || die "Invalid domain: $DOMAIN"

green ">>> Target domain: $DOMAIN"
green ">>> ACME contact:  $EMAIL"
green ">>> Default admins: ${ADMINS[*]}"
[[ -n "$BOT_TOKEN" && $SKIP_BOT -eq 0 ]] && green ">>> Bot token provided (bot will be installed)"

# ---------- detect distro ----------
. /etc/os-release
case "${ID:-}" in
    ubuntu|debian) ;;
    *) die "Unsupported distro: ${ID:-unknown}. This script targets Debian/Ubuntu." ;;
esac

# ---------- 1. dependencies ----------
green ">>> Installing base packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    curl wget tar socat openssl jq nginx sqlite3 cron \
    ca-certificates ufw netcat-openbsd python3 python3-venv python3-pip \
    qrencode fail2ban iproute2

# ---------- 2. resolve public IP ----------
SERVER_IP="$(curl -fsSL --max-time 4 https://api.ipify.org || true)"
[[ -z "$SERVER_IP" ]] && SERVER_IP="$(curl -fsSL --max-time 4 https://ifconfig.me || true)"
green ">>> Server IP: ${SERVER_IP:-unknown}"

# ---------- 3. kernel tuning (BBR, big UDP buffers, low tail latency) ----------
green ">>> Applying kernel tuning"
SYSCTL_FILE="/etc/sysctl.d/99-x-ui-hybrid.conf"
cat > "$SYSCTL_FILE" <<'EOF'
# QUIC / Hysteria2 want big UDP socket buffers — without these, hysteria2 logs
# "the kernel UDP buffer size is too small" and packets get dropped at the NIC.
net.core.rmem_max=33554432
net.core.wmem_max=33554432
net.core.rmem_default=16777216
net.core.wmem_default=16777216
net.core.netdev_max_backlog=4096
net.core.somaxconn=4096

# BBR + fq for TCP — XHTTP, panel and decoy. Big tail-latency win on lossy links.
net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr

# Faster TCP recovery, friendlier to short-lived flows.
net.ipv4.tcp_fastopen=3
net.ipv4.tcp_mtu_probing=1
net.ipv4.tcp_notsent_lowat=16384
net.ipv4.tcp_tw_reuse=1
net.ipv4.tcp_fin_timeout=15

# Gentler keepalive defaults for long-lived XHTTP POSTs.
net.ipv4.tcp_keepalive_time=300
net.ipv4.tcp_keepalive_intvl=30
net.ipv4.tcp_keepalive_probes=5
EOF
# Load the bbr module so the sysctl key resolves on first apply.
modprobe tcp_bbr 2>/dev/null || true
sysctl --system >/dev/null

# ---------- 4. decoy landing page ----------
WEBROOT="/var/www/${DOMAIN}"
ACME_WEBROOT="/var/www/_acme"
mkdir -p "$WEBROOT" "$ACME_WEBROOT"

LANDING_PY="${SCRIPT_DIR}/landing.py"
[[ -f "$LANDING_PY" ]] || die "landing.py not found at $LANDING_PY (must live next to install.sh)."

green ">>> Generating geo-aware decoy landing page"
LANDING_META="/var/lib/x-ui-hybrid/landing-meta.json"
mkdir -p "$(dirname "$LANDING_META")"
python3 "$LANDING_PY" --domain "$DOMAIN" --out "$WEBROOT" --meta-file "$LANDING_META"

PERSONA_NAME="$(jq -r '.persona.name'  "$LANDING_META")"
PERSONA_TRADE="$(jq -r '.persona.trade' "$LANDING_META")"
PERSONA_CITY="$(jq -r '.persona.city'  "$LANDING_META")"
PERSONA_LAYOUT="$(jq -r '.visual.layout' "$LANDING_META")"

# ---------- 5. nginx HTTP-only bootstrap (so acme webroot works) ----------
green ">>> Configuring nginx (HTTP bootstrap)"
rm -f /etc/nginx/sites-enabled/default
NGX_CONF="/etc/nginx/sites-available/${DOMAIN}.conf"

cat > "$NGX_CONF" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    location ^~ /.well-known/acme-challenge/ {
        root ${ACME_WEBROOT};
        default_type "text/plain";
        try_files \$uri =404;
    }

    location / {
        root ${WEBROOT};
        index index.html;
        try_files \$uri \$uri/ =404;
    }
}
EOF
ln -sf "$NGX_CONF" "/etc/nginx/sites-enabled/${DOMAIN}.conf"
nginx -t
systemctl enable --now nginx
systemctl reload nginx

# ---------- 6. acme.sh + Let's Encrypt cert ----------
green ">>> Installing acme.sh and issuing Let's Encrypt cert"
if [[ ! -x "/root/.acme.sh/acme.sh" ]]; then
    curl -fsSL https://get.acme.sh | sh -s email="$EMAIL"
fi
ACME=/root/.acme.sh/acme.sh
"$ACME" --set-default-ca --server letsencrypt

CERT_DIR="/etc/ssl/${DOMAIN}"
mkdir -p "$CERT_DIR"

PANEL_PORT="$(shuf -i 20000-39999 -n 1)"
PANEL_USER="admin"
PANEL_PASS="$(openssl rand -hex 12)"
PANEL_PATH="$(openssl rand -hex 9)"

ETC_DIR=/etc/x-ui-hybrid
mkdir -p "$ETC_DIR"
PANEL_RECOVERY_JSON="${ETC_DIR}/panel-recovery.json"

write_panel_recovery() {
    local state="$1"
    cat > "$PANEL_RECOVERY_JSON" <<EOF
{
  "domain": "${DOMAIN}",
  "state": "${state}",
  "panel": {
    "url": "https://${DOMAIN}/${PANEL_PATH}/",
    "internal": "https://127.0.0.1:${PANEL_PORT}/${PANEL_PATH}/",
    "host": "127.0.0.1",
    "port": ${PANEL_PORT},
    "path": "/${PANEL_PATH}/",
    "user": "${PANEL_USER}",
    "pass": "${PANEL_PASS}"
  }
}
EOF
    chmod 600 "$PANEL_RECOVERY_JSON"

    SUMMARY=/root/x-ui-hybrid-credentials.txt
    cat > "$SUMMARY" <<EOF
=== x-ui-hybrid panel recovery ===
Generated: $(date -u +'%Y-%m-%dT%H:%M:%SZ')
State    : ${state}

These are the generated panel settings. If State is applied_to_x-ui, they have
already been written to 3x-ui. Otherwise the installer stopped before that step.

URL      : https://${DOMAIN}/${PANEL_PATH}/
Internal : https://127.0.0.1:${PANEL_PORT}/${PANEL_PATH}/
Username : ${PANEL_USER}
Password : ${PANEL_PASS}

Recovery JSON: ${PANEL_RECOVERY_JSON}
EOF
    chmod 600 "$SUMMARY"
    green ">>> Panel recovery written: ${PANEL_RECOVERY_JSON} (${state})"
}

write_panel_recovery "generated_not_yet_applied"

if [[ -s "$CERT_DIR/fullchain.pem" && -s "$CERT_DIR/privkey.pem" ]]; then
    green ">>> Reusing existing certificate in ${CERT_DIR}"
else
    if "$ACME" --issue --webroot "$ACME_WEBROOT" -d "$DOMAIN" --keylength ec-256; then
        acme_issue_status=0
    else
        acme_issue_status=$?
    fi

    if [[ $acme_issue_status -ne 0 && $acme_issue_status -ne 2 ]]; then
        yellow ">>> acme.sh issue returned ${acme_issue_status}; trying to install any existing acme.sh cert"
    fi

    if ! "$ACME" --install-cert -d "$DOMAIN" --ecc \
        --fullchain-file "$CERT_DIR/fullchain.pem" \
        --key-file       "$CERT_DIR/privkey.pem" \
        --reloadcmd      "systemctl reload nginx 2>/dev/null; systemctl restart x-ui 2>/dev/null || true"; then
        die "Let's Encrypt certificate issue/install failed and no reusable certificate exists. If rate-limited, retry after the time shown by acme.sh or use another domain."
    fi

    [[ -s "$CERT_DIR/fullchain.pem" && -s "$CERT_DIR/privkey.pem" ]] \
        || die "acme.sh reported success but installed certificate files are missing in ${CERT_DIR}"
fi

chmod 644 "$CERT_DIR/fullchain.pem"
chmod 640 "$CERT_DIR/privkey.pem"
chown root:www-data "$CERT_DIR/privkey.pem"

"$ACME" --upgrade --auto-upgrade >/dev/null 2>&1 || true

# ---------- 7. nginx full TLS config (decoy + panel + XHTTP + subscription) ----------
green ">>> Switching nginx to TLS (TCP/443) with panel, XHTTP and subscription endpoints"

# Secrets used by xray and the bot. All hex / urlsafe.
XHTTP_PATH="$(openssl rand -hex 9)"            # path under /
SUB_PATH="$(openssl rand -hex 9)"              # path under /
XHTTP_PADDING_KEY="$(openssl rand -hex 32)"
SUB_PORT_INTERNAL=2096                         # 3x-ui default sub server port (loopback only)

# Pick a real-looking observability header name to carry XHTTP padding.
# DPI sees a long random hex value — same as Datadog/Honeycomb/Sentry headers do.
PADDING_HEADERS=(
    "X-Request-Trace" "X-Trace-Id" "X-Correlation-Id"
    "X-Datadog-Trace-Id" "X-Amzn-Trace-Id" "Sentry-Trace"
    "X-Sentry-Auth"   "X-Honeycomb-Trace"   "X-B3-TraceId"
)
XHTTP_PADDING_HEADER="${PADDING_HEADERS[RANDOM % ${#PADDING_HEADERS[@]}]}"

# Unix socket xray will listen on for VLESS+XHTTP. 660 perms; nginx group access.
XHTTP_SOCK_DIR=/run/x-ui-hybrid
XHTTP_SOCK="${XHTTP_SOCK_DIR}/xhttp.sock"

mkdir -p "$XHTTP_SOCK_DIR"
chgrp www-data "$XHTTP_SOCK_DIR"
chmod 0750 "$XHTTP_SOCK_DIR"

# Persist the runtime dir across reboots (xray creates the socket file each start)
cat > /etc/tmpfiles.d/x-ui-hybrid.conf <<EOF
d ${XHTTP_SOCK_DIR} 0750 root www-data -
EOF

cat > "$NGX_CONF" <<EOF
# rate-limit zone for the secret XHTTP path: 30 req/s per IP, soft burst 60
limit_req_zone \$binary_remote_addr zone=x_ui_hybrid_xhttp:10m rate=30r/s;
# slightly tighter for the subscription path: 10 req/s/IP
limit_req_zone \$binary_remote_addr zone=x_ui_hybrid_sub:10m   rate=10r/s;

server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    location ^~ /.well-known/acme-challenge/ {
        root ${ACME_WEBROOT};
        default_type "text/plain";
        try_files \$uri =404;
    }

    location / { return 301 https://\$host\$request_uri; }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name ${DOMAIN};

    ssl_certificate     ${CERT_DIR}/fullchain.pem;
    ssl_certificate_key ${CERT_DIR}/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers off;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # ---- VLESS + XHTTP: secret prefix proxied to xray on a unix socket ----
    location /${XHTTP_PATH}/ {
        limit_req zone=x_ui_hybrid_xhttp burst=60 nodelay;
        client_max_body_size 0;

        proxy_pass http://unix:${XHTTP_SOCK}:;
        proxy_http_version 1.1;
        proxy_set_header Host                  \$host;
        proxy_set_header X-Real-IP             \$remote_addr;
        proxy_set_header X-Forwarded-For       \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto     \$scheme;
        proxy_set_header Upgrade               \$http_upgrade;
        proxy_set_header Connection            "upgrade";

        # Streaming long POST: never buffer.
        proxy_buffering         off;
        proxy_request_buffering off;
        proxy_cache             off;
        proxy_redirect          off;

        # Long-lived XHTTP stream (server keeps the POST open up to 90s by default).
        proxy_read_timeout      1h;
        proxy_send_timeout      1h;
        send_timeout            1h;

        # Hide upstream identity.
        proxy_hide_header       X-Powered-By;
        proxy_hide_header       Server;
    }

    # ---- 3x-ui subscription server, reverse-proxied at a secret prefix ----
    # 3x-ui's subscription server listens with TLS on 127.0.0.1:${SUB_PORT_INTERNAL}/sub/
    # We expose it under /${SUB_PATH}/<subId> on 443 so clients only need port 443.
    location /${SUB_PATH}/ {
        limit_req zone=x_ui_hybrid_sub burst=20 nodelay;

        proxy_pass https://127.0.0.1:${SUB_PORT_INTERNAL}/sub/;
        proxy_http_version 1.1;
        proxy_ssl_verify off;
        proxy_set_header Host              \$host;
        proxy_set_header X-Real-IP         \$remote_addr;
        proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_hide_header X-Powered-By;
        proxy_hide_header Server;
    }

    # ---- 3x-ui admin panel: secret prefix proxied to the loopback-only panel ----
    location = /${PANEL_PATH} { return 308 /${PANEL_PATH}/; }

    location /${PANEL_PATH}/ {
        proxy_pass https://127.0.0.1:${PANEL_PORT};
        proxy_http_version 1.1;
        proxy_ssl_verify off;
        proxy_set_header Host              \$host;
        proxy_set_header X-Real-IP         \$remote_addr;
        proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade           \$http_upgrade;
        proxy_set_header Connection        "upgrade";
        proxy_read_timeout 1h;
        proxy_send_timeout 1h;
    }

    # ---- Decoy landing on / ----
    root  ${WEBROOT};
    index index.html;
    error_page 404 /404.html;

    location = /favicon.svg { try_files \$uri =404; }
    location = /favicon.ico { return 404; }
    location = /robots.txt  { try_files \$uri =404; }
    location = /404.html    { internal; try_files \$uri =404; }

    location / { try_files \$uri \$uri/ =404; }
}
EOF
nginx -t
systemctl reload nginx

# ---------- 8. firewall ----------
green ">>> Opening firewall ports"
if command -v ufw >/dev/null 2>&1; then
    # Never enable UFW before SSH is explicitly allowed on a remote VPS.
    ufw allow 22/tcp       >/dev/null 2>&1 || true
    ufw allow 80/tcp       >/dev/null 2>&1 || true
    ufw allow 443/tcp      >/dev/null 2>&1 || true
    ufw allow 443/udp      >/dev/null 2>&1 || true
    ufw --force enable     >/dev/null 2>&1 || true
    # Panel and subscription server stay bound to 127.0.0.1 — never opened externally.
fi

# ---------- 9. install 3x-ui ----------
green ">>> Installing 3x-ui (MHSanaei)"
bash <(curl -fsSL https://raw.githubusercontent.com/MHSanaei/3x-ui/main/install.sh) <<EOF
n
3
${DOMAIN}
${CERT_DIR}/fullchain.pem
${CERT_DIR}/privkey.pem
EOF
XUI_BIN=/usr/local/x-ui/x-ui
[[ -x "$XUI_BIN" ]] || die "3x-ui installation failed (binary not found at $XUI_BIN)."
command -v x-ui >/dev/null 2>&1 || die "3x-ui installation failed (x-ui menu command not found)."

# ---------- 10. force panel creds + bind sub server to loopback ----------
green ">>> Setting panel credentials and binding subscription server to localhost"
systemctl stop x-ui
"$XUI_BIN" setting -username "$PANEL_USER" -password "$PANEL_PASS" \
             -port "$PANEL_PORT" -webBasePath "$PANEL_PATH" -listenIP 127.0.0.1

"$XUI_BIN" cert -webCert "$CERT_DIR/fullchain.pem" -webCertKey "$CERT_DIR/privkey.pem"

# Subscription settings live in the settings table (no CLI flags).
# Make the path match nginx's secret prefix and bind the listener to loopback.
XUI_DB="/etc/x-ui/x-ui.db"
[[ -f "$XUI_DB" ]] || die "x-ui database not found at $XUI_DB after install."
if ! sqlite3 "$XUI_DB" >/dev/null <<SQL
PRAGMA busy_timeout=10000;
INSERT OR REPLACE INTO settings (key, value) VALUES ('subEnable', 'true');
INSERT OR REPLACE INTO settings (key, value) VALUES ('subPort',   '${SUB_PORT_INTERNAL}');
INSERT OR REPLACE INTO settings (key, value) VALUES ('subPath',   '/sub/');
INSERT OR REPLACE INTO settings (key, value) VALUES ('subListen', '127.0.0.1');
INSERT OR REPLACE INTO settings (key, value) VALUES ('subDomain', '${DOMAIN}');
INSERT OR REPLACE INTO settings (key, value) VALUES ('subURI',    'https://${DOMAIN}/${SUB_PATH}/');
INSERT OR REPLACE INTO settings (key, value) VALUES ('subShowInfo','true');
SQL
then
    die "failed to update x-ui subscription settings in $XUI_DB"
fi

actual_panel_port="$(sqlite3 "$XUI_DB" "SELECT value FROM settings WHERE key='webPort';")"
actual_panel_path="$(sqlite3 "$XUI_DB" "SELECT value FROM settings WHERE key='webBasePath';")"
actual_panel_listen="$(sqlite3 "$XUI_DB" "SELECT value FROM settings WHERE key='webListen';")"
expected_panel_path="/${PANEL_PATH}/"

[[ "$actual_panel_port" == "$PANEL_PORT" ]] \
    || die "x-ui panel port setting did not apply: expected ${PANEL_PORT}, got ${actual_panel_port:-empty}"
[[ "$actual_panel_path" == "$expected_panel_path" ]] \
    || die "x-ui panel path setting did not apply: expected ${expected_panel_path}, got ${actual_panel_path:-empty}"
[[ "$actual_panel_listen" == "127.0.0.1" ]] \
    || die "x-ui panel listen setting did not apply: expected 127.0.0.1, got ${actual_panel_listen:-empty}"

systemctl restart x-ui

# Persist panel access immediately. The following inbound/API steps can fail on
# upstream 3x-ui changes; without this early recovery file the generated panel
# password only exists in this shell process.
write_panel_recovery "applied_to_x-ui"

# ---------- 11. wait for panel + subscription server ----------
green ">>> Waiting for x-ui (panel + subscription server)"
for _ in $(seq 1 30); do
    curl -ks --max-time 2 --resolve "${DOMAIN}:443:127.0.0.1" "https://${DOMAIN}/${PANEL_PATH}/" >/dev/null \
        && curl -ks --max-time 2 "https://127.0.0.1:${SUB_PORT_INTERNAL}/sub/__probe__" -o /dev/null \
        && break
    sleep 1
done

# ---------- 12. login + Hysteria2 inbound ----------
green ">>> Creating Hysteria2 (UDP/443, native QUIC) inbound"

COOKIE_JAR="$(mktemp)"
trap 'rm -f "$COOKIE_JAR"' EXIT

PANEL_BASE="https://127.0.0.1:${PANEL_PORT}/${PANEL_PATH}"

login_resp="$(
    curl -ks --max-time 10 -c "$COOKIE_JAR" \
        -d "username=${PANEL_USER}" --data-urlencode "password=${PANEL_PASS}" \
        "${PANEL_BASE}/login"
)"
echo "$login_resp" | jq -e '.success == true' >/dev/null 2>&1 \
    || die "Panel login failed. Response: $login_resp"

HY_AUTH="$(openssl rand -hex 16)"
HY_OBFS_PASSWORD="$(openssl rand -hex 16)"
HY_EMAIL="default-hy2"
HY_SUBID="$(openssl rand -hex 8)"
HY_REMARK="Hysteria2 QUIC :443"

HY_SETTINGS_JSON="$(jq -nc \
    --arg auth "$HY_AUTH" --arg email "$HY_EMAIL" --arg sub "$HY_SUBID" \
    '{version: 2, clients: [{
        auth: $auth, email: $email, limitIp: 0, totalGB: 0, expiryTime: 0,
        enable: true, tgId: "", subId: $sub, comment: "default", reset: 0
    }]}')"

HY_STREAM_JSON="$(jq -nc \
    --arg sni "$DOMAIN" \
    --arg cert "$CERT_DIR/fullchain.pem" \
    --arg key  "$CERT_DIR/privkey.pem" \
    --arg obfs "$HY_OBFS_PASSWORD" \
    '{
        network: "hysteria",
        security: "tls",
        externalProxy: [],
        finalmask: {
            udp: [{type: "salamander", settings: {password: $obfs}}]
        },
        tlsSettings: {
            serverName: $sni,
            minVersion: "1.2", maxVersion: "1.3",
            cipherSuites: "", rejectUnknownSni: false,
            disableSystemRoot: false, enableSessionResumption: false,
            certificates: [{
                certificateFile: $cert, keyFile: $key,
                oneTimeLoading: false, usage: "encipherment", buildChain: false
            }],
            alpn: ["h3"],
            echServerKeys: "", echForceQuery: "none",
            settings: { fingerprint: "", echConfigList: "" }
        },
        hysteriaSettings: { version: 2, auth: "", udpIdleTimeout: 60 }
    }')"

SNIFFING_JSON='{"enabled":false,"destOverride":["http","tls","quic","fakedns"],"metadataOnly":false,"routeOnly":false}'

post_inbound() {
    local body
    body="$(curl -ks --max-time 10 -b "$COOKIE_JAR" \
        --data-urlencode "remark=$1" \
        --data-urlencode "enable=true" \
        --data-urlencode "listen=$2" \
        --data-urlencode "port=$3" \
        --data-urlencode "protocol=$4" \
        --data-urlencode "expiryTime=0" \
        --data-urlencode "settings=$5" \
        --data-urlencode "streamSettings=$6" \
        --data-urlencode "sniffing=${SNIFFING_JSON}" \
        "${PANEL_BASE}/panel/api/inbounds/add")"
    echo "$body" | jq -e '.success == true' >/dev/null 2>&1 \
        || die "Inbound creation failed for '$1'. Response: $body"
}

post_inbound "$HY_REMARK" "" 443 hysteria "$HY_SETTINGS_JSON" "$HY_STREAM_JSON"

# ---------- 13. VLESS + XHTTP inbound on a unix socket ----------
green ">>> Creating VLESS+XHTTP inbound on ${XHTTP_SOCK} with DPI-evasive padding"

XHTTP_UUID="$(cat /proc/sys/kernel/random/uuid)"
XHTTP_EMAIL="default-xhttp"
XHTTP_SUBID="$(openssl rand -hex 8)"
XHTTP_REMARK="VLESS XHTTP :443 (TLS at nginx, unix socket)"

XHTTP_SETTINGS_JSON="$(jq -nc \
    --arg id "$XHTTP_UUID" --arg email "$XHTTP_EMAIL" --arg sub "$XHTTP_SUBID" \
    '{
        clients: [{
            id: $id, email: $email, flow: "",
            limitIp: 0, totalGB: 0, expiryTime: 0,
            enable: true, tgId: "", subId: $sub, comment: "default", reset: 0
        }],
        decryption: "none",
        fallbacks: []
    }')"

# DPI-evasive xhttp settings: padding hidden inside an obfuscated, real-looking
# observability header; broad random size range; long-lived stream-up POSTs.
XHTTP_STREAM_JSON="$(jq -nc \
    --arg path  "/${XHTTP_PATH}/" \
    --arg host  "$DOMAIN" \
    --arg padk  "$XHTTP_PADDING_KEY" \
    --arg padh  "$XHTTP_PADDING_HEADER" \
    '{
        network: "xhttp",
        security: "none",
        externalProxy: [],
        xhttpSettings: {
            path: $path,
            host: $host,
            headers: [],
            mode: "auto",
            scMaxBufferedPosts:    30,
            scMaxEachPostBytes:    "1000000",
            scStreamUpServerSecs:  "30-90",
            noSSEHeader:           false,
            xPaddingBytes:         "256-2048",
            xPaddingObfsMode:      true,
            xPaddingKey:           $padk,
            xPaddingHeader:        $padh,
            xPaddingPlacement:     "header",
            xPaddingMethod:        "tokenish",
            uplinkHTTPMethod:      "POST"
        }
    }')"

# listen=<absolute path>,perm  → xray opens an AF_UNIX socket with that mode.
# port=0 is fine — xray ignores port for AF_UNIX listens.
post_inbound "$XHTTP_REMARK" "${XHTTP_SOCK},660" 0 vless "$XHTTP_SETTINGS_JSON" "$XHTTP_STREAM_JSON"

# Make sure xray (running as root) gives the socket file group=www-data so nginx can read it.
# x-ui restarts xray on inbound change; wait, then chown.
for _ in $(seq 1 10); do
    [[ -S "$XHTTP_SOCK" ]] && break
    sleep 1
done
if [[ -S "$XHTTP_SOCK" ]]; then
    chgrp www-data "$XHTTP_SOCK" 2>/dev/null || true
    chmod 0660     "$XHTTP_SOCK" 2>/dev/null || true
fi

# ---------- 14. fail2ban for the panel ----------
green ">>> Configuring fail2ban for the 3x-ui panel"
mkdir -p /var/log/x-ui
touch    /var/log/x-ui/access.log

cat > /etc/fail2ban/filter.d/3x-ui.conf <<'EOF'
[Definition]
failregex = .*"POST /[^"]*/login HTTP/[^"]*" 200 .*wrongUsername.*"<HOST>".*$
            .*Login attempt failed.*from <HOST>.*$
ignoreregex =
EOF

cat > /etc/fail2ban/jail.d/3x-ui.local <<EOF
[3x-ui]
enabled  = true
port     = 443
filter   = 3x-ui
logpath  = /var/log/x-ui/access.log
          /usr/local/x-ui/x-ui.log
maxretry = 5
findtime = 10m
bantime  = 1h
EOF

systemctl enable --now fail2ban
systemctl restart  fail2ban || true

# ---------- 15. healthcheck + backup cron ----------
green ">>> Installing healthcheck + backup cron jobs"
ETC_DIR=/etc/x-ui-hybrid
mkdir -p "$ETC_DIR"

# Compact JSON the bot/healthcheck both consume.
INSTALL_META="${ETC_DIR}/install.json"
cat > "$INSTALL_META" <<EOF
{
  "domain":          "${DOMAIN}",
  "server_ip":       "${SERVER_IP:-}",
  "panel": {
    "url":      "https://${DOMAIN}/${PANEL_PATH}/",
    "host":     "127.0.0.1",
    "port":     ${PANEL_PORT},
    "path":     "/${PANEL_PATH}/",
    "user":     "${PANEL_USER}",
    "pass":     "${PANEL_PASS}"
  },
  "hysteria2": {
    "port":     443,
    "remark":   "${HY_REMARK}",
    "default_email": "${HY_EMAIL}",
    "default_sub":   "${HY_SUBID}",
    "default_auth":  "${HY_AUTH}",
    "obfs":          "salamander",
    "obfs_password": "${HY_OBFS_PASSWORD}"
  },
  "xhttp": {
    "remark":           "${XHTTP_REMARK}",
    "path":             "/${XHTTP_PATH}/",
    "socket":           "${XHTTP_SOCK}",
    "default_email":    "${XHTTP_EMAIL}",
    "default_sub":      "${XHTTP_SUBID}",
    "default_uuid":     "${XHTTP_UUID}",
    "padding_header":   "${XHTTP_PADDING_HEADER}",
    "padding_key":      "${XHTTP_PADDING_KEY}"
  },
  "subscription": {
    "internal_port": ${SUB_PORT_INTERNAL},
    "internal_path": "/sub/",
    "public_path":   "/${SUB_PATH}/",
    "public_url":    "https://${DOMAIN}/${SUB_PATH}/"
  },
  "cert": {
    "fullchain": "${CERT_DIR}/fullchain.pem",
    "privkey":   "${CERT_DIR}/privkey.pem"
  },
  "admins": $(printf '%s\n' "${ADMINS[@]}" | jq -R . | jq -s .)
}
EOF
chmod 600 "$INSTALL_META"

# Healthcheck script — exits 0 if all four checks pass.
cat > /usr/local/sbin/x-ui-hybrid-healthcheck <<EOF
#!/usr/bin/env bash
set -u
META="${INSTALL_META}"
DOMAIN="\$(jq -r .domain   "\$META")"
PORT="\$(jq -r .panel.port "\$META")"
PATH_="\$(jq -r .panel.path "\$META")"
SUB_PUB="\$(jq -r .subscription.public_url "\$META")"
HOST_IP="\$(curl -fsSL --max-time 4 https://api.ipify.org 2>/dev/null || echo "")"
errs=()

# 1. nginx serves the decoy.
curl -fsS --max-time 5 "https://\${DOMAIN}/" -o /dev/null \\
    || errs+=("nginx 443/tcp not serving decoy")

# 2. Panel responds through nginx on TCP/443.
curl -ks --max-time 5 --resolve "\${DOMAIN}:443:127.0.0.1" "https://\${DOMAIN}\${PATH_}" -o /dev/null \\
    || errs+=("3x-ui panel not responding through nginx 443")

# 3. Hysteria2 listens on UDP/443.
ss -ulpn 'sport = :443' 2>/dev/null | grep -q ':443'  \\
    || errs+=("hysteria2: nothing listening on UDP/443")

# 4. XHTTP unix socket exists.
[[ -S "\$(jq -r .xhttp.socket "\$META")" ]] \\
    || errs+=("xhttp: unix socket missing")

if (( \${#errs[@]} > 0 )); then
    {
        printf '[%s] x-ui-hybrid health FAILED:\n' "\$(date -Iseconds)"
        printf '  - %s\n' "\${errs[@]}"
    } | tee -a /var/log/x-ui-hybrid-health.log >&2
    # Notify the bot if it is running.
    if systemctl is-active --quiet x-ui-hybrid-bot; then
        cat <<MSG | curl -fsS --max-time 5 -X POST -H 'Content-Type: application/json' \\
            -d @- http://127.0.0.1:8765/alert >/dev/null 2>&1 || true
{
  "kind":  "health-fail",
  "errors": $(printf '%s\n' "\${errs[@]}" | jq -R . | jq -sc .),
  "at":    "\$(date -Iseconds)"
}
MSG
    fi
    exit 1
fi
exit 0
EOF
chmod +x /usr/local/sbin/x-ui-hybrid-healthcheck

# Backup script — daily snapshot of x-ui.db + meta.
cat > /usr/local/sbin/x-ui-hybrid-backup <<EOF
#!/usr/bin/env bash
set -euo pipefail
DEST=/var/backups/x-ui-hybrid
mkdir -p "\$DEST"
ts="\$(date -u +%Y%m%dT%H%M%SZ)"
out="\$DEST/x-ui-\${ts}.tar.gz"
tar -czf "\$out" -C / etc/x-ui var/lib/x-ui-hybrid etc/x-ui-hybrid 2>/dev/null
chmod 600 "\$out"
# Keep last 14 daily backups.
ls -1t "\$DEST"/x-ui-*.tar.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
# Optionally hand the file to the bot to dispatch via Telegram.
if systemctl is-active --quiet x-ui-hybrid-bot; then
    curl -fsS --max-time 30 -X POST \\
        -F "kind=backup" -F "file=@\${out}" \\
        http://127.0.0.1:8765/upload >/dev/null 2>&1 || true
fi
EOF
chmod +x /usr/local/sbin/x-ui-hybrid-backup

# Cron entries: health every 5m, backup daily at 04:17.
cat > /etc/cron.d/x-ui-hybrid <<EOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
*/5 * * * * root /usr/local/sbin/x-ui-hybrid-healthcheck
17 4 * * *  root /usr/local/sbin/x-ui-hybrid-backup
EOF

# ---------- 16. share-link generation ----------
HY_LINK="hysteria2://${HY_AUTH}@${DOMAIN}:443/?sni=${DOMAIN}&alpn=h3&obfs=salamander&obfs-password=${HY_OBFS_PASSWORD}#$(printf '%s' "$HY_REMARK" | jq -sRr @uri)"

# VLESS XHTTP link with TLS, ALPN h2,http/1.1 (matches what nginx advertises),
# uTLS chrome, mode=auto. Padding params are not put in the link — stored on the
# server and consumed by the client via xray-core's xhttpSettings on connect.
XHTTP_LINK="vless://${XHTTP_UUID}@${DOMAIN}:443?encryption=none&security=tls&sni=${DOMAIN}&alpn=h2,http%2F1.1&fp=chrome&type=xhttp&host=${DOMAIN}&path=%2F${XHTTP_PATH}%2F&mode=auto#$(printf '%s' "$XHTTP_REMARK" | jq -sRr @uri)"

# ---------- 17. optional Telegram bot ----------
BOT_INSTALLED=0
if [[ -n "$BOT_TOKEN" && $SKIP_BOT -eq 0 ]]; then
    if [[ -x "${SCRIPT_DIR}/bot/install-bot.sh" ]]; then
        green ">>> Installing Telegram bot"
        admin_csv="$(IFS=,; echo "${ADMINS[*]}")"
        bash "${SCRIPT_DIR}/bot/install-bot.sh" \
            --token   "$BOT_TOKEN" \
            --admins  "$admin_csv" \
            --meta    "$INSTALL_META"
        BOT_INSTALLED=1
    else
        yellow "Bot dir/install script missing at ${SCRIPT_DIR}/bot/install-bot.sh — skipping."
    fi
fi

# ---------- 18. summary + QR codes ----------
SUMMARY=/root/x-ui-hybrid-credentials.txt
{
cat <<EOF
=== x-ui-hybrid deployment summary ===
Generated: $(date -u +'%Y-%m-%dT%H:%M:%SZ')

Server IP    : ${SERVER_IP:-unknown}
Domain       : ${DOMAIN}
Cert dir     : ${CERT_DIR}

--- 3x-ui panel ---
URL          : https://${DOMAIN}/${PANEL_PATH}/
Internal     : https://127.0.0.1:${PANEL_PORT}/${PANEL_PATH}/
Username     : ${PANEL_USER}
Password     : ${PANEL_PASS}

--- Hysteria2 inbound (UDP 443, native QUIC, ALPN h3) ---
SNI          : ${DOMAIN}
Auth         : ${HY_AUTH}
Obfs         : salamander
Obfs password: ${HY_OBFS_PASSWORD}
Email        : ${HY_EMAIL}
Share link   : ${HY_LINK}

--- VLESS + XHTTP inbound (TCP 443, behind nginx, unix socket) ---
Path         : /${XHTTP_PATH}/
UUID         : ${XHTTP_UUID}
Email        : ${XHTTP_EMAIL}
Mode         : auto · stream-up via nginx HTTP/1.1
Padding      : 256-2048 bytes, tokenish obfs in header "${XHTTP_PADDING_HEADER}"
Padding key  : ${XHTTP_PADDING_KEY}
Share link   : ${XHTTP_LINK}

--- Subscription endpoint ---
Public URL   : https://${DOMAIN}/${SUB_PATH}/<subId>
              (default Hysteria2 subId: ${HY_SUBID})
              (default XHTTP    subId: ${XHTTP_SUBID})

--- Decoy on TCP/443 ---
Document root: ${WEBROOT}
Persona      : ${PERSONA_NAME} (${PERSONA_TRADE}, ${PERSONA_CITY})
Layout       : ${PERSONA_LAYOUT}

--- Operational ---
Install meta : ${INSTALL_META}
Healthcheck  : /usr/local/sbin/x-ui-hybrid-healthcheck (every 5m)
Backups dir  : /var/backups/x-ui-hybrid (daily 04:17 UTC, keeps 14)
fail2ban jail: 3x-ui (5 fails / 10m → 1h ban)
Sysctl       : ${SYSCTL_FILE}
EOF

if [[ $BOT_INSTALLED -eq 1 ]]; then
    cat <<EOF

--- Telegram bot ---
Service      : x-ui-hybrid-bot.service
Default admin: $(printf '@%s ' "${ADMINS[@]}")
Open the bot in Telegram, run /start, then /admin from an admin account.
EOF
fi
} > "$SUMMARY"
chmod 600 "$SUMMARY"

echo
green "============================================================"
green "  Done. Summary saved to ${SUMMARY}"
green "============================================================"
cat "$SUMMARY"

echo
blue "--- Hysteria2 share link (QR) ---"
echo  "$HY_LINK"
qrencode -t ANSIUTF8 -m 1 -- "$HY_LINK" || true
echo
blue "--- VLESS+XHTTP share link (QR) ---"
echo  "$XHTTP_LINK"
qrencode -t ANSIUTF8 -m 1 -- "$XHTTP_LINK" || true
echo

yellow "Two transports ready: Hysteria2 on UDP/443 (preferred), VLESS+XHTTP on"
yellow "TCP/443 as a fallback when UDP is filtered upstream. Both share the"
yellow "same domain, certificate and decoy site."
