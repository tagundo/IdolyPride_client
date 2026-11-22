"""Actual native Director frontends and source/gateway certificates.

Host/loader/hook execution are explicitly modeled. The Android certificate
uses the real finite ShadowService and unchanged upstream ARM64 rewriter.
This does not claim device rendering or a completed MP4 export.
"""
from pathlib import Path
import hashlib
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/mp4_director_native7"
SHADOW = ROOT / "tests/fixtures/mp4_hook_bootstrap"


def _body(source, marker):
    return source.split("// BEGIN_" + marker + "\n", 1)[1].split(
        "// END_" + marker, 1
    )[0]


def _pins(source, name):
    start = source.index("inline constexpr BootstrapPin " + name + "[8]=")
    end = source.index("\n};", start) + 3
    return source[start:end]


@pytest.mark.parametrize("platform", ["ios", "android"])
def test_actual_native7_frontends_and_source_certificate_lifecycle(tmp_path, platform):
    cxx, cc = shutil.which("c++"), shutil.which("cc")
    if not cxx or not cc:
        pytest.skip("Host C/C++ sanitizer compilers are required")
    source = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    core = _body(source, "MP4_HOOK_BOOTSTRAP_CORE")
    frontends = _body(source, "MP4_DIRECTOR_NATIVE7_FRONTENDS")
    certificates = _body(source, "MP4_DIRECTOR_NATIVE7_CERTIFICATES")
    prefix = (FIXTURE / "fixture-prefix.cpp.inc").read_text()
    flags = ["-Wall", "-Wextra", "-Werror", "-Wno-misleading-indentation",
             "-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
    objects = []
    if platform == "ios":
        pins = "namespace mp4_bootstrap {\n" + "\n".join(
            _pins(core, name) for name in ("android_bootstrap_pins", "ios_bootstrap_pins")
        ) + "\n}"
        body = "\n".join((prefix, pins, frontends, certificates,
                          (FIXTURE / "fixture-driver.cpp.inc").read_text()))
    else:
        prefix = prefix.replace("#define IDOLY_DARWIN_BRIDGE 1\n", "")
        prefix = "\n".join(line for line in prefix.splitlines()
                           if not line.startswith("namespace mp4_bootstrap{"))
        original = (SHADOW / "driver.cpp").read_text()
        model = original[original.index("static void assert_case("):
                         original.index("static Model *global")]
        # Reuse the real-rewriter loader fixture for seven distinct hooks.
        model = (model.replace("  size_t span = 20;", "  uintptr_t requested=0;\n  size_t span = 20;")
                 .replace("i.replacement = 0x400001000;", "i.replacement = requested;")
                 .replace("i.gateway = 0x300001000;", "i.gateway = 0x300001000+calls*0x1000;")
                 .replace("i.stub = 0x500001000;", "i.stub = 0x500001000+calls*0x1000;"))
        headers = ('#include <string>\nextern "C" {\n#include "sh_a64.h"\n'
                   'void sh_island_alloc(sh_island_t*,size_t,uintptr_t,uintptr_t,uintptr_t,'
                   'sh_addr_info_t*,void*){assert(false);}\n}\n')
        body = "\n".join((prefix, headers, core,
                          "namespace qa { using namespace mp4_bootstrap;\n" + model + "\n}",
                          frontends, (FIXTURE / "android-services.cpp.inc").read_text(),
                          certificates, (FIXTURE / "android-driver.cpp.inc").read_text()))
        original_c = SHADOW / "sh_a64.c"
        assert hashlib.sha256(original_c.read_bytes()).hexdigest() == (
            "4a7185fe3efd2150a68400a0c221c2d7c711a21f53627eb3613a3e6ec89efb10"
        )
        obj = tmp_path / "original.o"
        result = subprocess.run([cc, "-std=c11", *flags, "-I", str(SHADOW),
                                 "-c", str(original_c), "-o", str(obj)],
                                capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        objects.append(str(obj))
    unit, binary = tmp_path / "native7.cpp", tmp_path / "native7"
    unit.write_text(body)
    result = subprocess.run([cxx, "-std=c++17", *flags, "-no-pie", "-pthread", "-I",
                             str(SHADOW), str(unit), *objects, "-o", str(binary)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    if platform == "ios":
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith("104 actual native7 certificate/frontend cases;")
    else:
        for mode in range(39):
            result = subprocess.run([str(binary), str(mode)], capture_output=True,
                                    text=True, timeout=10)
            assert result.returncode == 0, (mode, result.stdout, result.stderr)
