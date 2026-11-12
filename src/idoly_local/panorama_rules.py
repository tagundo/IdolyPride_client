"""Pinned public 360 LIVE catalog facts, independent of handler implementation.

The fourteen music/stage/order/condition mappings were read as factual data
from solis-server's public photo_panorama.yaml at commit
9b67c06939403d7035e1795745f791340a775868, file SHA-256
3cbd0d5d2b332aaae31370425b995e4c4ef165e32811ae7060a924e690cb68a1.
This is a secondary catalog source, not a captured official API response.
No implementation from that repository is included here. Every music, asset,
stage and camera reference is checked against the pinned original masters.

The fifteenth entry below has separate primary-master provenance: its one
explicit Music.selectableStageIds reference supplies its stage. It has no
claimed official API condition mapping; the media provider ignores conditions.
"""
from __future__ import annotations

from dataclasses import dataclass


MASTER_VERSION = "961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60"
SOURCE_SHA256 = "3cbd0d5d2b332aaae31370425b995e4c4ef165e32811ae7060a924e690cb68a1"
UNLOCK_CONDITION = "cd-tutorial-finish-photo-create-shooting"


@dataclass(frozen=True)
class PanoramaRule:
    music_id: str
    stage_id: str
    order: int
    view_condition_id: str


@dataclass(frozen=True)
class MasterPanoramaRule:
    music_id: str
    stage_id: str
    order: int
    release_time: int


# Original Music 6.1.1: is360LiveExist=true, exactly this one selectable stage,
# five cast positions, and this original release timestamp. The actual Stage
# supplies its asset and four camera positions. No official condition ID is
# guessed from the music ID or release date.
MASTER_PANORAMA_RULES = (
    MasterPanoramaRule("music-hsm-017", "stage-live-dome-03-00", 15, 1788145200000),
)


PANORAMA_RULES = (
    PanoramaRule("music-hsm-003", "stage-live-dome-01-00", 1, "cd-time-music-360live-25-0624"),
    PanoramaRule("music-hsm-015", "stage-live-dome-03-00", 2, "cd-time-music-360live-25-0624"),
    PanoramaRule("music-clb-011", "stage-live-unique-004-00", 3, "cd-time-music-clb-011-25-0826"),
    PanoramaRule("music-unit-012", "stage-live-dome-04-00", 4, "cd-time-music-unit-012-25-0927"),
    PanoramaRule("music-unit-010-360", "stage-live-dome-05-00", 5, "cd-time-music-unit-010-25-1128"),
    PanoramaRule("music-moon-010", "stage-live-dome-01-01", 6, "cd-time-music-moon-010-25-1224"),
    PanoramaRule("music-thrx-007", "stage-live-dome-02-01", 7, "cd-time-music-thrx-007-26-0104"),
    PanoramaRule("music-moon-011", "stage-live-dome-01-06", 8, "cd-time-music-moon-011-26-0128"),
    PanoramaRule("music-unit-013", "stage-live-dome-01-06", 9, "cd-time-music-unit-013-26-0226"),
    PanoramaRule("music-unit-014", "stage-live-dome-03-00", 10, "cd-time-music-unit-014-26-0327"),
    PanoramaRule("music-liz-005", "stage-live-dome-01-01", 11, "cd-time-music-liz-005-26-0527"),
    PanoramaRule("music-hsm-016", "stage-live-dome-04-00", 12, "cd-time-music-hsm-016-26-0624"),
    PanoramaRule("music-tri-010", "stage-live-dome-00-00", 13, "cd-time-music-tri-010-26-0625"),
    PanoramaRule("music-sun-004", "stage-live-dome-00-00", 14, "cd-time-music-sun-004-26-0708"),
)
