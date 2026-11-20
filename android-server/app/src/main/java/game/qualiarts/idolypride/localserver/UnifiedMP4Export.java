package game.qualiarts.idolypride.localserver;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.lang.ref.WeakReference;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.util.ArrayList;
import org.json.JSONObject;

/** Trusted local controller; neither the broker capability nor a filesystem path enters UI JSON. */
public final class UnifiedMP4Export {
    static final int SAVE_DOCUMENT = 50057;
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final ArrayList<Runnable> observers = new ArrayList<>();
    private static volatile boolean configured, initialized, saving;
    private static volatile File exportRoot;
    private static JSONObject last = new JSONObject();
    private static WeakReference<Activity> game = new WeakReference<>(null);
    private static boolean resumed, polling;
    private static long pendingDeadline;
    private static int[] pending;
    private static LinearLayout overlay;
    private static TextView overlayText;
    private static Button overlaySave, overlayCancel, overlayDismiss;
    private static boolean dismissed;
    private static String pendingSaveId;
    private static File pendingSaveRoot;
    private static final Runnable POLL = UnifiedMP4Export::poll;
    private static final Runnable BEGIN = UnifiedMP4Export::beginPending;
    private UnifiedMP4Export() {}

    private static native boolean nativeInitializeEncoder(Class<?> encoderClass);
    private static native int nativeConfigure(String brokerDirectory, long epoch, String capability,
                                               String exportDirectory, int platform);
    private static native int nativeStart(int fpsNumerator, int fpsDenominator, int codec, int videoBitrate, int audioBitrate);
    private static native String nativeStatus();
    private static native void nativeCancel();
    private static native boolean nativeReady();

    /** Only ServerService's trusted worker supplies this private Python descriptor. */
    static boolean prepare(Context context, String descriptor) {
        configured = false;
        if (!UnifiedRuntime.isEnabled(context)) return false;
        try {
            JSONObject value = new JSONObject(descriptor);
            if (value.getInt("schema") != 1 || !value.getBoolean("available")) return false;
            long epoch = value.getLong("epoch"); String capability = value.getString("capability");
            File files = context.getFilesDir().getCanonicalFile();
            File broker = privateDirectory(files, value.getString("directory"));
            File output = privateDirectory(files, value.getString("export_directory"));
            if (epoch < 1 || !capability.matches("[a-f0-9]{32}")) return false;
            System.loadLibrary("idoly_presentation");
            // Class resolution occurs here in Java's app class loader, never a foreign JNI thread.
            Class<?> encoder = Class.forName("game.qualiarts.idolypride.localserver.mp4.OfflineMp4Encoder");
            if (!nativeInitializeEncoder(encoder)) return false;
            initialized = true;
            if (nativeConfigure(broker.getPath(), epoch, capability, output.getPath(), 1) != 0) return false;
            exportRoot = output; configured = true; MAIN.post(UnifiedMP4Export::wake); return true;
        } catch (Exception | LinkageError unavailable) { configured = false; return false; }
    }

    private static File privateDirectory(File files, String path) throws IOException {
        File input = new File(path), real = input.getCanonicalFile();
        if (!input.isAbsolute() || !real.equals(input) || !real.isDirectory()
                || !real.getPath().startsWith(files.getPath() + File.separator)
                || Files.isSymbolicLink(input.toPath())) throw new IOException("Invalid private export directory");
        return real;
    }

    static void serverStopped() {
        configured = false;
        MAIN.post(() -> { cancel(); pending = null; wake(); });
    }
    static boolean available() { return configured; }
    static boolean ready() {
        if (!configured || pending != null || busy() || saving) return false;
        Activity current = game.get();
        if (current == null || current.isDestroyed() || current.isFinishing()) return false;
        try { return nativeReady(); } catch (LinkageError unavailable) { return false; }
    }
    static JSONObject snapshot() {
        try { return new JSONObject(last.toString()); } catch (Exception ignored) { return new JSONObject(); }
    }
    static boolean busy() {
        String phase = last.optString("phase", "idle");
        return pending != null || phase.equals("preparing_audio") || phase.equals("rendering")
                || phase.equals("finishing") || phase.equals("cancelling");
    }
    static void observe(Runnable observer) {
        if (!observers.contains(observer)) observers.add(observer);
        wake();
    }
    static void removeObserver(Runnable observer) { observers.remove(observer); }

