// SPDX-License-Identifier: AGPL-3.0-or-later
#ifndef IDOLY_MV_ENCODER_POLICY_H
#define IDOLY_MV_ENCODER_POLICY_H
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

/* Integer timeline and bounded-buffer rules shared by the Apple encoder and
 * its host tests. No wall clock, renderer, microphone, or game offsets. */
enum { IDMVMaximumPendingFrames = 3, IDMVMaximumPCMChunkFrames = 8192 };

static inline bool IDMVMultiply(uint64_t left, uint64_t right, uint64_t *out) {
    if (!out || (right && left > UINT64_MAX / right)) return false;
    *out = left * right;
    return true;
}

static inline bool IDMVFrameBytes(uint32_t width, uint32_t height, size_t *out) {
    uint64_t pixels = 0, bytes = 0;
    if (!out || width < 16 || height < 16 || width > 8192 || height > 8192
            || (width & 1) || (height & 1)
            || !IDMVMultiply(width, height, &pixels) || pixels > UINT64_C(4096) * 2160
            || !IDMVMultiply(pixels, 4, &bytes) || bytes > SIZE_MAX) return false;
    *out = (size_t)bytes;
    return true;
}

static inline bool IDMVRationalFrameTime(uint64_t frame, uint32_t fpsNumerator,
                                        uint32_t fpsDenominator, int64_t *value,
                                        int32_t *timescale) {
    uint64_t scaled = 0;
    if (!value || !timescale || !fpsNumerator || fpsNumerator > 240000
            || !fpsDenominator || fpsDenominator > 10000
            || fpsNumerator < fpsDenominator
            || (uint64_t)fpsNumerator > (uint64_t)fpsDenominator * 120
            || !IDMVMultiply(frame, fpsDenominator, &scaled) || scaled > INT64_MAX)
        return false;
    *value = (int64_t)scaled;
    *timescale = (int32_t)fpsNumerator;
    return true;
}

static inline bool IDMVPCMBytes(uint64_t sampleFrames, uint32_t channels, uint64_t *bytes) {
    uint64_t samples = 0;
    return channels >= 1 && channels <= 2 && sampleFrames > 0
        && IDMVMultiply(sampleFrames, channels, &samples)
        && IDMVMultiply(samples, sizeof(float), bytes) && *bytes <= INT64_MAX;
}

/* Number of source PCM frames whose timestamps lie before the video endpoint.
 * The last source sample may straddle that endpoint, by strictly < one sample.
 * This helper does not synthesize, trim, or resample song data. */
static inline bool IDMVAudioFramesCoveringVideo(uint64_t videoFrames,
                                              uint32_t fpsNumerator,
                                              uint32_t fpsDenominator,
                                              uint32_t sampleRate, uint64_t *out) {
    int64_t value = 0;
    int32_t scale = 0;
    uint64_t product = 0;
    if (!out || !videoFrames || sampleRate < 8000 || sampleRate > 192000
            || !IDMVRationalFrameTime(videoFrames, fpsNumerator, fpsDenominator, &value, &scale)
            || !IDMVMultiply((uint64_t)value, sampleRate, &product)) return false;
    *out = product / (uint32_t)scale + (product % (uint32_t)scale != 0);
    return *out > 0;
}

static inline bool IDMVContiguousIndex(uint64_t wanted, uint64_t accepted, uint64_t total) {
    return accepted < total && wanted == accepted;
}

#endif
