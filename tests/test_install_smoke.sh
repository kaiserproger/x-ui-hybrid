#!/usr/bin/env bash
# Shell smoke tests for installer scripts. No state changes — just static checks.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fail=0

check() {
    local name="$1"; shift
    if "$@" >/dev/null 2>&1; then
        printf '  OK   %s\n' "$name"
    else
        printf '  FAIL %s\n' "$name"
        "$@" 2>&1 | sed 's/^/         /'
        fail=1
    fi
}

# ---- bash syntax ----
check "bash -n install.sh"        bash -n "$ROOT/install.sh"
check "bash -n install-bot.sh"    bash -n "$ROOT/bot/install-bot.sh"
check "bash -n smoke (this file)" bash -n "$0"
check "bash -n docker e2e"        bash -n "$ROOT/tests/test_install_e2e_docker.sh"

# ---- python syntax ----
for f in landing.py bot/bot.py bot/db.py bot/panel.py bot/i18n.py bot/instructions.py; do
    check "python -m py_compile $f" python3 -m py_compile "$ROOT/$f"
done

# ---- install.sh sanity grep ----
check "install.sh has --bot-token flag" \
    grep -q -- '--bot-token)' "$ROOT/install.sh"
check "install.sh has --admin-tg flag" \
    grep -q -- '--admin-tg)' "$ROOT/install.sh"
check "install.sh has --uninstall flag" \
    grep -q -- '--uninstall)' "$ROOT/install.sh"
check "install.sh has purge uninstall flag" \
    grep -q -- '--purge)' "$ROOT/install.sh"
check "install.sh has purge-certs uninstall flag" \
    grep -q -- '--purge-certs)' "$ROOT/install.sh"
check "install.sh wires sysctl tuning" \
    grep -q '99-x-ui-hybrid.conf' "$ROOT/install.sh"
check "install.sh creates xhttp inbound" \
    grep -q 'XHTTP_REMARK' "$ROOT/install.sh"
check "install.sh enables hysteria salamander obfs" \
    grep -q 'salamander' "$ROOT/install.sh"
check "install.sh sets DPI-evasion fields" \
    grep -q 'xPaddingObfsMode' "$ROOT/install.sh"
check "install.sh uses valid xhttp padding method" \
    grep -q 'xPaddingMethod:        "tokenish"' "$ROOT/install.sh"
check "install.sh installs healthcheck" \
    grep -q 'x-ui-hybrid-healthcheck' "$ROOT/install.sh"
check "install.sh installs backup" \
    grep -q 'x-ui-hybrid-backup' "$ROOT/install.sh"
check "install.sh redirects bare panel path" \
    grep -Fq 'location = /${PANEL_PATH}' "$ROOT/install.sh"
check "install.sh proxies subscription over TLS" \
    grep -Fq 'proxy_pass https://127.0.0.1:${SUB_PORT_INTERNAL}/sub/;' "$ROOT/install.sh"
check "install.sh probes subscription over TLS" \
    grep -Fq 'https://127.0.0.1:${SUB_PORT_INTERNAL}/sub/__probe__' "$ROOT/install.sh"
check "install.sh writes meta JSON" \
    grep -qE 'INSTALL_META=.*install\.json' "$ROOT/install.sh"
check "install.sh writes early panel recovery" \
    grep -q 'panel-recovery.json' "$ROOT/install.sh"
check "install.sh has failure diagnostics" \
    grep -q 'run_failure_diagnostics' "$ROOT/install.sh"
check "install.sh prints QR codes" \
    grep -q 'qrencode' "$ROOT/install.sh"
check "install-bot.sh writes systemd unit" \
    grep -q 'x-ui-hybrid-bot.service' "$ROOT/bot/install-bot.sh"
check "bot.py wires hook server" \
    grep -q 'start_hook_server' "$ROOT/bot/bot.py"
check "bot/i18n has Russian welcome" \
    grep -q 'Привет' "$ROOT/bot/i18n.py"

# ---- landing.py CLI smokes ----
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
check "landing.py runs deterministically" \
    python3 "$ROOT/landing.py" --domain ex.test \
        --out "$TMP/site" --meta-file "$TMP/meta.json" \
        --seed smoke --no-network
check "landing meta is valid JSON" \
    python3 -c "import json; json.load(open('$TMP/meta.json'))"
check "landing produced 4 files in webroot" \
    test -f "$TMP/site/index.html" \
        -a -f "$TMP/site/404.html" \
        -a -f "$TMP/site/favicon.svg" \
        -a -f "$TMP/site/robots.txt"
check "landing did NOT pollute webroot with meta" \
    test ! -e "$TMP/site/_meta.json"

if [[ $fail -ne 0 ]]; then
    printf '\nFAIL: at least one smoke check failed.\n' >&2
    exit 1
fi
printf '\nAll smoke checks passed.\n'
