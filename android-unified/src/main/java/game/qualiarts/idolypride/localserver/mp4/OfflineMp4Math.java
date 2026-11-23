package game.qualiarts.idolypride.localserver.mp4;

/** Integer sample clocks and deterministic SDR conversion; no game or Android dependencies. */
public final class OfflineMp4Math {
    private static final int[] SRGB_TO_709 = transferTable();
    private OfflineMp4Math() {}

    public static long timestampUs(long index, int rateNumerator, int rateDenominator) {
        if (index < 0 || rateNumerator <= 0 || rateNumerator > 1_000_000
                || rateDenominator <= 0 || rateDenominator > 10_000)
            throw new IllegalArgumentException("Invalid sample clock");
        long unit = 1_000_000L * rateDenominator;
        return Math.addExact(Math.multiplyExact(index / rateNumerator, unit),
                Math.multiplyExact(index % rateNumerator, unit) / rateNumerator);
    }

    public static long audioBoundary(long videoFrames, int fpsNumerator, int fpsDenominator, int sampleRate) {
        if (videoFrames < 0 || fpsNumerator <= 0 || fpsNumerator > 1_000_000
                || fpsDenominator <= 0 || fpsDenominator > 10_000 || sampleRate <= 0 || sampleRate > 96000)
            throw new IllegalArgumentException("Invalid audio/video clock");
        long unit = (long) sampleRate * fpsDenominator;
        long remainder = Math.multiplyExact(videoFrames % fpsNumerator, unit);
        return Math.addExact(Math.multiplyExact(videoFrames / fpsNumerator, unit),
                remainder / fpsNumerator + (remainder % fpsNumerator == 0 ? 0 : 1));
    }

    public static long videoFramesForAudio(long audioFrames, int fpsNumerator, int fpsDenominator, int sampleRate) {
        if (audioFrames < 1 || fpsNumerator < 1 || fpsNumerator > 1_000_000 || fpsDenominator < 1
                || fpsDenominator > 10_000 || sampleRate < 1 || sampleRate > 96000)
            throw new IllegalArgumentException("Invalid audio/video duration");
        long divisor = (long) sampleRate * fpsDenominator;
        long rest = Math.multiplyExact(audioFrames % divisor, fpsNumerator);
        return Math.addExact(Math.multiplyExact(audioFrames / divisor, fpsNumerator),
                rest / divisor + (rest % divisor == 0 ? 0 : 1));
    }

    public static int pixels(int width, int height) {
        // The native producer never renders an edge above 4096. Frames are
        // staged as I420 (three 1.5-byte-per-pixel slots, at most 72 MiB).
        if (width < 16 || height < 16 || (width & 1) != 0 || (height & 1) != 0
                || width > 4096 || height > 4096)
            throw new IllegalArgumentException("Video dimensions must be even, between 16 and 4096");
        return width * height;
    }

    /** Opaque sRGB RGBA8 to limited-range BT.709. Alpha never becomes a fourth image plane. */
    public static void rgbaToI420(byte[] rgba, byte[] planar, int width, int height) {
        int pixels = pixels(width, height);
        if (rgba.length != pixels * 4)
            throw new IllegalArgumentException("Unexpected frame buffer size");
        rgbaToI420(java.nio.ByteBuffer.wrap(rgba), width * 4, planar, width, height);
    }

    /**
     * Same conversion from rows at rowBytes stride, read from the buffer's position. The native
     * producer's mp4_i420.hpp is bit-identical to this; its tests compare the two.
     */
    public static void rgbaToI420(java.nio.ByteBuffer rgba, int rowBytes, byte[] planar, int width, int height) {
        int pixels = pixels(width, height), origin = rgba.position();
        if (planar.length != pixels * 3 / 2 || rowBytes < width * 4
                || (long) (height - 1) * rowBytes + (long) width * 4 > rgba.remaining())
            throw new IllegalArgumentException("Unexpected frame buffer size");
        for (int y = 0; y < height; y += 2) {
            for (int x = 0; x < width; x += 2) {
                int red = 0, green = 0, blue = 0;
                for (int dy = 0; dy < 2; dy++) {
                    for (int dx = 0; dx < 2; dx++) {
                        int pixel = (y + dy) * width + x + dx, offset = origin + (y + dy) * rowBytes + (x + dx) * 4;
                        int r = SRGB_TO_709[rgba.get(offset) & 255], g = SRGB_TO_709[rgba.get(offset + 1) & 255],
                                b = SRGB_TO_709[rgba.get(offset + 2) & 255];
                        planar[pixel] = (byte) clamp(16 + ((47 * r + 157 * g + 16 * b + 128) >> 8), 16, 235);
                        red += r; green += g; blue += b;
                    }
                }
                int chroma = (y / 2) * (width / 2) + x / 2;
                planar[pixels + chroma] = (byte) clamp(128 + ((-26 * red - 86 * green + 112 * blue + 512) >> 10), 16, 240);
                planar[pixels + pixels / 4 + chroma] = (byte) clamp(128 + ((112 * red - 102 * green - 10 * blue + 512) >> 10), 16, 240);
            }
        }
    }

    /** PCM16 conversion is deterministic, with no resampling, time stretching or added noise. */
    public static short pcm16(float sample) {
        if (!Float.isFinite(sample)) throw new IllegalArgumentException("Non-finite source PCM");
        if (sample <= -1) return Short.MIN_VALUE;
        if (sample >= 1) return Short.MAX_VALUE;
        return (short) Math.round(sample * 32767f);
    }

    private static int clamp(int value, int lower, int upper) {
        return Math.max(lower, Math.min(upper, value));
    }

    private static int[] transferTable() {
        int[] table = new int[256];
        for (int i = 0; i < table.length; i++) {
            double signal = i / 255.0;
            double linear = signal <= 0.04045 ? signal / 12.92 : Math.pow((signal + 0.055) / 1.055, 2.4);
            double output = linear < 0.018 ? linear * 4.5 : 1.099 * Math.pow(linear, 0.45) - 0.099;
            table[i] = clamp((int) Math.round(output * 255), 0, 255);
        }
        return table;
    }
}
