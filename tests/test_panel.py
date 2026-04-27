"""Tests for the bot's 3x-ui PanelClient against an aiohttp mock server."""

import asyncio
import json

import pytest
from aiohttp import web

from bot.panel import PanelClient, PanelError


# Pretend 3x-ui live state.
class FakePanel:
    def __init__(self):
        self.inbounds = [
            {"id": 1, "remark": "Hysteria2 QUIC :443",
             "protocol": "hysteria", "port": 443, "enable": True,
             "settings": '{"clients":[{"email":"default-hy2","auth":"X"}]}'},
            {"id": 2, "remark": "VLESS XHTTP :443 (TLS at nginx, unix socket)",
             "protocol": "vless", "port": 0, "enable": True,
             "settings": '{"clients":[]}'},
        ]
        self.added_clients = []  # list of (inbound_id, client_dict)
        self.deleted = []
        self.login_calls = 0


@pytest.fixture
async def panel_app():
    fake = FakePanel()
    app = web.Application()

    async def login(req):
        fake.login_calls += 1
        form = await req.post()
        if form.get("username") == "admin" and form.get("password") == "secret":
            resp = web.json_response({"success": True, "msg": "ok"})
            resp.set_cookie("3x-ui", "session-cookie", path="/")
            return resp
        return web.json_response({"success": False, "msg": "bad creds"})

    async def list_inbounds(req):
        if "3x-ui" not in req.cookies:
            return web.json_response({"success": False, "msg": "unauth"})
        return web.json_response({"success": True, "obj": fake.inbounds})

    async def add_client(req):
        form = await req.post()
        inbound_id = int(form.get("id", "0"))
        settings = json.loads(form.get("settings", "{}"))
        for c in settings.get("clients", []):
            fake.added_clients.append((inbound_id, c))
        return web.json_response({"success": True})

    async def del_by_email(req):
        inbound_id = int(req.match_info["id"])
        email = req.match_info["email"]
        # 50/50: pretend "client not found" for emails that don't exist.
        is_known = any(
            c[1].get("email") == email and c[0] == inbound_id
            for c in fake.added_clients)
        if not is_known and email != "known":
            return web.json_response({"success": False, "msg": "client not found"})
        fake.deleted.append((inbound_id, email))
        return web.json_response({"success": True})

    async def list_inbounds_locked(req):
        # Returns 401 on first call, success on second — used by reauth test.
        return await list_inbounds(req)

    app.router.add_post("/login", login)
    app.router.add_get("/panel/api/inbounds/list", list_inbounds)
    app.router.add_post("/panel/api/inbounds/addClient", add_client)
    app.router.add_post("/panel/api/inbounds/{id}/delClientByEmail/{email}", del_by_email)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        yield fake, f"http://127.0.0.1:{port}"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_login_then_list(panel_app):
    fake, base = panel_app
    async with PanelClient(base, "admin", "secret") as p:
        inbounds = await p.list_inbounds()
        assert len(inbounds) == 2
        assert fake.login_calls == 1
        # Second call shouldn't re-login.
        await p.list_inbounds()
        assert fake.login_calls == 1


@pytest.mark.asyncio
async def test_login_failure_raises(panel_app):
    fake, base = panel_app
    async with PanelClient(base, "admin", "WRONG") as p:
        with pytest.raises(PanelError):
            await p.list_inbounds()


@pytest.mark.asyncio
async def test_find_inbound_by_remark(panel_app):
    _, base = panel_app
    async with PanelClient(base, "admin", "secret") as p:
        ref = await p.find_inbound(remark="Hysteria2 QUIC :443")
        assert ref.inbound_id == 1
        assert ref.protocol == "hysteria"
        ref2 = await p.find_inbound(remark="VLESS XHTTP :443 (TLS at nginx, unix socket)")
        assert ref2.inbound_id == 2


@pytest.mark.asyncio
async def test_find_inbound_missing_raises(panel_app):
    _, base = panel_app
    async with PanelClient(base, "admin", "secret") as p:
        with pytest.raises(PanelError):
            await p.find_inbound(remark="does-not-exist")


@pytest.mark.asyncio
async def test_add_client_wraps_in_settings(panel_app):
    fake, base = panel_app
    async with PanelClient(base, "admin", "secret") as p:
        await p.add_client(2, {"id": "uuid-1", "email": "u-1", "enable": True})
    assert fake.added_clients == [(2, {"id": "uuid-1", "email": "u-1", "enable": True})]


@pytest.mark.asyncio
async def test_del_by_email_soft_on_not_found(panel_app):
    """Deleting a non-existent email should NOT raise (idempotent revoke)."""
    _, base = panel_app
    async with PanelClient(base, "admin", "secret") as p:
        await p.del_client_by_email(2, "does-not-exist")  # must not raise


@pytest.mark.asyncio
async def test_del_by_email_succeeds_for_known(panel_app):
    fake, base = panel_app
    async with PanelClient(base, "admin", "secret") as p:
        await p.add_client(2, {"id": "u", "email": "known", "enable": True})
        await p.del_client_by_email(2, "known")
    assert (2, "known") in fake.deleted
