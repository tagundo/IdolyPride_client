// SPDX-License-Identifier: AGPL-3.0-or-later
// Offline MP4 encoding through public Apple APIs. No game offsets or capture APIs.
#import <Foundation/Foundation.h>
#import <AVFoundation/AVFoundation.h>
#import <AudioToolbox/AudioToolbox.h>
#import <CoreMedia/CoreMedia.h>
#import <CoreVideo/CoreVideo.h>
#import <VideoToolbox/VideoToolbox.h>
#include "../../client-presentation/native/mp4_encoder_api.h"
#include "IdolyMVEncoderPolicy.h"
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static void IDMVCode(char *destination, size_t capacity, const char *code) {
    if (destination && capacity) snprintf(destination, capacity, "%s", code ?: "unknown");
}

static BOOL IDMVTerminal(uint32_t phase) {
    return phase == IDMP4_COMPLETED || phase == IDMP4_CANCELLED || phase == IDMP4_FAILED;
}

static BOOL IDMVSameFile(const struct stat *left, const struct stat *right) {
    return S_ISREG(right->st_mode) && right->st_nlink == 1
        && left->st_dev == right->st_dev && left->st_ino == right->st_ino;
}

static uint8_t IDMVsRGBTo709(uint8_t value) {
    const double encoded = (double)value / 255.0;
    const double linear = encoded <= 0.04045 ? encoded / 12.92
        : pow((encoded + 0.055) / 1.055, 2.4);
    const double output = linear < 0.018 ? 4.5 * linear : 1.099 * pow(linear, 0.45) - 0.099;
    return (uint8_t)lround(fmax(0.0, fmin(1.0, output)) * 255.0);
}

@interface IDMVQueuedFrame : NSObject
@property(nonatomic, strong) NSData *rgba;
@property(nonatomic) uint64_t index;
@end
@implementation IDMVQueuedFrame
@end

@interface IDMVEncoder : NSObject {
    NSLock *_lock;
    dispatch_queue_t _queue;
    dispatch_source_t _timer;
    NSMutableArray<IDMVQueuedFrame *> *_frames;
    IDMP4EncoderConfig _config;
    IDMP4EncoderStatus _status;
    NSString *_pcmPath, *_partialPath, *_finalPath;
    AVAssetWriter *_writer;
    AVAssetWriterInput *_video, *_audio;
    AVAssetWriterInputPixelBufferAdaptor *_adaptor;
    CMAudioFormatDescriptionRef _audioFormat;
    int _pcmFD;
    struct stat _pcmIdentity, _partialIdentity, _directoryIdentity;
    BOOL _partialOwned, _cancelRequested, _finishRequested, _finishStarted;
    BOOL _videoEnded, _audioEnded, _workerStopped;
    size_t _frameBytes;
    uint8_t _transfer[256];
}
- (instancetype)initWithConfig:(const IDMP4EncoderConfig *)config error:(char *)error capacity:(size_t)capacity;
- (int)append:(const uint8_t *)rgba rowBytes:(size_t)rowBytes index:(uint64_t)index;
- (int)poll:(IDMP4EncoderStatus *)status;
- (int)finish;
- (void)cancel;
- (BOOL)canDestroy;
- (void)startWorker;
- (void)pump;
- (void)publishCompletedWriter;
@end

