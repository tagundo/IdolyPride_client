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
import org.json.JSONArray;

/** Trusted local controller; neither the broker capability nor a filesystem path enters UI JSON. */
public final class UnifiedMP4Export {
    static final int SAVE_DOCUMENT = 50057;
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final ArrayList<Runnable> observers = new ArrayList<>();
    private static volatile boolean configured, initialized, saving;
    private static volatile File exportRoot;
    private static volatile File persistentExportRoot;
    private static boolean queueConfigured;
    private static JSONObject last = new JSONObject();
    private static JSONObject lastQueue = new JSONObject();
    private static volatile Mp4TitleCatalog titleCatalog = Mp4TitleCatalog.empty();
    private static boolean pendingQueueRun;
    private static WeakReference<Activity> game = new WeakReference<>(null);
    private static boolean resumed, stopped = true, userPaused, polling;
    private static boolean gameFocused;
    private static volatile boolean foregroundSelectionReady;
    private static volatile long menuHandoffDeadline;
    private static long pendingDeadline;
    private static int[] pending;
    private static LinearLayout overlay;
    private static TextView overlayText;
    private static Button overlaySave, overlayCancel, overlayPause, overlayDismiss;
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
    private static native int nativeStartV2(int fpsNumerator, int fpsDenominator, int codec, int videoBitrate,
                                             int audioBitrate, int outputWidth, int outputHeight);
    private static native String nativeStatus();
    private static native void nativeCancel();
    private static native void nativeSuspend(int reason);
    private static native void nativeResume();
    private static native boolean nativeReady();
    private static native int nativeQueueConfigure(String queueRoot, String exportsRoot);
    private static native int nativeQueueEnqueue(int fpsNum, int fpsDen, int codec, int videoBitrate, int audioBitrate);
    private static native int nativeQueueEnqueueV2(int fpsNum, int fpsDen, int codec, int videoBitrate,
                                                   int audioBitrate, int outputWidth, int outputHeight);
    private static native int nativeQueueRun();
    private static native int nativeQueuePause();
    private static native int nativeQueueResume();
    private static native int nativeQueueCommand(int operation, String jobId, int position);
    private static native String nativeQueueStatus();

