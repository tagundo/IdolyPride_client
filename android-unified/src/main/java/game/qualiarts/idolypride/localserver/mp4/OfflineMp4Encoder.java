package game.qualiarts.idolypride.localserver.mp4;

import android.graphics.ImageFormat;
import android.media.Image;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaCodecList;
import android.media.MediaFormat;
import android.media.MediaMuxer;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;

/**
 * Bounded offline encoder. The game owns simulation/rendering; this worker only consumes copied
 * frames and an immutable, complete float32-LE soundtrack. No screen or microphone capture occurs.
 */
public final class OfflineMp4Encoder {
    public static final int ACCEPT = 0, RETRY = 1, ERROR = -1;
    private static final int SLOTS = 3, PCM_CHUNK = 4096, PENDING_LIMIT = 8 * 1024 * 1024;
    private static final long STALL_NS = 120_000_000_000L;

    public static final class Config {
        public final int width, height, fpsNumerator, fpsDenominator, bitrate, sampleRate, channels, audioBitrate, codec;
        public final long audioFrames, videoFrames;
        public final File pcm, partial, destination;

        public Config(int width, int height, int fpsNumerator, int fpsDenominator, int bitrate,
                      int sampleRate, int channels, long audioFrames, long videoFrames,
                      String pcm, String partial, String destination, int codec) throws IOException {
            this(width, height, fpsNumerator, fpsDenominator, bitrate, sampleRate, channels, 192_000,
                    audioFrames, videoFrames, pcm, partial, destination, codec);
        }
        public Config(int width, int height, int fpsNumerator, int fpsDenominator, int bitrate,
                      int sampleRate, int channels, int audioBitrate, long audioFrames, long videoFrames,
                      String pcm, String partial, String destination, int codec) throws IOException {
            OfflineMp4Math.pixels(width, height);
            if (fpsNumerator < 1 || fpsNumerator > 1_000_000 || fpsDenominator < 1 || fpsDenominator > 10_000
                    || (long) fpsNumerator < fpsDenominator || (long) fpsNumerator > 240L * fpsDenominator
                    || bitrate < 64_000 || bitrate > 240_000_000 || sampleRate < 8000 || sampleRate > 65535
                    || channels < 1 || channels > 2 || audioBitrate < 16_000 || audioBitrate > 512_000
                    || audioFrames < 1 || videoFrames < 1 || (codec != 1 && codec != 2))
                throw new IllegalArgumentException("Invalid offline export configuration");
            // This is a single complete clip, with its last video frame ending within one frame
            // of the exact soundtrack end. Do not silently stretch, trim or pad the source audio.
            if (videoFrames != OfflineMp4Math.videoFramesForAudio(audioFrames, fpsNumerator, fpsDenominator, sampleRate)
                    || OfflineMp4Math.timestampUs(videoFrames, fpsNumerator, fpsDenominator) > 86_400_000_000L)
                throw new IllegalArgumentException("Frame count must cover the exact soundtrack, within one frame");
            this.width = width; this.height = height; this.fpsNumerator = fpsNumerator;
            this.fpsDenominator = fpsDenominator; this.bitrate = bitrate; this.sampleRate = sampleRate;
            this.channels = channels; this.audioBitrate = audioBitrate;
            this.audioFrames = audioFrames; this.videoFrames = videoFrames; this.codec = codec;
            this.pcm = new File(pcm).getCanonicalFile();
            this.partial = new File(partial).getCanonicalFile();
            this.destination = new File(destination).getCanonicalFile();
            if (this.pcm.equals(this.partial) || this.pcm.equals(this.destination) || this.partial.equals(this.destination)
                    || !this.partial.getParentFile().equals(this.destination.getParentFile())
                    || !this.partial.getParentFile().isDirectory() || this.partial.exists() || this.destination.exists())
                throw new IOException("Export requires two new private paths in the same directory");
            long expected = Math.multiplyExact(Math.multiplyExact(audioFrames, channels), 4L);
            if (!this.pcm.isFile() || this.pcm.length() != expected)
                throw new IOException("Soundtrack is incomplete or has an unexpected float32 size");
        }
        String mime() { return codec == 1 ? "video/avc" : "video/hevc"; }
    }

