package game.qualiarts.idolypride.mp4qa;

import android.app.Activity;
import android.media.AudioFormat;
import android.media.Image;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaExtractor;
import android.media.MediaFormat;
import android.os.Bundle;
import android.widget.TextView;
import game.qualiarts.idolypride.localserver.mp4.OfflineMp4Encoder;
import game.qualiarts.idolypride.localserver.mp4.OfflineMp4Math;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import org.json.JSONArray;
import org.json.JSONObject;

/** Standalone real-device codec proof; no game, assets, native offsets or network access. */
public final class CodecProbeActivity extends Activity {
    private static final int WIDTH = 160, HEIGHT = 96, RATE = 48000, CHANNELS = 2;
    private static final String PACKAGE = "game.qualiarts.idolypride.mp4qa";
    private volatile OfflineMp4Encoder active;
    private volatile boolean stopped;
    private File root;
    private TextView label;
    private final JSONArray cases = new JSONArray();

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        label = new TextView(this); label.setText("Running actual MediaCodec A/V proof…"); setContentView(label);
        root = new File(getFilesDir(), "mp4-qa");
        if (ProbeRunOwnership.claimProcessRun()) new Thread(this::runProof, "IdolyCodecQA").start();
        else label.setText("The codec proof has already started in this process.");
    }
    @Override public void onDestroy() {
        if (!isChangingConfigurations()) {
            stopped = true; OfflineMp4Encoder encoder = active; if (encoder != null) encoder.cancel();
        }
        super.onDestroy();
    }

    private void runProof() {
        try {
            if (!root.isDirectory() && !root.mkdirs()) throw new IOException("QA directory unavailable");
            report("running", false, null);
            runCase("avc30", true, 1, 30, 1);
            runCase("avc60000_1001", true, 1, 60000, 1001);
            cancellation(); noOverwrite();
            runCase("hevc30", false, 2, 30, 1);
            report("completed", true, null);
            runOnUiThread(() -> label.setText("PASS: actual video/audio, timing, cancellation and no-overwrite"));
        } catch (Throwable failure) {
            OfflineMp4Encoder encoder = active; if (encoder != null) encoder.cancel();
            try { report("failed", false, failure.toString()); } catch (Exception ignored) {}
            runOnUiThread(() -> label.setText("FAIL: " + failure));
        }
    }

    private void runCase(String name, boolean required, int codec, int numerator, int denominator) throws Exception {
        JSONObject proof = new JSONObject().put("name", name).put("required", required);
        cases.put(proof); report("running", false, null);
        File directory = new File(root, name);
        ProbeRunOwnership.createFreshDirectory(directory);
        File pcm = new File(directory, "source.f32"); writePcm(pcm);
        File partial = new File(directory, "partial.mp4"), output = new File(directory, "complete.mp4");
        long frameCount = OfflineMp4Math.videoFramesForAudio(RATE, numerator, denominator, RATE);
        long deadline = System.nanoTime() + 180_000_000_000L;
        OfflineMp4Encoder encoder = OfflineMp4Encoder.create(WIDTH, HEIGHT, numerator, denominator,
                2_000_000, RATE, CHANNELS, RATE, frameCount, pcm.getPath(), partial.getPath(), output.getPath(), codec);
        active = encoder;
        ByteBuffer rgba = ByteBuffer.allocateDirect(WIDTH * HEIGHT * 4);
        for (long index = 0; index < frameCount;) {
            check(deadline); pixels(rgba, index);
            int result = encoder.appendFrame(rgba, WIDTH * 4, index);
            if (result == OfflineMp4Encoder.ACCEPT) index++;
            else if (result == OfflineMp4Encoder.RETRY) Thread.sleep(3);
            else break;
        }
        if (!encoder.isTerminal()) encoder.finish();
        while (!encoder.isTerminal()) { check(deadline); Thread.sleep(10); }
        active = null;
        JSONObject encoderStatus = new JSONObject(encoder.statusJson()); proof.put("encoder", encoderStatus);
        if (!"completed".equals(encoderStatus.getString("phase"))) {
            String detail = encoderStatus.optString("error");
            if (!required && detail.contains("No encoder accepted video/hevc")) {
                proof.put("status", "unsupported").put("reason", "device_has_no_supported_hevc_encoder")
                        .put("capability_checked", true);
                report("running", false, null); return;
            }
            throw new IOException(name + " encoder failed: " + encoderStatus);
        }
        require(output.isFile() && output.length() > 0 && !partial.exists(), "Final file ownership");
        require(pcm.length() == RATE * CHANNELS * 4L, "PCM source preserved");
        proof.put("width", WIDTH).put("height", HEIGHT).put("fps_numerator", numerator).put("fps_denominator", denominator);
        proof.put("frames", frameCount).put("file", name + "/complete.mp4");
        int videoFrames = decodeVideo(output, numerator, denominator, frameCount, deadline);
        proof.put("decoded_video_frames", videoFrames).put("ordered_video_pts", true).put("corner_pixels_verified", true);
        int priming = encoderStatus.getInt("aac_priming_samples");
        long packets = encoderStatus.getLong("audio_packets");
        JSONObject audio = decodeAudio(output, priming, packets, deadline);
        inspectEdit(output, priming); audio.put("edit_list_exact", true);
        proof.put("audio", audio).put("source_preserved", true).put("status", "passed");
        report("running", false, null);
    }

    private void cancellation() throws Exception {
        File directory = new File(root, "cancel"); require(directory.mkdir(), "Cancel directory");
        File pcm = new File(directory, "source.f32"); writePcm(pcm);
        File partial = new File(directory, "partial.mp4"), output = new File(directory, "complete.mp4");
        OfflineMp4Encoder encoder = OfflineMp4Encoder.create(WIDTH, HEIGHT, 30, 1, 2_000_000,
                RATE, CHANNELS, RATE, 30, pcm.getPath(), partial.getPath(), output.getPath(), 1);
        active = encoder; ByteBuffer rgba = ByteBuffer.allocateDirect(WIDTH * HEIGHT * 4); pixels(rgba, 0);
        require(encoder.appendFrame(rgba, WIDTH * 4, 0) == OfflineMp4Encoder.ACCEPT, "Cancel accepted copied frame");
        encoder.cancel(); encoder.cancel();
        long deadline = System.nanoTime() + 45_000_000_000L;
        while (!encoder.isTerminal()) { check(deadline); Thread.sleep(5); }
        active = null;
        require("cancelled".equals(new JSONObject(encoder.statusJson()).getString("phase")), "Cancel terminal phase");
        require(!partial.exists() && !output.exists() && pcm.length() == RATE * CHANNELS * 4L, "Cancel file ownership");
        cases.put(new JSONObject().put("name", "cancel").put("required", true).put("status", "passed")
                .put("terminal_cleanup", true).put("source_preserved", true).put("output_absent", true));
        report("running", false, null);
    }

    private void noOverwrite() throws Exception {
        File directory = new File(root, "no_overwrite"); require(directory.mkdir(), "Overwrite directory");
        File pcm = new File(directory, "source.f32"); writePcm(pcm);
        File output = new File(directory, "complete.mp4"), partial = new File(directory, "partial.mp4");
        byte[] sentinel = {19, 27, 34, 45}; Files.write(output.toPath(), sentinel);
        boolean rejected = false;
        try { OfflineMp4Encoder.create(WIDTH, HEIGHT, 30, 1, 2_000_000, RATE, CHANNELS, RATE, 30,
                pcm.getPath(), partial.getPath(), output.getPath(), 1); }
        catch (IOException expected) { rejected = true; }
        require(rejected && java.util.Arrays.equals(Files.readAllBytes(output.toPath()), sentinel) && !partial.exists(),
                "Existing final file was modified");
        cases.put(new JSONObject().put("name", "no_overwrite").put("required", true).put("status", "passed")
                .put("sentinel_preserved", true).put("partial_absent", true));
        report("running", false, null);
    }

    private static void writePcm(File path) throws IOException {
        ByteBuffer buffer = ByteBuffer.allocate(4096 * CHANNELS * 4).order(ByteOrder.LITTLE_ENDIAN);
        try (FileOutputStream file = new FileOutputStream(path)) {
            for (int index = 0; index < RATE;) {
                buffer.clear(); int count = Math.min(4096, RATE - index);
                for (int frame = 0; frame < count; frame++) for (int channel = 0; channel < CHANNELS; channel++)
                    buffer.putFloat(index + frame == 8000 ? 0.8f : index + frame == 32000 ? -0.6f : 0);
                file.write(buffer.array(), 0, buffer.position()); index += count;
            }
            file.getFD().sync();
        }
    }
    private static void pixels(ByteBuffer target, long index) {
        target.clear();
        for (int y = 0; y < HEIGHT; y++) for (int x = 0; x < WIDTH; x++) {
            int quadrant = (y >= HEIGHT / 2 ? 2 : 0) + (x >= WIDTH / 2 ? 1 : 0);
            int r = quadrant == 0 || quadrant == 3 ? 255 : 0;
            int g = quadrant == 1 || quadrant == 3 ? 255 : 0;
            int b = quadrant >= 2 ? 255 : 0;
            if (x > WIDTH / 2 - 8 && x < WIDTH / 2 + 8 && y > HEIGHT / 2 - 8 && y < HEIGHT / 2 + 8)
                r = g = b = (int) ((index * 31) & 255);
            target.put((byte) r).put((byte) g).put((byte) b).put((byte) 255);
        }
        target.flip();
    }

    private int decodeVideo(File file, int numerator, int denominator, long expectedFrames, long deadline) throws Exception {
        MediaExtractor extractor = new MediaExtractor(); MediaCodec decoder = null;
        try {
            extractor.setDataSource(file.getPath()); int track = track(extractor, "video/");
            MediaFormat format = extractor.getTrackFormat(track); extractor.selectTrack(track);
            require(format.getInteger(MediaFormat.KEY_WIDTH) == WIDTH && format.getInteger(MediaFormat.KEY_HEIGHT) == HEIGHT,
                    "Video dimensions changed");
            format.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible);
            decoder = MediaCodec.createDecoderByType(format.getString(MediaFormat.KEY_MIME));
            decoder.configure(format, null, null, 0); decoder.start();
            boolean inputEnd = false, outputEnd = false; int count = 0, inputs = 0;
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            while (!outputEnd) {
                check(deadline);
                if (!inputEnd) {
                    int slot = decoder.dequeueInputBuffer(0);
                    if (slot >= 0) {
                        ByteBuffer target = decoder.getInputBuffer(slot); require(target != null, "Video decoder input"); target.clear();
                        int length = extractor.readSampleData(target, 0);
                        if (length < 0) { decoder.queueInputBuffer(slot, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM); inputEnd = true; }
                        else {
                            long expected = OfflineMp4Math.timestampUs(inputs, numerator, denominator);
                            require(Math.abs(extractor.getSampleTime() - expected) <= 1, "Muxed video PTS changed");
                            decoder.queueInputBuffer(slot, 0, length, extractor.getSampleTime(), 0); inputs++; extractor.advance();
                        }
                    }
                }
                int slot = decoder.dequeueOutputBuffer(info, 1000);
                if (slot >= 0) {
                    try {
                        if (info.size > 0) {
                            require(Math.abs(info.presentationTimeUs - OfflineMp4Math.timestampUs(count, numerator, denominator)) <= 1,
                                    "Decoded video PTS changed");
                            Image image = decoder.getOutputImage(slot); require(image != null, "Video decoder exposes no YUV image");
                            corners(image); count++;
                        }
                        outputEnd = (info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0;
                    } finally { decoder.releaseOutputBuffer(slot, false); }
                }
            }
            require(inputs == expectedFrames && count == expectedFrames, "Actual video frame count differs");
            return count;
        } finally { extractor.release(); close(decoder); }
    }
    private static void corners(Image image) throws IOException {
        require(image.getPlanes().length == 3, "Decoded YUV plane count");
        int[][] values = {{63, 102, 240}, {172, 42, 26}, {32, 240, 118}, {235, 128, 128}};
        for (int quadrant = 0; quadrant < 4; quadrant++) {
            int x = quadrant % 2 == 0 ? WIDTH / 4 : WIDTH * 3 / 4;
            int y = quadrant / 2 == 0 ? HEIGHT / 4 : HEIGHT * 3 / 4;
            for (int p = 0; p < 3; p++) {
                Image.Plane plane = image.getPlanes()[p]; ByteBuffer data = plane.getBuffer();
                int divisor = p == 0 ? 1 : 2;
                int at = data.position() + (y / divisor) * plane.getRowStride() + (x / divisor) * plane.getPixelStride();
                require(at < data.limit() && Math.abs((data.get(at) & 255) - values[quadrant][p]) <= 18,
                        "Video corner color/orientation mismatch");
            }
        }
    }

    private JSONObject decodeAudio(File file, int priming, long packetCount, long deadline) throws Exception {
        MediaExtractor extractor = new MediaExtractor(); MediaCodec decoder = null;
        try {
            extractor.setDataSource(file.getPath()); int track = track(extractor, "audio/");
            MediaFormat format = extractor.getTrackFormat(track); extractor.selectTrack(track);
            require("audio/mp4a-latm".equals(format.getString(MediaFormat.KEY_MIME)), "AAC output missing");
            format.setInteger(MediaFormat.KEY_PCM_ENCODING, AudioFormat.ENCODING_PCM_16BIT);
            format.setInteger(MediaFormat.KEY_ENCODER_DELAY, 0); format.setInteger(MediaFormat.KEY_ENCODER_PADDING, 0);
            decoder = MediaCodec.createDecoderByType("audio/mp4a-latm"); decoder.configure(format, null, null, 0); decoder.start();
            short[] samples = new short[(int) packetCount * 1024 + 4096];
            boolean inputEnd = false, outputEnd = false; int count = 0, packets = 0;
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            while (!outputEnd) {
                check(deadline);
                if (!inputEnd) {
                    int slot = decoder.dequeueInputBuffer(0);
                    if (slot >= 0) {
                        ByteBuffer target = decoder.getInputBuffer(slot); require(target != null, "AAC decoder input"); target.clear();
                        int length = extractor.readSampleData(target, 0);
                        if (length < 0) { decoder.queueInputBuffer(slot, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM); inputEnd = true; }
                        else {
                            decoder.queueInputBuffer(slot, 0, length, OfflineMp4Math.timestampUs((long) packets * 1024, RATE, 1), 0);
                            packets++; extractor.advance();
                        }
                    }
                }
                int slot = decoder.dequeueOutputBuffer(info, 1000);
                if (slot == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    MediaFormat output = decoder.getOutputFormat();
                    require(output.getInteger(MediaFormat.KEY_SAMPLE_RATE) == RATE && output.getInteger(MediaFormat.KEY_CHANNEL_COUNT) == CHANNELS,
                            "Decoded AAC rate/channels changed");
                    require(!output.containsKey(MediaFormat.KEY_PCM_ENCODING)
                            || output.getInteger(MediaFormat.KEY_PCM_ENCODING) == AudioFormat.ENCODING_PCM_16BIT, "Decoded AAC PCM format");
                } else if (slot >= 0) {
                    try {
                        if (info.size > 0) {
                            ByteBuffer data = decoder.getOutputBuffer(slot); require(data != null && info.size % (CHANNELS * 2) == 0,
                                    "Decoded AAC buffer"); data.order(ByteOrder.LITTLE_ENDIAN);
                            require(count + info.size / (CHANNELS * 2) <= samples.length, "Decoded AAC bound");
                            for (int p = info.offset; p < info.offset + info.size; p += CHANNELS * 2) samples[count++] = data.getShort(p);
                        }
                        outputEnd = (info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0;
                    } finally { decoder.releaseOutputBuffer(slot, false); }
                }
            }
            require(packets == packetCount && count == packetCount * 1024, "AAC packet/sample clock differs");
            require(peak(samples, 8000 + priming - 8, 8000 + priming + 9) == 8000 + priming
                    && peak(samples, 32000 + priming - 8, 32000 + priming + 9) == 32000 + priming,
                    "Exported soundtrack priming differs from calibration");
            require(samples[8000 + priming] > 1000 && samples[32000 + priming] < -1000, "AAC impulse polarity/amplitude");
            return new JSONObject().put("raw_decoded_frames", count).put("logical_frames", RATE)
                    .put("aac_packets", packets).put("priming_samples", priming).put("impulses_verified", true);
        } finally { extractor.release(); close(decoder); }
    }
    private static int peak(short[] samples, int first, int end) {
        int best = first;
        for (int i = first + 1; i < end; i++) if (Math.abs((int) samples[i]) > Math.abs((int) samples[best])) best = i;
        return best;
    }

    private static final class Box {
        final String type; final int start, payload, end;
        Box(String type, int start, int payload, int end) { this.type = type; this.start = start; this.payload = payload; this.end = end; }
    }
    private static ArrayList<Box> boxes(ByteBuffer data, int start, int end) throws IOException {
        ArrayList<Box> result = new ArrayList<>();
        while (start < end) {
            require(end - start >= 8, "Short proof MP4 box"); long length = Integer.toUnsignedLong(data.getInt(start));
            byte[] type = new byte[4]; for (int i = 0; i < 4; i++) type[i] = data.get(start + 4 + i);
            int header = 8; if (length == 1) { require(end - start >= 16, "Short large box"); length = data.getLong(start + 8); header = 16; }
            if (length == 0) length = end - start;
            require(length >= header && length <= end - start, "Proof MP4 box bounds");
            result.add(new Box(new String(type, java.nio.charset.StandardCharsets.ISO_8859_1), start, start + header, start + (int) length));
            start += (int) length;
        }
        return result;
    }
    private static Box one(ArrayList<Box> boxes, String type) throws IOException {
        Box result = null;
        for (Box box : boxes) if (box.type.equals(type)) { require(result == null, "Duplicate " + type); result = box; }
        require(result != null, "Missing " + type); return result;
    }
    private static void inspectEdit(File file, int priming) throws IOException {
        require(file.length() < 16 * 1024 * 1024, "QA MP4 unexpectedly large");
        ByteBuffer data = ByteBuffer.wrap(Files.readAllBytes(file.toPath())).order(ByteOrder.BIG_ENDIAN);
        Box moov = one(boxes(data, 0, data.limit()), "moov"); ArrayList<Box> children = boxes(data, moov.payload, moov.end);
        Box mvhd = one(children, "mvhd"); int version = data.get(mvhd.payload) & 255;
        long scale = Integer.toUnsignedLong(data.getInt(mvhd.payload + (version == 0 ? 12 : 20)));
        require(scale > 0 && scale % RATE == 0, "Exact PCM movie timescale");
        int audio = 0;
        for (Box track : children) if (track.type.equals("trak")) {
            ArrayList<Box> parts = boxes(data, track.payload, track.end); Box mdia = one(parts, "mdia");
            Box hdlr = one(boxes(data, mdia.payload, mdia.end), "hdlr");
            if (data.getInt(hdlr.payload + 8) != 0x736f756e) continue;
            audio++; Box edts = one(parts, "edts"), elst = one(boxes(data, edts.payload, edts.end), "elst");
            require(data.get(elst.payload) == 1 && data.getInt(elst.payload + 4) == 1,
                    "Exact v1 AAC edit list");
            require(data.getLong(elst.payload + 8) == scale && data.getLong(elst.payload + 16) == priming
                    && data.getInt(elst.payload + 24) == 0x00010000, "AAC logical interval or media time changed");
        }
        require(audio == 1, "One AAC edit track required");
    }
    private static int track(MediaExtractor extractor, String prefix) throws IOException {
        require(extractor.getTrackCount() == 2, "Exactly video and audio tracks required");
        int found = -1;
        for (int i = 0; i < extractor.getTrackCount(); i++)
            if (extractor.getTrackFormat(i).getString(MediaFormat.KEY_MIME).startsWith(prefix)) { require(found < 0, "Duplicate track"); found = i; }
        require(found >= 0, "Missing " + prefix); return found;
    }
    private void check(long deadline) throws IOException {
        if (stopped || System.nanoTime() > deadline) throw new IOException("Codec QA stopped or timed out");
    }
    private static void require(boolean condition, String message) throws IOException {
        if (!condition) throw new IOException(message);
    }
    private static void close(MediaCodec codec) {
        if (codec == null) return;
        try { codec.stop(); } catch (RuntimeException ignored) {}
        try { codec.release(); } catch (RuntimeException ignored) {}
    }
    private void report(String phase, boolean passed, String error) throws Exception {
        JSONObject report = new JSONObject().put("schema", 1).put("package", PACKAGE).put("phase", phase)
                .put("passed", passed).put("cases", cases);
        if (error != null) report.put("error", error);
        File temporary = new File(root, "report.json.tmp"), destination = new File(root, "report.json");
        try (FileOutputStream output = new FileOutputStream(temporary)) {
            output.write(report.toString(2).getBytes(java.nio.charset.StandardCharsets.UTF_8)); output.getFD().sync();
        }
        Files.move(temporary.toPath(), destination.toPath(), StandardCopyOption.REPLACE_EXISTING);
    }
}
