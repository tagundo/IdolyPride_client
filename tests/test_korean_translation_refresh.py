"""Frozen upstream download identity and bounded compressed source handling."""
import hashlib
import io
import json
from urllib.error import HTTPError
from zipfile import ZipFile

import pytest

from idoly_local.resource_translation_build import ZipScriptSource
from tools import refresh_korean_translation_bundle as refresh

REVISION = "a" * 40
URL = "https://codeload.github.com/CyleAR/ipr-translation-data-ko/zip/" + REVISION
RAW = b"existing immutable public translation archive"
MIB = 1024 * 1024


def archive_pin(raw=RAW):
    return {"archive": {"url": URL, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}}


class Response(io.BytesIO):
    status = 200

    def __init__(self, raw, *, status=200, encoding="identity"):
        super().__init__(raw)
        self.status = status
        self.headers = {"Content-Encoding": encoding}


def mock_download(monkeypatch, raw=RAW, *, status=200, encoding="identity", on_open=None):
    calls = []

    class Opener:
        def open(self, request, *, timeout):
            calls.append((request, timeout))
            if on_open is not None:
                on_open()
            return Response(raw, status=status, encoding=encoding)

    def opener(*handlers):
        assert len(handlers) == 1 and isinstance(handlers[0], refresh.NoRedirect)
        return Opener()

    monkeypatch.setattr(refresh, "build_opener", opener)
    return calls


def test_pinned_source_download_checks_identity_then_publishes_exclusively(tmp_path, monkeypatch):
    calls = mock_download(monkeypatch)
    output = tmp_path / "source.zip"
    result = refresh.fetch_source(output, pin=archive_pin())
    assert output.read_bytes() == RAW
    assert result == {k: archive_pin()["archive"][k] for k in ("bytes", "sha256")}
    assert not (tmp_path / "source.zip.partial").exists()
    assert len(calls) == 1
    request, timeout = calls[0]
    assert request.full_url == URL and timeout == 90
    assert request.get_header("Accept-encoding") == "identity"


@pytest.mark.parametrize("damage", ("too-long", "too-short", "wrong-digest", "http-status", "content-encoding"))
def test_unpinned_download_bytes_never_reach_destination(tmp_path, monkeypatch, damage):
    pin = archive_pin()
    if damage == "too-long":
        pin["archive"]["bytes"] -= 1
    elif damage == "too-short":
        pin["archive"]["bytes"] += 1
    elif damage == "wrong-digest":
        pin["archive"]["sha256"] = "0" * 64
    mock_download(monkeypatch, status=206 if damage == "http-status" else 200,
                  encoding="gzip" if damage == "content-encoding" else "identity")
    protected = tmp_path / "keep.zip"; protected.write_bytes(b"preserved")
    with pytest.raises(ValueError):
        refresh.fetch_source(tmp_path / "source.zip", pin=pin)
    assert not (tmp_path / "source.zip").exists()
    assert not (tmp_path / "source.zip.partial").exists()
    assert protected.read_bytes() == b"preserved"


@pytest.mark.parametrize("occupied", ("destination", "partial", "destination-symlink", "partial-symlink"))
def test_download_rejects_existing_or_symlink_output_before_network(tmp_path, monkeypatch, occupied):
    calls = mock_download(monkeypatch)
    output = tmp_path / "source.zip"
    protected = tmp_path / "protected"; protected.write_bytes(b"preserved")
    path = output.with_name(output.name + ".partial") if occupied.startswith("partial") else output
    if occupied.endswith("symlink"):
        path.symlink_to(protected)
    else:
        path.write_bytes(b"owned-by-another-operation")
    with pytest.raises(ValueError, match="fresh_source"):
        refresh.fetch_source(output, pin=archive_pin())
    assert not calls and path.exists()
    assert protected.read_bytes() == b"preserved"
    if not path.is_symlink():
        assert path.read_bytes() == b"owned-by-another-operation"


def test_source_publish_race_keeps_new_destination_and_retires_own_partial(tmp_path, monkeypatch):
    output = tmp_path / "source.zip"
    mock_download(monkeypatch, on_open=lambda: output.write_bytes(b"another owner"))
    with pytest.raises(FileExistsError):
        refresh.fetch_source(output, pin=archive_pin())
    assert output.read_bytes() == b"another owner"
    assert not (tmp_path / "source.zip.partial").exists()


