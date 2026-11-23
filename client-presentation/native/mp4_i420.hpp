// SPDX-License-Identifier: AGPL-3.0-or-later
// Opaque sRGB RGBA8 to limited-range BT.709 I420, done natively before the
// frame reaches Java (as Elichika's exporter does). Java then stages 1.5
// bytes per pixel instead of 4, and its encoder thread only copies planes.
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace idoly_mp4_i420 {
// OfflineMp4Math.transferTable(): sRGB-encoded 8-bit to BT.709 OETF, rounded.
constexpr uint8_t srgb_to_709[256]={
    0,0,1,1,1,2,2,2,3,3,3,4,4,5,5,5,
    6,6,7,7,8,9,9,10,10,11,12,13,13,14,15,16,
    17,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,
    32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,
    48,49,50,51,52,53,55,56,57,58,59,60,61,62,63,64,
    65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,
    81,83,84,85,86,87,88,89,90,91,92,93,94,95,96,97,
    98,99,100,101,103,104,105,106,107,108,109,110,111,112,113,114,
    115,116,117,119,120,121,122,123,124,125,126,127,128,129,130,131,
    133,134,135,136,137,138,139,140,141,142,143,144,145,147,148,149,
    150,151,152,153,154,155,156,157,159,160,161,162,163,164,165,166,
    167,168,169,171,172,173,174,175,176,177,178,179,180,182,183,184,
    185,186,187,188,189,190,191,193,194,195,196,197,198,199,200,201,
    203,204,205,206,207,208,209,210,211,213,214,215,216,217,218,219,
    220,221,223,224,225,226,227,228,229,230,231,233,234,235,236,237,
    238,239,240,242,243,244,245,246,247,248,249,251,252,253,254,255};

inline size_t bytes(uint32_t width,uint32_t height){return static_cast<size_t>(width)*height*3/2;}
inline int clamp(int value,int lower,int upper){return value<lower?lower:value>upper?upper:value;}

// Rows are read first to last with row_bytes stride; Y, then U, then V, with
// no padding. Bit-identical to OfflineMp4Math.rgbaToI420 (alpha is ignored).
inline bool from_rgba(const uint8_t*rgba,size_t row_bytes,uint32_t width,uint32_t height,uint8_t*out,size_t out_bytes){
    if(!rgba||!out||width<2||height<2||(width&1)||(height&1)||row_bytes<static_cast<size_t>(width)*4
        ||out_bytes!=bytes(width,height))return false;
    const size_t pixels=static_cast<size_t>(width)*height;
    uint8_t*const u=out+pixels;uint8_t*const v=u+pixels/4;
    for(uint32_t y=0;y<height;y+=2){
        const uint8_t*const rows[2]={rgba+static_cast<size_t>(y)*row_bytes,rgba+static_cast<size_t>(y+1)*row_bytes};
        uint8_t*const luma[2]={out+static_cast<size_t>(y)*width,out+static_cast<size_t>(y+1)*width};
        const size_t chroma_row=static_cast<size_t>(y/2)*(width/2);
        for(uint32_t x=0;x<width;x+=2){
            int red=0,green=0,blue=0;
            for(int dy=0;dy<2;++dy)for(uint32_t dx=0;dx<2;++dx){
                const uint8_t*const p=rows[dy]+static_cast<size_t>(x+dx)*4;
                const int r=srgb_to_709[p[0]],g=srgb_to_709[p[1]],b=srgb_to_709[p[2]];
                luma[dy][x+dx]=static_cast<uint8_t>(clamp(16+((47*r+157*g+16*b+128)>>8),16,235));
                red+=r;green+=g;blue+=b;
            }
            u[chroma_row+x/2]=static_cast<uint8_t>(clamp(128+((-26*red-86*green+112*blue+512)>>10),16,240));
            v[chroma_row+x/2]=static_cast<uint8_t>(clamp(128+((112*red-102*green-10*blue+512)>>10),16,240));
        }
    }
    return true;
}
} // namespace idoly_mp4_i420