    private static final class Frame {
        final long index;
        final byte[] rgba;
        Frame(long index, byte[] rgba) { this.index = index; this.rgba = rgba; }
    }
    private static final class Encoded {
        final boolean audio;
        final byte[] bytes;
        final MediaCodec.BufferInfo info;
        Encoded(boolean audio, byte[] bytes, MediaCodec.BufferInfo info) {
            this.audio = audio; this.bytes = bytes; this.info = info;
        }
    }

    private final Object stateLock = new Object();
    private final Config config;
    private final ArrayBlockingQueue<Frame> frames = new ArrayBlockingQueue<>(SLOTS);
    private final ArrayBlockingQueue<byte[]> free = new ArrayBlockingQueue<>(SLOTS);
    private final ArrayDeque<Encoded> pending = new ArrayDeque<>();
    private volatile boolean cancelled, done;
    private volatile String phase = "initializing", failure, completedPath, videoCodecName, audioCodecName;
    private volatile String errorCode = "";
    private volatile long accepted, encodedVideo, audioInput, encodedAudioPackets;
    private volatile int priming = -1;
    private boolean finishRequested;
    private MediaCodec video, audio;
    private MediaMuxer muxer;
    private int videoTrack = -1, audioTrack = -1, pendingBytes;
    private boolean muxing, videoEnd, audioEnd;
    private long firstAudioPts = Long.MIN_VALUE, previousVideoPts = -1, previousAudioPts = -1;
    private byte[] planar;

    public static OfflineMp4Encoder create(int width, int height, int fpsNumerator, int fpsDenominator,
            int bitrate, int sampleRate, int channels, long audioFrames, long videoFrames,
            String pcm, String partial, String destination, int codec) throws IOException {
        return new OfflineMp4Encoder(new Config(width, height, fpsNumerator, fpsDenominator, bitrate,
                sampleRate, channels, audioFrames, videoFrames, pcm, partial, destination, codec));
    }

    public static OfflineMp4Encoder create(int width, int height, int fpsNumerator, int fpsDenominator,
            int bitrate, int sampleRate, int channels, int audioBitrate, long audioFrames, long videoFrames,
            String pcm, String partial, String destination, int codec) throws IOException {
        return new OfflineMp4Encoder(new Config(width, height, fpsNumerator, fpsDenominator, bitrate,
                sampleRate, channels, audioBitrate, audioFrames, videoFrames, pcm, partial, destination, codec));
    }

    /** Invoke from Java's app class loader before the native game-thread producer is started. */
    public static boolean installNativeBridge() {
        try {
            System.loadLibrary("idoly_presentation");
            return registerEncoderClass(OfflineMp4Encoder.class);
        } catch (LinkageError | SecurityException unavailable) { return false; }
    }
    private static native boolean registerEncoderClass(Class<?> encoderClass);

    public OfflineMp4Encoder(Config config) throws IOException {
        this.config = config;
        if (!config.partial.createNewFile()) throw new IOException("Partial export path already exists");
        try {
            int pixels = OfflineMp4Math.pixels(config.width, config.height);
            for (int i = 0; i < SLOTS; i++) free.add(new byte[pixels * 4]);
            planar = new byte[pixels * 3 / 2];
            Thread worker = new Thread(this::encode, "IdolyOfflineMp4");
            worker.setDaemon(true); worker.start();
        } catch (RuntimeException | Error error) { config.partial.delete(); throw error; }
    }

    /** ACCEPT means every source byte has been copied; RETRY leaves the clock and data untouched. */
    public int appendFrame(ByteBuffer rgba, int rowBytes, long index) {
        synchronized (stateLock) {
            if (done || cancelled || finishRequested || failure != null) return ERROR;
            if (index != accepted || index >= config.videoFrames || rgba == null || !rgba.isDirect()
                    || rowBytes < config.width * 4
                    || (long) (config.height - 1) * rowBytes + (long) config.width * 4 > rgba.remaining())
                return failInput("Invalid or out-of-order RGBA frame");
            byte[] target = free.poll();
            if (target == null) return RETRY;
            ByteBuffer source = rgba.duplicate();
            int origin = source.position(), rowLength = config.width * 4;
            for (int y = 0; y < config.height; y++) {
                source.position(origin + y * rowBytes); source.get(target, y * rowLength, rowLength);
            }
            if (!frames.offer(new Frame(index, target))) { free.add(target); return RETRY; }
            accepted++;
            return ACCEPT;
        }
    }