@implementation IDMVEncoder
- (instancetype)initWithConfig:(const IDMP4EncoderConfig *)config error:(char *)error capacity:(size_t)capacity {
    self = [super init];
    if (!self) return nil;
    _pcmFD = -1;
    uint64_t pcmBytes = 0, frameNumerator = 0, audioDenominator = 0;
    int64_t endpoint = 0; int32_t timescale = 0, movieTimescale = 0;
    if (!config || config->struct_size != sizeof(*config) || config->abi_version != 1
            || config->reserved || !IDMVFrameBytes(config->width, config->height, &_frameBytes)
            || !IDMVRationalFrameTime(config->video_frame_count, config->fps_num, config->fps_den,
                                     &endpoint, &timescale)
            || !IDMVPCMBytes(config->audio_sample_frames, config->audio_channels, &pcmBytes)
            || config->audio_sample_rate < 8000 || config->audio_sample_rate > 192000
            || !IDMVCommonTimeScale(config->fps_num, config->audio_sample_rate, &movieTimescale)
            || !IDMVMultiply(config->audio_sample_frames, config->fps_num, &frameNumerator)
            || !IDMVMultiply(config->audio_sample_rate, config->fps_den, &audioDenominator)
            || !config->video_frame_count || config->video_frame_count != frameNumerator / audioDenominator
                + (frameNumerator % audioDenominator != 0)
            || endpoint > (int64_t)timescale * 60 * 60 * 2
            || config->video_bitrate < 100000 || config->video_bitrate > 200000000
            || config->audio_bitrate < 32000 || config->audio_bitrate > 512000
            || (config->video_codec != IDMP4_H264 && config->video_codec != IDMP4_HEVC)) {
        IDMVCode(error, capacity, "invalid_configuration"); return nil;
    }
    NSString *pcm = config->pcm_f32_path ? [NSString stringWithUTF8String:config->pcm_f32_path] : nil;
    NSString *partial = config->partial_path ? [NSString stringWithUTF8String:config->partial_path] : nil;
    NSString *final = config->final_path ? [NSString stringWithUTF8String:config->final_path] : nil;
    if (!pcm.isAbsolutePath || !partial.isAbsolutePath || !final.isAbsolutePath
            || ![partial.pathExtension.lowercaseString isEqualToString:@"mp4"]
            || ![final.pathExtension.lowercaseString isEqualToString:@"mp4"]
            || [partial isEqualToString:final]) {
        IDMVCode(error, capacity, "invalid_private_paths"); return nil;
    }
    NSString *directory = [partial.stringByDeletingLastPathComponent stringByResolvingSymlinksInPath];
    if (![directory isEqualToString:[final.stringByDeletingLastPathComponent stringByResolvingSymlinksInPath]]
            || stat(directory.fileSystemRepresentation, &_directoryIdentity) != 0
            || !S_ISDIR(_directoryIdentity.st_mode) || _directoryIdentity.st_uid != getuid()
            || (_directoryIdentity.st_mode & (S_IWGRP | S_IWOTH))) {
        IDMVCode(error, capacity, "unsafe_output_directory"); return nil;
    }
    _partialPath = [directory stringByAppendingPathComponent:partial.lastPathComponent];
    _finalPath = [directory stringByAppendingPathComponent:final.lastPathComponent];
    if ([_partialPath isEqualToString:_finalPath]) {
        IDMVCode(error, capacity, "invalid_private_paths"); return nil;
    }
    struct stat existing;
    if (lstat(_partialPath.fileSystemRepresentation, &existing) == 0 || errno != ENOENT
            || lstat(_finalPath.fileSystemRepresentation, &existing) == 0 || errno != ENOENT) {
        IDMVCode(error, capacity, "output_exists"); return nil;
    }
    _pcmPath = [pcm copy];
    _pcmFD = open(pcm.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (_pcmFD < 0 || fstat(_pcmFD, &_pcmIdentity) != 0 || !S_ISREG(_pcmIdentity.st_mode)
            || _pcmIdentity.st_nlink != 1 || (uint64_t)_pcmIdentity.st_size != pcmBytes) {
        IDMVCode(error, capacity, "invalid_pcm_file"); return nil;
    }
    _config = *config;
    _config.pcm_f32_path = _config.partial_path = _config.final_path = NULL;
    _lock = [[NSLock alloc] init];
    _frames = [[NSMutableArray alloc] initWithCapacity:IDMVMaximumPendingFrames];
    _queue = dispatch_queue_create("local.idoly.offline-mp4", DISPATCH_QUEUE_SERIAL);
    _status.struct_size = sizeof(_status); _status.abi_version = 1; _status.phase = IDMP4_STARTING;
    for (unsigned index = 0; index < 256; ++index) _transfer[index] = IDMVsRGBTo709((uint8_t)index);
    __weak IDMVEncoder *weakSelf = self;
    dispatch_async(_queue, ^{ @autoreleasepool { [weakSelf startWorker]; } });
    IDMVCode(error, capacity, "none");
    return self;
}

- (void)dealloc {
    if (_pcmFD >= 0) close(_pcmFD);
    if (_audioFormat) CFRelease(_audioFormat);
}

- (BOOL)cancellationRequested {
    [_lock lock]; BOOL requested = _cancelRequested; [_lock unlock]; return requested;
}

- (void)rememberPartial {
    if (_partialOwned) return;
    struct stat current;
    if (lstat(_partialPath.fileSystemRepresentation, &current) == 0
            && S_ISREG(current.st_mode) && current.st_nlink == 1 && current.st_uid == getuid()) {
        _partialIdentity = current; _partialOwned = YES;
    }
}

- (void)stopWithPhase:(uint32_t)phase code:(const char *)code {
    if (_workerStopped) return;
    if (_timer) { dispatch_source_cancel(_timer); _timer = nil; }
    if (phase != IDMP4_COMPLETED) {
        if (_writer.status == AVAssetWriterStatusWriting || _writer.status == AVAssetWriterStatusUnknown)
            [_writer cancelWriting];
        struct stat current;
        if (_partialOwned && lstat(_partialPath.fileSystemRepresentation, &current) == 0
                && IDMVSameFile(&_partialIdentity, &current)) unlink(_partialPath.fileSystemRepresentation);
    }
    if (_pcmFD >= 0) { close(_pcmFD); _pcmFD = -1; }
    [_lock lock];
    [_frames removeAllObjects]; _status.queued_frames = 0;
    _status.phase = phase; IDMVCode(_status.error_code, sizeof(_status.error_code), code);
    _workerStopped = YES;
    [_lock unlock];
}

- (void)startWorker {
    if ([self cancellationRequested]) { [self stopWithPhase:IDMP4_CANCELLED code:"cancelled"]; return; }
    AVVideoCodecType codec = _config.video_codec == IDMP4_H264 ? AVVideoCodecTypeH264 : AVVideoCodecTypeHEVC;
    NSDictionary *compression = @{
        AVVideoAverageBitRateKey:@(_config.video_bitrate),
        AVVideoExpectedSourceFrameRateKey:@((double)_config.fps_num / _config.fps_den),
        AVVideoMaxKeyFrameIntervalKey:@(((_config.fps_num + _config.fps_den - 1) / _config.fps_den) * 2),
        AVVideoAllowFrameReorderingKey:@NO,
        AVVideoProfileLevelKey:(_config.video_codec == IDMP4_H264
            ? AVVideoProfileLevelH264HighAutoLevel : (__bridge NSString *)kVTProfileLevel_HEVC_Main_AutoLevel)
    };
    NSDictionary *videoSettings = @{ AVVideoCodecKey:codec, AVVideoWidthKey:@(_config.width),
        AVVideoHeightKey:@(_config.height), AVVideoCompressionPropertiesKey:compression,
        AVVideoColorPropertiesKey:@{ AVVideoColorPrimariesKey:AVVideoColorPrimaries_ITU_R_709_2,
            AVVideoTransferFunctionKey:AVVideoTransferFunction_ITU_R_709_2,
            AVVideoYCbCrMatrixKey:AVVideoYCbCrMatrix_ITU_R_709_2 } };
    NSDictionary *audioSettings = @{ AVFormatIDKey:@(kAudioFormatMPEG4AAC),
        AVSampleRateKey:@(_config.audio_sample_rate), AVNumberOfChannelsKey:@(_config.audio_channels),
        AVEncoderBitRateKey:@(_config.audio_bitrate) };
    NSError *error = nil;
    _writer = [[AVAssetWriter alloc] initWithURL:[NSURL fileURLWithPath:_partialPath]
                                      fileType:AVFileTypeMPEG4 error:&error];
    if (!_writer) { [self stopWithPhase:IDMP4_FAILED code:"writer_creation_failed"]; return; }
    int32_t movieTimescale = 0;
    if (!IDMVCommonTimeScale(_config.fps_num, _config.audio_sample_rate, &movieTimescale)) {
        [self stopWithPhase:IDMP4_FAILED code:"movie_timescale_unsupported"]; return;
    }
    _writer.movieTimeScale = movieTimescale;
    if (![_writer canApplyOutputSettings:videoSettings forMediaType:AVMediaTypeVideo]
            || ![_writer canApplyOutputSettings:audioSettings forMediaType:AVMediaTypeAudio]) {
        [self stopWithPhase:IDMP4_FAILED code:"codec_configuration_unsupported"]; return;
    }
    _video = [AVAssetWriterInput assetWriterInputWithMediaType:AVMediaTypeVideo outputSettings:videoSettings];
    AudioStreamBasicDescription asbd = {0};
    asbd.mSampleRate = _config.audio_sample_rate; asbd.mFormatID = kAudioFormatLinearPCM;
    asbd.mFormatFlags = kAudioFormatFlagsNativeFloatPacked;
    asbd.mBytesPerPacket = asbd.mBytesPerFrame = _config.audio_channels * sizeof(float);
    asbd.mFramesPerPacket = 1; asbd.mChannelsPerFrame = _config.audio_channels; asbd.mBitsPerChannel = 32;
    if (CMAudioFormatDescriptionCreate(kCFAllocatorDefault, &asbd, 0, NULL, 0, NULL, NULL,
                                     &_audioFormat) != noErr) {
        [self stopWithPhase:IDMP4_FAILED code:"pcm_format_failed"]; return;
    }
    _audio = [AVAssetWriterInput assetWriterInputWithMediaType:AVMediaTypeAudio
                                             outputSettings:audioSettings sourceFormatHint:_audioFormat];
    _video.expectsMediaDataInRealTime = NO; _audio.expectsMediaDataInRealTime = NO;
    _video.mediaTimeScale = (int32_t)_config.fps_num;
    _video.preferredMediaChunkDuration = _audio.preferredMediaChunkDuration = CMTimeMake(1, 10);
    _adaptor = [AVAssetWriterInputPixelBufferAdaptor assetWriterInputPixelBufferAdaptorWithAssetWriterInput:_video
        sourcePixelBufferAttributes:@{ (id)kCVPixelBufferPixelFormatTypeKey:@(kCVPixelFormatType_32BGRA),
            (id)kCVPixelBufferWidthKey:@(_config.width), (id)kCVPixelBufferHeightKey:@(_config.height),
            (id)kCVPixelBufferIOSurfacePropertiesKey:@{} }];
    if (![_writer canAddInput:_video] || ![_writer canAddInput:_audio]) {
        [self stopWithPhase:IDMP4_FAILED code:"writer_inputs_unsupported"]; return;
    }
    [_writer addInput:_video]; [_writer addInput:_audio];
    _writer.shouldOptimizeForNetworkUse = NO;
    if (![_writer startWriting]) { [self rememberPartial];
        [self stopWithPhase:IDMP4_FAILED code:"writer_start_failed"]; return; }
    [self rememberPartial];
    [_writer startSessionAtSourceTime:kCMTimeZero];
    [_lock lock]; _status.phase = IDMP4_ENCODING; [_lock unlock];
    _timer = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0, _queue);
    __weak IDMVEncoder *weakSelf = self;
    dispatch_source_set_event_handler(_timer, ^{ @autoreleasepool { [weakSelf pump]; } });
    dispatch_source_set_timer(_timer, DISPATCH_TIME_NOW, 5 * NSEC_PER_MSEC, NSEC_PER_MSEC);
    dispatch_resume(_timer);
}

