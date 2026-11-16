#!/usr/bin/env python3
"""Bounded read-only original Android prefab consumer audit on owned Actions."""
from __future__ import annotations
import argparse
import base64
import gc
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
BASE_BYTES = 159549324
BASE_SHA256 = "f5be0c0e19c2a17ea28ffa0c3205a49f5ab004f013e2e67e319aa192ca1995df"
NAMES = ("love_label_mo", "love_label_shi", "love_label_koi")

def need(value, message):
    if not value: raise ValueError(message)

def digest(path):
    with path.open("rb") as source: return hashlib.file_digest(source, "sha256").hexdigest()

def fact(reader):
    value = reader.read()
    result = {"path_id": reader.path_id, "class_id": reader.class_id,
              "sha256": hashlib.sha256(reader.get_raw_data()).hexdigest(),
              "file_offset": reader.byte_start, "bytes": len(reader.get_raw_data())}
    if reader.class_id == 224:
        result["parent"] = [value.m_Father.m_FileID,value.m_Father.m_PathID]
        result["children"] = [[item.m_FileID,item.m_PathID] for item in value.m_Children]
        for key in ("m_LocalPosition","m_LocalScale","m_LocalRotation","m_AnchorMin","m_AnchorMax","m_AnchoredPosition","m_SizeDelta","m_Pivot"):
            vector = getattr(value,key)
            result[key] = {axis:getattr(vector,axis) for axis in ("x","y","z","w") if hasattr(vector,axis)}
        result["raw_base64"] = base64.b64encode(reader.get_raw_data()).decode()
    return result

def audit(path):
    import UnityPy
    from idoly_local.static_ui_images import PROFILES
    need(path.is_file() and not path.is_symlink() and path.stat().st_size == BASE_BYTES and digest(path) == BASE_SHA256,
         "Pinned original Android donor differs")
    targets = {row["name"]:Path(row["android"]["member"]).name for row in PROFILES if row["name"] in NAMES}
    need(set(targets) == set(NAMES),"Complete original logo Sprite inputs required")
    references, inspected, candidates = [], 0, []
    with ZipFile(path) as archive:
        for row in archive.infolist():
            if not re.fullmatch("assets/bin/Data/[0-9a-f]{32}",row.filename) or not 48 <= row.file_size <= 4*1024*1024: continue
            inspected += row.file_size
            need(inspected <= 768*1024*1024,"Android source scan exceeds bound")
            raw = archive.read(row)
            matched = [name for name,member in targets.items() if member.encode() in raw]
            if not matched: continue
            need(len(candidates) < 64,"Android source candidate bound")
            env = UnityPy.load(raw)
            need(len(env.files)==1,"Expected one serialized prefab")
            asset = next(iter(env.files.values()))
            external_names = [str(item.path) for item in asset.externals]
            mapping = {name:[i+1 for i,item in enumerate(external_names) if targets[name] in item] for name in matched}
            candidates.append({"member":row.filename,"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),
                               "matching_external_ids":mapping,"object_count":len(asset.objects),"external_count":len(external_names)})
            need(len(asset.objects)<=10000,"Prefab object graph exceeds bound")
            for obj in asset.objects.values():
                if obj.class_id != 114: continue
                value = obj.get_raw_data()
                if not 96 <= len(value) <= 4096: continue
                matches = {name:[offset for file_id in ids for offset in range(0,len(value)-11,4)
                                 if value[offset:offset+12] == struct.pack("<iq",file_id,1)]
                           for name,ids in mapping.items()}
                matches = {name:offsets for name,offsets in matches.items() if offsets}
                if not matches: continue
                owner_file, owner_path = struct.unpack_from("<iq",value)
                item = {"member":row.filename,"component_path_id":obj.path_id,"component_sha256":hashlib.sha256(value).hexdigest(),
                        "bytes":len(value),"script_pointer":list(struct.unpack_from("<iq",value,16)),"matches":matches,
                        "owner":[owner_file,owner_path]}
                if owner_file == 0 and owner_path in asset.objects and asset.objects[owner_path].class_id == 1:
                    game = asset.objects[owner_path].read();item["game_object_name"] = game.m_Name
                    components=[]
                    for component in game.m_Component:
                        pointer=getattr(component,"component",component)
                        components.append([pointer.m_FileID,pointer.m_PathID])
                    item["components"] = components
                    item["transforms"] = [fact(asset.objects[child]) for file_id,child in components
                        if file_id==0 and child in asset.objects and asset.objects[child].class_id==224]
                references.append(item)
                need(len(references)<=128,"Android consumer reference bound")
            del asset,env;gc.collect()
    need(digest(path)==BASE_SHA256,"Original Android donor changed")
    return {"schema":1,"source_sha256":BASE_SHA256,"source_bytes":BASE_BYTES,"targets":targets,
            "scanned_bytes":inspected,"prefab_candidates":candidates,"aligned_consumer_candidates":references,
            "source_modified":False,"runtime_proof":False}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--android-base",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    need(os.environ.get("GITHUB_ACTIONS")=="true","Only owned Actions execution is supported")
    need(args.output.is_absolute() and not args.output.exists() and not args.output.is_symlink(),"Fresh absolute audit output required")
    result=audit(args.android_base);args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps({"status":"PASS_READ_ONLY_AUDIT","prefabs":len(result["prefab_candidates"]),"aligned_references":len(result["aligned_consumer_candidates"])}))

if __name__=="__main__": main()
