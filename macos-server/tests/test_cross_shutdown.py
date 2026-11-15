from pathlib import Path
import resource
import shutil
import subprocess

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason='SDK-free C cross contracts require the Linux host toolchain and resource limits')


def test_shutdown_deadlines_owned_child_and_saturated_pipe(tmp_path):
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("A host C compiler is required")
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "shutdown-policy"

    def bounded():
        resource.setrlimit(resource.RLIMIT_AS, (128 * 1024 * 1024,) * 2)

    subprocess.run([compiler, "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror",
                    str(root / "cross/tests/shutdown_policy_test.c"), "-o", str(output)],
                   check=True, timeout=20, preexec_fn=bounded)
    result = subprocess.run([str(output)], check=True, text=True, capture_output=True,
                            timeout=3, preexec_fn=bounded)
    assert "shutdown escalation and real nonblocking pipe checks" in result.stdout
