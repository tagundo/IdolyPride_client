package game.qualiarts.idolypride.localserver.mp4;

import android.media.AudioFormat;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaFormat;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.ArrayList;
import java.util.function.BooleanSupplier;

/** Measures the selected device encoder/decoder pair instead of guessing AAC priming. */
final class AacPrimingProbe {
    static final int MAX_DELAY = 8192;
    private static final int FIRST = 4096, SECOND = 20480, INPUT_FRAMES = 40960;
    private static final long STALL_NS = 30_000_000_000L;
    private AacPrimingProbe() {}

    static MediaFormat inputFormat(int rate, int channels, int bitrate) {
        MediaFormat format = MediaFormat.createAudioFormat("audio/mp4a-latm", rate, channels);
        format.setInteger(MediaFormat.KEY_AAC_PROFILE, MediaCodecInfo.CodecProfileLevel.AACObjectLC);
        format.setInteger(MediaFormat.KEY_BIT_RATE, bitrate);
        format.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 4096 * channels * 2);
        return format;
    }

    private static final class Packet {
        final byte[] data;
        Packet(byte[] data) { this.data = data; }
    }

    static int measure(String encoderName, int rate, int channels, int bitrate,
                       BooleanSupplier cancelled) throws IOException, InterruptedException {
        MediaCodec encoder = null, decoder = null;
        ArrayList<Packet> packets = new ArrayList<>();
        MediaFormat encodedFormat = null;
        try {
            encoder = MediaCodec.createByCodecName(encoderName);
            encoder.configure(inputFormat(rate, channels, bitrate), null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
            encoder.start();
            int fed = 0, bytes = 0;
            boolean inputEnd = false, outputEnd = false;
            long progressAt = System.nanoTime();
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            while (!outputEnd) {
                check(cancelled, progressAt);
                boolean progress = false;
                if (!inputEnd) {
                    int slot = encoder.dequeueInputBuffer(0);
                    if (slot >= 0) {
                        ByteBuffer target = encoder.getInputBuffer(slot);
                        if (target == null) throw new IOException("AAC probe input buffer missing");
                        target.clear(); target.order(ByteOrder.LITTLE_ENDIAN);
                        int count = Math.min(INPUT_FRAMES - fed, target.remaining() / (channels * 2));
                        if (fed < INPUT_FRAMES && count == 0) throw new IOException("AAC probe input capacity");
                        for (int i = 0; i < count; i++) for (int c = 0; c < channels; c++)
                            target.putShort((short) (fed + i == FIRST ? 24000 : fed + i == SECOND ? -18000 : 0));
                        int flags = count == 0 ? MediaCodec.BUFFER_FLAG_END_OF_STREAM : 0;
                        encoder.queueInputBuffer(slot, 0, count * channels * 2,
                                OfflineMp4Math.timestampUs(fed, rate, 1), flags);
                        fed += count; inputEnd = flags != 0; progress = true;
                    }
                }
                int slot = encoder.dequeueOutputBuffer(info, 0);
                if (slot == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    if (encodedFormat != null) throw new IOException("AAC probe repeated format");
                    encodedFormat = encoder.getOutputFormat(); progress = true;
                } else if (slot >= 0) {
                    try {
                        if (info.size > 0 && (info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) == 0) {
                            if (info.size > 1_048_576 - bytes) throw new IOException("AAC probe output limit");
                            ByteBuffer source = encoder.getOutputBuffer(slot);
                            if (source == null || info.offset < 0 || info.size > source.capacity() - info.offset)
                                throw new IOException("AAC probe output buffer");
                            byte[] copy = new byte[info.size];
                            source.position(info.offset); source.limit(info.offset + info.size); source.get(copy);
                            packets.add(new Packet(copy)); bytes += copy.length;
                        }
                        outputEnd = (info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0;
                    } finally { encoder.releaseOutputBuffer(slot, false); }
                    progress = true;
                }
                if (progress) progressAt = System.nanoTime(); else Thread.sleep(2);
            }
            if (encodedFormat == null || packets.isEmpty()) throw new IOException("AAC probe produced no stream");
            int reportedDelay = encodedFormat.containsKey(MediaFormat.KEY_ENCODER_DELAY)
                    ? encodedFormat.getInteger(MediaFormat.KEY_ENCODER_DELAY) : -1;
            if (reportedDelay < -1 || reportedDelay > MAX_DELAY) throw new IOException("AAC probe reported invalid delay");
            close(encoder); encoder = null;
            decoder = MediaCodec.createDecoderByType("audio/mp4a-latm");
            encodedFormat.setInteger(MediaFormat.KEY_PCM_ENCODING, AudioFormat.ENCODING_PCM_16BIT);
            // A raw decoder must expose priming, rather than applying an existing trim twice.
            encodedFormat.setInteger(MediaFormat.KEY_ENCODER_DELAY, 0);
            encodedFormat.setInteger(MediaFormat.KEY_ENCODER_PADDING, 0);
            decoder.configure(encodedFormat, null, null, 0); decoder.start();
            short[] firstChannel = new short[INPUT_FRAMES + MAX_DELAY * 2];
            int sent = 0, decoded = 0; inputEnd = false; outputEnd = false;
            progressAt = System.nanoTime();
            while (!outputEnd) {
                check(cancelled, progressAt);
                boolean progress = false;
                if (!inputEnd) {
                    int slot = decoder.dequeueInputBuffer(0);
                    if (slot >= 0) {
                        ByteBuffer target = decoder.getInputBuffer(slot);
                        if (target == null) throw new IOException("AAC probe decoder input missing");
                        target.clear();
                        byte[] data = sent < packets.size() ? packets.get(sent).data : new byte[0];
                        if (target.remaining() < data.length) throw new IOException("AAC packet exceeds decoder capacity");
                        target.put(data);
                        int flags = sent == packets.size() ? MediaCodec.BUFFER_FLAG_END_OF_STREAM : 0;
                        decoder.queueInputBuffer(slot, 0, data.length,
                                OfflineMp4Math.timestampUs((long) sent * 1024, rate, 1), flags);
                        if (flags == 0) sent++; else inputEnd = true;
                        progress = true;
                    }
                }
                int slot = decoder.dequeueOutputBuffer(info, 0);
                if (slot == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    MediaFormat format = decoder.getOutputFormat();
                    if (format.getInteger(MediaFormat.KEY_SAMPLE_RATE) != rate
                            || format.getInteger(MediaFormat.KEY_CHANNEL_COUNT) != channels
                            || (format.containsKey(MediaFormat.KEY_PCM_ENCODING)
                                && format.getInteger(MediaFormat.KEY_PCM_ENCODING) != AudioFormat.ENCODING_PCM_16BIT))
                        throw new IOException("AAC probe changed PCM format");
                    progress = true;
                } else if (slot >= 0) {
                    try {
                        if (info.size > 0) {
                            ByteBuffer source = decoder.getOutputBuffer(slot);
                            int stride = channels * 2;
                            if (source == null || info.offset < 0 || info.size % stride != 0
                                    || info.size > source.capacity() - info.offset
                                    || info.size / stride > firstChannel.length - decoded)
                                throw new IOException("AAC probe decoded buffer bounds");
                            source.order(ByteOrder.LITTLE_ENDIAN);
                            for (int offset = info.offset; offset < info.offset + info.size; offset += stride)
                                firstChannel[decoded++] = source.getShort(offset);
                        }
                        outputEnd = (info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0;
                    } finally { decoder.releaseOutputBuffer(slot, false); }
                    progress = true;
                }
                if (progress) progressAt = System.nanoTime(); else Thread.sleep(2);
            }
            if (decoded != packets.size() * 1024)
                throw new IOException("AAC decoder trimmed samples or changed the packet clock during calibration");
            int measured = measuredDelay(firstChannel, decoded);
            if (reportedDelay >= 0 && reportedDelay != measured)
                throw new IOException("AAC reported priming differs from the decoded calibration");
            return measured;
        } finally { close(encoder); close(decoder); }
    }

    static int measuredDelay(short[] samples, int count) throws IOException {
        if (count > samples.length || count < SECOND + MAX_DELAY + 1)
            throw new IOException("AAC probe returned too few samples");
        int first = peak(samples, FIRST, FIRST + MAX_DELAY + 1);
        int second = peak(samples, SECOND, SECOND + MAX_DELAY + 1);
        int delay = first - FIRST;
        if (second - SECOND != delay || Math.abs((int) samples[first]) < 1000
                || Math.abs((int) samples[second]) < 1000
                || samples[first] <= 0 || samples[second] >= 0)
            throw new IOException("AAC priming measurement was inconsistent");
        return delay;
    }

    private static int peak(short[] data, int start, int end) {
        int peak = start;
        for (int i = start + 1; i < end; i++) if (Math.abs((int) data[i]) > Math.abs((int) data[peak])) peak = i;
        return peak;
    }
    private static void check(BooleanSupplier cancelled, long lastProgress) throws IOException {
        if (cancelled.getAsBoolean()) throw new IOException("Export cancelled");
        if (System.nanoTime() - lastProgress > STALL_NS) throw new IOException("AAC probe codec stopped progressing");
    }
    static void close(MediaCodec codec) {
        if (codec == null) return;
        try { codec.stop(); } catch (RuntimeException ignored) {}
        try { codec.release(); } catch (RuntimeException ignored) {}
    }
}
