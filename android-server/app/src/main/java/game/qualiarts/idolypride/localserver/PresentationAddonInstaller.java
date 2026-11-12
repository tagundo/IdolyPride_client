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
import android.widget.Toast;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.json.JSONArray;
import org.json.JSONObject;

/** Updates from installed public APKs, or optionally inherits a feature-only update. */
final class PresentationAddonInstaller {
    static final String ACTION_RESULT = "game.qualiarts.idolypride.localserver.PRESENTATION_INSTALL_RESULT";
    static final String EXTRA_REQUESTED_SESSION = "presentation_session_id";
    static final String EXTRA_LEGACY_STATUS = "android.content.pm.extra.LEGACY_STATUS";
    private static final String PREFS = "presentation_addon_install";
    private static final String MANIFEST_ASSET = "presentation/manifest.json";
    private static final String SPLIT_ID = "idoly_presentation";
    private static final String STANDALONE_MARKER = "assets/idoly-presentation-standalone.json";
    private static final String PRESENTATION_NATIVE_SHA256 = "7a68c1be9a65b71cd3d56ce56c737fe3823438324746ec78feb436bc5ecbca6d";
    private static final int MAX_APK_BYTES = 1024 * 1024;
    private static final ExecutorService WORKER = Executors.newSingleThreadExecutor();
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final AtomicBoolean PREPARING = new AtomicBoolean();

    /** Closed, bounded public diagnostics. Never stores Throwable.getMessage() or raw OS text. */
    static final class Failure {
        final String stage, reason, exceptionClass, member, expectedSha, actualSha, installToken;
        final String category, osMessage, errno;
        final int status, legacyStatus;
        final long timeMs;

        Failure(String stage, String reason, String exceptionClass, String member, String expectedSha,
                String actualSha, String installToken, int status, int legacyStatus, long timeMs) {
            this(stage, reason, exceptionClass, member, expectedSha, actualSha, installToken, status,
                    legacyStatus, timeMs, "", "");
        }

        Failure(String stage, String reason, String exceptionClass, String member, String expectedSha,
                String actualSha, String installToken, int status, int legacyStatus, long timeMs,
                String osMessage, String errno) {
            this.stage = stage;
            this.reason = reason;
            this.exceptionClass = exceptionClass;
            this.member = member;
            this.expectedSha = expectedSha;
            this.actualSha = actualSha;
            this.installToken = installToken;
            this.status = status;
            this.legacyStatus = legacyStatus;
            this.timeMs = Math.max(0, timeMs);
            category = "storage_or_io_error".equals(reason) || "storage_insufficient".equals(reason)
                    ? "storage_or_io_error" : FailurePolicy.category(status, legacyStatus, installToken);
            this.osMessage = osMessage;
            this.errno = errno;
        }
    }

    // Pure Java so the redaction and bounded failure policy can run on the host without Android.
    static final class FailurePolicy {
        static final int NO_STATUS = Integer.MIN_VALUE;
        private static final Pattern INSTALL_TOKEN = Pattern.compile(
                "(?<![A-Za-z0-9_])INSTALL_[A-Z_]{1,64}(?![A-Za-z0-9_])");

        static String stage(String value) {
            switch (value == null ? "" : value) {
                case "preflight": case "manifest": case "compatibility": case "base_hash":
                case "asset_copy": case "asset_hash": case "session_create": case "session_write":
                case "session_recheck": case "session_bind": case "session_commit": case "callback":
                case "confirmation": case "post_install": case "session_state": case "permission":
                case "existing_apk_copy": case "android_result":
                    return value;
                default: return "unknown";
            }
        }

        static String reason(String value) {
            switch (value == null ? "" : value) {
                case "active_session": case "missing_profile": case "android_unsupported":
                case "permission_unavailable": case "package_missing": case "package_identity_mismatch":
                case "version_mismatch": case "signer_mismatch": case "base_member_missing":
                case "base_member_invalid": case "base_hash_mismatch": case "asset_size_mismatch":
                case "asset_hash_mismatch": case "base_changed": case "callback_persist_failed":
                case "os_rejected": case "confirmation_missing": case "confirmation_start_failed":
                case "stale_session": case "session_interrupted": case "session_query_failed":
                case "split_missing": case "artifact_too_large": case "operation_failed":
                case "callback_status_missing": case "native_library_extract_failed": case "abi_mismatch":
                case "storage_insufficient": case "user_rejected":
                case "split_layout_mismatch": case "existing_apk_missing": case "existing_apk_unreadable":
                case "existing_apk_size_limit": case "existing_apk_count_limit": case "existing_apk_name_invalid":
                case "existing_apk_duplicate": case "existing_apk_copy_mismatch": case "existing_apk_changed":
                case "existing_apk_total_limit":
                case "storage_or_io_error": case "inherit_failed": case "digest_store_failed": case "rename_failed":
                    return value;
                default: return "unknown";
            }
        }

        static String exceptionClass(String value) {
            switch (value == null ? "" : value) {
                case "IOException": case "FileNotFoundException": case "EOFException":
                case "SecurityException": case "IllegalArgumentException": case "IllegalStateException":
                case "NameNotFoundException": case "JSONException": case "ZipException":
                case "NoSuchAlgorithmException": case "ActivityNotFoundException": case "none":
                    return value;
                default: return "OtherException";
            }
        }

