from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import errno
import hashlib
import io
import stat
import sys
from zipfile import ZipFile

HERE = Path(__file__).resolve().parents[1] / "cross"
sys.path.insert(0, str(HERE))
spec = spec_from_file_location("cross_bundle_builder", HERE / "build_app.py")
builder = module_from_spec(spec)
spec.loader.exec_module(builder)


def test_archive_preserves_symlinks_executable_mode_and_large_stream(tmp_path):
    app = tmp_path / "Test.app"
    binary = app / "Contents/MacOS/Test"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"unchanged executable")
    binary.chmod(0o755)
    resource = app / "Contents/Resources/payload"
    resource.parent.mkdir()
    resource.write_bytes(bytes(range(256)) * 1024)
    (resource.parent / "alias").symlink_to("payload")
    archive = tmp_path / "Test.app.zip"
    builder.archive_app(app, archive)
    with ZipFile(archive) as zipped:
        assert zipped.read("Test.app/Contents/MacOS/Test") == binary.read_bytes()
        assert zipped.getinfo("Test.app/Contents/MacOS/Test").external_attr >> 16 & 0o777 == 0o755
        info = zipped.getinfo("Test.app/Contents/Resources/alias")
        assert stat.S_ISLNK(info.external_attr >> 16)
        assert zipped.read(info) == b"payload"
        assert zipped.read("Test.app/Contents/Resources/payload") == resource.read_bytes()


def test_archive_rejects_existing_destination(tmp_path):
    archive = tmp_path / "existing.zip"
    archive.write_bytes(b"preserve")
    import pytest
    with pytest.raises(ValueError, match="already exists"):
        builder.archive_app(tmp_path / "unused.app", archive)
    assert archive.read_bytes() == b"preserve"


def test_payload_same_filesystem_keeps_one_inode(tmp_path, monkeypatch):
    source, target = tmp_path / "data.zip", tmp_path / "installed.zip"
    source.write_bytes(b"known public payload")
    advised = []
    monkeypatch.setattr(builder, "release_public_input_cache", lambda path: advised.append(Path(path)))
    assert builder.install_payload(source, target, expected_sha=hashlib.sha256(source.read_bytes()).hexdigest(),
                                   expected_bytes=source.stat().st_size) == "hardlink"
    assert source.stat().st_ino == target.stat().st_ino and advised == [source]


def test_payload_exdev_uses_one_verified_bounded_app_copy(tmp_path, monkeypatch):
    source, target = tmp_path / "data.zip", tmp_path / "installed.zip"
    data = bytes(range(256)) * 1024
    source.write_bytes(data); source.chmod(0o600)
    def cross_device(*_args):
        raise OSError(errno.EXDEV, "Different filesystems")
    monkeypatch.setattr(builder.os, "link", cross_device)
    advised, sizes = [], []
    monkeypatch.setattr(builder, "release_public_input_cache", lambda path: advised.append(Path(path)))
    original_open = Path.open
    class BoundedReader:
        def __enter__(self):
            self.stream = original_open(source, "rb"); return self
        def __exit__(self, *_args):
            self.stream.close()
        def read(self, count):
            sizes.append(count); assert count == 65536; return self.stream.read(count)
    def controlled_open(path, mode="r", *args, **kwargs):
        return BoundedReader() if path == source and mode == "rb" else original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", controlled_open)
    assert builder.install_payload(source, target, expected_sha=hashlib.sha256(data).hexdigest(),
                                   expected_bytes=len(data)) == "streamed_copy"
    assert target.read_bytes() == data and stat.S_IMODE(target.stat().st_mode) == 0o600
    assert source.stat().st_ino != target.stat().st_ino and len(sizes) == 5 and advised == [source]


def test_payload_exdev_failure_removes_only_owned_partial_output(tmp_path, monkeypatch):
    source, target = tmp_path / "data.zip", tmp_path / "installed.zip"
    source.write_bytes(b"original")
    def cross_device(*_args):
        raise OSError(errno.EXDEV, "Different filesystems")
    monkeypatch.setattr(builder.os, "link", cross_device)
    monkeypatch.setattr(builder, "release_public_input_cache", lambda _path: None)
    import pytest
    with pytest.raises(ValueError, match="fingerprint"):
        builder.install_payload(source, target, expected_sha="0" * 64, expected_bytes=8)
    assert not target.exists() and source.read_bytes() == b"original"
    original_open = Path.open
    def growing_input(path, mode="r", *args, **kwargs):
        return io.BytesIO(b"grew beyond the verified bound") if path == source and mode == "rb" else original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", growing_input)
    with pytest.raises(ValueError, match="byte bound"):
        builder.install_payload(source, target, expected_sha="0" * 64, expected_bytes=8)
    assert not target.exists()
    target.write_bytes(b"preserve")
    with pytest.raises(FileExistsError):
        builder.install_payload(source, target, expected_sha="0" * 64, expected_bytes=8)
    assert target.read_bytes() == b"preserve"


def test_payload_other_link_errors_and_size_mismatches_do_not_copy(tmp_path, monkeypatch):
    import pytest
    source, target = tmp_path / "data.zip", tmp_path / "installed.zip"
    source.write_bytes(b"original")
    def denied(*_args):
        raise PermissionError(errno.EACCES, "Denied")
    monkeypatch.setattr(builder.os, "link", denied)
    with pytest.raises(ValueError, match="size"):
        builder.install_payload(source, target, expected_sha="0" * 64, expected_bytes=9)
    with pytest.raises(PermissionError):
        builder.install_payload(source, target, expected_sha="0" * 64, expected_bytes=8)
    assert not target.exists() and source.read_bytes() == b"original"
