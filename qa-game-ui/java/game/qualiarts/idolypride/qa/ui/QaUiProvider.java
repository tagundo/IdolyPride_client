package game.qualiarts.idolypride.qa.ui;

import android.app.Application;
import android.app.Activity;
import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.SystemClock;
import android.util.Log;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONObject;

/** Nonexported temporary QA bootstrap for pinned inputs and emulator indicators. */
public final class QaUiProvider extends ContentProvider {
    private static final String DIAGNOSTIC_PACKAGE = "game.qualiarts.idolypride.local.diagnostics";
    private static final String NORMAL_PACKAGE = "game.qualiarts.idolypride.local";
    private static final String NORMAL_INPUT_SHA256 = "28ecc6a617867d0842a5e88eac3d5736199809a49d4d433ce47816d6a40ba77b";
    private static final String TOKEN_FILE = "idoly-qa-ui-token";
    private static final String TAG = "IdolyQaUi";
    private static final AtomicBoolean STARTED = new AtomicBoolean();

    @Override public boolean onCreate() {
        Context context = getContext();
        if (context == null || !(DIAGNOSTIC_PACKAGE.equals(context.getPackageName())
                || NORMAL_PACKAGE.equals(context.getPackageName()))
                || !context.getPackageName().equals(Application.getProcessName()) || !emulatorHardware()) return true;
        long sessionMillis = markerSessionMillis(context);
        if (sessionMillis <= 0 || !STARTED.compareAndSet(false, true)) return true;
        Context application = context.getApplicationContext();
        if (application instanceof Application)
            ((Application)application).registerActivityLifecycleCallbacks(new ActivityObservation(application));
        Thread worker = new Thread(new Bootstrap(context.getApplicationContext(), sessionMillis), "IdolyQaUiBootstrap");
        worker.setDaemon(true);
        worker.start();
        return true;
    }

    /** Fixed, bounded observations only: no Intent contents or lifecycle changes. */
    private static final class ActivityObservation implements Application.ActivityLifecycleCallbacks {
        private final File file;
        private int records;
        ActivityObservation(Context context) {
            file = new File(context.getFilesDir(), "idoly-qa-lifecycle.txt");
            try (FileOutputStream output = new FileOutputStream(file, false)) {
                output.write("observer_registered\n".getBytes(StandardCharsets.US_ASCII));
            } catch (Exception ignored) { Log.i(TAG, "activity_observer_file_unavailable"); }
        }
        private synchronized void record(Activity activity, String phase) {
            if (records++ >= 128) return;
            String name = activity.getClass().getName();
            String role = "game.qualiarts.idolypride.localserver.MainActivity".equals(name) ? "server"
                : "game.qualiarts.idolypride.localserver.UnifiedGameActivity".equals(name) ? "game" : "other";
            String line = SystemClock.elapsedRealtime() + " " + role + " " + phase
                + " finishing=" + activity.isFinishing() + " destroyed=" + activity.isDestroyed() + "\n";
            Log.i(TAG, "activity_" + role + "_" + phase);
            try (FileOutputStream output = new FileOutputStream(file, true)) {
                output.write(line.getBytes(StandardCharsets.US_ASCII));
            } catch (Exception ignored) { Log.i(TAG, "activity_observer_write_unavailable"); }
        }
        @Override public void onActivityPreCreated(Activity a, Bundle b) { record(a, "precreated"); }
        @Override public void onActivityCreated(Activity a, Bundle b) { record(a, "created"); }
        @Override public void onActivityStarted(Activity a) { record(a, "started"); }
        @Override public void onActivityResumed(Activity a) { record(a, "resumed"); }
        @Override public void onActivityPaused(Activity a) { record(a, "paused"); }
        @Override public void onActivityStopped(Activity a) { record(a, "stopped"); }
        @Override public void onActivitySaveInstanceState(Activity a, Bundle b) { record(a, "saved"); }
        @Override public void onActivityDestroyed(Activity a) { record(a, "destroyed"); }
    }

    private static boolean emulatorHardware() {
        return "ranchu".equals(Build.HARDWARE) || "goldfish".equals(Build.HARDWARE)
            || "cutf_cvm".equals(Build.HARDWARE);
    }

