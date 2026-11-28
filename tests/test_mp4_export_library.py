"""Persistent export records survive ephemeral audio broker sessions."""
from pathlib import Path

import pytest

from idoly_local.mp4_export_library import MP4ExportLibrary


def test_finished_outputs_and_pending_journal_survive_library_restart(tmp_path):
    library = MP4ExportLibrary(tmp_path)
    first = library.configuration()
    queue, exports = Path(first["queue_directory"]), Path(first["persistent_export_directory"])
    assert queue.stat().st_mode & 0o777 == exports.stat().st_mode & 0o777 == 0o700
    (queue / "jobs.bin").write_bytes(b"native-owned-journal")
    (exports / ("a" * 32 + ".mp4")).write_bytes(b"finished-output")
    library.close()
    with pytest.raises(ValueError, match="closed"):
        library.configuration()
    reopened = MP4ExportLibrary(tmp_path)
    try:
        assert reopened.configuration() == first
        assert (queue / "jobs.bin").read_bytes() == b"native-owned-journal"
        assert (exports / ("a" * 32 + ".mp4")).read_bytes() == b"finished-output"
    finally:
        reopened.close()


@pytest.mark.parametrize("member", ["root", "queue", "exports"])
def test_library_rejects_symlinks_and_preserves_foreign_files(tmp_path, member):
    target = tmp_path / "foreign"
    target.mkdir(mode=0o700)
    (target / "keep").write_bytes(b"foreign")
    root = tmp_path / MP4ExportLibrary.NAME
    if member == "root":
        root.symlink_to(target, target_is_directory=True)
    else:
        root.mkdir(mode=0o700)
        (root / member).symlink_to(target, target_is_directory=True)
    with pytest.raises((OSError, ValueError)):
        MP4ExportLibrary(tmp_path)
    assert (target / "keep").read_bytes() == b"foreign"


def test_library_detects_replaced_directory_without_adopting_or_deleting_it(tmp_path):
    library = MP4ExportLibrary(tmp_path)
    root = Path(library.configuration()["queue_directory"])
    root.rename(root.with_name("original-queue"))
    root.mkdir(mode=0o700)
    (root / "foreign").write_bytes(b"keep")
    try:
        with pytest.raises(ValueError, match="changed"):
            library.configuration()
    finally:
        library.close()
    assert (root / "foreign").read_bytes() == b"keep"


def test_library_rejects_shared_permissions_without_chmoding_existing_data(tmp_path):
    root = tmp_path / MP4ExportLibrary.NAME
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    with pytest.raises(ValueError, match="private"):
        MP4ExportLibrary(tmp_path)
    assert root.stat().st_mode & 0o777 == 0o755


def test_audio_restart_rotates_capability_and_keeps_queue_and_finished_outputs(tmp_path):
    from idoly_local.mp4_audio_broker import MP4AudioBroker
    from test_mp4_audio_broker import make_store, eventually
    store, cache, _, _, _ = make_store(tmp_path)
    first = second = None
    try:
        first = MP4AudioBroker(store, tmp_path)
        a = first.configuration()
        journal = Path(a["queue_directory"]) / "native-journal"
        journal.write_bytes(b"pending-MV")
        first.close()
        eventually(lambda: not first._fds)
        second = MP4AudioBroker(store, tmp_path)
        b = second.configuration()
        assert a["directory"] != b["directory"] and a["capability"] != b["capability"]
        assert a["queue_directory"] == b["queue_directory"]
        assert a["persistent_export_directory"] == b["persistent_export_directory"]
        assert journal.read_bytes() == b"pending-MV"
        assert "queue_directory" not in second.status()
    finally:
        for broker in (first, second):
            if broker:
                broker.close()
        store.close()
        cache.close()
