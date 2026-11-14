from pathlib import Path
from zipfile import ZipFile

import pytest

from idoly_local import public_payload


def bundle(path, extra=None):
    rows = {"data/protocol/idolypride-6.1.1.pb": b"schema", "data/original-master/master-tag.json": b"{}",
        "data/original-master/assets/master/pack": b"encrypted", "data/master-json/Character.json": b"[]"}
    rows.update(extra or {})
    with ZipFile(path, "w") as archive:
        for name, raw in rows.items(): archive.writestr(name, raw)
    return path


def test_portable_installer_preserves_both_profile_databases_and_existing_public_files(tmp_path):
    source = bundle(tmp_path / "ServerData.zip"); data = tmp_path / "data"; data.mkdir()
    for name in ("state.db", "media-state.db"): (data / name).write_bytes(name.encode())
    public_payload.install_payload(source, data)
    existing = data / "master-json/Character.json"; existing.write_bytes(b"owner-preserved")
    assert public_payload.install_payload(source, data) == {"copied": 0, "preserved": 4}
    assert existing.read_bytes() == b"owner-preserved"
    for name in ("state.db", "media-state.db"): assert (data / name).read_bytes() == name.encode()


@pytest.mark.parametrize("name", ["data/../state.db", "data/state.db", "/data/master-json/X.json", "data/master-json/../private.json"])
def test_portable_installer_rejects_unapproved_members_before_writing(tmp_path, name):
    source = bundle(tmp_path / "ServerData.zip", {name: b"bad"}); data = tmp_path / "data"
    with pytest.raises(ValueError): public_payload.install_payload(source, data)
    assert not data.exists()


def test_optional_translation_metadata_must_bind_real_archive(tmp_path):
    data = tmp_path / "data"; data.mkdir()
    assert public_payload.install_bundled_translations(tmp_path / "ServerData.zip", tmp_path, data_dir=data) == {"state": "absent"}
    (tmp_path / "bundledTranslations.zip").write_bytes(b"invalid")
    with pytest.raises((ValueError, OSError)):
        public_payload.install_bundled_translations(tmp_path / "ServerData.zip", tmp_path, data_dir=data)
