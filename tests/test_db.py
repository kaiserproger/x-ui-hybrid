"""Unit tests for the bot's sqlite Store."""

from pathlib import Path

import pytest

from bot.db import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "bot.db")


def test_upsert_and_get(store):
    u = store.upsert_seen(101, "alice", "Alice", "ru")
    assert u.tg_id == 101
    assert u.username == "alice"
    assert u.first_name == "Alice"
    assert u.lang == "ru"
    assert u.status == "new"
    assert not u.is_admin

    # upsert again with refreshed username
    u2 = store.upsert_seen(101, "alice2", "Alice II", "en")
    assert u2.username == "alice2"
    assert u2.lang == "en"
    assert u2.status == "new"  # status preserved


def test_request_access_transitions(store):
    store.upsert_seen(1, None, None, None)
    store.request_access(1)
    assert store.get(1).status == "pending"

    # Re-requesting from pending is a no-op (only new/rejected/revoked move).
    store.request_access(1)
    assert store.get(1).status == "pending"


def test_approve_then_revoke(store):
    store.upsert_seen(2, "u2", "U2", None)
    store.request_access(2)
    store.approve(2, by=999, sub_id="s2", hy_auth="h2", xhttp_uuid="x2")
    u = store.get(2)
    assert u.status == "approved"
    assert (u.sub_id, u.hy_auth, u.xhttp_uuid) == ("s2", "h2", "x2")
    assert u.decided_by == 999

    store.revoke(2, by=999)
    u = store.get(2)
    assert u.status == "revoked"


def test_reject(store):
    store.upsert_seen(3, "u3", "U3", None)
    store.request_access(3)
    store.reject(3, by=999, note="spam")
    u = store.get(3)
    assert u.status == "rejected"
    assert u.note == "spam"


def test_rotate_secrets(store):
    store.upsert_seen(4, "u4", "U4", None)
    store.approve(4, by=1, sub_id="s", hy_auth="h_old", xhttp_uuid="x_old")
    store.rotate_secrets(4, hy_auth="h_new", xhttp_uuid="x_new")
    u = store.get(4)
    assert u.hy_auth == "h_new"
    assert u.xhttp_uuid == "x_new"
    assert u.sub_id == "s"  # sub_id stays


def test_admin_seed_and_promotion(store):
    store.seed_admin_username("kaiserroman")
    assert store.is_seeded_admin("kaiserroman")
    assert store.is_seeded_admin("KAISERROMAN")  # case-insensitive
    assert not store.is_seeded_admin("randomuser")
    assert not store.is_seeded_admin(None)
    assert not store.is_seeded_admin("")

    store.upsert_seen(50, "kaiserroman", "K", "ru")
    store.set_admin(50, True)
    assert store.get(50).is_admin

    admins = store.list_admins()
    assert any(a.tg_id == 50 for a in admins)


def test_list_by_status(store):
    for i in range(5):
        store.upsert_seen(100 + i, f"u{i}", f"U{i}", None)
        store.request_access(100 + i)
    store.approve(101, by=1, sub_id="a", hy_auth="b", xhttp_uuid="c")
    pending = store.list_by_status("pending")
    approved = store.list_by_status("approved")
    assert len(pending) == 4
    assert len(approved) == 1


def test_by_username_case_insensitive(store):
    store.upsert_seen(7, "MixedCase", "M", None)
    assert store.by_username("mixedcase").tg_id == 7
    assert store.by_username("MIXEDCASE").tg_id == 7
    assert store.by_username("nope") is None
