import hashlib
import importlib.util
import io
import json
import marshal
import os
from pathlib import Path
import struct
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest

from tools import repack_android_server_python as tool


def runtime_sources(extra=b""):
    return {"idoly_local/__init__.pyc": ("src/idoly_local/__init__.py", b""),
            "android_server_runtime.pyc": ("android-server/app/src/main/python/android_server_runtime.py", extra),
            "idoly_local/android_package.pyc": ("src/idoly_local/android_package.py", b"raise RuntimeError('offline tool must never load')\n")}


@pytest.mark.parametrize("source", [
    b"import idoly_local.android_package\n", b"from idoly_local import android_package\n",
    b"def late():\n from idoly_local.android_package import package_android\n",
    b"import importlib as loader\nloader.import_module('idoly_local.android_package')\n",
    b"from importlib import import_module as load\nload('.android_package', 'idoly_local')\n",
    b"__import__('idoly_local.android_package')\n",
    b"import builtins as b\nb.__import__('idoly_local.android_package')\n",
    b"from builtins import __import__ as load\nload('idoly_local.android_package')\n",
    b"from idoly_local import font_assets\n",
    b"def build_on_device():\n import idoly_local.font_assets\n",
    b"from idoly_local import translation_bundle_build\n"])
def test_android_exclusions_reject_static_and_literal_dynamic_imports_in_all_scopes(source):
    with pytest.raises(ValueError, match="excluded offline"):
        tool.android_runtime_sources(runtime_sources(source))


@pytest.mark.parametrize("source", [
    b"import importlib\nimportlib.import_module(module_name)\n",
    b"__import__(module_name)\n",
    b"__import__('idoly_local', fromlist=['android_package'])\n",
    b"import importlib\nload=importlib.import_module\nload(module_name)\n",
    b"import importlib\ngetattr(importlib,'import_module')(module_name)\n",
    b"import importlib\nimportlib.__dict__['import_module'](module_name)\n",
    b"exec(source)\n"])
def test_android_exclusions_do_not_silently_ignore_unknown_dynamic_import_forms(source):
    with pytest.raises(ValueError, match="dynamic"):
        tool.android_runtime_sources(runtime_sources(source))


def test_android_exclusions_refuse_ambiguous_internal_wildcard_import():
    with pytest.raises(ValueError,match="wildcard"):
        tool.android_runtime_sources(runtime_sources(b"from idoly_local import *\n"))


def test_android_policy_keeps_literal_external_descriptor_import_and_runtime_capture():
    sources=runtime_sources(b"import importlib\nimportlib.import_module('papi_pb2')\nfrom idoly_local import dream_capture\n")
    sources['idoly_local/dream_capture.pyc']=('src/idoly_local/dream_capture.py',b'VALUE=1\n')
    selected=tool.android_runtime_sources(sources)
    assert 'idoly_local/android_package.pyc' not in selected
    assert 'idoly_local/dream_capture.pyc' in selected
    assert len(tool.ANDROID_EXCLUDED_MODULES)==37
    assert {'idoly_local.' + name for name in ('static_ui_assets', 'static_ui_images',
            'ui_text_finishes', 'ui_display_literals')} <= tool.ANDROID_EXCLUDED_MODULES
    assert "idoly_local.story_loading_prefab" in tool.ANDROID_EXCLUDED_MODULES
    assert 'idoly_local.font_assets' in tool.ANDROID_EXCLUDED_MODULES


def test_android_compiler_removes_only_explicit_offline_modules(case):
    sources=runtime_sources();original=app_zip({name:value[1] for name,value in sources.items()})
    app,rows=tool.compile_app(original,sources,123)
    with ZipFile(io.BytesIO(app)) as archive:
        assert set(archive.namelist())-{'__pycache__/'}=={'idoly_local/__init__.pyc','android_server_runtime.pyc'}
    assert len(rows)==2 and all(row['code_object_matches_source'] for row in rows)
    unknown=app_zip({**{name:value[1] for name,value in sources.items()},'idoly_local/unknown.pyc':b'VALUE=1'})
    with pytest.raises(ValueError,match='omit an existing'):
        tool.compile_app(unknown,sources,123)


