// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
// Output dimensions are independent of the original game's render target.
// Preserve the complete final postprocessed frame and its aspect ratio; a
// differently shaped output receives opaque black bars, never a crop/stretch.
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
struct Fit {uint32_t width=0,height=0,x=0,y=0;};
inline Fit fit(uint32_t source_width,uint32_t source_height,uint32_t output_width,uint32_t output_height) {
    Fit result{};
    if(!source_dimensions(source_width,source_height)||!dimensions(output_width,output_height))return result;
    if(static_cast<uint64_t>(source_width)*output_height>static_cast<uint64_t>(source_height)*output_width) {
        result.width=output_width;
        result.height=static_cast<uint32_t>(static_cast<uint64_t>(source_height)*output_width/source_width);
    } else {
        result.height=output_height;
        result.width=static_cast<uint32_t>(static_cast<uint64_t>(source_width)*output_height/source_height);
    }
    if(!result.width)result.width=1;
    if(!result.height)result.height=1;
    result.x=(output_width-result.width)/2;result.y=(output_height-result.height)/2;
    return result;
}
inline uint32_t sample_position(uint32_t destination,uint32_t source_size,uint32_t destination_size) {
    // Pixel centres in unsigned 16.16; clamp both edges before interpolation.
    const uint64_t centred=(static_cast<uint64_t>(destination)*2+1)*source_size*32768/destination_size;
    if(centred<=32768)return 0;
    const uint64_t value=centred-32768,maximum=static_cast<uint64_t>(source_size-1)*65536;
    return static_cast<uint32_t>(value>maximum?maximum:value);
}
inline bool resample_rgba(const uint8_t* source,size_t source_capacity,uint32_t source_width,uint32_t source_height,
        uint8_t* output,size_t output_capacity,uint32_t output_width,uint32_t output_height) {
    if(!source||!output||!source_dimensions(source_width,source_height)||!dimensions(output_width,output_height))return false;
    const size_t source_bytes=static_cast<size_t>(source_width)*source_height*4;
    const size_t output_bytes=static_cast<size_t>(output_width)*output_height*4;
    if(source_capacity<source_bytes||output_capacity<output_bytes)return false;
    if(source_width==output_width&&source_height==output_height) {
        if(source!=output)memcpy(output,source,output_bytes);
        return true;
    }
    if(source==output)return false;
    for(size_t at=0;at<output_bytes;at+=4){output[at]=output[at+1]=output[at+2]=0;output[at+3]=255;}
    const Fit fitted=fit(source_width,source_height,output_width,output_height);
    for(uint32_t y=0;y<fitted.height;++y) {
        const uint32_t sy=sample_position(y,source_height,fitted.height),y0=sy>>16,y1=y0+1<source_height?y0+1:y0,fy=sy&65535;
        for(uint32_t x=0;x<fitted.width;++x) {
            const uint32_t sx=sample_position(x,source_width,fitted.width),x0=sx>>16,x1=x0+1<source_width?x0+1:x0,fx=sx&65535;
            const size_t a=(static_cast<size_t>(y0)*source_width+x0)*4,b=(static_cast<size_t>(y0)*source_width+x1)*4,
                c=(static_cast<size_t>(y1)*source_width+x0)*4,d=(static_cast<size_t>(y1)*source_width+x1)*4,
                target=(static_cast<size_t>(y+fitted.y)*output_width+x+fitted.x)*4;
            for(unsigned channel=0;channel<3;++channel) {
                const uint64_t top=static_cast<uint64_t>(source[a+channel])*(65536-fx)+static_cast<uint64_t>(source[b+channel])*fx;
                const uint64_t bottom=static_cast<uint64_t>(source[c+channel])*(65536-fx)+static_cast<uint64_t>(source[d+channel])*fx;
                output[target+channel]=static_cast<uint8_t>((top*(65536-fy)+bottom*fy+2147483648ULL)>>32);
            }
            output[target+3]=255;
        }
    }
    return true;
}
} // namespace idoly_mp4_output
