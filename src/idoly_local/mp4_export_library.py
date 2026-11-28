"""Stable app-private MP4 jobs and finished files, separate from audio sessions."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import threading


def _identity(info):
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError("MP4 library requires an owned private directory")
    return info.st_dev, info.st_ino, info.st_uid, info.st_mode


class MP4ExportLibrary:
    """Keep immutable queue records and outputs across server/app restarts.

    The native queue is the sole journal writer. This object only supplies
    validated directory capabilities; filenames and paths stay out of HTTP.
    Closing the audio session never removes these directories or their files.
    """

    NAME = ".idoly-mp4-library"

    def __init__(self, app_private_dir):
        supplied = Path(app_private_dir)
        if not supplied.is_absolute():
            raise ValueError("An absolute app-private root is required")
        self._parent = supplied.resolve(strict=True)
        self._fds, self._identities = {}, {}
        self._lock = threading.Lock()
        try:
            parent = os.open(self._parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self._fds["parent"] = parent
            info = os.fstat(parent)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
                raise ValueError("MP4 library root is not owned")
            self._parent_identity = info.st_dev, info.st_ino, info.st_uid, info.st_mode
            for key, name, owner in (("library", self.NAME, "parent"),
                                     ("queue", "queue", "library"),
                                     ("exports", "exports", "library")):
                try:
                    os.mkdir(name, 0o700, dir_fd=self._fds[owner])
                except FileExistsError:
                    pass
                descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                     dir_fd=self._fds[owner])
                self._fds[key] = descriptor
                self._identities[key] = _identity(os.fstat(descriptor))
                if _identity(os.stat(name, dir_fd=self._fds[owner], follow_symlinks=False)) != self._identities[key]:
                    raise ValueError("MP4 library directory changed")
                os.fsync(self._fds[owner])
        except BaseException:
            self.close()
            raise

    def configuration(self):
        with self._lock:
            if len(self._fds) != 4:
                raise ValueError("MP4 library is closed")
            parent = self._parent.lstat()
            if (parent.st_dev, parent.st_ino, parent.st_uid, parent.st_mode) != self._parent_identity:
                raise ValueError("MP4 library root changed")
            for key, name, owner in (("library", self.NAME, "parent"),
                                     ("queue", "queue", "library"),
                                     ("exports", "exports", "library")):
                if (_identity(os.fstat(self._fds[key])) != self._identities[key]
                        or _identity(os.stat(name, dir_fd=self._fds[owner], follow_symlinks=False)) != self._identities[key]):
                    raise ValueError("MP4 library directory changed")
            root = self._parent / self.NAME
            return {"queue_directory": str(root / "queue"),
                    "persistent_export_directory": str(root / "exports")}

    def close(self):
        with self._lock:
            for descriptor in self._fds.values():
                os.close(descriptor)
            self._fds.clear()
