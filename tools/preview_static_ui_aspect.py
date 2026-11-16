#!/usr/bin/env python3
"""Read actual rebuilt Korean Sprite pixels and audit source logo consumers.

Only fixed, pinned translation inputs and source-bound APK/IPA donors are read.
The before pictures simulate the reported fixed-Image rectangle; after pictures
come from the generated APK Sprite. Neither is a physical Unity screenshot.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
NAMES = ("love_btn_present", "love_btn_achievement", "love_btn_playing")


def need(ok, message):
    if not ok: raise ValueError(message)


def digest(path):
    before = path.lstat()
    need(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= 192 * 1024 * 1024, "Expected a bounded client input")
    with path.open("rb") as source: value = hashlib.file_digest(source, "sha256").hexdigest()
    after = path.lstat()
    need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
         == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), "Client input changed")
    return value


def _render_checker(image):
    from PIL import Image, ImageDraw
    canvas = Image.new("RGBA", image.size, (132, 140, 148, 255))
    draw = ImageDraw.Draw(canvas)
    for y in range(0, image.height, 8):
        for x in range(0, image.width, 8):
            if (x // 8 + y // 8) % 2: draw.rectangle((x,y,x+7,y+7), fill=(166,174,182,255))
    canvas.alpha_composite(image)
    return canvas


def previews(client, provenance, images_dir, output, source_commit):
    from io import BytesIO
    import importlib.metadata
    from PIL import Image
    from idoly_local import static_ui_images as sprites
    need(provenance.get("source_commit") == source_commit and provenance.get("ui_language") == "ko"
         and provenance.get("output_bytes") == client.stat().st_size
         and provenance.get("output_apk_sha256") == digest(client), "Korean client provenance differs")
    need(importlib.metadata.version("UnityPy") == "1.25.4", "Use pinned UnityPy 1.25.4")
    import UnityPy
    rows = []
    with ZipFile(client) as archive:
        for name in NAMES:
            profile = next(row for row in sprites.PROFILES if row["name"] == name)
            proof = next(row for row in provenance["static_ui_images"]["sprites"] if row["name"] == name)
            member = profile["android"]["member"]
            need(archive.namelist().count(member) == 1 and archive.getinfo(member).file_size <= 128 * 1024,
                 "Expected one bounded generated Sprite asset")
            raw = archive.read(member)
            need(hashlib.sha256(raw).hexdigest() == proof["output_sha256"]
                 and proof["layout_policy"] == sprites.TEXT_LAYOUT_POLICY and proof["readback_pixel_exact"] is True,
                 "Generated Sprite proof differs")
            environment = UnityPy.load(raw); asset = next(iter(environment.files.values()))
            need(sorted((obj.path_id, obj.class_id) for obj in environment.objects) == [(1, 213), (2, 28)],
                 "Generated Korean Sprite graph differs")
            sprite = asset.objects[1].read(); after = sprite.image.convert("RGBA")
            png = sprites._png(images_dir, profile); expected = sprites._canvas(png, profile)
            need(after.size == expected.size == tuple(profile["android"]["source_layout"]["sprite_size"])
                 and after.tobytes() == expected.tobytes(), "Actual generated Sprite pixels differ")
            with Image.open(BytesIO(png)) as source: before = source.convert("RGBA").resize(after.size, Image.Resampling.BILINEAR)
            # Equal four-times scaling improves visibility without changing the
            # measured source pixels or the actual packaged client image.
            panel = Image.new("RGBA", (after.width * 4, after.height * 8), (0,0,0,0))
            panel.paste(_render_checker(before).resize((after.width*4, after.height*4), Image.Resampling.NEAREST), (0,0))
            panel.paste(_render_checker(after).resize((after.width*4, after.height*4), Image.Resampling.NEAREST), (0,after.height*4))
            path = output / (name + "-before-after.png"); panel.save(path, format="PNG")
            rows.append({"name": name, "png_sha256": profile["png_sha256"], "client_member_sha256": hashlib.sha256(raw).hexdigest(),
                "original_ui_rect": list(after.size), "previous_sprite_rect": profile["png_size"],
                "content_size": profile["content_size"], "padding_offset": profile["padding_offset"],
                "actual_output_RGBA_sha256": hashlib.sha256(after.tobytes()).hexdigest(),
                "actual_generated_pixel_readback": True, "before_is_fixed_rectangle_simulation": True,
                "preview": {"name": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}})
            del environment, asset, after, expected, panel; gc.collect()
    return rows


def previews_ios(package, report, images_dir, output, source_commit):
    import copy
    from io import BytesIO
    from PIL import Image
    from idoly_local import static_ui_images as sprites
    reader = _builder()
    need(report.get("source_commit") == source_commit and report.get("korean_resources_refreshed") is True
         and report["package"]["bytes"] == package.stat().st_size
         and report["package"]["sha256"] == digest(package), "Fresh Korean language package proof differs")
    proof = report["proofs"]["korean_resources"]
    need(proof["original_stock_rebuilt"] is True and proof["all_other_objects_byte_identical"] is True,
         "Korean resource graph preservation is required")
    targets = {row["name"]: row for row in proof["static_images"]["sprites"] if row["name"] in NAMES}
    need(set(targets) == set(NAMES), "Expected all reported Korean button targets")
    wanted = {path for row in targets.values() for path in (row["sprite_path_id"],row["private_texture_path_id"])}
    raw_objects = {}
    with ZipFile(package) as archive, archive.open("ko/" + reader.RESOURCES) as incoming:
        index = reader._resource_index(incoming); position = index["offset"]
        for path, relative, size, kind in reader._resource_rows(index):
            reader._skip(incoming,index["offset"]+relative-position)
            if path in wanted:
                need(size <= 128*1024, "Generated button object exceeds preview bound")
                raw_objects[path] = reader._exact(incoming,size)
            else: reader._skip(incoming,size)
            position=index["offset"]+relative+size
    need(set(raw_objects)==wanted,"Generated button object is missing")
    results=[]
    for name in NAMES:
        profile=next(row for row in sprites.PROFILES if row["name"]==name); row=targets[name]
        raw, texture = raw_objects[row["sprite_path_id"]], raw_objects[row["private_texture_path_id"]]
        need(hashlib.sha256(raw).hexdigest()==row["output_sha256"]
             and hashlib.sha256(texture).hexdigest()==row["texture_sha256"],"Generated iOS button proof differs")
        env,sprite_reader=sprites._mini_asset(raw,213,9)
        texture_env,texture_reader=sprites._mini_asset(texture,28,9)
        owner=sprite_reader.assets_file
        clone=copy.copy(texture_reader);clone.assets_file=owner;clone.path_id=row["private_texture_path_id"];clone.type_id=len(owner.types)
        clone.serialized_type=copy.copy(texture_reader.serialized_type);clone.set_raw_data(texture)
        owner.types.append(clone.serialized_type);owner.objects[clone.path_id]=clone
        after=sprite_reader.read().image.convert("RGBA")
        png=sprites._png(images_dir,profile); expected=sprites._canvas(png,profile)
        need(after.size==expected.size and after.tobytes()==expected.tobytes(),"Generated iOS Sprite pixels differ")
        with Image.open(BytesIO(png)) as source: before=source.convert("RGBA").resize(after.size,Image.Resampling.BILINEAR)
        panel=Image.new("RGBA",(after.width*4,after.height*8),(0,0,0,0))
        panel.paste(_render_checker(before).resize((after.width*4,after.height*4),Image.Resampling.NEAREST),(0,0))
        panel.paste(_render_checker(after).resize((after.width*4,after.height*4),Image.Resampling.NEAREST),(0,after.height*4))
        path=output/(name+"-before-after.png");panel.save(path,format="PNG")
        results.append({"name":name,"png_sha256":profile["png_sha256"],"original_ui_rect":list(after.size),
            "previous_sprite_rect":profile["png_size"],"content_size":profile["content_size"],
            "padding_offset":profile["padding_offset"],"actual_generated_pixel_readback":True,
            "before_is_fixed_rectangle_simulation":True,"source":"generated_iOS_language_archive",
            "preview":{"name":path.name,"bytes":path.stat().st_size,"sha256":digest(path)}})
        del env,texture_env,clone,after,expected,panel;gc.collect()
    return results


def _builder():
    spec = importlib.util.spec_from_file_location("static_aspect_language_reader", ROOT / "tools/build_ios_client_languages.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def _virtual(raw, type_record):
    import UnityPy
    metadata = bytearray(b"2022.3.57f1\0" + struct.pack("<iBi", 9, 0, 1) + type_record)
    metadata.extend(struct.pack("<i", 1)); metadata.extend(b"\0" * (-(48 + len(metadata)) % 4))
    metadata.extend(struct.pack("<qQIi", 1, 0, len(raw), 0)); metadata.extend(b"\0" * 13)
    offset = (48 + len(metadata) + 15) & ~15
    header = struct.pack(">4I", 0,0,22,0) + b"\0" * 4 + struct.pack(">IQQQ",len(metadata),offset+len(raw),offset,0)
    env = UnityPy.load(header + metadata + b"\0" * (offset-48-len(metadata)) + raw)
    return next(iter(env.objects)).read()


def logo_consumers(base):
    from idoly_local import static_ui_images as sprites
    reader = _builder()
    need(base.stat().st_size == reader.BASE_BYTES and digest(base) == reader.BASE_SHA256,
         "Original Korean donor IPA differs")
    targets = {row["name"]: row["ios"][0]["path_id"] for row in sprites.PROFILES
               if row["name"] in ("love_label_mo", "love_label_shi", "love_label_koi")}
    needles = {name: struct.pack("<iq",0,path) for name,path in targets.items()}
    candidates = []
    with ZipFile(base) as archive:
        with archive.open(reader.APP + reader.RESOURCES) as source:
            index = reader._resource_index(source); position = index["offset"]
            for path, relative, size, kind in reader._resource_rows(index):
                reader._skip(source, index["offset"] + relative - position)
                if index["types"][kind][0] == 114 and 32 <= size <= 4096:
                    raw = reader._exact(source, size)
                    matches = {name: [m.start() for m in re.finditer(re.escape(needle),raw)]
                               for name,needle in needles.items() if needle in raw}
                    if matches:
                        file_id, owner = struct.unpack_from("<iq",raw)
                        candidates.append({"path_id":path,"object_sha256":hashlib.sha256(raw).hexdigest(),
                            "script_pointer":list(struct.unpack_from("<iq",raw,16)),
                            "owner":owner if file_id == 0 else None,"matches":matches,
                            "type_record_sha256":hashlib.sha256(index["types"][kind][1]).hexdigest()})
                        need(len(candidates)<=64,"Logo candidate count exceeds bound")
                else: reader._skip(source,size)
                position = index["offset"] + relative + size
        wanted = {row["owner"] for row in candidates if row["owner"]}
        objects = {}
        def capture(ids):
            with archive.open(reader.APP + reader.RESOURCES) as source:
                current = reader._resource_index(source); position = current["offset"]
                for path,relative,size,kind in reader._resource_rows(current):
                    reader._skip(source,current["offset"]+relative-position)
                    if path in ids:
                        need(size<=64*1024,"Logo owner object exceeds bound")
                        raw=reader._exact(source,size)
                        objects[path]=(raw,current["types"][kind])
                    else: reader._skip(source,size)
                    position=current["offset"]+relative+size
        capture(wanted)
        transforms = set()
        for row in candidates:
            owner = objects.get(row["owner"])
            if owner is None or owner[1][0] != 1:
                row["owner_resolved"] = False; continue
            game = _virtual(owner[0],owner[1][1]); row["owner_resolved"]=True; row["game_object_name"]=game.m_Name
            pointers=[]
            for component in game.m_Component:
                component=getattr(component,"component",component)
                if component.m_FileID==0: pointers.append(component.m_PathID)
            row["component_ids"]=pointers; transforms.update(pointers)
        capture(transforms)
        for row in candidates:
            records=[]
            for path in row.get("component_ids",[]):
                item=objects.get(path)
                if item is None or item[1][0]!=224: continue
                transform=_virtual(item[0],item[1][1])
                facts={"path_id":path,"sha256":hashlib.sha256(item[0]).hexdigest(),"parent":transform.m_Father.m_PathID}
                for key in ("m_LocalPosition","m_LocalScale","m_LocalRotation","m_AnchorMin","m_AnchorMax","m_AnchoredPosition","m_SizeDelta","m_Pivot"):
                    value=getattr(transform,key)
                    facts[key]={axis:getattr(value,axis) for axis in ("x","y","z","w") if hasattr(value,axis)}
                records.append(facts)
            row["rect_transforms"]=records
    need(digest(base)==reader.BASE_SHA256,"Korean donor changed during logo audit")
    return {"source_ipa_sha256":reader.BASE_SHA256,"sprite_ids":targets,"candidates":candidates,
            "consumer_references_are_candidates_not_runtime_proof":True,"sprite_or_layout_modified":False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client",type=Path)
    parser.add_argument("--provenance",type=Path)
    parser.add_argument("--images",type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--ios-base",type=Path)
    parser.add_argument("--client-languages",type=Path)
    parser.add_argument("--language-report",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    need(os.environ.get("GITHUB_ACTIONS")=="true", "Run this actual client audit only on an owned Actions runner")
    need(args.output.is_absolute() and not args.output.exists() and not args.output.is_symlink(),"Fresh absolute audit output required")
    args.output.mkdir(mode=0o700,parents=True)
    report={"schema":1,"physical_gameplay_tested":False,"runtime_image_hook":False}
    if args.client is not None:
        need(args.provenance is not None and args.images is not None
             and re.fullmatch("[0-9a-f]{40}",args.source_commit or ""),"Complete client proof arguments required")
        need(args.provenance.is_file() and not args.provenance.is_symlink() and args.provenance.stat().st_size<=1024*1024,"Bounded client provenance required")
        report["buttons"]=previews(args.client,json.loads(args.provenance.read_text()),args.images,args.output,args.source_commit)
    if args.client_languages is not None:
        need(args.language_report is not None and args.images is not None
             and re.fullmatch("[0-9a-f]{40}",args.source_commit or ""),"Complete language proof arguments required")
        need(args.language_report.is_file() and not args.language_report.is_symlink()
             and args.language_report.stat().st_size<=1024*1024,"Bounded language proof required")
        report["buttons"]=previews_ios(args.client_languages,json.loads(args.language_report.read_text()),args.images,args.output,args.source_commit)
    if args.ios_base is not None: report["logo_consumer_audit"]=logo_consumers(args.ios_base)
    need("buttons" in report or "logo_consumer_audit" in report,"An actual client or pinned logo donor is required")
    report["status"]="PASS"
    (args.output/"static-ui-aspect-proof.json").write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
    print(json.dumps({"status":report["status"],"buttons":len(report.get("buttons",[])),"logo_audited":"logo_consumer_audit" in report}))


if __name__=="__main__": main()
