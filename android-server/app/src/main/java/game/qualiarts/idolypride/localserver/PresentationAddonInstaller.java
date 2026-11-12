package game.qualiarts.idolypride.localserver;

import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageInstaller;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import org.json.JSONArray;
import org.json.JSONObject;

/** Adds one bundled feature split to a matching installed game; never supplies a base APK. */
final class PresentationAddonInstaller {
    static final String ACTION_RESULT = "game.qualiarts.idolypride.localserver.PRESENTATION_INSTALL_RESULT";
    static final String EXTRA_REQUESTED_SESSION = "presentation_session_id";
    private static final String PREFS = "presentation_addon_install";
    private static final String MANIFEST_ASSET = "presentation/manifest.json";
    private static final String SPLIT_ID = "idoly_presentation";
    private static final int MAX_APK_BYTES = 1024 * 1024;
    private static final ExecutorService WORKER = Executors.newSingleThreadExecutor();
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final AtomicBoolean PREPARING = new AtomicBoolean();

    static final class Profile {
        final String id;
        final String targetPackage;
        final long baseVersionCode;
        final String certificateSha256;
        final String asset;
        final String apkSha256;
        final long apkBytes;
        final Map<String, String> requiredBaseMembers;

        Profile(JSONObject object) throws Exception {
            id = object.getString("id");
            targetPackage = object.getString("target_package");
            String expectedPackage = "resources".equals(id) ? "game.qualiarts.idolypride.local.resources"
                    : "diagnostics".equals(id) ? "game.qualiarts.idolypride.local.diagnostics" : "";
            if (expectedPackage.isEmpty() || !expectedPackage.equals(targetPackage)) throw new IOException("Profile package mismatch");
            baseVersionCode = object.getLong("base_version_code");
            if (baseVersionCode != 414) throw new IOException("Unsupported base version");
            certificateSha256 = digestValue(object.getString("certificate_sha256"));
            asset = object.getString("asset");
            if (!asset.equals("presentation/" + id + ".apk")) throw new IOException("Unexpected asset path");
            apkSha256 = digestValue(object.getString("apk_sha256"));
            apkBytes = object.getLong("apk_bytes");
            if (apkBytes <= 0 || apkBytes > MAX_APK_BYTES) throw new IOException("Unexpected feature size");
            JSONObject required = object.getJSONObject("required_base_members");
            Map<String, String> hashes = new LinkedHashMap<>();
            for (Iterator<String> keys = required.keys(); keys.hasNext();) {
                String name = keys.next();
                if (!"lib/arm64-v8a/libil2cpp.so".equals(name)
                        && !("diagnostics".equals(id) && ("lib/arm64-v8a/libshadowhook.so".equals(name)
                        || "lib/arm64-v8a/libshadowhook_nothing.so".equals(name)))) {
                    throw new IOException("Unexpected base member");
                }
                hashes.put(name, digestValue(required.getString(name)));
            }
            if (!hashes.containsKey("lib/arm64-v8a/libil2cpp.so")
                    || hashes.size() != ("diagnostics".equals(id) ? 3 : 1)) {
                throw new IOException("Incomplete base compatibility hashes");
            }
            requiredBaseMembers = Collections.unmodifiableMap(hashes);
        }

        int label() {
            return "resources".equals(id) ? R.string.presentation_game_resources : R.string.presentation_game_diagnostics;
        }
    }

    static final class Snapshot {
        final List<Profile> compatible;
        final List<Profile> installed;
        final boolean busy;
        final String state;
        final boolean bundleAvailable;

        Snapshot(List<Profile> compatible, List<Profile> installed, boolean busy, String state, boolean available) {
            this.compatible = Collections.unmodifiableList(compatible);
            this.installed = Collections.unmodifiableList(installed);
            this.busy = busy;
            this.state = state;
            bundleAvailable = available;
        }
    }

    interface Callback { void complete(Snapshot snapshot); }

    static void refresh(Context context, Callback callback) {
        Context app = context.getApplicationContext();
        WORKER.execute(() -> deliver(callback, scan(app)));
    }

    static void install(Context context, Profile requested, Callback callback) {
        Context app = context.getApplicationContext();
        if (!PREPARING.compareAndSet(false, true)) {
            refresh(app, callback);
            return;
        }
        WORKER.execute(() -> {
            try {
                if (hasInstallerSession(app)) throw new IOException("Another installation is active");
                preferences(app).edit().putString("state", "checking").putString("profile", requested.id)
                        .putInt("session_id", -1).commit();
                Profile profile = findProfile(loadProfiles(app), requested.id);
                if (profile == null) throw new IOException("Missing feature profile");
                installVerified(app, profile);
            } catch (Exception error) {
                preferences(app).edit().putString("state", "failed").commit();
            } finally {
                PREPARING.set(false);
            }
            deliver(callback, scan(app));
        });
    }