        static String publicMember(String value) {
            if (value == null) return "";
            switch (value) {
                case "lib/arm64-v8a/libil2cpp.so": case "libil2cpp.so": return "libil2cpp.so";
                case "lib/arm64-v8a/libshadowhook.so": case "libshadowhook.so": return "libshadowhook.so";
                case "lib/arm64-v8a/libshadowhook_nothing.so": case "libshadowhook_nothing.so": return "libshadowhook_nothing.so";
                default: return "";
            }
        }

        static String shortSha(String value) {
            return value != null && value.matches("[0-9a-f]{64}") ? value.substring(0, 12) : "";
        }

        static String installToken(String message) {
            if (message == null) return "";
            // Bound work even when Android supplies an unexpectedly large message.
            int limit = Math.min(4096, message.length());
            Matcher match = INSTALL_TOKEN.matcher(message.substring(0, limit));
            if (!match.find() || (match.end() == limit && message.length() > limit)) return "";
            return match.group();
        }

        static String osReason(String message) {
            return osReason(NO_STATUS, NO_STATUS, message);
        }

        static String category(int status, int legacyStatus, String token) {
            return status == 6 || legacyStatus == -4 || "INSTALL_FAILED_INSUFFICIENT_STORAGE".equals(token)
                    ? "storage_or_io_error" : "installation_error";
        }

        static String osReason(int status, int legacyStatus, String message) {
            String text = message == null ? "" : message.substring(0, Math.min(4096, message.length()))
                    .toLowerCase(java.util.Locale.ROOT);
            if (text.contains("failed to inherit") || text.contains("failed to link")) return "inherit_failed";
            if (text.contains("failed to store digest") || text.contains("failed to write digest")) return "digest_store_failed";
            if (text.contains("failed to rename")) return "rename_failed";
            if (text.contains("failed to extract native libraries")) return "native_library_extract_failed";
            if (text.contains("no matching abi")) return "abi_mismatch";
            if (text.contains("insufficient storage")) return "storage_or_io_error";
            if (text.contains("signatures do not match") || text.contains("inconsistent certificates")) return "signer_mismatch";
            if (text.contains("user rejected") || text.contains("user canceled") || text.contains("user cancelled")) return "user_rejected";
            return "storage_or_io_error".equals(category(status, legacyStatus, installToken(message)))
                    ? "storage_or_io_error" : "os_rejected";
        }

        static String errno(String message) {
            if (message == null) return "";
            Matcher match = Pattern.compile("\\b(?:ENOSPC|EACCES|EPERM|EXDEV|EIO|ENOENT|EROFS|ENOMEM|EMFILE|ENFILE|EDQUOT|EEXIST|EINVAL|ENOTDIR|EISDIR|ENOTEMPTY|ETXTBSY)\\b")
                    .matcher(message.substring(0, Math.min(4096, message.length())));
            return match.find() ? match.group() : "";
        }

        static String redactMessage(String message) {
            if (message == null) return "";
            String text = message.substring(0, Math.min(4096, message.length()))
                    .replaceAll("[\\p{Cc}\\p{Cf}]", " ");
            text = text.replaceAll("(?i)\\b[a-z][a-z0-9+.-]{1,20}://[^\\s<>\"']+", "[URI]");
            text = text.replaceAll("\"/[^\"]*\"|'/.+?'", "[path]");
            text = text.replaceAll("(?<![A-Za-z0-9_])/(?:[^\\s,;:()\\[\\]{}<>\"']+)", "[path]");
            text = text.replaceAll("(?i)\\b[A-Z]:\\\\[^\\s,;()\\[\\]{}<>\"']+", "[path]");
            text = text.replaceAll("(?i)\\b(?:Bearer|Basic)\\s+[^\\s,;]+", "[credential]");
            text = text.replaceAll("(?i)\\b(?:access[_-]?token|refresh[_-]?token|token|password|passwd|authorization|auth|secret|credential|api[_-]?key|session[_-]?id)\\b\\s*[:=]\\s*(?:\"[^\"]*\"|'[^']*'|[^\\s,;]+)", "[credential]");
            text = text.replaceAll("\\beyJ[A-Za-z0-9_-]{4,}\\.[A-Za-z0-9_-]{4,}\\.[A-Za-z0-9_-]{4,}\\b", "[token]");
            text = text.replaceAll("(?<![A-Za-z0-9_+/=.-])(?!INSTALL_)[A-Za-z0-9_+/=-]{24,}(?![A-Za-z0-9_+/=.-])", "[token]");
            text = text.replaceAll("\\b[^\\s@]+@[^\\s@]+\\.[^\\s@]+", "[account]");
            text = text.replaceAll("\\s+", " ").trim();
            return text.substring(0, Math.min(512, text.length()));
        }

        static Failure make(String stage, String reason, Throwable error, String member,
                String expected, String actual, int status, int legacyStatus, String osMessage) {
            return new Failure(stage(stage), reason(reason), exceptionClass(error == null
                    ? "none" : error.getClass().getSimpleName()), publicMember(member), shortSha(expected),
                    shortSha(actual), installToken(osMessage), status, legacyStatus, System.currentTimeMillis(),
                    redactMessage(osMessage), errno(osMessage));
        }
    }

