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


def test_committed_upgraded_payload_inventory_is_admitted_by_the_real_installer_policy():
    import json
    pin_path=Path(__file__).resolve().parents[1]/"data/love-server-data-pin.json"
    pin=json.loads(pin_path.read_text())
    names=pin["output"]["member_names"]
    assert len(names)==pin["output"]["entries"]==566 and len(set(names))==566
    required={"data/love-reference.json","data/love-adv-proof.json","data/licenses/love-reference-NOTICE.txt",
        "data/licenses/love-reference-AGPL-3.0.txt"}
    assert required<=set(names)
    assert {public_payload.member_path(name) for name in names}=={name.removeprefix("data/") for name in names}


def test_all_eleven_overlay_members_install_without_changing_accounts_preferences_or_public_files(tmp_path):
    overlay={"data/master-json/"+table+".json":b"[]" for table in
        ("LoveStoryEpisode","LoveLevel","LoveHomeAction","LoveColor","Condition","EventMission","LoveCatalog")}
    overlay.update({"data/love-reference.json":b'{"source":"public-reference"}',"data/love-adv-proof.json":b'{"source":"public-proof"}',
        "data/licenses/love-reference-NOTICE.txt":b"public notice\n","data/licenses/love-reference-AGPL-3.0.txt":b"public license\n"})
    assert len(overlay)==11
    source=bundle(tmp_path/"ServerData.zip",overlay);data=tmp_path/"data";data.mkdir()
    owned={name:("preserve:"+name).encode() for name in ("state.db","media-state.db","server-events.json",
        "client-language.json","ios-host.json","client-media.json","client-presentation.json","client-playback.json")}
    for name,raw in owned.items():(data/name).write_bytes(raw)
    public=data/"master-json/Character.json";public.parent.mkdir();public.write_bytes(b"owner-preserved-public-table")
    result=public_payload.install_payload(source,data)
    assert result["copied"]>=11 and result["preserved"]>=1
    for name,raw in overlay.items():assert (data/name.removeprefix("data/")).read_bytes()==raw
    for name,raw in owned.items():assert (data/name).read_bytes()==raw
    assert public.read_bytes()==b"owner-preserved-public-table"


@pytest.mark.parametrize("name",["data/love-reference-private.json","data/love-reference.json/secret",
    "data/love-adv-proof.json.bak","data/licenses/other.txt","data/licenses/love-reference-NOTICE.txt.bak",
    "data/licenses/../state.db","data/licenses/love-reference-NOTICE.txt/../private",
    "data/server-events.json","data/media-state.db"])
def test_overlay_admission_does_not_allow_nearby_private_or_escaped_paths(tmp_path,name):
    source=bundle(tmp_path/"ServerData.zip",{name:b"must-not-install"});data=tmp_path/"data"
    with pytest.raises(ValueError):public_payload.install_payload(source,data)
    assert not data.exists()


@pytest.mark.parametrize("name",["data/love-reference.json","data/licenses/love-reference-NOTICE.txt"])
def test_new_public_overlay_names_still_reject_archive_symlinks_before_writing(tmp_path,name):
    import stat
    from zipfile import ZipInfo
    source=bundle(tmp_path/"ServerData.zip")
    entry=ZipInfo(name);entry.create_system=3;entry.external_attr=(stat.S_IFLNK|0o777)<<16
    with ZipFile(source,"a") as archive:archive.writestr(entry,b"../../private-state.db")
    data=tmp_path/"data"
    with pytest.raises(ValueError,match="symbolic link"):public_payload.install_payload(source,data)
    assert not data.exists()
