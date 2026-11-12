package game.qualiarts.idolypride.localserver;

import android.util.AtomicFile;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import org.json.JSONException;
import org.json.JSONObject;

/** The private, versioned hand-off between server controls and the game bridge. */
final class PresentationSettings {
    static final int[] QUALITY = {0, 10, 20, 30, 40, 100};
    static final int[] TARGET_FPS = {0, 30, 60, 90, 120};
    static final double[] RENDER_SCALE = {0.25, 0.5, 0.75, 1, 1.25, 1.5, 2};
    static final int[] MAX_BUFFER_PIXEL = {720, 1080, 1440, 1920, 2560, 3840, 4096};
    static final int[] ANTI_ALIASING = {-1, 0, 1, 2};
    static final int[] SHADOW_RESOLUTION = {0, 512, 1024, 2048, 4096};
    private static final int MAX_SETTINGS_BYTES = 16 * 1024;

    final long revision;
    final boolean customGraphics;
    final int quality;
    final int targetFps;
    final double renderScale;
    final int maxBufferPixel;
    final int antiAliasing;
    final int shadowResolution;
    final boolean expandPhotography;

    PresentationSettings(long revision, boolean customGraphics, int quality, int targetFps,
            double renderScale, int maxBufferPixel, int antiAliasing, int shadowResolution,
            boolean expandPhotography) {
        this.revision = revision;
        this.customGraphics = customGraphics;
        this.quality = quality;
        this.targetFps = targetFps;
        this.renderScale = renderScale;
        this.maxBufferPixel = maxBufferPixel;
        this.antiAliasing = antiAliasing;
        this.shadowResolution = shadowResolution;
        this.expandPhotography = expandPhotography;
    }

    static PresentationSettings defaults() {
        return new PresentationSettings(0, false, 0, 0, 1, 4096, -1, 0, false);
    }

    static File path(File filesDirectory) {
        return new File(new File(filesDirectory, "data"), "client-presentation.json");
    }

    static final class Loaded {
        final PresentationSettings settings;
        final boolean invalid;

        Loaded(PresentationSettings settings, boolean invalid) {
            this.settings = settings;
            this.invalid = invalid;
        }
    }

    static Loaded load(File filesDirectory) {
        AtomicFile source = new AtomicFile(path(filesDirectory));
        if (!source.getBaseFile().exists()
                && !new File(source.getBaseFile().getPath() + ".bak").exists()) {
            return new Loaded(defaults(), false);
        }
        try (FileInputStream input = source.openRead();
                ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[1024];
            int count;
            while ((count = input.read(buffer)) != -1) {
                if (output.size() + count > MAX_SETTINGS_BYTES) throw new IOException("Settings too large");
                output.write(buffer, 0, count);
            }
            return new Loaded(parse(new JSONObject(output.toString(StandardCharsets.UTF_8.name()))), false);
        } catch (IOException | JSONException | IllegalArgumentException error) {
            // A damaged settings file must never prevent server controls opening.
            // Do not replace it until the user makes an explicit setting change.
            return new Loaded(defaults(), true);
        }
    }

    private static PresentationSettings parse(JSONObject object) throws JSONException {
        if (object.length() != 10 || integer(object, "schema") != 1) {
            throw new IllegalArgumentException("Unsupported settings schema");
        }
        Object revisionValue = object.get("revision");
        if (!(revisionValue instanceof Integer || revisionValue instanceof Long)
                || ((Number) revisionValue).longValue() < 0) {
            throw new IllegalArgumentException("Invalid settings revision");
        }
        int quality = integer(object, "quality");
        int fps = integer(object, "target_fps");
        Object scaleValue = object.get("render_scale");
        if (!(scaleValue instanceof Number)) throw new IllegalArgumentException("Invalid render scale");
        double scale = ((Number) scaleValue).doubleValue();
        int maximum = integer(object, "max_buffer_pixel");
        int aa = integer(object, "anti_aliasing");
        int shadow = integer(object, "shadow_resolution");
        if (!contains(QUALITY, quality) || !contains(TARGET_FPS, fps)
                || !contains(RENDER_SCALE, scale) || !contains(MAX_BUFFER_PIXEL, maximum)
                || !contains(ANTI_ALIASING, aa) || !contains(SHADOW_RESOLUTION, shadow)) {
            throw new IllegalArgumentException("Invalid presentation value");
        }
        return new PresentationSettings(((Number) revisionValue).longValue(),
                bool(object, "custom_graphics"), quality, fps, scale, maximum, aa, shadow,
                bool(object, "expand_photography"));
    }

    private static int integer(JSONObject object, String key) throws JSONException {
        Object value = object.get(key);
        if (!(value instanceof Integer || value instanceof Long)) {
            throw new IllegalArgumentException("Invalid integer: " + key);
        }
        long number = ((Number) value).longValue();
        if (number < Integer.MIN_VALUE || number > Integer.MAX_VALUE) {
            throw new IllegalArgumentException("Integer out of range: " + key);
        }
        return (int) number;
    }

    private static boolean bool(JSONObject object, String key) throws JSONException {
        Object value = object.get(key);
        if (!(value instanceof Boolean)) throw new IllegalArgumentException("Invalid boolean: " + key);
        return (Boolean) value;
    }

    private static boolean contains(int[] values, int expected) {
        for (int value : values) if (value == expected) return true;
        return false;
    }

    private static boolean contains(double[] values, double expected) {
        for (double value : values) if (Double.compare(value, expected) == 0) return true;
        return false;
    }

    boolean sameValues(PresentationSettings other) {
        return customGraphics == other.customGraphics && quality == other.quality
                && targetFps == other.targetFps && Double.compare(renderScale, other.renderScale) == 0
                && maxBufferPixel == other.maxBufferPixel && antiAliasing == other.antiAliasing
                && shadowResolution == other.shadowResolution && expandPhotography == other.expandPhotography;
    }

    PresentationSettings save(File filesDirectory) throws IOException {
        if (revision == Long.MAX_VALUE) throw new IOException("Presentation revision exhausted");
        long nextRevision = Math.max(revision + 1, Math.max(0, System.currentTimeMillis()));
        PresentationSettings saved = new PresentationSettings(nextRevision,
                customGraphics, quality, targetFps, renderScale, maxBufferPixel, antiAliasing,
                shadowResolution, expandPhotography);
        JSONObject object = new JSONObject();
        try {
            object.put("schema", 1);
            object.put("revision", saved.revision);
            object.put("custom_graphics", saved.customGraphics);
            object.put("quality", saved.quality);
            object.put("target_fps", saved.targetFps);
            object.put("render_scale", saved.renderScale);
            object.put("max_buffer_pixel", saved.maxBufferPixel);
            object.put("anti_aliasing", saved.antiAliasing);
            object.put("shadow_resolution", saved.shadowResolution);
            object.put("expand_photography", saved.expandPhotography);
        } catch (JSONException error) {
            throw new IOException("Unable to encode presentation settings", error);
        }
        File destination = path(filesDirectory);
        File directory = destination.getParentFile();
        if (!directory.isDirectory() && !directory.mkdirs()) {
            throw new IOException("Unable to create presentation settings directory");
        }
        AtomicFile target = new AtomicFile(destination);
        FileOutputStream output = null;
        try {
            output = target.startWrite();
            output.write(object.toString().getBytes(StandardCharsets.UTF_8));
            target.finishWrite(output);
            return saved;
        } catch (IOException error) {
            if (output != null) target.failWrite(output);
            throw error;
        }
    }
}