    private static void installVerified(Context app, Profile profile) throws Exception {
        if (Build.VERSION.SDK_INT < 28 || !app.getPackageManager().canRequestPackageInstalls()) {
            throw new IOException("Installation permission unavailable");
        }
        PackageInfo installed = compatiblePackage(app, profile);
        verifyBaseLibraries(installed, profile);
        File staged = File.createTempFile("presentation-addon-", ".apk", app.getCacheDir());
        PackageInstaller installer = app.getPackageManager().getPackageInstaller();
        int sessionId = -1;
        boolean committed = false;
        try {
            try (InputStream input = app.getAssets().open(profile.asset);
                    FileOutputStream output = new FileOutputStream(staged)) {
                MessageDigest hash = MessageDigest.getInstance("SHA-256");
                long count = copy(input, output, hash, MAX_APK_BYTES);
                output.getFD().sync();
                if (count != profile.apkBytes || !hex(hash.digest()).equals(profile.apkSha256)) {
                    throw new IOException("Bundled feature integrity mismatch");
                }
            }
            // The server APK bundles both this public identity manifest and the
            // exact signed split it hashes. Android verifies the split's actual
            // package, version and signer against the inherited installed base.
            // A feature APK is not a standalone base for getPackageArchiveInfo.
            PackageInstaller.SessionParams params = new PackageInstaller.SessionParams(
                    PackageInstaller.SessionParams.MODE_INHERIT_EXISTING);
            params.setAppPackageName(profile.targetPackage);
            params.setSize(profile.apkBytes);
            if (Build.VERSION.SDK_INT >= 31) {
                params.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_REQUIRED);
            }
            sessionId = installer.createSession(params);
            try (PackageInstaller.Session session = installer.openSession(sessionId);
                    InputStream input = new java.io.FileInputStream(staged)) {
                try (OutputStream output = session.openWrite(SPLIT_ID + ".apk", 0, profile.apkBytes)) {
                    copy(input, output, null, MAX_APK_BYTES);
                    session.fsync(output);
                }
                // Recheck package identity if another installer changed it during hashing.
                PackageInfo current = compatiblePackage(app, profile);
                if (current.lastUpdateTime != installed.lastUpdateTime
                        || !current.applicationInfo.sourceDir.equals(installed.applicationInfo.sourceDir)) {
                    throw new IOException("Installed base changed during verification");
                }
                if (!preferences(app).edit().putInt("session_id", sessionId).putString("profile", profile.id)
                        .putString("state", "submitted").commit()) {
                    throw new IOException("Unable to persist installer callback identity");
                }
                Intent result = new Intent(app, PresentationInstallActivity.class)
                        .setAction(ACTION_RESULT).setData(sessionUri(sessionId))
                        .putExtra(EXTRA_REQUESTED_SESSION, sessionId)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                int flags = PendingIntent.FLAG_UPDATE_CURRENT;
                if (Build.VERSION.SDK_INT >= 31) flags |= PendingIntent.FLAG_MUTABLE;
                PendingIntent callback = PendingIntent.getActivity(app, sessionId, result, flags);
                session.commit(callback.getIntentSender());
                committed = true;
            }
        } finally {
            if (!committed && sessionId >= 0) {
                try { installer.abandonSession(sessionId); } catch (RuntimeException ignored) { }
            }
            staged.delete();
        }
    }

    private static void verifyBaseLibraries(PackageInfo installed, Profile profile) throws Exception {
        // sourceDir is the public base APK. No game data, saves, cache or account files are opened.
        try (ZipFile base = new ZipFile(installed.applicationInfo.sourceDir)) {
            for (Map.Entry<String, String> expected : profile.requiredBaseMembers.entrySet()) {
                ZipEntry entry = base.getEntry(expected.getKey());
                if (entry == null || entry.isDirectory() || entry.getSize() <= 0 || entry.getSize() > 512L * 1024 * 1024) {
                    throw new IOException("Unsupported base library");
                }
                MessageDigest hash = MessageDigest.getInstance("SHA-256");
                try (InputStream input = base.getInputStream(entry)) {
                    copy(input, null, hash, 512L * 1024 * 1024);
                }
                if (!hex(hash.digest()).equals(expected.getValue())) throw new IOException("Base library mismatch");
            }
        }
    }

    private static PackageInfo compatiblePackage(Context app, Profile profile) throws Exception {
        if (Build.VERSION.SDK_INT < 28) throw new IOException("Unsupported Android version");
        PackageInfo installed = app.getPackageManager().getPackageInfo(profile.targetPackage,
                PackageManager.GET_SIGNING_CERTIFICATES);
        if (!profile.targetPackage.equals(installed.packageName)
                || installed.getLongVersionCode() != profile.baseVersionCode || installed.signingInfo == null
                || installed.applicationInfo == null || installed.applicationInfo.sourceDir == null) {
            throw new IOException("Unsupported game package");
        }
        Signature[] signers = installed.signingInfo.getApkContentsSigners();
        if (signers == null || signers.length != 1
                || !hex(MessageDigest.getInstance("SHA-256").digest(signers[0].toByteArray()))
                .equals(profile.certificateSha256)) {
            throw new IOException("Game signer mismatch");
        }
        return installed;
    }

    private static boolean hasSplit(PackageInfo installed) {
        if (installed.splitNames != null) {
            for (String name : installed.splitNames) if (SPLIT_ID.equals(name)) return true;
        }
        return false;
    }

    private static List<Profile> loadProfiles(Context app) throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (InputStream input = app.getAssets().open(MANIFEST_ASSET)) {
            copy(input, bytes, null, 64 * 1024);
        }
        JSONObject manifest = new JSONObject(bytes.toString(StandardCharsets.UTF_8.name()));
        if (manifest.getInt("schema") != 1 || manifest.getInt("bridge_version") != 1
                || !SPLIT_ID.equals(manifest.getString("split_id"))) {
            throw new IOException("Unsupported feature manifest");
        }
        JSONArray records = manifest.getJSONArray("profiles");
        if (records.length() != 2) throw new IOException("Incomplete feature profiles");
        List<Profile> profiles = new ArrayList<>();
        for (int index = 0; index < records.length(); index++) {
            Profile profile = new Profile(records.getJSONObject(index));
            if (findProfile(profiles, profile.id) != null) throw new IOException("Duplicate feature profile");
            profiles.add(profile);
        }
        // Prefer the ordinary resource client; when both exist the UI still asks which one.
        profiles.sort((left, right) -> left.id.equals(right.id) ? 0 : "resources".equals(left.id) ? -1 : 1);
        return profiles;
    }

    private static Snapshot scan(Context app) {
        List<Profile> compatible = new ArrayList<>();
        List<Profile> installed = new ArrayList<>();
        boolean available = false;
        if (Build.VERSION.SDK_INT >= 28) {
            try {
                List<Profile> profiles = loadProfiles(app);
                available = true;
                for (Profile profile : profiles) {
                    try {
                        PackageInfo info = compatiblePackage(app, profile);
                        compatible.add(profile);
                        if (hasSplit(info)) installed.add(profile);
                    } catch (Exception ignored) { }
                }
            } catch (Exception ignored) { }
        }
        boolean busy = PREPARING.get() || hasInstallerSession(app);
        String state = preferences(app).getString("state", "idle");
        if (!busy && ("submitted".equals(state) || "confirmation".equals(state) || "checking".equals(state))) {
            state = "interrupted";
        }
        return new Snapshot(compatible, installed, busy, state, available);
    }

    private static void deliver(Callback callback, Snapshot snapshot) {
        MAIN.post(() -> callback.complete(snapshot));
    }

    private static Profile findProfile(List<Profile> profiles, String id) {
        for (Profile profile : profiles) if (profile.id.equals(id)) return profile;
        return null;
    }

    private static SharedPreferences preferences(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private static boolean hasInstallerSession(Context app) {
        int sessionId = preferences(app).getInt("session_id", -1);
        if (sessionId < 0) return false;
        try { return app.getPackageManager().getPackageInstaller().getSessionInfo(sessionId) != null; }
        catch (RuntimeException ignored) { return false; }
    }

    private static Uri sessionUri(int sessionId) {
        return Uri.parse("idoly-presentation-install://session/" + sessionId);
    }

    static boolean expectedCallback(Context context, Intent intent) {
        int expected = preferences(context).getInt("session_id", -1);
        return expected >= 0 && intent != null && ACTION_RESULT.equals(intent.getAction())
                && intent.getIntExtra(EXTRA_REQUESTED_SESSION, -1) == expected
                && sessionUri(expected).equals(intent.getData());
    }

    static void confirmationRequested(Context context) {
        preferences(context).edit().putString("state", "confirmation").apply();
    }

    static void completeInstall(Context context, int sessionId, int status, Callback callback) {
        Context app = context.getApplicationContext();
        WORKER.execute(() -> {
            if (preferences(app).getInt("session_id", -1) != sessionId) {
                deliver(callback, scan(app));
                return;
            }
            boolean success = false;
            if (status == PackageInstaller.STATUS_SUCCESS) {
                try {
                    Profile profile = findProfile(loadProfiles(app), preferences(app).getString("profile", ""));
                    success = profile != null && hasSplit(compatiblePackage(app, profile));
                } catch (Exception ignored) { }
            }
            preferences(app).edit().putString("state", success ? "installed" : "failed")
                    .putInt("session_id", -1).putInt("result_code", status).commit();
            deliver(callback, scan(app));
        });
    }

    private static String digestValue(String value) throws IOException {
        if (!value.matches("[0-9a-f]{64}")) throw new IOException("Invalid SHA-256");
        return value;
    }

    private static long copy(InputStream input, OutputStream output, MessageDigest hash, long maximum) throws IOException {
        byte[] buffer = new byte[32 * 1024];
        long total = 0;
        int count;
        while ((count = input.read(buffer)) != -1) {
            total += count;
            if (total > maximum) throw new IOException("Public artifact exceeds expected size");
            if (output != null) output.write(buffer, 0, count);
            if (hash != null) hash.update(buffer, 0, count);
        }
        return total;
    }

    private static String hex(byte[] bytes) {
        StringBuilder result = new StringBuilder(bytes.length * 2);
        for (byte value : bytes) result.append(String.format(java.util.Locale.ROOT, "%02x", value & 0xff));
        return result.toString();
    }
}