    private int failInput(String message) { errorCode = "invalid_frame_contract"; failure = message; cancelled = true; return ERROR; }

    public int finish() {
        synchronized (stateLock) {
            if (finishRequested || completedPath != null) return ACCEPT;
            if (done || cancelled || failure != null) return ERROR;
            if (accepted != config.videoFrames) return failInput("Cannot finish before every video frame is accepted");
            finishRequested = true; return ACCEPT;
        }
    }

    public void cancel() { synchronized (stateLock) { if (!done && completedPath == null) cancelled = true; } }
    public boolean isTerminal() { return done; }
    public String completedPath() { return completedPath; }
    public String errorCode() { return errorCode; }
    /** Fields match IDMP4EncoderStatus; this call never waits for a codec or reads soundtrack data. */
    public long[] nativeStatus() {
        String current = phase;
        int value = current.equals("completed") ? 4 : current.equals("cancelled") ? 6
                : current.equals("failed") ? 7 : cancelled ? 5 : current.equals("finalizing") ? 3
                : current.equals("encoding") ? 2 : 1;
        return new long[] { value, frames.size(), accepted, encodedVideo, audioInput,
                completedPath == null ? config.partial.length() : config.destination.length(), done ? 1 : 0 };
    }
    public String statusJson() {
        try {
            JSONObject status = new JSONObject();
            status.put("phase", phase); status.put("terminal", done);
            status.put("accepted_frames", accepted); status.put("encoded_frames", encodedVideo);
            status.put("video_frames", config.videoFrames); status.put("audio_frames", audioInput);
            status.put("source_audio_frames", config.audioFrames); status.put("audio_packets", encodedAudioPackets);
            status.put("fps_numerator", config.fpsNumerator); status.put("fps_denominator", config.fpsDenominator);
            status.put("video_codec", videoCodecName == null ? JSONObject.NULL : videoCodecName);
            status.put("audio_codec", audioCodecName == null ? JSONObject.NULL : audioCodecName);
            status.put("aac_priming_samples", priming);
            status.put("error", failure == null ? JSONObject.NULL : failure);
            status.put("path", completedPath == null ? JSONObject.NULL : completedPath);
            return status.toString();
        } catch (Exception impossible) { return "{\"phase\":\"failed\",\"terminal\":true}"; }
    }

