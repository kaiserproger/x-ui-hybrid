"""Bilingual strings for the bot. Russian + English.

Selection rule: if the user's Telegram language_code starts with "ru", use RU,
otherwise EN. The chosen lang is cached per-user in the DB (column users.lang).
"""

from __future__ import annotations

from typing import Optional

Lang = str  # "ru" | "en"


def detect(language_code: Optional[str]) -> Lang:
    if language_code and language_code.lower().startswith("ru"):
        return "ru"
    return "en"


_T: dict[str, dict[Lang, str]] = {

    # --- public greeting / status ---
    "welcome.new": {
        "ru": ("Привет.\n\nЭто закрытый VPN-канал. Доступ выдаётся вручную "
               "после одобрения администратора.\n\nНажми кнопку ниже, чтобы "
               "оставить заявку — администратору придёт уведомление."),
        "en": ("Hi.\n\nThis is a private VPN gateway. Access is granted "
               "manually after an admin approves your request.\n\n"
               "Tap the button below to send a request — admins will be "
               "notified."),
    },
    "welcome.pending": {
        "ru": "Заявка отправлена и ждёт рассмотрения. Я напишу, когда будет ответ.",
        "en": "Your request has been sent and is waiting for review. I'll let "
              "you know when there's a decision.",
    },
    "welcome.approved": {
        "ru": "Доступ у тебя уже есть. /connect — выслать подписку, "
              "/instructions — инструкция по подключению.",
        "en": "Your access is already active. /connect — get the subscription "
              "URL, /instructions — setup guide.",
    },
    "welcome.rejected": {
        "ru": "Заявка отклонена. Если это ошибка — напиши администратору.",
        "en": "Your request was rejected. If that's a mistake, message the admin.",
    },
    "welcome.revoked": {
        "ru": "Доступ был отозван. Напиши администратору, если нужен снова.",
        "en": "Access has been revoked. Message the admin if you need it again.",
    },

    # --- buttons ---
    "btn.request": {
        "ru": "🔑 Запросить доступ",
        "en": "🔑 Request access",
    },
    "btn.approve": {"ru": "✅ Одобрить", "en": "✅ Approve"},
    "btn.reject":  {"ru": "❌ Отклонить", "en": "❌ Reject"},

    # --- request flow ---
    "request.sent": {
        "ru": "✅ Заявка отправлена. Жди ответа администратора.",
        "en": "✅ Request sent. Wait for the admin's decision.",
    },
    "request.again": {
        "ru": "Заявка уже отправлена и ждёт рассмотрения.",
        "en": "A request is already pending review.",
    },

    # --- to admins on a new request ---
    "admin.new_request": {
        "ru": ("🔔 Новая заявка\n"
               "От: {who}\nID: <code>{tg_id}</code>\n"
               "Время: {when}"),
        "en": ("🔔 New access request\n"
               "From: {who}\nID: <code>{tg_id}</code>\n"
               "When: {when}"),
    },

    # --- after approve / reject ---
    "approved.user": {
        "ru": ("✅ Доступ выдан.\n\n"
               "Адрес подписки:\n<code>{sub_url}</code>\n\n"
               "Это один URL, который твой клиент сам разворачивает в "
               "оба транспорта (Hysteria2 / UDP-443 и VLESS+XHTTP / TCP-443). "
               "Просто вставь его в раздел «подписка / subscription» твоего "
               "приложения.\n\n"
               "/instructions — пошагово под твою платформу.\n"
               "/rotate — отозвать ключи и выдать новые, если что-то утекло."),
        "en": ("✅ Access granted.\n\n"
               "Subscription URL:\n<code>{sub_url}</code>\n\n"
               "One URL — your client expands it to both transports "
               "(Hysteria2 over UDP/443 and VLESS+XHTTP over TCP/443). Paste "
               "it into the «subscription» section of your app.\n\n"
               "/instructions — step-by-step setup for your platform.\n"
               "/rotate — wipe and reissue keys if something leaked."),
    },
    "approved.admin": {
        "ru": "✅ Заявка #{tg_id} одобрена. Пользователь получил подписку.",
        "en": "✅ Request #{tg_id} approved. The user has received their link.",
    },
    "rejected.user": {
        "ru": "❌ Заявка отклонена.",
        "en": "❌ Your request was rejected.",
    },
    "rejected.admin": {
        "ru": "❌ Заявка #{tg_id} отклонена.",
        "en": "❌ Request #{tg_id} rejected.",
    },

    # --- /connect / /rotate / /status ---
    "connect.body": {
        "ru": ("Адрес подписки:\n<code>{sub_url}</code>\n\n"
               "Если приложение не понимает подписку, вот прямые ссылки:\n\n"
               "Hysteria2 (рекомендую):\n<code>{hy_link}</code>\n\n"
               "VLESS XHTTP (TCP-fallback):\n<code>{xhttp_link}</code>"),
        "en": ("Subscription URL:\n<code>{sub_url}</code>\n\n"
               "Direct links if your app doesn't speak subscription:\n\n"
               "Hysteria2 (recommended):\n<code>{hy_link}</code>\n\n"
               "VLESS XHTTP (TCP fallback):\n<code>{xhttp_link}</code>"),
    },
    "rotate.done": {
        "ru": ("🔁 Ключи перевыпущены. Старые отозваны, можешь их забыть.\n\n"
               "Адрес подписки тот же:\n<code>{sub_url}</code>\n"
               "Просто обнови подписку в приложении."),
        "en": ("🔁 Keys rotated. Old ones revoked.\n\n"
               "Subscription URL stayed the same:\n<code>{sub_url}</code>\n"
               "Just refresh the subscription in your app."),
    },
    "status.body": {
        "ru": "Статус: <b>{status}</b>",
        "en": "Status: <b>{status}</b>",
    },

    # --- guard rails ---
    "denied.not_approved": {
        "ru": "Доступ ещё не выдан. /start — начать заявку.",
        "en": "Access has not been granted yet. /start to begin a request.",
    },
    "denied.admin_only": {
        "ru": "Только для администраторов.",
        "en": "Admins only.",
    },

    # --- admin commands ---
    "admin.menu": {
        "ru": ("Админ-меню:\n"
               "/list pending|approved|rejected|revoked — пользователи\n"
               "/approve &lt;id&gt; — одобрить\n"
               "/revoke &lt;id&gt; — отозвать\n"
               "/stats — состояние сервиса\n"
               "/broadcast &lt;text&gt; — разослать всем approved"),
        "en": ("Admin menu:\n"
               "/list pending|approved|rejected|revoked — users\n"
               "/approve &lt;id&gt; — approve\n"
               "/revoke &lt;id&gt; — revoke\n"
               "/stats — service status\n"
               "/broadcast &lt;text&gt; — message all approved users"),
    },
    "admin.list_empty": {
        "ru": "(пусто)",
        "en": "(empty)",
    },
    "admin.user_not_found": {
        "ru": "Пользователь не найден.",
        "en": "User not found.",
    },
    "admin.broadcast.sent": {
        "ru": "📣 Отправлено: {ok} OK, {fail} ошибок",
        "en": "📣 Broadcast: {ok} OK, {fail} failed",
    },
    "admin.alert.health": {
        "ru": "⚠️ Healthcheck FAILED:\n{errors}",
        "en": "⚠️ Healthcheck FAILED:\n{errors}",
    },
    "admin.alert.backup": {
        "ru": "💾 Бэкап от {ts}",
        "en": "💾 Backup at {ts}",
    },
}


def t(key: str, lang: Lang = "en", **kwargs) -> str:
    pack = _T.get(key)
    if not pack:
        return key
    template = pack.get(lang) or pack.get("en") or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            return template
    return template
