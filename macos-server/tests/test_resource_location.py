"""Resource-root selection policy and actual SDK-free Cocoa source checks."""
from pathlib import Path
import json
import resource
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]

def bounded():
    resource.setrlimit(resource.RLIMIT_AS, (128 * 1024 * 1024,) * 2)


def test_location_guard_utf8_json_and_atomic_command_boundaries(tmp_path):
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("A host C compiler is required")
    output = tmp_path / "resource-location"
    subprocess.run([compiler, "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
        str(ROOT / "cross/tests/resource_location_test.c"), "-o", str(output)],
        check=True, timeout=20, preexec_fn=bounded)
    result = subprocess.run([str(output)], check=True, capture_output=True, text=True, timeout=3,
                            preexec_fn=bounded).stdout.splitlines()
    frames = [json.loads(line) for line in result if line.startswith("{")]
    assert frames[0]["resource_cache_dir"] == '/Volumes/보관 디스크/아이프라 "공연"\\ 자료'
    assert frames[1]["resource_cache_dir"] is None
    assert all(frame["action"] == "start" and "data_dir" not in frame for frame in frames)
    assert result[-1] == "RESOURCE_LOCATION_POLICY_PASS"


def test_both_mac_uis_bind_the_chosen_root_and_preserve_the_export_root():
    swift = (ROOT / "App.swift").read_text()
    cocoa = (ROOT / "cross/appkit_ui.c").read_text()
    for source in (swift, cocoa):
        assert '"resourceDirectoryPath"' in source and '"resourcesInDownloads"' in source
        assert "isWritableFile" in source
        assert "기존 파일" in source and "삭제하지 않습니다" in source
        assert "setCanChooseDirectories:" in source or "canChooseDirectories = true" in source
        assert "setCanChooseFiles:" in source or "canChooseFiles = false" in source
    assert '!(saved is String)' in swift and 'guard !invalidResourceLocation else { return nil }' in swift
    assert 'let folder = selectedResourceDirectory' in swift
    assert 'let selected = externalResourceDirectory()' in swift
    assert 'resourceCacheDirectory: cache' in swift
    assert 'let root = downloadsResourceDirectory()' in swift.split('private func resourceExportsDirectory()', 1)[1].split('func revealResources()', 1)[0]
    assert 'external_resource_root()' in cocoa.split('static int send_control(', 1)[1].split('static void begin_start(', 1)[0]
    assert 'selected_resource_root()' in cocoa.split('tag == C_RESOURCE_REVEAL', 1)[1].split('C_RESOURCE_PARALLELISM', 1)[0]
    assert 'G.downloadsResourcesURL,"exports"' in cocoa.split('static void resource_archive_panel(', 1)[1].split('static void select_resource_directory(', 1)[0]
    assert 'if (!resource_location_can_change()) return;' in cocoa.split('runModal")!=1) return;', 1)[1]
    assert 'guard canChangeResourceLocation else { return }' in swift.split('private func saveResourceDirectory(', 1)[1]
    assert 'self.canChangeResourceLocation' in swift.split('var resourceLocationBinding:', 1)[1].split('private func externalResourceDirectory()', 1)[0]


def test_actual_cross_cocoa_source_still_compiles():
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("A host C compiler is required")
    subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-fsyntax-only",
        str(ROOT / "cross/appkit_ui.c")], check=True, timeout=20, preexec_fn=bounded)
