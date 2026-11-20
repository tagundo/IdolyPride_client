// SPDX-License-Identifier: AGPL-3.0-or-later
// Platform-neutral offline encoder boundary. Implementations use public OS APIs.
#pragma once
#ifndef IDOLY_DARWIN_BRIDGE
#include <stddef.h>
#include <stdint.h>
#endif

#if defined(__APPLE__)
#define IDMP4_ENCODER_API __attribute__((visibility("default")))
#else
#define IDMP4_ENCODER_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef void *IDMP4EncoderHandle;

enum IDMP4Result {
    IDMP4_ACCEPTED = 0,
    IDMP4_RETRY = 1,
    IDMP4_ERROR = -1,
    IDMP4_UNSUPPORTED = -2
};

enum IDMP4VideoCodec { IDMP4_H264 = 1, IDMP4_HEVC = 2 };
enum IDMP4EncoderPhase {
    IDMP4_STARTING = 1,
    IDMP4_ENCODING = 2,
    IDMP4_FINISHING = 3,
    IDMP4_COMPLETED = 4,
    IDMP4_CANCELLING = 5,
    IDMP4_CANCELLED = 6,
    IDMP4_FAILED = 7
};

typedef struct IDMP4EncoderConfig {
    uint32_t struct_size;
    uint32_t abi_version; // 1
    uint32_t width;
    uint32_t height;
    uint32_t fps_num;
    uint32_t fps_den;
    uint32_t video_codec;
    uint32_t video_bitrate;
    uint32_t audio_sample_rate;
    uint32_t audio_channels;
    uint32_t audio_bitrate;
    uint32_t reserved; // Must be zero.
    uint64_t audio_sample_frames;
    uint64_t video_frame_count;
    const char *pcm_f32_path; // Prepared full-timeline little-endian float32 PCM.
    const char *partial_path; // Private, exclusive job path; never a user file.
    const char *final_path; // Publish exclusively after complete A/V validation.
} IDMP4EncoderConfig;

typedef struct IDMP4EncoderStatus {
    uint32_t struct_size;
    uint32_t abi_version; // 1
    uint32_t phase;
    uint32_t queued_frames;
    uint64_t submitted_frames;
    uint64_t encoded_frames;
    uint64_t audio_frames;
    uint64_t bytes_written;
    char error_code[192]; // Stable code, not paths or credentials; NUL terminated.
} IDMP4EncoderStatus;

// Video PTS is exactly frame_index * fps_den / fps_num. Audio starts at sample 0.
// PCM is the prepared timeline soundtrack, including verified intro/outro silence
// and clip scheduling/gains, not an assumption that a clip spans the whole MV.
// Preserve every prepared audio frame. video_frame_count must be the ceiling of
// audio_sample_frames * fps_num / (audio_sample_rate * fps_den), so the video
// may end less than one frame after the exact audio end; do not truncate PCM.
// Configuration and path strings are copied before Create returns.
IDMP4_ENCODER_API IDMP4EncoderHandle IDMP4EncoderCreate(const IDMP4EncoderConfig *config,
                                    char *error_code, size_t error_capacity);

// Opaque SDR sRGB RGBA8, unpremultiplied, top row first. Convert linear/HDR
// sources explicitly before this boundary; both encoders write tagged Rec.709.
// The caller owns bytes until return.
// ACCEPTED copies the complete frame into a bounded owned queue; RETRY copies
// nothing, changes no index, and the caller must retain its frame/game clock.
IDMP4_ENCODER_API int IDMP4EncoderAppendFrame(IDMP4EncoderHandle encoder, const uint8_t *rgba,
                          size_t row_bytes, uint64_t frame_index);
IDMP4_ENCODER_API int IDMP4EncoderPoll(IDMP4EncoderHandle encoder, IDMP4EncoderStatus *status);
IDMP4_ENCODER_API int IDMP4EncoderFinish(IDMP4EncoderHandle encoder); // Nonblocking, idempotent.
IDMP4_ENCODER_API void IDMP4EncoderCancel(IDMP4EncoderHandle encoder); // Thread-safe, nonblocking.
// Call only after COMPLETED/CANCELLED/FAILED and all workers have stopped.
// Return RETRY while a worker still owns the encoder; NULL is already destroyed.
IDMP4_ENCODER_API int IDMP4EncoderDestroy(IDMP4EncoderHandle encoder);

#ifdef __cplusplus
}
#endif
