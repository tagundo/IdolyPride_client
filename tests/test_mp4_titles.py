"""Public MV title data is reproducible and independent of job identity."""
import importlib.util
import json
import os
from pathlib import Path

import pytest

from idoly_local.mp4_titles import SOURCE_PROVENANCE, title_catalog


ROOT = Path(__file__).resolve().parents[1]


def builder():
    spec = importlib.util.spec_from_file_location("build_mp4_titles", ROOT / "tools/build_mp4_titles.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalog_has_real_localized_titles_with_fresh_bounded_maps():
    catalog = title_catalog()
    assert set(catalog) == {"ja", "ko", "en"}
    assert all(len(rows) == 77 for rows in catalog.values())
    assert len(json.dumps(catalog, ensure_ascii=True, separators=(",", ":")).encode("ascii")) <= 48 * 1024
    assert catalog["ja"]["tln_live_clb-006"] == "君のこころは輝いてるかい？"
    assert catalog["ko"]["tln_live_clb-006"] == "너의 마음은 빛나고 있니?"
    assert catalog["en"]["tln_live_clb-006"] == "Kimi no Kokoro wa Kagayaiteru kai?"
    assert all(rows["tln_live_tri-004"] == "lumière" for rows in catalog.values())
    assert all(not key.startswith("tln_live_mov_mv_") for rows in catalog.values() for key in rows)
    assert "tln_live_hsm-011" not in catalog["ja"]  # Ambiguous pre-rendered video variants are not 3D timelines.
    catalog["ko"]["tln_live_tri-004"] = "changed"
    catalog.clear()
    assert title_catalog()["ko"]["tln_live_tri-004"] == "lumière"


def test_generator_rejects_unpinned_or_linked_payload_before_decoding(tmp_path):
    tool = builder()
    source = tmp_path / "wrong.zip"; source.write_bytes(b"not the audited public payload")
    with pytest.raises(ValueError, match="pinned bounded"):
        tool.build(source)
    link = tmp_path / "alias.zip"; link.symlink_to(source)
    with pytest.raises(OSError):
        tool.build(link)
    assert tool.SOURCE_SHA256 == SOURCE_PROVENANCE["source_sha256"]
    assert tool.MUSIC_JSON_SHA256 == SOURCE_PROVENANCE["source_music_json_sha256"]
    assert tool.PACKS == SOURCE_PROVENANCE["packs"]


def test_generator_reproduces_module_from_actual_pinned_music_packs():
    source = Path(os.environ.get("IDOLY_MP4_TITLES_DATA", "/workspace/shared/idoly-qa-fixtures/ServerData.zip"))
    if not source.is_file():
        pytest.skip("Pinned public ServerData.zip is required for the SQLCipher rebuild")
    pytest.importorskip("sqlcipher3")
    assert builder().build(source) == (ROOT / "src/idoly_local/mp4_titles.py").read_bytes()
