package game.qualiarts.idolypride.localserver;

import android.content.Context;
import org.json.JSONObject;
import java.io.File;

/** Optional same-process bridge; no credentials or public storage paths cross it. */
public final class UnifiedSharedResources {
    private static volatile boolean configured;
    private UnifiedSharedResources() {}

    public static native boolean configure(String directory, long epoch);
    public static native String status();

    static boolean prepare(Context context, String descriptor) {
        if (!UnifiedRuntime.isEnabled(context)) return false;
        try {
            JSONObject value = new JSONObject(descriptor);
            if (value.getInt("schema") != 1 || !value.getBoolean("available")) return false;
            long epoch = value.getLong("epoch");
            File root = context.getFilesDir().getCanonicalFile();
            File directory = new File(value.getString("directory"));
            File canonical = directory.getCanonicalFile();
            if (epoch < 1 || !canonical.equals(directory) || !canonical.isDirectory()
                    || !canonical.getPath().startsWith(root.getPath() + File.separator)) return false;
            System.loadLibrary("idoly_presentation");
            configured = configure(canonical.getPath(), epoch);
            return configured;
        } catch (Exception | LinkageError unavailable) {
            configured = false;
            return false;
        }
    }

    static boolean configured() { return configured; }

    static JSONObject snapshot() {
        try {
            if (configured) {
                String raw = status();
                if (raw != null && raw.length() <= 4096) return new JSONObject(raw);
            }
        } catch (Exception | LinkageError unavailable) { /* Optional bridge only. */ }
        JSONObject value = new JSONObject();
        try { value.put("available", false); }
        catch (org.json.JSONException impossible) { throw new IllegalStateException(impossible); }
        return value;
    }
}
