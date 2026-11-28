"""The Fresh video bank accepts the game's own VideoImage binding states.

VideoImage._videoPlayer (+0xf0) is not serialized. Only VideoImage.OnEnable
writes it (GetComponent<VideoPlayer>() of its own GameObject), and the
SolisVideoPlayerTrack mixer first enables the image in PrepareCompleted. At
scene acquisition it is therefore null (device 2026.11.23.6 failed with
fresh_video_image_binding_unsupported). These checks run the shipping helper
with modeled memory reads; they do not execute Unity or decode video.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "client-presentation/native/bridge.cpp"


def _function(source, signature):
    begin = source.index(signature)
    at = source.index("{", begin) + 1
    depth = 1
    while depth:
        depth += (source[at] == "{") - (source[at] == "}")
        at += 1
    return source[begin:at]


def test_image_binding_accepts_unbound_until_publish(tmp_path):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("A host C++ compiler is required")
    helper = _function(BRIDGE.read_text(), "bool mp4_fresh_video_image_bound(")
    source = tmp_path / "binding.cpp"
    source.write_text(r'''
#include <cassert>
#include <cstddef>
#include <cstring>
namespace mp4camp {struct RenderLayout {static constexpr size_t video_image_player=0xf0;};}
struct Image {unsigned char bytes[0x100]{};bool readable=true;};
template<class T>bool mp4_actor_field(void*pointer,size_t offset,T&value){
  auto*image=static_cast<Image*>(pointer);if(!image||!image->readable||offset+sizeof(T)>sizeof image->bytes)return false;
  std::memcpy(&value,image->bytes+offset,sizeof(T));return true;
}
''' + helper + r'''
int main(){
  Image image{};int player=0,other=0;void*p=&player;void*o=&other;
  // Before the game's first OnEnable: tracked, but never published.
  assert(mp4_fresh_video_image_bound(&image,p,false));
  assert(!mp4_fresh_video_image_bound(&image,p,true));
  // After OnEnable bound this player.
  std::memcpy(image.bytes+0xf0,&p,sizeof p);
  assert(mp4_fresh_video_image_bound(&image,p,false)&&mp4_fresh_video_image_bound(&image,p,true));
  // Another player is never accepted.
  std::memcpy(image.bytes+0xf0,&o,sizeof o);
  assert(!mp4_fresh_video_image_bound(&image,p,false)&&!mp4_fresh_video_image_bound(&image,p,true));
  // Unreadable memory and a missing player fail closed.
  image.readable=false;assert(!mp4_fresh_video_image_bound(&image,p,false));
  image.readable=true;std::memset(image.bytes+0xf0,0,sizeof(void*));assert(!mp4_fresh_video_image_bound(&image,nullptr,false));
  return 0;
}
''')
    binary = tmp_path / "binding"
    built = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
                           capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
    assert ran.returncode == 0, ran.stderr


def test_inventory_pairs_the_image_like_the_game_and_names_each_case():
    source = BRIDGE.read_text()
    inventory = _function(source, "Mp4FreshResult mp4_fresh_video_inventory(")
    # The same-GameObject pairing of SolisVideoPlayerTrack.CreateTrackMixer, with
    # the bound player proven to be the GameObject's first VideoPlayer.
    for code in ("fresh_video_player_gameobject_invalid", "fresh_video_image_missing",
                 "fresh_video_image_type_unsupported", "fresh_video_image_player_ambiguous",
                 "fresh_video_image_field_unreadable", "fresh_video_image_bound_elsewhere"):
        assert code in inventory
    assert "fresh_video_image_binding_unsupported" not in source
    assert "||bound!=t.player)return fail" not in inventory  # the old strict form
    assert "if(bound&&bound!=t.player)return fail(\"fresh_video_image_bound_elsewhere\")" in inventory
    for name in ("bool mp4_fresh_video_current(", "bool mp4_fresh_video_add("):
        assert "mp4_fresh_video_image_bound(" in _function(source, name)
    assert "mp4_fresh_video_image_bound(e->image,id.player,true)" in _function(source, "bool mp4_fresh_video_publish(")
