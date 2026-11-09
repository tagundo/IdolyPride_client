"""Persist local profiles and opaque local sessions, never Firebase credentials."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class State:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS profiles (
                    name TEXT PRIMARY KEY,
                    server_id TEXT NOT NULL,
                    public_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    profile TEXT NOT NULL REFERENCES profiles(name),
                    expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    profile TEXT PRIMARY KEY REFERENCES profiles(name),
                    response BLOB NOT NULL,
                    schema_sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS profile_settings (
                    profile TEXT PRIMARY KEY REFERENCES profiles(name),
                    response BLOB NOT NULL,
                    schema_sha256 TEXT NOT NULL
                );
            """)
        path.chmod(0o600)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def login(self, profile: str) -> tuple[str, dict]:
        now = int(time.time())
        token = "local-" + secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires_at<=?", (now,))
            row = self._ensure_profile(db, profile)
            db.execute("INSERT INTO sessions VALUES (?,?,?)", (token_hash, profile, now + 86400 * 30))
        return token, row

    @staticmethod
    def _ensure_profile(db, profile: str) -> dict:
        db.execute("INSERT OR IGNORE INTO profiles VALUES (?,?,?)", (
            profile, str(uuid.uuid4()), "".join(secrets.choice("0123456789") for _ in range(12)),
        ))
        return dict(db.execute("SELECT * FROM profiles WHERE name=?", (profile,)).fetchone())

    def ensure_profile(self, profile: str) -> dict:
        """Return an existing local identity or create one without a session."""
        with self.connect() as db:
            return self._ensure_profile(db, profile)

    def profile(self, profile: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM profiles WHERE name=?", (profile,)).fetchone()
            return dict(row) if row is not None else None

    def save_snapshot(self, profile: str, payload: bytes, schema_sha256: str,
                      server_id: str | None = None, public_id: str | None = None) -> None:
        """Replace a local snapshot and supplied identities in one transaction.

        Existing sessions are invalidated so clients log in with the imported
        identity and reload state. Other profiles and sessions are unaffected.
        """
        if not isinstance(payload, bytes):
            raise ValueError("Snapshot payload must be protobuf bytes")
        if not isinstance(schema_sha256, str) or not schema_sha256:
            raise ValueError("Snapshot schema fingerprint is required")
        if any(value is not None and not isinstance(value, str) for value in (server_id, public_id)):
            raise ValueError("Profile identities must be strings")
        with self.connect() as db:
            self._ensure_profile(db, profile)
            db.execute("UPDATE profiles SET server_id=COALESCE(?,server_id), public_id=COALESCE(?,public_id) WHERE name=?",
                       (server_id, public_id, profile))
            db.execute("INSERT INTO snapshots(profile,response,schema_sha256) VALUES (?,?,?) "
                       "ON CONFLICT(profile) DO UPDATE SET response=excluded.response,schema_sha256=excluded.schema_sha256",
                       (profile, payload, schema_sha256))
            db.execute("DELETE FROM sessions WHERE profile=?", (profile,))

    def snapshot(self, profile: str) -> tuple[bytes, str] | None:
        with self.connect() as db:
            row = db.execute("SELECT response,schema_sha256 FROM snapshots WHERE profile=?", (profile,)).fetchone()
            return (bytes(row["response"]), row["schema_sha256"]) if row is not None else None

    def settings(self, profile: str) -> tuple[bytes, str] | None:
        with self.connect() as db:
            row = db.execute("SELECT response,schema_sha256 FROM profile_settings WHERE profile=?", (profile,)).fetchone()
            return (bytes(row["response"]), row["schema_sha256"]) if row is not None else None

    def mutate_snapshot(self, profile: str, schema_sha256: str, callback, *, setting_info: bytes | None = None) -> bytes:
        """Apply a game action atomically, preserving the active local session.

        Import deliberately invalidates sessions; ordinary game updates do not.
        Callback or settings failures roll back the entire action.
        """
        if setting_info is not None and not isinstance(setting_info, bytes):
            raise ValueError("Settings must be protobuf bytes")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT response,schema_sha256 FROM snapshots WHERE profile=?", (profile,)).fetchone()
            if row is None:
                raise ValueError("Local profile has no snapshot")
            if row["schema_sha256"] != schema_sha256:
                raise ValueError("Local profile snapshot uses a different schema")
            payload = callback(bytes(row["response"]))
            if not isinstance(payload, bytes):
                raise ValueError("Snapshot mutation must return protobuf bytes")
            db.execute("UPDATE snapshots SET response=? WHERE profile=?", (payload, profile))
            if setting_info is not None:
                db.execute("INSERT INTO profile_settings VALUES (?,?,?) ON CONFLICT(profile) DO UPDATE SET "
                           "response=excluded.response,schema_sha256=excluded.schema_sha256",
                           (profile, setting_info, schema_sha256))
        return payload

    def authenticated(self, token: str, profile: str) -> bool:
        if not token:
            return False
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            return db.execute("SELECT 1 FROM sessions WHERE token_hash=? AND profile=? AND expires_at>?", (
                token_hash, profile, int(time.time()),
            )).fetchone() is not None
