"""Android's independent ZIP installer admits the exact prepared public names.

Fixtures contain synthetic bytes only: full original payload provenance/hash is
verified separately by the native builder and the pinned payload verifier.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("android_love_installer", ROOT / "android-server/app/src/main/python/android_server_runtime.py")
boundary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(boundary)
PUBLIC = {"data/love-reference.json", "data/love-adv-proof.json",
          "data/licenses/love-reference-NOTICE.txt", "data/licenses/love-reference-AGPL-3.0.txt"}


def bundle(path, names):
    with ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, b"synthetic approved public namespace fixture")
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("platform", ["android", "macos", "ios"])
def test_actual_pinned_566_member_names_install_without_changing_account_state(tmp_path, platform):
    pin = json.loads((ROOT / "data/love-server-data-pin.json").read_bytes())
    names = pin["output"]["member_names"]
    assert pin["output"]["entries"] == len(names) == 566
    assert pin["output"]["master_json_tables"] == 62
    assert PUBLIC <= set(names) and boundary._LOVE_METADATA_FILES == PUBLIC
    path = tmp_path / "namespace-only.zip"
    expected = bundle(path, names)
    files = tmp_path / "app-files"; data = files / "data"; data.mkdir(parents=True)
    state = data / "state.db"; state.write_bytes(b"synthetic owned account: preserve")
    if platform == "android":
        assert boundary.install_bundle(path, files, expected) == data
    else:
        from idoly_local.public_payload import install_payload
        from idoly_local.ios_host import _Host
        mac_spec = importlib.util.spec_from_file_location("cross_platform_mac_payload", ROOT / "macos-server/payload.py")
        mac_payload = importlib.util.module_from_spec(mac_spec)
        mac_spec.loader.exec_module(mac_payload)
        host = _Host()
        assert mac_payload.install_payload is install_payload and host._installer is install_payload
        installer = mac_payload.install_payload if platform == "macos" else host._installer
        assert installer(path, data) == {"copied": 566, "preserved": 0}
    assert state.read_bytes() == b"synthetic owned account: preserve"
    assert all((files / name).read_bytes() == b"synthetic approved public namespace fixture" for name in names)
    if platform == "android":
        assert (files / ".server-data-sha256").read_text().strip() == expected


@pytest.mark.parametrize("bad", ["data/licenses/unapproved.txt", "data/licenses/state.db", "data/state.db",
    "data/private/account.json", "data/love-reference-extra.json", "data/love-reference.json.bak",
    "data//love-reference.json", "data/./love-reference.json", "data/../love-reference.json",
    "data/licenses/../state.db", "data\\licenses\\love-reference-NOTICE.txt", "/data/love-reference.json"])
def test_metadata_allowlist_never_admits_unrelated_or_aliased_paths(tmp_path, bad):
    names = ["data/protocol/idolypride-6.1.1.pb", "data/original-master/master-tag.json", *sorted(PUBLIC), bad]
    path = tmp_path / "unapproved.zip"; expected = bundle(path, names)
    files = tmp_path / "app-files"
    with pytest.raises(ValueError, match="non-public or unsafe"):
        boundary.install_bundle(path, files, expected)
    assert not (files / ".server-data-sha256").exists()
    assert not any(files.rglob("*"))


def test_shared_and_android_installer_agree_on_only_the_four_new_metadata_names():
    from idoly_local.public_payload import member_path
    assert len(PUBLIC) == 4
    for name in PUBLIC:
        assert str(member_path(name)) == name.removeprefix("data/")
    for name in ("data/licenses/unapproved.txt", "data/love-reference-extra.json"):
        with pytest.raises(ValueError): member_path(name)
