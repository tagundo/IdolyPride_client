"""Run shipping lifecycle hooks with throwing observation/unchanged originals."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


def definition(source, signature):
    start = source.index(signature)
    at = source.index("{", start)
    depth, end = 1, at + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


@pytest.fixture(scope="module")
def lifecycle_host(tmp_path_factory):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    source = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    directory = tmp_path_factory.mktemp("mp4-lifecycle")
    at = source.index("unsigned mp4_original_lifecycle_depth=")
    types = source[at:source.index(";", at) + 1] + "\n"
    types += "\n".join(definition(source, name) + ";" for name in
                       ("struct Mp4UniTask", "struct Mp4CancellationToken", "struct Mp4LifecycleOriginalDepth"))
    (directory / "lifecycle_types.inc").write_text(types)
    signatures = ["template<class Observer> void mp4_lifecycle_observe_noexcept",
                  "Mp4UniTask mp4_player_initialize_hook", "Mp4UniTask mp4_presenter_end_hook",
                  "Mp4UniTask mp4_photography_initialize_hook", "Mp4UniTask mp4_photography_player_initialize_hook",
                  "void mp4_photography_end_hook"]
    (directory / "lifecycle_hooks.inc").write_text("\n".join(definition(source, name) for name in signatures))
    binary = directory / "lifecycle"
    built = subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(directory),
                            str(ROOT / "tests/mp4_lifecycle_host_harness.cpp"), "-o", str(binary)],
                           capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


CASES = [(route, failure) for route in ("player", "end", "photo", "photo_player", "photo_end")
         for failure in ("none", "globals", "scene", "actor", "original")]
CASES += [("player", "runtime"), ("player", "player_observe"),
          ("end", "end_observe"), ("photo", "source_observe"), ("photo", "runtime"), ("photo", "presenter_set"),
          ("photo_player", "source_observe"), ("photo_player", "runtime"), ("photo_player", "descriptors"),
          ("photo_player", "photo_observe"), ("photo_end", "presenter_get"),
          ("photo_end", "presenter_clear"), ("photo_end", "end_observe")]


@pytest.mark.parametrize("route,failure", CASES)
def test_observation_failure_preserves_exactly_one_original_call_and_result(lifecycle_host, route, failure):
    result = subprocess.run([str(lifecycle_host), route, failure], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