- (BOOL)appendNextVideo {
    [_lock lock]; IDMVQueuedFrame *frame = _frames.firstObject; [_lock unlock];
    if (!frame || !_video.readyForMoreMediaData) return YES;
    if (!_adaptor.pixelBufferPool) {
        [self stopWithPhase:IDMP4_FAILED code:"pixel_buffer_pool_unavailable"]; return NO;
    }
    CVPixelBufferRef pixel = NULL;
    NSDictionary *allocation = @{ (id)kCVPixelBufferPoolAllocationThresholdKey:@(IDMVMaximumPendingFrames) };
    CVReturn result = CVPixelBufferPoolCreatePixelBufferWithAuxAttributes(kCFAllocatorDefault,
        _adaptor.pixelBufferPool, (__bridge CFDictionaryRef)allocation, &pixel);
    if (result == kCVReturnWouldExceedAllocationThreshold) return YES;
    if (result != kCVReturnSuccess || !pixel) {
        [self stopWithPhase:IDMP4_FAILED code:"pixel_buffer_allocation_failed"]; return NO;
    }
    if (CVPixelBufferLockBaseAddress(pixel, 0) != kCVReturnSuccess) {
        CFRelease(pixel); [self stopWithPhase:IDMP4_FAILED code:"pixel_buffer_lock_failed"]; return NO;
    }
    uint8_t *destination = (uint8_t *)CVPixelBufferGetBaseAddress(pixel);
    const size_t stride = CVPixelBufferGetBytesPerRow(pixel);
    if (!destination || stride < (size_t)_config.width * 4) {
        CVPixelBufferUnlockBaseAddress(pixel, 0); CFRelease(pixel);
        [self stopWithPhase:IDMP4_FAILED code:"pixel_buffer_layout_invalid"]; return NO;
    }
    const uint8_t *source = (const uint8_t *)frame.rgba.bytes;
    for (uint32_t y = 0; y < _config.height; ++y) {
        uint8_t *row = destination + y * stride;
        const uint8_t *input = source + (size_t)y * _config.width * 4;
        for (uint32_t x = 0; x < _config.width; ++x) {
            row[x*4] = _transfer[input[x*4+2]];
            row[x*4+1] = _transfer[input[x*4+1]];
            row[x*4+2] = _transfer[input[x*4]];
            row[x*4+3] = 255;
        }
    }
    CVBufferSetAttachment(pixel, kCVImageBufferColorPrimariesKey,
        kCVImageBufferColorPrimaries_ITU_R_709_2, kCVAttachmentMode_ShouldPropagate);
    CVBufferSetAttachment(pixel, kCVImageBufferTransferFunctionKey,
        kCVImageBufferTransferFunction_ITU_R_709_2, kCVAttachmentMode_ShouldPropagate);
    CVBufferSetAttachment(pixel, kCVImageBufferYCbCrMatrixKey,
        kCVImageBufferYCbCrMatrix_ITU_R_709_2, kCVAttachmentMode_ShouldPropagate);
    CVPixelBufferUnlockBaseAddress(pixel, 0);
    CMTime time = CMTimeMake((int64_t)(frame.index * _config.fps_den), (int32_t)_config.fps_num);
    BOOL accepted = [_adaptor appendPixelBuffer:pixel withPresentationTime:time];
    CFRelease(pixel);
    if (!accepted) {
        [self stopWithPhase:IDMP4_FAILED code:"video_append_failed"]; return NO;
    }
    [_lock lock];
    [_frames removeObjectAtIndex:0]; _status.queued_frames = (uint32_t)_frames.count;
    ++_status.encoded_frames;
    [_lock unlock];
    return YES;
}

