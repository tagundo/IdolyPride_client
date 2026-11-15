#!/usr/bin/env python3
"""Build source-bound release candidates on owned Actions runners; never publish.

Public donor bytes are immutable inputs, not fresh-source build claims. This
module is import-safe; all downloads, native tools and emulators require main.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import time
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
REPO = "tagundo/IdolyPride_client"
VERSION, BUILD_NUMBER = "0.3.34",51
GO_VERSION, NDK_VERSION = "1.27.3","26.3.11579264"
MIB,CHUNK = 1024*1024,128*1024
PUBLIC_SOURCE = "cba4b5a272d4e7033ec5a18223f737c37a749d8f"
SERVER_DATA = {"bytes":191343014,"sha256":"37dbf0fb9bac5d860991753d2e41ff0c269684bfca673ba41e1bcb897651c223"}
TRANSLATIONS = {
 "android":{"bytes":125709184,"sha256":"22c166ffc3bbbc9e38739cea21fbfd7a87436a166ed56cdb7ee650acfc222dec"},
 "ios":{"bytes":125717042,"sha256":"987fab065fbf791b37b9afe71c53979dc2186e711cde338c89ebe8e0ff905b72"}}
DONORS = {
 "android":{"bytes":332386192,"sha256":"303ac7c4977956d5187a0f3967409dc263dfd3ba2d97b1d6d17eb7a24b64a3cc","prefix":"assets/"},
 "ios":{"bytes":330787485,"sha256":"f40a393ad766ac36035332ba741236eea00da9ba9310d401613f10566037043d","prefix":"IdolyPrideLocalServer.app/Contents/Resources/"}}
COMPANIONS = (
 {"name":"IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ko.apk","bytes":165128829,
  "sha256":"44f233290128a97f78940e3167c9486dbe39550090efcb90f7dc403430e94b9e",
  "branch":"downloads/local-v0.3.31-client-android-ko-source-"+PUBLIC_SOURCE},
 {"name":"IdolyPride-6.1.1-Local-PlayCover-ko.ipa","bytes":150132823,
  "sha256":"d872903da8d79bf4a255888f9d5a952198ff47268cfcf7c35e8ac437b56e72a1",
  "branch":"downloads/local-v0.3.31-client-macos-ko-source-"+PUBLIC_SOURCE})
ANDROID_NAME = "IdolyPride-Local-Server-Android.apk"
ANDROID_QA_NAME = "IdolyPride-Local-Server-Android-x86_64-QA.apk"
MAC_NAME = "IdolyPride-Local-Server-macOS-arm64.app.zip"
ANDROID_PACKAGE = "game.qualiarts.idolypride.localserver"
ANDROID_CERT = "ff5b25120ac58f5b82861320925448663a5ac3f812e93736cad1de6a6ac29e51"
QA_FLAGS = ("final_stop","system_check","local_auth","home_rpcs","restart_session_preserved",
 "gameplay_change_preserved","port_rebound","upgrade_identity_preserved","upgrade_sessions_preserved",
 "upgrade_settings_preserved","starter_inventory_persisted","main_live_first_quest","main_live_mode_default_off",
 "main_live_opt_in","main_live_persisted","main_live_attempts_persisted","main_live_clock_preserved",
 "main_live_identity_preserved","main_live_sessions_preserved","main_live_settings_preserved","main_live_cached_no_grant")

class BuildError(ValueError):
    """Fixed credential-free failure codes only."""

def need(value,code):
    if not value:raise BuildError(code)

def sha(path):
    with Path(path).open("rb") as incoming:return hashlib.file_digest(incoming,"sha256").hexdigest()

def identity(path):
    s=Path(path).lstat()
    return s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns

def read_json(path,maximum=2*MIB):
    path=Path(path)
    need(path.is_file() and not path.is_symlink() and 0<path.stat().st_size<=maximum,"report_file_bound")
    with path.open("rb") as incoming:return json.loads(incoming.read(maximum+1))

def write_json(path,value):
    with Path(path).open("x") as outgoing:json.dump(value,outgoing,indent=2);outgoing.write("\n")

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);sys.modules[name]=result;spec.loader.exec_module(result)
    return result

def clean_env():
    hidden=("GH_TOKEN","GITHUB_TOKEN","GH_DEBUG","GIT_CURL_VERBOSE","IDOLY_SERVER_KEYSTORE",
            "IDOLY_SERVER_STORE_PASSWORD","IDOLY_SERVER_KEY_ALIAS","IDOLY_SERVER_KEY_PASSWORD")
    return {k:v for k,v in os.environ.items() if k not in hidden and not k.startswith("GIT_TRACE")}

class Guard:
    def __init__(self):
        self.samples=0;self.oom=None;self.minimum_disk=None
        self.check()
        need(shutil.disk_usage(os.environ["RUNNER_TEMP"]).free>=4*1024*MIB,"runner_disk_entry_floor")
    def check(self):
        free=shutil.disk_usage(os.environ["RUNNER_TEMP"]).free
        need(free>=150*MIB,"runner_disk_floor")
        self.minimum_disk=free if self.minimum_disk is None else min(free,self.minimum_disk)
        cg=Path("/sys/fs/cgroup")
        if (cg/"memory.events").is_file():
            events=dict(line.split() for line in (cg/"memory.events").read_text().splitlines())
            current=int(events["oom_kill"])
            if self.oom is None:self.oom=current
            need(current==self.oom,"runner_oom_baseline_changed")
        self.samples+=1
    def report(self):return {"oom_baseline":self.oom,"minimum_disk":self.minimum_disk,"samples":self.samples}

def run(arguments,log,guard,*,cwd=ROOT,env=None):
    with Path(log).open("xb") as outgoing:
        child=subprocess.Popen(list(map(str,arguments)),cwd=cwd,env=env or clean_env(),
            stdin=subprocess.DEVNULL,stdout=outgoing,stderr=subprocess.STDOUT)
        try:
            while child.poll() is None:guard.check();time.sleep(.5)
            guard.check();need(child.returncode==0,"remote_build_step_failed")
        except BaseException:
            if child.poll() is None:child.terminate();child.wait(timeout=10)
            raise

def capture(arguments,*,cwd=ROOT):
    raw=subprocess.check_output(list(map(str,arguments)),cwd=cwd,env=clean_env(),stderr=subprocess.DEVNULL,timeout=60)
    need(len(raw)<=2*MIB,"tool_output_bound")
    return raw.decode("utf-8")

def source_binding(source):
    need(re.fullmatch(r"[0-9a-f]{40}",source) and capture(["git","rev-parse","HEAD"]).strip()==source,"frozen_source_required")
    paths=("src","android-server","macos-server","native-live-engine","tools/release_platform_builds.py")
    need(not capture(["git","status","--porcelain","--untracked-files=no","--",*paths]).strip(),"source_worktree_changed")
    names=capture(["git","ls-files","--",*paths]).splitlines()
    suffixes={".py",".java",".kt",".kts",".h",".c",".cpp",".go",".mod",".sum",".swift",".json",".xml",".properties",".txt",".pem",".keystore"}
    pins={}
    for name in names:
        path=ROOT/name
        if path.suffix in suffixes:
            need(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(ROOT),"source_file_invalid")
            pins[name]=sha(path)
    need("tools/release_platform_builds.py" in pins,"build_driver_source_pin_missing")
    for name in ("app_runtime.py","diagnostics.py","resource_translation_runtime.py"):
        need("src/idoly_local/"+name in pins,"common_source_pin_missing")
    return pins

def copy_member(archive,name,destination,pin,guard):
    matches=[entry for entry in archive.infolist() if entry.filename==name]
    need(len(matches)==1,"donor_member_missing_or_duplicate")
    info=matches[0]
    need(info.file_size==pin["bytes"] and not info.flag_bits&1 and not stat.S_ISLNK(info.external_attr>>16),"donor_member_identity_differs")
    digest,count=hashlib.sha256(),0
    with archive.open(info) as incoming,Path(destination).open("xb") as outgoing:
        while block:=incoming.read(CHUNK):
            guard.check();count+=len(block);need(count<=pin["bytes"],"donor_member_extent")
            digest.update(block);outgoing.write(block)
    need(count==pin["bytes"] and digest.hexdigest()==pin["sha256"],"donor_member_sha256_differs")

def fetch_public_inputs(kind,destination,work,guard):
    need(kind in ("android","ios"),"unknown_input_platform")
    helper=module("release_public_input_fetch",ROOT/"ios-unified/fetch_inputs.py")
    donor=work/("donor-"+kind+".zip")
    helper.lfs_download(DONORS[kind],donor)
    owned=identity(donor)
    need(donor.stat().st_size==DONORS[kind]["bytes"] and sha(donor)==DONORS[kind]["sha256"],"donor_sha256_differs")
    destination.mkdir(mode=0o700,exist_ok=True)
    with ZipFile(donor) as archive:
        need(len(archive.infolist())<=32768 and len(set(archive.namelist()))==len(archive.infolist()),"donor_inventory_bound")
        copy_member(archive,DONORS[kind]["prefix"]+"ServerData.zip",destination/"ServerData.zip",SERVER_DATA,guard)
        copy_member(archive,DONORS[kind]["prefix"]+"bundledTranslations.zip",destination/"bundledTranslations.zip",TRANSLATIONS[kind],guard)
    need(identity(donor)==owned,"owned_donor_identity_changed");donor.unlink()
    return {"server_data":dict(SERVER_DATA),"translations":{"platform":kind,"included":True,**TRANSLATIONS[kind]},
            "donor":{"source_commit":PUBLIC_SOURCE,**{k:v for k,v in DONORS[kind].items() if k!="prefix"}}}

def artifact(path):
    path=Path(path)
    return {"name":path.name,"bytes":path.stat().st_size,"sha256":sha(path)}

def build_go(target,work,guard,ndk=None):
    go=shutil.which("go");need(go is not None,"Go_required")
    need(capture([go,"version"]).startswith("go version go"+GO_VERSION+" "),"pinned_Go_required")
    output=work/("live-"+target)
    command=[sys.executable,"-B",ROOT/"native-live-engine/scripts/build.py","--target",target,"--go",go,
             "--output",output,"--cache",work/"go-cache"]
    if ndk is not None:command += ["--ndk",ndk]
    run(command,work/("go-"+target+".log"),guard)
    report=read_json(output/"build-report.json")
    need(report.get("target")==target and report.get("abi_version")==1 and report.get("ruleset")=="live-v5"
         and report.get("no_db_or_server_dependencies") is True and report.get("official_score_equivalence") is False,
         "live_engine_report_differs")
    name="libidoly_live.dylib" if target=="macos" else "libidoly_live.so"
    library=output/name
    need(library.stat().st_size==report["library_bytes"] and sha(library)==report["library_sha256"],"source_built_engine_sha256_differs")
    return library,report

def check_apk(path,abi,inputs,engine,tools):
    signed=capture([tools/"apksigner","verify","--verbose","--print-certs",path])
    certificates=re.findall(r"Signer #[0-9]+ certificate SHA-256 digest: ([0-9a-fA-F]{64})",signed)
    need([value.lower() for value in certificates]==[ANDROID_CERT] and "Verified using v2 scheme (APK Signature Scheme v2): true" in signed,"apk_signature_or_certificate_differs")
    badging=capture([tools/"aapt","dump","badging",path])
    package=re.search(r"package: name='([^']+)' versionCode='([^']+)' versionName='([^']+)'",badging)
    need(package is not None and package.groups()==(ANDROID_PACKAGE,str(BUILD_NUMBER),VERSION),"apk_package_version_differs")
    need(("application-debuggable" in badging)==(abi=="x86_64"),"apk_debuggable_mode_differs")
    capture([tools/"zipalign","-c","-v","4",path])
    with ZipFile(path) as archive:
        need(len(archive.infolist())<=32768 and len(set(archive.namelist()))==len(archive.infolist()),"apk_inventory_differs")
        for name,pin in (("assets/ServerData.zip",SERVER_DATA),("assets/bundledTranslations.zip",TRANSLATIONS["android"]),
                         ("lib/"+abi+"/libidoly_live.so",{"bytes":engine["library_bytes"],"sha256":engine["library_sha256"]})):
            info=archive.getinfo(name);need(info.file_size==pin["bytes"],"apk_embedded_size_differs")
            with archive.open(info) as incoming:need(hashlib.file_digest(incoming,"sha256").hexdigest()==pin["sha256"],"apk_embedded_sha256_differs")
        abis={PurePosixPath(info.filename).parts[1] for info in archive.infolist() if info.filename.startswith("lib/") and len(PurePosixPath(info.filename).parts)>2}
        need(abis=={abi},"apk_abi_differs")
    return {**artifact(path),"abi":abi,"application_id":ANDROID_PACKAGE,"version":VERSION,"build_number":BUILD_NUMBER,
            "certificate_sha256":ANDROID_CERT,"signature_verified":True,"alignment_verified":True}

def build_android(work,output,source,pins,guard):
    need(sys.platform.startswith("linux"),"Linux_Android_build_host_required")
    inputs=work/"inputs";input_report=fetch_public_inputs("android",inputs,work,guard)
    sdk=Path(os.environ.get("ANDROID_HOME",os.environ.get("ANDROID_SDK_ROOT","")))
    ndk=sdk/"ndk"/NDK_VERSION;tools=sdk/"build-tools/34.0.0"
    need(ndk.is_dir() and (ndk/"source.properties").is_file() and NDK_VERSION in (ndk/"source.properties").read_text(),"pinned_NDK_required")
    jni=work/"jni";engines={}
    for target,abi in (("android","arm64-v8a"),("android-x86_64","x86_64")):
        library,report=build_go(target,work,guard,ndk)
        destination=jni/abi;destination.mkdir(parents=True);shutil.copyfile(library,destination/library.name)
        engines[abi]=report
        write_json(output/("live-engine-"+abi+".json"),report)
    binaries={}
    for abi,mode,name in (("arm64-v8a","Release",ANDROID_NAME),("x86_64","Debug",ANDROID_QA_NAME)):
        command=["bash",ROOT/"android-server/gradlew","-p",ROOT/"android-server",":app:clean",":app:assemble"+mode,
            "--no-daemon","--console=plain","--stacktrace","-PbuildPython="+sys.executable,
            "-PserverData="+str(inputs/"ServerData.zip"),"-PserverAbi="+abi,"-PserverVersionName="+VERSION,
            "-PserverVersionCode="+str(BUILD_NUMBER),"-PliveEngineDir="+str(jni),
            "-PbundledTranslations="+str(inputs/"bundledTranslations.zip"),
            "-PbundledTranslationsSha256="+TRANSLATIONS["android"]["sha256"],
            "-PbundledTranslationsBytes="+str(TRANSLATIONS["android"]["bytes"])]
        run(command,work/("gradle-"+abi+".log"),guard)
        built=ROOT/"android-server/app/build/outputs/apk"/mode.lower()/("app-"+mode.lower()+".apk")
        shutil.copyfile(built,output/name)
        binaries[abi]=check_apk(output/name,abi,input_report,engines[abi],tools)
    report=base_report("android",source,pins,input_report)
    report.update(status="BUILT_REQUIRES_ANDROID_QA",binary=binaries["arm64-v8a"],qa_binary=binaries["x86_64"],
        live_engine=engines,input_directory=str(inputs.resolve()))
    write_json(output/"build-report.json",report)
    return report


def base_report(kind,source,pins,inputs):
    return {"schema":1,"status":"PASS","platform":kind,"source_commit":source,
        "run_id":int(os.environ["GITHUB_RUN_ID"]),"version":VERSION,"build_number":BUILD_NUMBER,
        "inputs":inputs,"source_sha256":pins,
        "validation":{"source_bound":True,"payload_sha256_verified":True,"translations_sha256_verified":True,
                      "live_engine_included":True,"live_engine_source_built":True},
        "execution":{"actual_macos_execution":kind=="macos","actual_android_arm64_execution":False,
                     "physical_PlayCover_execution":False}}

QA_REFERENCE_PREFIXES = ("data/master-json/","data/public-tutorial/","data/public-story/")
QA_REFERENCE_FILES = frozenset(("protocol/idolypride-6.1.1.pb","master-json/!version.txt",
    "public-tutorial/manifest.json","public-tutorial/tutorial-short.pb","public-tutorial/tutorial-full.pb",
    "public-story/manifest.json","public-story/story-list-event.pb","public-story/story-list-extra.pb"))

def extract_qa_references(payload,destination,guard):
    need(payload.stat().st_size==SERVER_DATA["bytes"] and sha(payload)==SERVER_DATA["sha256"],"QA_payload_pin_differs")
    destination.mkdir(mode=0o700)
    total=0;copied=set()
    with ZipFile(payload) as archive:
        for info in archive.infolist():
            name=info.filename
            if not (name=="data/protocol/idolypride-6.1.1.pb" or name.startswith(QA_REFERENCE_PREFIXES)):continue
            path=PurePosixPath(name)
            need(not path.is_absolute() and ".." not in path.parts and "\\" not in name and "\0" not in name,"QA_reference_path_invalid")
            if info.is_dir():continue
            need(not stat.S_ISLNK(info.external_attr>>16) and not info.flag_bits&1 and 0<info.file_size<=128*MIB,"QA_reference_bound")
            total+=info.file_size;need(total<=1024*MIB,"QA_reference_total_bound")
            target=destination.joinpath(*path.parts[1:]);target.parent.mkdir(parents=True,exist_ok=True)
            count=0
            with archive.open(info) as incoming,target.open("xb") as outgoing:
                while block:=incoming.read(CHUNK):
                    guard.check();count+=len(block);need(count<=info.file_size,"QA_reference_extent")
                    outgoing.write(block)
            need(count==info.file_size,"QA_reference_truncated")
            copied.add(str(PurePosixPath(*path.parts[1:])))
    need(QA_REFERENCE_FILES<=copied and any(name.startswith("master-json/") and name.endswith(".json") for name in copied),
         "QA_references_missing")

def validate_android_qa(report):
    need(type(report) is dict and report.get("ok") is True and report.get("target")=="Android emulator"
         and report.get("device_game_client_tested") is False,"Android_QA_not_passed")
    need(all(report.get(key) is True for key in QA_FLAGS),"Android_QA_preservation_or_engine_gate_missing")
    live=report.get("main_live")
    need(type(live) is dict and live.get("platform")=="Android native" and live.get("quest_id")=="qt-main-1-001-01"
         and live.get("ruleset")=="live-v5" and live.get("chart_count")==183 and live.get("beat_count")==855,
         "Android_live_engine_QA_differs")
    return report

def finish_android(inputs,work,output,source,pins,guard):
    built=read_json(inputs/"build-report.json")
    need(built.get("status")=="BUILT_REQUIRES_ANDROID_QA" and built.get("platform")=="android"
         and built.get("source_commit")==source and built.get("source_sha256")==pins
         and built.get("version")==VERSION and built.get("build_number")==BUILD_NUMBER,"Android_build_binding_differs")
    runner=Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    public=Path(built["input_directory"])
    need(public.is_absolute() and public.resolve(strict=True).is_relative_to(runner),"owned_QA_inputs_required")
    for name,pin in (("ServerData.zip",SERVER_DATA),("bundledTranslations.zip",TRANSLATIONS["android"])):
        need((public/name).stat().st_size==pin["bytes"] and sha(public/name)==pin["sha256"],"Android_QA_input_sha256_differs")
    tools=Path(os.environ.get("ANDROID_HOME",os.environ.get("ANDROID_SDK_ROOT","")))/"build-tools/34.0.0"
    for key,name,abi in (("binary",ANDROID_NAME,"arm64-v8a"),("qa_binary",ANDROID_QA_NAME,"x86_64")):
        actual=check_apk(inputs/name,abi,built["inputs"],built["live_engine"][abi],tools)
        need(actual==built[key],"Android_built_binary_changed")
    refs=work/"references";extract_qa_references(public/"ServerData.zip",refs,guard)
    serial=os.environ.get("ANDROID_SERIAL","emulator-5554")
    need(capture(["adb","-s",serial,"shell","getprop","ro.product.cpu.abi"]).strip()=="x86_64","x86_QA_target_required")
    qa=work/"qa"
    command=[sys.executable,"-B",ROOT/"android-server/ci/qa_emulator.py","--apk",inputs/ANDROID_QA_NAME,
        "--descriptor-set",refs/"protocol/idolypride-6.1.1.pb","--master-dir",refs/"master-json",
        "--public-tutorial-dir",refs/"public-tutorial","--artifacts",qa,"--serial",serial,"--startup-timeout","600"]
    run(command,work/"emulator-QA.log",guard)
    result=validate_android_qa(read_json(qa/"result.json"))
    for name in (ANDROID_NAME,ANDROID_QA_NAME):
        need(artifact(inputs/name)=={key:built["binary" if name==ANDROID_NAME else "qa_binary"][key] for key in ("name","bytes","sha256")},"Android_QA_binary_changed")
        shutil.copyfile(inputs/name,output/name)
    write_json(output/"android-qa.json",result)
    for abi in ("arm64-v8a","x86_64"):write_json(output/("live-engine-"+abi+".json"),built["live_engine"][abi])
    report=base_report("android",source,pins,built["inputs"])
    report.update(binary=built["binary"],qa_binary=built["qa_binary"],application_id=ANDROID_PACKAGE,
                  certificate_sha256=ANDROID_CERT,live_engine=built["live_engine"],
                  qa_report=artifact(output/"android-qa.json"))
    report["validation"].update(apk_signature_verified=True,apk_alignment_verified=True,package_version_verified=True,
        development_certificate_verified=True,x86_emulator_runtime_passed=True)
    write_json(output/"platform-report.json",report)
    return report

def build_macos(work,output,source,pins,guard):
    need(sys.platform=="darwin" and platform.machine()=="arm64","actual_Apple_Silicon_host_required")
    inputs=work/"inputs";input_report=fetch_public_inputs("ios",inputs,work,guard)
    library,engine=build_go("macos",work,guard)
    evidence=work/"mac-evidence"
    app=work/"IdolyPrideLocalServer.app"
    run([sys.executable,"-B",ROOT/"macos-server/build_app.py","--server-data",inputs/"ServerData.zip",
        "--output",app,"--archive",output/MAC_NAME,"--evidence",evidence,"--version",VERSION,
        "--build-number",str(BUILD_NUMBER),"--live-engine-library",library,"--translations",inputs/"bundledTranslations.zip",
        "--translations-sha256",TRANSLATIONS["ios"]["sha256"],"--translations-bytes",str(TRANSLATIONS["ios"]["bytes"])],
        work/"mac-native-build.log",guard)
    raw=read_json(evidence/"build-report.json")
    need(raw.get("source_commit")==source and raw.get("version")==VERSION and raw.get("build_number")==str(BUILD_NUMBER)
         and raw.get("architecture")=="arm64" and raw.get("minimum_macos")=="13.0"
         and raw.get("signature")=="ad-hoc" and raw.get("notarized") is False
         and raw.get("bundled_engine_tested") is True and raw.get("native_gui_start_stop_tested") is True,
         "Mac_native_build_or_execution_not_passed")
    need(raw.get("server_data_sha256")==SERVER_DATA["sha256"] and raw.get("translations",{}).get("included") is True
         and raw["translations"]["sha256"]==TRANSLATIONS["ios"]["sha256"]
         and raw["translations"]["bytes"]==TRANSLATIONS["ios"]["bytes"],"Mac_translation_or_data_pin_differs")
    live=raw.get("live_engine")
    need(type(live) is dict and live.get("included") is True and live.get("default_enabled") is False
         and live.get("input_sha256")==engine["library_sha256"] and live.get("ad_hoc_codesign_verified") is True,
         "Mac_source_built_engine_missing")
    run(["/usr/bin/codesign","--verify","--deep","--strict",app],work/"mac-final-signature.log",guard)
    actual=artifact(output/MAC_NAME)
    need(actual["sha256"]==raw["archive_sha256"] and actual["bytes"]==raw["archive_bytes"],"Mac_archive_binding_differs")
    write_json(output/"mac-build-report.json",raw)
    write_json(output/"live-engine-macos.json",engine)
    for name in ("engine-smoke.json","native-smoke.json","native-app-smoke.json"):
        path=evidence/name
        if path.is_file():shutil.copyfile(path,output/name)
    report=base_report("macos",source,pins,input_report)
    report.update(binary=actual,live_engine=live,application_id="game.idolypride.localserver",
                  signature="ad-hoc",notarized=False,build_report=artifact(output/"mac-build-report.json"))
    report["validation"].update(codesign_strict_verified=True,bundled_engine_tested=True,native_gui_start_stop_tested=True)
    write_json(output/"platform-report.json",report)
    return report

def companions(work,output,source,pins,guard):
    helper=module("release_companion_fetch",ROOT/"ios-unified/fetch_inputs.py")
    records=[]
    for row in COMPANIONS:
        path=work/row["name"]
        helper.lfs_download(row,path);owned=identity(path)
        need(path.stat().st_size==row["bytes"] and sha(path)==row["sha256"],"companion_full_sha256_differs")
        records.append({**row,"source_commit":PUBLIC_SOURCE,"reused_verified_bytes":True,
            "fresh_source_build":False,"full_download_sha256_verified":True,
            "url":"https://github.com/"+REPO+"/raw/refs/heads/"+row["branch"]+"/"+row["name"]})
        need(identity(path)==owned,"owned_companion_changed");path.unlink()
        guard.check()
    report={"schema":1,"status":"PASS","source_commit":source,"run_id":int(os.environ["GITHUB_RUN_ID"]),
            "source_sha256":pins,"companions":records,"fresh_source_build_claimed":False}
    write_json(output/"companion-links.json",report)
    return report

def verify_ios(inputs,work,output,source,pins,guard):
    helper=module("release_unified_delivery",ROOT/"ios-unified/delivery.py")
    manifest,_owned=helper.verify_members(inputs,output,source,int(os.environ["GITHUB_RUN_ID"]),0,guard)
    report={"schema":1,"status":"PASS","platform":"ios-unified","source_commit":source,
            "run_id":int(os.environ["GITHUB_RUN_ID"]),"version":"156.9114","source_sha256":pins,
            "binary":{key:manifest["artifacts"][0][key] for key in ("name","bytes","sha256")},
            "validation":{"all_existing_unified_delivery_gates":True,"artifact_api_digest_required_before_publication":True},
            "execution":{"actual_iOS_Simulator_execution":True,"physical_PlayCover_execution":False,"physical_iPhone_iPad_execution":False}}
    write_json(output/"ios-platform-report.json",report)
    return report

def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform",choices=("inputs","android","android-qa","macos","companions","verify-ios"),required=True)
    parser.add_argument("--source-commit",required=True)
    parser.add_argument("--work",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--inputs",type=Path)
    args=parser.parse_args()
    need(__debug__ and os.environ.get("GITHUB_ACTIONS")=="true" and os.environ.get("GITHUB_REPOSITORY")==REPO
         and args.source_commit==os.environ.get("GITHUB_SHA") and os.environ.get("GITHUB_RUN_ID","").isdigit(),"owned_Actions_runner_required")
    need(sys.platform.startswith("linux") or sys.platform=="darwin","supported_remote_runner_required")
    runner=Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    for path in (args.work,args.output):
        need(path.is_absolute() and path.parent.resolve(strict=True)==runner and not path.exists() and not path.is_symlink(),"fresh_owned_output_required")
    need(args.work!=args.output,"separate_work_and_output_required")
    if args.platform in ("android-qa","verify-ios"):
        need(args.inputs is not None and args.inputs.is_absolute() and args.inputs.resolve(strict=True).is_relative_to(runner),"owned_existing_inputs_required")
    else:need(args.inputs is None,"unexpected_inputs_argument")
    guard=Guard();pins=source_binding(args.source_commit)
    args.work.mkdir(mode=0o700);args.output.mkdir(mode=0o700)
    try:
        if args.platform=="inputs":
            data=fetch_public_inputs("ios",args.output,args.work,guard)
            result={"schema":1,"status":"PASS","source_commit":args.source_commit,"run_id":int(os.environ["GITHUB_RUN_ID"]),
                    "source_sha256":pins,"inputs":data}
            write_json(args.output/"inputs-report.json",result)
        elif args.platform=="android":result=build_android(args.work,args.output,args.source_commit,pins,guard)
        elif args.platform=="android-qa":result=finish_android(args.inputs,args.work,args.output,args.source_commit,pins,guard)
        elif args.platform=="macos":result=build_macos(args.work,args.output,args.source_commit,pins,guard)
        elif args.platform=="companions":result=companions(args.work,args.output,args.source_commit,pins,guard)
        else:result=verify_ios(args.inputs,args.work,args.output,args.source_commit,pins,guard)
        need(source_binding(args.source_commit)==pins,"source_changed_during_build")
        write_json(args.output/"resource-report.json",guard.report())
        print(json.dumps({"status":result["status"],"platform":args.platform,"source_commit":args.source_commit}))
    except BaseException as error:
        failure={"schema":1,"status":"FAIL","source_commit":args.source_commit,"platform":args.platform,"error_type":type(error).__name__}
        if isinstance(error,BuildError):failure["error_code"]=str(error)
        write_json(args.output/"build-failure.json",failure)
        raise SystemExit("Release candidate stopped; sanitized metadata retained") from None

if __name__=="__main__":
    try:main()
    except Exception:
        raise SystemExit("Release candidate refused before execution") from None
