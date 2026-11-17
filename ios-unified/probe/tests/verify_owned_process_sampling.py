#!/usr/bin/env python3
"""Actual owned macOS Foundation fixture; never a Simulator or release PASS."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
SOURCE_PATHS = (".github/workflows/verify-owned-process-sampling.yml",
    "ios-unified/probe/tests/verify_owned_process_sampling.py",
    "ios-unified/probe/smoke_probe.py", "ios-unified/probe/ui_test_driver.py")
READY = b"IDOLY_OWNED_FIXTURE_READY\n"
FIXTURE_SOURCE = r"""#import <Foundation/Foundation.h>
#include <stdio.h>
#include <unistd.h>
int main(void) {
    alarm(25);
    @autoreleasepool {
        [NSTimer scheduledTimerWithTimeInterval:0.25 repeats:YES block:^(NSTimer *timer) { (void)timer; }];
        fputs("IDOLY_OWNED_FIXTURE_READY\n", stdout); fflush(stdout);
        [[NSRunLoop currentRunLoop] run];
    }
    return 0;
}
"""

class FixtureError(RuntimeError):
    pass

def need(value, code):
    if not value: raise FixtureError(code)

def digest(path):
    with Path(path).open("rb") as source: return hashlib.file_digest(source,"sha256").hexdigest()

def stop(child):
    if child.poll() is None:
        child.terminate()
        try: child.wait(timeout=2)
        except subprocess.TimeoutExpired: child.kill();child.wait(timeout=2)
    if child.stdout is not None: child.stdout.close()
    return child.poll() is not None

def ready(child):
    deadline=time.monotonic()+2;raw=b""
    while b"\n" not in raw:
        left=deadline-time.monotonic();need(left>0,"fixture_ready_failed")
        readable,_,_=select.select([child.stdout],[],[],left)
        need(bool(readable),"fixture_ready_failed")
        block=os.read(child.stdout.fileno(),256-len(raw));need(bool(block),"fixture_ready_failed")
        raw+=block;need(len(raw)<=255,"fixture_ready_failed")
    need(raw==READY and child.poll() is None,"fixture_ready_failed")

def legacy_ps_comm_checks(sampler, executable):
    keys=("query_completed","output_bounded","utf8","row_shape","pid_equal","path_absolute",
          "path_equal","path_resolves_equal","start_parsed","launch_interval_valid","start_in_launch_window")
    result={key:False for key in keys}
    try:
        row=subprocess.run(["/bin/ps","-p",str(sampler.pid),"-o","pid=","-o","lstart=","-o","comm=","-ww"],
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=2,check=False,
            env={**os.environ,"LC_ALL":"C","LANG":"C"})
        result["query_completed"]=row.returncode==0
        result["output_bounded"]=type(row.stdout) is bytes and 0<len(row.stdout)<=4096
        if not result["query_completed"] or not result["output_bounded"]:return result
        text=row.stdout.decode("utf-8").strip();result["utf8"]=True
        match=re.fullmatch(r"([1-9][0-9]{0,9})\s+([A-Za-z]{3}\s+[A-Za-z]{3}\s+[0-9]{1,2}\s+[0-9]{2}:[0-9]{2}:[0-9]{2}\s+[0-9]{4})\s+([^\r\n]+)",text)
        result["row_shape"]=match is not None
        if match is None:return result
        result["pid_equal"]=int(match[1])==sampler.pid;path=Path(match[3])
        result["path_absolute"]=path.is_absolute();result["path_equal"]=path==executable
        try:result["path_resolves_equal"]=path.resolve(strict=True)==executable
        except (OSError,RuntimeError):pass
        started=time.mktime(time.strptime(match[2],"%a %b %d %H:%M:%S %Y"));result["start_parsed"]=True
        low,high=sampler.launch_started,sampler.launch_ack
        result["launch_interval_valid"]=all(type(x) in (int,float) and math.isfinite(x) for x in (low,high)) and low<=high
        result["start_in_launch_window"]=result["launch_interval_valid"] and low-1<=started<=high+1
    except (OSError,ValueError,OverflowError,UnicodeError,subprocess.TimeoutExpired):pass
    return result

def identity(probe, sampler, executable):
    try:return "none",sampler._process_identity(executable)
    except probe.ProbeError as error:
        code=str(error)
        return (code if code in probe.PROCESS_SAMPLE_ERRORS else "fixture_identity_error"),None
    except Exception:return "fixture_identity_error",None

def observe_case(probe, executable, case):
    sampler=probe.OwnedProbeProcessSampler("00000000-0000-4000-8000-000000000000",executable.parent,executable.parent)
    # Host fixture only: no Simulator discovery or container preparation is claimed.
    sampler.executable=executable;sampler.executable_pin=probe._sample_executable_identity(executable);sampler.prepare_error="none"
    sampler.clear_launch()
    argv=[str(executable)] if case=="argv0_absolute" else [probe.PROBE_EXECUTABLE]
    result={"case":case,"ready_observed":False,"owned_child_stopped":False,
        "launch_ack_pid_equal":False,"sample_attempted":False}
    child=subprocess.Popen(argv,executable=str(executable),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,start_new_session=True)
    try:
        sampler.note_launch((probe.BUNDLE_ID+": "+str(child.pid)+"\n").encode("ascii"))
        result["launch_ack_pid_equal"]=sampler.pid==child.pid
        ready(child);result["ready_observed"]=True
        result["legacy_ps_comm_before"]=legacy_ps_comm_checks(sampler,executable)
        before_code,before=identity(probe,sampler,executable)
        result["identity_before_error_code"]=before_code;result["identity_before_passed"]=before_code=="none"
        result["kernel_path_matches_expected"]=False;result["kernel_path_error_code"]="none"
        try:
            kernel_path=sampler._kernel_process_path(2)
            result["kernel_path_matches_expected"]=kernel_path==executable
        except probe.ProbeError as error:
            code=str(error)
            result["kernel_path_error_code"]=code if code in probe.PROCESS_SAMPLE_ERRORS else "fixture_identity_error"
        except Exception:result["kernel_path_error_code"]="fixture_identity_error"
        if before_code=="none":
            sampled=sampler.capture({"process_id":child.pid})
            result["sample_attempted"]=True
            result["sample"]={"scope":"owned-macos-foundation-fixture",**probe.process_sample_summary(sampled)}
            result["sample"]["scope"]="owned-macos-foundation-fixture"
        after_code,after=identity(probe,sampler,executable)
        result["identity_after_error_code"]=after_code;result["identity_after_passed"]=after_code=="none"
        result["legacy_ps_comm_after"]=legacy_ps_comm_checks(sampler,executable)
        result["start_identity_unchanged"]=before is not None and before==after
        result["executable_identity_unchanged"]=probe._sample_executable_identity(executable)==sampler.executable_pin
    finally:result["owned_child_stopped"]=stop(child)
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit",required=True);parser.add_argument("--run-id",type=int,required=True)
    parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    report={"schema":1,"status":"FAIL","scope":"owned-macos-foundation-fixture",
        "simulator_tested":False,"gameplay_tested":False,"release_pass_claimed":False,
        "simulator_container_preparation_executed":False,"legacy_ps_comm_diagnostic_only":True,
        "cases":[],"temporary_removed":False,"all_identity_guards_passed":False,"all_samples_available":False}
    work=None;error_code="none";output_approved=False
    os.umask(0o077)
    try:
        runner=Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
        need(args.output.is_absolute() and args.output.parent.resolve(strict=True)==runner
            and not args.output.exists() and not args.output.is_symlink(),"fixture_output_invalid")
        output_approved=True
        need(sys.platform=="darwin","fixture_macos_required")
        need(re.fullmatch(r"[0-9a-f]{40}",args.source_commit) is not None and args.source_commit==os.environ.get("GITHUB_SHA")
            and type(args.run_id) is int and args.run_id>0 and str(args.run_id)==os.environ.get("GITHUB_RUN_ID"),"fixture_binding_invalid")
        head=subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,capture_output=True,timeout=5,check=False)
        need(head.returncode==0 and head.stdout.decode().strip()==args.source_commit,"fixture_binding_invalid")
        need(subprocess.run(["git","diff","--quiet"],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5).returncode==0,"fixture_checkout_changed")
        report.update(source_commit=args.source_commit,run_id=args.run_id,source_sha256={name:digest(ROOT/name) for name in SOURCE_PATHS},
            fixture_source_sha256=hashlib.sha256(FIXTURE_SOURCE.encode()).hexdigest())
        spec=importlib.util.spec_from_file_location("owned_macos_sampler_probe",ROOT/"ios-unified/probe/smoke_probe.py")
        probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)
        with tempfile.TemporaryDirectory(prefix="idoly-owned-foundation-",dir=runner) as directory:
            work=Path(directory).resolve(strict=True);work.chmod(0o700)
            source=work/"fixture.m";source.write_text(FIXTURE_SOURCE)
            binary=work/probe.PROBE_EXECUTABLE
            compiler=subprocess.run(["xcrun","--sdk","macosx","--find","clang"],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=15,check=False)
            need(compiler.returncode==0 and 0<len(compiler.stdout)<=4096,"fixture_compiler_unavailable")
            clang=Path(compiler.stdout.decode().strip()).resolve(strict=True)
            need(clang.is_absolute() and clang.is_file(),"fixture_compiler_unavailable")
            selected_sdk=subprocess.run(["xcrun","--sdk","macosx","--show-sdk-path"],stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,timeout=15,check=False)
            need(selected_sdk.returncode==0 and 0<len(selected_sdk.stdout)<=4096,"fixture_compiler_unavailable")
            sdk=Path(selected_sdk.stdout.decode().strip()).resolve(strict=True)
            need(sdk.is_absolute() and sdk.is_dir(),"fixture_compiler_unavailable")
            built=subprocess.run([str(clang),"-isysroot",str(sdk),"-fobjc-arc","-fblocks","-framework","Foundation",str(source),"-o",str(binary)],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30,check=False)
            need(built.returncode==0 and binary.is_file() and not binary.is_symlink(),"fixture_compile_failed")
            executable=binary.resolve(strict=True);report["fixture_executable_sha256"]=digest(executable)
            for case in ("argv0_absolute","argv0_basename"):report["cases"].append(observe_case(probe,executable,case))
            need(all(row["ready_observed"] and row["owned_child_stopped"] for row in report["cases"]),"fixture_incomplete")
            report["all_identity_guards_passed"]=all(row.get("identity_before_passed") is True
                and row.get("identity_after_passed") is True and row.get("start_identity_unchanged") is True
                and row.get("executable_identity_unchanged") is True for row in report["cases"])
            report["all_samples_available"]=all(row.get("sample",{}).get("available") is True
                and row["sample"].get("error_code")=="none" for row in report["cases"])
        report["status"]="DIAGNOSTIC_COMPLETE"
    except FixtureError as error:error_code=str(error)
    except Exception:error_code="fixture_unexpected_error"
    finally:
        report["error_code"]=error_code
        report["temporary_removed"]=work is not None and not work.exists()
        if not report["temporary_removed"]:report["status"]="FAIL"
        raw=(json.dumps(report,sort_keys=True,separators=(",",":"))+"\n").encode()
        try:
            need(output_approved and len(raw)<=32768,"fixture_report_bound")
            with args.output.open("xb") as target:target.write(raw)
        except Exception:
            print('{"error_code":"fixture_report_write_failed","status":"FAIL"}');return 1
        print(json.dumps({"status":report["status"],"error_code":error_code,"case_count":len(report["cases"])}))
    return 0 if report["status"]=="DIAGNOSTIC_COMPLETE" else 1

if __name__=="__main__":raise SystemExit(main())