def test_real_android_source_selection_keeps_new_runtime_features_and_excludes_host_builders():
    root=Path(__file__).resolve().parents[1]
    sources={'idoly_local/'+p.stem+'.pyc':(str(p.relative_to(root)),p.read_bytes())
             for p in (root/'src/idoly_local').glob('*.py')}
    bridge=root/'android-server/app/src/main/python/android_server_runtime.py'
    sources['android_server_runtime.pyc']=(str(bridge.relative_to(root)),bridge.read_bytes())
    selected=tool.android_runtime_sources(sources)
    assert len(selected)==len(sources)-len(sources.keys() & tool.ANDROID_EXCLUDED_MEMBERS)
    assert len(sources.keys() & tool.ANDROID_EXCLUDED_MEMBERS)==37
    for name in ("font_assets", "resource_translation_build", "text_translation_build", "ui_translation_build", "ui_assets", "translation_bundle_build"):
        assert 'idoly_local/'+name+'.pyc' not in selected
    for name in ("language_settings", "media_settings", "master_sort", "resource_library", "resource_archive", "resource_routes"):
        assert "idoly_local/"+name+".pyc" in selected
    assert 'idoly_local/render_probe.pyc' in selected
    assert 'idoly_local/dream_capture.pyc' in selected
    assert not selected.keys() & tool.ANDROID_EXCLUDED_MEMBERS


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL).strip().decode()


def commit(root):
    git(root, "add", ".")
    git(root, "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid",
        "commit", "-qm", "synthetic fixture")
    return git(root, "rev-parse", "HEAD")


def pyc(source, filename):
    return (importlib.util.MAGIC_NUMBER + struct.pack("<III", 0, 1, len(source))
            + marshal.dumps(compile(source, filename, "exec", dont_inherit=True, optimize=0)))


