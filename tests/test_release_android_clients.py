"""Fixed-locale Android delivery preserves update identity and rejects forged inputs."""
from copy import deepcopy
from io import BytesIO
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from zipfile import ZipFile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("release_android_clients_test", ROOT / "tools/release_android_clients.py")
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)
COMMIT = "1" * 40


def test_locales_are_alternative_updates_of_the_existing_server_launch_target():
    assert tool.LANGUAGES == ("ja", "en")
    assert tool.PACKAGE == "game.qualiarts.idolypride.local.diagnostics"
    assert tool.VERSION_CODE == 414
    assert tool.CERTIFICATE == "aa4e9346ff9e542b263b70254df3e25b79211df16161208a3b509c4f113facfc"
    assert set(tool.CLIENT_NAMES) == {"ja", "en"}
    assert all(name.endswith("-" + lang + ".apk") for lang, name in tool.CLIENT_NAMES.items())
    assert len(tool.VALIDATION_FLAGS) == len(set(tool.VALIDATION_FLAGS)) == 10


@pytest.mark.parametrize("url", ("http://github.com/o/r/file", "https://example.com/file",
    "https://github.com:8080/file", "https://token@github.com/file", "file:///tmp/source"))
def test_public_input_origin_cannot_forward_to_unapproved_or_authenticated_target(url):
    with pytest.raises(ValueError, match="unapproved_public_input_origin"):
        tool.approved(url)


class Guard:
    def __init__(self):
        self.checks = 0
    def check(self):
        self.checks += 1


def test_streamed_download_has_no_repository_credentials_even_after_redirect(tmp_path, monkeypatch):
    raw = b"one verified public dependency"
    pin = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    requests = []
    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            if len(requests) == 1:
                raise HTTPError(request.full_url, 302, "redirect",
                    {"Location": "https://release-assets.githubusercontent.com/input"}, None)
            return BytesIO(raw)
    monkeypatch.setenv("GH_TOKEN", "do-not-forward")
    monkeypatch.setattr(tool, "build_opener", lambda *_: Opener())
    target, guard = tmp_path / "input", Guard()
    tool.download("https://github.com/owner/repository/input", pin, target, guard)
    assert target.read_bytes() == raw and guard.checks > 0
    assert len(requests) == 2
    assert all(request.get_header("Authorization") is None and "do-not-forward" not in request.full_url
               for request in requests)
    assert not target.with_name("input.partial").exists()


@pytest.mark.parametrize("failure", ("oversized", "truncated", "bad-hash", "host-redirect"))
def test_bad_public_dependency_never_becomes_an_admitted_input(tmp_path, monkeypatch, failure):
    raw = b"public bytes"
    pin = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    if failure == "oversized":
        pin["bytes"] -= 1
    elif failure == "truncated":
        pin["bytes"] += 1
    elif failure == "bad-hash":
        pin["sha256"] = "0" * 64
    class Opener:
        def open(self, request, timeout):
            if failure == "host-redirect":
                raise HTTPError(request.full_url, 302, "redirect", {"Location": "https://example.com/file"}, None)
            return BytesIO(raw)
    monkeypatch.setattr(tool, "build_opener", lambda *_: Opener())
    target = tmp_path / "admitted"
    with pytest.raises(ValueError):
        tool.download("https://github.com/owner/repository/input", pin, target, Guard())
    assert not target.exists()


def test_native_recipe_keeps_audited_android_abi_exceptions_static_runtime_and_16k_alignment(tmp_path):
    command = list(map(str, tool.native_command(
        tmp_path / "aarch64-linux-android28-clang++", tmp_path / "ndk", tmp_path / "shadow", tmp_path / "library.so")))
    assert "-fexceptions" in command and "-fno-rtti" in command and "-nostdlib++" in command
    assert "-Wl,-z,max-page-size=16384" in command and "-Wl,-z,common-page-size=16384" in command
    assert "-Wl,--no-undefined" in command and "-Wl,--threads=1" in command
    assert any(name.endswith("/libc++abi.a") for name in command)
    assert "-lshadowhook" in command and not any("libc++_shared" in name for name in command)


