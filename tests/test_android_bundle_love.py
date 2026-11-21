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
OLD_PUBLIC = {"data/love-reference.json", "data/love-adv-proof.json",
              "data/licenses/love-reference-NOTICE.txt", "data/licenses/love-reference-AGPL-3.0.txt"}
PUBLIC = OLD_PUBLIC | {"data/love-compatibility.json", "data/love-legacy-rules.json"}
LATEST_OCTO = {"data/public-octo/legacy-manifest.pb", "data/public-octo-ios/legacy-manifest.pb"}


def bundle(path, names, *, latest=False):
    files = {name: b"synthetic approved public namespace fixture" for name in names}
    if latest:
        files["data/payload-manifest.json"] = json.dumps({"schema": 1, "master_version": "a"*64,
            "source_overlay": {"operation": "latest-cohort-overlay-v1",
                "derivation": "complete-public-member-replacement", "master_version": "a"*64},
            "files": [{"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                      for name, raw in sorted(files.items()) if name != "data/payload-manifest.json"]},
            sort_keys=True).encode()
    with ZipFile(path, "w") as archive:
        for name, raw in files.items(): archive.writestr(name, raw)
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("platform", ["android", "macos", "ios"])
@pytest.mark.parametrize("cohort", ["legacy", "latest"])
def test_actual_pinned_member_names_install_without_changing_account_state(tmp_path, platform, cohort):
    latest = cohort == "latest"
    pin = json.loads((ROOT / ("data/latest-server-data-pin.json" if latest else "data/love-server-data-pin.json")).read_bytes())
    names = pin["output"]["member_names"]
    assert pin["output"]["entries"] == len(names) and names == sorted(set(names))
    if latest:
        from idoly_local.public_payload_transaction import TABLES
        assert pin["output"]["master_json_tables"] == len(TABLES) == 64
        assert set(pin["output"]["master_json_table_names"]) == TABLES
    else:
        assert len(names) == 566 and pin["output"]["master_json_tables"] == 62
    assert (PUBLIC if latest else OLD_PUBLIC) <= set(names) and boundary._LOVE_METADATA_FILES == PUBLIC
    if latest: assert LATEST_OCTO <= set(names) and boundary._LATEST_OCTO_FILES == LATEST_OCTO
    if latest: assert "data/latest-semantic-controls.json" in names
    path = tmp_path / "namespace-only.zip"
    expected = bundle(path, names, latest=latest)
    files = tmp_path / "app-files"; data = files / "data"; data.mkdir(parents=True)
    state = data / "state.db"; state.write_bytes(b"synthetic owned account: preserve")
    if platform == "android":
        assert boundary.install_bundle(path, files, expected, path.stat().st_size if latest else None) == data
    else:
        from idoly_local.public_payload import install_payload
        from idoly_local.ios_host import _Host
        mac_spec = importlib.util.spec_from_file_location("cross_platform_mac_payload", ROOT / "macos-server/payload.py")
        mac_payload = importlib.util.module_from_spec(mac_spec)
        mac_spec.loader.exec_module(mac_payload)
        host = _Host()
        assert mac_payload.install_payload is install_payload and host._installer is install_payload
        installer = mac_payload.install_payload if platform == "macos" else host._installer
        kwargs = {"expected_sha256": expected, "expected_bytes": path.stat().st_size} if latest else {}
        assert installer(path, data, **kwargs) == {"copied": len(names), "preserved": 0}
    assert state.read_bytes() == b"synthetic owned account: preserve"
    with ZipFile(path) as archive:
        assert all((files / name).read_bytes() == archive.read(name) for name in names)
    if latest:
        marker = json.loads((data / ".public-payload-state.json").read_bytes())
        assert marker["identity"]["sha256"] == expected
    elif platform == "android":
        assert (files / ".server-data-sha256").read_text().strip() == expected


@pytest.mark.parametrize("bad", ["data/licenses/unapproved.txt", "data/licenses/state.db", "data/state.db",
    "data/private/account.json", "data/love-reference-extra.json", "data/love-reference.json.bak",
    "data/love-compatibility-extra.json", "data/love-legacy-rules.json.bak",
    "data/latest-semantic-controls.json.bak", "data/public-octo/legacy-extra.pb",
    "data/public-octo/legacy-manifest-extra.pb", "data/public-octo-ios/legacy-manifest.pb.bak",
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


def test_shared_and_android_installer_agree_on_only_the_six_approved_metadata_names():
    from idoly_local.public_payload import member_path
    assert len(PUBLIC) == 6
    for name in PUBLIC:
        assert str(member_path(name)) == name.removeprefix("data/")
    for name in ("data/licenses/unapproved.txt", "data/love-reference-extra.json"):
        with pytest.raises(ValueError): member_path(name)
