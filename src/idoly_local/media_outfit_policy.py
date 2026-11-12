"""Audited work-only 3D outfits allowed in the separate media account.

These twenty-one original training swimsuits are used by the hot-spring
PhotoActivity's force type ``mizg``. All have a real mdl_chr_<body>_body entry
in public manifest e9a4ccb49817338e311c60d22f7fea34fbeb02cad33c4ef81098b773abb1ae05.
The other forty hidden playable outfits are SD ambassador/police definitions
without that 3D body entry and are deliberately absent. No NPC is added.
The separate admin sets describe eighteen already-owned 3D rabbit outfits and
nineteen real hairs; clearing their media visibility flags grants no new row.

This module is pure standard-library data so the public master builder and
media inventory preparation share exactly the same narrow exception.
"""


COSTUME_IDS = frozenset((
    "cos-ai-mizg-00", "cos-aoi-mizg-00", "cos-chs-mizg-00",
    "cos-hrk-mizg-00", "cos-kan-mizg-00", "cos-kkr-mizg-00",
    "cos-kor-mizg-00", "cos-ktn-mizg-00", "cos-mei-mizg-00",
    "cos-mhk-mizg-00", "cos-mna-mizg-00", "cos-ngs-mizg-00",
    "cos-rei-mizg-00", "cos-rio-mizg-00", "cos-rui-mizg-00",
    "cos-ski-mizg-00", "cos-skr-mizg-00", "cos-smr-mizg-00",
    "cos-suz-mizg-00", "cos-szk-mizg-00", "cos-yu-mizg-00",
))


ADMIN_COSTUME_IDS = frozenset((
    "cos-ai-buny-00", "cos-aoi-buny-00", "cos-chs-buny-00",
    "cos-hrk-buny-00", "cos-kkr-buny-00", "cos-ktn-buny-00",
    "cos-mei-buny-00", "cos-mna-buny-00", "cos-ngs-buny-00",
    "cos-rei-buny-00", "cos-rio-buny-00", "cos-rui-buny-00",
    "cos-ski-buny-00", "cos-skr-buny-00", "cos-smr-buny-00",
    "cos-suz-buny-00", "cos-szk-buny-00", "cos-yu-buny-00",
))

ADMIN_HAIR_IDS = frozenset((
    "hair-ai-buny-00", "hair-aoi-buny-00", "hair-chs-buny-00",
    "hair-hrk-buny-00", "hair-kkr-buny-00", "hair-kor-hair-00",
    "hair-ktn-buny-00", "hair-mei-buny-00", "hair-mna-buny-00",
    "hair-ngs-buny-00", "hair-rei-buny-00", "hair-rio-buny-00",
    "hair-rui-buny-00", "hair-ski-buny-00", "hair-skr-buny-00",
    "hair-smr-buny-00", "hair-suz-buny-00", "hair-szk-buny-00",
    "hair-yu-buny-00",
))


def is_audited_work_costume(row):
    """Match the real owner, body and default hair, not a general ID prefix."""
    if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
            or row["id"] not in COSTUME_IDS):
        return False
    body = row["id"][4:]
    return (row.get("characterId") == "char-" + body.split("-", 1)[0]
            and row.get("costumeTypeId") == "mizg"
            and row.get("bodyAssetId") == body
            and row.get("defaultHairId") == "hair-" + body
            and row.get("isDisableAdmin") is False)


def is_audited_admin_costume(row):
    """Recognize only the eighteen original 3D rabbit outfits, without edits."""
    if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
            or row["id"] not in ADMIN_COSTUME_IDS):
        return False
    body = row["id"][4:]
    return (row.get("characterId") == "char-" + body.split("-", 1)[0]
            and row.get("costumeTypeId") == "idol"
            and row.get("bodyAssetId") == body
            and row.get("defaultHairId") == "hair-" + body
            and row.get("isUserUnavailable") is False)


def is_audited_admin_hair(row):
    """Recognize the eighteen matching hairs and fran's real twin-tail hair.

    Compatibility lists, pose restrictions and all asset references are kept;
    the media master builder changes only the audited admin visibility flag.
    """
    if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
            or row["id"] not in ADMIN_HAIR_IDS):
        return False
    asset = row["id"][5:]
    owner = asset.split("-", 1)[0]
    fitting = "cos-kor-casl-00" if row["id"] == "hair-kor-hair-00" else "cos-" + asset
    return (row.get("characterId") == "char-" + owner
            and row.get("hairAssetId") == asset
            and row.get("faceAssetId") == owner + "-base-00"
            and row.get("fittingCostumeId") == fitting)
