from pathlib import Path
import stat
import sys
from zipfile import ZipFile, ZipInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from payload import install_payload, member_path


PUBLIC = {
    "data/protocol/idolypride-6.1.1.pb": b"protocol",
    "data/original-master/master-tag.json": b"{}",
    "data/original-master/assets/master/pack": b"public encrypted master",
    "data/master-json/Character.json": b"[]",
    "data/master-json/!version.txt": b"public-version",
    "data/payload-manifest.json": b"{}",
}


def archive(path, contents=None):
    with ZipFile(path, "w") as zipped:
        for filename, data in (contents or PUBLIC).items():
            zipped.writestr(filename, data)
    return path


def test_first_launch_install_and_update_preserve_profiles_and_existing_files(tmp_path):
    source = archive(tmp_path / "ServerData.zip")
    data = tmp_path / "Application Support/IdolyPrideLocal"
    data.mkdir(parents=True)
    database = data / "state.db"
    database.write_bytes(b"existing user account database")
    private = data / "private/firebase.archive"
    private.parent.mkdir()
    private.write_bytes(b"private account backup")
    result = install_payload(source, data)
    assert result == {"copied": 6, "preserved": 0}
    assert database.read_bytes() == b"existing user account database"
    assert private.read_bytes() == b"private account backup"
    descriptor = data / "protocol/idolypride-6.1.1.pb"
    descriptor.write_bytes(b"existing owner file")
    result = install_payload(source, data)
    assert result == {"copied": 0, "preserved": 6}
    assert descriptor.read_bytes() == b"existing owner file"
    assert all(file.stat().st_mode & 0o777 == 0o600 for file in data.rglob("*") if file.is_file() and file not in (database, private))
    assert not list(data.rglob(".server-data-*"))


@pytest.mark.parametrize("name", ["data/../state.db", "/data/protocol/idolypride-6.1.1.pb", "data/state.db",
                                  "data/sandbox/fixtures/private.pb", "data/private/firebase.archive",
                                  "data/master-json/../../state.db", "data/original-master/assets/master/../state.db",
                                  "data\\state.db", "state.db"])
def test_only_public_payload_paths_are_permitted_before_any_write(tmp_path, name):
    contents = dict(PUBLIC)
    contents[name] = b"must not be copied"
    source = archive(tmp_path / "ServerData.zip", contents)
    data = tmp_path / "data"
    with pytest.raises(ValueError):
        install_payload(source, data)
    assert not data.exists()


def test_symbolic_link_payload_and_destination_escape_are_rejected(tmp_path):
    source = archive(tmp_path / "ServerData.zip")
    with ZipFile(source, "a") as zipped:
        info = ZipInfo("data/master-json/Setting.json")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zipped.writestr(info, "../../private")
    with pytest.raises(ValueError, match="symbolic link"):
        install_payload(source, tmp_path / "data")
    source = archive(tmp_path / "clean.zip")
    outside = tmp_path / "outside"
    outside.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    (data / "protocol").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="outside"):
        install_payload(source, data)
    assert not list(outside.iterdir())


def test_missing_catalog_is_reported_before_files_are_installed(tmp_path):
    contents = {name: data for name, data in PUBLIC.items() if not name.startswith("data/master-json/")}
    source = archive(tmp_path / "incomplete.zip", contents)
    with pytest.raises(ValueError, match="incomplete"):
        install_payload(source, tmp_path / "data")
    assert not (tmp_path / "data").exists()


def test_public_terms_help_manifest_and_response_paths_are_supported(tmp_path):
    contents = dict(PUBLIC)
    contents["data/public-fixtures/manifest.json"] = b'{"schema_version":1,"responses":[]}'
    contents["data/public-fixtures/responses/api.Master-Rule-public.pb"] = b"public terms protobuf"
    source = archive(tmp_path / "ServerData.zip", contents)
    data = tmp_path / "data"
    install_payload(source, data)
    assert (data / "public-fixtures/responses/api.Master-Rule-public.pb").read_bytes() == b"public terms protobuf"


def test_only_the_three_fixed_public_tutorial_files_are_installed_and_preserved(tmp_path):
    contents = dict(PUBLIC)
    contents.update({"data/public-tutorial/manifest.json": b'{"schema":1}',
                     "data/public-tutorial/tutorial-short.pb": b"sanitized public short replay",
                     "data/public-tutorial/tutorial-full.pb": b"sanitized public full replay"})
    source = archive(tmp_path / "ServerData.zip", contents)
    data = tmp_path / "data"
    assert install_payload(source, data) == {"copied": 9, "preserved": 0}
    database = data / "state.db"
    database.write_bytes(b"existing local account")
    existing = data / "public-tutorial/tutorial-short.pb"
    existing.write_bytes(b"existing owner file")
    assert install_payload(source, data) == {"copied": 0, "preserved": 9}
    assert existing.read_bytes() == b"existing owner file"
    assert database.read_bytes() == b"existing local account"


@pytest.mark.parametrize("path", ["data/public-tutorial/private.archive", "data/public-tutorial/other.pb",
    "data/public-tutorial/nested/tutorial-short.pb", "data/public-tutorial/../state.db",
    "data/public-tutorial/tutorial-full.pb/secret", "data/public-tutorial/tutorial-short.pb.bak",
    "data/public-tutorial/tutorial-short\\.pb", "data/public-tutorial/manifest.json/private"])
def test_public_tutorial_paths_reject_private_arbitrary_and_traversal_files(path):
    with pytest.raises(ValueError):
        member_path(path)


@pytest.mark.parametrize("path", ["data/public-fixtures/private.archive", "data/public-fixtures/responses/nested/private.pb",
                                  "data/public-fixtures/responses/../state.db", "data/public-fixtures/responses/token.json",
                                  "data/public-fixtures/responses/.pb", "data/public-fixtures/responses/unsafe\\name.pb"])
def test_public_fixture_layout_does_not_allow_arbitrary_user_files(path):
    with pytest.raises(ValueError):
        member_path(path)
