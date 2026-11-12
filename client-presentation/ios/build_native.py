#!/usr/bin/env python3
"""Build the locked iOS presentation bridge with Clang/LLD, including on Linux.

Only the public Darwin C ABI is declared locally. No copied Apple SDK or runtime
hook framework is needed. The packager supplies the original-derived profile.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--llvm-bin',type=Path,required=True)
    parser.add_argument('--profile-header',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    here=Path(__file__).resolve().parent
    output=args.output.resolve(); output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists(): raise ValueError('Output already exists')
    header=args.profile_header.resolve()
    if header.name!='ios_profile.hpp' or not header.is_file(): raise ValueError('Expected generated ios_profile.hpp')
    obj=output.with_suffix('.o')
    sources=[here.parent/'native/bridge.cpp',here.parent/'native/presentation_math.hpp',
        here.parent/'native/presentation_scope.hpp',*sorted(here.glob('*.hpp')),
        here/'libSystem.tbd',here/'libcxx.tbd',Path(__file__).resolve()]
    hashes={str(path.relative_to(here.parent.parent)):hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    header_hash=hashlib.sha256(header.read_bytes()).hexdigest()
    commands=[
        [str(args.llvm_bin/'clang++'),'-target','arm64-apple-ios13.0','-std=c++17',
         '-DIDOLY_DARWIN_BRIDGE=1','-ffreestanding','-fno-stack-protector','-fexceptions','-fno-rtti',
         '-fvisibility=hidden','-O2','-Wall','-Wextra','-Werror','-Wno-unused-variable',
         '-I',str(header.parent),'-c',str(here.parent/'native/bridge.cpp'),'-o',str(obj)],
        [str(args.llvm_bin/'ld64.lld'),'-dylib','-arch','arm64','-platform_version','ios','13.0','13.0',
         '-install_name','@rpath/IdolyPresentation.dylib','-adhoc_codesign',str(obj),str(here/'libSystem.tbd'),str(here/'libcxx.tbd'),
         '-o',str(output)],
    ]
    env={**os.environ,'MALLOC_ARENA_MAX':'2'}
    try:
        for command in commands: subprocess.run(command,check=True,env=env)
        if (hashes!={str(path.relative_to(here.parent.parent)):hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
                or hashlib.sha256(header.read_bytes()).hexdigest()!=header_hash):
            output.unlink(missing_ok=True)
            raise ValueError('Native sources changed while building')
    finally:
        obj.unlink(missing_ok=True)
    report={'schema':1,'target':'arm64-apple-ios13.0','source':'shared native/bridge.cpp',
        'profile_header_sha256':header_hash,
        'bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
        'runtime_executable_memory_writes':False,'requires_playcover_resigning':True,
        'runtime_verified':False,'source_sha256':hashes}
    output.with_suffix('.build.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__': main()