@pytest.fixture
def packaged(tmp_path):
    members = {tool.UI_MEMBER: b"translated-serialized-fixture",
               "font": b"retained-font-fixture", "guid": b"different-extraction-guid", "native": b"same-native-feature"}
    apk = tmp_path / "client.apk"
    with ZipFile(apk, "x") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    digest = lambda name: hashlib.sha256(members[name]).hexdigest()
    proof = {
        "source_commit": COMMIT, "source_apk_sha256": tool.INPUTS["diagnostic_base"]["sha256"],
        "source_apk_bytes": tool.INPUTS["diagnostic_base"]["bytes"], "ui_language": "en",
        "certificate_sha256": tool.CERTIFICATE, "signature_v2_v3_verified": True,
        "local_resource_output_fields_verified": True,
        "all_original_members_preserved_except_declared_manifest_font_UI_transport_and_story_loading": True,
        "native_input": {"source_commit": COMMIT}, "device_tested": False,
        "output_bytes": apk.stat().st_size, "output_apk_sha256": tool.sha(apk),
        "font_support": {"original_long_dash_font_retained": True, "legacy_Japanese_font_data_unchanged": True,
            "all_other_objects_byte_identical": True,
            "output_members": {"font": {"bytes": len(members["font"]), "sha256": digest("font")}}},
        "ui_translation": {"language": "en", "output_asset_sha256": digest(tool.UI_MEMBER),
            "compiled_csv_sha256": tool.INPUTS["english_ui"]["sha256"],
            "runtime_translation_hooks_added": False, "all_other_objects_byte_identical": True},
        "local_resource_transport": {"typed": "fixture"}, "native_library_sha256": digest("native"),
    }
    calls = []
    full = SimpleNamespace(unity_cache=SimpleNamespace(MEMBER="guid"), addon=SimpleNamespace(LIBRARY="native"),
                           verify_local_resource_output=lambda archive, transport: calls.append(transport))
    return apk, proof, full, calls


def test_packaging_gate_reads_actual_ui_font_native_and_guid_members(packaged):
    apk, proof, full, calls = packaged
    result = tool.verify_language(apk, proof, "en", COMMIT, full)
    assert result["ui_asset_sha256"] == proof["ui_translation"]["output_asset_sha256"]
    assert result["presentation_native_sha256"] == proof["native_library_sha256"]
    assert result["unity_cache_sha256"] and calls == [proof["local_resource_transport"]]


@pytest.mark.parametrize("path,value", (
    (("source_commit",), "2" * 40), (("ui_language",), "ko"),
    (("certificate_sha256",), "0" * 64), (("signature_v2_v3_verified",), False),
    (("local_resource_output_fields_verified",), False),
    (("all_original_members_preserved_except_declared_manifest_font_UI_transport_and_story_loading",), False),
    (("native_input", "source_commit"), "2" * 40),
    (("font_support", "original_long_dash_font_retained"), False),
    (("font_support", "output_members", "font", "sha256"), "0" * 64),
    (("ui_translation", "compiled_csv_sha256"), "0" * 64),
    (("ui_translation", "output_asset_sha256"), "0" * 64),
    (("ui_translation", "runtime_translation_hooks_added"), True),
    (("native_library_sha256",), "0" * 64),
    (("device_tested",), True),
))
def test_a_claimed_language_build_cannot_pass_with_mismatched_payload_or_proof(packaged, path, value):
    apk, original, full, _calls = packaged
    proof = deepcopy(original)
    node = proof
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    with pytest.raises(ValueError):
        tool.verify_language(apk, proof, "en", COMMIT, full)


def test_japanese_gate_cannot_relabel_translated_ui_as_original(packaged):
    apk, original, full, _calls = packaged
    proof = deepcopy(original)
    proof["ui_language"] = "ja"
    proof["ui_translation"] = None
    with pytest.raises(ValueError, match="japanese_ui_not_original"):
        tool.verify_language(apk, proof, "ja", COMMIT, full)

@pytest.mark.parametrize("message", ("https://signed.example/token?secret=do-not-print",
    "Tool failed with request Authorization: private", "bad path /Users/private/name"))
def test_failure_diagnostics_expose_only_fixed_phase_and_credential_free_codes(message):
    tool.phase("input_font")
    result = tool.failure_report(ValueError(message))
    assert result == {"schema": 1, "status": "FAIL", "phase": "input_font",
                      "error_type": "ValueError", "file_role": "none", "error_code": "unclassified"}
    assert "do-not-print" not in str(result) and "Authorization" not in str(result)


