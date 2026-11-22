"""Execute the shipping static install body with explicit loader/cert models.

The exact Mach-O/gateway verifier has its own byte-level tests. This fixture
tests the install coordinator and original-before-publication order; it does
not claim device execution, ABI validation, or MP4 export readiness.
"""
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def installer(tmp_path_factory):
    cc=shutil.which("g++") or shutil.which("clang++")
    if not cc:
        pytest.skip("C++ compiler required")
    source=(ROOT/"client-presentation/ios/static_install.hpp").read_text()
    body=source[source.index("void *install(void *) {"):]
    rows=[row for row in re.findall(r"HOOK\((\w+),\s*([\w:]+),\s*([\w:]+)\)",body) if row[0]!="entry"]
    assert len(rows)>100 and len({row[0] for row in rows})==len(rows)
    assert len({row[2]for row in rows})==len(rows)
    pins="\n".join(f'Entry {name}{{"{name}",0,0}};'for name,_,_ in rows)
    declarations=[]
    for _,hook,original in rows:
        namespace=hook.rsplit("::",1)[0] if "::" in hook else ""
        assert (original.rsplit("::",1)[0] if "::"in original else "")==namespace
        h,o=hook.rsplit("::",1)[-1],original.rsplit("::",1)[-1]
        declaration=f'void *{o}=nullptr;void {h}(){{model_forward(&{o});}}'
        declarations.append(f'namespace {namespace}{{{declaration}}}'if namespace else declaration)
    model=(ROOT/"tests/fixtures/ios_presentation_install.cpp.inc").read_text()
    model=model.replace("// PIN_ENTRIES",pins).replace("// HOOK_DECLARATIONS","\n".join(declarations))
    model=model.replace("// ENTRY_POINTERS",",".join("&pin::"+row[0]for row in rows))
    model=model.replace("// ORIGINAL_POINTERS",",".join("&"+row[2]for row in rows))
    model=model.replace("// ACTUAL_INSTALL",body)
    folder=tmp_path_factory.mktemp("ios-static-install")
    path,binary=folder/"install.cpp",folder/"install"
    path.write_text(model)
    result=subprocess.run([cc,"-std=c++17","-Wall","-Wextra","-Werror","-Wno-misleading-indentation",
        "-O1","-g","-fsanitize=address,undefined","-fno-omit-frame-pointer","-fno-pie","-no-pie","-pthread",
        str(path),"-o",str(binary)],capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stdout+result.stderr
    return binary


@pytest.mark.parametrize("mode",[
    "normal","native_source","fixed_source","animation_source","api_source","clock_install","fixed_install",
    "scene_frontends","scene_origin","native7","capture","audio","queue",
    "missing_image","primary_image","helper_rotation","helper_preview","helper_fallback","helper_list","helper_sound",
    "gateway_first","gateway_middle","gateway_last","slot_first","slot_middle","slot_last",
])
def test_static_install_preserves_primary_without_forging_export_certificate(installer,mode):
    result=subprocess.run([str(installer),mode],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
