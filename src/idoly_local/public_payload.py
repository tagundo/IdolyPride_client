"""Install bundled public server data without replacing profiles or state.

The portable runtime boundary is shared by native launchers. It uses only
stdlib file/ZIP APIs until an optional prepared translation bundle is present.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import os
import json
import shutil
import stat
import tempfile
from zipfile import ZipFile


FIXED_FILES = {
    "payload-manifest.json",
    "love-reference.json",
    "love-adv-proof.json",
    "love-compatibility.json",
    "love-legacy-rules.json",
    "latest-semantic-controls.json",
    "licenses/love-reference-NOTICE.txt",
    "licenses/love-reference-AGPL-3.0.txt",
    "public-fixtures/manifest.json",
    "public-tutorial/manifest.json",
    "public-tutorial/tutorial-short.pb",
    "public-tutorial/tutorial-full.pb",
    "public-story/manifest.json",
    "public-story/story-list-event.pb",
    "public-story/story-list-extra.pb",
    "protocol/idolypride-6.1.1.pb",
    "protocol/idolypride-6.1.1.evidence.json",
    "public-octo/settings.json",
    "public-octo/manifest.pb",
    "public-octo/legacy-manifest.pb",
    "public-octo-ios/settings.json",
    "public-octo-ios/manifest.pb",
    "public-octo-ios/legacy-manifest.pb",
    "original-master/response.pb",
    "original-master/master-tag.json",
    "original-master/media-master-tag.json",
    "original-master/archive-report.json",
}
PACK_PREFIX = "original-master/assets/master/"
FIXED_FILES.update({"original-master/master-sort.json", "original-master/media-master-sort.json"})
FIXED_FILES.update(
    f"original-master/languages/{language}/{filename}"
    for language in ("ko", "en")
    for filename in ("master-tag.json", "media-master-tag.json", "master-sort.json",
                     "media-master-sort.json", "coverage.json", "media-coverage.json")
)


def member_path(name: str) -> str:
    if "\\" in name or "\x00" in name:
        raise ValueError("Server data contains an invalid path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("Server data contains an invalid path")
    if not name.startswith("data/"):
        raise ValueError("Server data must use the data/ layout")
    relative = name[5:]
    if relative in FIXED_FILES:
        return relative
    if relative.startswith("public-fixtures/responses/"):
        filename = relative[len("public-fixtures/responses/"):]
        if (filename.endswith(".pb") and "/" not in filename
                and filename[:-3] and all(char.isalnum() or char in "._-" for char in filename[:-3])):
            return relative
    if relative.startswith("master-json/"):
        filename = relative[len("master-json/"):]
        if filename == "!version.txt" or (filename.endswith(".json") and filename[:-5].replace("_", "").isalnum()):
            return relative
    if relative.startswith(PACK_PREFIX):
        filename = relative[len(PACK_PREFIX):]
        if filename and "/" not in filename and filename not in (".", ".."):
            return relative
    raise ValueError("Server data contains files outside the public payload")


def acquire_payload_read_lease(data_dir):
    """Hold the public cohort stable until the calling runtime has fully stopped."""
    from .public_payload_transaction import acquire_payload_read_lease as acquire
    return acquire(data_dir)


def install_payload(source: Path, data_dir: Path, log=None, *, expected_sha256=None, expected_bytes=None) -> dict:
    """Install a pinned latest cohort transactionally; retain legacy missing-only fixtures."""
    latest = expected_sha256 is not None or expected_bytes is not None
    if not latest:
        with ZipFile(source) as archive:
            if "data/payload-manifest.json" in archive.namelist():
                info = archive.getinfo("data/payload-manifest.json")
                if info.file_size > 2*1024*1024:
                    raise ValueError("public_payload_invalid")
                try:
                    manifest = json.loads(archive.read(info))
                except (ValueError, UnicodeError):
                    manifest = {}  # Preserve legacy non-JSON namespace fixtures.
                overlay = manifest.get("source_overlay", {}) if type(manifest) is dict else {}
                operation = overlay.get("operation") if type(overlay) is dict else None
                if operation == "latest-cohort-overlay-v1":
                    latest = True
                elif operation not in (None, "love-source-overlay-v1"):
                    raise ValueError("public_payload_policy_unsupported")
    if latest:
        from .public_payload_transaction import install_managed_payload
        return install_managed_payload(source, data_dir, expected_sha256=expected_sha256, expected_bytes=expected_bytes)
    data_dir = Path(data_dir).expanduser().resolve()
    copied = preserved = 0
    with ZipFile(source) as archive:
        members = []
        names = set()
        for info in archive.infolist():
            if info.is_dir():
                continue
            relative = member_path(info.filename)
            if relative in names or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("Server data contains a duplicate or symbolic link")
            names.add(relative)
            members.append((info, relative))
        required = {"protocol/idolypride-6.1.1.pb", "original-master/master-tag.json"}
        if (not required.issubset(names) or not any(name.startswith(PACK_PREFIX) for name in names)
                or not any(name.startswith("master-json/") and name.endswith(".json") for name in names)):
            raise ValueError("Bundled server data is incomplete")
        data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        for info, relative in members:
            target = data_dir / relative
            if not target.resolve().is_relative_to(data_dir):
                raise ValueError("Server data destination is outside the data folder")
            if target.exists():
                if not target.is_file():
                    raise ValueError("A server data destination is not a regular file")
                preserved += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = None
            try:
                with archive.open(info) as stream, tempfile.NamedTemporaryFile(
                        dir=target.parent, prefix=".server-data-", delete=False) as output:
                    temporary = Path(output.name)
                    shutil.copyfileobj(stream, output, length=64 * 1024)
                # Another app instance may have installed this public file first.
                if not target.exists():
                    os.replace(temporary, target)
                    copied += 1
                else:
                    preserved += 1
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            if log and copied and copied % 25 == 0:
                log(f"서버 데이터 준비 중: {copied}개 파일")
    return {"copied": copied, "preserved": preserved}


def install_bundled_translations(server_data: Path, cache_root: Path, log=None, *, data_dir=None) -> dict:
    """Install an optional, separately pinned prepared iOS language package."""
    from .bundled_translations import install_translation_bundle, read_translation_metadata

    directory = Path(server_data).parent
    archive, metadata = directory / "bundledTranslations.zip", directory / "bundledTranslations.json"
    if not os.path.lexists(archive) and not os.path.lexists(metadata):
        return {"state": "absent"}
    pin = read_translation_metadata(metadata, platform="ios")
    if data_dir is None:
        raise ValueError("Installed core data directory is required for language preparation")
    from .resource_translation_runtime import validate_prepared_translations

    return install_translation_bundle(archive, cache_root, expected_sha256=pin["sha256"],
        expected_bytes=pin["bytes"], platform="ios", log=log,
        validate_prepared=lambda prepared: validate_prepared_translations(prepared, data_dir, platform="ios"))
