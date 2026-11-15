"""Persist local profiles and opaque local sessions, never Firebase credentials."""

from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class AttemptConflict(ValueError):
    """A request identity was already used for different live input."""


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
                CREATE TABLE IF NOT EXISTS profile_lesson_progress (
                    profile TEXT PRIMARY KEY REFERENCES profiles(name),
                    response BLOB NOT NULL,
                    schema_sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS preference_receipts (
                    profile TEXT NOT NULL REFERENCES profiles(name),
                    path TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    schema_sha256 TEXT NOT NULL,
                    response BLOB NOT NULL,
                    PRIMARY KEY(profile, path, request_id)
                );
                CREATE TABLE IF NOT EXISTS main_live_attempts (
                    profile TEXT NOT NULL REFERENCES profiles(name),
                    request_id TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    path TEXT NOT NULL,
                    schema_sha256 TEXT NOT NULL,
                    master_version TEXT NOT NULL,
                    ruleset TEXT NOT NULL,
                    seed TEXT NOT NULL,
                    started_time INTEGER NOT NULL,
                    response BLOB NOT NULL,
                    PRIMARY KEY(profile, request_id)
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
        identity and reload state. The profile's local lesson clock is reset;
        an imported account never inherits the previous snapshot's earnings.
        Other profiles and sessions are unaffected.
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
            # A replacement/import starts a new local earning timeline. Never
            # carry time accumulated by the previous snapshot/account into it.
            db.execute("DELETE FROM profile_lesson_progress WHERE profile=?", (profile,))
            # Request identities belong to this snapshot/account, not its name.
            db.execute("DELETE FROM main_live_attempts WHERE profile=?", (profile,))
            db.execute("DELETE FROM preference_receipts WHERE profile=?", (profile,))

    def snapshot(self, profile: str) -> tuple[bytes, str] | None:
        with self.connect() as db:
            row = db.execute("SELECT response,schema_sha256 FROM snapshots WHERE profile=?", (profile,)).fetchone()
            return (bytes(row["response"]), row["schema_sha256"]) if row is not None else None

    def settings(self, profile: str) -> tuple[bytes, str] | None:
        with self.connect() as db:
            row = db.execute("SELECT response,schema_sha256 FROM profile_settings WHERE profile=?", (profile,)).fetchone()
            return (bytes(row["response"]), row["schema_sha256"]) if row is not None else None

    def lesson_progress(self, profile: str) -> tuple[bytes, str] | None:
        """Return the opaque local ActivityLessonProgress, if initialized."""
        with self.connect() as db:
            row = db.execute("SELECT response,schema_sha256 FROM profile_lesson_progress WHERE profile=?",
                             (profile,)).fetchone()
            return (bytes(row["response"]), row["schema_sha256"]) if row is not None else None

    @staticmethod
    def live_request_id(value: str) -> str:
        """Validate the canonical positive uint64 x-app-request-id spelling."""
        if (not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", value)
                or int(value) > (1 << 64) - 1):
            raise ValueError("A canonical positive uint64 live request identity is required")
        return value

    def main_live_attempt(self, profile: str, request_id: str) -> dict | None:
        """Return an opaque local attempt receipt, without re-running a live."""
        self.live_request_id(request_id)
        with self.connect() as db:
            row = db.execute("SELECT * FROM main_live_attempts WHERE profile=? AND request_id=?",
                             (profile, request_id)).fetchone()
            return dict(row) if row is not None else None

    def mutate_main_live_snapshot(self, profile: str, schema_sha256: str, request_id: str,
                                  request_sha256: str, path: str, master_version: str,
                                  ruleset: str, callback) -> bytes:
        """Settle a live and its complete retry response in one write transaction.

        The callback runs only on a cache miss and returns
        ``(snapshot_bytes, response_bytes, uint64_seed, unix_milliseconds)``.
        It owns all protobuf, engine and reward validation. A cache hit returns
        the original response even if later actions changed the snapshot. An
        explicit snapshot import clears receipts; ordinary mutations never do.
        """
        self.live_request_id(request_id)
        if (not isinstance(request_sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", request_sha256) is None):
            raise ValueError("Live request SHA256 is required")
        if any(not isinstance(value, str) or not value
               for value in (schema_sha256, path, master_version, ruleset)) or not callable(callback):
            raise ValueError("Live attempt context and callback are required")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT response,schema_sha256 FROM snapshots WHERE profile=?",
                             (profile,)).fetchone()
            if row is None or row["schema_sha256"] != schema_sha256:
                raise ValueError("Local profile has no snapshot for this schema")
            old = db.execute("SELECT * FROM main_live_attempts WHERE profile=? AND request_id=?",
                             (profile, request_id)).fetchone()
            if old is not None:
                if old["request_sha256"] != request_sha256 or old["path"] != path:
                    raise AttemptConflict("Live request identity was reused for different input")
                if any(old[key] != value for key, value in (
                        ("schema_sha256", schema_sha256), ("master_version", master_version),
                        ("ruleset", ruleset))):
                    raise ValueError("Cached live attempt uses a different ruleset or master")
                return bytes(old["response"])
            original = bytes(row["response"])
            result = callback(original)
            if not isinstance(result, tuple) or len(result) != 4:
                raise ValueError("Live mutation must return snapshot, response, seed and time")
            payload, response, seed, started_time = result
            if (not isinstance(payload, bytes) or not isinstance(response, bytes)
                    or type(seed) is not int or not 0 <= seed <= (1 << 64) - 1
                    or type(started_time) is not int or not 0 < started_time <= (1 << 63) - 1):
                raise ValueError("Invalid live mutation receipt")
            if payload != original:
                db.execute("UPDATE snapshots SET response=? WHERE profile=?", (payload, profile))
            db.execute("INSERT INTO main_live_attempts VALUES (?,?,?,?,?,?,?,?,?,?)", (
                profile, request_id, request_sha256, path, schema_sha256,
                master_version, ruleset, str(seed), started_time, response))
        return response

    def mutate_preference_snapshot(self, profile: str, schema_sha256: str, request_id: str,
                                   request_sha256: str, path: str, callback) -> bytes:
        """Commit a toggle and its retry response in the same transaction.

        The callback returns (snapshot_bytes, response_bytes). An exact retry
        returns the original response without running the toggle, including
        after another preference changed or the server restarted. Snapshot
        replacement clears only this profile's receipts.
        """
        self.live_request_id(request_id)
        if (not isinstance(request_sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", request_sha256) is None
                or not isinstance(schema_sha256, str) or not schema_sha256
                or not isinstance(path, str)
                or re.fullmatch(r"/api\.[A-Za-z][A-Za-z0-9]*/[A-Za-z][A-Za-z0-9]*", path) is None
                or not callable(callback)):
            raise ValueError("Preference request context and callback are required")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT response,schema_sha256 FROM snapshots WHERE profile=?",
                             (profile,)).fetchone()
            if row is None or row["schema_sha256"] != schema_sha256:
                raise ValueError("Local profile has no snapshot for this schema")
            old = db.execute(
                "SELECT request_sha256,schema_sha256,response FROM preference_receipts "
                "WHERE profile=? AND path=? AND request_id=?", (profile, path, request_id)).fetchone()
            if old is not None:
                if old["request_sha256"] != request_sha256:
                    raise AttemptConflict("Preference request identity was reused for different input")
                if old["schema_sha256"] != schema_sha256:
                    raise ValueError("Cached preference response uses a different schema")
                return bytes(old["response"])
            original = bytes(row["response"])
            result = callback(original)
            if (not isinstance(result, tuple) or len(result) != 2
                    or not all(isinstance(value, bytes) for value in result)):
                raise ValueError("Preference mutation must return snapshot and response bytes")
            payload, response = result
            if payload != original:
                db.execute("UPDATE snapshots SET response=? WHERE profile=?", (payload, profile))
            db.execute("INSERT INTO preference_receipts VALUES (?,?,?,?,?,?)",
                       (profile, path, request_id, request_sha256, schema_sha256, response))
        return response

    def mutate_lesson_snapshot(self, profile: str, schema_sha256: str, callback) -> tuple[bytes, bytes]:
        """Update a snapshot and its local lesson clock in one transaction.

        ``callback(snapshot_bytes, lesson_bytes_or_none)`` returns both new
        protobuf byte strings. The activity service owns timestamp, cap and
        reward calculations; State never interprets those messages. A missing
        clock is explicit so the service can anchor at first supported access
        without estimating historical earnings. Callback failures roll back
        both rows. Sessions, identities, settings and starter markers remain
        intact, and unchanged snapshot bytes are not rewritten.
        """
        if not isinstance(schema_sha256, str) or not schema_sha256:
            raise ValueError("Lesson schema fingerprint is required")
        if not callable(callback):
            raise ValueError("Lesson mutation callback must be callable")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT s.response,s.schema_sha256,l.response AS lesson_response,"
                "l.schema_sha256 AS lesson_schema FROM snapshots AS s "
                "LEFT JOIN profile_lesson_progress AS l ON l.profile=s.profile WHERE s.profile=?",
                (profile,),
            ).fetchone()
            if row is None:
                raise ValueError("Local profile has no snapshot")
            if row["schema_sha256"] != schema_sha256:
                raise ValueError("Local profile snapshot uses a different schema")
            if row["lesson_response"] is not None and row["lesson_schema"] != schema_sha256:
                raise ValueError("Local lesson progress uses a different schema")
            original = bytes(row["response"])
            lesson = bytes(row["lesson_response"]) if row["lesson_response"] is not None else None
            result = callback(original, lesson)
            if not isinstance(result, tuple) or len(result) != 2:
                raise ValueError("Lesson mutation must return snapshot and progress bytes")
            payload, progress = result
            if not isinstance(payload, bytes) or not isinstance(progress, bytes):
                raise ValueError("Lesson mutation must return snapshot and progress bytes")
            if payload != original:
                db.execute("UPDATE snapshots SET response=? WHERE profile=?", (payload, profile))
            if lesson is None or progress != lesson:
                db.execute("INSERT INTO profile_lesson_progress VALUES (?,?,?) "
                           "ON CONFLICT(profile) DO UPDATE SET response=excluded.response,"
                           "schema_sha256=excluded.schema_sha256", (profile, progress, schema_sha256))
        return payload, progress

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
            original = bytes(row["response"])
            payload = callback(original)
            if not isinstance(payload, bytes):
                raise ValueError("Snapshot mutation must return protobuf bytes")
            if payload != original:
                db.execute("UPDATE snapshots SET response=? WHERE profile=?", (payload, profile))
            if setting_info is not None:
                db.execute("INSERT INTO profile_settings VALUES (?,?,?) ON CONFLICT(profile) DO UPDATE SET "
                           "response=excluded.response,schema_sha256=excluded.schema_sha256 "
                           "WHERE profile_settings.response IS NOT excluded.response "
                           "OR profile_settings.schema_sha256 IS NOT excluded.schema_sha256",
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
