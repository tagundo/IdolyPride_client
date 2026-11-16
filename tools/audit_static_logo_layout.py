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
    if reader.class_id in (4,224):
        result["parent"] = [value.m_Father.m_FileID,value.m_Father.m_PathID]
        result["children"] = [[item.m_FileID,item.m_PathID] for item in value.m_Children]
        for key in ("m_LocalPosition","m_LocalScale","m_LocalRotation","m_AnchorMin","m_AnchorMax","m_AnchoredPosition","m_SizeDelta","m_Pivot"):
            if not hasattr(value,key): continue
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
    external_cache = {}
    with ZipFile(path) as archive:
        def script_info(asset, pointer):
            file_id, path_id = pointer
            target = asset
            external = None
            if file_id:
                need(0 < file_id <= len(asset.externals), "Script file ID exceeds source externals")
                external = str(asset.externals[file_id-1].path)
                member = "assets/bin/Data/" + external.rsplit("/",1)[-1]
                names=archive.namelist()
                if member in names: parts=[member]
                else:
                    numbered=[(int(name.rsplit(".split",1)[1]),name) for name in names
                              if re.fullmatch(re.escape(member)+r"\.split[0-9]+",name)]
                    numbered.sort();parts=[name for _,name in numbered]
                    need(not numbered or [number for number,_ in numbered]==list(range(len(numbered))),"Script split inventory differs")
                if not parts:
                    return {"resolved":False,"reason":"external_member_not_found","external":external,"pointer":pointer,
                        "nearby_member_names":[name for name in names if "globalgamemanagers" in name][:8]}
                if member not in external_cache:
                    need(len(parts)<=32 and sum(archive.getinfo(part).file_size for part in parts)<=32*1024*1024
                         and len(external_cache)<4,"Script source exceeds audit bound")
                    env = UnityPy.load(b"".join(archive.read(part) for part in parts))
                    need(len(env.files)==1,"Expected one serialized script source")
                    external_cache[member] = (env,next(iter(env.files.values())))
                target = external_cache[member][1]
            obj = target.objects.get(path_id)
            if obj is None or obj.class_id != 115:
                return {"resolved":False,"reason":"script_object_not_monoscript","external":external,"pointer":pointer,
                        "actual_class_id":None if obj is None else obj.class_id,"object_count":len(target.objects)}
            value = obj.read()
            return {"resolved":True,"external":external,"pointer":pointer,
                    "class_name":value.m_ClassName,"namespace":value.m_Namespace,"assembly":value.m_AssemblyName,
                    "sha256":hashlib.sha256(obj.get_raw_data()).hexdigest()}
        def ancestry(asset, transform_id):
            result,seen=[],set()
            while transform_id:
                need(transform_id not in seen and len(seen)<12,"Prefab ancestor chain exceeds bound")
                seen.add(transform_id)
                obj=asset.objects.get(transform_id)
                need(obj is not None and obj.class_id in (4,224),"Prefab ancestor is not an original Transform or RectTransform")
                value=obj.read();owner=value.m_GameObject
                need(owner.m_FileID==0 and owner.m_PathID in asset.objects,"Prefab ancestor owner is external")
                game=asset.objects[owner.m_PathID].read()
                row={"game_object_name":game.m_Name,"transform":fact(obj),"components":[]}
                for component in game.m_Component:
                    pointer=getattr(component,"component",component)
                    need(pointer.m_FileID==0 and pointer.m_PathID in asset.objects,"Prefab component is external")
                    child=asset.objects[pointer.m_PathID]
                    item={"path_id":child.path_id,"class_id":child.class_id}
                    if child.class_id==114:
                        raw=child.get_raw_data();need(len(raw)>=28,"Truncated MonoBehaviour")
                        item["script"]=script_info(asset,list(struct.unpack_from("<iq",raw,16)))
                    row["components"].append(item)
                    need(len(row["components"])<=64,"Prefab ancestor component count exceeds bound")
                result.append(row)
                need(value.m_Father.m_FileID==0,"Prefab ancestor parent is external")
                transform_id=value.m_Father.m_PathID
            return result
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
                item["script"] = script_info(asset,item["script_pointer"])
                if owner_file == 0 and owner_path in asset.objects and asset.objects[owner_path].class_id == 1:
                    game = asset.objects[owner_path].read();item["game_object_name"] = game.m_Name
                    components=[]
                    for component in game.m_Component:
                        pointer=getattr(component,"component",component)
                        components.append([pointer.m_FileID,pointer.m_PathID])
                    item["components"] = components
                    need([0,obj.path_id] in components,"Sprite consumer does not belong to source owner")
                    item["transforms"] = [fact(asset.objects[child]) for file_id,child in components
                        if file_id==0 and child in asset.objects and asset.objects[child].class_id==224]
                    if len(item["transforms"])==1:
                        item["ancestors"] = ancestry(asset,item["transforms"][0]["parent"][1])
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
