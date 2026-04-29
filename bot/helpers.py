"""Pure helpers for the bot — no Telegram, no network, no aiogram imports.

Lives in its own module so the test suite can exercise it without aiogram
installed in the test environment.
"""

from __future__ import annotations

import json
import secrets
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib.parse import quote


# Inbound remarks the installer creates. Used to look up inbound IDs at runtime.
REMARK_HY    = "Hysteria2 QUIC :443"
REMARK_HY_GAME = "Hysteria2 QUIC :19132 (game UDP)"
REMARK_XHTTP = "VLESS XHTTP :443 (TLS at nginx, unix socket)"


@dataclass
class Meta:
    domain: str
    panel_url: str
    panel_user: str
    panel_pass: str
    sub_public_url: str
    xhttp_path: str
    xhttp_padding_header: str
    xhttp_padding_key: str
    cert_fullchain: str
    hy_obfs_password: str = ""
    hy_game_port: int | None = None

    @classmethod
    def load(cls, path: Path) -> "Meta":
        data = json.loads(Path(path).read_text())
        panel = data["panel"]
        hy_game_port = data.get("hysteria2", {}).get("game_port")
        return cls(
            domain=data["domain"],
            panel_url=f"https://{panel['host']}:{panel['port']}{panel['path']}".rstrip("/"),
            panel_user=panel["user"],
            panel_pass=panel["pass"],
            sub_public_url=data["subscription"]["public_url"],
            xhttp_path=data["xhttp"]["path"].strip("/"),
            xhttp_padding_header=data["xhttp"]["padding_header"],
            xhttp_padding_key=data["xhttp"]["padding_key"],
            cert_fullchain=data["cert"]["fullchain"],
            hy_obfs_password=data.get("hysteria2", {}).get("obfs_password", ""),
            hy_game_port=int(hy_game_port) if hy_game_port else None,
        )


def gen_secrets() -> Tuple[str, str, str]:
    """Generate (sub_id 16hex, hy_auth 32hex, xhttp_uuid)."""
    return secrets.token_hex(8), secrets.token_hex(16), str(uuid.uuid4())


def email_for(tg_id: int, kind: str) -> str:
    """Stable email tag tying a 3x-ui client to a Telegram user."""
    return f"{kind}-tg-{tg_id}"


def sub_url_for(meta: Meta, sub_id: str | None) -> str:
    if not sub_id:
        return "—"
    return f"{meta.sub_public_url.rstrip('/')}/{sub_id}"


def hy_share_link(meta: Meta, auth: str, remark: str = REMARK_HY, port: int = 443) -> str:
    query = f"sni={meta.domain}&alpn=h3"
    if meta.hy_obfs_password:
        obfs_password = quote(meta.hy_obfs_password, safe="")
        query += f"&obfs=salamander&obfs-password={obfs_password}"
    return f"hysteria2://{auth}@{meta.domain}:{port}/?{query}#{quote(remark)}"


def xhttp_share_link(meta: Meta, uuid_: str, remark: str = REMARK_XHTTP) -> str:
    path_enc = quote("/" + meta.xhttp_path + "/", safe="")
    return ("vless://"
            f"{uuid_}@{meta.domain}:443"
            "?encryption=none&security=tls"
            f"&sni={meta.domain}&alpn=h2%2Chttp%2F1.1&fp=chrome"
            "&type=xhttp"
            f"&host={meta.domain}&path={path_enc}"
            "&mode=auto"
            f"#{quote(remark)}")


def hy_client_dict(*, email: str, sub_id: str, auth: str) -> Dict[str, Any]:
    return {"auth": auth, "email": email, "limitIp": 0, "totalGB": 0,
            "expiryTime": 0, "enable": True, "tgId": "",
            "subId": sub_id, "comment": "bot", "reset": 0}


def xhttp_client_dict(*, email: str, sub_id: str, uuid_: str) -> Dict[str, Any]:
    return {"id": uuid_, "email": email, "flow": "", "limitIp": 0,
            "totalGB": 0, "expiryTime": 0, "enable": True, "tgId": "",
            "subId": sub_id, "comment": "bot", "reset": 0}
