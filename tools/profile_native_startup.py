#!/usr/bin/env python3
"""Actions-only phase/CPU profile of native-server preparation on pinned data.

This measures a Linux proxy with the native apps' pure-Python protobuf backend.
It deliberately does not claim Android device, Java asset-copy or Unity timing.
Every child owns a fresh temporary data directory and retains account bytes.
"""
from __future__ import annotations

import argparse
import cProfile
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = {"bytes":198675046,"sha256":"3ea45bd9fba07d35cf366d50e8bc7604aeb67ea0aa1cd55f751474a75724dbce"}
TRANSLATIONS = {
    "android":{"bytes":125709184,"sha256":"22c166ffc3bbbc9e38739cea21fbfd7a87436a166ed56cdb7ee650acfc222dec"},
    "ios":{"bytes":125717042,"sha256":"987fab065fbf791b37b9afe71c53979dc2186e711cde338c89ebe8e0ff905b72"}}
MARKER = ".idoly-startup-profile-owned"


def require(value, message):
    if not value:
        raise ValueError(message)


def phase(output, name, action):
    wall, cpu = time.perf_counter(), time.process_time()
    result = action()
    output[name] = {"wall_seconds":time.perf_counter()-wall,"cpu_seconds":time.process_time()-cpu}
    return result


def cpu_rows(profile):
    profile.create_stats()
    rows = []
    for (filename, line, function), (primitive, total, self_time, cumulative, _callers) in profile.stats.items():
        if not filename.startswith(str(ROOT / "src")) and not filename.startswith(str(ROOT / "android-server")):
            continue
        rows.append({"file":Path(filename).name,"line":line,"function":function,
                     "primitive_calls":primitive,"total_calls":total,
                     "self_seconds":self_time,"cumulative_seconds":cumulative})
    return sorted(rows,key=lambda row:row["cumulative_seconds"],reverse=True)[:40]


