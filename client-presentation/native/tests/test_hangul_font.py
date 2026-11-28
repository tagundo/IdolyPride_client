"""One-time font fallback lifecycle with no Unity/GPU or real game execution."""
from pathlib import Path
import resource
import shutil
import subprocess

import pytest


def bounded():
    resource.setrlimit(resource.RLIMIT_AS, (128 * 1024 * 1024,) * 2)


@pytest.mark.parametrize('filename', ['hangul_font_test.cpp', 'font_list_factory_test.cpp'])
def test_original_awake_order_gc_lifetime_native_unload_and_once_only_fallbacks(tmp_path, filename):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("A host C++ compiler is unavailable")
    source = Path(__file__).with_name(filename)
    output = tmp_path / "hangul-font"
    subprocess.run([compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror",
                    str(source), "-o", str(output)], check=True, capture_output=True,
                   timeout=20, preexec_fn=bounded)
    subprocess.run([str(output)], check=True, capture_output=True, timeout=5, preexec_fn=bounded)


def test_font_installation_precedes_startup_delay_and_engine_calls_follow_original():
    native = Path(__file__).resolve().parents[1]
    text = (native / "bridge.cpp").read_text()
    install = text.split("void *install(void *) {", 1)[1]
    assert install.index("load_calls();") < install.index("HOOK(font_awake,")
    assert install.index("HOOK(font_awake,") < install.index("if (i==0) pause_ms(500)")
    assert "shadowhook_unhook(hooks[j - 1].stub)" in install
    callback = text.split("void font_awake_hook(", 1)[1].split("\n}\n", 1)[0]
    assert callback.index("font_awake_original(font,method)") < callback.index("korean_fallback.after_original(font)")
    assert "ready.load" not in callback and "game_call" not in callback
    ios = native.parent / "ios"
    startup = (ios / "transport.hpp").read_text().split("void start_presentation() {", 1)[1]
    assert "if (mapped_unity_header()) install(nullptr);" in startup
    publisher = (ios / "static_install.hpp").read_text()
    assert publisher.index("load_calls();") < publisher.index("*hook.original=") < publisher.index("__atomic_store_n(")
    assert "HOOK(font_awake,font_awake_hook,font_awake_original)" in publisher
    assert "glob('*.hpp')" in (ios / "build_native.py").read_text()
