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
                CREATE TABLE IF NOT EXISTS starter_profiles (
                    profile TEXT PRIMARY KEY REFERENCES profiles(name),
                    version INTEGER NOT NULL CHECK(version >= 0)
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
                      server_id: str | None = None, public_id: str | None = None, *,
                      starter_version: int | None = None) -> None:
        """Replace a local snapshot and supplied identities in one transaction.

        Existing sessions are invalidated so clients log in with the imported
        identity and reload state. Other profiles and sessions are unaffected.
        The default records an explicit import marker (version zero), preventing
        an imported snapshot from being mistaken for an older local starter.
        Only a known starter creator should supply a positive starter version.
        """
        if not isinstance(payload, bytes):
            raise ValueError("Snapshot payload must be protobuf bytes")
        if not isinstance(schema_sha256, str) or not schema_sha256:
            raise ValueError("Snapshot schema fingerprint is required")
        if any(value is not None and not isinstance(value, str) for value in (server_id, public_id)):
            raise ValueError("Profile identities must be strings")
        if starter_version is not None and (type(starter_version) is not int or starter_version < 0):
            raise ValueError("Starter version must be a nonnegative integer")
        origin_version = 0 if starter_version is None else starter_version
        with self.connect() as db:
            self._ensure_profile(db, profile)
            db.execute("UPDATE profiles SET server_id=COALESCE(?,server_id), public_id=COALESCE(?,public_id) WHERE name=?",
                       (server_id, public_id, profile))
            db.execute("INSERT INTO snapshots(profile,response,schema_sha256) VALUES (?,?,?) "
                       "ON CONFLICT(profile) DO UPDATE SET response=excluded.response,schema_sha256=excluded.schema_sha256",
                       (profile, payload, schema_sha256))
            db.execute("INSERT INTO starter_profiles(profile,version) VALUES (?,?) "
                       "ON CONFLICT(profile) DO UPDATE SET version=excluded.version", (profile, origin_version))
            db.execute("DELETE FROM sessions WHERE profile=?", (profile,))

    def snapshot(self, profile: str) -> tuple[bytes, str] | None:
        with self.connect() as db:
            row = db.execute("SELECT response,schema_sha256 FROM snapshots WHERE profile=?", (profile,)).fetchone()
            return (bytes(row["response"]), row["schema_sha256"]) if row is not None else None

    def settings(self, profile: str) -> tuple[bytes, str] | None:
        with self.connect() as db:
            row = db.execute("SELECT response,schema_sha256 FROM profile_settings WHERE profile=?", (profile,)).fetchone()
            return (bytes(row["response"]), row["schema_sha256"]) if row is not None else None

    def starter_version(self, profile: str) -> int | None:
        """Return zero for an explicit import, positive for a known starter.

        A missing row returns ``None`` for a database created before provenance
        was recorded. It does not establish that the snapshot was a starter;
        migration callers must separately recognize an exact legacy shape.
        """
        with self.connect() as db:
            row = db.execute("SELECT version FROM starter_profiles WHERE profile=?", (profile,)).fetchone()
            return int(row["version"]) if row is not None else None

    def mutate_starter_snapshot(self, profile: str, schema_sha256: str, callback) -> bytes | None:
        """Atomically migrate a starter snapshot and its provenance together.

        ``callback(payload, version)`` sees the original bytes and the marker
        returned by ``starter_version``. It returns ``None`` to preserve both,
        or ``(new_bytes, positive_version)``. It owns deciding which known
        starter/legacy shapes are eligible; explicit imports have version zero.
        Sessions, identities and settings are preserved. Only a changed
        snapshot or marker returns bytes; failures roll back the transaction.
        """
        if not isinstance(schema_sha256, str) or not schema_sha256:
            raise ValueError("Snapshot schema fingerprint is required")
        if not callable(callback):
            raise ValueError("Starter migration callback must be callable")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT s.response,s.schema_sha256,o.version FROM snapshots AS s "
                "LEFT JOIN starter_profiles AS o ON o.profile=s.profile WHERE s.profile=?", (profile,)
            ).fetchone()
            if row is None:
                raise ValueError("Local profile has no snapshot")
            if row["schema_sha256"] != schema_sha256:
                raise ValueError("Local profile snapshot uses a different schema")
            original = bytes(row["response"])
            version = int(row["version"]) if row["version"] is not None else None
            result = callback(original, version)
            if result is None:
                return None
            if not isinstance(result, tuple) or len(result) != 2:
                raise ValueError("Starter migration must return bytes and a positive version")
            payload, new_version = result
            if (not isinstance(payload, bytes) or type(new_version) is not int or new_version <= 0
                    or (version is not None and new_version < version)):
                raise ValueError("Starter migration must return bytes and a nondecreasing positive version")
            if payload == original and new_version == version:
                return None
            db.execute("UPDATE snapshots SET response=? WHERE profile=?", (payload, profile))
            db.execute("INSERT INTO starter_profiles(profile,version) VALUES (?,?) "
                       "ON CONFLICT(profile) DO UPDATE SET version=excluded.version", (profile, new_version))
        return payload

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
