"""Embedded translation startup copies only the separately pinned public asset."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from idoly_local.bundled_translations import resolve_translation_root
from test_bundled_translations import make_bundle


def load(relative, name):
    source = Path(__file__).resolve().parents[1] / relative
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def android():
    return load("android-server/app/src/main/python/android_server_runtime.py", "translation_android_boundary")


def java_asset(monkeypatch, path, *, close_error=False):
    raw, opened = path.read_bytes(), []

    class Asset:
        def __init__(self):
            self.offset, self.closed = 0, 0
        def read(self, target):
            if self.offset == len(raw):
                return -1
            count = min(17, len(target), len(raw) - self.offset)
            target[:count] = raw[self.offset:self.offset + count]
            self.offset += count
            return count
        def close(self):
            self.closed += 1
            if close_error:
                raise OSError("simulated stream close failure")

    instance = Asset()
    def open_asset(name):
        opened.append(name)
        assert name == "bundledTranslations.zip"
        return instance
    monkeypatch.setitem(sys.modules, "java", SimpleNamespace(jarray=lambda _: lambda size: bytearray(size), jbyte=object()))
    return SimpleNamespace(open=open_asset), instance, opened


def test_android_absent_optional_fields_do_not_open_assets(android, tmp_path):
    def reject(_name):
        raise AssertionError("Absent optional asset must not be opened")
    assert android._install_bundled_translations(SimpleNamespace(open=reject), SimpleNamespace(),
        tmp_path, tmp_path / "data", None, lambda _: None) == {"state": "absent"}
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("public", (False, True))
def test_android_asset_is_bounded_verified_and_installed_in_selected_storage(android, tmp_path, monkeypatch, public):
    from idoly_local import resource_translation_runtime
    semantic = []
    monkeypatch.setattr(resource_translation_runtime, "validate_prepared_translations",
        lambda prepared, data, **kwargs: semantic.append((prepared, data, kwargs)))
    path, pin = make_bundle(tmp_path)
    assets, stream, opened = java_asset(monkeypatch, path)
    files, data = tmp_path / "private", tmp_path / "private/data"
    selected = tmp_path / "Downloads/IdolyPride" if public else data
    config = SimpleNamespace(BUNDLED_TRANSLATIONS_SHA256=pin["expected_sha256"],
                             BUNDLED_TRANSLATIONS_BYTES=pin["expected_bytes"])
    result = android._install_bundled_translations(assets, config, files, data,
        str(selected) if public else None, lambda _: None)
    assert result["state"] == "installed" and opened == ["bundledTranslations.zip"] and stream.closed == 1
    assert (resolve_translation_root(selected, platform="android") / "ko/android/objects.zip").read_bytes() == b"v1:ko:objects.zip"
    assert not (files / "data/translations").exists() if public else True
    assert not list(files.rglob(".translations-zip-*"))
    # A valid private copied ZIP is reused without another Java asset open.
    assert android._install_bundled_translations(assets, config, files, data,
        str(selected) if public else None, lambda _: None)["state"] == "unchanged"
    assert opened == ["bundledTranslations.zip"]
    assert len(semantic) == 2 and all(row[1:] == (data, {"platform": "android"}) for row in semantic)


def test_android_hash_failure_survives_close_failure_and_cleans_temp(android, tmp_path, monkeypatch):
    path, pin = make_bundle(tmp_path)
    assets, stream, _ = java_asset(monkeypatch, path, close_error=True)
    config = SimpleNamespace(BUNDLED_TRANSLATIONS_SHA256="0" * 64, BUNDLED_TRANSLATIONS_BYTES=pin["expected_bytes"])
    with pytest.raises(ValueError, match="digest"):
        android._install_bundled_translations(assets, config, tmp_path / "private", tmp_path / "private/data",
                                             None, lambda _: None)
    assert stream.closed == 1 and not list((tmp_path / "private").rglob(".translations-zip-*"))
    assert not (tmp_path / "private/data/translations/current-android.json").exists()


def test_mac_optional_sidecar_pin_and_platform_are_required(tmp_path, monkeypatch):
    from idoly_local import resource_translation_runtime
    semantic = []
    monkeypatch.setattr(resource_translation_runtime, "validate_prepared_translations",
        lambda prepared, data, **kwargs: semantic.append((prepared, data, kwargs)))
    boundary = load("macos-server/payload.py", "translation_mac_payload")
    source = tmp_path / "ServerData.zip"
    root = tmp_path / "Downloads/IdolyPride"
    assert boundary.install_bundled_translations(source, root) == {"state": "absent"}
    archive, pin = make_bundle(tmp_path, platform="ios", name="bundledTranslations.zip")
    metadata = {"schema": 1, "platform": "ios", "sha256": pin["expected_sha256"], "bytes": pin["expected_bytes"]}
    (tmp_path / "bundledTranslations.json").write_text(json.dumps(metadata))
    assert boundary.install_bundled_translations(source, root, data_dir=tmp_path / "installed-core")["state"] == "installed"
    assert len(semantic) == 1 and semantic[0][1:] == (tmp_path / "installed-core", {"platform": "ios"})
    assert (resolve_translation_root(root, platform="ios") / "en/ios/manifest.pb").read_bytes() == b"v1:en:manifest.pb"
    before = (root / "translations/current-ios.json").read_bytes()
    metadata["platform"] = "android"
    (tmp_path / "bundledTranslations.json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError):
        boundary.install_bundled_translations(source, root, data_dir=tmp_path / "installed-core")
    assert (root / "translations/current-ios.json").read_bytes() == before


def test_android_optional_failure_is_visible_and_still_starts_original_runtime(android, tmp_path, monkeypatch):
    import idoly_local
    logs, starts = [], []
    config = SimpleNamespace(SERVER_DATA_SHA256="0" * 64)
    monkeypatch.setitem(sys.modules, "java", SimpleNamespace(jclass=lambda name:
        config if name.endswith("BuildConfig") else SimpleNamespace()))
    monkeypatch.setattr(android, "_copy_asset", lambda *args: None)
    monkeypatch.setattr(android, "install_bundle", lambda *args: tmp_path / "data")
    def fail(*args, **kwargs):
        raise ValueError("invalid new optional package")
    monkeypatch.setattr(android, "_install_bundled_translations", fail)
    runtime = SimpleNamespace(status=lambda: {"running": True})
    def start(*args, **kwargs):
        starts.append((args, kwargs))
        return runtime
    fake = SimpleNamespace(start=start)
    monkeypatch.setitem(sys.modules, "idoly_local.app_runtime", fake)
    monkeypatch.setattr(idoly_local, "app_runtime", fake, raising=False)
    result = json.loads(android.start(str(tmp_path), object(), SimpleNamespace(log=logs.append)))
    assert result["running"] is True and len(starts) == 1
    assert result["bundled_translations"] == {"state": "failed", "installed": False,
                                               "previous_files_preserved": True}
    assert any("번역 패키지를 설치하지 못했습니다" in message for message in logs)


def test_mac_optional_failure_is_visible_and_still_starts_original_runtime(tmp_path, monkeypatch):
    import idoly_local
    payload = load("macos-server/payload.py", "translation_mac_payload_start")
    monkeypatch.setitem(sys.modules, "payload", payload)
    engine = load("macos-server/engine.py", "translation_mac_engine_start")
    events, starts, failures = [], [], []
    monkeypatch.setattr(engine, "install_payload", lambda *args: None)
    def fail(*args, **kwargs):
        raise ValueError("invalid new optional package")
    monkeypatch.setattr(engine, "install_bundled_translations", fail)
    runtime = SimpleNamespace(status=lambda: {"running": True})
    def start(*args, **kwargs):
        starts.append((args, kwargs))
        return runtime
    fake = SimpleNamespace(start=start, record_startup_failure=lambda root, error, stage="catalog": failures.append((root, error, stage)))
    monkeypatch.setitem(sys.modules, "idoly_local.app_runtime", fake)
    monkeypatch.setattr(idoly_local, "app_runtime", fake, raising=False)
    controller = engine.Controller(tmp_path, tmp_path / "ServerData.zip",
        emit_event=lambda event, **fields: events.append((event, fields)))
    controller._start()
    assert controller.runtime is runtime and len(starts) == 1
    assert controller.status()["bundled_translations"] == {"state": "failed", "installed": False,
                                                          "previous_files_preserved": True}
    assert not any(event == "error" for event, fields in events)
    assert len(failures) == 1 and failures[0][0] == tmp_path
    assert isinstance(failures[0][1], ValueError) and failures[0][2] == "catalog"
