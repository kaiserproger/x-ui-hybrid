"""Async client for the 3x-ui (MHSanaei) panel HTTP API.

We log in once with username/password, keep a session cookie, and call:
  POST /<base>/login
  GET  /<base>/panel/api/inbounds/list
  POST /<base>/panel/api/inbounds/addClient
  POST /<base>/panel/api/inbounds/{inbound_id}/delClientByEmail/{email}

Inbounds are referenced by their `remark` string the installer set:
  * Hysteria2: "Hysteria2 QUIC :443"
  * XHTTP:     "VLESS XHTTP :443 (TLS at nginx, unix socket)"
"""

from __future__ import annotations

import json
import ssl
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import aiohttp


@dataclass
class InboundRef:
    inbound_id: int
    protocol: str
    remark: str


class PanelError(RuntimeError):
    """Bubbled up when the panel returns success=false or HTTP error."""


class PanelClient:
    """Thin wrapper around the 3x-ui session-cookie HTTP API."""

    def __init__(self, base_url: str, username: str, password: str,
                 verify_tls: bool = False, timeout: float = 12.0):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.verify_tls = verify_tls
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None
        self._authenticated_at: float = 0.0
        # Re-authenticate every hour even if the cookie isn't expired yet —
        # cheap insurance against silent session resets.
        self._reauth_after = 3600.0

    async def __aenter__(self) -> "PanelClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def connect(self) -> None:
        if self._session is not None and not self._session.closed:
            return
        ssl_ctx: ssl.SSLContext | bool
        if self.verify_tls:
            ssl_ctx = ssl.create_default_context()
        else:
            # The installer uses 127.0.0.1:<port> with the public LE cert,
            # whose CN doesn't match 127.0.0.1 — so we skip verification.
            # The connection is loopback-only, so this is acceptable.
            ssl_ctx = False
        connector = aiohttp.TCPConnector(ssl=ssl_ctx, limit=8)
        self._session = aiohttp.ClientSession(
            connector=connector, timeout=self.timeout, raise_for_status=False)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    # ---------------- auth ----------------

    async def _ensure_login(self) -> None:
        await self.connect()
        if (time.monotonic() - self._authenticated_at) < self._reauth_after \
                and self._session and self._session.cookie_jar.filter_cookies(self.base_url):
            return
        await self._login()

    async def _login(self) -> None:
        assert self._session is not None
        url = f"{self.base_url}/login"
        data = {"username": self.username, "password": self.password}
        async with self._session.post(url, data=data) as r:
            body = await r.json(content_type=None)
        if not isinstance(body, dict) or not body.get("success"):
            raise PanelError(f"Panel login failed: {body!r}")
        self._authenticated_at = time.monotonic()

    # ---------------- inbounds ----------------

    async def list_inbounds(self) -> List[Dict[str, Any]]:
        await self._ensure_login()
        assert self._session is not None
        url = f"{self.base_url}/panel/api/inbounds/list"
        async with self._session.get(url) as r:
            body = await r.json(content_type=None)
        if not isinstance(body, dict) or not body.get("success"):
            raise PanelError(f"list inbounds failed: {body!r}")
        return list(body.get("obj") or [])

    async def find_inbound(self, *, remark: str | None = None,
                           protocol: str | None = None) -> InboundRef:
        for inb in await self.list_inbounds():
            if remark and inb.get("remark") != remark:
                continue
            if protocol and inb.get("protocol") != protocol:
                continue
            return InboundRef(
                inbound_id=int(inb["id"]),
                protocol=inb["protocol"],
                remark=inb.get("remark") or "")
        raise PanelError(f"inbound not found (remark={remark!r}, protocol={protocol!r})")

    async def add_client(self, inbound_id: int, client: Dict[str, Any]) -> None:
        """Add one client to an existing inbound.

        3x-ui's addClient endpoint takes a JSON `settings` payload with shape
        {"clients": [<one client dict>]}. We wrap accordingly.
        """
        await self._ensure_login()
        assert self._session is not None
        settings_blob = json.dumps({"clients": [client]}, separators=(",", ":"))
        url = f"{self.base_url}/panel/api/inbounds/addClient"
        async with self._session.post(
                url, data={"id": str(inbound_id), "settings": settings_blob}) as r:
            body = await r.json(content_type=None)
        if not isinstance(body, dict) or not body.get("success"):
            raise PanelError(f"addClient failed: {body!r}")

    async def del_client_by_email(self, inbound_id: int, email: str) -> None:
        await self._ensure_login()
        assert self._session is not None
        url = f"{self.base_url}/panel/api/inbounds/{inbound_id}/delClientByEmail/{email}"
        async with self._session.post(url) as r:
            body = await r.json(content_type=None)
        if not isinstance(body, dict) or not body.get("success"):
            # Treat "client not found" as a soft success — we can call this
            # idempotently from /revoke and /rotate.
            msg = (body.get("msg") or "") if isinstance(body, dict) else ""
            if "not found" not in msg.lower():
                raise PanelError(f"delClientByEmail failed: {body!r}")
