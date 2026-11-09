"""Build only the pinned ARM64 observation shim and its ShadowHook dependency."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
SHADOWHOOK_VERSION = "2.0.1"
SHADOWHOOK_SHA256 = "2cad01ff4d59542958775e19f281981a7e84b39670b5fae75905b8511e10c7cd"
SHADOWHOOK_URL = "https://repo.maven.apache.org/maven2/com/bytedance/android/shadowhook/2.0.1/shadowhook-2.0.1.aar"
MEMBERS = {
    "prefab/modules/shadowhook/include/shadowhook.h": "include/shadowhook.h",
    "jni/arm64-v8a/libshadowhook.so": "lib/libshadowhook.so",
    "jni/arm64-v8a/libshadowhook_nothing.so": "lib/libshadowhook_nothing.so",
}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch_shadowhook(cache_dir):
    root = Path(cache_dir) / ("shadowhook-" + SHADOWHOOK_VERSION)
    root.mkdir(parents=True, exist_ok=True)
    archive = root / ("shadowhook-" + SHADOWHOOK_VERSION + ".aar")
    if not archive.is_file() or digest(archive) != SHADOWHOOK_SHA256:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=root, delete=False) as output:
                temporary = Path(output.name)
                with urlopen(SHADOWHOOK_URL, timeout=60) as incoming:
                    shutil.copyfileobj(incoming, output)
            if digest(temporary) != SHADOWHOOK_SHA256:
                raise ValueError("Pinned ShadowHook AAR digest did not match")
            os.replace(temporary, archive)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    hashes = {}
    with ZipFile(archive) as zipped:
        for member, relative in MEMBERS.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = zipped.read(member)
            target.write_bytes(payload)
            hashes[relative] = hashlib.sha256(payload).hexdigest()
    return root / "include", root / "lib", {
        "version": SHADOWHOOK_VERSION, "aar_url": SHADOWHOOK_URL,
        "aar_sha256": SHADOWHOOK_SHA256, "member_sha256": hashes,
        "license": "MIT; SHADOWHOOK-LICENSE and upstream third-party notices apply",
    }


def find_ndk(ndk=None):
    if ndk is not None:
        root = Path(ndk)
    elif os.environ.get("ANDROID_NDK_HOME"):
        root = Path(os.environ["ANDROID_NDK_HOME"])
    else:
        sdk = Path(os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
                   or PROJECT.parent / ".setup/android-sdk")
        root = sdk / "ndk/26.3.11579264"
    toolchain = root / "toolchains/llvm/prebuilt/linux-x86_64/bin"
    compiler = toolchain / "aarch64-linux-android28-clang"
    if not compiler.is_file():
        raise ValueError("Native diagnostics requires Linux NDK 26.3.11579264; pass --ndk")
    properties = dict(line.split("=", 1) for line in (root / "source.properties").read_text().splitlines() if "=" in line)
    revision = next((value.strip() for key, value in properties.items() if key.strip() == "Pkg.Revision"), None)
    if revision != "26.3.11579264":
        raise ValueError("Native diagnostics requires the pinned NDK 26.3.11579264 revision")
    return root, compiler


def check_arm64_16k(path):
    payload = Path(path).read_bytes()
    if payload[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", payload, 18)[0] != 183:
        raise ValueError("Diagnostic library must be an ARM64 little-endian ELF")
    offset = struct.unpack_from("<Q", payload, 32)[0]
    size, count = struct.unpack_from("<HH", payload, 54)
    for index in range(count):
        kind, flags, file_offset, address, physical, file_size, memory_size, alignment = struct.unpack_from(
            "<II6Q", payload, offset + index * size)
        if kind == 1 and (alignment < 16384 or file_offset % 16384 != address % 16384):
            raise ValueError("Diagnostic library PT_LOAD segments must support 16 KiB pages")


def generate_header(profile, output):
    sites = profile["sites"]
    if len(sites) != 16 or len({row["code"] for row in sites}) != len(sites):
        raise ValueError("The pinned phase profile must contain sixteen unique checkpoints")
    rows = []
    for site in sites:
        expected = bytes.fromhex(site["expected16"])
        if len(expected) != 16:
            raise ValueError("Phase site requires a complete 16-byte native window")
        rows.append("    {" + site["rva"] + ", {" + ",".join(hex(b) for b in expected) + "}, "
                    + json.dumps(site["code"]) + "},")
    build_id = bytes.fromhex(profile["elf_build_id"])
    output.write_text("#include <stdint.h>\n"
        "struct phase_site { uintptr_t rva; unsigned char expected[16]; const char *code; };\n"
        + "#define PHASE_COUNT " + str(len(sites)) + "\n"
        + "static const unsigned char EXPECTED_BUILD_ID[] = {" + ",".join(hex(b) for b in build_id) + "};\n"
        + "static const struct phase_site PHASE_SITES[PHASE_COUNT] = {\n" + "\n".join(rows) + "\n};\n")


def build_native(output: Path, *, ndk=None, cache_dir=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    ndk_root, compiler = find_ndk(ndk)
    include, dependency_libs, dependency = fetch_shadowhook(cache_dir or PROJECT / "data/diagnostic-deps")
    generated = output / "include"
    generated.mkdir(exist_ok=True)
    profile_path = HERE / "phase-profile.json"
    profile = json.loads(profile_path.read_text())
    generate_header(profile, generated / "phase_sites.h")
    libraries = output / "lib/arm64-v8a"
    libraries.mkdir(parents=True, exist_ok=True)
    target = libraries / "libidoly_phase_probe.so"
    cpp_compiler = compiler.with_name("aarch64-linux-android28-clang++")
    common = ["-O2", "-fPIC", "-Werror", "-Wall", "-Wextra", "-fvisibility=hidden",
              "-I", str(include), "-I", str(generated), "-I", str(HERE)]
    objects = output / "objects"
    objects.mkdir(exist_ok=True)
    sources = [(HERE / "phase_probe.c", compiler, ["-std=c11"]),
               (HERE / "machine_state_check.cpp", cpp_compiler, ["-std=c++17", "-fno-exceptions", "-fno-rtti"]),
               (HERE / "checkpoint.S", compiler, [])]
    compiled = []
    for source, executable, flags in sources:
        obj = objects / (source.name + ".o")
        command = [str(executable), *common, *flags, "-c", str(source), "-o", str(obj)]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise ValueError("Native phase probe compilation failed: " + result.stderr[-2400:])
        compiled.append(str(obj))
    command = [str(cpp_compiler), "-shared", "-nostdlib++", "-Wl,--no-undefined",
        "-Wl,-z,max-page-size=16384", "-Wl,-z,common-page-size=16384", "-Wl,-z,relro,-z,now",
        "-Wl,--build-id=sha1", "-Wl,-soname,libidoly_phase_probe.so", *compiled,
        "-L", str(dependency_libs), "-lshadowhook", "-llog", "-ldl", "-o", str(target)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise ValueError("Native phase probe linking failed: " + result.stderr[-2400:])
    dynamic = subprocess.run([str(compiler.with_name("llvm-readelf")), "-d", str(target)],
                             capture_output=True, text=True, check=True).stdout
    if "libc++" in dynamic:
        raise ValueError("Native phase probe must not require a C++ shared runtime")
    for source in dependency_libs.glob("*.so"):
        shutil.copyfile(source, libraries / source.name)
    for library in libraries.glob("*.so"):
        check_arm64_16k(library)
    report = {"architecture": "arm64-v8a", "minimum_api": 28, "alignment_bytes": 16384,
        "ndk_version": (ndk_root / "source.properties").read_text().strip(),
        "shadowhook": dependency, "phase_profile_sha256": digest(profile_path),
        "phase_count": len(profile["sites"]), "observations_only": True,
        "managed_memory_read": False, "register_context_modified": False,
        "per_device_preflight_required": True,
        "preflight_checks": ["ADD", "BL", "original_link_register", "GPR", "FPSIMD", "SP", "NZCV", "FPCR", "FPSR", "unintercept"],
        "source_sha256": {path.name: digest(path) for path in [HERE / "phase_probe.c", Path(__file__),
            HERE / "machine_state_check.cpp", HERE / "machine_state_check.h", HERE / "checkpoint.S"]},
        "library_sha256": {path.name: digest(path) for path in sorted(libraries.glob("*.so"))}}
    (output / "native-provenance.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ndk", type=Path)
    parser.add_argument("--cache-dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(build_native(args.output, ndk=args.ndk, cache_dir=args.cache_dir), indent=2))


if __name__ == "__main__":
    main()
