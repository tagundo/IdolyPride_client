"""Pinned GitHub asset and local input admission without remote downloads."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import time
from zipfile import ZipFile

import pytest


MODULE = Path(__file__).resolve().parents[1] / "ios-unified/fetch_inputs.py"
spec = importlib.util.spec_from_file_location("ios_unified_fetch", MODULE)
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)


def pin(raw, **extra):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), **extra}


def stock_pin(raw):
    return pin(raw, asset_id=fetch.RELEASE_ASSET_ID, filename=fetch.RELEASE_ASSET_NAME)


def metadata(row, **changes):
    return json.dumps({"id": row["asset_id"], "name": row["filename"],
                       "size": row["bytes"], "state": "uploaded", **changes}).encode()


class Process:
    """A pipe-backed owned subprocess fixture; no command is executed."""

    def __init__(self, raw, *, code=0):
        incoming, self.writer = os.pipe()
        self.stdout = os.fdopen(incoming, "rb", buffering=0)
        self.code = code
        self.returncode = None
        self.killed = 0
        if raw is not None:
            assert len(raw) < 4096
            os.write(self.writer, raw)
            os.close(self.writer)
            self.writer = None

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed += 1
        self.returncode = -9
        if self.writer is not None:
            os.close(self.writer)
            self.writer = None

    def wait(self, timeout=None):
        if self.returncode is None:
            if self.writer is not None:
                raise subprocess.TimeoutExpired("owned fixture", timeout)
            self.returncode = self.code
        return self.returncode


def processes(monkeypatch, responses, *, on_start=None):
    started, commands = [], []
    monkeypatch.setenv("GH_TOKEN", "synthetic-token-never-an-argument")

    def popen(command, **kwargs):
        assert kwargs == {"stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE,
                          "stderr": subprocess.DEVNULL}
        commands.append(command)
        if on_start is not None:
            on_start(len(started))
        process = Process(responses[len(started)])
        started.append(process)
        return process

    monkeypatch.setattr(fetch.subprocess, "Popen", popen)
    return started, commands


def test_fixed_asset_metadata_then_streamed_body(monkeypatch, tmp_path, capsys):
    raw = b"PK\x03\x04synthetic-public-ipa"
    row = stock_pin(raw)
    started, commands = processes(monkeypatch, [metadata(row), raw])
    output = tmp_path / "stock.ipa"
    fetch.release_asset_download(row, output)
    assert output.read_bytes() == raw
    assert not output.with_name("stock.ipa.partial").exists()
    assert [command[:5] for command in commands] == [
        ["gh", "api", "--hostname", "github.com",
         "repos/tagundo/IdolyPride_client/releases/assets/725761399"]] * 2
    assert [command[-1] for command in commands] == ["Accept: application/vnd.github+json",
                                                       "Accept: application/octet-stream"]
    assert not any("synthetic-token" in value or "://" in value for command in commands for value in command)
    assert all(process.returncode == 0 and process.killed == 0 for process in started)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("changes", [{"id": 1}, {"id": True}, {"name": "other.ipa"},
                                     {"size": 999}, {"size": True}, {"state": "new"}])
def test_changed_asset_metadata_never_starts_body(monkeypatch, tmp_path, changes):
    row = stock_pin(b"public")
    started, _ = processes(monkeypatch, [metadata(row, **changes)])
    with pytest.raises(ValueError, match="Release asset metadata differs"):
        fetch.release_asset_download(row, tmp_path / "stock.ipa")
    assert len(started) == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("raw", [b"[]", b"null", b"{", b"\xff", b'"signed-url-must-not-appear"'])
def test_malformed_asset_metadata_is_sanitized(monkeypatch, tmp_path, raw):
    row = stock_pin(b"public")
    started, _ = processes(monkeypatch, [raw])
    with pytest.raises(ValueError, match="^Release asset metadata (?:invalid|differs)$"):
        fetch.release_asset_download(row, tmp_path / "stock.ipa")
    assert len(started) == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("changes", [{"asset_id": 1}, {"asset_id": True}, {"filename": "../other"},
                                     {"bytes": -1}, {"bytes": True}, {"sha256": "not-a-digest"}])
def test_invalid_manifest_pin_rejected_before_gh(monkeypatch, tmp_path, changes):
    started, _ = processes(monkeypatch, [])
    row = {**stock_pin(b"public"), **changes}
    with pytest.raises(ValueError):
        fetch.release_asset_download(row, tmp_path / "stock.ipa")
    assert started == []


@pytest.mark.parametrize("body", [b"wrong!", b"pub", b"public-extra"])
def test_wrong_asset_body_retires_only_its_partial(monkeypatch, tmp_path, body):
    row = stock_pin(b"public")
    processes(monkeypatch, [metadata(row), body])
    untouched = tmp_path / "unrelated"; untouched.write_bytes(b"keep")
    with pytest.raises(ValueError, match="(?:digest differs|response exceeds bound)"):
        fetch.release_asset_download(row, tmp_path / "stock.ipa")
    assert not (tmp_path / "stock.ipa").exists()
    assert not (tmp_path / "stock.ipa.partial").exists()
    assert untouched.read_bytes() == b"keep"


def test_nonzero_cli_exit_retires_partial(monkeypatch, tmp_path):
    raw = b"public"; row = stock_pin(raw)
    started, _ = processes(monkeypatch, [metadata(row), raw])
    # Alter only the owned body process's exit status, after construction.
    original = fetch.subprocess.Popen
    def failing(command, **kwargs):
        process = original(command, **kwargs)
        if len(started) == 2:
            process.code = 7
        return process
    monkeypatch.setattr(fetch.subprocess, "Popen", failing)
    with pytest.raises(ValueError, match="^Release asset request failed$"):
        fetch.release_asset_download(row, tmp_path / "stock.ipa")
    assert list(tmp_path.iterdir()) == []


def test_timeout_kills_only_its_own_cli(monkeypatch):
    started, _ = processes(monkeypatch, [None])
    before = time.monotonic()
    with pytest.raises(ValueError, match="^Release asset request timed out$"):
        fetch._gh_api_stream("application/vnd.github+json", lambda block: None, 20, timeout=0.02)
    assert time.monotonic() - before < 2
    assert len(started) == 1 and started[0].killed == 1
    assert started[0].stdout.closed


def test_destination_appearing_during_download_is_not_replaced(monkeypatch, tmp_path):
    raw = b"public"; row = stock_pin(raw)
    output = tmp_path / "stock.ipa"
    processes(monkeypatch, [metadata(row), raw], on_start=lambda index: output.write_bytes(b"other") if index == 1 else None)
    with pytest.raises(ValueError, match="Fresh build input path required"):
        fetch.release_asset_download(row, output)
    assert output.read_bytes() == b"other"
    assert not output.with_name("stock.ipa.partial").exists()


@pytest.mark.parametrize("kind", ["file", "symlink", "partial"])
def test_existing_output_or_partial_never_touched(monkeypatch, tmp_path, kind):
    output = tmp_path / "stock.ipa"
    preserved = output.with_name("stock.ipa.partial") if kind == "partial" else output
    if kind == "symlink":
        preserved.symlink_to(tmp_path / "missing")
    else:
        preserved.write_bytes(b"keep")
    started, _ = processes(monkeypatch, [])
    with pytest.raises(ValueError, match="Fresh build input path required"):
        fetch.release_asset_download(stock_pin(b"public"), output)
    assert started == []
    assert preserved.is_symlink() if kind == "symlink" else preserved.read_bytes() == b"keep"


def local_input(monkeypatch, tmp_path, filename="en.csv"):
    root = tmp_path / "code"; folder = root / "client-language-inputs"; folder.mkdir(parents=True)
    source = folder / filename; source.write_bytes(b"source,translation\nhello,world\n")
    monkeypatch.setattr(fetch, "HERE", root)
    return source, tmp_path / "output" / filename, pin(source.read_bytes(), filename=filename)


@pytest.mark.parametrize("filename", ["en.csv", "en-report.json"])
def test_local_pinned_inputs_use_verified_copies(monkeypatch, tmp_path, filename):
    source, output, row = local_input(monkeypatch, tmp_path, filename)
    fetch.copy_local_pinned(filename, output, row)
    assert output.read_bytes() == source.read_bytes()
    assert output.stat().st_ino != source.stat().st_ino
    assert not output.with_name(output.name + ".partial").exists()


def test_local_bad_digest_cleans_partial_and_keeps_source(monkeypatch, tmp_path):
    source, output, row = local_input(monkeypatch, tmp_path)
    original = source.read_bytes()
    row["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="Donor member digest differs"):
        fetch.copy_local_pinned("en.csv", output, row)
    assert source.read_bytes() == original
    assert not output.exists() and not output.with_name("en.csv.partial").exists()


def test_local_symlink_is_rejected(monkeypatch, tmp_path):
    source, output, row = local_input(monkeypatch, tmp_path)
    original = source.with_name("actual.csv"); source.rename(original); source.symlink_to(original)
    with pytest.raises(ValueError, match="regular file"):
        fetch.copy_local_pinned("en.csv", output, row)
    assert source.is_symlink() and original.exists() and not output.exists()


def test_local_copy_does_not_retire_a_foreign_racing_partial(monkeypatch, tmp_path):
    source, output, row = local_input(monkeypatch, tmp_path)
    original = fetch.copy_pinned
    def raced(incoming, partial, settings, **kwargs):
        partial.write_bytes(b"foreign")
        return original(incoming, partial, settings, **kwargs)
    monkeypatch.setattr(fetch, "copy_pinned", raced)
    with pytest.raises(FileExistsError):
        fetch.copy_local_pinned("en.csv", output, row)
    assert output.with_name("en.csv.partial").read_bytes() == b"foreign"
    assert source.exists() and not output.exists()


def test_local_source_mutation_during_copy_is_rejected(monkeypatch, tmp_path):
    source, output, row = local_input(monkeypatch, tmp_path)
    original = fetch.copy_pinned
    def changed(incoming, partial, settings, **kwargs):
        original(incoming, partial, settings, **kwargs)
        old = source.stat().st_mtime_ns
        os.utime(source, ns=(old + 1_000_000_000, old + 1_000_000_000))
    monkeypatch.setattr(fetch, "copy_pinned", changed)
    with pytest.raises(ValueError, match="Pinned English input changed"):
        fetch.copy_local_pinned("en.csv", output, row)
    assert not output.exists() and not output.with_name("en.csv.partial").exists()


def test_main_fetches_fixed_new_input_names_and_records_hashes(monkeypatch, tmp_path):
    root = tmp_path / "code"; root.mkdir()
    sample = pin(b"public")
    manifest = {"support": {**sample, "filename": "support.tar.gz", "url": "https://example.invalid/support"},
                "pure_wheels": [], "inputs": {"base_ipa": sample, "stock_ipa": stock_pin(b"public"),
                    "english_ui": {**sample, "filename": "en.csv"},
                    "english_ui_proof": {**sample, "filename": "en-report.json"},
                    "server_data": sample, "translations": sample}}
    (root / "runtime_inputs.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(fetch, "HERE", root)
    output = tmp_path / "inputs"
    calls = []
    def zipped(names):
        data = io.BytesIO()
        with ZipFile(data, "w") as archive:
            for name in names: archive.writestr(name, b"public")
        return data.getvalue()
    def lfs(row, path):
        calls.append(path.name)
        names = ([fetch.DONOR_ROOT + name for name in ("ServerData.zip", "bundledTranslations.zip")]
                 if path.name == "donor-macos.zip" else ["Payload/IDOLY PRIDE.app/Frameworks/IdolyPresentation.dylib"])
        path.write_bytes(zipped(names))
    monkeypatch.setattr(fetch, "lfs_download", lfs)
    monkeypatch.setattr(fetch, "download", lambda url, row, path: path.write_bytes(b"public"))
    monkeypatch.setattr(fetch, "release_asset_download", lambda row, path: (calls.append(path.name), path.write_bytes(b"public")))
    monkeypatch.setattr(fetch, "copy_local_pinned", lambda name, path, row: (calls.append(path.name), path.write_bytes(b"public")))
    monkeypatch.setattr(fetch, "copy_pinned", lambda incoming, path, row: path.write_bytes(incoming.read()))
    monkeypatch.setattr(fetch, "__name__", "ios_unified_fetch_fixture")
    monkeypatch.setattr("sys.argv", [str(MODULE), "--output", str(output)])
    fetch.main()
    assert calls == ["base.ipa", "stock.ipa", "en.csv", "en-report.json", "donor-macos.zip"]
    report = json.loads((output / "fetch-report.json").read_text())
    assert report["stock_ipa_sha256"] == manifest["inputs"]["stock_ipa"]["sha256"]
    assert report["english_ui_sha256"] == manifest["inputs"]["english_ui"]["sha256"]
    assert report["english_ui_proof_sha256"] == manifest["inputs"]["english_ui_proof"]["sha256"]
    assert report["verified"] is True and report["Mac_executable_bundled"] is False
    assert not (output / "donor-macos.zip").exists()