- (BOOL)appendNextAudio {
    [_lock lock]; uint64_t offset = _status.audio_frames; [_lock unlock];
    if (offset == _config.audio_sample_frames || !_audio.readyForMoreMediaData) return YES;
    struct stat identity;
    if (fstat(_pcmFD, &identity) != 0 || !IDMVSameFile(&_pcmIdentity, &identity)
            || identity.st_size != _pcmIdentity.st_size
            || identity.st_mtimespec.tv_sec != _pcmIdentity.st_mtimespec.tv_sec
            || identity.st_mtimespec.tv_nsec != _pcmIdentity.st_mtimespec.tv_nsec) {
        [self stopWithPhase:IDMP4_FAILED code:"pcm_changed"]; return NO;
    }
    uint64_t count = _config.audio_sample_frames - offset;
    if (count > IDMVMaximumPCMChunkFrames) count = IDMVMaximumPCMChunkFrames;
    const size_t size = (size_t)count * _config.audio_channels * sizeof(float);
    NSMutableData *pcm = [NSMutableData dataWithLength:size];
    size_t done = 0;
    while (done < size) {
        ssize_t readBytes = pread(_pcmFD, (uint8_t *)pcm.mutableBytes + done, size - done,
            (off_t)(offset * _config.audio_channels * sizeof(float) + done));
        if (readBytes < 0 && errno == EINTR) continue;
        if (readBytes <= 0) { [self stopWithPhase:IDMP4_FAILED code:"pcm_read_failed"]; return NO; }
        done += (size_t)readBytes;
    }
    const float *values = (const float *)pcm.bytes;
    for (size_t index = 0; index < size / sizeof(float); ++index) {
        if (!isfinite(values[index])) { [self stopWithPhase:IDMP4_FAILED code:"pcm_nonfinite"]; return NO; }
    }
    CMBlockBufferRef block = NULL; CMSampleBufferRef sample = NULL;
    OSStatus result = CMBlockBufferCreateWithMemoryBlock(kCFAllocatorDefault, NULL, size,
        kCFAllocatorDefault, NULL, 0, size, 0, &block);
    if (result == noErr) result = CMBlockBufferReplaceDataBytes(pcm.bytes, block, 0, size);
    CMSampleTimingInfo timing = {CMTimeMake(1, (int32_t)_config.audio_sample_rate),
        CMTimeMake((int64_t)offset, (int32_t)_config.audio_sample_rate), kCMTimeInvalid};
    size_t sampleSize = _config.audio_channels * sizeof(float);
    if (result == noErr) result = CMSampleBufferCreateReady(kCFAllocatorDefault, block, _audioFormat,
        (CMItemCount)count, 1, &timing, 1, &sampleSize, &sample);
    BOOL accepted = result == noErr && [_audio appendSampleBuffer:sample];
    if (sample) CFRelease(sample);
    if (block) CFRelease(block);
    if (!accepted) { [self stopWithPhase:IDMP4_FAILED code:"audio_append_failed"]; return NO; }
    [_lock lock]; _status.audio_frames += count; [_lock unlock];
    return YES;
}

