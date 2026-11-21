// SPDX-License-Identifier: AGPL-3.0-or-later
// Synthetic encoder/independent decoder proof. This does not exercise a game MV.
#import <Foundation/Foundation.h>
#import <AVFoundation/AVFoundation.h>
#import <AudioToolbox/AudioToolbox.h>
#include "../../../client-presentation/native/mp4_encoder_api.h"
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static void Require(BOOL condition, NSString *message) {
    if (!condition) { fprintf(stderr, "FAIL: %s\n", message.UTF8String); exit(2); }
}

static double Now(void) { return [NSDate timeIntervalSinceReferenceDate]; }

static IDMP4EncoderStatus Status(IDMP4EncoderHandle encoder) {
    IDMP4EncoderStatus status = {0}; status.struct_size = sizeof(status); status.abi_version = 1;
    Require(IDMP4EncoderPoll(encoder, &status) == IDMP4_ACCEPTED, @"poll ABI"); return status;
}

static float Signal(uint64_t sample, uint32_t rate, uint32_t channel) {
    return (float)(0.3 * sin(2.0 * M_PI * (channel ? 431.0 : 997.0) * (double)sample / rate));
}

static void WritePCM(NSString *path, uint32_t rate, uint32_t channels, uint64_t frames) {
    NSMutableData *pcm = [NSMutableData dataWithLength:(NSUInteger)(frames * channels * sizeof(float))];
    float *values = (float *)pcm.mutableBytes;
    for (uint64_t frame = 0; frame < frames; ++frame)
        for (uint32_t channel = 0; channel < channels; ++channel)
            values[frame * channels + channel] = Signal(frame, rate, channel);
    Require([pcm writeToFile:path options:NSDataWritingWithoutOverwriting error:NULL], @"create fresh PCM");
}

static void FillFrame(uint8_t *bytes, size_t rowBytes, uint32_t width, uint32_t height, uint64_t index) {
    memset(bytes, 0x59, rowBytes * height);
    for (uint32_t y = 0; y < height; ++y) {
        for (uint32_t x = 0; x < width; ++x) {
            uint8_t *pixel = bytes + y * rowBytes + x * 4;
            pixel[0] = y < height/2 && x < width/2 ? 255 : 0;
            pixel[1] = y < height/2 && x >= width/2 ? 255 : 0;
            pixel[2] = y >= height/2 && x < width/2 ? 255 : 0;
            if (y >= height/2 && x >= width/2) pixel[0] = pixel[1] = pixel[2] = 128;
            // Seven independently decoded frame-ID cells, away from color samples.
            if (y >= height/2-12 && y < height/2 && x < 7*12) {
                const uint8_t bit = (index & (UINT64_C(1) << (x/12))) ? 255 : 0;
                pixel[0] = pixel[1] = pixel[2] = bit;
            }
            pixel[3] = 255;
        }
    }
}

static void DecodeVideo(AVAsset *asset, const IDMP4EncoderConfig *config) {
    NSArray<AVAssetTrack *> *tracks = [asset tracksWithMediaType:AVMediaTypeVideo];
    Require(tracks.count == 1, @"one video track");
    NSError *error = nil;
    AVAssetReader *reader = [[AVAssetReader alloc] initWithAsset:asset error:&error];
    AVAssetReaderTrackOutput *output = [[AVAssetReaderTrackOutput alloc] initWithTrack:tracks.firstObject
        outputSettings:@{(id)kCVPixelBufferPixelFormatTypeKey:@(kCVPixelFormatType_32BGRA)}];
    Require([reader canAddOutput:output], @"video reader output"); [reader addOutput:output];
    Require([reader startReading], @"video decode start");
    uint64_t count = 0;
    for (;;) {
        CMSampleBufferRef sample = [output copyNextSampleBuffer];
        if (!sample) break;
        CMTime wanted = CMTimeMake((int64_t)(count * config->fps_den), (int32_t)config->fps_num);
        Require(CMTimeCompare(CMSampleBufferGetPresentationTimeStamp(sample), wanted) == 0,
            @"every decoded video PTS is the requested rational index");
        CVPixelBufferRef pixel = CMSampleBufferGetImageBuffer(sample);
        Require(pixel && CVPixelBufferGetWidth(pixel) == config->width
            && CVPixelBufferGetHeight(pixel) == config->height, @"decoded dimensions");
        Require(CVPixelBufferLockBaseAddress(pixel, kCVPixelBufferLock_ReadOnly) == kCVReturnSuccess,
            @"decoded pixels readable");
        const uint8_t *bytes = (const uint8_t *)CVPixelBufferGetBaseAddress(pixel);
        const size_t stride = CVPixelBufferGetBytesPerRow(pixel);
        const uint8_t *top = bytes + 12 * stride + 12 * 4;
        const uint8_t *bottom = bytes + (config->height-12) * stride + 12 * 4;
        const uint8_t *right = bytes + 12 * stride + (config->width-12) * 4;
        Require(top[2] > 180 && top[0] < 70 && top[1] < 70, @"RGBA red remains top left");
        Require(bottom[0] > 180 && bottom[1] < 70 && bottom[2] < 70, @"blue remains bottom left");
        Require(right[1] > 180 && right[0] < 70 && right[2] < 70, @"green remains top right");
        uint64_t marker = 0;
        for (unsigned bit = 0; bit < 7; ++bit) {
            const uint8_t *cell = bytes + (config->height/2-6) * stride + (bit*12+6) * 4;
            if ((unsigned)cell[0] + cell[1] + cell[2] > 384) marker |= UINT64_C(1) << bit;
        }
        Require(marker == count, @"no frame dropped, duplicated, reordered, or borrowed after ACCEPTED");
        CVPixelBufferUnlockBaseAddress(pixel, kCVPixelBufferLock_ReadOnly);
        CFRelease(sample); ++count;
    }
    Require(reader.status == AVAssetReaderStatusCompleted && count == config->video_frame_count,
        @"all planned frames independently decoded");
}