def test_fixed_build_failure_code_is_available_without_stack_or_url():
    tool.phase("input_font")
    result = tool.failure_report(ValueError("public_input_http_failure"))
    assert result["error_code"] == "public_input_http_failure" and result["phase"] == "input_font"
    with pytest.raises(ValueError, match="unknown_build_phase"):
        tool.phase("https://private.example")

def test_font_origin_is_public_upstream_with_exact_same_cached_blob_and_sha256():
    import json
    profile = json.loads((ROOT / "client-presentation/fonts/pretendard-jp-v1.json").read_text())
    assert tool.FONT_GIT_BLOB == profile["cached_source"]["git_blob"] == "ab20ba021ecb09802976a8dcee3eaa4219bf55f7"
    assert tool.INPUTS["font"] == {"bytes": profile["bytes"], "sha256": profile["sha256"]}
    assert tool.URLS["font"] == (
        "https://github.com/orioncactus/pretendard/raw/" + tool.FONT_PUBLIC_COMMIT
        + "/packages/pretendard-jp/dist/public/static/PretendardJP-SemiBold.otf")
    assert tool.FONT_PUBLIC_COMMIT == "5c41199ea0024a9e0b2cb31735265056e5472d76"
    assert "tagundo/hoshimi-localify-ios" not in tool.URLS["font"]

@pytest.mark.parametrize("filename,expected", (
    ("/sys/fs/cgroup/memory.max", "cgroup_memory_max"),
    ("/sys/fs/cgroup/memory.current", "cgroup_memory_current"),
    ("/sys/fs/cgroup/memory.events", "cgroup_memory_events"),
    ("/proc/meminfo", "proc_meminfo"),
    ("/public/ndk/source.properties", "ndk_properties"),
    ("/Users/private-name/signed-token-file", "unknown"),
))
def test_missing_file_diagnostics_use_only_fixed_role_without_raw_path(filename, expected):
    tool.phase("native_resource")
    result = tool.failure_report(FileNotFoundError(2, "missing", filename))
    assert result["file_role"] == expected
    assert result["phase"] == "native_resource" and result["error_code"] == "unclassified"
    assert filename not in str(result) and "private-name" not in str(result)