- (void)finishWriter {
    _finishStarted = YES;
    [_lock lock]; _status.phase = IDMP4_FINISHING; [_lock unlock];
    [_writer endSessionAtSourceTime:CMTimeMake((int64_t)(_config.video_frame_count * _config.fps_den),
                                             (int32_t)_config.fps_num)];
    __weak IDMVEncoder *weakSelf = self;
    [_writer finishWritingWithCompletionHandler:^{
        IDMVEncoder *owner = weakSelf;
        if (!owner) return;
        dispatch_async(owner->_queue, ^{ @autoreleasepool { [owner publishCompletedWriter]; } });
    }];
}

- (void)publishCompletedWriter {
    if ([self cancellationRequested]) { [self stopWithPhase:IDMP4_CANCELLED code:"cancelled"]; return; }
    if (_writer.status != AVAssetWriterStatusCompleted) {
        [self stopWithPhase:IDMP4_FAILED code:"writer_finish_failed"]; return;
    }
    [self rememberPartial];
    struct stat current, directory;
    if (!_partialOwned || lstat(_partialPath.fileSystemRepresentation, &current) != 0
            || !IDMVSameFile(&_partialIdentity, &current) || current.st_size <= 0
            || stat(_partialPath.stringByDeletingLastPathComponent.fileSystemRepresentation, &directory) != 0
            || directory.st_dev != _directoryIdentity.st_dev || directory.st_ino != _directoryIdentity.st_ino) {
        [self stopWithPhase:IDMP4_FAILED code:"output_changed"]; return;
    }
    AVURLAsset *asset = [AVURLAsset URLAssetWithURL:[NSURL fileURLWithPath:_partialPath]
                                        options:@{AVURLAssetPreferPreciseDurationAndTimingKey:@YES}];
    NSArray<AVAssetTrack *> *videoTracks = [asset tracksWithMediaType:AVMediaTypeVideo];
    NSArray<AVAssetTrack *> *audioTracks = [asset tracksWithMediaType:AVMediaTypeAudio];
    CMTime expectedVideo = CMTimeMake((int64_t)(_config.video_frame_count * _config.fps_den),
                                      (int32_t)_config.fps_num);
    CMTime expectedAudio = CMTimeMake((int64_t)_config.audio_sample_frames, (int32_t)_config.audio_sample_rate);
#if IDMV_ENCODER_DIAGNOSTICS
    fprintf(stderr,"IDMV timeline video_tracks=%lu audio_tracks=%lu v_start=%lld/%d v_duration=%lld/%d v_expected=%lld/%d a_start=%lld/%d a_duration=%lld/%d a_expected=%lld/%d\n",
        (unsigned long)videoTracks.count,(unsigned long)audioTracks.count,
        (long long)videoTracks.firstObject.timeRange.start.value,videoTracks.firstObject.timeRange.start.timescale,
        (long long)videoTracks.firstObject.timeRange.duration.value,videoTracks.firstObject.timeRange.duration.timescale,
        (long long)expectedVideo.value,expectedVideo.timescale,
        (long long)audioTracks.firstObject.timeRange.start.value,audioTracks.firstObject.timeRange.start.timescale,
        (long long)audioTracks.firstObject.timeRange.duration.value,audioTracks.firstObject.timeRange.duration.timescale,
        (long long)expectedAudio.value,expectedAudio.timescale);
#endif
    if (videoTracks.count != 1 || audioTracks.count != 1
            || CMTimeCompare(videoTracks.firstObject.timeRange.start, kCMTimeZero) != 0
            || CMTimeCompare(videoTracks.firstObject.timeRange.duration, expectedVideo) != 0
            || CMTimeCompare(audioTracks.firstObject.timeRange.start, kCMTimeZero) != 0
            || fabs(CMTimeGetSeconds(CMTimeSubtract(audioTracks.firstObject.timeRange.duration, expectedAudio)))
                > 1.0 / _config.audio_sample_rate) {
#if IDMV_ENCODER_DIAGNOSTICS
        // Synthetic proof builds only: retain an explicitly rejected artifact
        // for independent timestamp/packet inspection. Never enabled in the IPA.
        NSString *rejected = [_partialPath stringByAppendingString:@".rejected.mp4"];
        [NSFileManager.defaultManager copyItemAtPath:_partialPath toPath:rejected error:NULL];
#endif
        [self stopWithPhase:IDMP4_FAILED code:"encoded_timeline_mismatch"]; return;
    }
    // Cancellation and publication have one linearization point. Cancellation
    // that wins this lock leaves no final file; a published job is already done.
    [_lock lock];
    BOOL cancelled = _cancelRequested;
    int published = cancelled ? -1 : renamex_np(_partialPath.fileSystemRepresentation,
        _finalPath.fileSystemRepresentation, RENAME_EXCL);
    if (published == 0) {
        _status.bytes_written = (uint64_t)current.st_size; _status.phase = IDMP4_COMPLETED;
    }
    [_lock unlock];
    if (cancelled) { [self stopWithPhase:IDMP4_CANCELLED code:"cancelled"]; return; }
    if (published != 0) {
        [self stopWithPhase:IDMP4_FAILED code:"exclusive_publish_failed"]; return;
    }
    _partialOwned = NO;
    [self stopWithPhase:IDMP4_COMPLETED code:"none"];
}

