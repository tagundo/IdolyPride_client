from pathlib import Path
import json
import resource
import shutil
import subprocess

import pytest


def test_playback_json_types_revision_and_independent_graphics(tmp_path):
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("A host C compiler is required")
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "playback-contract"

    def bounded():
        resource.setrlimit(resource.RLIMIT_AS, (128 * 1024 * 1024,) * 2)

    subprocess.run([compiler, "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                    str(root / "cross/tests/playback_contract_test.c"), "-o", str(output)],
                   check=True, timeout=20, preexec_fn=bounded)
    result = subprocess.run([str(output)], check=True, text=True, capture_output=True,
                            timeout=3, preexec_fn=bounded)
    assert "independent playback preference checks" in result.stdout
    exported = subprocess.run([str(output), "--json"], check=True, text=True, capture_output=True,
                              timeout=3, preexec_fn=bounded)
    assert json.loads(exported.stdout) == {"schema": 1, "revision": 102, "wait_for_orientation": True}