static void DecodeAudio(AVAsset *asset, const IDMP4EncoderConfig *config) {
    NSArray<AVAssetTrack *> *tracks = [asset tracksWithMediaType:AVMediaTypeAudio];
    Require(tracks.count == 1, @"one audio track");
    AVAssetReader *reader = [[AVAssetReader alloc] initWithAsset:asset error:NULL];
    NSDictionary *settings = @{AVFormatIDKey:@(kAudioFormatLinearPCM), AVLinearPCMIsFloatKey:@YES,
        AVLinearPCMBitDepthKey:@32, AVLinearPCMIsNonInterleaved:@NO,
        AVSampleRateKey:@(config->audio_sample_rate), AVNumberOfChannelsKey:@(config->audio_channels)};
    AVAssetReaderTrackOutput *output = [[AVAssetReaderTrackOutput alloc] initWithTrack:tracks.firstObject
        outputSettings:settings];
    Require([reader canAddOutput:output], @"audio reader output"); [reader addOutput:output];
    Require([reader startReading], @"AAC decode start");
    uint64_t count = 0; double dot[2] = {0}, energy[2] = {0}, expectedEnergy[2] = {0};
    for (;;) {
        CMSampleBufferRef sample = [output copyNextSampleBuffer];
        if (!sample) break;
        CMTime wanted = CMTimeMake((int64_t)count, (int32_t)config->audio_sample_rate);
        Require(CMTimeCompare(CMSampleBufferGetPresentationTimeStamp(sample), wanted) == 0,
            @"decoded audio begins at source sample zero and stays contiguous");
        CMBlockBufferRef block = CMSampleBufferGetDataBuffer(sample);
        const size_t samples = (size_t)CMSampleBufferGetNumSamples(sample);
        const size_t length = samples * config->audio_channels * sizeof(float);
        NSMutableData *data = [NSMutableData dataWithLength:length];
        Require(block && CMBlockBufferGetDataLength(block) == length
            && CMBlockBufferCopyDataBytes(block, 0, length, data.mutableBytes) == noErr,
            @"decoded interleaved float32 PCM");
        const float *values = (const float *)data.bytes;
        for (size_t offset = 0; offset < samples; ++offset) {
            if (count+offset < 2048 || count+offset+2048 >= config->audio_sample_frames) continue;
            for (uint32_t channel = 0; channel < config->audio_channels; ++channel) {
                double actual = values[offset * config->audio_channels + channel];
                double expected = Signal(count+offset, config->audio_sample_rate, channel);
                dot[channel] += actual * expected; energy[channel] += actual * actual;
                expectedEnergy[channel] += expected * expected;
            }
        }
        count += samples; CFRelease(sample);
    }
    Require(reader.status == AVAssetReaderStatusCompleted && count == config->audio_sample_frames,
        @"AAC priming and tail trimmed to every original PCM frame exactly");
    for (uint32_t channel = 0; channel < config->audio_channels; ++channel)
        Require(dot[channel] / sqrt(energy[channel] * expectedEnergy[channel]) > 0.85,
            @"decoded AAC matches source position and channel without priming offset");
}

