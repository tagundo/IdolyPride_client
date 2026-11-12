#!/usr/bin/env python3
"""Add the audited bridge to the exact diagnostic base as a normal APK update.

Only the manifest changes among existing members. Original SDK/DEX/native,
resources, Unity GUID and metadata are copied unchanged. No device is accessed.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED, ZIP_STORED

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT / "tools"), str(ROOT / "src")]
import build_addon as addon
import build_android_server_manual as limits
from package_android_resource_client import write_resource_input

BASE_SHA256 = "f5be0c0e19c2a17ea28ffa0c3205a49f5ab004f013e2e67e319aa192ca1995df"
BASE_BYTES = 159549324
FEATURE_SHA256 = "e7213b358f331b75ace056ab73da58f33b2215452585dd59ef6a17159d7f1f5a"
NATIVE_SHA256 = "7a68c1be9a65b71cd3d56ce56c737fe3823438324746ec78feb436bc5ecbca6d"
ASPECT_NATIVE_SHA256 = "efc14402105da403c92eef1f096ef9a9752b99c95f11ef86423270103c5ba1df"
ASPECT_NATIVE_BYTES = 246576
NATIVE_SOURCE_PATHS = tuple("client-presentation/native/" + name for name in
    ("bridge.cpp", "presentation_math.hpp", "presentation_scope.hpp", "profile.hpp", "profile.json"))
EDITOR_SHA256 = "4a98ae6a755264357603f1906b92e62e757d59229014e33395f4e03ff019fda8"
PACKAGE = addon.PROFILES["diagnostics"]["package"]
CERTIFICATE = addon.PROFILES["diagnostics"]["certificate"]
PROVIDER = "game.qualiarts.idolypride.presentation.PresentationProvider"
AUTHORITY = PACKAGE + ".idoly.presentation"
MARKER = "assets/idoly-presentation-standalone.json"
ANDROID = "{http://schemas.android.com/apk/res/android}"
MAX_APK = 192 * 1024 * 1024


def marker(native_sha256=NATIVE_SHA256):
    return {"schema": 1, "bridge_version": 1, "target_package": PACKAGE,
            "base_version_code": 414, "native_library_sha256": native_sha256}


def output_verify_command(signer, apk):
    # A min28 manifest selects v3 by default. Explicitly include API24..27
    # when checking both signature blocks; the APK/signing minSdk stays28.
    return [*signer,"verify","--verbose","--print-certs","--min-sdk-version","24",apk]


def xml_shape(element):
    return (element.tag, tuple(sorted(element.attrib.items())),
            (element.text or "").strip(), tuple(xml_shape(child) for child in element))


def add_provider(path):
    tree = ET.parse(path); root = tree.getroot(); app = root.find("application")
    if root.get("package") != PACKAGE or root.get(ANDROID + "sharedUserId") or app is None:
        raise ValueError("Expected the existing separate diagnostic package")
    if any(child.get(ANDROID + "name") == PROVIDER or child.get(ANDROID + "authorities") == AUTHORITY for child in app):
        raise ValueError("Presentation provider already exists")
    before = xml_shape(root)
    provider = ET.SubElement(app, "provider", {ANDROID + "name": PROVIDER,
        ANDROID + "authorities": AUTHORITY, ANDROID + "exported": "false", ANDROID + "initOrder": "1"})
    app.remove(provider)
    if xml_shape(root) != before: raise ValueError("An original manifest element changed")
    app.append(provider); ET.register_namespace("android", ANDROID[1:-1])
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return before


def compiled_tree(text, *, remove_provider=False):
    """Compare actual aapt2 typed values, ignoring source line numbers/order."""
    roots, stack = [], []; removed = 0
    for line in text.splitlines():
        clean = re.sub(r" \(line=[0-9]+\)", "", line)
        content = clean.lstrip(); indent = len(clean) - len(content)
        if content.startswith("E: "):
            while stack and stack[-1][0] >= indent: stack.pop()
            node = [content[3:], [], []]
            (stack[-1][1][2] if stack else roots).append(node); stack.append((indent, node))
        elif content.startswith("A: "):
            if not stack: raise ValueError("Manifest attribute has no element")
            stack[-1][1][1].append(content[3:])
        elif content.startswith("C: "):
            if not stack: raise ValueError("Manifest text has no element")
            stack[-1][1][1].append(content)
    def normalize(node):
        nonlocal removed
        if remove_provider and node[0] == "provider" and any(
                ":name(" in value and '="' + PROVIDER + '"' in value for value in node[1]):
            required = {"name": PROVIDER, "authorities": AUTHORITY, "exported": "false", "initOrder": "1"}
            if len(node[1]) != 4 or node[2]: raise ValueError("Presentation provider has unexpected content")
            for key, value in required.items():
                if not any(re.search(r":" + key + r"\([^)]*\)=" +
                    (re.escape('"' + value + '"') if key in ("name", "authorities") else re.escape(value)) + r"(?:\s|$)", item) for item in node[1]):
                    raise ValueError("Presentation provider attribute differs")
            removed += 1; return None
        children = [normalize(child) for child in node[2]]
        return (node[0], tuple(sorted(node[1])), tuple(child for child in children if child is not None))
    result = tuple(normalize(node) for node in roots)
    if len(result) != 1 or remove_provider and removed != 1:
        raise ValueError("Expected exactly one compiled manifest/provider")
    return result


def next_dex(names):
    dexes = [name for name in names if re.fullmatch(r"classes(?:[2-9][0-9]*|1[0-9]+)?\.dex", name)]
    if "classes.dex" not in dexes: raise ValueError("Original primary DEX is missing")
    return "classes" + str(max(int(name[7:-4] or "1") for name in dexes) + 1) + ".dex"


def signature_member(name):
    upper = name.upper()
    return upper == "META-INF/MANIFEST.MF" or upper.startswith("META-INF/") and upper.count("/") == 1 and upper.endswith((".SF", ".RSA", ".DSA", ".EC"))


def members(archive):
    infos = archive.infolist(); names = [i.filename for i in infos]
    if (len(infos) > 8192 or len(set(names)) != len(names) or sum(i.file_size for i in infos) > 1024 ** 3
            or any(PurePosixPath(n).is_absolute() or ".." in PurePosixPath(n).parts or "\\" in n for n in names)):
        raise ValueError("APK member inventory is unsafe or outside its bounds")
    return {i.filename: i for i in infos if not signature_member(i.filename)}


def hashes(archive, infos):
    result = {}
    for name in infos:
        with archive.open(name) as stream: result[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    return result


def stream_apk(source, target, manifest, additions):
    with ZipFile(source) as incoming, ZipFile(target, "x") as outgoing:
        for name, info in members(incoming).items():
            copied = copy.copy(info)
            if name == "AndroidManifest.xml": outgoing.writestr(copied, manifest)
            else:
                with incoming.open(info) as reader, outgoing.open(copied, "w") as writer:
                    shutil.copyfileobj(reader, writer, 1024 * 1024)
            outgoing.getinfo(name).external_attr = info.external_attr
        for name, raw in additions.items():
            info = ZipInfo(name); info.external_attr = 0o100644 << 16
            info.compress_type = ZIP_STORED if name.endswith((".dex", ".so")) else ZIP_DEFLATED
            outgoing.writestr(info, raw)


class PublicCache:
    """Only exact public build inputs and closed files in our two temp dirs."""
    def __init__(self): self.files, self.owned, self.events = {}, set(), []
    def register(self, path, expected, *, own=False):
        path = Path(path); info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_APK or own and (path.parent not in self.owned or info.st_nlink != 1):
            raise ValueError("Expected a stable public/owned regular file")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            identity = limits._file_identity(info)
            if limits._file_identity(os.fstat(fd)) != identity: raise ValueError("Input changed while opening")
            with os.fdopen(fd, "rb", closefd=False) as stream: actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if expected is not None and actual != expected: raise ValueError("Pinned public build input differs")
            self.files[path] = (identity, actual)
        finally: os.close(fd)
        self.advise(path); return actual
    def advise(self, path):
        path = Path(path); identity, digest = self.files[path]
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            if limits._file_identity(path.lstat()) != identity or limits._file_identity(os.fstat(fd)) != identity:
                raise ValueError("Verified public/owned file changed")
            result = "unsupported"
            try: os.fsync(fd); os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED); result = "advised"
            except (AttributeError, OSError): pass
            if limits._file_identity(path.lstat()) != identity or limits._file_identity(os.fstat(fd)) != identity:
                raise ValueError("Verified public/owned file changed")
            self.events.append({"path": str(path), "bytes": identity[3], "sha256": digest, "result": result})
        finally: os.close(fd)


def native_override(path, cache, source_hashes):
    """Bind the separate pinned native artifact to its frozen compile inputs."""
    path = Path(path)
    cache.register(path, ASPECT_NATIVE_SHA256)
    if path.stat().st_size != ASPECT_NATIVE_BYTES:
        raise ValueError("Pinned replacement native size differs")
    receipt_path = path.with_name("build-receipt.json")
    receipt_info = receipt_path.lstat()
    if not stat.S_ISREG(receipt_info.st_mode) or not 0 < receipt_info.st_size <= 256 * 1024:
        raise ValueError("A bounded regular native build receipt is required")
    receipt_sha256 = cache.register(receipt_path, None)
    receipt = json.loads(receipt_path.read_bytes())
    expected = {name: source_hashes[name] for name in NATIVE_SOURCE_PATHS}
    if (receipt.get("sha256") != ASPECT_NATIVE_SHA256 or receipt.get("bytes") != ASPECT_NATIVE_BYTES
            or receipt.get("profile_prefix_count") != 63
            or receipt.get("source_unchanged_during_build") is not True
            or any(receipt.get("source_sha256", {}).get(name) != digest for name, digest in expected.items())):
        raise ValueError("Replacement native receipt differs from the frozen compile inputs")
    native = path.read_bytes()
    if hashlib.sha256(native).hexdigest() != ASPECT_NATIVE_SHA256:
        raise ValueError("Replacement native changed after verification")
    cache.advise(path); cache.advise(receipt_path)
    return native, {"kind": "pinned_native_artifact", "sha256": ASPECT_NATIVE_SHA256,
        "bytes": ASPECT_NATIVE_BYTES, "profile_prefix_count": 63,
        "build_receipt_sha256": receipt_sha256, "source_sha256": expected,
        "runtime_device_tested": False}


def build(args):
    os.umask(0o077); root = ROOT; source, feature, output = map(Path, (args.source, args.feature_apk, args.output))
    proof = output.with_suffix(".provenance.json")
    if output.exists() or proof.exists() or output.suffix != ".apk" or output.resolve() in (source.resolve(), feature.resolve()):
        raise ValueError("Choose unused standalone APK/provenance paths")
    output.parent.mkdir(parents=True,exist_ok=True)
    if not re.fullmatch(r"[0-9a-f]{40}",args.source_commit): raise ValueError("An exact frozen source commit is required")
    source_paths=[Path(__file__),HERE/"build_addon.py",ROOT/"tools/build_android_server_manual.py",
                  ROOT/"tools/repack_android_server_python.py",
                  ROOT/"tools/package_android_resource_client.py",*sorted((HERE/"java").rglob("*.java"))]
    replacement_native = getattr(args, "native_library", None)
    if replacement_native is not None:
        source_paths.extend(ROOT / name for name in NATIVE_SOURCE_PATHS)
    source_hashes={}
    for path in source_paths:
        relative=path.relative_to(ROOT).as_posix();raw=path.read_bytes()
        if raw!=limits.pybundle._git(ROOT,"show",args.source_commit+":"+relative,limit=2*1024*1024):
            raise ValueError("A public build source differs from the frozen commit")
        source_hashes[relative]=hashlib.sha256(raw).hexdigest()
    cache = PublicCache(); cache.register(source, BASE_SHA256); cache.register(feature, FEATURE_SHA256)
    native_input = {"kind": "audited_feature_apk", "sha256": NATIVE_SHA256,
        "profile_prefix_count": 55, "runtime_device_tested": False}
    replacement = None
    if replacement_native is not None:
        replacement, native_input = native_override(replacement_native, cache, source_hashes)
    if source.stat().st_size != BASE_BYTES: raise ValueError("Diagnostic base size differs")
    sdk, jdk, editor = Path(args.build_tools), Path(args.jdk_bin), Path(args.apkeditor)
    cache.register(editor, EDITOR_SHA256)
    cache.register(sdk/"lib/apksigner.jar",limits.PUBLIC_INPUT_HASHES["signer-jar"])
    ram_root=Path(args.ram_directory).resolve(strict=True)
    if ram_root!=Path("/dev/shm") or ram_root.stat().st_dev==output.parent.stat().st_dev or shutil.disk_usage(ram_root).free<MAX_APK:
        raise ValueError("The approved separate RAM staging directory is required")
    env = dict(os.environ, MALLOC_ARENA_MAX="2")
    for name in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "CLASSPATH", "JAVA_OPTS"): env.pop(name, None)
    stages = []
    def run(command):
        for p in list(cache.files): cache.advise(p)
        tick = time.monotonic(); value = limits._run(command, root=root, env=env, timeout=60)
        stages.append({"tool": Path(str(command[0])).name, "seconds": round(time.monotonic()-tick,3)}); return value
    signer = [jdk / "java", *addon.JAVA_FLAGS, "-jar", sdk / "lib/apksigner.jar"]
    preflight = limits._resource_guard(root)
    verification = run([*signer,"verify","--verbose","--print-certs",source]).decode()
    if (re.findall(r"^Signer #\d+ certificate SHA-256 digest: ([a-f0-9]{64})$",verification,re.M)!=[CERTIFICATE]
            or not any("Verified using v"+str(n)+" scheme (APK Signature Scheme v"+str(n)+"): true" in verification for n in (2,3))):
        raise ValueError("The existing diagnostic signature differs")
    with ZipFile(feature) as small:
        dex = small.read("classes.dex"); native = small.read(addon.LIBRARY)
        if hashlib.sha256(native).hexdigest() != NATIVE_SHA256: raise ValueError("Audited presentation native differs")
        if replacement is not None: native = replacement
        additions = {addon.LIBRARY: native, MARKER: (json.dumps(marker(native_input["sha256"]),sort_keys=True,indent=2)+"\n").encode(), **addon.license_members("diagnostics")}
    with ZipFile(source) as base:
        infos = members(base); before = hashes(base, infos); addon.check_base_members(base, "diagnostics")
    added_dex = next_dex(infos); additions[added_dex] = dex
    if additions.keys() & infos.keys(): raise ValueError("Standalone additions collide with original members")
    output.parent.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(root).free < MAX_APK + limits.MIN_ROOT_FREE + 32*1024*1024:
        raise ValueError("Preserve Root reserve and bounded resource-only scratch")
    with tempfile.TemporaryDirectory(prefix=".presentation-full-",dir=output.parent) as td, tempfile.TemporaryDirectory(prefix="idoly-presentation-full-",dir=args.ram_directory) as rd:
        work, ram = Path(td), Path(rd); cache.owned.update((work, ram))
        resource_input, decoded, rebuilt = work/"resource-input.apk", work/"decoded", work/"resource-rebuilt.apk"
        write_resource_input(source,resource_input)
        if resource_input.stat().st_size > 8*1024*1024: raise ValueError("Resource-only input exceeded its bound")
        run([jdk/"java",*addon.JAVA_FLAGS,"-jar",editor,"d","-dex","-t","xml","-i",resource_input,"-o",decoded])
        add_provider(decoded/"AndroidManifest.xml")
        if sum(p.stat().st_size for p in decoded.rglob("*") if p.is_file())>32*1024*1024:
            raise ValueError("Resource-only decode exceeded its small scratch bound")
        run([jdk/"java",*addon.JAVA_FLAGS,"-jar",editor,"b","-i",decoded,"-o",rebuilt])
        with ZipFile(rebuilt) as z: manifest=z.read("AndroidManifest.xml")
        old_tree=run([sdk/"aapt2","dump","xmltree","--file","AndroidManifest.xml",source]).decode()
        new_tree=run([sdk/"aapt2","dump","xmltree","--file","AndroidManifest.xml",rebuilt]).decode()
        if compiled_tree(old_tree)!=compiled_tree(new_tree,remove_provider=True): raise ValueError("An original compiled manifest value changed")
        shutil.rmtree(decoded);resource_input.unlink();rebuilt.unlink()
        unsigned,aligned,signed=work/"unsigned.apk",ram/"aligned.apk",work/"signed.apk"
        stream_apk(source,unsigned,manifest,additions);cache.register(unsigned,None,own=True)
        run([sdk/"zipalign","-f","16384",unsigned,aligned]);cache.register(aligned,None,own=True)
        run([sdk/"zipalign","-c","16384",aligned]);unsigned.unlink();cache.files.pop(unsigned)
        password=Path(args.password_file);key=Path(args.keystore)
        if password.is_symlink() or not password.is_file() or password.stat().st_mode&0o077 or not key.is_file() or key.is_symlink():
            raise ValueError("Existing matching private signing files are required")
        run([*signer,"sign","--ks",key,"--ks-key-alias","idoly-diagnostics-public","--ks-pass","file:"+str(password),
            "--min-sdk-version","28","--v1-signing-enabled","false","--v2-signing-enabled","true","--v3-signing-enabled","true","--v4-signing-enabled","false","--out",signed,aligned])
        cache.register(signed,None,own=True)
        signature=run(output_verify_command(signer,signed)).decode()
        if (re.findall(r"^Signer #\d+ certificate SHA-256 digest: ([a-f0-9]{64})$",signature,re.M)!=[CERTIFICATE]
                or any("Verified using v"+str(n)+" scheme (APK Signature Scheme v"+str(n)+"): true" not in signature for n in (2,3))):
            raise ValueError("Standalone signature differs from the existing diagnostic certificate")
        run([sdk/"zipalign","-c","16384",signed])
        with ZipFile(signed) as z:
            after=hashes(z,members(z))
            expected={**before,"AndroidManifest.xml":hashlib.sha256(manifest).hexdigest(),**{n:hashlib.sha256(v).hexdigest() for n,v in additions.items()}}
            if after!=expected: raise ValueError("Original game/SDK/resource member changed")
        final_tree=run([sdk/"aapt2","dump","xmltree","--file","AndroidManifest.xml",signed]).decode()
        if compiled_tree(old_tree)!=compiled_tree(final_tree,remove_provider=True):raise ValueError("Signed manifest changed")
        postflight=limits._resource_guard(root)
        if postflight["oom_kill"]!=preflight["oom_kill"]:raise ValueError("OOM counter changed")
        report={"schema":1,"standalone":True,"source_commit":args.source_commit,"source_apk_sha256":BASE_SHA256,"source_apk_bytes":BASE_BYTES,
            "output_apk_sha256":addon.digest(signed),"output_bytes":signed.stat().st_size,"certificate_sha256":CERTIFICATE,
            "signature_v2_v3_verified":True,"manifest_original_values_preserved":True,"provider":PROVIDER,"added_dex":added_dex,
            "all_original_members_preserved_except_manifest_and_signatures":True,"original_member_sha256":before,
            "added_member_sha256":{n:after[n] for n in additions},"native_library_sha256":native_input["sha256"],
            "native_input":native_input,
            "reused_audited_feature_sha256":FEATURE_SHA256,"source_sha256":source_hashes,
            "tool_sha256":{str(p):addon.digest(p) for p in (jdk/"java",sdk/"aapt2",sdk/"zipalign",sdk/"lib/apksigner.jar",editor)},
            "stages":stages,"preflight":preflight,"postflight":postflight,"public_cache_advice":cache.events,
            "existing_install_or_data_accessed":False,"device_tested":False,"published":False}
        staged=work/"provenance.json";staged.write_text(json.dumps(report,indent=2)+"\n");os.link(staged,proof)
        try:os.link(signed,output)
        except BaseException:proof.unlink();raise
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("source","feature-apk","output","ram-directory","apkeditor","jdk-bin","build-tools","keystore","password-file"):
        parser.add_argument("--"+name,required=True,type=Path)
    parser.add_argument("--source-commit",required=True)
    parser.add_argument("--native-library",type=Path,
        help="Use the pinned aspect-fix native library and adjacent build-receipt.json; otherwise retain the audited feature native")
    args=parser.parse_args();result=build(args)
    print(json.dumps({k:result[k] for k in ("output_apk_sha256","output_bytes","certificate_sha256")}))


if __name__=="__main__":main()
