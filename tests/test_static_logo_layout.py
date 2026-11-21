import base64
import hashlib
import json
from pathlib import Path
import struct

import pytest

from idoly_local import static_ui_images as images

ROOT=Path(__file__).resolve().parents[1]
FIXTURES=json.loads((ROOT / "tests/fixtures/love-logo-rect-transforms.json").read_text())["objects"]


@pytest.mark.parametrize("fixture",FIXTURES,ids=lambda row:row["platform"]+"-"+row["name"])
def test_original_logo_transform_changes_only_its_sixteen_layout_bytes(fixture):
    raw=base64.b64decode(fixture["raw_base64"])
    assert len(raw)==108 and hashlib.sha256(raw).hexdigest()==fixture["sha256"]
    updated,proof=images._logo_rect(raw,fixture["name"],fixture["platform"])
    assert updated[:84]==raw[:84] and updated[100:]==raw[100:] and len(updated)==108
    target=images.LOGO_TRANSFORMS[fixture["name"]]
    assert struct.unpack_from("<4f",updated,84)==(target["x"],0.0,target["width"],24.0)
    assert proof["path_id"]==fixture["path_id"] and proof["only_position_and_size_changed"] is True
    assert proof["input_sha256"]==fixture["sha256"] and proof["output_sha256"]==hashlib.sha256(updated).hexdigest()


@pytest.mark.parametrize("offset",(4,12,40,52,60,68,84,92,100,104))
def test_logo_transform_rejects_changed_owner_hierarchy_animation_or_layout(offset):
    fixture=FIXTURES[0];raw=bytearray(base64.b64decode(fixture["raw_base64"]));raw[offset]^=1
    with pytest.raises(ValueError,match="Original Love logo RectTransform differs"):
        images._logo_rect(bytes(raw),fixture["name"],fixture["platform"])


def test_whole_logo_preserves_four_glyph_aspects_and_the_original_frame():
    end=-47.25;rows=[]
    for name in ("love_label_mo","love_label_shi","love_label_koi"):
        target=images.LOGO_TRANSFORMS[name]
        assert target["x"]-target["width"]/2==end
        end=target["x"]+target["width"]/2
        assert target["width"]/target["png_size"][0]==24/target["png_size"][1]==0.75
        assert -48<=target["x"]-target["width"]/2 and target["x"]+target["width"]/2<=48
        profile=next(row for row in images.PROFILES if row["name"]==name)
        assert tuple(profile["png_size"])==tuple(profile["sprite_size"])==target["png_size"]
        fixture=next(row for row in FIXTURES if row["name"]==name and row["platform"]=="ios")
        _,proof=images._logo_rect(base64.b64decode(fixture["raw_base64"]),name,"ios");rows.append(proof)
    assert end==47.25
    proof=images._logo_summary("ios",rows,[])
    assert proof["content_size"]==[94.5,24.0] and proof["original_frame"]==[96.0,32.0]
    assert proof["full_translated_glyphs_preserved"] is True