    /** Only ServerService's trusted worker supplies this private Python descriptor. */
    static boolean prepare(Context context, String descriptor) {
        configured = false;
        foregroundSelectionReady = false; menuHandoffDeadline = 0;
        titleCatalog = Mp4TitleCatalog.empty();
        if (!UnifiedRuntime.isEnabled(context)) return false;
        try {
            JSONObject value = new JSONObject(descriptor);
            if (value.getInt("schema") != 1 || !value.getBoolean("available")) return false;
            titleCatalog = Mp4TitleCatalog.parse(value.optJSONObject("title_catalog"));
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
            queueConfigured = false;
            if (value.has("queue_directory") && value.has("persistent_export_directory")) {
                File queue = privateDirectory(files, value.getString("queue_directory"));
                File completed = privateDirectory(files, value.getString("persistent_export_directory"));
                queueConfigured = nativeQueueConfigure(queue.getPath(), completed.getPath()) == 0;
                if (queueConfigured) persistentExportRoot = completed;
            }
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
        // The queue can own an original pre-download before a session exists.
        // Park it on the host thread before retiring the server/encoder path.
        if (initialized && queueConfigured) try { nativeQueuePause(); }
        catch (LinkageError unavailable) { /* Optional addon; still retire the session below. */ }
        configured = false; queueConfigured = false; foregroundSelectionReady = false; menuHandoffDeadline = 0;
        MAIN.post(() -> { cancel(); pending = null; wake(); });
    }
    static boolean available() { return configured; }
    static boolean ready() {
        if (!configured || pending != null || busy() || saving) return false;
        Activity current = game.get();
        if (current == null || current.isDestroyed() || current.isFinishing()) return false;
        // Opening the separate server Activity pauses Unity. Retain only this
        // live Activity's last verified foreground selection to offer a request;
        // actual capture still revalidates after the original player resumes.
        if ((!resumed || !gameFocused) && foregroundSelectionReady) return true;
        try { return nativeReady(); } catch (LinkageError unavailable) { return false; }
    }
    private static void observeForegroundReadiness(boolean nativeReady) {
        boolean menuHandoff = menuHandoffDeadline > 0
                && android.os.SystemClock.uptimeMillis() <= menuHandoffDeadline;
        // A config/layout callback can release the source before Android has
        // delivered onPause/focus loss. Do not let the intervening poll undo
        // this short, explicit menu handoff's already verified selection.
        if (resumed && gameFocused && !busy() && (nativeReady || !menuHandoff))
            foregroundSelectionReady = nativeReady;
    }
    static JSONObject snapshot() {
        try { return new JSONObject(last.toString()); } catch (Exception ignored) { return new JSONObject(); }
    }
    /** Bounded public observations only: no broker paths, capabilities or job payloads. */
    static JSONObject diagnostics() {
        JSONObject result = new JSONObject();
        try {
            Activity owner = game.get();
            result.put("schema", 1).put("available", configured).put("initialized", initialized)
                    .put("game_attached", owner != null && !owner.isDestroyed() && !owner.isFinishing())
                    .put("game_resumed", resumed).put("game_focused", gameFocused).put("game_stopped", stopped)
                    .put("verified_foreground_selection", foregroundSelectionReady);
            JSONObject state = snapshot();
            if (initialized) try {
                String raw = nativeStatus();
                if (raw != null && raw.length() <= 65536) state = new JSONObject(raw);
            } catch (Exception | LinkageError ignored) { }
            result.put("ready", state.optBoolean("ready"));
            for (String key : new String[] {"phase", "readiness_error", "error_code", "pause_reason"}) {
                String value = state.optString(key, "unknown");
                result.put(key, value.matches("[A-Za-z0-9_]{1,96}") ? value : "unknown");
            }
            for (String key : new String[] {"unity_ticks", "capture_acks", "width", "height", "source_width", "source_height",
                    "fps_num", "fps_den", "video_bitrate", "frames", "total_frames"})
                result.put(key, Math.max(0L, Math.min(9007199254740991L, state.optLong(key))));
            JSONObject queue = queueSnapshot();
            JSONArray jobs = queue.optJSONArray("jobs");
            result.put("queue_available", queueConfigured && queue.optBoolean("available"))
                    .put("queue_running", queue.optBoolean("running"))
                    .put("queue_paused", queue.optBoolean("paused"))
                    .put("queue_job_count", jobs == null ? 0 : Math.min(8, jobs.length()));
        } catch (Exception ignored) { /* Keep the bounded observations already collected. */ }
        return result;
    }
    static JSONObject queueSnapshot() {
        try { return titleCatalog.enrich(lastQueue).put("available", queueConfigured && lastQueue.optBoolean("available")); }
        catch (Exception ignored) { return new JSONObject(); }
    }
    static JSONObject backgroundSnapshot() { return UnifiedMP4Background.snapshot(); }
    static boolean backgroundQueueHasWork() {
        return pendingQueueRun || lastQueue.optBoolean("running") || lastQueue.optBoolean("command_pending");
    }
    static boolean requestEnqueue(Activity caller, int fps, int codec, int bitrate) {
        return requestEnqueue(caller, fps, codec, bitrate, 0, 0);
    }
    static boolean requestEnqueue(Activity caller, int fps, int codec, int bitrate, int outputWidth, int outputHeight) {
        if (!queueConfigured || !ready() || (fps != 30 && fps != 60) || (codec != 1 && codec != 2)
                || !Mp4ExportSettings.validBitrate(bitrate)
                || !Mp4ExportSettings.validResolution(outputWidth, outputHeight)) return false;
        Activity current = game.get();
        if (current == null || current.isDestroyed() || current.isFinishing()) return false;
        try {
            if (nativeQueueEnqueueV2(fps, 1, codec, bitrate, 192_000, outputWidth, outputHeight) != 0) return false;
            caller.startActivity(new Intent(caller, current.getClass())
                    .addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT | Intent.FLAG_ACTIVITY_SINGLE_TOP));
            wake(); return true;
        } catch (RuntimeException | LinkageError unavailable) { return false; }
    }
    static boolean requestQueueRun(Activity caller) {
        if (!queueConfigured) return false;
        try {
            if (nativeQueueRun() != 0) return false;
            return bringQueueToForeground(caller);
        } catch (LinkageError unavailable) { return false; }
    }
    private static boolean bringQueueToForeground(Activity caller) {
        Activity current = game.get();
        if (current == null || current.isDestroyed() || current.isFinishing()) return false;
        try {
            userPaused = false; pendingQueueRun = true; pendingDeadline = android.os.SystemClock.uptimeMillis() + 8000;
            caller.startActivity(new Intent(caller, current.getClass())
                    .addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT | Intent.FLAG_ACTIVITY_SINGLE_TOP));
            MAIN.postDelayed(BEGIN, 200); wake(); return true;
        } catch (RuntimeException unavailable) { pendingQueueRun = false; return false; }
    }
    static boolean queuePause() {
        if (!queueConfigured) return false;
        try {
            if (nativeQueuePause() != 0) return false;
            userPaused = true; pendingQueueRun = false; UnifiedMP4Background.stopCurrent(); wake(); return true;
        } catch (LinkageError unavailable) { return false; }
    }
    static boolean queueResume(Activity caller) {
        if (!queueConfigured) return false;
        try {
            if (nativeQueueResume() != 0) return false;
            return bringQueueToForeground(caller);
        } catch (LinkageError unavailable) { return false; }
    }
    static boolean queueCommand(int operation, String jobId, int position) {
        if (!queueConfigured || operation < 1 || operation > 4 || jobId == null || !jobId.matches("[A-Za-z0-9_-]{1,80}")) return false;
        try { boolean accepted = nativeQueueCommand(operation, jobId, position) == 0; wake(); return accepted; }
        catch (LinkageError unavailable) { return false; }
    }
    static boolean experimentalBackgroundEnabled(Context context) {
        return context.getSharedPreferences("mp4_export", Context.MODE_PRIVATE).getBoolean("experimental_background", false);
    }
    static void setExperimentalBackgroundEnabled(Context context, boolean enabled) {
        context.getSharedPreferences("mp4_export", Context.MODE_PRIVATE).edit().putBoolean("experimental_background", enabled).apply();
        if (!enabled) UnifiedMP4Background.stopCurrent();
        else {
            Activity activity = game.get();
            if (activity != null && busy()) prepareBackground(activity);
        }
        wake();
    }
    private static void prepareBackground(Activity activity) {
        if (!experimentalBackgroundEnabled(activity)) return;
        UnifiedMP4Background.prepare(activity, new UnifiedMP4Background.Host() {
            public JSONObject status() {
                try { return new JSONObject(nativeStatus()); }
                catch (Exception | LinkageError unavailable) { return snapshot(); }
            }
            public void park() { if (initialized) try { nativeSuspend(userPaused ? 3 : 2); } catch (LinkageError ignored) { } }
            public void resume() { resumeForLifecycle(); }
            public boolean userPaused() { return userPaused; }
            public void changed() { wake(); }
        });
        if (!resumed) UnifiedMP4Background.backgrounded(activity);
    }
    static boolean busy() {
        String phase = last.optString("phase", "idle");
        return pending != null || pendingQueueRun || phase.equals("preparing_audio") || phase.equals("rendering")
                || phase.equals("finishing") || phase.equals("cancelling")
                || phase.equals("pausing") || phase.equals("paused");
    }
    static void observe(Runnable observer) {
        if (!observers.contains(observer)) observers.add(observer);
        wake();
    }
    static void removeObserver(Runnable observer) { observers.remove(observer); }

    static boolean requestStart(Activity caller, int fps, int codec, int bitrate) {
        return requestStart(caller, fps, codec, bitrate, 0, 0);
    }
    static boolean requestStart(Activity caller, int fps, int codec, int bitrate, int outputWidth, int outputHeight) {
        if (!ready() || (fps != 30 && fps != 60) || (codec != 1 && codec != 2)
                || !Mp4ExportSettings.validBitrate(bitrate)
                || !Mp4ExportSettings.validResolution(outputWidth, outputHeight)) return false;
        Activity current = game.get();
        if (current == null) return false;
        pending = new int[] {fps, 1, codec, bitrate, 192_000, outputWidth, outputHeight};
        dismissed = false;
        pendingDeadline = android.os.SystemClock.uptimeMillis() + 8000;
        try {
            caller.startActivity(new Intent(caller, current.getClass())
                    .addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT | Intent.FLAG_ACTIVITY_SINGLE_TOP));
            MAIN.postDelayed(BEGIN, 250); wake(); return true;
        } catch (RuntimeException unavailable) { pending = null; wake(); return false; }
    }
    private static void beginPending() {
        if (pendingQueueRun) {
            Activity target = game.get();
            if (target == null || target.isDestroyed() || target.isFinishing()
                    || android.os.SystemClock.uptimeMillis() > pendingDeadline) { pendingQueueRun = false; wake(); return; }
            if (!resumed) { MAIN.postDelayed(BEGIN, 100); return; }
            pendingQueueRun = false;
            prepareBackground(target);
            wake();
        }
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
            userPaused = false;
            if (nativeStartV2(options[0], options[1], options[2], options[3], options[4], options[5], options[6]) != 0)
                Toast.makeText(current, R.string.mp4_not_ready, Toast.LENGTH_LONG).show();
            else { last = new JSONObject().put("phase", "preparing_audio"); prepareBackground(current); }
        } catch (Exception | LinkageError unavailable) {
            pending = null; Toast.makeText(current, R.string.mp4_unavailable, Toast.LENGTH_LONG).show();
        }
        wake();
    }

    static void attachGame(Activity activity) {
        game = new WeakReference<>(activity);
        foregroundSelectionReady = false; gameFocused = false; menuHandoffDeadline = 0;
        LinearLayout bar = new LinearLayout(activity); bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL); bar.setBackgroundColor(0xe6222630);
        int padding = Math.round(10 * activity.getResources().getDisplayMetrics().density);
        bar.setPadding(padding, padding / 2, padding, padding / 2);
        TextView message = new TextView(activity); message.setTextColor(Color.WHITE); message.setTextSize(14);
        bar.addView(message, new LinearLayout.LayoutParams(0, -2, 1));
        Button pause = new Button(activity); pause.setText(R.string.mp4_pause);
        pause.setOnClickListener(view -> togglePause()); bar.addView(pause);
        Button stop = new Button(activity); stop.setText(R.string.mp4_cancel); stop.setOnClickListener(view -> cancel()); bar.addView(stop);
        Button save = new Button(activity); save.setText(R.string.mp4_save); save.setOnClickListener(view -> requestSave(activity)); bar.addView(save);
        Button dismiss = new Button(activity); dismiss.setText(R.string.mp4_dismiss);
        dismiss.setOnClickListener(view -> { dismissed = true; bar.setVisibility(View.GONE); }); bar.addView(dismiss);
        FrameLayout.LayoutParams layout = new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM);
        activity.addContentView(bar, layout);
        overlay = bar; overlayText = message; overlaySave = save; overlayCancel = stop; overlayPause = pause; overlayDismiss = dismiss; bar.setVisibility(View.GONE);
        // Android views are outside the original Unity render target captured by the exporter.
        wake();
    }
    static void gameResumed(Activity activity) {
        if (game.get() != activity) return;
        menuHandoffDeadline = 0;
        resumed = true; stopped = false; resumeForLifecycle(); MAIN.postDelayed(BEGIN, 200); wake();
    }
    static void gameResuming(Activity activity) {
        if (game.get() == activity) UnifiedMP4Background.foregrounding(activity);
    }
    static void gamePauseCompleted(Activity activity) {
        if (game.get() == activity) UnifiedMP4Background.backgrounded(activity);
    }
    static void gamePaused(Activity activity) {
        if (game.get() != activity) return;
        // Called before super.onPause: preserve a positive native observation.
        // A focus-loss frame may already report not-ready; it must not erase a
        // verified MV just because the server menu is being opened.
        if (initialized) try { if (nativeReady()) foregroundSelectionReady = true; }
        catch (LinkageError unavailable) { /* Optional addon. */ }
        resumed = false; gameFocused = false;
        // Original Unity keeps a visible multi-window player running onPause.
        // Focus and resumed state alone do not mean its render surface is lost.
        if (!activity.isInMultiWindowMode()) suspendForLifecycle();
    }
    static void gameStarted(Activity activity) {
        if (game.get() != activity) return;
        stopped = false;
        if (activity.isInMultiWindowMode()) resumeForLifecycle();
    }
    static void gameStopped(Activity activity) {
        if (game.get() != activity) return;
        stopped = true; suspendForLifecycle();
    }
    private static void suspendForLifecycle() {
        if (initialized && pending == null && !userPaused) try { nativeSuspend(1); }
        catch (LinkageError unavailable) { /* Optional addon. */ }
        wake();
    }
    private static void resumeForLifecycle() {
        if (initialized && !userPaused) try { nativeResume(); }
        catch (LinkageError unavailable) { /* Optional addon. */ }
        wake();
    }
    static void togglePause() {
        if (!initialized || !busy() || pending != null) return;
        Activity activity = game.get();
        if (activity == null || stopped || (!resumed && !activity.isInMultiWindowMode())) return;
        if (userPaused || last.optString("phase").equals("paused")) requestResume(activity);
        else requestPause();
    }
    static boolean requestPause() {
        if (!initialized || !busy() || pending != null) return false;
        try { userPaused = true; nativeSuspend(3); UnifiedMP4Background.stopCurrent(); wake(); return true; }
        catch (LinkageError unavailable) { userPaused = false; return false; }
    }
    static boolean requestResume(Activity caller) {
        if (!initialized || !busy() || pending != null) return false;
        Activity activity = game.get();
        if (activity == null || activity.isDestroyed() || activity.isFinishing()) return false;
        try {
            if (stopped || (!resumed && !activity.isInMultiWindowMode())) {
                // Server controls live in a different Activity. Restore the
                // existing Unity owner and let its original lifecycle resume it.
                caller.startActivity(new Intent(caller, activity.getClass())
                        .addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT | Intent.FLAG_ACTIVITY_SINGLE_TOP));
                userPaused = false;
            } else { userPaused = false; nativeResume(); }
            wake(); return true;
        } catch (RuntimeException | LinkageError unavailable) { return false; }
    }
    static void serverMenuOpening(Activity activity) {
        if (!configured || game.get() != activity || activity.isDestroyed() || activity.isFinishing()) return;
        // Android may deliver the landscape -> server-menu portrait config
        // before onPause. Bind this short handoff to the existing Unity owner.
        menuHandoffDeadline = android.os.SystemClock.uptimeMillis() + 8000;
        if (initialized) try { if (nativeReady()) foregroundSelectionReady = true; }
        catch (LinkageError unavailable) { /* Only retain an actually verified selection. */ }
    }
    static void serverMenuOpenFailed(Activity activity) {
        if (game.get() == activity) menuHandoffDeadline = 0;
    }
    static void geometryChanged(Activity activity) {
        if (game.get() == activity && pending == null && !UnifiedMP4Background.ownsSurface(activity)) {
            boolean menuHandoff = menuHandoffDeadline > 0
                    && android.os.SystemClock.uptimeMillis() <= menuHandoffDeadline;
            boolean activePlayerWindow = resumed || (!stopped && activity.isInMultiWindowMode());
            // A background Unity resize can release only its render target,
            // while its logical MV remains selected. Native enqueue fixes that
            // identity and revalidates the actual source after returning.
            if (!menuHandoff && activePlayerWindow) foregroundSelectionReady = false;
            // An existing capture still cancels on every real geometry change.
            cancel();
        }
    }
    static void focusChanged(Activity activity, boolean focused) {
        // A notification shade or another split-screen window can take focus
        // without pausing Unity. onPause/onStop own the lifecycle decision.
        if (game.get() == activity) {
            gameFocused = focused;
            if (!focused) UnifiedMP4Background.focusLost(activity);
            wake();
        }
    }
    static void gameDestroyed(Activity activity) {
        if (game.get() != activity) return;
        cancel(); pending = null; game.clear(); resumed = false; stopped = true;
        foregroundSelectionReady = false; gameFocused = false; menuHandoffDeadline = 0;
        if (overlay != null && overlay.getParent() instanceof ViewGroup) ((ViewGroup) overlay.getParent()).removeView(overlay);
        overlay = null; overlayText = null; overlaySave = null; overlayCancel = null; overlayPause = null; overlayDismiss = null;
    }
    static void cancel() {
        UnifiedMP4Background.stopCurrent();
        pendingQueueRun = false;
        userPaused = false;
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
            if (queueConfigured) {
                String queue = nativeQueueStatus();
                if (queue != null && queue.length() <= 65536) lastQueue = new JSONObject(queue);
            }
        } catch (Exception | LinkageError unavailable) { /* Keep last complete user-visible snapshot. */ }
        UnifiedMP4Background.sample(last);
        Activity activity = game.get();
        if (activity != null) observeForegroundReadiness(last.optBoolean("ready"));
        if (activity != null && resumed && !userPaused && (busy() || backgroundQueueHasWork())
                && UnifiedMP4Background.snapshot().optString("state").equals("off")) prepareBackground(activity);
        if (overlay != null && activity != null) {
            String phase = last.optString("phase");
            boolean complete = phase.equals("completed");
            boolean terminal = complete || phase.equals("failed") || phase.equals("cancelled");
            if (busy()) dismissed = false;
            overlay.setVisibility(!dismissed && (busy() || terminal || saving) ? View.VISIBLE : View.GONE);
            overlayText.setText(statusText(activity)); overlaySave.setVisibility(complete ? View.VISIBLE : View.GONE);
            overlaySave.setEnabled(complete && canSave());
            overlayCancel.setVisibility(busy() ? View.VISIBLE : View.GONE);
            boolean pausable = phase.equals("preparing_audio") || phase.equals("rendering")
                    || phase.equals("pausing") || phase.equals("paused");
            overlayPause.setVisibility(pausable ? View.VISIBLE : View.GONE);
            overlayPause.setText(userPaused || phase.equals("paused") ? R.string.mp4_resume : R.string.mp4_pause);
            overlayPause.setEnabled(!stopped && (resumed || activity.isInMultiWindowMode()));
            overlayDismiss.setVisibility(terminal && !saving ? View.VISIBLE : View.GONE);
        }
        for (Runnable observer : new ArrayList<>(observers)) observer.run();
        if (configured && (resumed || !observers.isEmpty()) || initialized && (busy() || backgroundQueueHasWork())
                || UnifiedMP4Background.expectsService() || saving) {
            polling = true; MAIN.postDelayed(POLL, 400);
        }
    }
    static String statusText(Context context) {
        if (saving) return context.getString(R.string.mp4_finishing);
        if (pending != null) return context.getString(R.string.mp4_preparing_audio);
        String phase = last.optString("phase", "idle");
        if (backgroundQueueHasWork() && (phase.isEmpty() || phase.equals("idle") || phase.equals("completed")
                || phase.equals("failed") || phase.equals("cancelled")))
            return context.getString(R.string.mp4_queue_waiting_scene);
        switch (phase) {
            case "preparing_audio": return last.optLong("total_audio_frames") > 0
                    ? context.getString(R.string.mp4_preparing_audio_progress, last.optLong("audio_frames"), last.optLong("total_audio_frames"))
                    : context.getString(R.string.mp4_preparing_audio);
            case "rendering": {
                String progress = context.getString(R.string.mp4_rendering, last.optLong("frames"), last.optLong("total_frames"));
                long width = last.optLong("width"), height = last.optLong("height"), fps = last.optLong("fps_num");
                return width > 0 && height > 0 ? progress + "\n" + context.getString(R.string.mp4_geometry, width, height, fps) : progress;
            }
            case "finishing": case "cancelling": return context.getString(R.string.mp4_finishing);
            case "pausing": return context.getString(R.string.mp4_pausing);
            case "paused": return context.getString(last.optString("pause_reason").equals("user_paused")
                    ? R.string.mp4_paused : R.string.mp4_background_paused);
            case "completed": return context.getString(R.string.mp4_completed);
            case "cancelled": return context.getString(R.string.mp4_cancelled);
            case "failed": return context.getString(R.string.mp4_failed, last.optString("error_code", "export_failed"));
            default:
                if (!configured) return context.getString(R.string.mp4_unavailable);
                if (ready()) return context.getString(R.string.mp4_idle);
                String reason = last.optString("readiness_error");
                return reason.matches("[A-Za-z0-9_]{1,96}") && !reason.equals("none")
                        && !reason.equals("open_selected_mv_first")
                        ? context.getString(R.string.mp4_not_ready_reason, reason)
                        : context.getString(R.string.mp4_not_ready);
        }
    }

    private static final class SaveTarget {
        final File root;
        final String outputId, jobId;
        SaveTarget(File root, String outputId, String jobId) { this.root = root; this.outputId = outputId; this.jobId = jobId; }
    }
    private static SaveTarget queuedSaveTarget(String jobId) throws IOException {
        if (persistentExportRoot == null || jobId == null || !jobId.matches("[A-Za-z0-9_-]{1,80}")) throw new IOException("Invalid queue job");
        JSONArray jobs = lastQueue.optJSONArray("jobs");
        if (jobs != null) for (int i = 0; i < jobs.length(); i++) {
            JSONObject job = jobs.optJSONObject(i);
            if (job == null || !jobId.equals(job.optString("job_id"))) continue;
            if (!job.optString("state").equals("completed")) throw new IOException("Queue job is not complete");
            String output = job.optString("output_id");
            completedFile(persistentExportRoot, output);
            return new SaveTarget(persistentExportRoot, output, jobId);
        }
        throw new IOException("Queue job unavailable");
    }
    private static SaveTarget currentSaveTarget() throws IOException {
        if (!last.optString("phase").equals("completed")) throw new IOException("Export is not complete");
        String output = last.optString("export_id");
        JSONArray jobs = lastQueue.optJSONArray("jobs");
        if (jobs != null) for (int i = 0; i < jobs.length(); i++) {
            JSONObject job = jobs.optJSONObject(i);
            if (job != null && output.equals(job.optString("output_id"))) {
                // A known queue output may never fall back to the temporary
                // one-shot directory, even if its journal/file is unavailable.
                return queuedSaveTarget(job.optString("job_id"));
            }
        }
        completedFile(exportRoot, output);
        return new SaveTarget(exportRoot, output, null);
    }
    static boolean canSave() {
        if (saving) return false;
        try { currentSaveTarget(); return true; } catch (IOException invalid) { return false; }
    }
    private static void openSave(Activity activity, SaveTarget target) {
        pendingSaveId = target.outputId; pendingSaveRoot = target.root;
        Intent picker = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("video/mp4")
                .putExtra(Intent.EXTRA_TITLE, activity.getString(R.string.mp4_export_filename, pendingSaveId));
        try { activity.startActivityForResult(picker, SAVE_DOCUMENT); }
        catch (RuntimeException unavailable) { pendingSaveId = null; pendingSaveRoot = null; Toast.makeText(activity, R.string.mp4_save_failed, Toast.LENGTH_LONG).show(); }
    }
    static void requestSave(Activity activity) {
        if (saving) return;
        try { openSave(activity, currentSaveTarget()); } catch (IOException invalid) { /* Keep unavailable outputs private. */ }
    }
    static void requestSave(Activity activity, String jobId) {
        if (saving) return;
        try { openSave(activity, queuedSaveTarget(jobId)); } catch (IOException invalid) { /* The completed file stays available for retry. */ }
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
