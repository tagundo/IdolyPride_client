"""Starter provenance and migrations must not replace imports or local sessions."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import unittest

from idoly_local.state import State


class StarterStateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "state.db"
        self.state = State(self.path)

    def save(self, payload=b"original", version=1):
        self.state.save_snapshot("starter", payload, "schema", starter_version=version)

    def mark_legacy(self):
        with self.state.connect() as db:
            db.execute("DELETE FROM starter_profiles WHERE profile='starter'")

    def test_save_default_marks_explicit_import_and_replaces_starter_origin(self):
        self.assertIsNone(self.state.starter_version("absent"))
        self.save(version=2)
        self.assertEqual(self.state.starter_version("starter"), 2)
        token, _ = self.state.login("starter")
        self.state.save_snapshot("starter", b"imported", "schema")
        self.assertEqual(self.state.starter_version("starter"), 0)
        self.assertEqual(self.state.snapshot("starter"), (b"imported", "schema"))
        self.assertFalse(self.state.authenticated(token, "starter"))
        self.assertEqual(State(self.path).starter_version("starter"), 0)

    def test_callback_can_distinguish_import_zero_legacy_none_and_starter_version(self):
        self.save(version=1)
        seen = []

        def preserve(payload, version):
            seen.append((payload, version))
            return None

        self.state.mutate_starter_snapshot("starter", "schema", preserve)
        self.mark_legacy()
        self.state.mutate_starter_snapshot("starter", "schema", preserve)
        self.state.save_snapshot("starter", b"imported", "schema")
        self.state.mutate_starter_snapshot("starter", "schema", preserve)
        self.assertEqual(seen, [(b"original", 1), (b"original", None), (b"imported", 0)])
        self.assertEqual(self.state.starter_version("starter"), 0)

    def test_migration_preserves_sessions_settings_identity_and_other_profiles(self):
        self.save()
        identity = self.state.profile("starter")
        token, _ = self.state.login("starter")
        self.state.mutate_snapshot("starter", "schema", lambda payload: payload, setting_info=b"settings")
        self.state.save_snapshot("other", b"other", "other-schema", starter_version=3)
        other_token, _ = self.state.login("other")
        actual = self.state.mutate_starter_snapshot("starter", "schema", lambda payload, version: (payload + b"-repaired", 2))
        self.assertEqual(actual, b"original-repaired")
        self.assertEqual(self.state.snapshot("starter"), (actual, "schema"))
        self.assertEqual(self.state.starter_version("starter"), 2)
        self.assertTrue(self.state.authenticated(token, "starter"))
        self.assertEqual(self.state.settings("starter"), (b"settings", "schema"))
        self.assertEqual(self.state.profile("starter"), identity)
        self.assertEqual(self.state.snapshot("other"), (b"other", "other-schema"))
        self.assertEqual(self.state.starter_version("other"), 3)
        self.assertTrue(self.state.authenticated(other_token, "other"))

    def test_legacy_migration_commits_bytes_and_origin_together(self):
        self.save()
        self.mark_legacy()
        self.assertIsNone(self.state.starter_version("starter"))
        self.assertEqual(self.state.mutate_starter_snapshot("starter", "schema", lambda p, v: (b"repaired", 2)), b"repaired")
        reopened = State(self.path)
        self.assertEqual(reopened.snapshot("starter"), (b"repaired", "schema"))
        self.assertEqual(reopened.starter_version("starter"), 2)

    def test_legacy_database_initialization_does_not_relabel_existing_snapshot(self):
        self.save()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TABLE starter_profiles")
        reopened = State(self.path)
        self.assertEqual(reopened.snapshot("starter"), (b"original", "schema"))
        self.assertIsNone(reopened.starter_version("starter"))
        reopened.mutate_snapshot("starter", "schema", lambda payload: payload + b"-ordinary")
        self.assertIsNone(reopened.starter_version("starter"))

    def test_skip_and_identical_return_do_not_claim_a_change(self):
        self.save(version=2)
        self.assertIsNone(self.state.mutate_starter_snapshot("starter", "schema", lambda p, v: None))
        self.assertIsNone(self.state.mutate_starter_snapshot("starter", "schema", lambda p, v: (p, v)))
        self.assertEqual(self.state.snapshot("starter"), (b"original", "schema"))
        # Marker-only upgrades still count as a committed migration.
        self.assertEqual(self.state.mutate_starter_snapshot("starter", "schema", lambda p, v: (p, 3)), b"original")

    def test_callback_exception_and_invalid_result_roll_back_everything(self):
        self.save()
        token, _ = self.state.login("starter")
        bad_results = [(b"changed", 0), (b"changed", -1), (b"changed", True),
                       (b"changed", "2"), ("not bytes", 2), [b"changed", 2], (b"changed",)]
        for result in bad_results:
            with self.subTest(result=result), self.assertRaises(ValueError):
                self.state.mutate_starter_snapshot("starter", "schema", lambda p, v: result)
            self.assertEqual(self.state.snapshot("starter"), (b"original", "schema"))
            self.assertEqual(self.state.starter_version("starter"), 1)
            self.assertTrue(self.state.authenticated(token, "starter"))

        def fail(_payload, _version):
            raise RuntimeError("Synthetic failed migration")

        self.mark_legacy()
        with self.assertRaises(RuntimeError):
            self.state.mutate_starter_snapshot("starter", "schema", fail)
        self.assertIsNone(self.state.starter_version("starter"))
        self.assertEqual(self.state.snapshot("starter"), (b"original", "schema"))
        self.assertTrue(self.state.authenticated(token, "starter"))

    def test_origin_write_failure_rolls_back_snapshot_update(self):
        self.save()
        with self.state.connect() as db:
            db.execute("CREATE TRIGGER fail_starter_update BEFORE UPDATE ON starter_profiles "
                       "BEGIN SELECT RAISE(ABORT, 'synthetic origin failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.state.mutate_starter_snapshot("starter", "schema", lambda p, v: (b"changed", 2))
        self.assertEqual(self.state.snapshot("starter"), (b"original", "schema"))
        self.assertEqual(self.state.starter_version("starter"), 1)

    def test_invalid_save_version_and_migration_context_preserve_prior_state(self):
        self.save(version=2)
        for version in [-1, True, 1.5, "2"]:
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.state.save_snapshot("starter", b"changed", "schema", starter_version=version)
        for profile, schema in [("absent", "schema"), ("starter", "wrong-schema"), ("starter", "")]:
            with self.subTest(profile=profile, schema=schema), self.assertRaises(ValueError):
                self.state.mutate_starter_snapshot(profile, schema, lambda p, v: (b"changed", 3))
        with self.assertRaises(ValueError):
            self.state.mutate_starter_snapshot("starter", "schema", None)
        with self.assertRaises(ValueError):
            self.state.mutate_starter_snapshot("starter", "schema", lambda p, v: (b"changed", 1))
        self.assertEqual(self.state.snapshot("starter"), (b"original", "schema"))
        self.assertEqual(self.state.starter_version("starter"), 2)

    def test_concurrent_upgrade_is_applied_once_and_observes_committed_version(self):
        self.save()

        def repair(_):
            def change(payload, version):
                return (payload + b"-upgraded", 2) if version == 1 else None
            return State(self.path).mutate_starter_snapshot("starter", "schema", change)

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(repair, range(12)))
        self.assertEqual(results.count(b"original-upgraded"), 1)
        self.assertEqual(results.count(None), 11)
        self.assertEqual(self.state.snapshot("starter"), (b"original-upgraded", "schema"))
        self.assertEqual(self.state.starter_version("starter"), 2)


if __name__ == "__main__":
    unittest.main()
