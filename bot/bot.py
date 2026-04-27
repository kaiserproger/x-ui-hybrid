"""x-ui-hybrid Telegram bot.

A small aiogram-3 bot that runs alongside the 3x-ui panel and controls
Hysteria2 / VLESS+XHTTP clients via the panel HTTP API.

Flow:
    user /start                 → /apply button if not yet pending
    user /apply (button)        → status = pending; admins notified
    admin clicks ✅/❌            → status = approved|rejected
    on approve: bot creates a hysteria2 client + xhttp client tied to
        a freshly-generated subId, then DM's the user the subscription URL.

Configuration: read from /etc/x-ui-hybrid/install.json (path overridable via
XUH_META env var) and the following env vars:

    BOT_TOKEN          Telegram bot token from @BotFather (required).
    XUH_ADMINS         CSV of default-admin Telegram usernames (no @).
    XUH_DB             Path to the bot's sqlite store (default: /var/lib/x-ui-hybrid/bot.db).
    XUH_META           Path to install.json (default: /etc/x-ui-hybrid/install.json).
    XUH_HOOK_HOST      Bind host for the local healthcheck hook server (default: 127.0.0.1).
    XUH_HOOK_PORT      Bind port for the local hook server (default: 8765).
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from aiohttp import web

from . import i18n
from .db import Store, User
from .helpers import (
    Meta, REMARK_HY, REMARK_XHTTP,
    email_for, gen_secrets, hy_client_dict, hy_share_link,
    sub_url_for, xhttp_client_dict, xhttp_share_link,
)
from .instructions import GUIDES, get_guide, platform_buttons
from .panel import PanelClient, PanelError

logger = logging.getLogger("x-ui-hybrid.bot")

router = Router(name="x-ui-hybrid")


# --------------------------------------------------------------------------
# Config + state
# --------------------------------------------------------------------------

@dataclass
class Config:
    bot_token: str
    admins_csv: str
    db_path: Path
    meta_path: Path
    hook_host: str
    hook_port: int

    @classmethod
    def from_env(cls) -> "Config":
        token = os.environ.get("BOT_TOKEN", "").strip()
        if not token:
            raise SystemExit("BOT_TOKEN env var is required")
        admins = os.environ.get("XUH_ADMINS", "").strip()
        if not admins:
            raise SystemExit("XUH_ADMINS env var is required (csv of Telegram usernames)")
        return cls(
            bot_token=token,
            admins_csv=admins,
            db_path=Path(os.environ.get("XUH_DB", "/var/lib/x-ui-hybrid/bot.db")),
            meta_path=Path(os.environ.get("XUH_META", "/etc/x-ui-hybrid/install.json")),
            hook_host=os.environ.get("XUH_HOOK_HOST", "127.0.0.1"),
            hook_port=int(os.environ.get("XUH_HOOK_PORT", "8765")),
        )


@dataclass
class AppCtx:
    cfg: Config
    meta: Meta
    store: Store
    panel: PanelClient
    bot: Bot


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def lang_of(user: User, fallback_code: Optional[str] = None) -> str:
    return i18n.detect(user.lang or fallback_code)


def display_name(user: User) -> str:
    if user.username:
        return f"@{user.username}"
    if user.first_name:
        return user.first_name
    return f"id={user.tg_id}"


def sub_url(meta: Meta, user: User) -> str:
    return sub_url_for(meta, user.sub_id)


# --------------------------------------------------------------------------
# Public commands
# --------------------------------------------------------------------------

@router.message(CommandStart())
async def cmd_start(msg: Message) -> None:
    ctx = _ctx(msg)
    tg = msg.from_user
    user = ctx.store.upsert_seen(
        tg.id, tg.username, tg.first_name,
        i18n.detect(tg.language_code))
    user = await maybe_promote_admin(ctx, user)

    lang = lang_of(user, tg.language_code)

    if user.status == "approved":
        await msg.answer(i18n.t("welcome.approved", lang))
        return
    if user.status == "pending":
        await msg.answer(i18n.t("welcome.pending", lang))
        return
    if user.status == "rejected":
        await msg.answer(i18n.t("welcome.rejected", lang))
        return
    if user.status == "revoked":
        await msg.answer(i18n.t("welcome.revoked", lang))
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=i18n.t("btn.request", lang),
                             callback_data="apply"),
    ]])
    await msg.answer(i18n.t("welcome.new", lang), reply_markup=kb)


@router.callback_query(F.data == "apply")
async def cb_apply(call: CallbackQuery) -> None:
    ctx = _ctx(call)
    tg = call.from_user
    user = ctx.store.upsert_seen(tg.id, tg.username, tg.first_name,
                                 i18n.detect(tg.language_code))
    lang = lang_of(user, tg.language_code)

    if user.status == "pending":
        await call.answer(i18n.t("request.again", lang), show_alert=True)
        return
    if user.status == "approved":
        await call.answer(i18n.t("welcome.approved", lang), show_alert=True)
        return

    ctx.store.request_access(user.tg_id)
    await call.answer(i18n.t("request.sent", lang))
    if call.message:
        await call.message.edit_reply_markup(reply_markup=None)
        await call.message.answer(i18n.t("request.sent", lang))

    await notify_admins_new_request(ctx, user)


async def notify_admins_new_request(ctx: AppCtx, user: User) -> None:
    when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    for admin in ctx.store.list_admins():
        body = i18n.t("admin.new_request", lang_of(admin),
                      who=display_name(user),
                      tg_id=user.tg_id, when=when)
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=i18n.t("btn.approve", lang_of(admin)),
                                 callback_data=f"approve:{user.tg_id}"),
            InlineKeyboardButton(text=i18n.t("btn.reject", lang_of(admin)),
                                 callback_data=f"reject:{user.tg_id}"),
        ]])
        try:
            await ctx.bot.send_message(admin.tg_id, body, reply_markup=kb)
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            logger.warning("notify admin %s failed: %s", admin.tg_id, e)


@router.message(Command("connect"))
async def cmd_connect(msg: Message) -> None:
    ctx = _ctx(msg)
    user = ctx.store.get(msg.from_user.id)
    lang = lang_of(user) if user else i18n.detect(msg.from_user.language_code)
    if not user or user.status != "approved":
        await msg.answer(i18n.t("denied.not_approved", lang))
        return
    body = i18n.t("connect.body", lang,
                  sub_url=sub_url(ctx.meta, user),
                  hy_link=hy_share_link(ctx.meta, user.hy_auth or ""),
                  xhttp_link=xhttp_share_link(ctx.meta, user.xhttp_uuid or ""))
    await msg.answer(body)


@router.message(Command("rotate"))
async def cmd_rotate(msg: Message) -> None:
    ctx = _ctx(msg)
    user = ctx.store.get(msg.from_user.id)
    lang = lang_of(user) if user else i18n.detect(msg.from_user.language_code)
    if not user or user.status != "approved":
        await msg.answer(i18n.t("denied.not_approved", lang))
        return
    # Revoke old, mint new, re-add.
    await delete_user_clients(ctx, user)
    _, hy_auth, xhttp_uuid = gen_secrets()
    await create_user_clients(ctx, user, hy_auth=hy_auth, xhttp_uuid=xhttp_uuid)
    ctx.store.rotate_secrets(user.tg_id, hy_auth=hy_auth, xhttp_uuid=xhttp_uuid)
    user2 = ctx.store.get(user.tg_id)
    await msg.answer(i18n.t("rotate.done", lang,
                            sub_url=sub_url(ctx.meta, user2)))  # type: ignore[arg-type]


@router.message(Command("status"))
async def cmd_status(msg: Message) -> None:
    ctx = _ctx(msg)
    user = ctx.store.get(msg.from_user.id)
    lang = lang_of(user) if user else i18n.detect(msg.from_user.language_code)
    status = (user.status if user else "new")
    await msg.answer(i18n.t("status.body", lang, status=status))


@router.message(Command("instructions"))
async def cmd_instructions(msg: Message) -> None:
    ctx = _ctx(msg)
    user = ctx.store.get(msg.from_user.id)
    lang = lang_of(user) if user else i18n.detect(msg.from_user.language_code)
    rows: List[List[InlineKeyboardButton]] = []
    for key, label in platform_buttons(lang):
        rows.append([InlineKeyboardButton(text=label, callback_data=f"plat:{key}")])
    await msg.answer("Platform / Платформа:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("plat:"))
async def cb_platform(call: CallbackQuery) -> None:
    ctx = _ctx(call)
    user = ctx.store.get(call.from_user.id)
    lang = lang_of(user) if user else i18n.detect(call.from_user.language_code)
    plat = (call.data or "").split(":", 1)[1]
    body = get_guide(plat, lang)
    if call.message:
        await call.message.answer(body, parse_mode=ParseMode.MARKDOWN)
    await call.answer()


# --------------------------------------------------------------------------
# Admin commands
# --------------------------------------------------------------------------

def _is_admin(ctx: AppCtx, tg_id: int) -> bool:
    u = ctx.store.get(tg_id)
    return bool(u and u.is_admin)


@router.message(Command("admin"))
async def cmd_admin(msg: Message) -> None:
    ctx = _ctx(msg)
    user = ctx.store.get(msg.from_user.id)
    lang = lang_of(user) if user else "en"
    if not _is_admin(ctx, msg.from_user.id):
        await msg.answer(i18n.t("denied.admin_only", lang))
        return
    await msg.answer(i18n.t("admin.menu", lang))


@router.message(Command("list"))
async def cmd_list(msg: Message) -> None:
    ctx = _ctx(msg)
    if not _is_admin(ctx, msg.from_user.id):
        await msg.answer(i18n.t("denied.admin_only",
                                lang_of(ctx.store.get(msg.from_user.id) or User(0, None, None))))
        return
    parts = (msg.text or "").split(maxsplit=1)
    status = parts[1].strip() if len(parts) > 1 else "pending"
    if status not in {"new", "pending", "approved", "rejected", "revoked"}:
        await msg.answer("statuses: new pending approved rejected revoked")
        return
    users = ctx.store.list_by_status(status)
    if not users:
        await msg.answer(i18n.t("admin.list_empty", "en"))
        return
    lines = []
    for u in users:
        when = time.strftime("%Y-%m-%d", time.gmtime(u.requested_at or 0))
        lines.append(f"<code>{u.tg_id}</code> {display_name(u)} · {when}")
    await msg.answer(f"<b>{status}</b>\n" + "\n".join(lines))


@router.message(Command("approve"))
async def cmd_approve(msg: Message) -> None:
    ctx = _ctx(msg)
    if not _is_admin(ctx, msg.from_user.id):
        return
    parts = (msg.text or "").split()
    if len(parts) < 2:
        await msg.answer("usage: /approve <tg_id>")
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        await msg.answer("usage: /approve <tg_id>")
        return
    await do_approve(ctx, target_id, by_admin=msg.from_user.id, ack_msg=msg)


@router.message(Command("revoke"))
async def cmd_revoke(msg: Message) -> None:
    ctx = _ctx(msg)
    if not _is_admin(ctx, msg.from_user.id):
        return
    parts = (msg.text or "").split()
    if len(parts) < 2:
        await msg.answer("usage: /revoke <tg_id>")
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        return
    await do_revoke(ctx, target_id, by_admin=msg.from_user.id, ack_msg=msg)


@router.callback_query(F.data.startswith("approve:"))
async def cb_approve(call: CallbackQuery) -> None:
    ctx = _ctx(call)
    if not _is_admin(ctx, call.from_user.id):
        await call.answer("admins only", show_alert=True)
        return
    target_id = int((call.data or "approve:0").split(":", 1)[1])
    await do_approve(ctx, target_id, by_admin=call.from_user.id, ack_call=call)


@router.callback_query(F.data.startswith("reject:"))
async def cb_reject(call: CallbackQuery) -> None:
    ctx = _ctx(call)
    if not _is_admin(ctx, call.from_user.id):
        await call.answer("admins only", show_alert=True)
        return
    target_id = int((call.data or "reject:0").split(":", 1)[1])
    user = ctx.store.get(target_id)
    if not user:
        await call.answer(i18n.t("admin.user_not_found",
                                 lang_of(ctx.store.get(call.from_user.id) or User(0, None, None))),
                          show_alert=True)
        return
    ctx.store.reject(target_id, by=call.from_user.id)
    try:
        await ctx.bot.send_message(target_id, i18n.t("rejected.user", lang_of(user)))
    except (TelegramBadRequest, TelegramForbiddenError):
        pass
    if call.message:
        admin = ctx.store.get(call.from_user.id)
        await call.message.edit_text(
            i18n.t("rejected.admin", lang_of(admin or User(0, None, None)),
                   tg_id=target_id))
    await call.answer()


@router.message(Command("stats"))
async def cmd_stats(msg: Message) -> None:
    ctx = _ctx(msg)
    if not _is_admin(ctx, msg.from_user.id):
        return
    counts = {s: len(ctx.store.list_by_status(s))
              for s in ("pending", "approved", "rejected", "revoked")}
    healthy = await probe_panel(ctx)
    lines = [f"panel: {'OK' if healthy else 'DOWN'}"]
    for k, v in counts.items():
        lines.append(f"{k}: {v}")
    await msg.answer("<b>stats</b>\n" + "\n".join(lines))


@router.message(Command("broadcast"))
async def cmd_broadcast(msg: Message) -> None:
    ctx = _ctx(msg)
    if not _is_admin(ctx, msg.from_user.id):
        return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("usage: /broadcast <message>")
        return
    text = parts[1]
    ok = fail = 0
    for u in ctx.store.list_by_status("approved"):
        try:
            await ctx.bot.send_message(u.tg_id, text)
            ok += 1
        except (TelegramBadRequest, TelegramForbiddenError):
            fail += 1
    admin = ctx.store.get(msg.from_user.id)
    await msg.answer(i18n.t("admin.broadcast.sent",
                            lang_of(admin or User(0, None, None)),
                            ok=ok, fail=fail))


# --------------------------------------------------------------------------
# Approve/Revoke implementation
# --------------------------------------------------------------------------

async def do_approve(ctx: AppCtx, target_id: int, *,
                     by_admin: int,
                     ack_msg: Optional[Message] = None,
                     ack_call: Optional[CallbackQuery] = None) -> None:
    user = ctx.store.get(target_id)
    if not user:
        if ack_msg:  await ack_msg.answer(i18n.t("admin.user_not_found", "en"))
        if ack_call: await ack_call.answer("not found", show_alert=True)
        return

    sub_id, hy_auth, xhttp_uuid = gen_secrets()
    try:
        await create_user_clients(ctx, user,
                                  hy_auth=hy_auth, xhttp_uuid=xhttp_uuid,
                                  sub_id=sub_id)
    except PanelError as e:
        logger.exception("approve failed for %s: %s", target_id, e)
        if ack_msg:  await ack_msg.answer(f"panel error: {e}")
        if ack_call: await ack_call.answer(f"panel error: {e}", show_alert=True)
        return

    ctx.store.approve(target_id, by=by_admin,
                      sub_id=sub_id, hy_auth=hy_auth, xhttp_uuid=xhttp_uuid)
    user = ctx.store.get(target_id)  # refresh
    assert user is not None

    try:
        await ctx.bot.send_message(
            target_id,
            i18n.t("approved.user", lang_of(user),
                   sub_url=sub_url(ctx.meta, user)))
    except (TelegramBadRequest, TelegramForbiddenError):
        pass

    admin = ctx.store.get(by_admin)
    ack_text = i18n.t("approved.admin",
                      lang_of(admin or User(0, None, None)), tg_id=target_id)
    if ack_msg:  await ack_msg.answer(ack_text)
    if ack_call:
        if ack_call.message:
            await ack_call.message.edit_text(ack_text)
        await ack_call.answer()


async def do_revoke(ctx: AppCtx, target_id: int, *,
                    by_admin: int,
                    ack_msg: Optional[Message] = None) -> None:
    user = ctx.store.get(target_id)
    if not user:
        if ack_msg:
            await ack_msg.answer(i18n.t("admin.user_not_found", "en"))
        return
    await delete_user_clients(ctx, user)
    ctx.store.revoke(target_id, by=by_admin)
    if ack_msg:
        await ack_msg.answer(f"revoked: {target_id}")
    try:
        await ctx.bot.send_message(target_id,
                                   i18n.t("welcome.revoked", lang_of(user)))
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


async def create_user_clients(ctx: AppCtx, user: User, *,
                              hy_auth: str, xhttp_uuid: str,
                              sub_id: Optional[str] = None) -> None:
    sub = sub_id or user.sub_id or secrets.token_hex(8)
    hy_in    = await ctx.panel.find_inbound(remark=REMARK_HY)
    xhttp_in = await ctx.panel.find_inbound(remark=REMARK_XHTTP)
    await ctx.panel.add_client(hy_in.inbound_id, hy_client_dict(
        email=email_for(user.tg_id, "hy"), sub_id=sub, auth=hy_auth))
    await ctx.panel.add_client(xhttp_in.inbound_id, xhttp_client_dict(
        email=email_for(user.tg_id, "xhttp"), sub_id=sub, uuid_=xhttp_uuid))


async def delete_user_clients(ctx: AppCtx, user: User) -> None:
    try:
        hy_in = await ctx.panel.find_inbound(remark=REMARK_HY)
        await ctx.panel.del_client_by_email(hy_in.inbound_id, email_for(user.tg_id, "hy"))
    except PanelError as e:
        logger.warning("delete hy client failed: %s", e)
    try:
        xhttp_in = await ctx.panel.find_inbound(remark=REMARK_XHTTP)
        await ctx.panel.del_client_by_email(xhttp_in.inbound_id, email_for(user.tg_id, "xhttp"))
    except PanelError as e:
        logger.warning("delete xhttp client failed: %s", e)


# --------------------------------------------------------------------------
# Promotion of seeded admins
# --------------------------------------------------------------------------

async def maybe_promote_admin(ctx: AppCtx, user: User) -> User:
    """If this user's username matches a seeded-admin entry, promote them."""
    if user.is_admin:
        return user
    if user.username and ctx.store.is_seeded_admin(user.username):
        ctx.store.set_admin(user.tg_id, True)
        # Auto-approve admins (so /admin works without going through the queue).
        if user.status != "approved":
            sub_id, hy_auth, xhttp_uuid = gen_secrets()
            try:
                await create_user_clients(ctx, user,
                                          hy_auth=hy_auth, xhttp_uuid=xhttp_uuid,
                                          sub_id=sub_id)
                ctx.store.approve(user.tg_id, by=user.tg_id,
                                  sub_id=sub_id, hy_auth=hy_auth, xhttp_uuid=xhttp_uuid)
            except PanelError as e:
                logger.warning("admin auto-approve failed: %s", e)
        u = ctx.store.get(user.tg_id)
        return u or user
    return user


