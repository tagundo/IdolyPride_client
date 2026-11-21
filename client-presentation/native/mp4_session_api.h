// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
// Thread-safe host commands. Original Unity methods run only on its own tick.
#ifndef IDOLY_DARWIN_BRIDGE
#include <stddef.h>
#include <stdint.h>
#endif

#ifdef IDOLY_DARWIN_BRIDGE
#define IDMP4_SESSION_API __attribute__((visibility("default")))
#else
#define IDMP4_SESSION_API __attribute__((visibility("hidden")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

enum IDMP4PauseReason {
    IDMP4_PAUSE_NONE = 0,
    IDMP4_PAUSE_LIFECYCLE_BACKGROUND = 1,
    IDMP4_PAUSE_SURFACE_UNAVAILABLE = 2,
    IDMP4_PAUSE_USER = 3
};

IDMP4_SESSION_API int IDMP4SessionConfigure(const char *broker, uint64_t epoch,
    const char *capability, const char *output, int platform);
IDMP4_SESSION_API int IDMP4SessionStart(uint32_t fps_num, uint32_t fps_den,
    uint32_t codec, uint32_t video_bitrate, uint32_t audio_bitrate);
// V2: video_bitrate=0 uses the output size/FPS/codec recommendation. Explicit
// output dimensions must both be even 16..4096; (0,0) follows the source with
// odd edges rounded down to an encoder-compatible size. V1 remains available.
IDMP4_SESSION_API int IDMP4SessionStartV2(uint32_t fps_num, uint32_t fps_den,
    uint32_t codec, uint32_t video_bitrate, uint32_t audio_bitrate,
    uint32_t output_width, uint32_t output_height);
IDMP4_SESSION_API size_t IDMP4SessionStatus(char *buffer, size_t capacity);
IDMP4_SESSION_API void IDMP4SessionCancel(void);
IDMP4_SESSION_API int IDMP4SessionReady(void);

// Suspend is acknowledged at the next boundary between Unity actions. Pending
// audio, capture/readback, encoder backpressure and exact frame PTS stay owned.
// A stopped Unity loop cannot acknowledge or advance work until it resumes.
// Status distinguishes pause_requested/pausing from acknowledged paused.
// Final codec publication/retirement may finish without another render frame.
IDMP4_SESSION_API void IDMP4SessionSuspend(int reason);
// Clears the current request. The host keeps explicit user-pause state so a
// lifecycle foreground event cannot accidentally resume a user-paused export.
IDMP4_SESSION_API void IDMP4SessionResume(void);

// Queue commands copy only bounded scalar options/opaque IDs on host threads.
// Selection, graphics and source geometry are captured on the Unity tick.
// Return 0 for accepted; inspect QueueStatus for completion or a stable error.
// Configure inspects the journal synchronously without Unity calls; inactive
// job edits also work in a cold server menu. The host runs file work off its UI.
IDMP4_SESSION_API int IDMP4QueueConfigure(const char *queue_directory, const char *export_directory);
IDMP4_SESSION_API int IDMP4QueueEnqueue(uint32_t fps_num, uint32_t fps_den,
    uint32_t codec, uint32_t video_bitrate, uint32_t audio_bitrate);
IDMP4_SESSION_API int IDMP4QueueEnqueueV2(uint32_t fps_num, uint32_t fps_den,
    uint32_t codec, uint32_t video_bitrate, uint32_t audio_bitrate,
    uint32_t output_width, uint32_t output_height);
IDMP4_SESSION_API int IDMP4QueueRun(void);
IDMP4_SESSION_API int IDMP4QueuePause(void);
IDMP4_SESSION_API int IDMP4QueueResume(void);
enum IDMP4QueueOperation { IDMP4_QUEUE_CANCEL=1, IDMP4_QUEUE_REMOVE=2,
    IDMP4_QUEUE_RETRY=3, IDMP4_QUEUE_MOVE=4 };
IDMP4_SESSION_API int IDMP4QueueCommand(int operation, const char *job_id, int position);
IDMP4_SESSION_API size_t IDMP4QueueStatus(char *buffer, size_t capacity);

#ifdef __cplusplus
}
#endif