    static boolean requestStart(Activity caller, int fps, int codec, int bitrate) {
        if (!ready() || (fps != 30 && fps != 60) || (codec != 1 && codec != 2)
                || (bitrate != 8_000_000 && bitrate != 16_000_000 && bitrate != 32_000_000)) return false;
        Activity current = game.get();
        if (current == null) return false;
        pending = new int[] {fps, 1, codec, bitrate, 192_000};
        dismissed = false;
        pendingDeadline = android.os.SystemClock.uptimeMillis() + 8000;
        try {
            caller.startActivity(new Intent(caller, current.getClass())
                    .addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT | Intent.FLAG_ACTIVITY_SINGLE_TOP));
            MAIN.postDelayed(BEGIN, 250); wake(); return true;
        } catch (RuntimeException unavailable) { pending = null; wake(); return false; }
    }
    private static void beginPending() {
        if (pending == null) return;
        Activity current = game.get();
        if (!configured || current == null || current.isDestroyed() || current.isFinishing()
                || android.os.SystemClock.uptimeMillis() > pendingDeadline) {
            pending = null; wake(); return;
        }
        if (!resumed) { MAIN.postDelayed(BEGIN, 100); return; }
        try {
            if (!nativeReady()) { MAIN.postDelayed(BEGIN, 100); return; }
            int[] options = pending; pending = null;
            if (nativeStart(options[0], options[1], options[2], options[3], options[4]) != 0)
                Toast.makeText(current, R.string.mp4_not_ready, Toast.LENGTH_LONG).show();
            else last = new JSONObject().put("phase", "preparing_audio");
        } catch (Exception | LinkageError unavailable) {
            pending = null; Toast.makeText(current, R.string.mp4_unavailable, Toast.LENGTH_LONG).show();
        }
        wake();
    }

    static void attachGame(Activity activity) {
        game = new WeakReference<>(activity);
        LinearLayout bar = new LinearLayout(activity); bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL); bar.setBackgroundColor(0xe6222630);
        int padding = Math.round(10 * activity.getResources().getDisplayMetrics().density);
        bar.setPadding(padding, padding / 2, padding, padding / 2);
        TextView message = new TextView(activity); message.setTextColor(Color.WHITE); message.setTextSize(14);
        bar.addView(message, new LinearLayout.LayoutParams(0, -2, 1));
        Button stop = new Button(activity); stop.setText(R.string.mp4_cancel); stop.setOnClickListener(view -> cancel()); bar.addView(stop);
        Button save = new Button(activity); save.setText(R.string.mp4_save); save.setOnClickListener(view -> requestSave(activity)); bar.addView(save);
        Button dismiss = new Button(activity); dismiss.setText(R.string.mp4_dismiss);
        dismiss.setOnClickListener(view -> { dismissed = true; bar.setVisibility(View.GONE); }); bar.addView(dismiss);
        FrameLayout.LayoutParams layout = new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM);
        activity.addContentView(bar, layout);
        overlay = bar; overlayText = message; overlaySave = save; overlayCancel = stop; overlayDismiss = dismiss; bar.setVisibility(View.GONE);
        // Android views are outside the original Unity render target captured by the exporter.
        wake();
    }
    static void gameResumed(Activity activity) {
        if (game.get() != activity) return;
        resumed = true; MAIN.postDelayed(BEGIN, 200); wake();
    }
    static void gamePaused(Activity activity) {
        if (game.get() != activity) return;
        resumed = false;
        if (pending == null) cancel();
    }
    static void geometryChanged(Activity activity) { if (game.get() == activity && pending == null) cancel(); }
    static void focusChanged(Activity activity, boolean focused) {
        if (!focused && game.get() == activity && pending == null) cancel();
    }
    static void gameDestroyed(Activity activity) {
        if (game.get() != activity) return;
        cancel(); pending = null; game.clear(); resumed = false;
        if (overlay != null && overlay.getParent() instanceof ViewGroup) ((ViewGroup) overlay.getParent()).removeView(overlay);
        overlay = null; overlayText = null; overlaySave = null; overlayCancel = null; overlayDismiss = null;
    }
    static void cancel() {
        if (pending != null) { pending = null; MAIN.removeCallbacks(BEGIN); }
        if (initialized) try { nativeCancel(); } catch (LinkageError unavailable) { /* Optional addon. */ }
        wake();
    }
    private static void wake() { if (!polling) { polling = true; MAIN.post(POLL); } }
    private static void poll() {
        polling = false;
        if (initialized) try {
            String raw = nativeStatus();
            if (raw != null && raw.length() <= 65536) last = new JSONObject(raw);
        } catch (Exception | LinkageError unavailable) { /* Keep last complete user-visible snapshot. */ }
        Activity activity = game.get();
        if (overlay != null && activity != null) {
            String phase = last.optString("phase");
            boolean complete = phase.equals("completed");
            boolean terminal = complete || phase.equals("failed") || phase.equals("cancelled");
            if (busy()) dismissed = false;
            overlay.setVisibility(!dismissed && (busy() || terminal || saving) ? View.VISIBLE : View.GONE);
            overlayText.setText(statusText(activity)); overlaySave.setVisibility(complete ? View.VISIBLE : View.GONE);
            overlaySave.setEnabled(!saving && complete);
            overlayCancel.setVisibility(busy() ? View.VISIBLE : View.GONE);
            overlayDismiss.setVisibility(terminal && !saving ? View.VISIBLE : View.GONE);
        }
        for (Runnable observer : new ArrayList<>(observers)) observer.run();
        if (configured && (resumed || !observers.isEmpty()) || initialized && busy() || saving) {
            polling = true; MAIN.postDelayed(POLL, 400);
        }
    }
    static String statusText(Context context) {
        if (saving) return context.getString(R.string.mp4_finishing);
        if (pending != null) return context.getString(R.string.mp4_preparing_audio);
        switch (last.optString("phase", "idle")) {
            case "preparing_audio": return last.optLong("total_audio_frames") > 0
                    ? context.getString(R.string.mp4_preparing_audio_progress, last.optLong("audio_frames"), last.optLong("total_audio_frames"))
                    : context.getString(R.string.mp4_preparing_audio);
            case "rendering": {
                String progress = context.getString(R.string.mp4_rendering, last.optLong("frames"), last.optLong("total_frames"));
                long width = last.optLong("width"), height = last.optLong("height"), fps = last.optLong("fps_num");
                return width > 0 && height > 0 ? progress + "\n" + context.getString(R.string.mp4_geometry, width, height, fps) : progress;
            }
            case "finishing": case "cancelling": return context.getString(R.string.mp4_finishing);
            case "completed": return context.getString(R.string.mp4_completed);
            case "cancelled": return context.getString(R.string.mp4_cancelled);
            case "failed": return context.getString(R.string.mp4_failed, last.optString("error_code", "export_failed"));
            default: return context.getString(!configured ? R.string.mp4_unavailable : ready() ? R.string.mp4_idle : R.string.mp4_not_ready);
        }
    }

    static boolean canSave() {
        if (saving || !last.optString("phase").equals("completed")) return false;
        try { completedFile(exportRoot, last.optString("export_id")); return true; } catch (IOException invalid) { return false; }
    }
    static void requestSave(Activity activity) {
        if (!canSave()) return;
        pendingSaveId = last.optString("export_id"); pendingSaveRoot = exportRoot;
        Intent picker = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("video/mp4")
                .putExtra(Intent.EXTRA_TITLE, activity.getString(R.string.mp4_export_filename, pendingSaveId));
        try { activity.startActivityForResult(picker, SAVE_DOCUMENT); }
        catch (RuntimeException unavailable) { pendingSaveId = null; pendingSaveRoot = null; Toast.makeText(activity, R.string.mp4_save_failed, Toast.LENGTH_LONG).show(); }
    }
    static boolean activityResult(Activity activity, int request, int result, Intent data) {
        if (request != SAVE_DOCUMENT) return false;
        String id = pendingSaveId; File root = pendingSaveRoot; pendingSaveId = null; pendingSaveRoot = null;
        if (result != Activity.RESULT_OK || data == null || data.getData() == null || id == null) return true;
        Uri destination = data.getData(); Context context = activity.getApplicationContext(); saving = true; wake();
        new Thread(() -> {
            boolean success = false;
            try {
                File source = completedFile(root, id); long expected = source.length(), copied = 0;
                try (FileInputStream input = new FileInputStream(source); OutputStream output = context.getContentResolver().openOutputStream(destination, "w")) {
                    if (output == null) throw new IOException("Document output unavailable");
                    byte[] buffer = new byte[131072]; int read;
                    while ((read = input.read(buffer)) != -1) { output.write(buffer, 0, read); copied += read; }
                    output.flush();
                }
                if (copied != expected || source.length() != expected) throw new IOException("Completed file changed");
                success = true;
            } catch (Exception ignored) { /* The private completed file stays available for retry. */ }
            boolean saved = success;
            MAIN.post(() -> { saving = false; Toast.makeText(context, saved ? R.string.mp4_saved : R.string.mp4_save_failed, Toast.LENGTH_LONG).show(); wake(); });
        }, "IdolyMp4Document").start();
        return true;
    }
    private static File completedFile(File directory, String id) throws IOException {
        if (directory == null || id == null || !id.matches("[A-Za-z0-9_-]{1,80}")) throw new IOException("Invalid export id");
        File source = new File(directory, id + ".mp4");
        if (!source.getCanonicalFile().equals(source) || !Files.isRegularFile(source.toPath(), LinkOption.NOFOLLOW_LINKS)
                || source.length() < 1) throw new IOException("Completed export unavailable");
        return source;
    }
    static void saveState(Bundle state) {
        if (pendingSaveId != null && pendingSaveRoot != null) { state.putString("mp4_save_id", pendingSaveId); state.putString("mp4_save_root", pendingSaveRoot.getPath()); }
    }
    static void restoreState(Context context, Bundle state) {
        if (state == null || pendingSaveId != null) return;
        try {
            String id = state.getString("mp4_save_id"), path = state.getString("mp4_save_root");
            if (id == null || path == null) return;
            File root = privateDirectory(context.getFilesDir().getCanonicalFile(), path); completedFile(root, id);
            pendingSaveId = id; pendingSaveRoot = root;
        } catch (IOException invalid) { /* A stale picker cannot select an arbitrary private file. */ }
    }
}
