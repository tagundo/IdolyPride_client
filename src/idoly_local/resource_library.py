"""Explicit bulk resource preservation and portable, verified cache archives.

The library never starts a transfer during construction/status polling. It owns
its cache transports independently of the game's gateway, uses daemon workers,
and resumes completed verified objects rather than partial HTTP byte ranges.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import secrets
import shutil
import threading

from .octo_cache import OctoCache, OctoCacheError
from .octo_manifest import OctoManifest
from .octo_runtime import PLATFORM_ARCHIVES, _desktop_aes_backend, load_octo_archive


_KINDS = frozenset(("all", "assetbundle", "resources"))
_TERMINAL = frozenset(("completed", "partial", "failed", "cancelled"))
_RESERVE_BYTES = 16 * 1024 * 1024
_MAX_ERRORS = 20
DOWNLOAD_PARALLELISM = (1, 2, 4, 8)
DEFAULT_DOWNLOAD_PARALLELISM = 4
_SAFE_ERRORS = frozenset(("cache_io", "cache_closed", "download_disabled", "budget_exceeded",
    "upstream_redirect", "upstream_http", "upstream_timeout", "upstream_size", "upstream_encoding",
    "upstream_data", "upstream_digest", "conflicting_metadata", "upstream_tls", "upstream_dns",
    "upstream_connect", "invalid_selection", "catalog_unavailable", "invalid_catalog", "busy", "closed",
    "unknown_job", "not_prepared", "cancelled", "insufficient_space", "export_failed", "import_failed",
    "archive_catalog", "archive_io", "archive_source", "archive_size", "archive_digest",
    "archive_manifest", "archive_invalid", "archive_bounds", "archive_unsupported"))


class ResourceLibraryError(ValueError):
    def __init__(self, code="cache_io"):
        allowed = {"invalid_selection", "catalog_unavailable", "invalid_catalog", "busy", "closed",
                   "unknown_job", "not_prepared", "cancelled", "cache_io", "insufficient_space",
                   "export_failed", "import_failed"}
        self.code = code if code in allowed else "cache_io"
        super().__init__("Resource library: " + self.code)


@dataclass(frozen=True)
class _Catalog:
    manifest: OctoManifest
    raw: bytes
    records: tuple


@dataclass
class _Job:
    identifier: str
    action: str
    platform: str
    kind: str
    catalog: _Catalog
    records: tuple
    total_bytes: int = 0
    parallelism: int = 1
    archive_complete: bool = False
    state: str = "preparing"
    cancel: threading.Event = field(default_factory=threading.Event)
    cache: object = None
    close_started: bool = False
    workers: int = 0
    processed: int = 0
    received_by_key: dict = field(default_factory=dict)
    pending_write_by_key: dict = field(default_factory=dict)
    counts: dict = field(default_factory=lambda: {name: 0 for name in (
        "verified_files", "verified_bytes", "cache_hit_files", "downloaded_files", "received_bytes",
        "exported_files", "exported_bytes", "imported_files", "imported_bytes", "missing_files",
        "failed_files", "active_files")})
    errors: list = field(default_factory=list)
    error_code: str | None = None
    fatal: str | None = None
    local: threading.local = field(default_factory=threading.local)


class ResourceLibrary:
    # max_workers selects the default for future jobs; an explicit supported
    # per-job value can choose a different bound without changing a running job.
    def __init__(self, data_dir, catalogs=None, *, fetcher=None, max_workers=DEFAULT_DOWNLOAD_PARALLELISM,
                 base_url="http://127.0.0.1:8080", aes_cbc=None, resource_cache_dir=None):
        if type(max_workers) is not int or max_workers not in DOWNLOAD_PARALLELISM:
            raise ValueError("Resource workers must be one, two, four or eight")
        if fetcher is not None and not callable(fetcher):
            raise ValueError("Invalid resource fetcher")
        self.root = Path(data_dir).resolve()
        if not self.root.is_dir():
            raise ValueError("Resource data directory is missing")
        from .octo_runtime import resource_cache_root
        self.cache_root = resource_cache_root(self.root, resource_cache_dir)
        self._fetcher, self._workers = fetcher, max_workers
        self._base_url, self._aes = base_url, aes_cbc
        self._lock, self._catalog_lock = threading.RLock(), threading.Lock()
        self._closed, self._job = False, None
        self._catalogs, self._summaries = {}, {}
        for platform, (archive, _cache, version, revision) in PLATFORM_ARCHIVES.items():
            directory = self.root / archive
            available = (not directory.is_symlink()
                         and all((directory / name).is_file() for name in ("settings.json", "manifest.pb")))
            self._summaries[platform] = {"available": available, "loaded": False,
                "application_version": version, "revision": revision, "object_count": None,
                "total_bytes": None, "error_code": None if available else "catalog_unavailable"}
        if catalogs is not None:
            if not isinstance(catalogs, dict) or any(name not in PLATFORM_ARCHIVES for name in catalogs):
                raise ValueError("Invalid resource platform catalogs")
            for platform, manifest in catalogs.items():
                self._load_catalog(platform, existing=manifest)

    @classmethod
    def from_data_dir(cls, data_dir, *, base_url="http://127.0.0.1:8080", aes_cbc=None,
                      fetcher=None, active_gateway=None, max_workers=DEFAULT_DOWNLOAD_PARALLELISM,
                      resource_cache_dir=None):
        catalogs = {}
        if active_gateway is not None:
            manifest = getattr(active_gateway, "manifest", None)
            for platform, (_, _, version, _) in PLATFORM_ARCHIVES.items():
                if isinstance(manifest, OctoManifest) and manifest.application_version == version:
                    catalogs[platform] = manifest
        return cls(data_dir, catalogs, fetcher=fetcher, max_workers=max_workers,
                   base_url=base_url, aes_cbc=aes_cbc, resource_cache_dir=resource_cache_dir)

    def _load_catalog(self, platform, *, existing=None):
        self._selection(platform, "all")
        with self._catalog_lock:
            if platform in self._catalogs:
                return self._catalogs[platform]
            archive_name, _cache, version, revision = PLATFORM_ARCHIVES[platform]
            try:
                archive = load_octo_archive(self.root / archive_name, platform=platform)
                if archive is None:
                    raise ResourceLibraryError("catalog_unavailable")
                settings, raw = archive
                if existing is not None:
                    if (not isinstance(existing, OctoManifest) or existing.application_version != version
                            or existing.revision != revision
                            or getattr(existing, "archive_sha256", None) != settings["manifest_sha256"]):
                        raise ResourceLibraryError("invalid_catalog")
                    manifest = existing
                else:
                    manifest = OctoManifest(raw, aes_key=bytes.fromhex(settings["aes_key_hex"]),
                        client_key=settings["client_key"], base_url=self._base_url,
                        aes_cbc=self._aes if self._aes is not None else _desktop_aes_backend(),
                        application_version=version)
                if manifest.revision != revision:
                    raise ResourceLibraryError("invalid_catalog")
                records = tuple(sorted(manifest.objects.values(), key=lambda value: value.cache_key))
                catalog = _Catalog(manifest, raw, records)
            except (OSError, ValueError) as error:
                code = error.code if isinstance(error, ResourceLibraryError) else "invalid_catalog"
                with self._lock:
                    self._summaries[platform].update(available=False, loaded=False, error_code=code)
                raise ResourceLibraryError(code) from None
            self._catalogs[platform] = catalog
            with self._lock:
                self._summaries[platform].update(available=True, loaded=True, error_code=None,
                    object_count=len(records), total_bytes=sum(record.size for record in records))
            return catalog

    @staticmethod
    def _selection(platform, kind):
        if not isinstance(platform, str) or platform not in PLATFORM_ARCHIVES or not isinstance(kind, str) or kind not in _KINDS:
            raise ResourceLibraryError("invalid_selection")

    def catalog_summary(self, platform=None):
        if platform is not None:
            self._load_catalog(platform)
        with self._lock:
            return {name: dict(value) for name, value in self._summaries.items()}

    def _snapshot(self, job):
        return {"job_id": job.identifier, "action": job.action, "platform": job.platform,
            "kind": job.kind, "state": job.state, "total_files": len(job.records),
            "total_bytes": job.total_bytes, **job.counts,
            "error_code": job.error_code, "errors": [dict(value) for value in job.errors],
            "archive_complete": job.archive_complete,
            "parallelism": job.parallelism,
            "pending_write_bytes": sum(job.pending_write_by_key.values()),
            "resume_mode": "verified_objects", "partial_byte_resume": False}

    def status(self):
        with self._lock:
            return {"schema": 1, "catalogs": self.catalog_summary(),
                    "download_options": {"default_parallelism": self._workers,
                                         "supported_parallelism": list(DOWNLOAD_PARALLELISM)},
                    "storage": {"mode": "private" if self.cache_root == self.root else "public_directory"},
                    "job": None if self._job is None else self._snapshot(self._job)}

    def _reserve(self, action, platform, kind, *, parallelism=1):
        self._selection(platform, kind)
        with self._lock:
            if self._closed:
                raise ResourceLibraryError("closed")
            if self._job is not None and self._job.state not in _TERMINAL:
                raise ResourceLibraryError("busy")
        catalog = self._load_catalog(platform)
        records = tuple(record for record in catalog.records if kind == "all" or record.kind == kind)
        with self._lock:
            if self._closed:
                raise ResourceLibraryError("closed")
            if self._job is not None and self._job.state not in _TERMINAL:
                raise ResourceLibraryError("busy")
            job = _Job(secrets.token_hex(16), action, platform, kind, catalog, records,
                       total_bytes=sum(record.size for record in records), parallelism=parallelism)
            self._job = job
            return job

    def _get(self, identifier):
        if (not isinstance(identifier, str) or self._job is None
                or identifier != self._job.identifier):
            raise ResourceLibraryError("unknown_job")
        return self._job

    def _close_cache(self, job):
        with self._lock:
            cache = job.cache
            if cache is None or job.close_started:
                return
            job.close_started = True
        def close():
            try:
                cache.close()
            except Exception:
                pass
            finally:
                with self._lock:
                    if job.cache is cache:
                        job.cache = None
        threading.Thread(target=close, name="IdolyResourceClose", daemon=True).start()

    def cancel(self, identifier):
        with self._lock:
            job = self._get(identifier)
            if job.state not in _TERMINAL:
                job.cancel.set()
                job.state = "cancelled" if job.state == "export_ready" else "cancelling"
        self._close_cache(job)
        with self._lock:
            return self._snapshot(job)

    def close(self):
        # Never join worker/network threads or close a possibly blocking
        # transport on the launcher's shutdown thread.
        with self._lock:
            self._closed = True
            job = self._job
        if job is not None:
            self.cancel(job.identifier)

    def _observe(self, job, event):
        with self._lock:
            if self._job is not job or job.cancel.is_set() or job.state in _TERMINAL:
                return
            phase, key, received = event.get("phase"), event.get("cache_key"), event.get("received_bytes", 0)
            if phase == "cache_hit":
                job.pending_write_by_key.pop(key, None)
                job.counts["cache_hit_files"] += 1
            elif phase == "started":
                job.received_by_key[key] = 0
                job.counts["active_files"] = len(job.received_by_key)
            elif phase in ("progress", "verified", "failed") and key in job.received_by_key:
                previous = job.received_by_key[key]
                job.counts["received_bytes"] += max(0, received - previous) if job.action == "download" else 0
                job.received_by_key[key] = received
                if phase in ("verified", "failed"):
                    job.received_by_key.pop(key)
                    job.counts["active_files"] = len(job.received_by_key)
                    if phase == "verified" and job.action == "download":
                        job.counts["downloaded_files"] += 1

    def _cache(self, job, *, download, fetcher=None):
        from .octo_runtime import resource_cache_paths
        try:
            path, seed_dirs = resource_cache_paths(self.root, self.cache_root, job.platform)
        except (ValueError, OSError):
            raise ResourceLibraryError("cache_io") from None

        def write_guard(record, phase, written):
            key = record.cache_key
            # A finish callback must release even after cancellation or a new
            # terminal job. No cache/commit lock is acquired under our lock.
            if phase == "finish":
                with self._lock:
                    job.pending_write_by_key.pop(key, None)
                return
            if (job.catalog.manifest.objects.get(record.identity) != record
                    or job.kind != "all" and record.kind != job.kind):
                raise OctoCacheError("cache_io")
            with self._lock:
                if self._closed or job.cancel.is_set() or self._job is not job:
                    raise OctoCacheError("cache_closed")
                insufficient = False
                if phase == "start":
                    # Remaining bytes of other active writes are not yet in
                    # disk_usage. Already-written bytes are reflected there.
                    insufficient = (shutil.disk_usage(path).free
                        < record.size + sum(job.pending_write_by_key.values()) + _RESERVE_BYTES)
                    if insufficient:
                        job.fatal = job.error_code = "insufficient_space"
                        job.cancel.set()
                    else:
                        job.pending_write_by_key[key] = record.size
                elif phase == "progress":
                    if (key not in job.pending_write_by_key or type(written) is not int
                            or not 0 <= written <= record.size):
                        raise OctoCacheError("cache_io")
                    job.pending_write_by_key[key] = record.size - written
                else:
                    raise OctoCacheError("cache_io")
            if insufficient:
                self._close_cache(job)
                raise OctoCacheError("cache_io")

        if download:
            provided = fetcher or self._fetcher
            def fetcher(url, *, timeout):
                record = getattr(job.local, "record", None)
                if record is None or url != record.upstream_url:
                    raise OctoCacheError("cache_io")
                with self._lock:
                    if self._closed or job.cancel.is_set() or self._job is not job:
                        raise OctoCacheError("cache_closed")
                if provided is not None:
                    return provided(url, timeout=timeout)
                from .octo_cache import open_upstream
                return open_upstream(url, timeout=timeout)
        cache = OctoCache(path, fetcher=fetcher, allow_download=download, seed_dirs=seed_dirs,
            max_parallel=job.parallelism, max_object_bytes=2**31-1, total_timeout=900,
            on_event=lambda event: self._observe(job, event), write_guard=write_guard)
        with self._lock:
            job.cache = cache
            cancelled = self._closed or job.cancel.is_set()
        if cancelled:
            self._close_cache(job)
            raise ResourceLibraryError("cancelled")
        return cache

    def _error(self, job, error, record=None, *, fallback="cache_io"):
        code = getattr(error, "code", fallback)
        if not isinstance(code, str) or code not in _SAFE_ERRORS:
            code = fallback
        with self._lock:
            if not job.cancel.is_set():
                job.counts["failed_files"] += 1
                job.error_code = code
                if len(job.errors) < _MAX_ERRORS:
                    job.errors.append({"cache_key": record.cache_key if record is not None else None,
                                       "error_code": code})

    def _finish(self, job):
        with self._lock:
            job.counts["active_files"] = 0
            job.pending_write_by_key.clear()
            if job.fatal:
                job.state, job.error_code = "failed", job.fatal
            elif job.cancel.is_set():
                job.state = "cancelled"
            elif job.counts["failed_files"] or job.counts["missing_files"]:
                job.state = "partial" if job.counts["verified_files"] or job.action == "export" and not job.counts["failed_files"] else "failed"
            elif job.counts["verified_files"] != len(job.records):
                job.state = "partial" if job.counts["verified_files"] else "failed"
                job.error_code = job.error_code or "cache_io"
            else:
                job.state = "completed"
        self._close_cache(job)

    def start_download(self, platform, kind="all", *, parallelism=None):
        # Freeze the selected bound for this job. Commands can select a new
        # speed for a later job without changing any running cache semaphore.
        parallelism = self._workers if parallelism is None else parallelism
        if type(parallelism) is not int or parallelism not in DOWNLOAD_PARALLELISM:
            raise ResourceLibraryError("invalid_selection")
        job = self._reserve("download", platform, kind, parallelism=parallelism)
        try:
            cache = self._cache(job, download=True)
        except Exception as error:
            self._error(job, error)
            self._finish(job)
            raise ResourceLibraryError(getattr(error, "code", "cache_io")) from None
        with self._lock:
            job.state, job.workers = "running", job.parallelism
        def worker():
            try:
                while True:
                    with self._lock:
                        if job.cancel.is_set() or job.processed == len(job.records):
                            break
                        record = job.records[job.processed]
                        job.processed += 1
                    try:
                        job.local.record = record
                        with cache.open_verified(record):
                            pass
                        with self._lock:
                            if not job.cancel.is_set():
                                job.counts["verified_files"] += 1
                                job.counts["verified_bytes"] += record.size
                    except Exception as error:
                        self._error(job, error, record)
                    finally:
                        with self._lock:
                            job.pending_write_by_key.pop(record.cache_key, None)
                        job.local.record = None
            finally:
                with self._lock:
                    job.workers -= 1
                    done = job.workers == 0
                if done:
                    self._finish(job)
        for index in range(job.parallelism):
            try:
                threading.Thread(target=worker, name="IdolyResourceDownload", daemon=True).start()
            except RuntimeError:
                with self._lock:
                    job.workers -= job.parallelism - index
                    job.fatal = job.error_code = "cache_io"
                    job.cancel.set()
                    done = job.workers == 0
                if done:
                    self._finish(job)
                else:
                    self._close_cache(job)
                raise ResourceLibraryError("cache_io") from None
        with self._lock:
            return self._snapshot(job)

    def prepare_export(self, platform, kind="all"):
        job = self._reserve("export", platform, kind)
        try:
            self._cache(job, download=False)
        except Exception as error:
            self._error(job, error)
            self._finish(job)
            raise ResourceLibraryError(getattr(error, "code", "cache_io")) from None
        with self._lock:
            job.state = "export_ready"
            return {**self._snapshot(job), "filename":
                f"IdolyPride-Resources-{platform}{'-' + kind if kind != 'all' else ''}-r{job.catalog.manifest.revision}.zip"}

    def write_export(self, identifier, output):
        from .resource_archive import write_archive
        with self._lock:
            job = self._get(identifier)
            if job.action != "export" or job.state != "export_ready":
                raise ResourceLibraryError("not_prepared")
            job.state = "running"
        def copied(record):
            with self._lock:
                if not job.cancel.is_set():
                    job.counts["verified_files"] += 1
                    job.counts["verified_bytes"] += record.size
                    job.counts["exported_files"] += 1
                    job.counts["exported_bytes"] += record.size
        try:
            result = write_archive(output, platform=job.platform, manifest_bytes=job.catalog.raw,
                revision=job.catalog.manifest.revision,
                application_version=job.catalog.manifest.application_version, records=job.records,
                open_verified=job.cache.open_verified, cancel_event=job.cancel, on_file=copied, kind=job.kind)
            with self._lock:
                job.counts["missing_files"] = result["missing_files"]
                job.archive_complete = True
        except Exception as error:
            self._error(job, error, fallback="export_failed")
            self._finish(job)
            raise ResourceLibraryError("cancelled" if job.cancel.is_set() else "export_failed") from None
        self._finish(job)
        with self._lock:
            return self._snapshot(job)

    def import_from(self, source, platform, kind="all"):
        from .resource_archive import VerifiedResourceArchive
        job = self._reserve("import", platform, kind)
        try:
            with VerifiedResourceArchive(source, platform=platform, manifest_bytes=job.catalog.raw,
                                          records=job.catalog.records) as archive:
                rows = tuple(record for record in archive.objects if kind == "all" or record.kind == kind)
                with self._lock:
                    job.records, job.state = rows, "running"
                    job.total_bytes = sum(record.size for record in rows)
                cache = self._cache(job, download=True, fetcher=archive.fetch)
                for record in rows:
                    if job.cancel.is_set():
                        break
                    try:
                        job.local.record = record
                        with cache.open_verified(record):
                            pass
                        with self._lock:
                            if not job.cancel.is_set():
                                job.counts["verified_files"] += 1
                                job.counts["verified_bytes"] += record.size
                                job.counts["imported_files"] += 1
                                job.counts["imported_bytes"] += record.size
                    except Exception as error:
                        self._error(job, error, record, fallback="import_failed")
                    finally:
                        with self._lock:
                            job.pending_write_by_key.pop(record.cache_key, None)
                        job.local.record = None
        except Exception as error:
            self._error(job, error, fallback="import_failed")
            self._finish(job)
            raise ResourceLibraryError("cancelled" if job.cancel.is_set() else "import_failed") from None
        self._finish(job)
        with self._lock:
            return self._snapshot(job)
