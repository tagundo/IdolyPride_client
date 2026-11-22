package game.qualiarts.idolypride.localserver;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.LinkedHashMap;
import java.util.Map;

/** Durable editor draft, separate from the immutable options already copied into queue jobs. */
final class Mp4ExportSettings {
    static final String PREFS = "mp4_export";
    static final int MIN_BITRATE = 100_000, MAX_BITRATE = 200_000_000;
    static final int MIN_EDGE = 16, MAX_EDGE = 4096;
    private static final String PREFIX = "options_v1_";

    interface Store {
        String read(String key, String fallback);
        void write(Map<String, String> values);
    }

    final int fps, codec;
    final boolean customBitrate, customResolution;
    final String bitrateMbps, width, height;

    Mp4ExportSettings(int fps, int codec, boolean customBitrate, String bitrateMbps,
            boolean customResolution, String width, String height) {
        this.fps = supportedFps(fps) ? fps : 30;
        this.codec = codec == 2 ? 2 : 1;
        this.customBitrate = customBitrate;
        this.bitrateMbps = bounded(bitrateMbps);
        this.customResolution = customResolution;
        this.width = bounded(width);
        this.height = bounded(height);
    }

    static boolean supportedFps(int value) { return value == 30 || value == 60 || value == 120; }
    static int fpsPosition(int value) { return value == 120 ? 2 : value == 60 ? 1 : 0; }
    static int fpsAt(int position) { return position == 2 ? 120 : position == 1 ? 60 : 30; }
    private static int parseFps(String value) { return "120".equals(value) ? 120 : "60".equals(value) ? 60 : 30; }

    static Mp4ExportSettings defaults() {
        return new Mp4ExportSettings(30, 1, false, "16", false, "1920", "1080");
    }

    static Mp4ExportSettings load(Store store) {
        Mp4ExportSettings defaults = defaults();
        return new Mp4ExportSettings(parseFps(store.read(PREFIX + "fps", "30")),
                "2".equals(store.read(PREFIX + "codec", "1")) ? 2 : 1,
                "custom".equals(store.read(PREFIX + "bitrate_mode", "recommended")),
                store.read(PREFIX + "bitrate_mbps", defaults.bitrateMbps),
                "custom".equals(store.read(PREFIX + "resolution_mode", "current")),
                store.read(PREFIX + "width", defaults.width), store.read(PREFIX + "height", defaults.height));
    }

    void save(Store store) {
        Map<String, String> values = new LinkedHashMap<>();
        values.put(PREFIX + "fps", Integer.toString(fps));
        values.put(PREFIX + "codec", Integer.toString(codec));
        values.put(PREFIX + "bitrate_mode", customBitrate ? "custom" : "recommended");
        values.put(PREFIX + "bitrate_mbps", bitrateMbps);
        values.put(PREFIX + "resolution_mode", customResolution ? "custom" : "current");
        values.put(PREFIX + "width", width);
        values.put(PREFIX + "height", height);
        store.write(values);
    }

    /** Zero asks the native job admission path to resolve a recommendation from actual output geometry. */
    int requestBitrate() { return customBitrate ? parseBitrate(bitrateMbps) : 0; }
    int requestWidth() { return customResolution ? parseEdge(width) : 0; }
    int requestHeight() { return customResolution ? parseEdge(height) : 0; }
    boolean valid() {
        return validBitrate(requestBitrate()) && validResolution(requestWidth(), requestHeight());
    }
    boolean bitrateValid() { return validBitrate(requestBitrate()); }
    boolean resolutionValid() { return validResolution(requestWidth(), requestHeight()); }

    static boolean validBitrate(int value) { return value == 0 || value >= MIN_BITRATE && value <= MAX_BITRATE; }
    static boolean validResolution(int width, int height) {
        return width == 0 && height == 0 || validEdge(width) && validEdge(height);
    }
    private static boolean validEdge(int value) {
        return value >= MIN_EDGE && value <= MAX_EDGE && value % 2 == 0;
    }
    static int parseEdge(String text) {
        if (text == null || !text.matches("[0-9]{1,5}")) return -1;
        try { int value = Integer.parseInt(text); return validEdge(value) ? value : -1; }
        catch (NumberFormatException invalid) { return -1; }
    }
    static int parseBitrate(String text) {
        if (text == null || !text.matches("(?:[0-9]{1,3})(?:\\.[0-9]{1,6})?")) return -1;
        try {
            int value = new BigDecimal(text).multiply(BigDecimal.valueOf(1_000_000))
                    .setScale(0, RoundingMode.UNNECESSARY).intValueExact();
            return value >= MIN_BITRATE && value <= MAX_BITRATE ? value : -1;
        } catch (ArithmeticException | NumberFormatException invalid) { return -1; }
    }
    static int recommendedBitrate(int width, int height, int fps, int codec) {
        if (!validEdge(width) || !validEdge(height) || !supportedFps(fps) || (codec != 1 && codec != 2)) return -1;
        long suggested = (((long) width * height * fps * (codec == 1 ? 14 : 9) + 500_000) / 1_000_000) * 10_000;
        return (int) Math.max(250_000, Math.min(MAX_BITRATE, suggested));
    }
    private static String bounded(String value) {
        if (value == null) return "";
        return value.length() <= 32 ? value : value.substring(0, 32);
    }
}
