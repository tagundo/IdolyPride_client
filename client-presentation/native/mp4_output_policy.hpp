// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
// Exact original-renderer output dimensions and codec recommendations.
// Requested aspect ratios are rendered as 3D with expanded camera framing.
#ifndef IDOLY_DARWIN_BRIDGE
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#endif

namespace idoly_mp4_output {
constexpr uint32_t maximum_dimension=4096;
inline bool supported_fps(uint32_t fps) { return fps==30||fps==60||fps==120; }
// 30 fps retains the original 60 Hz simulation and samples every other tick.
// 120 fps advances the owned original loop at 120 Hz, one distinct step per frame.
inline uint32_t simulation_hz(uint32_t fps) { return !supported_fps(fps)?0:fps==120?120:60; }
inline bool source_dimensions(uint32_t width,uint32_t height) {
    return width>=16&&height>=16&&width<=maximum_dimension&&height<=maximum_dimension;
}
inline bool dimensions(uint32_t width,uint32_t height) {
    return source_dimensions(width,height)&&!(width&1)&&!(height&1);
}
inline bool requested_dimensions(uint32_t width,uint32_t height) {
    return (!width&&!height)||dimensions(width,height);
}
inline bool bitrate(uint32_t value) { return !value||(value>=100000&&value<=200000000); }
inline uint32_t recommended_bitrate(uint32_t width,uint32_t height,uint32_t fps,uint32_t codec) {
    if(!dimensions(width,height)||!supported_fps(fps)||(codec!=1&&codec!=2))return 0;
    // Elichika's bits/pixel/frame factors (.14 H.264, .09 HEVC), rounded
    // half-up to 0.01 Mbps so the displayed and encoded recommendation agree.
    const uint64_t numerator=static_cast<uint64_t>(width)*height*fps*(codec==1?14:9);
    uint64_t value=((numerator+500000)/1000000)*10000;
    if(value<250000)value=250000;
    if(value>200000000)value=200000000;
    return static_cast<uint32_t>(value);
}
inline uint32_t resolved_bitrate(uint32_t requested,uint32_t width,uint32_t height,uint32_t fps,uint32_t codec) {
    return !bitrate(requested)?0:requested?requested:recommended_bitrate(width,height,fps,codec);
}
// Java stages three RGBA copies plus one I420 frame under 128 MiB
// (OfflineMp4Math.pixels). Larger frames can never create an encoder.
inline bool staging_fits(uint32_t width,uint32_t height) {
    return static_cast<uint64_t>(width)*height*27/2<=128ULL*1024*1024;
}
// "Current" exports follow the live render target, which a large window at
// render_scale 2 makes larger than encoders accept. Keep them inside the
// broadly supported UHD class (3840x2160 in either orientation).
constexpr uint32_t current_long_edge=3840,current_short_edge=2160;
inline bool current_encodable(uint32_t width,uint32_t height) {
    const uint32_t longer=width>height?width:height,shorter=width>height?height:width;
    return dimensions(width,height)&&longer<=current_long_edge&&shorter<=current_short_edge&&staging_fits(width,height);
}
// The largest even render long-edge cap that keeps a target of this aspect
// encodable. The short edge keeps a 2 px margin for the renderer's rounding.
inline uint32_t current_long_edge_cap(uint32_t width,uint32_t height) {
    if(!source_dimensions(width,height))return 0;
    const uint64_t longer=width>height?width:height,shorter=width>height?height:width;
    uint64_t cap=current_long_edge;
    const uint64_t by_short=static_cast<uint64_t>(current_short_edge-2)*longer/shorter;
    if(by_short<cap)cap=by_short;
    if(cap>longer)cap=longer;
    return static_cast<uint32_t>(cap&~1ULL);
}
// A queued "current" job may meet its Add-time size turned by the window
// (the reload rotates it) or rounded differently once the long edge is
// capped. Anything else is a different render target and still fails.
inline bool same_current_geometry(uint32_t expected_width,uint32_t expected_height,uint32_t width,uint32_t height) {
    const auto near=[](uint32_t a,uint32_t b){return (a>b?a-b:b-a)<=4;};
    return (near(expected_width,width)&&near(expected_height,height))
        ||(near(expected_width,height)&&near(expected_height,width));
}
// The original renderer must produce exactly these pixels. There is no
// letterbox, crop, stretch, or image-resampling fallback.
inline bool resolved_dimensions(uint32_t source_width,uint32_t source_height,uint32_t requested_width,uint32_t requested_height,uint32_t& width,uint32_t& height) {
    if(!source_dimensions(source_width,source_height)||!requested_dimensions(requested_width,requested_height))return false;
    width=requested_width?requested_width:source_width&~1U;
    height=requested_height?requested_height:source_height&~1U;
    return dimensions(width,height);
}
} // namespace idoly_mp4_output