    private void encode() {
        boolean success = false, finalReservationOwned = false;
        try (FileInputStream pcm = new FileInputStream(config.pcm)) {
            video = openVideo();
            audioCodecName = chooseAudioEncoder();
            phase = "checking_audio";
            priming = AacPrimingProbe.measure(audioCodecName, config.sampleRate, config.channels, config.audioBitrate, () -> cancelled);
            check();
            audio = MediaCodec.createByCodecName(audioCodecName);
            audio.configure(AacPrimingProbe.inputFormat(config.sampleRate, config.channels, config.audioBitrate),
                    null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
            audio.start();
            muxer = new MediaMuxer(config.partial.getPath(), MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4);
            phase = "encoding";
            byte[] floats = new byte[PCM_CHUNK * config.channels * 4];
            byte[] pcm16 = new byte[PCM_CHUNK * config.channels * 2];
            for (;;) {
                check();
                Frame frame = frames.poll(10, TimeUnit.MILLISECONDS);
                if (frame != null) {
                    try {
                        OfflineMp4Math.rgbaToI420(frame.rgba, planar, config.width, config.height);
                        inputVideo(frame.index);
                    } finally { free.add(frame.rgba); }
                    long target = Math.min(config.audioFrames, OfflineMp4Math.audioBoundary(
                            frame.index + 1, config.fpsNumerator, config.fpsDenominator, config.sampleRate));
                    while (audioInput < target) {
                        int count = (int) Math.min(PCM_CHUNK, target - audioInput);
                        readPcm(pcm, floats, pcm16, count);
                        inputPcm(pcm16, count, audioInput);
                        audioInput += count;
                    }
                }
                drain(false); drain(true);
                synchronized (stateLock) { if (finishRequested && frames.isEmpty()) break; }
            }
            if (audioInput != config.audioFrames || pcm.read() != -1
                    || pcm.getChannel().size() != Math.multiplyExact(Math.multiplyExact(config.audioFrames, config.channels), 4L))
                throw new IOException("Soundtrack length changed during export");
            phase = "finalizing";
            inputEnd(false, config.videoFrames);
            // Supply bounded silent codec-flush input; it never changes the logical soundtrack.
            byte[] silence = new byte[PCM_CHUNK * config.channels * 2];
            long flushEnd = config.audioFrames + priming + 2048L;
            for (long position = config.audioFrames; position < flushEnd;) {
                int count = (int) Math.min(PCM_CHUNK, flushEnd - position);
                inputPcm(silence, count, position); position += count;
            }
            inputEnd(true, flushEnd);
            long progressAt = System.nanoTime();
            while (!videoEnd || !audioEnd) {
                check();
                if (drain(false) | drain(true)) progressAt = System.nanoTime();
                else waitForCodec(progressAt);
            }
            if (!muxing || !pending.isEmpty() || encodedVideo != config.videoFrames)
                throw new IOException("Encoded video or tracks are incomplete");
            // MediaMuxer otherwise estimates the last sample duration from the previous delta.
            // An empty EOS marker states both exact track boundaries without adding a frame.
            MediaCodec.BufferInfo end = new MediaCodec.BufferInfo();
            end.set(0, 0, OfflineMp4Math.timestampUs(config.videoFrames, config.fpsNumerator,
                    config.fpsDenominator), MediaCodec.BUFFER_FLAG_END_OF_STREAM);
            muxer.writeSampleData(videoTrack, ByteBuffer.allocate(0), end);
            end.set(0, 0, OfflineMp4Math.timestampUs(encodedAudioPackets * 1024, config.sampleRate, 1),
                    MediaCodec.BUFFER_FLAG_END_OF_STREAM);
            muxer.writeSampleData(audioTrack, ByteBuffer.allocate(0), end);
            muxer.stop(); muxing = false; muxer.release(); muxer = null;
            Mp4AudioTimeline.finalizeFile(config.partial, config.sampleRate, config.audioFrames, priming,
                    encodedAudioPackets, config.fpsNumerator, config.fpsDenominator, config.videoFrames);
            check();
            synchronized (stateLock) {
                check();
                if (config.destination.exists()) throw new IOException("Final export path was occupied");
                // Android SELinux may deny hardlinks even inside app-private files. Reserve a
                // new private name exclusively, then replace only our own empty reservation.
                // No user can save it until the complete rename and terminal status publication.
                Files.createFile(config.destination.toPath()); finalReservationOwned = true;
                Files.move(config.partial.toPath(), config.destination.toPath(),
                        StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
                finalReservationOwned = false;
                completedPath = config.destination.getPath(); phase = "completed"; success = true;
            }
        } catch (Throwable error) {
            if (failure == null && !cancelled) {
                errorCode = "platform_encoder_failure";
                String message = error.getClass().getSimpleName() + ": " + error.getMessage();
                failure = message.substring(0, Math.min(4096, message.length()));
            }
            phase = failure == null ? "cancelled" : "failed";
        } finally {
            AacPrimingProbe.close(video); AacPrimingProbe.close(audio);
            if (muxer != null) try { muxer.release(); } catch (RuntimeException ignored) {}
            synchronized (stateLock) {
                frames.clear(); free.clear(); pending.clear(); planar = null;
                if (!success) config.partial.delete();
                if (finalReservationOwned) config.destination.delete();
                done = true;
            }
        }
    }

    private void check() throws IOException {
        if (cancelled || Thread.currentThread().isInterrupted()) throw new IOException("Export cancelled");
    }
    private void waitForCodec(long lastProgress) throws IOException, InterruptedException {
        check();
        if (System.nanoTime() - lastProgress > STALL_NS) throw new IOException("Media codec stopped progressing");
        Thread.sleep(2);
    }

    private MediaCodec openVideo() throws IOException {
        MediaFormat format = MediaFormat.createVideoFormat(config.mime(), config.width, config.height);
        format.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible);
        format.setInteger(MediaFormat.KEY_BIT_RATE, config.bitrate);
        format.setFloat(MediaFormat.KEY_FRAME_RATE, (float) config.fpsNumerator / config.fpsDenominator);
        format.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 2);
        format.setInteger(MediaFormat.KEY_MAX_B_FRAMES, 0);
        format.setInteger(MediaFormat.KEY_COLOR_STANDARD, MediaFormat.COLOR_STANDARD_BT709);
        format.setInteger(MediaFormat.KEY_COLOR_RANGE, MediaFormat.COLOR_RANGE_LIMITED);
        format.setInteger(MediaFormat.KEY_COLOR_TRANSFER, MediaFormat.COLOR_TRANSFER_SDR_VIDEO);
        ArrayList<String> preferred = new ArrayList<>(), others = new ArrayList<>();
        for (MediaCodecInfo info : new MediaCodecList(MediaCodecList.REGULAR_CODECS).getCodecInfos()) {
            if (!info.isEncoder()) continue;
            try {
                MediaCodecInfo.CodecCapabilities caps = info.getCapabilitiesForType(config.mime());
                boolean flexible = false;
                for (int color : caps.colorFormats) if (color == MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible) flexible = true;
                if (!flexible) continue;
                if (caps.getVideoCapabilities().isSizeSupported(config.width, config.height)) preferred.add(info.getName());
                else others.add(info.getName());
            } catch (IllegalArgumentException ignored) {}
        }
        // Offline throughput is not real-time playback. Advertised fps is advisory; configure/start
        // and the verified output clock decide support, with no resolution, codec or fps fallback.
        preferred.addAll(others);
        StringBuilder errors = new StringBuilder();
        for (String name : preferred) {
            check(); MediaCodec candidate = null;
            try {
                candidate = MediaCodec.createByCodecName(name);
                candidate.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE); candidate.start();
                videoCodecName = name; return candidate;
            } catch (IOException | RuntimeException error) {
                AacPrimingProbe.close(candidate); errors.append(name).append(": ").append(error.getMessage()).append("; ");
            }
        }
        throw new IOException("No encoder accepted " + config.mime() + " " + config.width + "x" + config.height + ": " + errors);
    }

    private String chooseAudioEncoder() throws IOException {
        ArrayList<String> candidates = new ArrayList<>();
        for (MediaCodecInfo info : new MediaCodecList(MediaCodecList.REGULAR_CODECS).getCodecInfos()) {
            if (!info.isEncoder()) continue;
            try { info.getCapabilitiesForType("audio/mp4a-latm"); candidates.add(info.getName()); }
            catch (IllegalArgumentException ignored) {}
        }
        for (String preferred : new String[] {"c2.android.aac.encoder", "OMX.google.aac.encoder"})
            if (candidates.contains(preferred)) return preferred;
        if (candidates.isEmpty()) throw new IOException("No AAC encoder is available");
        return candidates.get(0);
    }

    private int inputSlot(MediaCodec codec) throws IOException, InterruptedException {
        long progressAt = System.nanoTime();
        for (;;) {
            check(); int index = codec.dequeueInputBuffer(0); if (index >= 0) return index;
            if (drain(false) | drain(true)) progressAt = System.nanoTime(); else waitForCodec(progressAt);
        }
    }
    private void inputVideo(long index) throws IOException, InterruptedException {
        int slot = inputSlot(video);
        Image image = video.getInputImage(slot);
        if (image == null || image.getFormat() != ImageFormat.YUV_420_888 || image.getPlanes().length != 3
                || image.getCropRect().left != 0 || image.getCropRect().top != 0
                || image.getCropRect().width() != config.width || image.getCropRect().height() != config.height)
            throw new IOException("Video encoder has no supported flexible YUV input image");
        int source = 0;
        for (int p = 0; p < 3; p++) {
            int width = p == 0 ? config.width : config.width / 2, height = p == 0 ? config.height : config.height / 2;
            Image.Plane plane = image.getPlanes()[p]; ByteBuffer target = plane.getBuffer().duplicate();
            int base = target.position(), row = plane.getRowStride(), pixel = plane.getPixelStride();
            if (row <= 0 || pixel <= 0 || (long) base + (long) (height - 1) * row + (long) (width - 1) * pixel >= target.limit())
                throw new IOException("Video encoder YUV plane strides are invalid");
            for (int y = 0; y < height; y++) for (int x = 0; x < width; x++)
                target.put(base + y * row + x * pixel, planar[source++]);
        }
        video.queueInputBuffer(slot, 0, planar.length,
                OfflineMp4Math.timestampUs(index, config.fpsNumerator, config.fpsDenominator), 0);
    }
    private void readPcm(FileInputStream input, byte[] floats, byte[] output, int count) throws IOException {
        int length = count * config.channels * 4, offset = 0;
        while (offset < length) {
            check(); int read = input.read(floats, offset, length - offset);
            if (read < 0) throw new IOException("Soundtrack ended early");
            if (read == 0) throw new IOException("Soundtrack made no read progress");
            offset += read;
        }
        ByteBuffer source = ByteBuffer.wrap(floats, 0, length).order(ByteOrder.LITTLE_ENDIAN);
        ByteBuffer target = ByteBuffer.wrap(output).order(ByteOrder.LITTLE_ENDIAN);
        while (source.hasRemaining()) target.putShort(OfflineMp4Math.pcm16(source.getFloat()));
    }
    private void inputPcm(byte[] data, int count, long firstSample) throws IOException, InterruptedException {
        int consumed = 0, stride = config.channels * 2, length = count * stride;
        while (consumed < length) {
            int slot = inputSlot(audio); ByteBuffer target = audio.getInputBuffer(slot);
            if (target == null) throw new IOException("AAC input buffer missing");
            target.clear(); int size = Math.min(length - consumed, target.remaining() / stride * stride);
            if (size == 0) throw new IOException("AAC input cannot hold one sample frame");
            target.put(data, consumed, size);
            audio.queueInputBuffer(slot, 0, size,
                    OfflineMp4Math.timestampUs(firstSample + consumed / stride, config.sampleRate, 1), 0);
            consumed += size; drain(false); drain(true);
        }
    }
    private void inputEnd(boolean isAudio, long index) throws IOException, InterruptedException {
        MediaCodec codec = isAudio ? audio : video; int slot = inputSlot(codec);
        long timestamp = isAudio ? OfflineMp4Math.timestampUs(index, config.sampleRate, 1)
                : OfflineMp4Math.timestampUs(index, config.fpsNumerator, config.fpsDenominator);
        codec.queueInputBuffer(slot, 0, 0, timestamp, MediaCodec.BUFFER_FLAG_END_OF_STREAM);
    }

    private boolean drain(boolean isAudio) throws IOException {
        MediaCodec codec = isAudio ? audio : video;
        if (codec == null || (isAudio ? audioEnd : videoEnd)) return false;
        boolean progress = false; MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
        for (;;) {
            check(); int slot = codec.dequeueOutputBuffer(info, 0);
            if (slot == MediaCodec.INFO_TRY_AGAIN_LATER) return progress;
            progress = true;
            if (slot == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                if (muxing || (isAudio ? audioTrack : videoTrack) >= 0) throw new IOException("Encoder repeated track format");
                MediaFormat format = codec.getOutputFormat();
                if (isAudio) validateAudioFormat(format);
                int track = muxer.addTrack(format);
                if (isAudio) audioTrack = track; else videoTrack = track;
                if (audioTrack >= 0 && videoTrack >= 0) {
                    muxer.start(); muxing = true;
                    while (!pending.isEmpty()) { Encoded sample = pending.removeFirst(); write(sample); pendingBytes -= sample.bytes.length; }
                }
                continue;
            }
            if (slot < 0) continue;
            try {
                if (info.size > 0 && (info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) == 0) {
                    long timestamp = info.presentationTimeUs;
                    if (isAudio) {
                        if (firstAudioPts == Long.MIN_VALUE) firstAudioPts = timestamp;
                        long expected = OfflineMp4Math.timestampUs(encodedAudioPackets * 1024, config.sampleRate, 1);
                        if (Math.abs((timestamp - firstAudioPts) - expected) > 4)
                            throw new IOException("AAC packet clock changed");
                        timestamp = expected; encodedAudioPackets++;
                    } else {
                        if (encodedVideo >= config.videoFrames || timestamp != OfflineMp4Math.timestampUs(
                                encodedVideo, config.fpsNumerator, config.fpsDenominator))
                            throw new IOException("Video encoder dropped, duplicated or reordered a frame");
                        encodedVideo++;
                    }
                    long previous = isAudio ? previousAudioPts : previousVideoPts;
                    if (timestamp < 0 || timestamp <= previous) throw new IOException("Encoder timestamps are not monotonic");
                    if (isAudio) previousAudioPts = timestamp; else previousVideoPts = timestamp;
                    ByteBuffer buffer = codec.getOutputBuffer(slot);
                    if (buffer == null || info.offset < 0 || info.size > buffer.capacity() - info.offset
                            || info.size > PENDING_LIMIT || (!muxing && info.size > PENDING_LIMIT - pendingBytes))
                        throw new IOException("Encoded buffer is invalid or exceeds the bounded interleave queue");
                    byte[] copy = new byte[info.size]; buffer.position(info.offset); buffer.limit(info.offset + info.size); buffer.get(copy);
                    MediaCodec.BufferInfo timing = new MediaCodec.BufferInfo();
                    timing.set(0, copy.length, timestamp, info.flags & ~MediaCodec.BUFFER_FLAG_END_OF_STREAM);
                    Encoded sample = new Encoded(isAudio, copy, timing);
                    if (muxing) write(sample); else { pending.addLast(sample); pendingBytes += copy.length; }
                }
                if ((info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0) {
                    if (isAudio) audioEnd = true; else videoEnd = true;
                    return true;
                }
            } finally { codec.releaseOutputBuffer(slot, false); }
        }
    }
    private void write(Encoded sample) throws IOException {
        check(); muxer.writeSampleData(sample.audio ? audioTrack : videoTrack, ByteBuffer.wrap(sample.bytes), sample.info);
    }
    private void validateAudioFormat(MediaFormat format) throws IOException {
        if (format.getInteger(MediaFormat.KEY_SAMPLE_RATE) != config.sampleRate
                || format.getInteger(MediaFormat.KEY_CHANNEL_COUNT) != config.channels)
            throw new IOException("AAC encoder changed soundtrack format");
        if (format.containsKey(MediaFormat.KEY_ENCODER_DELAY)
                && format.getInteger(MediaFormat.KEY_ENCODER_DELAY) != priming)
            throw new IOException("AAC encoder-reported delay differs from verified decoder timing");
        ByteBuffer csd = format.getByteBuffer("csd-0");
        if (csd == null || csd.remaining() < 2 || csd.remaining() > 64) throw new IOException("AAC codec configuration missing");
        byte[] bytes = new byte[csd.remaining()]; csd.duplicate().get(bytes);
        int[] position = {0}; int object = bits(bytes, position, 5), frequency = bits(bytes, position, 4);
        int[] rates = {96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350};
        int rate = frequency == 15 ? bits(bytes, position, 24) : frequency < rates.length ? rates[frequency] : 0;
        int channels = bits(bytes, position, 4), shortFrame = bits(bytes, position, 1);
        if (object != 2 || rate != config.sampleRate || channels != config.channels || shortFrame != 0)
            throw new IOException("Only 1024-sample AAC-LC matching the source PCM is supported");
    }
    private static int bits(byte[] bytes, int[] position, int count) throws IOException {
        if (position[0] > bytes.length * 8 - count) throw new IOException("Truncated AAC configuration");
        int result = 0;
        while (count-- > 0) { int bit = position[0]++; result = (result << 1) | ((bytes[bit / 8] >> (7 - bit % 8)) & 1); }
        return result;
    }
}