- (void)pump {
    if (_workerStopped) return;
    if ([self cancellationRequested]) {
        if (_finishStarted) {
            [_lock lock]; _status.phase = IDMP4_CANCELLING; [_lock unlock];
            if (_writer.status == AVAssetWriterStatusWriting) [_writer cancelWriting];
            return; // The pending finish callback owns completion and worker shutdown.
        }
        [self stopWithPhase:IDMP4_CANCELLED code:"cancelled"]; return;
    }
    if (_finishStarted) return;
    if (_writer.status != AVAssetWriterStatusWriting) {
        [self stopWithPhase:IDMP4_FAILED code:"writer_failed"]; return;
    }
    // Independent bounded pumps: do not cap audio to the submitted video lead.
    // Such a cap can deadlock a muxer that needs another audio packet first.
    if (![self appendNextAudio] || ![self appendNextVideo]) return;
    [_lock lock];
    BOOL videoDone = _status.encoded_frames == _config.video_frame_count;
    BOOL audioDone = _status.audio_frames == _config.audio_sample_frames;
    BOOL finishRequested = _finishRequested;
    [_lock unlock];
    if (videoDone && !_videoEnded) { [_video markAsFinished]; _videoEnded = YES; }
    if (audioDone && !_audioEnded) { [_audio markAsFinished]; _audioEnded = YES; }
    if (videoDone && audioDone && finishRequested) [self finishWriter];
}