static IDMP4EncoderStatus WaitTerminal(IDMP4EncoderHandle encoder, double timeout) {
    double deadline = Now() + timeout;
    for (;;) {
        IDMP4EncoderStatus status = Status(encoder);
        if (status.phase == IDMP4_COMPLETED || status.phase == IDMP4_CANCELLED || status.phase == IDMP4_FAILED)
            return status;
        Require(Now() < deadline, @"bounded encoder completion"); usleep(2000);
    }
}

static void EncodeCase(NSString *directory, uint32_t codec, uint32_t rate, uint32_t channels,
                       uint32_t fpsNum, uint32_t fpsDen) {
    NSString *name = [NSString stringWithFormat:@"codec-%u-%u-%u", codec, rate, channels];
    NSString *pcm = [directory stringByAppendingPathComponent:[name stringByAppendingString:@".f32"]];
    NSString *partial = [directory stringByAppendingPathComponent:[name stringByAppendingString:@".partial.mp4"]];
    NSString *final = [directory stringByAppendingPathComponent:[name stringByAppendingString:@".mp4"]];
    // Deliberately not an AAC packet boundary or a whole video frame.
    uint64_t audioFrames = rate + 1777;
    WritePCM(pcm, rate, channels, audioFrames);
    IDMP4EncoderConfig config = {0}; config.struct_size = sizeof(config); config.abi_version = 1;
    config.width = 128; config.height = 96; config.fps_num = fpsNum; config.fps_den = fpsDen;
    config.video_codec = codec; config.video_bitrate = 2000000;
    config.audio_sample_rate = rate; config.audio_channels = channels; config.audio_bitrate = 128000;
    config.audio_sample_frames = audioFrames;
    config.video_frame_count = (audioFrames * fpsNum + rate * (uint64_t)fpsDen - 1) / (rate * (uint64_t)fpsDen);
    config.pcm_f32_path = pcm.fileSystemRepresentation; config.partial_path = partial.fileSystemRepresentation;
    config.final_path = final.fileSystemRepresentation;
    char error[192] = {0};
    IDMP4EncoderConfig invalid = config; ++invalid.video_frame_count;
    Require(!IDMP4EncoderCreate(&invalid, error, sizeof(error)) && !strcmp(error, "invalid_configuration"),
        @"timeline mismatch rejected before writing");
    IDMP4EncoderHandle encoder = IDMP4EncoderCreate(&config, error, sizeof(error));
    Require(encoder != NULL, [NSString stringWithFormat:@"create: %s", error]);
    Require(IDMP4EncoderDestroy(encoder) == IDMP4_RETRY, @"active worker cannot be destroyed");
    double permissionDeadline = Now() + 10;
    while (Status(encoder).phase == IDMP4_STARTING && Now() < permissionDeadline) usleep(1000);
    Require(Status(encoder).phase == IDMP4_ENCODING, @"writer prepared before frames");
    struct stat partialMode;
    Require(lstat(partial.fileSystemRepresentation, &partialMode) == 0 && (partialMode.st_mode & 0777) == 0600,
        @"owned partial permissions are 0600 before encoding");
    const size_t rowBytes = config.width * 4 + 16;
    NSMutableData *frame = [NSMutableData dataWithLength:rowBytes * config.height];
    double deadline = Now() + 90; uint64_t retryCount = 0;
    for (uint64_t index = 0; index < config.video_frame_count;) {
        FillFrame((uint8_t *)frame.mutableBytes, rowBytes, config.width, config.height, index);
        IDMP4EncoderStatus before = Status(encoder);
        int result = IDMP4EncoderAppendFrame(encoder, (const uint8_t *)frame.bytes, rowBytes, index);
        IDMP4EncoderStatus after = Status(encoder);
        Require(after.queued_frames <= 3, @"bounded accepted queue");
        if (result == IDMP4_RETRY) {
            Require(before.submitted_frames == after.submitted_frames, @"RETRY consumes no frame index");
            ++retryCount; usleep(1000);
        } else {
            Require(result == IDMP4_ACCEPTED, [NSString stringWithFormat:@"append: %s", after.error_code]);
            // Corrupt caller memory immediately; decoder proves ACCEPTED owns a copy.
            memset(frame.mutableBytes, 0, frame.length);
            Require(IDMP4EncoderAppendFrame(encoder, (const uint8_t *)frame.bytes, rowBytes, index) == IDMP4_ERROR,
                @"duplicate index rejected");
            ++index;
        }
        Require(Now() < deadline, @"bounded append loop");
    }
    Require(IDMP4EncoderFinish(encoder) == IDMP4_ACCEPTED
        && IDMP4EncoderFinish(encoder) == IDMP4_ACCEPTED, @"idempotent asynchronous finish");
    IDMP4EncoderStatus terminal = WaitTerminal(encoder, 90);
    Require(terminal.phase == IDMP4_COMPLETED,
        [NSString stringWithFormat:@"encode failed: %s", terminal.error_code]);
    Require(terminal.encoded_frames == config.video_frame_count
        && terminal.audio_frames == audioFrames && terminal.bytes_written > 0, @"exact producer totals");
    Require(IDMP4EncoderDestroy(encoder) == IDMP4_ACCEPTED, @"terminal worker released");
    Require(![[NSFileManager defaultManager] fileExistsAtPath:partial], @"partial moved only on completion");
    struct stat finalMode;
    Require(lstat(final.fileSystemRepresentation, &finalMode) == 0 && (finalMode.st_mode & 0777) == 0600,
        @"owned final permissions remain 0600 after publication");
    AVURLAsset *asset = [AVURLAsset URLAssetWithURL:[NSURL fileURLWithPath:final]
        options:@{AVURLAssetPreferPreciseDurationAndTimingKey:@YES}];
    DecodeVideo(asset, &config); DecodeAudio(asset, &config);
    Require(!IDMP4EncoderCreate(&config, error, sizeof(error)) && !strcmp(error, "output_exists"),
        @"published output never overwritten");
    NSString *cancelPartial = [directory stringByAppendingPathComponent:[name stringByAppendingString:@".cancel.partial.mp4"]];
    NSString *cancelFinal = [directory stringByAppendingPathComponent:[name stringByAppendingString:@".cancel.mp4"]];
    config.partial_path = cancelPartial.fileSystemRepresentation; config.final_path = cancelFinal.fileSystemRepresentation;
    IDMP4EncoderHandle cancelled = IDMP4EncoderCreate(&config, error, sizeof(error));
    Require(cancelled != NULL, @"cancel job created");
    double cancelDeadline = Now() + 15;
    while (Status(cancelled).phase == IDMP4_STARTING) {
        Require(Now() < cancelDeadline, @"cancel test writer became ready"); usleep(1000);
    }
    FillFrame((uint8_t *)frame.mutableBytes, rowBytes, config.width, config.height, 0);
    Require(IDMP4EncoderAppendFrame(cancelled, (const uint8_t *)frame.bytes, rowBytes, 0) == IDMP4_ACCEPTED,
        @"cancellation exercised after the writer accepted real media");
    while (Status(cancelled).encoded_frames == 0) {
        Require(Now() < cancelDeadline, @"cancel test writer encoded media"); usleep(1000);
    }
    IDMP4EncoderCancel(cancelled);
    Require(WaitTerminal(cancelled, 10).phase == IDMP4_CANCELLED, @"cancellation completes asynchronously");
    Require(IDMP4EncoderDestroy(cancelled) == IDMP4_ACCEPTED, @"cancel worker ended before destroy");
    Require(![[NSFileManager defaultManager] fileExistsAtPath:cancelPartial]
        && ![[NSFileManager defaultManager] fileExistsAtPath:cancelFinal], @"cancel publishes no MP4");
    printf("PASS codec=%u sample_rate=%u channels=%u fps=%u/%u video_frames=%llu audio_frames=%llu retries=%llu\n",
        codec, rate, channels, fpsNum, fpsDen, (unsigned long long)terminal.encoded_frames,
        (unsigned long long)terminal.audio_frames, (unsigned long long)retryCount);
}

int main(int argc, char *argv[]) {
    @autoreleasepool {
        Require(argc == 2, @"private scratch directory argument required");
        NSString *directory = [NSString stringWithUTF8String:argv[1]];
        EncodeCase(directory, IDMP4_H264, 44100, 1, 30000, 1001);
        EncodeCase(directory, IDMP4_HEVC, 48000, 2, 60, 1);
        puts("PASS original Apple encoder + independent video/AAC decode; game MV not exercised");
    }
    return 0;
}
