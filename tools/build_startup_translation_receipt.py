#!/usr/bin/env python3
"""Build public-only native startup metadata using original strict validators."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from zipfile import ZipFile,ZipInfo,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]


def build(prepared,data_dir,output,*,platform):
    from idoly_local import resource_translation_cache as cache
    from idoly_local import startup_receipt as receipt
    from idoly_local.resource_translation import load_resource_translation
    from idoly_local.octo_runtime import _platform_archive,load_octo_archive
    output=Path(output);prepared=Path(prepared);data_dir=Path(data_dir)
    if output.exists() or output.is_symlink() or platform not in ("android","ios"):
        raise ValueError("Use an unused public startup receipt output")
    archive_name,*_= _platform_archive(platform)
    _settings,original=load_octo_archive(data_dir/archive_name,platform=platform)
    index={"schema":receipt._FORMAT,"platform":platform,"layers":{}}
    weight=0;temporary=output.with_name(output.name+".part")
    if temporary.exists() or temporary.is_symlink():raise ValueError("Startup receipt staging already exists")
    with receipt._LOCK:
        if receipt._RECEIPTS:raise ValueError("Build requires original strict validators")
    try:
        with ZipFile(temporary,"x",compression=ZIP_DEFLATED,compresslevel=6) as archive:
            for language in ("ko","en"):
                directory=prepared/language/platform
                before=cache._signature(directory,data_dir,platform)
                digests=cache._hashes(directory,data_dir,platform,before)
                legacy_name="public-octo" if platform=="android" else "public-octo-ios"
                legacy_path=data_dir/legacy_name/"legacy-manifest.pb"
                report=json.loads((directory/"manifest.json").read_bytes())
                legacy=None if report["original_manifest_sha256"]==hashlib.sha256(original).hexdigest() else legacy_path.read_bytes()
                # Process-local reuse is explicitly disabled. The original full
                # constructors validate all authorized six-field wire changes.
                with cache._LOCK:cache._CACHE.clear()
                layer=load_resource_translation(directory,original,language=language,data_dir=data_dir,platform=platform)
                try:
                    snapshot=cache._snapshot(layer)
                    if snapshot is None:raise ValueError("Original validator produced non-public metadata")
                    weight+=snapshot[1]
                    if weight>cache._MAX_METADATA_BYTES:raise ValueError("Startup receipt metadata exceeds shared cache budget")
                    rows=receipt.encode_snapshot(snapshot)
                    index["layers"][language]=receipt.binding(original,legacy,digests)
                    for name,raw in zip(("metadata.json","rebased.pb"),rows):
                        info=ZipInfo(language+"/"+name,(1980,1,1,0,0,0))
                        info.compress_type=ZIP_DEFLATED;info.external_attr=0o100644<<16
                        archive.writestr(info,raw)
                    if (cache._signature(directory,data_dir,platform)!=before
                            or cache._hashes(directory,data_dir,platform,before)!=digests):
                        raise ValueError("Public startup inputs changed while building")
                finally:layer.close()
            info=ZipInfo("index.json",(1980,1,1,0,0,0));info.compress_type=ZIP_DEFLATED;info.external_attr=0o100644<<16
            archive.writestr(info,json.dumps(index,sort_keys=True,separators=(",",":")).encode())
        size=temporary.stat().st_size
        if not 0<size<=receipt.MAX_RECEIPT_BYTES:raise ValueError("Startup receipt archive exceeds boundary")
        with temporary.open("rb") as incoming:digest=hashlib.file_digest(incoming,"sha256").hexdigest()
        pin={"schema":1,"platform":platform,"sha256":digest,"bytes":size}
        if not receipt.inspect_startup_receipt(temporary,expected_sha256=digest,expected_bytes=size,platform=platform)["available"]:
            raise ValueError("Generated startup receipt failed bounded envelope validation")
        temporary.rename(output)
        return pin
    finally:
        temporary.unlink(missing_ok=True)
        with cache._LOCK:cache._CACHE.clear()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("payload","translations","output","receipt"):parser.add_argument("--"+name,type=Path,required=True)
    for name in ("payload","translations"):
        parser.add_argument("--"+name+"-sha256",required=True)
        parser.add_argument("--"+name+"-bytes",type=int,required=True)
    parser.add_argument("--platform",choices=("android","ios"),required=True)
    args=parser.parse_args();sys.path.insert(0,str(ROOT/"src"))
    # Match Android/iOS's bundled parser and complete unknown-field wire output.
    os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"]="python"
    from idoly_local.public_payload import install_payload
    from idoly_local.bundled_translations import install_translation_bundle,resolve_translation_root
    if args.receipt.exists() or args.receipt.is_symlink():raise ValueError("Use an unused startup receipt pin output")
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".startup-receipt-",dir=args.output.parent) as work:
        data=Path(work)/"data"
        install_payload(args.payload,data,expected_sha256=args.payload_sha256,expected_bytes=args.payload_bytes)
        install_translation_bundle(args.translations,data,expected_sha256=args.translations_sha256,
                                   expected_bytes=args.translations_bytes,platform=args.platform)
        result=build(resolve_translation_root(data,platform=args.platform),data,args.output,platform=args.platform)
    with args.receipt.open("x") as target:target.write(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":main()