- (int)append:(const uint8_t *)rgba rowBytes:(size_t)rowBytes index:(uint64_t)index {
    if (!rgba || rowBytes < (size_t)_config.width * 4 || rowBytes > SIZE_MAX / _config.height)
        return IDMP4_ERROR;
    [_lock lock];
    if (_cancelRequested || _finishRequested || IDMVTerminal(_status.phase)
            || !IDMVContiguousIndex(index, _status.submitted_frames, _config.video_frame_count)) {
        [_lock unlock]; return IDMP4_ERROR;
    }
    if (_status.phase == IDMP4_STARTING || _frames.count == IDMVMaximumPendingFrames) {
        [_lock unlock]; return IDMP4_RETRY;
    }
    uint8_t *copy = (uint8_t *)malloc(_frameBytes);
    if (!copy) { [_lock unlock]; return IDMP4_ERROR; }
    for (uint32_t row = 0; row < _config.height; ++row)
        memcpy(copy + (size_t)row * _config.width * 4, rgba + row * rowBytes, (size_t)_config.width * 4);
    IDMVQueuedFrame *frame = [[IDMVQueuedFrame alloc] init];
    frame.rgba = [NSData dataWithBytesNoCopy:copy length:_frameBytes freeWhenDone:YES]; frame.index = index;
    [_frames addObject:frame]; ++_status.submitted_frames; _status.queued_frames = (uint32_t)_frames.count;
    [_lock unlock];
    return IDMP4_ACCEPTED;
}

