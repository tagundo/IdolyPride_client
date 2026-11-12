from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
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
