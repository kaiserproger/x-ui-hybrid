"""SQLite-backed user store for the x-ui-hybrid Telegram bot.

Single-table model. Sync sqlite3 — the bot's traffic is low and a real DB
would be overkill. Each method opens-and-closes a short-lived connection
so we don't have to worry about cross-thread sharing.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id          INTEGER PRIMARY KEY,
    username       TEXT,
    first_name     TEXT,
    status         TEXT NOT NULL DEFAULT 'new',
        -- 'new' | 'pending' | 'approved' | 'rejected' | 'revoked'
    sub_id         TEXT,             -- 3x-ui client subId, shared across inbounds
    hy_auth        TEXT,             -- hysteria2 auth secret
    xhttp_uuid     TEXT,             -- VLESS+XHTTP UUID
    note           TEXT,             -- admin note
    requested_at   INTEGER,          -- unix seconds
    decided_at     INTEGER,
    decided_by     INTEGER,          -- admin tg_id
    is_admin       INTEGER NOT NULL DEFAULT 0,
    lang           TEXT              -- 'ru' | 'en' (cached from telegram language_code)
);

CREATE INDEX IF NOT EXISTS users_status_idx ON users(status);
CREATE INDEX IF NOT EXISTS users_username_idx ON users(username);
"""


@dataclass
class User:
    tg_id: int
    username: Optional[str]
    first_name: Optional[str]
    status: str = "new"
    sub_id: Optional[str] = None
    hy_auth: Optional[str] = None
    xhttp_uuid: Optional[str] = None
    note: Optional[str] = None
    requested_at: Optional[int] = None
    decided_at: Optional[int] = None
    decided_by: Optional[int] = None
    is_admin: bool = False
    lang: Optional[str] = None


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, isolation_level=None)  # autocommit
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # ---- helpers ----

    @staticmethod
    def _row_to_user(row: sqlite3.Row | None) -> Optional[User]:
        if row is None:
            return None
        return User(
            tg_id=row["tg_id"],
            username=row["username"],
            first_name=row["first_name"],
            status=row["status"],
            sub_id=row["sub_id"],
            hy_auth=row["hy_auth"],
            xhttp_uuid=row["xhttp_uuid"],
            note=row["note"],
            requested_at=row["requested_at"],
            decided_at=row["decided_at"],
            decided_by=row["decided_by"],
            is_admin=bool(row["is_admin"]),
            lang=row["lang"],
        )

    # ---- reads ----

    def get(self, tg_id: int) -> Optional[User]:
        with self._conn() as c:
            return self._row_to_user(c.execute(
                "SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone())

    def by_username(self, username: str) -> Optional[User]:
        with self._conn() as c:
            return self._row_to_user(c.execute(
                "SELECT * FROM users WHERE LOWER(username)=LOWER(?)",
                (username,)).fetchone())

    def list_by_status(self, status: str) -> List[User]:
        with self._conn() as c:
            return [self._row_to_user(r) for r in c.execute(  # type: ignore[misc]
                "SELECT * FROM users WHERE status=? ORDER BY requested_at DESC",
                (status,)).fetchall()]

    def list_admins(self) -> List[User]:
        with self._conn() as c:
            return [self._row_to_user(r) for r in c.execute(  # type: ignore[misc]
                "SELECT * FROM users WHERE is_admin=1").fetchall()]

    # ---- writes ----

    def upsert_seen(self, tg_id: int, username: Optional[str],
                    first_name: Optional[str], lang: Optional[str]) -> User:
        """Record (or refresh) a user's identity on /start. Does not touch status."""
        with self._conn() as c:
            c.execute("""
                INSERT INTO users (tg_id, username, first_name, lang)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tg_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    lang = excluded.lang
            """, (tg_id, username, first_name, lang))
        u = self.get(tg_id)
        assert u is not None
        return u

    def request_access(self, tg_id: int) -> None:
        with self._conn() as c:
            c.execute("""
                UPDATE users SET status='pending', requested_at=?
                 WHERE tg_id=? AND status IN ('new','rejected','revoked')
            """, (int(time.time()), tg_id))

    def approve(self, tg_id: int, *, by: int,
                sub_id: str, hy_auth: str, xhttp_uuid: str) -> None:
        with self._conn() as c:
            c.execute("""
                UPDATE users SET status='approved',
                                  sub_id=?, hy_auth=?, xhttp_uuid=?,
                                  decided_at=?, decided_by=?
                 WHERE tg_id=?
            """, (sub_id, hy_auth, xhttp_uuid, int(time.time()), by, tg_id))

    def reject(self, tg_id: int, *, by: int, note: Optional[str] = None) -> None:
        with self._conn() as c:
            c.execute("""
                UPDATE users SET status='rejected',
                                  note=?, decided_at=?, decided_by=?
                 WHERE tg_id=?
            """, (note, int(time.time()), by, tg_id))

    def revoke(self, tg_id: int, *, by: int) -> None:
        with self._conn() as c:
            c.execute("""
                UPDATE users SET status='revoked',
                                  decided_at=?, decided_by=?
                 WHERE tg_id=?
            """, (int(time.time()), by, tg_id))

    def rotate_secrets(self, tg_id: int, *, hy_auth: str, xhttp_uuid: str) -> None:
        with self._conn() as c:
            c.execute("""UPDATE users SET hy_auth=?, xhttp_uuid=? WHERE tg_id=?""",
                      (hy_auth, xhttp_uuid, tg_id))

    def set_admin(self, tg_id: int, is_admin: bool) -> None:
        with self._conn() as c:
            c.execute("UPDATE users SET is_admin=? WHERE tg_id=?",
                      (1 if is_admin else 0, tg_id))

    # ---- bootstrap from username allow-list ----

    def seed_admin_username(self, username: str) -> None:
        """Insert a placeholder row for an admin we haven't seen yet (no tg_id).

        We can't do that with PRIMARY KEY = tg_id. Instead we track desired
        usernames in a side table and promote on first contact.
        """
        with self._conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS admin_seeds (
                    username TEXT PRIMARY KEY COLLATE NOCASE
                )
            """)
            c.execute("INSERT OR IGNORE INTO admin_seeds(username) VALUES(?)", (username,))

    def is_seeded_admin(self, username: Optional[str]) -> bool:
        if not username:
            return False
        with self._conn() as c:
            try:
                row = c.execute(
                    "SELECT 1 FROM admin_seeds WHERE username=? COLLATE NOCASE",
                    (username,)).fetchone()
            except sqlite3.OperationalError:
                return False
        return row is not None