@pytest.fixture
def hosted_resources(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")
    cg, proc = tmp_path / "cgroup", tmp_path / "proc"
    cg.mkdir(); proc.mkdir()
    (proc / "meminfo").write_text("MemTotal: 4096000 kB\nMemAvailable: 1048576 kB\n")
    state = {"free": 150 * 1024**2, "budget_calls": 0,
             "budget": {"memory_current": 1024**3, "memory_max": 2 * 1024**3,
                        "memory_direct_headroom": 768 * 1024**2,
                        "memory_clean_inactive_credit": 256 * 1024**2,
                        "memory_effective_headroom": 1024**3}}
    def budget():
        state["budget_calls"] += 1
        return dict(state["budget"])
    def create():
        return tool.HostedResourceGuard(budget, cgroup=cg, proc=proc,
            disk_usage=lambda _root: SimpleNamespace(free=state["free"]))
    return cg, proc, state, create


@pytest.mark.parametrize("maximum", (None, "max"))
def test_hosted_unlimited_runner_uses_memavailable_with_explicit_entry_and_stage_floors(hosted_resources, maximum):
    cg, proc, state, create = hosted_resources
    if maximum is not None:
        (cg / "memory.max").write_text(maximum)
    checked = create()
    assert checked.entry["memory_direct_headroom"] == 1024**3
    assert checked.entry["memory_max"] is None and checked.entry["oom_kill"] is None
    assert checked.entry["oom_counter_supported"] is False and state["budget_calls"] == 0
    (proc / "meminfo").write_text("MemAvailable: 524288 kB\n")
    assert checked(Path("."))["memory_direct_headroom"] == 512 * 1024**2
    (proc / "meminfo").write_text("MemAvailable: 524287 kB\n")
    with pytest.raises(ValueError, match="hosted_memory_stage_floor"):
        checked(Path("."))
    assert checked.report()["oom_baseline"] is None
    (proc / "meminfo").write_text("MemAvailable: 1048575 kB\n")
    with pytest.raises(ValueError, match="hosted_memory_entry_floor"):
        create()


def test_hosted_finite_cgroup_keeps_existing_direct_and_effective_limits(hosted_resources):
    cg, _proc, state, create = hosted_resources
    (cg / "memory.max").write_text(str(2 * 1024**3))
    checked = create()
    assert checked.entry["memory_policy"] == "finite_cgroup" and state["budget_calls"] == 1
    state["budget"]["memory_direct_headroom"] -= 1
    with pytest.raises(ValueError, match="hosted_finite_cgroup_headroom_floor"):
        checked(Path("."))
    state["budget"]["memory_direct_headroom"] += 1
    state["budget"]["memory_effective_headroom"] -= 1
    with pytest.raises(ValueError, match="hosted_finite_cgroup_headroom_floor"):
        checked(Path("."))


def test_finite_cgroup_missing_current_is_not_host_memory_fallback(hosted_resources):
    cg, proc, _state, _create = hosted_resources
    (cg / "memory.max").write_text(str(2 * 1024**3))
    def incomplete_budget():
        return (cg / "memory.current").read_text()
    with pytest.raises(FileNotFoundError) as error:
        tool.HostedResourceGuard(incomplete_budget, cgroup=cg, proc=proc)
    assert error.value.filename == str(cg / "memory.current")


def test_hosted_guard_keeps_disk_reserve_and_oom_baseline(hosted_resources):
    cg, _proc, state, create = hosted_resources
    (cg / "memory.events").write_text("oom 0\noom_kill 2\n")
    checked = create()
    assert checked.entry["oom_counter_supported"] is True and checked.entry["oom_kill"] == 2
    state["free"] -= 1
    with pytest.raises(ValueError, match="hosted_disk_reserve_floor"):
        checked(Path("."))
    state["free"] += 1
    (cg / "memory.events").write_text("oom 1\noom_kill 3\n")
    with pytest.raises(ValueError, match="hosted_oom_baseline_changed"):
        checked(Path("."))


@pytest.mark.parametrize("change", ("events_appear", "events_disappear", "limit_changes"))
def test_hosted_resource_policy_or_counter_support_cannot_change_during_build(hosted_resources, change):
    cg, _proc, _state, create = hosted_resources
    if change == "events_disappear":
        (cg / "memory.events").write_text("oom_kill 0\n")
    checked = create()
    if change == "events_appear":
        (cg / "memory.events").write_text("oom_kill 0\n")
    elif change == "events_disappear":
        (cg / "memory.events").unlink()
    else:
        (cg / "memory.max").write_text("max")
    with pytest.raises(ValueError, match="hosted_(oom_counter_support|memory_policy)_changed"):
        checked(Path("."))


@pytest.mark.parametrize("filename,raw", (("memory.max", "invalid"), ("memory.max", "0"),
    ("meminfo", "MemAvailable: -1 kB\n"),
    ("meminfo", "MemAvailable: 1048576 kB\nMemAvailable: 1048576 kB\n"),
    ("memory.events", "oom_kill 0\noom_kill 0\n")))
def test_hosted_malformed_metadata_fails_closed(hosted_resources, filename, raw):
    cg, proc, _state, create = hosted_resources
    ((proc if filename == "meminfo" else cg) / filename).write_text(raw)
    with pytest.raises(ValueError, match="hosted_.*malformed"):
        create()


def test_hosted_guard_excludes_another_active_java_build(hosted_resources):
    _cg, proc, _state, create = hosted_resources
    process = proc / "123"; process.mkdir()
    (process / "comm").write_text("java\n")
    (process / "status").write_text("State: S (sleeping)\n")
    with pytest.raises(ValueError, match="hosted_other_java_process_active"):
        create()
    (process / "status").write_text("State: Z (zombie)\n")
    assert create().samples == 1


@pytest.mark.parametrize("environment", (None, "self-hosted", "local"))
def test_hosted_policy_is_never_implicitly_selected_for_local_or_self_hosted_runner(monkeypatch, environment):
    if environment is None:
        monkeypatch.delenv("RUNNER_ENVIRONMENT", raising=False)
    else:
        monkeypatch.setenv("RUNNER_ENVIRONMENT", environment)
    def untouched():
        raise AssertionError("Local strict guard selection must not read a hosted budget")
    assert tool.runner_resource_guard(SimpleNamespace(_memory_budget=untouched)) is None
    with pytest.raises(ValueError, match="hosted_runner_required"):
        tool.HostedResourceGuard(untouched)