    private static long markerSessionMillis(Context context) {
        try (InputStream stream = context.getAssets().open("idoly-qa-ui.json")) {
            ByteArrayOutputStream buffer = new ByteArrayOutputStream();
            byte[] chunk = new byte[1024];
            int count;
            while ((count = stream.read(chunk)) >= 0) {
                if (buffer.size() + count > 16384) return 0;
                buffer.write(chunk, 0, count);
            }
            JSONObject marker = new JSONObject(new String(buffer.toByteArray(), StandardCharsets.UTF_8));
            String packageName = context.getPackageName();
            String profile = marker.optString("input_profile", "diagnostic-aes");
            boolean supportedProfile = DIAGNOSTIC_PACKAGE.equals(packageName) && "diagnostic-aes".equals(profile);
            if (DIAGNOSTIC_PACKAGE.equals(packageName) && "unified-current".equals(profile)) {
                JSONObject provenance = marker.optJSONObject("provenance");
                String source = marker.optString("source_commit", "");
                supportedProfile = provenance != null && source.matches("[0-9a-f]{40}")
                    && source.equals(provenance.optString("source_commit", ""))
                    && marker.optString("input_apk_sha256", "").matches("[0-9a-f]{64}")
                    && marker.optString("input_apk_sha256", "").equals(provenance.optString("current_unified_apk_sha256", ""))
                    && !provenance.optBoolean("sdk_aes_store_adaptations", true)
                    && (DIAGNOSTIC_PACKAGE + ".qa.ui").equals(marker.optString("authority", ""))
                    && !marker.optBoolean("exported", true) && marker.optBoolean("debuggable", false)
                    && marker.optBoolean("loopback_only", false);
            }
            if (NORMAL_PACKAGE.equals(packageName)) {
                supportedProfile = "normal-local".equals(profile)
                    && NORMAL_INPUT_SHA256.equals(marker.optString("input_apk_sha256", ""))
                    && (NORMAL_PACKAGE + ".qa.ui").equals(marker.optString("authority", ""))
                    && !marker.optBoolean("exported", true) && marker.optBoolean("debuggable", false)
                    && marker.optBoolean("loopback_only", false);
            }
            if (!(supportedProfile && marker.optInt("schema", 0) == 1 && marker.optBoolean("qa_only", false)
                && marker.optBoolean("emulator_only", false) && packageName.equals(marker.optString("package", "")))) return 0;
            return LoopbackUiServer.markerSessionMillis(marker.opt("session_millis"), marker.has("session_millis"));
        } catch (Exception ignored) { return 0; }
    }

    static final class EmulatorIndicators {
        static boolean matches(String hardware, String bootHardware, String device, String qemu) {
            if ("cutf_cvm".equals(hardware)) {
                return "cutf_cvm".equals(bootHardware) && "vsoc_arm64_only".equals(device);
            }
            return ("ranchu".equals(hardware) || "goldfish".equals(hardware)) && "1".equals(qemu);
        }
    }

    private static String property(String name, long timeoutSeconds) {
        Process process = null;
        try {
            process = new ProcessBuilder("/system/bin/getprop", name).start();
            if (!process.waitFor(timeoutSeconds, TimeUnit.SECONDS) || process.exitValue() != 0) return "";
            byte[] value = new byte[128];
            try (InputStream stream = process.getInputStream()) {
                int count = stream.read(value);
                return count > 0 ? new String(value, 0, count, StandardCharsets.US_ASCII).trim() : "";
            }
        } catch (Exception ignored) { return ""; }
        finally { if (process != null) process.destroy(); }
    }

    private static boolean emulatorProperty() {
        if ("cutf_cvm".equals(Build.HARDWARE)) {
            // Stock Cuttlefish has no ro.kernel.qemu property. Require its
            // observed boot hardware and exact ARM64-only product instead.
            return EmulatorIndicators.matches(Build.HARDWARE, property("ro.boot.hardware", 3), Build.DEVICE, "");
        }
        return EmulatorIndicators.matches(Build.HARDWARE, "", Build.DEVICE, property("ro.kernel.qemu", 1));
    }

    private static final class Bootstrap implements Runnable {
        private final Context context;
        private final long sessionMillis;
        Bootstrap(Context context, long sessionMillis) {
            this.context = context;
            this.sessionMillis = LoopbackUiServer.checkedSessionMillis(sessionMillis);
        }
        @Override public void run() {
            if (!emulatorProperty()) { Log.i(TAG, "emulator_guard_blocked"); return; }
            UnityDispatcher dispatcher = null;
            LoopbackUiServer server = null;
            File tokenFile = new File(context.getFilesDir(), TOKEN_FILE);
            File temporary = new File(context.getFilesDir(), ".idoly-qa-ui-token.tmp");
            boolean ownsToken = false;
            String phase = "native_load";
            try {
                NativeUiBridge.load();
                byte[] random = new byte[32];
                new SecureRandom().nextBytes(random);
                StringBuilder encoded = new StringBuilder(64);
                for (byte value : random) encoded.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
                String token = encoded.toString();
                dispatcher = new UnityDispatcher(context, sessionMillis);
                phase = "listener_start";
                server = new LoopbackUiServer(token, dispatcher, sessionMillis);
                phase = "private_token_write";
                try (FileOutputStream stream = context.openFileOutput(temporary.getName(), Context.MODE_PRIVATE)) {
                    stream.write((token + "\n").getBytes(StandardCharsets.US_ASCII));
                    stream.getFD().sync();
                }
                if (!temporary.renameTo(tokenFile)) throw new IllegalStateException("QA token unavailable");
                ownsToken = true;
                dispatcher.start();
                phase = "bridge_run";
                Log.i(TAG, "bridge_ready");
                server.run();
            } catch (Throwable ignored) {
                // These phases are fixed source literals, never payloads or exceptions.
                Log.i(TAG, phase + "_failed");
            } finally {
                if (server != null) server.stop();
                if (dispatcher != null) dispatcher.stop();
                temporary.delete();
                if (ownsToken) tokenFile.delete();
                Log.i(TAG, "bridge_stopped");
            }
        }
    }

    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] selectionArgs, String order) { return null; }
    @Override public String getType(Uri uri) { return null; }
    @Override public Uri insert(Uri uri, ContentValues values) { return null; }
    @Override public int delete(Uri uri, String selection, String[] args) { return 0; }
    @Override public int update(Uri uri, ContentValues values, String selection, String[] args) { return 0; }
}