    private static final class InstallFailure extends IOException {
        final Failure failure;
        InstallFailure(Failure failure) { super(failure.reason); this.failure = failure; }
    }

    private static final class Attempt { String stage = "preflight"; }

    /** Pure public-file bounds and entry-name policy, also exercised by host tests. */
    static final class ExistingApkPolicy {
        static final int MAX_SPLITS = 32;
        static final long MAX_FILE_BYTES = 256L * 1024 * 1024;
        static final long MAX_TOTAL_BYTES = 512L * 1024 * 1024;

        static String sessionName(String split) {
            if (split == null || !split.matches("[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}")
                    || split.contains("..")) return null;
            return "split_" + split + ".apk";
        }

        static boolean validFileSize(long bytes) { return bytes > 0 && bytes <= MAX_FILE_BYTES; }

        static long addSize(long total, long bytes) {
            return validFileSize(bytes) && total >= 0 && total <= MAX_TOTAL_BYTES
                    && bytes <= MAX_TOTAL_BYTES - total ? total + bytes : -1;
        }

        static ExistingPlan plan(String basePath, String[] names, String[] paths, long featureBytes)
                throws ExistingApkException {
            return create(basePath, names, paths, featureBytes, true);
        }

        static ExistingPlan inventory(String basePath, String[] names, String[] paths, long featureBytes)
                throws ExistingApkException {
            return create(basePath, names, paths, featureBytes, false);
        }

        private static ExistingPlan create(String basePath, String[] names, String[] paths, long featureBytes,
                boolean copyExisting) throws ExistingApkException {
            String[] splitNames = names == null ? new String[0] : names.clone();
            String[] splitPaths = paths == null ? new String[0] : paths.clone();
            if (splitNames.length != splitPaths.length) throw new ExistingApkException("split_layout_mismatch");
            if (splitNames.length > MAX_SPLITS) throw new ExistingApkException("existing_apk_count_limit");
            List<ExistingApk> files = new ArrayList<>();
            if (basePath == null || basePath.isEmpty()) throw new ExistingApkException("existing_apk_missing");
            if (copyExisting) files.add(new ExistingApk("base.apk", basePath));
            HashSet<String> uniqueNames = new HashSet<>();
            HashSet<String> uniquePaths = new HashSet<>();
            uniquePaths.add(basePath);
            for (int index = 0; index < splitNames.length; index++) {
                String name = sessionName(splitNames[index]);
                if (name == null) throw new ExistingApkException("existing_apk_name_invalid");
                if (splitPaths[index] == null || splitPaths[index].isEmpty()) throw new ExistingApkException("existing_apk_missing");
                if (!uniqueNames.add(name) || !uniquePaths.add(splitPaths[index])) throw new ExistingApkException("existing_apk_duplicate");
                if (copyExisting && !"idoly_presentation".equals(splitNames[index])) files.add(new ExistingApk(name, splitPaths[index]));
            }
            if (featureBytes <= 0 || featureBytes > 1024 * 1024) throw new ExistingApkException("existing_apk_total_limit");
            long total = featureBytes;
            for (ExistingApk file : files) {
                total = addSize(total, file.bytes);
                if (total < 0) throw new ExistingApkException("existing_apk_total_limit");
            }
            return new ExistingPlan(basePath, splitNames, splitPaths, files, total);
        }
    }

    static final class ExistingApkException extends IOException {
        final String reason;
        ExistingApkException(String reason) { this.reason = reason; }
    }

    static final class ExistingApk {
        final String sessionName;
        final File file;
        final long bytes;
        final long modified;

        ExistingApk(String sessionName, String path) throws ExistingApkException {
            this.sessionName = sessionName;
            if (path == null || path.isEmpty()) throw new ExistingApkException("existing_apk_missing");
            file = new File(path);
            if (!file.isFile()) throw new ExistingApkException("existing_apk_missing");
            if (!file.canRead()) throw new ExistingApkException("existing_apk_unreadable");
            bytes = file.length();
            modified = file.lastModified();
            if (!ExistingApkPolicy.validFileSize(bytes)) throw new ExistingApkException("existing_apk_size_limit");
        }

        boolean unchanged() {
            return file.isFile() && file.canRead() && file.length() == bytes && file.lastModified() == modified;
        }
    }

    static final class ExistingPlan {
        private final String basePath;
        private final String[] splitNames;
        private final String[] splitPaths;
        final List<ExistingApk> files;
        final long sessionBytes;

        ExistingPlan(String basePath, String[] splitNames, String[] splitPaths, List<ExistingApk> files, long bytes) {
            this.basePath = basePath;
            this.splitNames = splitNames.clone();
            this.splitPaths = splitPaths.clone();
            this.files = Collections.unmodifiableList(new ArrayList<>(files));
            sessionBytes = bytes;
        }

        boolean samePaths(String currentBase, String[] currentNames, String[] currentPaths) {
            return basePath.equals(currentBase)
                    && Arrays.equals(splitNames, currentNames == null ? new String[0] : currentNames)
                    && Arrays.equals(splitPaths, currentPaths == null ? new String[0] : currentPaths);
        }
    }

    private static final class ExistingSet {
        final ExistingPlan plan;
        final long lastUpdateTime;
        final List<ExistingApk> files;
        final long sessionBytes;