def app_zip(sources):
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(ZipInfo("__pycache__/", (1980, 2, 1, 0, 0, 0)), b"")
        for name, source in sources.items():
            info = ZipInfo(name, (1980, 2, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            archive.writestr(info, pyc(source, Path(name).with_suffix(".py").name))
    return output.getvalue()


@pytest.fixture
def case(tmp_path, monkeypatch):
    # Synthetic archives use the running test interpreter. Production remains
    # pinned to CPython3.13; its mismatch guard has a separate test below.
    monkeypatch.setattr(tool, "PYTHON_VERSION", sys.version_info[:2])
    monkeypatch.setattr(tool, "PYC_MAGIC", importlib.util.MAGIC_NUMBER)
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    files = {"src/idoly_local/__init__.py": b"",
             "src/idoly_local/logic.py": b"def outer():\n    def inner():\n        return 2\n    return inner()\n",
             "src/idoly_local/added.py": b"VALUE = 3\n",
             "android-server/app/src/main/python/android_server_runtime.py": b"VALUE = 'bridge'\n"}
    for name, raw in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    (root / "private").mkdir()
    (root / "private/password").write_bytes(b"synthetic private neighbor, never an input")
    source_commit = commit(root)
    old = {"idoly_local/__init__.pyc": b"",
           "idoly_local/logic.pyc": files["src/idoly_local/logic.py"].replace(b"return 2", b"return 1"),
           "android_server_runtime.pyc": files["android-server/app/src/main/python/android_server_runtime.py"]}
    original_app = app_zip(old)
    payload = b"synthetic public server data"
    baseline = tmp_path / "baseline.apk"

    def write_baseline(app=original_app, build=None, zero_attr_compression=None):
        build = build if build is not None else json.dumps({
            "assets": {"app.imy": hashlib.sha1(app).hexdigest(), "bootstrap.imy": "f" * 40},
            "extract_packages": [], "python_version": "3.13"}).encode()
        with ZipFile(baseline, "w") as archive:
            archive.comment = b"retain archive comment"
            for name, raw in {tool.APP: app, tool.BUILD: build, tool.PAYLOAD: payload,
                              "classes.dex": b"synthetic DEX unchanged", "AndroidManifest.xml": b"version23 unchanged",
                              "resources.arsc": b"resources unchanged", "lib/arm64-v8a/libidoly_live.so": b"engine unchanged"}.items():
                info = ZipInfo(name, (1980, 2, 1, 0, 0, 0))
                info.compress_type = ZIP_STORED if name in (tool.APP, tool.PAYLOAD, "resources.arsc") else ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                info.comment = b"retain member comment"
                if name == "classes.dex" and zero_attr_compression is not None:
                    info.compress_type = zero_attr_compression
                archive.writestr(info, raw)
                if name == "classes.dex" and zero_attr_compression is not None:
                    info.external_attr = 0
        monkeypatch.setattr(tool, "BASELINE_SHA256", tool.digest(baseline))
        monkeypatch.setattr(tool, "PAYLOAD_SHA256", hashlib.sha256(payload).hexdigest())
    write_baseline()
    return root, source_commit, baseline, tmp_path / "candidate.apk", write_baseline


def run(case, **kwargs):
    root, source_commit, baseline, output, _ = case
    return tool.repack(baseline, root, source_commit, output, epoch=12345678, **kwargs)


def test_only_two_assets_change_all_committed_modules_and_cache_hash_match(case):
    root, source_commit, baseline, output, _ = case
    original = baseline.read_bytes()
    # A changing worktree must not silently replace the declared commit's code.
    (root / "src/idoly_local/logic.py").write_text("raise RuntimeError('worktree must not run')\n")
    report = run(case)
    assert baseline.read_bytes() == original
    assert report["source_commit"] == source_commit
    assert report["changed_apk_members"] == sorted((tool.APP, tool.BUILD))
    assert not report["signed"] and not report["aligned"] and not report["runtime_verified"]
    assert len(report["modules"]) == 4
    assert not any("private" in row["source"] for row in report["modules"])
    with ZipFile(baseline) as before, ZipFile(output) as after:
        assert before.namelist() == after.namelist()
        assert before.comment == after.comment
        for name in before.namelist():
            if name not in (tool.APP, tool.BUILD):
                assert before.read(name) == after.read(name)
        old_build, new_build = json.loads(before.read(tool.BUILD)), json.loads(after.read(tool.BUILD))
        app = after.read(tool.APP)
        assert new_build["assets"].pop("app.imy") == hashlib.sha1(app).hexdigest()
        old_build["assets"].pop("app.imy")
        assert new_build == old_build
    with ZipFile(io.BytesIO(app)) as archive:
        for row in report["modules"]:
            raw = archive.read(row["member"])
            assert raw[:8] == importlib.util.MAGIC_NUMBER + b"\0" * 4
            assert int.from_bytes(raw[8:12], "little") == 12345678
            assert hashlib.sha256(raw).hexdigest() == row["pyc_sha256"]
            assert row["code_object_matches_source"]
        namespace = {}
        exec(marshal.loads(archive.read("idoly_local/logic.pyc")[16:]), namespace)
        assert namespace["outer"]() == 2
        assert "idoly_local/added.pyc" in archive.namelist()
    assert json.loads(output.with_suffix(".provenance.json").read_text()) == report


def test_zip_reads_are_bounded_and_do_not_use_whole_member_read(case, monkeypatch):
    import zipfile
    original = zipfile.ZipExtFile.read
    def bounded(self, size=-1):
        assert 0 <= size <= tool.MAX_APP + 1
        return original(self, size)
    monkeypatch.setattr(zipfile.ZipExtFile, "read", bounded)
    monkeypatch.setattr(ZipFile, "read", lambda *a, **k: pytest.fail("unbounded ZipFile.read"))
    run(case)


@pytest.mark.parametrize("compression", [ZIP_STORED, ZIP_DEFLATED])
def test_zero_external_attrs_survive_both_compression_methods(case, compression):
    case[4](zero_attr_compression=compression)
    with ZipFile(case[2]) as archive:
        assert archive.getinfo("classes.dex").external_attr == 0
    run(case)
    with ZipFile(case[3]) as archive:
        assert archive.getinfo("classes.dex").external_attr == 0
        assert archive.getinfo("classes.dex").compress_type == compression


def test_wrong_compiler_and_baseline_fail_before_output(case, monkeypatch):
    monkeypatch.setattr(tool, "PYTHON_VERSION", (0, 0))
    with pytest.raises(ValueError, match="CPython"):
        run(case)
    monkeypatch.setattr(tool, "PYTHON_VERSION", sys.version_info[:2])
    monkeypatch.setattr(tool, "BASELINE_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="pinned"):
        run(case)
    assert not case[3].exists()


@pytest.mark.parametrize("name", ["../escape.pyc", "/absolute.pyc", "a//b.pyc", "a\\b.pyc", "a/./b.pyc"])
def test_unsafe_archive_paths_rejected(name):
    raw = io.BytesIO()
    with ZipFile(raw, "w") as archive:
        archive.writestr(name, b"synthetic")
    with ZipFile(io.BytesIO(raw.getvalue())) as archive, pytest.raises(ValueError, match="unsafe"):
        tool._members(archive, tool.MAX_APP)


def test_duplicate_archive_and_metadata_limits_rejected():
    raw = io.BytesIO()
    with ZipFile(raw, "w") as archive:
        archive.writestr("a.pyc", b"one")
        with pytest.warns(UserWarning):
            archive.writestr("a.pyc", b"two")
    with ZipFile(io.BytesIO(raw.getvalue())) as archive, pytest.raises(ValueError, match="duplicate"):
        tool._members(archive, tool.MAX_APP)
    with ZipFile(io.BytesIO(raw.getvalue())) as archive, pytest.raises(ValueError, match="bound"):
        tool._members(archive, 1)


def test_source_audit_detects_signed_zero_constant_and_nested_filename_changes():
    expected = compile("VALUE = -0.0\n", "module.py", "exec")
    changed = expected.replace(co_consts=(0.0, None))
    assert not tool._code_matches(changed, expected)
    expected = compile("def outer():\n    return 1\n", "module.py", "exec")
    changed_inner = expected.co_consts[0].replace(co_filename="foreign.py")
    changed = expected.replace(co_consts=(changed_inner, None))
    assert not tool._code_matches(changed, expected)


def test_source_audit_accepts_equal_strings_with_different_intern_state():
    expected = compile("VALUE = 'constant with spaces and intern state'\n", "module.py", "exec")
    interned = sys.intern(expected.co_consts[0].encode().decode())
    changed = expected.replace(co_consts=(interned, None))
    assert tool._code_matches(changed, expected)
    assert tool._constant_key(frozenset(("a", 1))) == tool._constant_key(frozenset((1, "a")))
    assert tool._constant_key((True, 0)) != tool._constant_key((1, False))
    assert tool._constant_key(0j) != tool._constant_key(complex(-0.0, 0.0))


def test_source_audit_unknown_constant_types_fail_closed():
    with pytest.raises(ValueError, match="Unsupported"):
        tool._constant_key([])


def test_frozenset_constant_keys_preserve_repeated_nan_bit_pattern_counts():
    def nan(payload):
        return struct.unpack(">d", (0x7FF8000000000000 | payload).to_bytes(8, "big"))[0]
    left = frozenset((nan(1), nan(1), nan(2)))
    right = frozenset((nan(1), nan(2), nan(2)))
    assert len(left) == len(right) == 3
    assert tool._constant_key(left) != tool._constant_key(right)


@pytest.mark.parametrize("mutation", ["digest", "extract", "duplicate-json", "payload"])
def test_stale_digest_policy_duplicate_json_and_changed_payload_fail(case, mutation, monkeypatch):
    _, _, baseline, output, write = case
    with ZipFile(baseline) as archive:
        app, build = archive.read(tool.APP), json.loads(archive.read(tool.BUILD))
    if mutation == "duplicate-json":
        raw = json.dumps(build).replace('"python_version": "3.13"', '"python_version": "3.13", "python_version": "3.13"').encode()
    else:
        if mutation == "digest": build["assets"]["app.imy"] = "0" * 40
        if mutation == "extract": build["extract_packages"] = ["*"]
        raw = json.dumps(build).encode()
    write(app=app, build=raw)
    if mutation == "payload": monkeypatch.setattr(tool, "PAYLOAD_SHA256", "0" * 64)
    with pytest.raises(ValueError):
        run(case)
    assert not output.exists() and not output.with_suffix(".provenance.json").exists()


def test_symlink_source_and_missing_old_module_rejected(case):
    root, _, _, output, _ = case
    (root / "src/idoly_local/added.py").unlink()
    (root / "src/idoly_local/added.py").symlink_to("../../private/password")
    source_commit = commit(root)
    with pytest.raises(ValueError, match="regular"):
        tool.repack(case[2], root, source_commit, output, epoch=1)
    (root / "src/idoly_local/added.py").unlink()
    (root / "src/idoly_local/logic.py").unlink()
    source_commit = commit(root)
    with pytest.raises(ValueError, match="omit"):
        tool.repack(case[2], root, source_commit, output, epoch=1)
    assert not output.exists()


def test_existing_broken_symlink_and_publication_race_preserve_foreign_files(case, monkeypatch):
    output = case[3]
    output.symlink_to(output.parent / "missing")
    with pytest.raises(ValueError, match="Existing"):
        run(case)
    assert output.is_symlink()
    output.unlink()
    original = tool._exclusive_publish
    def raced(source, target):
        if target == output:
            target.write_bytes(b"another writer's output")
        original(source, target)
    monkeypatch.setattr(tool, "_exclusive_publish", raced)
    with pytest.raises(FileExistsError):
        run(case)
    assert output.read_bytes() == b"another writer's output"
    assert not output.with_suffix(".provenance.json").exists()
    assert not list(output.parent.glob(".server-python-*"))


def test_bad_source_syntax_leaves_no_candidate_or_temporary_files(case):
    root, _, baseline, output, _ = case
    (root / "src/idoly_local/logic.py").write_text("def broken(:\n")
    source_commit = commit(root)
    with pytest.raises(SyntaxError):
        tool.repack(baseline, root, source_commit, output, epoch=1)
    assert not output.exists() and not output.with_suffix(".provenance.json").exists()
    assert not list(output.parent.glob(".server-python-*"))


def test_staging_unlink_failure_cannot_split_published_pair(case, monkeypatch):
    original = Path.unlink
    def fail_staging_unlink(path, *args, **kwargs):
        if any(p.startswith(".server-python-") for p in path.parts):
            raise OSError("synthetic staging unlink failure")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail_staging_unlink)
    report = run(case)
    assert case[3].exists()
    assert json.loads(case[3].with_suffix(".provenance.json").read_text()) == report


@pytest.mark.parametrize("timeout", [False, True])
def test_git_reads_are_bounded_timed_local_only_and_reaped(tmp_path, monkeypatch, timeout):
    read_fd, write_fd = os.pipe()
    class FakeProcess:
        stdout = os.fdopen(read_fd, "rb")
        killed = False
        waited = False
        returncode = None
        def poll(self):
            return self.returncode
        def kill(self):
            self.killed = True
            self.returncode = -9
        def wait(self, timeout=None):
            self.waited = True
            return self.returncode or 0
    process = FakeProcess()
    if not timeout:
        os.write(write_fd, b"too many bytes")
    def popen(command, **kwargs):
        assert command[:4] == ["git", "-c", "protocol.allow=never", "-C"]
        assert kwargs["env"]["GIT_NO_LAZY_FETCH"] == "1"
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
        return process
    monkeypatch.setattr(tool.subprocess, "Popen", popen)
    monkeypatch.setattr(tool, "GIT_TIMEOUT", 0.01)
    try:
        with pytest.raises(ValueError, match="timed out" if timeout else "bound"):
            tool._git(tmp_path, "cat-file", "blob", "0" * 40, limit=4)
    finally:
        os.close(write_fd)
    assert process.killed and process.waited and process.stdout.closed
