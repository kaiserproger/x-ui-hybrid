# x-ui-hybrid

One-shot installer that puts a hardened proxy stack on a single Linux box:

- **3x-ui (xray-core)** panel.
- **Hysteria2** on UDP/443 — native QUIC, ALPN h3, no TCP-over-TCP.
- **VLESS+XHTTP** on TCP/443 fronted by nginx, talking to xray over a unix
  socket, with DPI-evasive padding obfuscated inside an observability-style
  HTTP header.
- **Geo-aware decoy site** on TCP/443 — picks a plausible artisan-business
  persona for the server's actual country and renders one of five layouts.
- **Subscription endpoint** (3x-ui's built-in sub server) reverse-proxied at
  a secret prefix on the same 443.
- **Telegram bot** with whitelist + admin approve flow. Hands users a single
  subscription URL, sends bilingual setup walkthroughs (RU/EN), pushes
  healthcheck alerts and daily backups to admin DMs.
- **Kernel tuning** (BBR, fq, big UDP buffers) for stable p95/p99 under loss.
- **fail2ban** jail on the panel, **healthcheck** every 5 min, **backups**
  daily.

```
                                          ┌─────────────────────────────┐
                                          │  3x-ui panel  (random port) │
                                          └────────────▲────────────────┘
                                                       │
client ── HTTPS ─────────► nginx :443/tcp ─┬──── /        decoy lander
                                           ├──── /<secret>/  ──► xray VLESS+XHTTP (unix socket)
                                           └──── /<sub>/     ──► xray sub-server (127.0.0.1:2096)
client ── QUIC ──────────► xray  :443/udp                        Hysteria2 (native, ALPN h3)

             ┌────────────────────────────────────────────────────────────┐
             │  x-ui-hybrid-bot.service (Telegram)                         │
             │   ▸ /start /apply  → admin approve → adds clients to xray │
             │   ▸ /connect /rotate /instructions /status                │
             │   ▸ admin: /list /approve /revoke /broadcast /stats       │
             │   ▸ POST 127.0.0.1:8765/{alert,upload} from cron jobs     │
             └────────────────────────────────────────────────────────────┘
```

## What you get on which port

| Port      | Service                                                          |
|-----------|------------------------------------------------------------------|
| 80/tcp    | nginx — HTTPS redirect + ACME http-01 webroot                    |
| 443/tcp / | nginx — geo-aware decoy site (HSTS, OCSP stapling)               |
| 443/tcp /\<secret\>/ | nginx → xray VLESS+XHTTP via unix socket             |
| 443/tcp /\<sub\>/    | nginx → 3x-ui subscription server (127.0.0.1:2096)   |
| 443/udp   | xray — Hysteria2, ALPN h3                                        |
| panel     | 3x-ui admin panel (random port, same cert)                       |
| local 8765 | bot's hook server (alert + backup, 127.0.0.1 only)              |

## Why these components

- **3x-ui (MHSanaei)** — actively maintained x-ui fork. v2.9.x ships native
  Hysteria2 + XHTTP UI/share-link support backed by xray-core (hysteria2
  inbound landed in xray-core v26.3.27). One daemon, one config DB, one
  cert. No sing-box co-process.
- **acme.sh in webroot mode** — renewals never need to stop nginx.
- **XHTTP on a unix socket** — xray-core resolves an absolute path in
  `listen` to AF_UNIX. nginx talks to it via `proxy_pass http://unix:/path:`.
  No exposed loopback TCP port even on 127.0.0.1.
- **Decoy generator (`landing.py`)** — geo-detects via `ipinfo.io` (with
  `ipapi.co` and `ip-api.com` fallbacks), picks a plausible artisan persona
  for the country, composes copy from per-archetype phrase pools, and
  renders one of five hand-written layouts (editorial / studio_dark /
  brutalist / boutique / press) with a randomised palette and font pairing.

## DPI evasion settings (XHTTP)

The installer turns on every padding/obfuscation knob that current xray-core
supports for XHTTP:

| Setting             | Value                  | Why                                              |
|---------------------|------------------------|--------------------------------------------------|
| `mode`              | `auto`                 | client picks stream-up via nginx HTTP/1.1        |
| `xPaddingBytes`     | `256-2048`             | wide range — frame sizes don't fingerprint       |
| `xPaddingObfsMode`  | `true`                 | padding hidden in obfuscated HTTP header         |
| `xPaddingPlacement` | `header`               | inside header value, not body                    |
| `xPaddingMethod`    | `header-value`         |                                                  |
| `xPaddingHeader`    | random from realistic pool | `X-Trace-Id`, `X-Datadog-Trace-Id`, `Sentry-Trace`, … — looks like real observability traffic |
| `xPaddingKey`       | random 32-hex          | per-install secret; without it padding looks like noise |
| `scStreamUpServerSecs` | `30-90`             | longer streams → fewer reconnect signals         |
| `noSSEHeader`       | `false`                | keeps SSE-style header — matches legitimate streaming endpoints |

Combined with: TLS terminated at nginx (ALPN advertises `h2,http/1.1`),
the decoy *actually* serving HTML on `/`, and small per-IP rate-limit zones
(30 req/s on the XHTTP path, 10 req/s on the subscription path), the result
looks like a small business serving a legitimate single-page site with some
streaming endpoint behind it.

## Requirements

- Clean **Debian 11/12** or **Ubuntu 22.04/24.04** server, root access.
- A domain with `A` (and optionally `AAAA`) record pointing at the server.
- `80/tcp`, `443/tcp` and `443/udp` reachable from the public internet.
- Don't run on a box that already has nginx / x-ui / acme.sh configured.
- For the bot: a token from [@BotFather](https://t.me/BotFather).

## Install

### One-liner (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/kaiserproger/x-ui-hybrid/main/bootstrap.sh \
  | sudo bash -s -- vpn.example.org --admin-tg myhandle
```

`bootstrap.sh` resolves the **latest GitHub release tag** (currently
[v0.1.0](https://github.com/kaiserproger/x-ui-hybrid/releases/tag/v0.1.0)),
pulls *that* tarball into a tempdir, and execs `install.sh` inside it with
everything after `--`. The one-liner stays the same across releases — every
new tagged release is picked up automatically.

To pin a specific version (or follow `main` for unreleased changes):

```bash
HUH_REF=v0.1.0 curl -fsSL …/bootstrap.sh | sudo bash -s -- …  # specific tag
HUH_REF=main   curl -fsSL …/bootstrap.sh | sudo bash -s -- …  # bleeding edge
```

### From a clone

```bash
git clone https://github.com/kaiserproger/x-ui-hybrid.git
cd x-ui-hybrid

# Minimum (no bot — just the proxy stack + decoy):
sudo bash install.sh vpn.example.org --admin-tg myhandle

# Full: with the Telegram bot.
sudo bash install.sh vpn.example.org \
    --email me@example.org \
    --bot-token 8000000000:AAA-your-bot-token \
    --admin-tg myhandle \
    --admin-tg co-admin
```

Flags:

| Flag                   | Meaning                                                                        |
|------------------------|--------------------------------------------------------------------------------|
| `<domain>` (positional)| public domain — required                                                       |
| `--admin-tg`           | admin Telegram username (without `@`); repeatable; **at least one required**   |
| `--email`              | ACME contact (default: `admin@<domain>`)                                       |
| `--bot-token`          | Telegram bot token; **enables the bot** (otherwise skipped)                    |
| `--skip-bot`           | don't install the bot even if `--bot-token` is given                           |
| `-h`, `--help`         | help                                                                           |

Whole run: ~2–4 minutes (apt + LE challenge + xray binary download).

## After install

Operator summary lands at `/root/x-ui-hybrid-credentials.txt` (chmod 600).
It includes:

- panel URL + creds
- Hysteria2 share link + auth + QR (rendered to terminal as ANSI art)
- VLESS+XHTTP share link + UUID + QR
- subscription public URL
- decoy persona + layout summary
- paths of healthcheck/backup scripts and the cron file

The bot reads its config from `/etc/x-ui-hybrid/install.json` (operator
secrets included — chmod 600).

## Telegram bot

When `--bot-token` is passed, `bot/install-bot.sh` runs:

1. Creates a venv at `/opt/x-ui-hybrid-bot/.venv`.
2. Installs `aiogram` + `aiohttp` from `bot/requirements.txt`.
3. Writes `/etc/x-ui-hybrid/bot.env` (chmod 600) with:
   `BOT_TOKEN`, `XUH_ADMINS=<csv>`, `XUH_META`, `XUH_DB`, `XUH_HOOK_*`.
4. Writes `x-ui-hybrid-bot.service` and `systemctl enable --now`s it.

### What users see

```
/start                — welcome + "Request access" button
                        new users are queued, admins are notified

/connect              — once approved: subscription URL + direct
                        hysteria2:// and vless:// share links

/rotate               — wipe the user's keys, mint new ones, send the
                        same subscription URL (clients refresh it)

/instructions         — picks a platform (iOS/Android/Win/macOS/Linux)
                        and shows a step-by-step guide naming concrete
                        client apps (Streisand, v2rayNG, v2rayN,
                        Hiddify-Next, nekoray)

/status               — pending|approved|rejected|revoked
```

Russian and English are auto-selected from the user's Telegram
`language_code`; `ru*` → RU, anything else → EN.

### What admins see

```
/admin                — menu

/list pending|approved|rejected|revoked
                      — paginated user list

/approve <tg_id>      — manual approve (also one-click from the request DM)
/revoke  <tg_id>      — wipe the user's xray clients, set status=revoked
/broadcast <text>     — DM all approved users
/stats                — panel up/down, counts per status
```

When a user requests access, every seeded admin gets a DM with **✅ Approve
/ ❌ Reject** inline buttons. Approve does the panel API calls (creating
two clients, one per inbound, sharing a freshly-minted `subId`), updates
the DB, and DM's the user the subscription URL.

### Whitelist bootstrap

Each `--admin-tg <username>` seeds an *expected admin* into the bot DB. The
first time someone with that username does `/start`, the bot promotes them to
admin and auto-approves them (no queue dance for the operator). At least one
must be set at install time.

After the first contact, admin status is keyed by Telegram user ID (not
username), so renaming on Telegram won't lose the role.

### Healthcheck + backup integration

`install.sh` drops two cron entries in `/etc/cron.d/x-ui-hybrid`:

- `*/5 * * * * /usr/local/sbin/x-ui-hybrid-healthcheck` — checks decoy on
  443/tcp, panel response, UDP listener for hysteria2, XHTTP unix socket.
  On failure, posts JSON to `127.0.0.1:8765/alert`. The bot relays it as a
  DM to every admin. Failures are also logged to `/var/log/x-ui-hybrid-health.log`.
- `17 4 * * * /usr/local/sbin/x-ui-hybrid-backup` — tars `/etc/x-ui`,
  `/etc/x-ui-hybrid` and `/var/lib/x-ui-hybrid` into
  `/var/backups/x-ui-hybrid/x-ui-<timestamp>.tar.gz` (keeps the last 14).
  If the bot is up, the archive is also POSTed to
  `127.0.0.1:8765/upload`, which DM's it to admins.

The hook port (`XUH_HOOK_PORT`, default 8765) only listens on
`127.0.0.1` — never opened in the firewall.

## Uninstall

```bash
systemctl disable --now x-ui-hybrid-bot 2>/dev/null
rm -f /etc/systemd/system/x-ui-hybrid-bot.service
systemctl daemon-reload
rm -rf /opt/x-ui-hybrid-bot

x-ui uninstall                # removes 3x-ui + xray + service file
systemctl disable --now nginx fail2ban
apt-get purge -y nginx fail2ban
~/.acme.sh/acme.sh --uninstall

rm -rf /etc/ssl/<domain> /var/www/<domain> /var/www/_acme
rm -rf /etc/x-ui-hybrid /var/lib/x-ui-hybrid /var/backups/x-ui-hybrid
rm -f  /etc/cron.d/x-ui-hybrid /etc/sysctl.d/99-x-ui-hybrid.conf
rm -f  /etc/fail2ban/jail.d/3x-ui.local /etc/fail2ban/filter.d/3x-ui.conf
rm -f  /usr/local/sbin/x-ui-hybrid-{healthcheck,backup}
rm -f  /root/x-ui-hybrid-credentials.txt
```

## Files this script touches

```
/etc/sysctl.d/99-x-ui-hybrid.conf       # BBR, big UDP buffers, low-latency TCP
/etc/nginx/sites-available/<domain>.conf
/etc/nginx/sites-enabled/<domain>.conf
/etc/ssl/<domain>/{fullchain,privkey}.pem
/etc/x-ui/x-ui.db                      # 3x-ui state
/etc/x-ui-hybrid/install.json           # ops/bot meta (chmod 600)
/etc/x-ui-hybrid/bot.env                # BOT_TOKEN + admins (chmod 600)
/etc/cron.d/x-ui-hybrid                 # healthcheck + backup
/etc/fail2ban/jail.d/3x-ui.local       # 3x-ui jail
/etc/fail2ban/filter.d/3x-ui.conf
/etc/tmpfiles.d/x-ui-hybrid.conf        # /run/x-ui-hybrid dir at boot
/etc/systemd/system/x-ui.service       # 3x-ui (from upstream)
/etc/systemd/system/x-ui-hybrid-bot.service
/run/x-ui-hybrid/xhttp.sock             # AF_UNIX socket xray opens
/var/www/<domain>/                     # decoy site (index.html, 404, favicon)
/var/www/_acme/                        # ACME http-01 webroot
/var/lib/x-ui-hybrid/landing-meta.json  # what persona was generated
/var/lib/x-ui-hybrid/bot.db             # bot's user/applications store
/var/backups/x-ui-hybrid/               # daily backups
/var/log/x-ui-hybrid-health.log         # health-check failures
/usr/local/sbin/x-ui-hybrid-healthcheck
/usr/local/sbin/x-ui-hybrid-backup
/usr/local/x-ui/                       # 3x-ui binary + xray binaries
/opt/x-ui-hybrid-bot/                   # bot venv + package
/root/.acme.sh/                        # acme.sh client + per-domain config
/root/x-ui-hybrid-credentials.txt       # operator summary (chmod 600)
```

## Tests

The repo ships two test runners:

### Stdlib-only (works in any sandbox)

```bash
python3 tests/run-stdlib.py
```

Runs **32 tests** for the landing generator, the bot's sqlite store, the
i18n module, the per-platform instructions, and the bot's pure helpers
(`hy_share_link`, `xhttp_share_link`, `gen_secrets`, `email_for`, etc.).
No external pip packages needed; pytest is stubbed.

### Full pytest suite (covers the panel HTTP client too)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r tests/requirements.txt
python -m pytest tests -ra
```

Adds `tests/test_panel.py` which spins up an aiohttp mock 3x-ui and
exercises login, list, find, addClient and idempotent
delClientByEmail.

### Static smoke (no Python needed)

```bash
bash tests/test_install_smoke.sh
```

`bash -n` for both installers, `py_compile` for every Python module, plus
greps that catch the common "feature dropped from install.sh" regression
(missing `--bot-token` flag, no XHTTP padding, missing healthcheck, …).

## Troubleshooting

- **acme.sh fails with "Invalid response"** — DNS isn't propagated yet, or
  the provider blocks port 80 inbound. `dig +short <domain>` should match
  the server IP; `curl http://<domain>/.well-known/acme-challenge/test`
  must reach nginx.
- **Hysteria2 client can't connect, decoy loads fine** — UDP/443 is
  filtered upstream. `ss -ulpn 'sport = :443'` should show xray; if it
  does, the issue is between you and the VPS, not the box. Some VPS
  providers block UDP by default.
- **XHTTP fails with "502 Bad Gateway"** — xray hasn't created the unix
  socket yet (or got the wrong group). Check `ls -l /run/x-ui-hybrid/`,
  it should be `srw-rw---- root www-data xhttp.sock`. The installer
  fixes ownership but a `systemctl restart x-ui` re-creates the socket
  cleanly.
- **Subscription URL returns 404** — the path on disk is in
  `subPath` (default `/sub/`), nginx prefix in `/<sub>/` proxies to it.
  `jq .subscription /etc/x-ui-hybrid/install.json` shows the public URL.
- **Bot won't start** — `journalctl -u x-ui-hybrid-bot -f`. Most common:
  bad token (BotFather gave you a fresh one), or `/etc/x-ui-hybrid/install.json`
  isn't there yet (you ran `install-bot.sh` standalone before `install.sh`).
- **Bot says `panel error: ...`** — the bot's reaching the 3x-ui panel but
  the request failed (renamed inbound, bad creds in `install.json`).
  Check `journalctl -u x-ui -n 200` and `journalctl -u x-ui-hybrid-bot -n 200`.

## Security notes (read this)

- The decoy is a façade. It deters scanning and casual probing; it does
  **not** make the proxy uncensorable. If your adversary is a state-level
  active prober that does timed correlation across handshakes, stop here
  and use Reality / Cloudflare-fronted setups.
- The Telegram bot stores user IDs and `auth/uuid` secrets in plaintext at
  `/var/lib/x-ui-hybrid/bot.db`. Lock down the host. The bot DB and the
  install meta are both `chmod 600 root`.
- Backups in `/var/backups/x-ui-hybrid/` are also `chmod 600` and contain
  the panel password + every client's auth — don't ship them anywhere
  you don't trust. Disable Telegram-side backup by removing the
  `x-ui-hybrid-backup` line in `/etc/cron.d/x-ui-hybrid` if you don't want
  them flying through Telegram.
- Subscription URLs are bearer secrets — anyone with the URL has access.
  Use `/rotate` (or admin `/revoke` + reapply) if a URL leaks.

## Contributing

PRs welcome. Anything that touches behaviour should come with a test
in `tests/`, even if just an addition to the smoke checks or the
`run-stdlib.py` runner. Style: small files, no premature abstractions,
ASCII-only in code (Russian only in user-facing strings).