        ExistingSet(PackageInfo info, long featureBytes, boolean featureOnly) throws InstallFailure {
            lastUpdateTime = info.lastUpdateTime;
            try {
                plan = featureOnly ? ExistingApkPolicy.inventory(info.applicationInfo.sourceDir, info.splitNames,
                        info.applicationInfo.splitSourceDirs, featureBytes) : ExistingApkPolicy.plan(
                        info.applicationInfo.sourceDir, info.splitNames, info.applicationInfo.splitSourceDirs, featureBytes);
            } catch (ExistingApkException error) {
                throw failure("existing_apk_copy", error.reason);
            }
            files = plan.files;
            sessionBytes = plan.sessionBytes;
        }

        boolean matches(PackageInfo current) {
            return current.lastUpdateTime == lastUpdateTime && plan.samePaths(current.applicationInfo.sourceDir,
                    current.splitNames, current.applicationInfo.splitSourceDirs);
        }
    }

    private static InstallFailure failure(String stage, String reason) {
        return new InstallFailure(FailurePolicy.make(stage, reason, null, null, null, null,
                FailurePolicy.NO_STATUS, FailurePolicy.NO_STATUS, null));
    }

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
        final Failure failure;
        final String profile;
        final boolean featureOnly;
        final List<PresentationStorage.Estimate> storage;