def child(args):
    require(os.environ.get("GITHUB_ACTIONS")=="true", "owned_actions_runner_required")
    os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"]="python"
    os.environ["PYTHONDONTWRITEBYTECODE"]="1"
    resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,)*2)
    sys.path.insert(0,str(ROOT / "src"))
    from google.protobuf.internal import api_implementation
    require(api_implementation.Type()=="python","pure_python_protobuf_required")
    root=args._case.resolve(strict=True)
    require((root / MARKER).read_text()==args.source_commit, "owned_case_required")
    require(root.parent==args.work.resolve(strict=True), "owned_case_parent_required")
    phases={}
    imports=time.perf_counter()
    from idoly_local import app_runtime, codec
    from idoly_local.schema import Schema
    from idoly_local.state import State
    from idoly_local.public_payload import install_payload
    spec=importlib.util.spec_from_file_location("profile_android_boundary",ROOT / "android-server/app/src/main/python/android_server_runtime.py")
    adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
    phases["module_import"]={"wall_seconds":time.perf_counter()-imports}
    payload=args.payload.resolve(strict=True)
    if args._platform=="android":
        # Same warm source-cache check as Android's native adapter. The cache
        # ZIP is already present; Java AssetManager copying is not simulated.
        phase(phases,"android_cached_zip_check",lambda:adapter._copy_asset(None,payload,PAYLOAD["sha256"]))
        install=lambda:adapter.install_bundle(payload,root,PAYLOAD["sha256"],PAYLOAD["bytes"])
        data=root / "data"
    else:
        data=root / "data"
        install=lambda:install_payload(payload,data,expected_sha256=PAYLOAD["sha256"],expected_bytes=PAYLOAD["bytes"])
    phase(phases,"public_install_empty_data",install)
    def prepare_translations(label):
        if args.translations_root is None:
            return
        from idoly_local.bundled_translations import install_translation_bundle
        from idoly_local.resource_translation_runtime import validate_prepared_translations
        translation=args.translations_root / args._platform / "bundledTranslations.zip"
        pin=TRANSLATIONS[args._platform]
        require(translation.is_file() and not translation.is_symlink() and translation.stat().st_size==pin["bytes"],
                "prepared_translation_source_missing")
        if args._platform=="android":
            digest=phase(phases,"android_translation_zip_check_"+label,lambda:adapter._digest(translation))
            require(digest==pin["sha256"],"prepared_translation_source_differs")
        result=phase(phases,"prepared_translation_"+label,lambda:install_translation_bundle(translation,data,
            expected_sha256=pin["sha256"],expected_bytes=pin["bytes"],platform=args._platform,
            validate_prepared=lambda prepared:validate_prepared_translations(prepared,data,platform=args._platform)))
        require(result["state"] in ("installed","unchanged"),"prepared_translation_not_ready")
    prepare_translations("empty_data")
    (data / "client-language.json").write_text('{"schema":1,"language":"ko"}')
    def no_download(*_args,**_kwargs):
        raise AssertionError("Startup profiling may not download game resources")
    def start():
        return app_runtime.start(data,profile="sandbox",media_mode=args._media,
            resource_platform=args._platform,grpc_port=0,asset_port=0,
            download_missing_resources=False,resource_fetcher=no_download)
    def verify(runtime):
        status=runtime.status()
        require(status["running"] is True and status["startup_checks"]["state"]=="ready", "runtime_not_ready")
        require(status["language"]["effective_language"]=="ko", "unexpected_language")
        require(status["media_mode"] is args._media, "unexpected_mode")
        if args.translations_root is not None:
            require(status["language"]["resource_translation"]["prepared"] is True,"translation_not_selected")
        import grpc
        schema=Schema.from_descriptor_set(data / "protocol/idolypride-6.1.1.pb")
        with grpc.insecure_channel(status["grpc_address"]) as channel:
            raw=channel.unary_unary("/api.System/Check")(b"",timeout=5)
        require(schema.response_type("/api.System/Check").FromString(codec.decode(raw)).keepAliveTimeMilliseconds>0,
                "encrypted_loopback_failed")
    runtime=phase(phases,"runtime_new_account",start)
    try:verify(runtime)
    finally:runtime.stop()
    state=State(data / ("media-state.db" if args._media else "state.db"))
    before=State.account_bytes(state.account_snapshot("sandbox")[0])
    if args._platform=="android":
        phase(phases,"android_cached_zip_check_preserved",lambda:adapter._copy_asset(None,payload,PAYLOAD["sha256"]))
    phase(phases,"public_install_preserved",install)
    prepare_translations("preserved_data")
    runtime=phase(phases,"runtime_existing_account",start)
    try:verify(runtime)
    finally:runtime.stop()
    require(State.account_bytes(state.account_snapshot("sandbox")[0])==before,"account_bytes_changed")
    # Separate instrumented run: unprofiled phase timings above remain honest.
    trace=None
    if args._trace:
        trace=cProfile.Profile();trace.enable()
        try:runtime=start()
        finally:trace.disable()
        try:verify(runtime)
        finally:runtime.stop()
        require(State.account_bytes(state.account_snapshot("sandbox")[0])==before,"profiled_account_bytes_changed")
    return {"platform":args._platform,"media_mode":args._media,"protobuf_backend":"python",
            "phases":phases,"account_bytes_preserved":True,"encrypted_loopback_verified":True,
            "instrumented_existing_startup_project_top":cpu_rows(trace) if trace is not None else [],
            "peak_rss_bytes":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload",type=Path,required=True)
    parser.add_argument("--work",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--source-commit",required=True)
    parser.add_argument("--translations-root",type=Path)
    parser.add_argument("--_trace",action="store_true")
    parser.add_argument("--runs",type=int,default=3)
    parser.add_argument("--_case",type=Path)
    parser.add_argument("--_platform",choices=("android","ios"))
    parser.add_argument("--_media",action="store_true")
    args=parser.parse_args()
    require(os.environ.get("GITHUB_ACTIONS")=="true", "owned_actions_runner_required")
    require(len(args.source_commit)==40 and all(c in "0123456789abcdef" for c in args.source_commit),"invalid_source")
    if args._case is not None:
        args.output.write_text(json.dumps(child(args),sort_keys=True,indent=2)+"\n")
        return
    require(1<=args.runs<=3,"bounded_runs_required")
    require(subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()==args.source_commit,"source_differs")
    runner=Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    work=args.work.resolve();output=args.output.resolve()
    require(work.is_relative_to(runner) and work!=runner and not work.exists(),"fresh_owned_work_required")
    require(output.parent.is_relative_to(runner) and not output.exists(),"fresh_owned_output_required")
    work.mkdir(mode=0o700);output.parent.mkdir(parents=True,exist_ok=True)
    from tools import latest_server_data_pin as latest
    require(latest.output_pin()==PAYLOAD,"frozen_payload_differs")
    latest.verify_payload(args.payload)
    cases=[]
    for platform in ("android","ios"):
        for media in (False,True):
            for number in range(args.runs):
                owned=Path(tempfile.mkdtemp(prefix="case-",dir=work));(owned/MARKER).write_text(args.source_commit)
                report=work/(platform+"-"+str(media)+"-"+str(number)+".json")
                command=[sys.executable,"-B",str(Path(__file__).resolve()),"--payload",str(args.payload),
                    "--work",str(work),"--output",str(report),"--source-commit",args.source_commit,
                    "--_case",str(owned),"--_platform",platform]
                if media:command.append("--_media")
                if number==0:command.append("--_trace")
                if args.translations_root is not None:command.extend(("--translations-root",str(args.translations_root)))
                try:
                    subprocess.run(command,check=True,timeout=240,cwd=ROOT,env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1"})
                    require(report.stat().st_size<=128*1024,"case_report_too_large")
                    cases.append(json.loads(report.read_text()))
                finally:
                    require(owned.parent==work and (owned/MARKER).read_text()==args.source_commit,"owned_cleanup_required")
                    shutil.rmtree(owned)
    groups=[]
    for platform in ("android","ios"):
        for media in (False,True):
            selected=[case for case in cases if case["platform"]==platform and case["media_mode"] is media]
            groups.append({"platform":platform,"media_mode":media,"runs":len(selected),"median_seconds":{
                name:statistics.median(case["phases"][name]["wall_seconds"] for case in selected)
                for name in selected[0]["phases"]}})
    output.write_text(json.dumps({"schema":1,"status":"PASS","source_commit":args.source_commit,
        "payload":PAYLOAD,"translation_bundles":TRANSLATIONS if args.translations_root is not None else None,"execution":"owned GitHub Actions Linux CPU proxy; pure-Python protobuf",
        "native_android_device_timing":False,"native_ios_device_timing":False,"java_asset_copy_measured":False,
        "unity_gameplay_tested":False,"cases":cases,"groups":groups},sort_keys=True,indent=2)+"\n")
    print(json.dumps({"status":"PASS","source_commit":args.source_commit,"groups":groups},sort_keys=True))


if __name__=="__main__":
    main()
