"""The game and bulk/archive operations share the selected primary resource store."""
from __future__ import annotations

import io
from pathlib import Path
from zipfile import ZipFile

import pytest

from idoly_local.octo_cache import OctoCache
from idoly_local.octo_runtime import create_octo_gateway
from idoly_local.resource_library import ResourceLibrary
from test_resource_library import AES, Response, catalog, complete


def stored(root, platform, record):
    name = "octo-cache-ios" if platform == "ios" else "octo-cache"
    return root / name / record.cache_key[:2] / (record.cache_key + ".bin")


@pytest.mark.parametrize("platform", ["android", "ios"])
def test_game_bulk_export_and_import_use_one_public_primary_without_account_files(tmp_path, platform):
    private = tmp_path / "private"
    private.mkdir()
    manifest, bodies = catalog(private, platform, count=1)
    account = private / "state.db"
    account.write_bytes(b"private account state")
    public = tmp_path / "Download" / "IdolyPride"
    calls = []
    def fetch(url, *, timeout):
        calls.append(url)
        return Response(bodies[url])
    gateway, tracker = create_octo_gateway(private, "http://127.0.0.1:8080", aes_cbc=AES,
        fetcher=fetch, platform=platform, resource_cache_dir=public)
    library = ResourceLibrary.from_data_dir(private, aes_cbc=AES, fetcher=fetch,
        active_gateway=gateway, resource_cache_dir=public)
    target = None
    try:
        record = next(iter(manifest.objects.values()))
        with gateway.cache.open_verified(record) as stream:
            assert stream.read() == bodies[record.upstream_url]
        assert stored(public, platform, record).read_bytes() == bodies[record.upstream_url]
        library.start_download(platform)
        downloaded = complete(library)
        assert downloaded["state"] == "completed" and downloaded["cache_hit_files"] == 1
        assert len(calls) == 2
        assert tracker.status()["session_received_bytes"] == len(bodies[record.upstream_url])
        assert library.status()["storage"] == {"mode": "public_directory"}
        assert not (private / "octo-cache").exists() and not (private / "octo-cache-ios").exists()
        output = io.BytesIO()
        prepared = library.prepare_export(platform)
        exported = library.write_export(prepared["job_id"], output)
        assert exported["state"] == "completed" and exported["archive_complete"]
        with ZipFile(io.BytesIO(output.getvalue())) as archive:
            assert not any(name.endswith("state.db") or name.endswith("settings.json") for name in archive.namelist())
        other_private = tmp_path / "other-private"
        other_private.mkdir()
        other_manifest, _ = catalog(other_private, platform, count=1)
        other_public = tmp_path / "other-Download" / "IdolyPride"
        target = ResourceLibrary(other_private, {platform: other_manifest}, resource_cache_dir=other_public,
            fetcher=lambda *args, **kwargs: pytest.fail("Import must never reach the CDN"))
        imported = target.import_from(io.BytesIO(output.getvalue()), platform)
        assert imported["state"] == "completed" and imported["imported_files"] == 2
        assert imported["received_bytes"] == imported["downloaded_files"] == 0
        for record in manifest.objects.values():
            assert stored(other_public, platform, record).read_bytes() == bodies[record.upstream_url]
        assert not (other_private / "octo-cache").exists() and not (other_private / "octo-cache-ios").exists()
        assert not (public / "state.db").exists() and account.read_bytes() == b"private account state"
        assert set(path.name for path in public.iterdir()) == {"octo-cache-ios" if platform == "ios" else "octo-cache"}
    finally:
        gateway.close()
        library.close()
        if target is not None:
            target.close()


@pytest.mark.parametrize("platform", ["android", "ios"])
def test_existing_private_cache_seeds_public_primary_for_offline_game_bulk_and_export(tmp_path, platform):
    private = tmp_path / "private"
    private.mkdir()
    manifest, bodies = catalog(private, platform, count=1)
    legacy_root = private / ("octo-cache-ios" if platform == "ios" else "octo-cache")
    legacy = OctoCache(legacy_root, fetcher=lambda url, **kwargs: Response(bodies[url]))
    for record in manifest.objects.values():
        with legacy.open_verified(record):
            pass
    legacy.close()
    before = {record.cache_key: (stored(private, platform, record).read_bytes(), stored(private, platform, record).stat())
        for record in manifest.objects.values()}
    public = tmp_path / "Download" / "IdolyPride"
    forbidden = lambda *args, **kwargs: pytest.fail("Known verified legacy bytes must prevent CDN requests")
    gateway, tracker = create_octo_gateway(private, "http://127.0.0.1:8080", aes_cbc=AES, fetcher=forbidden,
        platform=platform, allow_downloads=False, resource_cache_dir=public)
    library = ResourceLibrary.from_data_dir(private, aes_cbc=AES, fetcher=forbidden, active_gateway=gateway,
        resource_cache_dir=public)
    try:
        record = next(iter(manifest.objects.values()))
        with gateway.cache.open_verified(record) as stream:
            assert stream.read() == bodies[record.upstream_url]
        output = io.BytesIO()
        prepared = library.prepare_export(platform)
        exported = library.write_export(prepared["job_id"], output)
        assert exported["state"] == "completed" and exported["exported_files"] == 2
        library.start_download(platform)
        job = complete(library)
        assert job["state"] == "completed" and job["cache_hit_files"] == 2
        assert job["received_bytes"] == job["downloaded_files"] == 0
        assert tracker.status()["session_received_bytes"] == 0
        for record in manifest.objects.values():
            content, old = before[record.cache_key]
            current = stored(private, platform, record).stat()
            assert stored(private, platform, record).read_bytes() == content
            assert (current.st_ino, current.st_mode, current.st_mtime_ns, current.st_ctime_ns) == (
                old.st_ino, old.st_mode, old.st_mtime_ns, old.st_ctime_ns)
            assert stored(public, platform, record).read_bytes() == content
    finally:
        gateway.close()
        library.close()


@pytest.mark.parametrize("selection", ["relative", "symlink", "cache-symlink"])
def test_public_storage_rejects_unsafe_root_or_platform_directory(tmp_path, selection):
    private = tmp_path / "private"
    private.mkdir()
    catalog(private, count=1)
    target = tmp_path / "target"
    target.mkdir()
    public = tmp_path / "public"
    if selection == "relative":
        public = Path("not-an-absolute-public-store")
    elif selection == "symlink":
        public.symlink_to(target, target_is_directory=True)
    else:
        public.mkdir()
        (public / "octo-cache").symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError):
        create_octo_gateway(private, "http://127.0.0.1:8080", aes_cbc=AES, resource_cache_dir=public,
            fetcher=lambda *args, **kwargs: pytest.fail("Invalid storage cannot reach the CDN"))