        Snapshot(List<Profile> compatible, List<Profile> installed, boolean busy, String state, boolean available,
                Failure failure, String profile, boolean featureOnly, List<PresentationStorage.Estimate> storage) {
            this.compatible = Collections.unmodifiableList(compatible);
            this.installed = Collections.unmodifiableList(installed);
            this.busy = busy;
            this.state = state;
            bundleAvailable = available;
            this.failure = failure;
            this.profile = profile;
            this.featureOnly = featureOnly;
            this.storage = Collections.unmodifiableList(new ArrayList<>(storage));
        }
    }

    interface Callback { void complete(Snapshot snapshot); }

    static void refresh(Context context, Callback callback) {
        Context app = context.getApplicationContext();
        WORKER.execute(() -> deliver(callback, scan(app)));
    }

    static boolean featureOnly(Context context) {
        return preferences(context).getBoolean("feature_only", false);
    }

    static void setFeatureOnly(Context context, boolean enabled) {
        preferences(context).edit().putBoolean("feature_only", enabled).apply();
    }

    static void install(Context context, Profile requested, boolean featureOnly, Callback callback) {
        Context app = context.getApplicationContext();
        if (!PREPARING.compareAndSet(false, true)) {
            refresh(app, callback);
            return;
        }
        WORKER.execute(() -> {
            Attempt attempt = new Attempt();
            try {
                if (hasInstallerSession(app)) throw failure("preflight", "active_session");
                clearFailure(preferences(app).edit()).putString("state", "checking").putString("profile", requested.id)
                        .putBoolean("attempt_feature_only", featureOnly)
                        .putString("attempt_mode", featureOnly ? "feature_only_inherit" : "full_update")
                        .putInt("session_id", -1).commit();
                attempt.stage = "manifest";
                Profile profile = findProfile(loadProfiles(app), requested.id);
                if (profile == null) throw failure("manifest", "missing_profile");
                installVerified(app, profile, featureOnly, attempt);
            } catch (Exception error) {
                storeFailure(app, error instanceof InstallFailure ? ((InstallFailure) error).failure
                        : FailurePolicy.make(attempt.stage, "operation_failed", error, null, null, null,
                        FailurePolicy.NO_STATUS, FailurePolicy.NO_STATUS, null));
                preferences(app).edit().putString("state", "failed").commit();
            } finally {
                PREPARING.set(false);
            }
            deliver(callback, scan(app));
        });
    }

    private static void installVerified(Context app, Profile profile, boolean featureOnly, Attempt attempt) throws Exception {
        if (Build.VERSION.SDK_INT < 28) throw failure("preflight", "android_unsupported");
        if (!app.getPackageManager().canRequestPackageInstalls()) throw failure("permission", "permission_unavailable");
        attempt.stage = "compatibility";
        PackageInfo installed = compatiblePackage(app, profile);
        if (hasStandalonePresentation(installed)) {
            clearFailure(preferences(app).edit()).putString("state", "installed").putInt("session_id", -1).commit();
            MAIN.post(() -> Toast.makeText(app, R.string.presentation_install_already_included,
                    Toast.LENGTH_LONG).show());
            return;
        }
        attempt.stage = "base_hash";
        verifyBaseLibraries(installed, profile);
        attempt.stage = "existing_apk_copy";
        ExistingSet existing = new ExistingSet(installed, profile.apkBytes, featureOnly);
        attempt.stage = "asset_copy";
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
                attempt.stage = "asset_hash";
                if (count != profile.apkBytes) throw failure("asset_hash", "asset_size_mismatch");
                if (!hex(hash.digest()).equals(profile.apkSha256)) throw failure("asset_hash", "asset_hash_mismatch");
            }
            // The server APK bundles both this public identity manifest and the
            // exact signed split it hashes. Android verifies the split's actual
            // package, version and signer against the inherited installed base.
            // A feature APK is not a standalone base for getPackageArchiveInfo.
            PackageInstaller.SessionParams params = new PackageInstaller.SessionParams(
                    featureOnly ? PackageInstaller.SessionParams.MODE_INHERIT_EXISTING
                            : PackageInstaller.SessionParams.MODE_FULL_INSTALL);
            params.setAppPackageName(profile.targetPackage);
            params.setSize(existing.sessionBytes);
            if (Build.VERSION.SDK_INT >= 31) {
                params.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_REQUIRED);
            }
            attempt.stage = "session_create";
            sessionId = installer.createSession(params);
            attempt.stage = "session_write";
            try (PackageInstaller.Session session = installer.openSession(sessionId);
                    InputStream input = new java.io.FileInputStream(staged)) {
                try (OutputStream output = session.openWrite(SPLIT_ID + ".apk", 0, profile.apkBytes)) {
                    if (copy(input, output, null, MAX_APK_BYTES) != profile.apkBytes)
                        throw failure("session_write", "asset_size_mismatch");
                    session.fsync(output);
                }
                if (!featureOnly) {
                    attempt.stage = "existing_apk_copy";
                    preferences(app).edit().putString("state", "copying_existing").commit();
                }
                for (ExistingApk apk : existing.files) {
                    if (!apk.unchanged()) throw failure("existing_apk_copy", "existing_apk_changed");
                    try (InputStream installedInput = new java.io.FileInputStream(apk.file);
                            OutputStream output = session.openWrite(apk.sessionName, 0, apk.bytes)) {
                        if (copy(installedInput, output, null, ExistingApkPolicy.MAX_FILE_BYTES) != apk.bytes)
                            throw failure("existing_apk_copy", "existing_apk_copy_mismatch");
                        session.fsync(output);
                    }
                    if (!apk.unchanged()) throw failure("existing_apk_copy", "existing_apk_changed");
                }
                // Recheck package identity if another installer changed it during hashing.
                attempt.stage = "session_recheck";
                PackageInfo current = compatiblePackage(app, profile);
                if (!existing.matches(current)) throw failure("session_recheck", "base_changed");
                for (ExistingApk apk : existing.files)
                    if (!apk.unchanged()) throw failure("session_recheck", "existing_apk_changed");
                attempt.stage = "session_bind";
                if (!preferences(app).edit().putInt("session_id", sessionId).putString("profile", profile.id)
                        .putString("state", "submitted").commit()) {
                    throw failure("session_bind", "callback_persist_failed");
                }
                Intent result = new Intent(app, PresentationInstallActivity.class)
                        .setAction(ACTION_RESULT).setData(sessionUri(sessionId))
                        .putExtra(EXTRA_REQUESTED_SESSION, sessionId)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                int flags = PendingIntent.FLAG_UPDATE_CURRENT;
                if (Build.VERSION.SDK_INT >= 31) flags |= PendingIntent.FLAG_MUTABLE;
                PendingIntent callback = PendingIntent.getActivity(app, sessionId, result, flags);
                attempt.stage = "session_commit";
                session.commit(callback.getIntentSender());
                committed = true;
            }
        } finally {
            if (!committed && sessionId >= 0) {
                try {
                    installer.abandonSession(sessionId);
                    preferences(app).edit().putInt("session_id", -1).putString("cleanup_state", "abandoned")
                            .remove("cleanup_exception").commit();
                } catch (RuntimeException error) {
                    preferences(app).edit().putInt("session_id", sessionId).putString("cleanup_state", "retained")
                            .putString("cleanup_exception", FailurePolicy.exceptionClass(error.getClass().getSimpleName())).commit();
                }
            }
            staged.delete();
        }
    }

    private static void verifyBaseLibraries(PackageInfo installed, Profile profile) throws Exception {
        // sourceDir is the public base APK. No game data, saves, cache or account files are opened.
        try (ZipFile base = new ZipFile(installed.applicationInfo.sourceDir)) {
            for (Map.Entry<String, String> expected : profile.requiredBaseMembers.entrySet()) {
                ZipEntry entry = base.getEntry(expected.getKey());
                if (entry == null) throw failure("base_hash", "base_member_missing");
                if (entry.isDirectory() || entry.getSize() <= 0 || entry.getSize() > 512L * 1024 * 1024)
                    throw failure("base_hash", "base_member_invalid");
                MessageDigest hash = MessageDigest.getInstance("SHA-256");
                try (InputStream input = base.getInputStream(entry)) {
                    copy(input, null, hash, 512L * 1024 * 1024);
                }
                String actual = hex(hash.digest());
                if (!actual.equals(expected.getValue())) throw new InstallFailure(FailurePolicy.make("base_hash",
                        "base_hash_mismatch", null, expected.getKey(), expected.getValue(), actual,
                        FailurePolicy.NO_STATUS, FailurePolicy.NO_STATUS, null));
            }
        }
    }

    private static PackageInfo compatiblePackage(Context app, Profile profile) throws Exception {
        if (Build.VERSION.SDK_INT < 28) throw failure("compatibility", "android_unsupported");
        PackageInfo installed;
        try {
            installed = app.getPackageManager().getPackageInfo(profile.targetPackage, PackageManager.GET_SIGNING_CERTIFICATES);
        } catch (PackageManager.NameNotFoundException error) {
            throw new InstallFailure(FailurePolicy.make("compatibility", "package_missing", error, null, null, null,
                    FailurePolicy.NO_STATUS, FailurePolicy.NO_STATUS, null));
        }
        if (installed.getLongVersionCode() != profile.baseVersionCode) throw failure("compatibility", "version_mismatch");
        if (!profile.targetPackage.equals(installed.packageName) || installed.signingInfo == null
                || installed.applicationInfo == null || installed.applicationInfo.sourceDir == null) {
            throw failure("compatibility", "package_identity_mismatch");
        }
        Signature[] signers = installed.signingInfo.getApkContentsSigners();
        if (signers == null || signers.length != 1
                || !hex(MessageDigest.getInstance("SHA-256").digest(signers[0].toByteArray()))
                .equals(profile.certificateSha256)) {
            throw failure("compatibility", "signer_mismatch");
        }
        return installed;
    }

    private static boolean hasPresentation(PackageInfo installed) {
        if (installed.splitNames != null) {
            for (String name : installed.splitNames) if (SPLIT_ID.equals(name)) return true;
        }
        return hasStandalonePresentation(installed);
    }

    private static boolean hasStandalonePresentation(PackageInfo installed) {
        if (Build.VERSION.SDK_INT < 28 || installed.applicationInfo == null || installed.applicationInfo.sourceDir == null)
            return false;
        // Called only after compatiblePackage verifies the installed package's
        // certificate/version. Read this public base marker and native member only.
        try (ZipFile base = new ZipFile(installed.applicationInfo.sourceDir)) {
            ZipEntry marker = base.getEntry(STANDALONE_MARKER);
            ZipEntry library = base.getEntry("lib/arm64-v8a/libidoly_presentation.so");
            if (marker == null || marker.isDirectory() || marker.getSize() <= 0 || marker.getSize() > 4096
                    || library == null || library.isDirectory() || library.getSize() <= 0
                    || library.getSize() > 8L * 1024 * 1024) return false;
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            try (InputStream input = base.getInputStream(marker)) { copy(input, bytes, null, 4096); }
            JSONObject identity = new JSONObject(bytes.toString(StandardCharsets.UTF_8.name()));
            if (identity.length() != 5 || identity.getInt("schema") != 1 || identity.getInt("bridge_version") != 1
                    || !installed.packageName.equals(identity.getString("target_package"))
                    || identity.getLong("base_version_code") != 414 || installed.getLongVersionCode() != 414
                    || !PRESENTATION_NATIVE_SHA256.equals(identity.getString("native_library_sha256"))) return false;
            MessageDigest hash = MessageDigest.getInstance("SHA-256");
            try (InputStream input = base.getInputStream(library)) { copy(input, null, hash, 8L * 1024 * 1024); }
            return PRESENTATION_NATIVE_SHA256.equals(hex(hash.digest()));
        } catch (Exception ignored) { }
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
        List<PresentationStorage.Estimate> storage = new ArrayList<>();
        boolean featureOnly = featureOnly(app);
        boolean available = false;
        if (Build.VERSION.SDK_INT >= 28) {
            try {
                List<Profile> profiles = loadProfiles(app);
                available = true;
                for (Profile profile : profiles) {
                    try {
                        PackageInfo info = compatiblePackage(app, profile);
                        compatible.add(profile);
                        if (hasPresentation(info)) installed.add(profile);
                        storage.add(PresentationStorage.inspect(app, profile, info, featureOnly));
                    } catch (Exception ignored) { }
                }
            } catch (Exception error) {
                if (readFailure(app) == null) storeFailure(app, FailurePolicy.make("manifest", "operation_failed",
                        error, null, null, null, FailurePolicy.NO_STATUS, FailurePolicy.NO_STATUS, null));
            }
        }
        boolean busy = PREPARING.get() || hasInstallerSession(app);
        String state = preferences(app).getString("state", "idle");
        if (!busy && ("submitted".equals(state) || "confirmation".equals(state) || "checking".equals(state)
                || "copying_existing".equals(state))) {
            state = "interrupted";
            preferences(app).edit().putString("state", state).commit();
            Failure previous = readFailure(app);
            if (previous == null || !"session_query_failed".equals(previous.reason)) {
                storeFailure(app, FailurePolicy.make("session_state", "session_interrupted", null, null, null,
                        null, FailurePolicy.NO_STATUS, FailurePolicy.NO_STATUS, null));
            }
        }
        return new Snapshot(compatible, installed, busy, state, available, readFailure(app),
                safeProfile(preferences(app).getString("profile", "")), featureOnly, storage);
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
        catch (RuntimeException error) {
            storeFailure(app, FailurePolicy.make("session_state", "session_query_failed", error, null, null,
                    null, FailurePolicy.NO_STATUS, FailurePolicy.NO_STATUS, null));
            return false;
        }
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

    static void completeInstall(Context context, int sessionId, int status, int legacyStatus,
            String installToken, Failure callbackFailure, Callback callback) {
        Context app = context.getApplicationContext();
        WORKER.execute(() -> {
            if (preferences(app).getInt("session_id", -1) != sessionId) {
                recordStaleCallback(app, status, legacyStatus, installToken);
                deliver(callback, scan(app));
                return;
            }
            boolean success = false;
            Failure resultFailure = callbackFailure;
            if (status == PackageInstaller.STATUS_SUCCESS) {
                try {
                    Profile profile = findProfile(loadProfiles(app), preferences(app).getString("profile", ""));
                    if (profile == null) throw failure("post_install", "missing_profile");
                    if (!hasPresentation(compatiblePackage(app, profile))) throw failure("post_install", "split_missing");
                    success = true;
                } catch (Exception error) {
                    resultFailure = FailurePolicy.make("post_install", error instanceof InstallFailure
                            ? ((InstallFailure) error).failure.reason : "operation_failed", error instanceof InstallFailure
                            ? null : error, null, null, null, status, legacyStatus, installToken);
                }
            } else if (resultFailure == null) {
                resultFailure = FailurePolicy.make("callback", "os_rejected", null, null, null, null,
                        status, legacyStatus, installToken);
            }
            if (success) clearFailure(preferences(app).edit()).commit();
            else if (resultFailure != null) storeFailure(app, resultFailure);
            boolean clearSession = true;
            if (callbackFailure != null && "confirmation".equals(callbackFailure.stage)) {
                // No OS confirmation was opened. Abandon only this owned session;
                // if Android refuses cleanup, keep its ID so it cannot be orphaned.
                try {
                    app.getPackageManager().getPackageInstaller().abandonSession(sessionId);
                    preferences(app).edit().putString("cleanup_state", "abandoned").remove("cleanup_exception").commit();
                } catch (RuntimeException error) {
                    clearSession = false;
                    preferences(app).edit().putString("cleanup_state", "retained").putString("cleanup_exception",
                            FailurePolicy.exceptionClass(error.getClass().getSimpleName())).commit();
                }
            }
            preferences(app).edit().putString("state", success ? "installed" : "failed")
                    .putInt("session_id", clearSession ? -1 : sessionId).putInt("result_code", status).commit();
            deliver(callback, scan(app));
        });
    }

    static void rejectedCallback(Context context, int status, int legacyStatus, String installToken) {
        Context app = context.getApplicationContext();
        WORKER.execute(() -> recordStaleCallback(app, status, legacyStatus, installToken));
    }

    private static void recordStaleCallback(Context app, int status, int legacyStatus, String installToken) {
        if (readFailure(app) == null) storeFailure(app, FailurePolicy.make("callback", "stale_session", null,
                null, null, null, status, legacyStatus, installToken));
        else preferences(app).edit().putBoolean("stale_callback_observed", true).commit();
    }

    static void permissionScreenFailed(Context context, Throwable error) {
        Context app = context.getApplicationContext();
        WORKER.execute(() -> storeFailure(app, FailurePolicy.make("permission", "operation_failed", error,
                null, null, null, FailurePolicy.NO_STATUS, FailurePolicy.NO_STATUS, null)));
    }

    private static SharedPreferences.Editor clearFailure(SharedPreferences.Editor editor) {
        for (String key : new String[]{"stage", "reason", "exception", "member", "expected_sha", "actual_sha",
                "install_token", "status", "legacy_status", "time_ms", "message", "errno"}) editor.remove("failure_" + key);
        return editor.remove("cleanup_state").remove("cleanup_exception").remove("stale_callback_observed")
                .remove("result_code");
    }

    private static void storeFailure(Context context, Failure value) {
        preferences(context).edit().putString("failure_stage", value.stage).putString("failure_reason", value.reason)
                .putString("failure_exception", value.exceptionClass).putString("failure_member", value.member)
                .putString("failure_expected_sha", value.expectedSha).putString("failure_actual_sha", value.actualSha)
                .putString("failure_install_token", value.installToken).putInt("failure_status", value.status)
                .putInt("failure_legacy_status", value.legacyStatus).putLong("failure_time_ms", value.timeMs)
                .putString("failure_message", value.osMessage).putString("failure_errno", value.errno).commit();
    }

    private static Failure readFailure(Context context) {
        SharedPreferences values = preferences(context);
        if (!values.contains("failure_reason")) {
            // 0.3.9 recorded only Android's high-level callback code. Preserve
            // that existing evidence on upgrade without inventing missing data.
            if ("failed".equals(values.getString("state", "")) && values.contains("result_code"))
                return new Failure("android_result", FailurePolicy.osReason(values.getInt("result_code",
                        FailurePolicy.NO_STATUS), FailurePolicy.NO_STATUS, null), "none", "", "", "", "",
                        values.getInt("result_code", FailurePolicy.NO_STATUS), FailurePolicy.NO_STATUS, 0);
            return null;
        }
        String expected = values.getString("failure_expected_sha", "");
        String actual = values.getString("failure_actual_sha", "");
        int status = values.getInt("failure_status", FailurePolicy.NO_STATUS);
        int legacyStatus = values.getInt("failure_legacy_status", FailurePolicy.NO_STATUS);
        String token = FailurePolicy.installToken(values.getString("failure_install_token", ""));
        String message = FailurePolicy.redactMessage(values.getString("failure_message", ""));
        String reason = FailurePolicy.reason(values.getString("failure_reason", ""));
        if ("os_rejected".equals(reason) || "storage_insufficient".equals(reason) || "storage_or_io_error".equals(reason)) {
            String normalized = FailurePolicy.osReason(status, legacyStatus, message + " " + token);
            reason = "storage_insufficient".equals(reason) && "os_rejected".equals(normalized)
                    ? "storage_or_io_error" : normalized;
        }
        return new Failure(FailurePolicy.stage(values.getString("failure_stage", "")),
                reason,
                FailurePolicy.exceptionClass(values.getString("failure_exception", "")),
                FailurePolicy.publicMember(values.getString("failure_member", "")),
                expected.matches("[0-9a-f]{12}") ? expected : "", actual.matches("[0-9a-f]{12}") ? actual : "",
                token, status, legacyStatus, values.getLong("failure_time_ms", 0), message,
                FailurePolicy.errno(values.getString("failure_errno", "")));
    }

    private static String safeProfile(String profile) {
        return "resources".equals(profile) || "diagnostics".equals(profile) ? profile : "";
    }

    /** Called by ServerService's existing export path even when the server runtime is stopped. */
    static void appendDiagnostics(Context context, JSONObject document) throws org.json.JSONException {
        SharedPreferences values = preferences(context);
        JSONObject details = new JSONObject();
        details.put("schema", 1);
        details.put("android_sdk", Build.VERSION.SDK_INT);
        details.put("profile", safeProfile(values.getString("profile", "")));
        String state = values.getString("state", "idle");
        if (!("idle".equals(state) || "checking".equals(state) || "submitted".equals(state)
                || "confirmation".equals(state) || "installed".equals(state) || "failed".equals(state)
                || "interrupted".equals(state) || "copying_existing".equals(state))) state = "unknown";
        details.put("state", state);
        details.put("session_id", Math.max(-1, values.getInt("session_id", -1)));
        details.put("feature_only", featureOnly(context));
        String attemptMode = values.getString("attempt_mode", "");
        boolean knownAttemptMode = "full_update".equals(attemptMode) || "feature_only_inherit".equals(attemptMode);
        if (knownAttemptMode)
            details.put("attempt_mode", attemptMode);
        boolean storageFeatureOnly = knownAttemptMode ? "feature_only_inherit".equals(attemptMode) : featureOnly(context);
        details.put("storage_mode", storageFeatureOnly ? "feature_only_inherit" : "full_update");
        details.put("storage_context", knownAttemptMode ? "current_for_last_attempt_mode" : "current_for_selected_mode");
        details.put("storage_observed_at_ms", Math.max(0, System.currentTimeMillis()));
        JSONArray storage = new JSONArray();
        try {
            String attemptedProfile = safeProfile(values.getString("profile", ""));
            for (Profile profile : loadProfiles(context)) {
                if (knownAttemptMode && !attemptedProfile.isEmpty() && !profile.id.equals(attemptedProfile)) continue;
                PresentationStorage.Estimate estimate = null;
                try { estimate = PresentationStorage.inspect(context, profile, compatiblePackage(context, profile), storageFeatureOnly); }
                catch (Exception ignored) { }
                JSONObject observed = new JSONObject();
                observed.put("profile", profile.id);
                observed.put("addon_bytes", profile.apkBytes);
                observed.put("existing_copy_bytes", storageFeatureOnly ? 0 : estimate == null ? -1 : Math.max(-1, estimate.existingCopyBytes));
                observed.put("native_extract_bytes", estimate == null ? -1 : Math.max(-1, estimate.nativeExtractBytes));
                observed.put("total_bytes", estimate == null ? -1 : Math.max(-1, estimate.totalBytes));
                observed.put("available_bytes", estimate == null ? -1 : Math.max(-1, estimate.availableBytes));
                observed.put("free_bytes", estimate == null ? -1 : Math.max(-1, estimate.freeBytes));
                String volume = estimate == null ? "unknown" : estimate.volume;
                observed.put("volume", "internal".equals(volume) || "other".equals(volume) ? volume : "unknown");
                storage.put(observed);
            }
        } catch (Exception ignored) { }
        details.put("storage", storage);
        if (values.getBoolean("stale_callback_observed", false)) details.put("stale_callback_observed", true);
        String cleanup = values.getString("cleanup_state", "");
        if ("abandoned".equals(cleanup) || "retained".equals(cleanup)) {
            details.put("session_cleanup", cleanup);
            if (values.contains("cleanup_exception")) details.put("cleanup_exception",
                    FailurePolicy.exceptionClass(values.getString("cleanup_exception", "")));
        }
        Failure failure = readFailure(context);
        if (failure != null) {
            JSONObject error = new JSONObject();
            error.put("stage", failure.stage);
            error.put("category", failure.category);
            error.put("reason", failure.reason);
            error.put("exception", failure.exceptionClass);
            error.put("time_ms", failure.timeMs);
            if (!failure.member.isEmpty()) error.put("member", failure.member);
            if (!failure.expectedSha.isEmpty()) error.put("expected_sha256_prefix", failure.expectedSha);
            if (!failure.actualSha.isEmpty()) error.put("actual_sha256_prefix", failure.actualSha);
            if (failure.status != FailurePolicy.NO_STATUS) error.put("status", failure.status);
            if (failure.legacyStatus != FailurePolicy.NO_STATUS) error.put("legacy_status", failure.legacyStatus);
            if (!failure.installToken.isEmpty()) error.put("install_token", failure.installToken);
            if (!failure.osMessage.isEmpty()) error.put("message", failure.osMessage);
            if (!failure.errno.isEmpty()) error.put("errno", failure.errno);
            details.put("failure", error);
        }
        document.put("presentation_install", details);
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