# --------------------------------------------------------------------------
# Local hook server (healthcheck + backup)
# --------------------------------------------------------------------------

async def probe_panel(ctx: AppCtx) -> bool:
    try:
        await ctx.panel.list_inbounds()
        return True
    except Exception:
        return False


async def _hook_alert(ctx: AppCtx, request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.Response(status=400, text="bad json")
    errors = body.get("errors") or []
    text = "\n".join(f"• {e}" for e in errors) or "(no detail)"
    for admin in ctx.store.list_admins():
        try:
            await ctx.bot.send_message(
                admin.tg_id,
                i18n.t("admin.alert.health", lang_of(admin), errors=text))
        except (TelegramBadRequest, TelegramForbiddenError):
            pass
    return web.Response(text="ok")


async def _hook_upload(ctx: AppCtx, request: web.Request) -> web.Response:
    reader = await request.multipart()
    file_field = None
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "file":
            file_field = part
            break
    if file_field is None:
        return web.Response(status=400, text="no file")
    data = await file_field.read(decode=False)
    name = file_field.filename or f"backup-{int(time.time())}.tar.gz"
    ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    for admin in ctx.store.list_admins():
        try:
            await ctx.bot.send_document(
                admin.tg_id,
                BufferedInputFile(data, filename=name),
                caption=i18n.t("admin.alert.backup", lang_of(admin), ts=ts))
        except (TelegramBadRequest, TelegramForbiddenError):
            pass
    return web.Response(text="ok")


async def start_hook_server(ctx: AppCtx) -> web.AppRunner:
    app = web.Application()
    app.router.add_post("/alert",  lambda r: _hook_alert(ctx, r))
    app.router.add_post("/upload", lambda r: _hook_upload(ctx, r))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, ctx.cfg.hook_host, ctx.cfg.hook_port)
    await site.start()
    logger.info("hook server listening on %s:%s", ctx.cfg.hook_host, ctx.cfg.hook_port)
    return runner


# --------------------------------------------------------------------------
# Wire-up
# --------------------------------------------------------------------------

_CTX: Optional[AppCtx] = None


def _ctx(_: Any) -> AppCtx:
    """Module-global retrieval of AppCtx — set in main()."""
    assert _CTX is not None, "bot context not initialised"
    return _CTX


async def amain() -> None:
    global _CTX
    cfg = Config.from_env()
    meta = Meta.load(cfg.meta_path)
    store = Store(cfg.db_path)
    for u in cfg.admins_csv.split(","):
        u = u.strip().lstrip("@")
        if u:
            store.seed_admin_username(u)

    bot = Bot(cfg.bot_token,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    panel = PanelClient(meta.panel_url, meta.panel_user, meta.panel_pass)
    await panel.connect()

    _CTX = AppCtx(cfg=cfg, meta=meta, store=store, panel=panel, bot=bot)

    dp = Dispatcher()
    dp.include_router(router)

    runner = await start_hook_server(_CTX)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await runner.cleanup()
        await panel.close()
        await bot.session.close()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("XUH_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(amain())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
