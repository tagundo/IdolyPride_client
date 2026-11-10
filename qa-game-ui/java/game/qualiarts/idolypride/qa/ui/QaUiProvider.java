package game.qualiarts.idolypride.qa.ui;

import android.app.Application;
import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
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

/** Nonexported, temporary QA bootstrap. Physical devices never start a bridge. */
public final class QaUiProvider extends ContentProvider {
    private static final String PACKAGE = "game.qualiarts.idolypride.local.diagnostics";
    private static final String TOKEN_FILE = "idoly-qa-ui-token";
    private static final String TAG = "IdolyQaUi";
    private static final long SESSION_MILLIS = 1800000L;
    private static final AtomicBoolean STARTED = new AtomicBoolean();

    @Override public boolean onCreate() {
        Context context = getContext();
        if (context == null || !PACKAGE.equals(context.getPackageName())
                || !PACKAGE.equals(Application.getProcessName()) || !emulatorHardware()
                || !validMarker(context) || !STARTED.compareAndSet(false, true)) return true;
        Thread worker = new Thread(new Bootstrap(context.getApplicationContext()), "IdolyQaUiBootstrap");
        worker.setDaemon(true);
        worker.start();
        return true;
    }

    private static boolean emulatorHardware() {
        return "ranchu".equals(Build.HARDWARE) || "goldfish".equals(Build.HARDWARE)
            || "cutf_cvm".equals(Build.HARDWARE);
    }

    private static boolean validMarker(Context context) {
        try (InputStream stream = context.getAssets().open("idoly-qa-ui.json")) {
            ByteArrayOutputStream buffer = new ByteArrayOutputStream();
            byte[] chunk = new byte[1024];
            int count;
            while ((count = stream.read(chunk)) >= 0) {
                if (buffer.size() + count > 16384) return false;
                buffer.write(chunk, 0, count);
            }
            JSONObject marker = new JSONObject(new String(buffer.toByteArray(), StandardCharsets.UTF_8));
            return marker.optInt("schema", 0) == 1 && marker.optBoolean("qa_only", false)
                && marker.optBoolean("emulator_only", false) && PACKAGE.equals(marker.optString("package", ""));
        } catch (Exception ignored) { return false; }
    }

    private static boolean emulatorProperty() {
        Process process = null;
        try {
            process = new ProcessBuilder("/system/bin/getprop", "ro.kernel.qemu").start();
            if (!process.waitFor(1, TimeUnit.SECONDS) || process.exitValue() != 0) return false;
            byte[] value = new byte[8];
            try (InputStream stream = process.getInputStream()) {
                int count = stream.read(value);
                return count > 0 && new String(value, 0, count, StandardCharsets.US_ASCII).trim().equals("1");
            }
        } catch (Exception ignored) { return false; }
        finally { if (process != null) process.destroy(); }
    }

    private static final class Bootstrap implements Runnable {
        private final Context context;
        Bootstrap(Context context) { this.context = context; }
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
                dispatcher = new UnityDispatcher(context, SESSION_MILLIS);
                phase = "listener_start";
                server = new LoopbackUiServer(token, dispatcher, SESSION_MILLIS);
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
