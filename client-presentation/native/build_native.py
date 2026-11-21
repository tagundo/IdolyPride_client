#!/usr/bin/env python3
"""Build the current ARM64 presentation/shared-cache bridge with exact receipts."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def sources():
    return tuple(sorted(path for path in HERE.iterdir() if path.suffix in (".cpp",".hpp",".h",".py",".json")))


def session_jni_exports():
    source=(ROOT/"android-server/app/src/main/java/game/qualiarts/idolypride/localserver/UnifiedMP4Export.java").read_text()
    methods=re.findall(r"\bstatic\s+native\s+[\w<>\[\]]+\s+(\w+)\s*\(",source)
    if not methods or len(methods)!=len(set(methods)):
        raise ValueError("Session Java native contract is invalid")
    prefix="Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_"
    return {prefix+name for name in methods}


def build(output,source_commit,*,ndk=None,cache_dir=None):
    if not re.fullmatch(r"[a-f0-9]{40}",source_commit):
        raise ValueError("An exact source commit is required")
    helper=ROOT/"android-diagnostics/native/build_native.py"
    spec=importlib.util.spec_from_file_location("presentation_native_dependencies",helper)
    dependencies=importlib.util.module_from_spec(spec);spec.loader.exec_module(dependencies)
    _,compiler=dependencies.find_ndk(ndk)
    include,libraries,dependency=dependencies.fetch_shadowhook(cache_dir or ROOT/"data/diagnostic-deps")
    output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():
        raise ValueError("Output already exists")
    paths=(*sources(),helper)
    hashes={path.relative_to(ROOT).as_posix():digest(path) for path in paths}
    session_exports=session_jni_exports()
    command=[str(compiler.with_name("aarch64-linux-android28-clang++")),"-std=c++17","-O2","-fPIC",
        "-fvisibility=hidden","-fexceptions","-fno-rtti","-Wall","-Wextra","-Werror","-nostdlib++",
        "-ffunction-sections","-fdata-sections","-Wl,--gc-sections","-Wl,--exclude-libs,ALL",
        "-I",str(include),"-shared",str(HERE/"bridge.cpp"),"-L",str(libraries),"-lshadowhook","-ldl","-lm","-llog",
        str(compiler.parent.parent/"sysroot/usr/lib/aarch64-linux-android/libc++abi.a"),
        "-Wl,--no-undefined","-Wl,-z,relro,-z,now","-Wl,-z,max-page-size=16384","-Wl,-z,common-page-size=16384",
        "-Wl,-soname,libidoly_presentation.so","-o",str(output)]
    try:
        subprocess.run(command,check=True,capture_output=True,text=True,env={**os.environ,"MALLOC_ARENA_MAX":"2"})
        dependencies.check_arm64_16k(output)
        unchanged=hashes=={path.relative_to(ROOT).as_posix():digest(path) for path in paths}
        if not unchanged:
            raise ValueError("Native sources changed while building")
        readelf=compiler.parent/"llvm-readelf"
        dynamic=subprocess.check_output([str(readelf),"-d",str(output)],text=True)
        needed=re.findall(r"\(NEEDED\).*?\[(.*?)\]",dynamic)
        if "libshadowhook.so" not in needed or set(needed)-{"libshadowhook.so","libc.so","libdl.so","libm.so","liblog.so"}:
            raise ValueError("Unexpected native runtime dependency")
        symbols=subprocess.check_output([str(compiler.parent/"llvm-nm"),"--dynamic","--defined-only",str(output)],text=True)
        exports=[line.split()[-1] for line in symbols.splitlines() if line.split()]
        if not exports or any(name!="JNI_OnLoad" and not name.startswith("Java_game_qualiarts_idolypride_") for name in exports):
            raise ValueError("Unexpected exported runtime symbol")
        prefix="Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_"
        if session_exports!={name for name in exports if name.startswith(prefix)} or session_exports!=session_jni_exports():
            raise ValueError("Native session JNI exports differ from current Java contract")
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    profile=json.loads((HERE/"profile.json").read_text())
    hook_names=re.findall(r"\b(?:HOOK|SHARED_HOOK)\(\s*([a-zA-Z_][a-zA-Z_0-9]*)\s*,",(HERE/"bridge.cpp").read_text())
    hook_names=[name for name in hook_names if name!="entry"]
    report={"schema":1,"abi":"arm64-v8a","source_commit":source_commit,"source_unchanged_during_build":True,
        "source_sha256":hashes,"bytes":output.stat().st_size,"sha256":digest(output),
        "profile_prefix_count":len(profile["aliases"]),"profile_hook_count":len(hook_names),
        "shared_cache_hooks":5,"early_install":"ShadowHook post dl-init callback before managed Setup",
        "dependency":dependency,"needed":needed,"jni_exports":sorted(exports),"session_jni_exports":sorted(session_exports),"runtime_symbols_hidden":True,
        "physical_device_verified":False}
    output.with_name("build-receipt.json").write_text(json.dumps(report,indent=2)+"\n")
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--source-commit",required=True)
    parser.add_argument("--ndk",type=Path)
    parser.add_argument("--cache-dir",type=Path)
    args=parser.parse_args()
    try:
        report=build(args.output,args.source_commit,ndk=args.ndk,cache_dir=args.cache_dir)
    except subprocess.CalledProcessError as error:
        raise SystemExit((error.stderr or str(error))[-4000:]) from None
    print(json.dumps({"sha256":report["sha256"],"bytes":report["bytes"],"shared_cache_hooks":5}))


if __name__=="__main__":
    main()
