#!/usr/bin/env bash
# Docker e2e for install.sh. It runs the installer in a disposable Debian
# container and mocks only the external/host-specific pieces: ACME, upstream
# 3x-ui installer, systemd, nginx, firewall and HTTP panel responses.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="x-ui-hybrid-install-e2e:local"
DOMAIN="mocked.example.test"

if ! command -v docker >/dev/null 2>&1; then
    printf 'SKIP: docker is not installed\n' >&2
    exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

mkdir -p "$tmp/fakebin" "$tmp/acme"

cat > "$tmp/Dockerfile" <<'EOF'
FROM debian:12-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -y \
    && apt-get install -y --no-install-recommends \
        bash ca-certificates coreutils curl jq openssl python3 qrencode \
        sqlite3 iproute2 procps tar gzip util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && (getent group www-data >/dev/null || groupadd -r www-data) \
    && mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled \
        /etc/fail2ban/filter.d /etc/fail2ban/jail.d /etc/systemd/system \
        /etc/tmpfiles.d /etc/cron.d

WORKDIR /work
EOF

cat > "$tmp/fakebin/apt-get" <<'EOF'
#!/usr/bin/env bash
printf '[mock apt-get] %s\n' "$*" >&2
exit 0
EOF

cat > "$tmp/fakebin/systemctl" <<'EOF'
#!/usr/bin/env bash
printf '[mock systemctl] %s\n' "$*" >&2
exit 0
EOF

cat > "$tmp/fakebin/nginx" <<'EOF'
#!/usr/bin/env bash
printf '[mock nginx] %s\n' "$*" >&2
exit 0
EOF

cat > "$tmp/fakebin/ufw" <<'EOF'
#!/usr/bin/env bash
printf '[mock ufw] %s\n' "$*" >&2
exit 0
EOF

cat > "$tmp/fakebin/modprobe" <<'EOF'
#!/usr/bin/env bash
printf '[mock modprobe] %s\n' "$*" >&2
exit 0
EOF

cat > "$tmp/fakebin/sysctl" <<'EOF'
#!/usr/bin/env bash
printf '[mock sysctl] %s\n' "$*" >&2
exit 0
EOF

cat > "$tmp/fakebin/journalctl" <<'EOF'
#!/usr/bin/env bash
printf '[mock journalctl] %s\n' "$*" >&2
exit 0
EOF

cat > "$tmp/fakebin/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

url=""
for arg in "$@"; do
    case "$arg" in
        http://*|https://*) url="$arg" ;;
    esac
done

case "$url" in
    https://api.ipify.org|https://ifconfig.me)
        printf '203.0.113.10'
        exit 0
        ;;
    https://get.acme.sh)
        printf '#!/usr/bin/env sh\nexit 0\n'
        exit 0
        ;;
    https://raw.githubusercontent.com/MHSanaei/3x-ui/main/install.sh)
        cat <<'INSTALL'
#!/usr/bin/env bash
set -euo pipefail

mkdir -p /etc/x-ui /usr/local/x-ui /etc/systemd/system
sqlite3 /etc/x-ui/x-ui.db 'CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);'
sqlite3 /etc/x-ui/x-ui.db "INSERT OR REPLACE INTO settings (key, value) VALUES ('webPort', '10587'), ('webBasePath', '/upstream-secret/'), ('webListen', '0.0.0.0');"

cat > /usr/bin/x-ui <<'XUI'
#!/usr/bin/env bash
set -euo pipefail

db=/etc/x-ui/x-ui.db
mkdir -p /etc/x-ui
sqlite3 "$db" 'CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);'

