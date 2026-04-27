"""Per-platform setup instructions for end users (RU/EN).

The bot shows a platform picker on /instructions; the user picks a tile and
gets a detailed walkthrough — recommended client app, how to install it,
how to import the subscription URL, and what to expect.

These guides reference real, currently-maintained clients:

    iOS / macOS  : Streisand (free, App Store) or Hiddify-Next
    Android      : v2rayNG or Hiddify-Next
    Windows      : v2rayN or Hiddify-Next
    macOS        : Hiddify-Next or v2rayN-Mac
    Linux        : nekoray or hiddify-next AppImage
"""

from __future__ import annotations

from typing import Dict, List, Tuple


PLATFORMS: List[Tuple[str, str, str]] = [
    # (key, ru-label, en-label)
    ("ios",     "📱 iOS / iPad",       "📱 iOS / iPad"),
    ("android", "🤖 Android",          "🤖 Android"),
    ("windows", "🪟 Windows",          "🪟 Windows"),
    ("macos",   "🍎 macOS",            "🍎 macOS"),
    ("linux",   "🐧 Linux",            "🐧 Linux"),
]

# Each guide is a Markdown-flavoured plain-text body. Keep blocks short:
# the walkthrough should fit in a single Telegram message (4096 chars).

GUIDES: Dict[str, Dict[str, str]] = {
    "ios": {
        "ru": """📱 *iOS — Streisand*

1. Установи *Streisand* из App Store:
   https://apps.apple.com/app/streisand/id6450534064
2. Скопируй адрес подписки, который я тебе прислал в /connect.
3. Открой Streisand → вкладка «Подписки» → «+» → «Импорт из буфера обмена».
4. Подожди пару секунд, пока подтянутся два сервера: Hysteria2 и XHTTP.
5. На главном экране выбери *Hysteria2* (быстрее) и нажми «Подключить».
6. Если подключение не идёт через 10 секунд (бывает на провайдерах, режущих
   UDP) — переключись на *VLESS XHTTP*. Это тот же сервер, но через TCP/443.

Альтернатива: *Hiddify-Next* — кросс-платформенный, тоже понимает подписку
из одной ссылки. Ставится из App Store.""",
        "en": """📱 *iOS — Streisand*

1. Install *Streisand* from the App Store:
   https://apps.apple.com/app/streisand/id6450534064
2. Copy the subscription URL I sent you in /connect.
3. Open Streisand → *Subscriptions* tab → *+* → *Import from clipboard*.
4. Wait a few seconds for two servers to appear: Hysteria2 and XHTTP.
5. On the main screen pick *Hysteria2* (faster) and tap *Connect*.
6. If it doesn't connect within ~10s (happens on networks that filter UDP),
   switch to *VLESS XHTTP* — same server, over TCP/443.

Alternative: *Hiddify-Next* — cross-platform, also reads a single
subscription URL. Available on the App Store.""",
    },

    "android": {
        "ru": """🤖 *Android — v2rayNG*

1. Установи *v2rayNG* из Google Play или с GitHub:
   https://github.com/2dust/v2rayNG/releases/latest
   (на хуавеях/ноунеймах без Play бери .apk с GitHub).
2. Скопируй адрес подписки из /connect.
3. v2rayNG → меню (☰) → *Subscription group setting* → плюс справа сверху.
4. *Remarks*: любое имя. *URL*: вставь подписку. Сохрани.
5. ☰ → *Update subscriptions* — подтянутся два сервера.
6. На главном экране выбери Hysteria2, тапни плашку «V» снизу.
7. Если не идёт — попробуй VLESS XHTTP из того же списка.

Альтернатива: *Hiddify-Next* (Play Store / F-Droid) — проще на вид, тоже
читает подписку.""",
        "en": """🤖 *Android — v2rayNG*

1. Install *v2rayNG* from Play Store or GitHub:
   https://github.com/2dust/v2rayNG/releases/latest
2. Copy the subscription URL from /connect.
3. v2rayNG → menu (☰) → *Subscription group setting* → top-right plus.
4. *Remarks*: any name. *URL*: paste the subscription. Save.
5. ☰ → *Update subscriptions* — both servers will appear.
6. On the main screen pick Hysteria2, tap the *V* button at the bottom.
7. If it won't connect, try *VLESS XHTTP* from the same list.

Alternative: *Hiddify-Next* (Play Store / F-Droid) — simpler UI, same
subscription URL.""",
    },

    "windows": {
        "ru": """🪟 *Windows — v2rayN*

1. Скачай последний релиз *v2rayN* с GitHub:
   https://github.com/2dust/v2rayN/releases/latest
   (бери архив `v2rayN-windows-64-desktop.zip`).
2. Распакуй, запусти `v2rayN.exe` (Windows может ругнуться SmartScreen — это
   нормально для самого приложения, не для трафика).
3. Скопируй адрес подписки из /connect.
4. В v2rayN: *Subscription* → *Manage subscriptions* → *Add* → вставь URL,
   укажи имя, ОК.
5. *Subscription* → *Update subscriptions (without proxy)* — появятся два сервера.
6. Кликни по строке Hysteria2, *Set as active*.
7. Внизу справа: *System proxy* → *Set system proxy*. Готово.

Альтернатива: *Hiddify-Next for Windows* — установщик `.exe`, проще
для нетехнических людей.""",
        "en": """🪟 *Windows — v2rayN*

1. Download the latest *v2rayN* release from GitHub:
   https://github.com/2dust/v2rayN/releases/latest
   (`v2rayN-windows-64-desktop.zip`).
2. Extract and run `v2rayN.exe` (Windows SmartScreen may warn — that's
   about the binary, not your traffic).
3. Copy the subscription URL from /connect.
4. In v2rayN: *Subscription* → *Manage subscriptions* → *Add* → paste the
   URL, name it, OK.
5. *Subscription* → *Update subscriptions (without proxy)* — both servers appear.
6. Click the Hysteria2 row → *Set as active*.
7. Bottom-right: *System proxy* → *Set system proxy*. Done.

Alternative: *Hiddify-Next for Windows* — friendlier installer for
non-technical users.""",
    },

    "macos": {
        "ru": """🍎 *macOS — Hiddify-Next*

1. Скачай *Hiddify-Next* с https://github.com/hiddify/hiddify-next/releases
   (`Hiddify-MacOS.dmg`) и установи.
2. При первом запуске System Settings → *Privacy & Security* → разрешить.
3. Скопируй адрес подписки из /connect.
4. Hiddify-Next → большой плюс → *Add from clipboard*.
5. Выбери появившийся Hysteria2-сервер, нажми *Connect*.
6. Если UDP не идёт — VLESS XHTTP в той же подписке.

Альтернатива: *v2rayN-Mac* (форк v2rayN для маков) — те же шаги, что под
Windows.""",
        "en": """🍎 *macOS — Hiddify-Next*

1. Grab *Hiddify-Next* from https://github.com/hiddify/hiddify-next/releases
   (`Hiddify-MacOS.dmg`) and install.
2. First launch: System Settings → *Privacy & Security* → allow it.
3. Copy the subscription URL from /connect.
4. Hiddify-Next → big plus → *Add from clipboard*.
5. Pick the Hysteria2 server that appears, hit *Connect*.
6. If UDP doesn't work — VLESS XHTTP from the same subscription.

Alternative: *v2rayN-Mac* — same flow as on Windows.""",
    },

    "linux": {
        "ru": """🐧 *Linux — nekoray или hiddify-next*

Самый стабильный путь — официальный AppImage *hiddify-next*:
1. https://github.com/hiddify/hiddify-next/releases — `Hiddify-Linux.AppImage`.
2. `chmod +x Hiddify-*.AppImage && ./Hiddify-*.AppImage`.
3. Add → from clipboard, после копирования URL из /connect.
4. Connect.

Если предпочитаешь нативный клиент в трее: *nekoray* —
https://github.com/MatsuriDayo/nekoray/releases.

Голый CLI для серверов / VPS:
1. Поставь `hysteria2` и `xray` в систему (см. их docs).
2. Возьми из /connect прямые ссылки `hysteria2://...` и `vless://...`.
3. Запусти `hysteria2 client` или `xray run -c <client.json>`.""",
        "en": """🐧 *Linux — nekoray or hiddify-next*

The smoothest route is the official *hiddify-next* AppImage:
1. https://github.com/hiddify/hiddify-next/releases — `Hiddify-Linux.AppImage`.
2. `chmod +x Hiddify-*.AppImage && ./Hiddify-*.AppImage`.
3. Add → from clipboard, after copying the URL from /connect.
4. Connect.

If you prefer a native tray client: *nekoray* —
https://github.com/MatsuriDayo/nekoray/releases.

Pure CLI / headless server:
1. Install `hysteria2` and `xray` (see their docs).
2. Use the direct `hysteria2://...` / `vless://...` links from /connect.
3. Run `hysteria2 client` or `xray run -c <client.json>`.""",
    },
}


def platform_buttons(lang: str) -> List[Tuple[str, str]]:
    return [(key, ru if lang == "ru" else en) for (key, ru, en) in PLATFORMS]


def get_guide(platform: str, lang: str) -> str:
    body = GUIDES.get(platform)
    if not body:
        return "—"
    return body.get(lang) or body.get("en") or "—"
