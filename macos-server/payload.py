"""Install bundled public server files without writing to user profiles or state."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import os
from zipfile import ZipFile

FIXED_FILES = {
    "payload-manifest.json",
    "public-fixtures/manifest.json",
    "public-tutorial/manifest.json",
    "public-tutorial/tutorial-short.pb",
    "public-tutorial/tutorial-full.pb",
    "public-story/manifest.json",
    "public-story/story-list-event.pb",
    "public-story/story-list-extra.pb",
    "protocol/idolypride-6.1.1.pb",
    "protocol/idolypride-6.1.1.evidence.json",
    "original-master/response.pb",
    "original-master/master-tag.json",
    "original-master/archive-report.json",
}
PACK_PREFIX = "original-master/assets/master/"


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


def install_payload(source: Path, data_dir: Path, log=None) -> dict:
    """Copy only missing public files; existing state and files remain intact."""
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