if [[ "${1:-}" == "setting" ]]; then
    shift
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -username)    sqlite3 "$db" "INSERT OR REPLACE INTO settings (key, value) VALUES ('username', '$2');"; shift 2 ;;
            -password)    sqlite3 "$db" "INSERT OR REPLACE INTO settings (key, value) VALUES ('password', '$2');"; shift 2 ;;
            -port)        sqlite3 "$db" "INSERT OR REPLACE INTO settings (key, value) VALUES ('webPort', '$2');"; shift 2 ;;
            -webBasePath) sqlite3 "$db" "INSERT OR REPLACE INTO settings (key, value) VALUES ('webBasePath', '/${2#/}/');"; shift 2 ;;
            -listenIP)    sqlite3 "$db" "INSERT OR REPLACE INTO settings (key, value) VALUES ('webListen', '$2');"; shift 2 ;;
            -webCert)     sqlite3 "$db" "INSERT OR REPLACE INTO settings (key, value) VALUES ('webCertFile', '$2');"; shift 2 ;;
            -webCertKey)  sqlite3 "$db" "INSERT OR REPLACE INTO settings (key, value) VALUES ('webKeyFile', '$2');"; shift 2 ;;
            *) shift ;;
        esac
    done
    exit 0
fi

if [[ "${1:-}" == "cert" ]]; then
    exit 0
fi

if [[ "${1:-}" == "settings" ]]; then
    sqlite3 "$db" 'SELECT key || "=" || value FROM settings ORDER BY key;'
    exit 0
fi

exit 0
XUI
chmod +x /usr/bin/x-ui
cp /usr/bin/x-ui /usr/local/x-ui/x-ui
chmod +x /usr/local/x-ui/x-ui

cat > /etc/systemd/system/x-ui.service <<'UNIT'
[Service]
ExecStart=/usr/bin/x-ui
UNIT

cat <<'OUT'
Generated random port: 10587
Port set successfully: 10587
Username and password updated successfully
Base URI path set successfully
Access URL:  https://mocked.example.test:10587/upstream-secret/
x-ui v2.9.3 installation finished, it is running now...
OUT
INSTALL
        exit 0
        ;;
esac

if [[ "$url" == */login ]]; then
    printf '{"success":true}'
    exit 0
fi

if [[ "$url" == */panel/api/inbounds/add ]]; then
    printf '{"success":true}'
    exit 0
fi

printf '[mock curl] %s\n' "$*" >&2
exit 0
EOF

cat > "$tmp/acme/acme.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

fullchain=""
key=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --fullchain-file) fullchain="$2"; shift 2 ;;
        --key-file)       key="$2"; shift 2 ;;
        *) shift ;;
    esac
done

if [[ -n "$fullchain" ]]; then
    mkdir -p "$(dirname "$fullchain")"
    printf 'mock fullchain\n' > "$fullchain"
fi

if [[ -n "$key" ]]; then
    mkdir -p "$(dirname "$key")"
    printf 'mock private key\n' > "$key"
fi

exit 0
EOF

chmod +x "$tmp/fakebin"/* "$tmp/acme/acme.sh"

docker build -q -t "$IMAGE" "$tmp" >/dev/null

docker run --rm \
    -v "$ROOT:/work:ro" \
    -v "$tmp/fakebin:/mock/bin:ro" \
    -v "$tmp/acme:/root/.acme.sh:ro" \
    -e PATH="/mock/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    "$IMAGE" \
    bash -c '
        set -euo pipefail
        bash /work/install.sh "'"$DOMAIN"'" --admin-tg operator --skip-bot

        test -f /etc/x-ui-hybrid/panel-recovery.json
        test -f /etc/x-ui-hybrid/install.json
        test -f /root/x-ui-hybrid-credentials.txt
        test -f /var/log/x-ui-hybrid-install.log

        jq -e --arg domain "'"$DOMAIN"'" ".domain == \$domain" /etc/x-ui-hybrid/install.json >/dev/null
        jq -e ".panel.url | startswith(\"https://'"$DOMAIN"'/\")" /etc/x-ui-hybrid/install.json >/dev/null
        jq -e ".panel.port != 10587" /etc/x-ui-hybrid/install.json >/dev/null
        jq -e ".panel.path != \"/upstream-secret/\"" /etc/x-ui-hybrid/install.json >/dev/null

        recovery_url="$(jq -r .panel.url /etc/x-ui-hybrid/panel-recovery.json)"
        final_url="$(jq -r .panel.url /etc/x-ui-hybrid/install.json)"
        test "$recovery_url" = "$final_url"

        grep -q "x-ui-hybrid deployment summary" /root/x-ui-hybrid-credentials.txt
        grep -q "Full install log" /var/log/x-ui-hybrid-install.log
    '

printf 'Docker install e2e passed.\n'