@pytest.mark.parametrize("replacement", ("regular", "symlink"))
@pytest.mark.parametrize("valid_digest", (True, False))
def test_replaced_partial_is_neither_published_nor_deleted(tmp_path, monkeypatch, replacement, valid_digest):
    output = tmp_path / "source.zip"
    partial = tmp_path / "source.zip.partial"
    protected = tmp_path / "protected"; protected.write_bytes(b"other owner")

    class SwappingResponse(Response):
        swapped = False

        def read(self, maximum):
            if not self.swapped:
                self.swapped = True
                # The downloader already holds its original file descriptor.
                # A replacement at the same path belongs to another operation.
                partial.unlink()
                if replacement == "regular":
                    partial.write_bytes(b"replacement file")
                else:
                    partial.symlink_to(protected)
            return super().read(maximum)

    class Opener:
        def open(self, request, *, timeout):
            return SwappingResponse(RAW)

    monkeypatch.setattr(refresh, "build_opener", lambda *_handlers: Opener())
    pin = archive_pin()
    if not valid_digest:
        pin["archive"]["sha256"] = "0" * 64
    reason = "owned_partial_changed" if valid_digest else "source_digest_differs"
    with pytest.raises(ValueError, match=reason):
        refresh.fetch_source(output, pin=pin)
    assert not output.exists()
    assert protected.read_bytes() == b"other owner"
    if replacement == "regular":
        assert not partial.is_symlink() and partial.read_bytes() == b"replacement file"
    else:
        assert partial.is_symlink() and partial.readlink() == protected


def test_download_redirect_is_refused_without_followup_request(tmp_path, monkeypatch):
    calls = []

    class Opener:
        def open(self, request, *, timeout):
            calls.append(request.full_url)
            raise HTTPError(request.full_url, 302, "redirect", {"Location": "https://example.invalid/other"}, None)

    def opener(handler):
        assert isinstance(handler, refresh.NoRedirect)
        assert handler.redirect_request(None, None, 302, None, {}, "https://example.invalid/other") is None
        return Opener()

    monkeypatch.setattr(refresh, "build_opener", opener)
    with pytest.raises(HTTPError):
        refresh.fetch_source(tmp_path / "source.zip", pin=archive_pin())
    assert calls == [URL]
    assert not (tmp_path / "source.zip").exists()
    assert not (tmp_path / "source.zip.partial").exists()


def source_pin_document():
    row = {"bytes": 1, "sha256": "b" * 64}
    return {"schema": 1,
            "source": {"repository": "https://github.com/CyleAR/ipr-translation-data-ko",
                       "revision": REVISION, "data_terms": "NOASSERTION"},
            "archive": {**row, "url": URL, "prefix": "ipr-translation-data-ko-" + REVISION + "/local-files/"},
            "platforms": {platform: {"base": row.copy(), "output": row.copy(), "original_manifest": row.copy()}
                          for platform in ("android", "ios")}}


@pytest.mark.parametrize("damage", ("moving-revision", "other-origin", "bad-prefix", "archive-too-large", "bool-size", "digest"))
def test_source_manifest_cannot_relax_immutable_origin_or_size_pin(tmp_path, monkeypatch, damage):
    value = source_pin_document()
    if damage == "moving-revision":
        value["source"]["revision"] = "master"
    elif damage == "other-origin":
        value["archive"]["url"] = "https://example.invalid/public.zip"
    elif damage == "bad-prefix":
        value["archive"]["prefix"] = "../local-files/"
    elif damage == "archive-too-large":
        value["archive"]["bytes"] = 192 * MIB + 1
    elif damage == "bool-size":
        value["platforms"]["ios"]["base"]["bytes"] = True
    else:
        value["archive"]["sha256"] = "not-a-digest"
    path = tmp_path / "pin.json"; path.write_text(json.dumps(value))
    monkeypatch.setattr(refresh, "PIN", path)
    with pytest.raises(ValueError):
        refresh.pins()


def test_compressed_source_default_bound_stays_small_and_explicit_bound_accepts_large_frozen_archive(tmp_path):
    path = tmp_path / "large.zip"
    # Sparse padding models upstream's unrelated PNG payload without allocating
    # a large fixture or expanding it during the named-script read.
    with path.open("wb") as stream:
        stream.truncate(65 * MIB)
    prefix = "repo/local-files/resource/adv/"
    with ZipFile(path, "a") as archive:
        archive.writestr(prefix + "adv_bond_ai_01_09.txt", "번역된 대사")
        archive.writestr("repo/local-files/masterTrans/Unused.json", "unrelated")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    with pytest.raises(ValueError, match="Invalid pinned"):
        ZipScriptSource(path, prefix, expected_sha256=digest)
    with ZipScriptSource(path, prefix, expected_sha256=digest, max_archive_bytes=192 * MIB) as reader:
        assert reader("adv_bond_ai_01_09.txt") == "번역된 대사".encode()
        assert reader("../../masterTrans/Unused.json") is None


@pytest.mark.parametrize("maximum", (0, True, 192 * MIB + 1, "192MiB"))
def test_compressed_source_cannot_raise_bound_above_supported_maximum(tmp_path, maximum):
    path = tmp_path / "source.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("repo/adv_bond_ai_01_09.txt", "번역")
    with pytest.raises(ValueError, match="Invalid pinned"):
        ZipScriptSource(path, "repo/", expected_sha256="b" * 64, max_archive_bytes=maximum)


def test_compressed_source_rejects_archive_exceeding_explicit_maximum(tmp_path):
    path = tmp_path / "oversize.zip"
    with path.open("wb") as stream:
        stream.truncate(192 * MIB + 1)
    with pytest.raises(ValueError, match="Invalid pinned"):
        ZipScriptSource(path, "repo/", expected_sha256="b" * 64, max_archive_bytes=192 * MIB)