- (int)poll:(IDMP4EncoderStatus *)status {
    if (!status || status->struct_size != sizeof(*status) || status->abi_version != 1) return IDMP4_ERROR;
    [_lock lock]; *status = _status; [_lock unlock]; return IDMP4_ACCEPTED;
}

- (int)finish {
    [_lock lock];
    if (_cancelRequested || _status.phase == IDMP4_FAILED || _status.phase == IDMP4_CANCELLED) {
        [_lock unlock]; return IDMP4_ERROR;
    }
    if (_status.submitted_frames != _config.video_frame_count) { [_lock unlock]; return IDMP4_RETRY; }
    _finishRequested = YES; [_lock unlock]; return IDMP4_ACCEPTED;
}

- (void)cancel {
    [_lock lock];
    if (!IDMVTerminal(_status.phase)) { _cancelRequested = YES; _status.phase = IDMP4_CANCELLING; }
    [_lock unlock];
}

- (BOOL)canDestroy {
    [_lock lock]; BOOL ready = _workerStopped && IDMVTerminal(_status.phase); [_lock unlock]; return ready;
}
@end

extern "C" {
__attribute__((visibility("default")))
IDMP4EncoderHandle IDMP4EncoderCreate(const IDMP4EncoderConfig *config, char *error, size_t capacity) {
    @autoreleasepool {
        IDMVEncoder *owner = [[IDMVEncoder alloc] initWithConfig:config error:error capacity:capacity];
        return owner ? (__bridge_retained void *)owner : NULL;
    }
}
__attribute__((visibility("default")))
int IDMP4EncoderAppendFrame(IDMP4EncoderHandle handle, const uint8_t *rgba, size_t rowBytes, uint64_t index) {
    if (!handle) return IDMP4_ERROR;
    @autoreleasepool { return [(__bridge IDMVEncoder *)handle append:rgba rowBytes:rowBytes index:index]; }
}
__attribute__((visibility("default")))
int IDMP4EncoderPoll(IDMP4EncoderHandle handle, IDMP4EncoderStatus *status) {
    return handle ? [(__bridge IDMVEncoder *)handle poll:status] : IDMP4_ERROR;
}
__attribute__((visibility("default")))
int IDMP4EncoderFinish(IDMP4EncoderHandle handle) {
    return handle ? [(__bridge IDMVEncoder *)handle finish] : IDMP4_ERROR;
}
__attribute__((visibility("default")))
void IDMP4EncoderCancel(IDMP4EncoderHandle handle) {
    if (handle) [(__bridge IDMVEncoder *)handle cancel];
}
__attribute__((visibility("default")))
int IDMP4EncoderDestroy(IDMP4EncoderHandle handle) {
    if (!handle) return IDMP4_ACCEPTED;
    if (![(__bridge IDMVEncoder *)handle canDestroy]) return IDMP4_RETRY;
    (void)CFBridgingRelease(handle);
    return IDMP4_ACCEPTED;
}
}
