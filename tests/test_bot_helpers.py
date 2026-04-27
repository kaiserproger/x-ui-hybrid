"""Pure-function tests for bot helpers (no network, no Telegram)."""

from urllib.parse import parse_qs, unquote, urlparse

import pytest

from bot import i18n
from bot.helpers import (
    REMARK_HY,
    REMARK_XHTTP,
    Meta,
    email_for,
    gen_secrets,
    hy_client_dict,
    hy_share_link,
    sub_url_for as sub_url,
    xhttp_client_dict,
    xhttp_share_link,
)
from bot.db import User
from bot.instructions import GUIDES, get_guide, platform_buttons


def make_meta() -> Meta:
    return Meta(
        domain="vpn.example.org",
        panel_url="https://127.0.0.1:31000/p",
        panel_user="admin",
        panel_pass="x",
        sub_public_url="https://vpn.example.org/sub-prefix/",
        xhttp_path="abc123",
        xhttp_padding_header="X-Trace-Id",
        xhttp_padding_key="deadbeef",
        cert_fullchain="/etc/ssl/v.pem",
    )


# ---- i18n -------------------------------------------------------------------

def test_i18n_detect():
    assert i18n.detect("ru") == "ru"
    assert i18n.detect("ru-RU") == "ru"
    assert i18n.detect("en-US") == "en"
    assert i18n.detect(None) == "en"
    assert i18n.detect("") == "en"


def test_i18n_t_format():
    assert "Привет" in i18n.t("welcome.new", "ru")
    assert i18n.t("welcome.new", "ru") != i18n.t("welcome.new", "en")
    out = i18n.t("admin.new_request", "en", who="@u", tg_id=42, when="now")
    assert "42" in out and "@u" in out and "now" in out


def test_i18n_falls_back_to_en():
    assert i18n.t("connect.body", "fr", sub_url="x", hy_link="y", xhttp_link="z")
    # Unknown key — return key (debugging aid, not crash).
    assert i18n.t("does.not.exist", "en") == "does.not.exist"


# ---- bot.bot pure functions -------------------------------------------------

def test_gen_secrets_distinct():
    a = gen_secrets()
    b = gen_secrets()
    assert a != b
    assert len(a[0]) == 16  # sub_id hex
    assert len(a[1]) == 32  # hy_auth hex
    # uuid string
    assert len(a[2]) == 36 and a[2].count("-") == 4


def test_email_for():
    assert email_for(123, "hy") == "hy-tg-123"
    assert email_for(123, "xhttp") == "xhttp-tg-123"


def test_sub_url_uses_user_sub_id():
    meta = make_meta()
    user = User(tg_id=1, username="u", first_name="U",
                status="approved", sub_id="abcd1234")
    assert sub_url(meta, user.sub_id) == "https://vpn.example.org/sub-prefix/abcd1234"


def test_sub_url_handles_missing():
    meta = make_meta()
    user = User(tg_id=1, username=None, first_name=None)
    assert sub_url(meta, user.sub_id) == "—"


def test_hy_share_link_format():
    meta = make_meta()
    link = hy_share_link(meta, "AUTH123")
    p = urlparse(link)
    assert p.scheme == "hysteria2"
    assert p.username == "AUTH123"
    assert p.hostname == "vpn.example.org"
    assert p.port == 443
    q = parse_qs(p.query)
    assert q["sni"] == ["vpn.example.org"]
    assert q["alpn"] == ["h3"]
    assert unquote(p.fragment) == REMARK_HY


def test_xhttp_share_link_carries_path():
    meta = make_meta()
    link = xhttp_share_link(meta, "11111111-2222-3333-4444-555555555555")
    p = urlparse(link)
    assert p.scheme == "vless"
    q = parse_qs(p.query)
    assert q["security"] == ["tls"]
    assert q["type"] == ["xhttp"]
    assert q["host"] == ["vpn.example.org"]
    assert q["mode"] == ["auto"]
    # Path should round-trip through encoding to '/abc123/'.
    assert unquote(q["path"][0]) == "/abc123/"
    assert "h2" in q["alpn"][0]
    assert unquote(p.fragment) == REMARK_XHTTP


def test_hy_client_dict_minimal():
    c = hy_client_dict(email="hy-tg-1", sub_id="s", auth="a")
    # Required keys for a 3x-ui hysteria client row.
    for k in ("auth", "email", "limitIp", "totalGB", "expiryTime", "enable", "subId"):
        assert k in c
    assert c["auth"] == "a"
    assert c["enable"] is True


def test_xhttp_client_dict_uses_id_field():
    c = xhttp_client_dict(email="x-tg-1", sub_id="s", uuid_="u")
    assert c["id"] == "u"  # VLESS clients use 'id', not 'auth'
    assert c["enable"] is True


# ---- instructions -----------------------------------------------------------

def test_all_platforms_have_both_languages():
    for plat_key, _, _ in [(p[0], p[1], p[2]) for p in [
        ("ios", None, None), ("android", None, None), ("windows", None, None),
        ("macos", None, None), ("linux", None, None)]]:
        assert plat_key in GUIDES
        assert "ru" in GUIDES[plat_key] and "en" in GUIDES[plat_key]
        assert len(GUIDES[plat_key]["ru"]) > 200
        assert len(GUIDES[plat_key]["en"]) > 200


def test_get_guide_falls_back_to_en():
    assert get_guide("ios", "fr") == GUIDES["ios"]["en"]
    assert get_guide("ios", "ru") == GUIDES["ios"]["ru"]
    assert get_guide("does-not-exist", "en") == "—"


def test_platform_buttons_use_lang():
    ru = dict(platform_buttons("ru"))
    en = dict(platform_buttons("en"))
    assert "ios" in ru and "ios" in en
    # iOS label is the same emoji+text in both for these platforms,
    # but guarantee the function returns five entries either way.
    assert len(ru) == 5
    assert len(en) == 5
