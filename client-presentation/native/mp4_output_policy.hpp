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
    if(!dimensions(width,height)||(fps!=30&&fps!=60)||(codec!=1&&codec!=2))return 0;
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
// The original renderer must produce exactly these pixels. There is no
// letterbox, crop, stretch, or image-resampling fallback.
inline bool resolved_dimensions(uint32_t source_width,uint32_t source_height,uint32_t requested_width,uint32_t requested_height,uint32_t& width,uint32_t& height) {
    if(!source_dimensions(source_width,source_height)||!requested_dimensions(requested_width,requested_height))return false;
    width=requested_width?requested_width:source_width&~1U;
    height=requested_height?requested_height:source_height&~1U;
    return dimensions(width,height);
}
} // namespace idoly_mp4_output
