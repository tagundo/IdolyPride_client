"""Exercise the actual bridge helper with metadata/liveness mock callbacks."""
from pathlib import Path
import shutil
import subprocess
import pytest

HERE = Path(__file__).resolve().parent
BRIDGE = HERE.parent / "bridge.cpp"

def test_invocation_only_rect_type_memo(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("A host C++ compiler is unavailable")
    text = BRIDGE.read_text()
    start = "// BEGIN_INVOCATION_RECT_TYPE_MEMO\n"
    end = "// END_INVOCATION_RECT_TYPE_MEMO"
    assert text.count(start) == text.count(end) == 1
    fragment = text.split(start, 1)[1].split(end, 1)[0]
    (tmp_path / "rect_type_memo_fragment.hpp").write_text(fragment)
    output = tmp_path / "rect-type-memo-test"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(tmp_path),
                    str(HERE / "rect_type_memo_test.cpp"), "-o", str(output)],
                   check=True, capture_output=True, timeout=20)
    subprocess.run([str(output)], check=True, capture_output=True, timeout=5)

def test_scope_is_installed_only_after_original_callback():
    text = BRIDGE.read_text()
    assert text.count("RectTypeMemoScope type_memo;") == 3
    for hook, original, following in [
        ("target_update_hook", "target_update_original(self, texture, method);", "identify_main_target(self, texture);"),
        ("target_late_hook", "target_late_original(self, method);", "void *texture = target_current(self, nullptr);"),
        ("quality_update_hook", "quality_update_original(self, method);", "const bool quality_readback ="),
    ]:
        body = text.split("void " + hook + "(", 1)[1].split("\n}\n", 1)[0]
        scope = body.index("RectTypeMemoScope type_memo;")
        assert body.rfind(original, 0, scope) >= 0
        assert body.index(following, scope) > scope
