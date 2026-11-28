"""Frozen public-image inputs and owned build-directory boundaries."""
import hashlib
import json
from pathlib import Path
import pytest
from tools import fetch_korean_ui_images as images
RAW=b"\x89PNG\r\n\x1a\nexisting translation pixels"

def fixture_root(tmp_path):
    root=tmp_path/"source";directory=root/"client-presentation/images";directory.mkdir(parents=True)
    for name in images.PROFILES:
        (directory/name).write_text(json.dumps({"source":{"repository":images.REPOSITORY,"revision":images.REVISION},
            "inputs":[{"name":"existing-label","png_bytes":len(RAW),"png_sha256":hashlib.sha256(RAW).hexdigest()}]}))
    return root

def test_all_current_frozen_sprite_and_texture_inputs_are_available_by_exact_byte_pin():
    rows,profiles=images.inventory()
    assert len(profiles)==3 and len(rows)>=138
    assert rows["love_btn_present.png"]["bytes"] == 1583
    assert len(rows["love_btn_present.png"]["sha256"]) == 64
    assert all(name.endswith(".png") and "/" not in name for name in rows)

@pytest.mark.parametrize("damage",["origin","traversal","bytes-bool","digest","conflict"])
def test_image_profiles_cannot_change_origin_paths_or_cross_profile_identity(tmp_path,damage):
    root=fixture_root(tmp_path);path=root/"client-presentation/images"/images.PROFILES[-1]
    d=json.loads(path.read_text());row=d["inputs"][0]
    if damage=="origin":d["source"]["revision"]="moving-main"
    elif damage=="traversal":row["name"]="../existing-label"
    elif damage=="bytes-bool":row["png_bytes"]=True
    elif damage=="digest":row["png_sha256"]="not-a-digest"
    elif damage=="conflict":row["png_bytes"]+=1
    path.write_text(json.dumps(d))
    with pytest.raises(ValueError):images.inventory(root)

def test_only_fresh_owned_outputs_receive_verified_existing_bytes(tmp_path,monkeypatch):
    root=fixture_root(tmp_path);work=tmp_path/"work";work.mkdir()
    monkeypatch.setenv("GITHUB_ACTIONS","true");monkeypatch.setenv("RUNNER_TEMP",str(work))
    def download(name,pin,path):path.write_bytes(RAW)
    result=images.fetch_images(work/"images",downloader=download,root=root)
    assert result["all_inputs_verified"] and result["new_images_generated"] is False
    assert (work/"images/existing-label.png").read_bytes()==RAW
    with pytest.raises(ValueError):images.fetch_images(work/"images",downloader=download,root=root)
    with pytest.raises(ValueError):images.fetch_images(tmp_path/"outside",downloader=download,root=root)

@pytest.mark.parametrize("damage",["bytes","symlink","missing"])
def test_failed_download_removes_only_its_new_directory(tmp_path,monkeypatch,damage):
    root=fixture_root(tmp_path);work=tmp_path/"work";work.mkdir()
    protected=tmp_path/"protected";protected.write_bytes(b"keep")
    monkeypatch.setenv("GITHUB_ACTIONS","true");monkeypatch.setenv("RUNNER_TEMP",str(work))
    def download(name,pin,path):
        if damage=="bytes":path.write_bytes(b"changed")
        elif damage=="symlink":path.symlink_to(protected)
    with pytest.raises(ValueError):images.fetch_images(work/"images",downloader=download,root=root)
    assert not (work/"images").exists() and protected.read_bytes()==b"keep"

@pytest.mark.parametrize("url",["http://raw.githubusercontent.com/x","https://user:secret@raw.githubusercontent.com/x", "https://example.com/x","https://raw.githubusercontent.com:443/x","file:///tmp/x"])
def test_image_fetch_never_targets_an_authenticated_or_nonpublic_origin(url):
    with pytest.raises(ValueError):images.approved(url)
