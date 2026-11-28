import hashlib
import json

import pytest

from idoly_local.octo_manifest import Database
from idoly_local.octo_runtime import load_octo_archive


def archive(tmp_path, revision=1200):
    root = tmp_path / "public-octo"; root.mkdir()
    raw = Database(revision=revision).SerializeToString()
    settings = {"schema": 1, "application_id": 212, "application_version": 205051,
        "revision": revision, "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "aes_key_hex": "a" * 64, "client_key": "public-sdk-application-key"}
    (root / "manifest.pb").write_bytes(raw)
    (root / "settings.json").write_text(json.dumps(settings))
    pin = {"application_version": 205051, "revision": revision,
        "manifest_sha256": settings["manifest_sha256"], "legacy_manifest_sha256": "23b66c095821ed73cf9690c394d4acdbd2394315b39d30398d85f87a5762017a"}
    return root, settings, raw, pin


def test_latest_archive_requires_finite_actual_revision_and_digest_pin(tmp_path, monkeypatch):
    import idoly_local.latest_cohort_pins as pins
    root, settings, raw, approved = archive(tmp_path)
    monkeypatch.setattr(pins, "RESOURCE_ARCHIVES", {})
    with pytest.raises(ValueError, match="not approved"):
        load_octo_archive(root)
    monkeypatch.setattr(pins, "RESOURCE_ARCHIVES", {"android": approved})
    assert load_octo_archive(root) == (settings, raw)
    assert not list(tmp_path.glob("*.json"))


@pytest.mark.parametrize("key,value", [("revision", 1201), ("revision", True),
    ("application_version", 105051), ("manifest_sha256", "f" * 64),
    ("manifest_sha256", None), ("legacy_manifest_sha256", "c" * 64),
    ("legacy_manifest_sha256", None), ("unknown", 1)])
def test_latest_archive_rejects_another_revision_or_malformed_authority(tmp_path, monkeypatch, key, value):
    import idoly_local.latest_cohort_pins as pins
    root, _settings, _raw, approved = archive(tmp_path)
    approved[key] = value
    monkeypatch.setattr(pins, "RESOURCE_ARCHIVES", {"android": approved})
    with pytest.raises(ValueError, match="not approved|settings version differs"):
        load_octo_archive(root)


def test_latest_manifest_is_rehashed_after_settings_pin_matches(tmp_path, monkeypatch):
    import idoly_local.latest_cohort_pins as pins
    root, _settings, raw, approved = archive(tmp_path)
    monkeypatch.setattr(pins, "RESOURCE_ARCHIVES", {"android": approved})
    (root / "manifest.pb").write_bytes(raw + b"\x38\x01")
    with pytest.raises(ValueError, match="digest differs"):
        load_octo_archive(root)


def test_historical_archive_does_not_need_latest_authority(tmp_path, monkeypatch):
    import idoly_local.latest_cohort_pins as pins
    root, settings, raw, _approved = archive(tmp_path, revision=1087)
    monkeypatch.setattr(pins, "RESOURCE_ARCHIVES", {})
    assert load_octo_archive(root) == (settings, raw)
