#!/usr/bin/env python3
"""Fetch existing frozen Korean UI PNGs on an owned build runner; never redraw."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
ROOT = Path(__file__).resolve().parents[1]
REVISION = "f6e5689bcd6878d962996edfd390c1442b926c0f"
REPOSITORY = "https://github.com/CyleAR/ipr-translation-data-ko"
PROFILES = ("korean-static-sprites-v1.json", "korean-static-sprites-v2.json", "korean-static-textures-v1.json")

def need(ok, code):
    if not ok: raise ValueError(code)

def inventory(root=ROOT):
    result, profiles = {}, {}
    for name in PROFILES:
        path=Path(root)/"client-presentation/images"/name
        raw=path.read_bytes();need(0<len(raw)<=1024*1024,"image_profile_bound")
        value=json.loads(raw);origin=value.get("source",{})
        need(origin.get("repository")==REPOSITORY and origin.get("revision")==REVISION,"image_profile_origin_differs")
        rows=value.get("inputs");need(type(rows) is list and 0<len(rows)<=256,"image_profile_inventory_invalid")
        for row in rows:
            name=row["name"];filename=name if name.endswith(".png") else name+".png"
            need(re.fullmatch(r"[A-Za-z0-9_.-]{1,120}\.png",filename) is not None
                 and filename not in ("..png","...png"),"image_name_invalid")
            size=row.get("png_bytes",row.get("bytes"));digest=row.get("png_sha256",row.get("sha256"))
            need(type(size) is int and 0<size<=2*1024*1024 and type(digest) is str
                 and re.fullmatch(r"[0-9a-f]{64}",digest) is not None,"image_pin_invalid")
            pin={"bytes":size,"sha256":digest}
            need(filename not in result or result[filename]==pin,"image_duplicate_pin_differs")
            result[filename]=pin
        profiles[path.name]=hashlib.sha256(raw).hexdigest()
    need(sum(x["bytes"] for x in result.values())<=16*1024*1024,"image_total_bound")
    return dict(sorted(result.items())), profiles

def approved(url):
    p=urlsplit(url)
    need(p.scheme=="https" and p.hostname=="raw.githubusercontent.com" and not p.username
         and not p.password and p.port is None and not p.fragment,"image_url_origin_invalid")

class Redirects(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        approved(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def download(filename,pin,destination):
    url="https://raw.githubusercontent.com/CyleAR/ipr-translation-data-ko/"+REVISION+"/local-files/resource/img/"+quote(filename,safe="")
    approved(url)
    with build_opener(Redirects()).open(Request(url,headers={"User-Agent":"IdolyPride-public-image-build"}),timeout=45) as response:
        approved(response.geturl())
        need(response.status==200 and response.headers.get("Content-Encoding","identity")=="identity","image_http_invalid")
        raw=response.read(pin["bytes"]+1)
    need(len(raw)==pin["bytes"] and hashlib.sha256(raw).hexdigest()==pin["sha256"]
         and raw.startswith(b"\x89PNG\r\n\x1a\n"),"image_download_digest_differs")
    with Path(destination).open("xb") as stream:need(stream.write(raw)==len(raw),"image_write_incomplete")

def fetch_images(destination, *, downloader=download, root=ROOT):
    need(os.environ.get("GITHUB_ACTIONS")=="true","owned_actions_images_required")
    temporary=os.environ.get("RUNNER_TEMP","");need(bool(temporary) and Path(temporary).is_absolute(),"image_owned_root_required")
    temporary=Path(temporary).resolve(strict=True);destination=Path(destination)
    need(destination.is_absolute() and destination.parent.resolve(strict=True).is_relative_to(temporary)
         and not os.path.lexists(destination),"fresh_owned_image_directory_required")
    pins,profiles=inventory(root)
    destination.mkdir(mode=0o700)
    try:
        def one(item):
            name,pin=item;path=destination/name;downloader(name,pin,path)
            need(path.is_file() and not path.is_symlink() and path.stat().st_nlink==1
                 and path.stat().st_size==pin["bytes"] and hashlib.sha256(path.read_bytes()).hexdigest()==pin["sha256"],"image_output_pin_differs")
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(one,pins.items()))
    except BaseException:
        shutil.rmtree(destination)
        raise
    return {"schema":1,"source_revision":REVISION,"files":pins,"profile_sha256":profiles,"all_inputs_verified":True,"new_images_generated":False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--output",required=True,type=Path);p.add_argument("--report",required=True,type=Path)
    args=p.parse_args();result=fetch_images(args.output)
    with args.report.open("x") as f:json.dump(result,f,indent=2,sort_keys=True);f.write("\n")
    print(json.dumps({"status":"PASS","files":len(result["files"]),"source_revision":REVISION}))
if __name__=="__main__":main()
