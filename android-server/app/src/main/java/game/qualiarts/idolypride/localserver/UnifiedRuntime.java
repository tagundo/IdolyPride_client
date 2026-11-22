package game.qualiarts.idolypride.localserver;

import android.content.Context;
import android.content.Intent;
import android.content.res.Resources;
import android.os.Build;
import android.os.ParcelFileDescriptor;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Collections;
import java.util.Set;
import java.util.WeakHashMap;

/** Optional same-UID host. Ordinary standalone installations have no marker. */
public final class UnifiedRuntime {
    static final String MARKER = "idoly-unified.json";
    static final String PACKAGE = "game.qualiarts.idolypride.local.diagnostics";
    static final String GAME = "game.qualiarts.idolypride.localserver.UnifiedGameActivity";
    static final String ORIGINAL_GAME = "com.google.firebase.MessagingUnityPlayerActivity";
    static final String EXPECTED_LANGUAGE = "idoly_unified_expected_language";
    private static final int MAX_MARKER = 32768;
    private static final int MAX_RESOURCES = 4 * 1024 * 1024;
    private static JSONObject cached;
    private static boolean inspected;

    private UnifiedRuntime() {}

    private static IllegalStateException invalid(String code) {
        return new IllegalStateException(code);
    }

    private static boolean language(String value) {
        return "ja".equals(value) || "ko".equals(value) || "en".equals(value);
    }

