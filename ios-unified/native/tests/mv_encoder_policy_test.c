// SPDX-License-Identifier: AGPL-3.0-or-later
#include "../IdolyMVEncoderPolicy.h"
#include <assert.h>

int main(void) {
    size_t bytes = 0;
    assert(IDMVMaximumPendingFrames == 3);
    assert(IDMVMaximumPCMChunkFrames == 8192);
    assert(IDMVFrameBytes(3840, 2160, &bytes) && bytes == 33177600);
    assert(IDMVFrameBytes(2160, 3840, &bytes) && bytes == 33177600);
    assert(!IDMVFrameBytes(3841, 2160, &bytes));
    assert(!IDMVFrameBytes(7680, 4320, &bytes));
    assert(!IDMVFrameBytes(UINT32_MAX, UINT32_MAX, &bytes));
    assert(!IDMVFrameBytes(0, 0, &bytes));
    int64_t value = 0; int32_t scale = 0;
    assert(IDMVRationalFrameTime(1000000, 30000, 1001, &value, &scale));
    assert(value == INT64_C(1001000000) && scale == 30000);
    assert(IDMVRationalFrameTime(720000, 120, 1, &value, &scale));
    assert(value == 720000 && scale == 120);
    assert(!IDMVRationalFrameTime(UINT64_MAX, 30000, 1001, &value, &scale));
    assert(!IDMVRationalFrameTime(1, 121, 1, &value, &scale));
    assert(!IDMVRationalFrameTime(1, 0, 1, &value, &scale));
    assert(!IDMVRationalFrameTime(1, 60, 0, &value, &scale));
    uint64_t pcm = 0;
    assert(IDMVPCMBytes(48000, 2, &pcm) && pcm == 384000);
    assert(IDMVPCMBytes(44100, 1, &pcm) && pcm == 176400);
    assert(!IDMVPCMBytes(1, 3, &pcm));
    assert(!IDMVPCMBytes(UINT64_MAX, 2, &pcm));
    assert(!IDMVPCMBytes(0, 1, &pcm));
    uint64_t covering = 0;
    assert(IDMVAudioFramesCoveringVideo(1, 60, 1, 44100, &covering) && covering == 735);
    assert(IDMVAudioFramesCoveringVideo(1, 30000, 1001, 44100, &covering) && covering == 1472);
    assert(IDMVAudioFramesCoveringVideo(1000000, 30000, 1001, 44100, &covering));
    assert(covering == UINT64_C(1471470000));
    assert(!IDMVAudioFramesCoveringVideo(UINT64_MAX, 30000, 1001, 44100, &covering));
    assert(!IDMVAudioFramesCoveringVideo(1, 30, 1, 0, &covering));
    assert(IDMVContiguousIndex(0, 0, 73));
    assert(!IDMVContiguousIndex(1, 0, 73));
    assert(!IDMVContiguousIndex(72, 73, 73));
    assert(!IDMVContiguousIndex(73, 73, 73));
    return 0;
}
