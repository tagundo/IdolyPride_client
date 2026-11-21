"""APK identity checks consume bounded full badging, never a truncated build log."""
import os
import sys

import pytest

from tools import package_android_unified as unified


def badging():
    return (f"package: name='{unified.PACKAGE}' versionCode='414' versionName='6.1.1'\n"
            "sdkVersion:'30'\n"
            "targetSdkVersion:'36'\n"
            f"launchable-activity: name='{unified.MENU_ACTIVITY}' label='' icon=''\n")


def test_8195_byte_success_output_preserves_package_header_and_exact_identity():
    header = badging()
    payload = header + "x" * (8195 - len(header))
    command = [sys.executable, "-c", "import sys;sys.stdout.write(sys.argv[1])", payload]
    env = dict(os.environ)
    tail = unified.run(command, env)
    assert tail == payload[-8192:]
    with pytest.raises(ValueError, match="Final manifest identity/launcher differs"):
        unified.validate_final_badging(tail)
    complete = unified.run(command, env, complete_output_limit=64 * 1024)
    assert complete == payload
    unified.validate_final_badging(complete)
    with pytest.raises(ValueError, match="output exceeds bound.*8195 bytes"):
        unified.run(command, env, complete_output_limit=8192)


@pytest.mark.parametrize("changed", [
    lambda value: value.replace(unified.PACKAGE, "foreign.package", 1),
    lambda value: value.replace("versionCode='414'", "versionCode='415'"),
    lambda value: value.replace("sdkVersion:'30'", "sdkVersion:'28'"),
    lambda value: value.replace(unified.MENU_ACTIVITY, unified.ORIGINAL_ACTIVITY),
    lambda value: value + value.splitlines()[0] + "\n",
    lambda value: value + "sdkVersion:'30'\n",
    lambda value: value + f"launchable-activity: name='{unified.MENU_ACTIVITY}'\n",
])
def test_badging_identity_gate_rejects_different_or_ambiguous_fields(changed):
    with pytest.raises(ValueError, match="Final manifest identity/launcher differs") as error:
        unified.validate_final_badging(changed(badging()))
    assert len(str(error.value)) <= 1100


def test_success_bound_does_not_expand_failure_logs():
    command = [sys.executable, "-c", "import sys;sys.stdout.write('x'*20000);raise SystemExit(1)"]
    with pytest.raises(ValueError, match="Build command failed") as error:
        unified.run(command, dict(os.environ), complete_output_limit=64 * 1024)
    assert len(str(error.value)) < 8300