    private static byte[] bounded(InputStream input, int maximum) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        byte[] buffer = new byte[4096];
        int count;
        while ((count = input.read(buffer)) != -1) {
            if (bytes.size() + count > maximum) throw new IOException("unified_asset_bound");
            bytes.write(buffer, 0, count);
        }
        return bytes.toByteArray();
    }

    private static synchronized JSONObject marker(Context context) {
        if (inspected) return cached;
        try (InputStream input = context.getAssets().open(MARKER)) {
            JSONObject value = new JSONObject(new String(bounded(input, MAX_MARKER), StandardCharsets.UTF_8));
            if (!Integer.valueOf(1).equals(value.get("schema")) || !Boolean.TRUE.equals(value.get("prototype"))
                    || !PACKAGE.equals(value.getString("package")) || !PACKAGE.equals(context.getPackageName())
                    || !GAME.equals(value.getString("game_activity"))
                    || !ORIGINAL_GAME.equals(value.getString("original_game_activity"))
                    || !Integer.valueOf(30).equals(value.get("min_sdk"))
                    || !"same".equals(value.getString("process_mode"))) throw invalid("unified_marker_invalid");
            JSONArray languages = value.getJSONArray("languages");
            Set<String> seen = new java.util.HashSet<>();
            for (int index = 0; index < languages.length(); ++index) {
                Object item = languages.get(index);
                if (!(item instanceof String) || !language((String) item) || !seen.add((String) item))
                    throw invalid("unified_languages_invalid");
            }
            if (seen.isEmpty() || seen.size() > 3 || !seen.contains(value.getString("default_language")))
                throw invalid("unified_languages_invalid");
            JSONObject pack = value.getJSONObject("resource_pack");
            if (!"idoly-unified/server-resources.apk".equals(pack.getString("asset"))
                    || !pack.getString("sha256").matches("[0-9a-f]{64}")
                    || pack.getLong("bytes") < 1 || pack.getLong("bytes") > MAX_RESOURCES
                    || !Integer.valueOf(126).equals(pack.get("package_id"))) throw invalid("unified_resource_identity_invalid");
            cached = value;
            inspected = true;
            return cached;
        } catch (FileNotFoundException absent) {
            inspected = true;
            return null;
        } catch (Exception failure) {
            if (failure instanceof IllegalStateException) throw (IllegalStateException) failure;
            throw invalid("unified_marker_invalid");
        }
    }

    public static boolean isEnabled(Context context) { return marker(context) != null; }

    /** Shared canonical objects need the app filesystem's stable inode/mode semantics. */
    public static File resourceDirectory(Context context, File standaloneDirectory) {
        return isEnabled(context) ? new File(context.getFilesDir(), "IdolyPrideResources") : standaloneDirectory;
    }

    /** A copy prevents consumers from changing the validated marker shared by the host. */
    static JSONObject configuration(Context context) {
        JSONObject value = marker(context);
        if (value == null) throw invalid("unified_marker_missing");
        try { return new JSONObject(value.toString()); }
        catch (Exception impossible) { throw invalid("unified_marker_invalid"); }
    }

    private static StructStat regular(File path) throws Exception {
        StructStat info = Os.lstat(path.getAbsolutePath());
        if (!OsConstants.S_ISREG(info.st_mode) || info.st_nlink != 1 || info.st_size < 1
                || info.st_size > MAX_RESOURCES) throw invalid("unified_resource_file_invalid");
        return info;
    }

    private static String hash(File path) throws Exception {
        StructStat before = regular(path);
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = new FileInputStream(path)) {
            byte[] buffer = new byte[32768];
            int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        StructStat after = regular(path);
        if (before.st_dev != after.st_dev || before.st_ino != after.st_ino || before.st_size != after.st_size
                || before.st_mtime != after.st_mtime || before.st_ctime != after.st_ctime)
            throw invalid("unified_resource_changed");
        StringBuilder result = new StringBuilder(64);
        for (byte value : digest.digest()) result.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
        return result.toString();
    }

    private static File resourceFile(Context context, JSONObject value) throws Exception {
        JSONObject pack = value.getJSONObject("resource_pack");
        String expected = pack.getString("sha256");
        // Android's trusted app root can use /data/user/0 while its canonical
        // path uses /data/data. Normalize that root before checking our child;
        // an existing child symlink must still fail the checks below.
        File cacheRoot = context.getCodeCacheDir().getCanonicalFile();
        File directory = new File(cacheRoot, "idoly-unified-resources");
        if (!directory.isDirectory() && !directory.mkdirs()) throw invalid("unified_resource_directory_invalid");
        if (!directory.getCanonicalFile().equals(directory.getAbsoluteFile())
                || !OsConstants.S_ISDIR(Os.lstat(directory.getAbsolutePath()).st_mode))
            throw invalid("unified_resource_directory_invalid");
        File target = new File(directory, expected + ".apk");
        if (target.exists()) {
            if (target.length() != pack.getLong("bytes") || !expected.equals(hash(target)))
                throw invalid("unified_resource_hash_differs");
            return target;
        }
        File temporary = File.createTempFile(".resource-", ".part", directory);
        try {
            try (InputStream input = context.getAssets().open(pack.getString("asset"));
                 FileOutputStream output = new FileOutputStream(temporary)) {
                byte[] buffer = new byte[32768];
                long total = 0;
                int count;
                while ((count = input.read(buffer)) != -1) {
                    total += count;
                    if (total > pack.getLong("bytes")) throw invalid("unified_resource_size_differs");
                    output.write(buffer, 0, count);
                }
                output.getFD().sync();
                if (total != pack.getLong("bytes")) throw invalid("unified_resource_size_differs");
            }
            if (!expected.equals(hash(temporary))) throw invalid("unified_resource_hash_differs");
            if (target.exists() || !temporary.renameTo(target)) throw invalid("unified_resource_publish_failed");
            return target;
        } finally {
            if (temporary.exists() && !temporary.delete()) temporary.deleteOnExit();
        }
    }

    public static synchronized void installResources(Context context) {
        JSONObject value = marker(context);
        if (value == null) return;
        if (Build.VERSION.SDK_INT < 30) throw invalid("unified_requires_android_11");
        try {
            File file = resourceFile(context, value);
            Api30.attach(context.getResources(), file);
            Api30.attach(context.getApplicationContext().getResources(), file);
            File languageFile = new File(new File(context.getFilesDir(), "data"), "client-language.json");
            if (!languageFile.exists() && !new File(languageFile + ".bak").exists())
                LibrarySettings.defaults().changedLanguage(value.getString("default_language")).saveLanguage(context.getFilesDir());
        } catch (Exception failure) {
            if (failure instanceof IllegalStateException) throw (IllegalStateException) failure;
            throw invalid("unified_resource_prepare_failed");
        }
    }

    public static Intent launchIntent(Context context) {
        JSONObject value = marker(context);
        if (value == null) return null;
        try {
            LibrarySettings.Loaded loaded = LibrarySettings.load(context.getFilesDir());
            if (loaded.invalidLanguage) throw invalid("unified_language_invalid");
            JSONArray languages = value.getJSONArray("languages");
            boolean found = false;
            for (int index = 0; index < languages.length(); ++index)
                found |= loaded.settings.language.equals(languages.getString(index));
            if (!found) throw invalid("unified_language_mismatch");
            Intent result = new Intent(Intent.ACTION_MAIN)
                    .setClassName(context.getPackageName(), value.getString("game_activity"))
                    .addCategory(Intent.CATEGORY_LAUNCHER).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            // The old Firebase component is an alias to the server menu. Keep
            // its deep-link/notification payload until the user starts Unity;
            // component, selector, ClipData and caller flags are never copied.
            if (context instanceof android.app.Activity)
                copyLaunchPayload(result, ((android.app.Activity) context).getIntent());
            result.putExtra(EXPECTED_LANGUAGE, loaded.settings.language);
            return result;
        } catch (Exception failure) {
            if (failure instanceof IllegalStateException) throw (IllegalStateException) failure;
            throw invalid("unified_game_launch_invalid");
        }
    }

    static void copyLaunchPayload(Intent result, Intent incoming) {
        if (incoming == null) return;
        result.setAction(incoming.getAction());
        result.setDataAndType(incoming.getData(), incoming.getType());
        if (incoming.getExtras() != null) result.putExtras(incoming.getExtras());
        if (incoming.getCategories() != null)
            for (String category : incoming.getCategories()) result.addCategory(category);
    }

    static String expectedLanguage(Intent intent) {
        try {
            String selected = intent == null ? null : intent.getStringExtra(EXPECTED_LANGUAGE);
            return language(selected) ? selected : null;
        } catch (RuntimeException malformed) { return null; }
    }

    public static int notificationIcon(Context context, int ordinary) {
        if (marker(context) == null) return ordinary;
        int icon = context.getApplicationInfo().icon;
        if ((icon >>> 24) != 0x7f) throw invalid("unified_installed_icon_invalid");
        return icon;
    }

    private static final class Api30 {
        private static android.content.res.loader.ResourcesLoader loader;
        private static final Set<Resources> attached = Collections.newSetFromMap(new WeakHashMap<>());
        static void attach(Resources resources, File file) throws IOException {
            if (loader == null) {
                try (ParcelFileDescriptor descriptor = ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)) {
                    android.content.res.loader.ResourcesProvider provider =
                            android.content.res.loader.ResourcesProvider.loadFromApk(descriptor);
                    loader = new android.content.res.loader.ResourcesLoader();
                    loader.addProvider(provider);
                }
            }
            if (!attached.contains(resources)) {
                resources.addLoaders(loader);
                attached.add(resources);
            }
        }
    }
}
