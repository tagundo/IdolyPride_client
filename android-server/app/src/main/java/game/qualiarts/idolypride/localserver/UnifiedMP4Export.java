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
import java.util.HashSet;
import java.util.Set;
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
    private static volatile Context application;
    private static volatile Mp4CompletedExports completedExports;
    private static DocumentPickerHistory documentHistory;
    private static boolean queueConfigured;
    private static JSONObject last = new JSONObject();
    private static JSONObject lastQueue = new JSONObject();
    private static JSONObject lastNativeTrace;
    private static long tracePersistedAt;
    private static String persistedTrace = "";
    private static volatile Mp4TitleCatalog titleCatalog = Mp4TitleCatalog.empty();
    private static boolean pendingQueueRun;
    private static WeakReference<Activity> game = new WeakReference<>(null);
    private static boolean resumed, stopped = true, userPaused, polling;
    private static boolean gameFocused;
    private static volatile boolean foregroundSelectionReady;
    private static volatile boolean foregroundMvSelected;
    private static volatile long menuHandoffDeadline;
    private static long pendingDeadline;
    private static int[] pending;
    private static LinearLayout overlay;
    private static TextView overlayText;
    private static Button overlaySave, overlayCancel, overlayPause, overlayDismiss;
    private static boolean dismissed;
    private static String pendingSaveId;
    private static File pendingSaveRoot;
    private static String pendingSaveOwner;
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
    private static native String nativeDiagnostics();
    private static native void nativeCancel();
    private static native void nativeSuspend(int reason);
    private static native void nativeResume();
    private static native boolean nativeReady();
    private static native boolean nativeSelectionReady();
    private static native int nativeQueueConfigure(String queueRoot, String exportsRoot);
    private static native int nativeQueueEnqueue(int fpsNum, int fpsDen, int codec, int videoBitrate, int audioBitrate);
    private static native int nativeQueueEnqueueV2(int fpsNum, int fpsDen, int codec, int videoBitrate,
                                                   int audioBitrate, int outputWidth, int outputHeight);
    private static native void nativeInvalidateQueueSelection();
    private static native int nativeQueueRun();
    private static native int nativeQueuePause();
    private static native int nativeQueueResume();
    private static native int nativeQueueCommand(int operation, String jobId, int position);
    private static native String nativeQueueStatus();

    /** Only ServerService's trusted worker supplies this private Python descriptor. */
    static boolean prepare(Context context, String descriptor) {
        restoreCompleted(context);
        configured = false;
        foregroundSelectionReady = false; foregroundMvSelected = false; menuHandoffDeadline = 0;
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
            exportRoot = output;
            if (completedExports != null) completedExports.rememberDirectory(output);
            configured = true; MAIN.post(UnifiedMP4Export::wake); return true;
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
        invalidateQueueSelection();
        configured = false; queueConfigured = false; foregroundSelectionReady = false; foregroundMvSelected = false; menuHandoffDeadline = 0;
        // poll() stops refreshing the unconfigured queue; never keep showing its
        // last running snapshot as live work for the rest of the process.
        MAIN.post(() -> { cancelFrom("server_stopped"); pending = null; lastQueue = new JSONObject(); wake(); });
    }
    private static void invalidateQueueSelection() {
        foregroundSelectionReady = false; foregroundMvSelected = false;
        if (initialized) try { nativeInvalidateQueueSelection(); }
        catch (LinkageError unavailable) { /* Optional addon; eligibility is still retired locally. */ }
    }
    static boolean available() { return configured; }
    static boolean ready() {
        if (!configured || pending != null || busy() || saving) return false;
        Activity current = game.get();
        if (current == null || current.isDestroyed() || current.isFinishing()) return false;
        // Opening the separate server Activity pauses Unity. Retain only this
        // live Activity's last verified foreground selection to offer a request.
        // Native queue admission validates its immutable snapshot without
        // resuming Unity; immediate capture revalidates after player resume.
        if ((!resumed || !gameFocused) && foregroundSelectionReady) return true;
        try { return nativeReady(); } catch (LinkageError unavailable) { return false; }
    }
    static boolean selectedMv() {
        if (!configured) return false;
        Activity current = game.get();
        if (current == null || current.isDestroyed() || current.isFinishing()) return false;
        if ((!resumed || !gameFocused) && foregroundMvSelected) return true;
        try { return nativeSelectionReady(); } catch (LinkageError unavailable) { return false; }
    }
    static boolean canEnqueueSelection() {
        Activity current = game.get();
        return configured && queueConfigured && selectedMv() && pending == null && !busy() && !saving
                && current != null && !current.isDestroyed() && !current.isFinishing()
                && Boolean.TRUE.equals(queueSnapshot().opt("can_add"));
    }
    private static void observeForegroundSelection(boolean selected) {
        boolean menuHandoff = menuHandoffDeadline > 0
                && android.os.SystemClock.uptimeMillis() <= menuHandoffDeadline;
        if (resumed && gameFocused && !busy() && (selected || !menuHandoff)) foregroundMvSelected = selected;
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
        try {
            JSONObject result = new JSONObject(last.toString());
            JSONObject discovery = controllerDiscovery(result);
            result.remove("controller_discovery");
            if (discovery != null) result.put("controller_discovery", discovery);
            return result;
        } catch (Exception ignored) { return new JSONObject(); }
    }
    private static JSONObject controllerDiscovery(JSONObject state) {
        JSONObject source = state.optJSONObject("controller_discovery");
        if (source == null) return null;
        JSONObject result = new JSONObject();
        try {
            Object reason = source.opt("reason");
            if (reason instanceof String && ((String) reason).matches("[A-Za-z0-9_]{1,96}"))
                result.put("reason", reason);
            Object origin = source.opt("source");
            if (origin instanceof String && ((String) origin).matches("[A-Za-z0-9_]{1,24}")
                    && (origin.equals("none") || origin.equals("observed") || origin.equals("singleton")
                        || origin.equals("camera_component"))) result.put("source", origin);
            for (String key : new String[] {"listed_directors", "unique_directors", "assets", "output_tracks",
                    "camera_tracks", "null_assets", "candidate_controllers"}) {
                Object value = source.opt(key);
                if (value instanceof Byte || value instanceof Short || value instanceof Integer || value instanceof Long)
                    result.put(key, Math.max(0L, Math.min(65536L, ((Number) value).longValue())));
            }
        } catch (Exception ignored) { /* Retain only the bounded public observations already copied. */ }
        return result.length() == 0 ? null : result;
    }
    /** Native trace is a separate optional ABI; small existing status callers stay compatible. */
    private static JSONObject exportTrace(JSONObject document) {
        JSONObject source = document == null ? null : document.optJSONObject("export_trace");
        if (source == null || !(source.opt("schema") instanceof Integer) || source.optLong("schema") != 1) return null;
        JSONObject trace = new JSONObject();
        try {
            trace.put("schema", 1);
            for (String key : new String[] {"current_stage", "last_error"}) {
                Object value = source.opt(key);
                if (value instanceof String && ((String) value).matches("[A-Za-z0-9_.-]{1,95}")) trace.put(key, value);
            }
            JSONArray input = source.optJSONArray("events"), events = new JSONArray();
            long previous = 0;
            if (input != null) for (int i = Math.max(0, input.length() - 16); i < input.length(); i++) {
                JSONObject row = input.optJSONObject(i); if (row == null) continue;
                Object stage = row.opt("stage"), code = row.opt("code");
                if (!(stage instanceof String) || !(code instanceof String)
                        || !((String) stage).matches("[A-Za-z0-9_.-]{1,95}") || !((String) code).matches("[A-Za-z0-9_.-]{1,95}")) continue;
                Long sequence = traceInteger(row.opt("sequence")), frame = traceInteger(row.opt("frame")), tick = traceInteger(row.opt("tick"));
                if (sequence == null || frame == null || tick == null || sequence <= previous) continue;
                previous = sequence;
                events.put(new JSONObject().put("sequence", sequence).put("stage", stage).put("code", code).put("frame", frame).put("tick", tick));
            }
            trace.put("events", events);
            JSONObject inputModules = source.optJSONObject("modules"), modules = new JSONObject();
            if (inputModules != null) for (String key : new String[] {"native_scene_control", "scene_parts", "final_playback_handoff", "pending_journal", "frame_coordinator", "default_images", "monitor_ui", "video_coordinator", "proflare_source", "particle_renderer", "graphics_program", "srp_mutations", "audio_frontends", "managed_observers", "native_director_gateway", "capture_queue", "initial_gpu_fence", "render_hold", "native_clock", "game_api"}) {
                Object value = inputModules.opt(key); if (value instanceof Boolean) modules.put(key, value);
            }
            trace.put("modules", modules);
        } catch (Exception invalid) { return null; }
        return trace.has("current_stage") || trace.has("last_error") || eventsPresent(trace) ? trace : null;
    }
    private static Long traceInteger(Object value) {
        if (!(value instanceof Byte || value instanceof Short || value instanceof Integer || value instanceof Long)) return null;
        long number = ((Number) value).longValue(); return number >= 0 && number <= 9007199254740991L ? number : null;
    }
    private static boolean eventsPresent(JSONObject trace) {
        JSONArray events = trace.optJSONArray("events"); return events != null && events.length() != 0;
    }
    private static JSONObject readNativeDiagnostics() {
        if (!initialized) return null;
        try {
            String raw = nativeDiagnostics();
            return raw != null && raw.length() <= 65536 ? new JSONObject(raw) : null;
        } catch (Exception | LinkageError unavailable) { return null; }
    }
    /** The 2 KiB session status is unchanged; its pending cleanup join comes from the separate diagnostics ABI. */
    private static void mergeSessionProgress(JSONObject target, JSONObject document) {
        JSONObject source = document == null ? null : document.optJSONObject("session_progress");
        try {
            String stage = source == null ? "idle" : source.optString("job_stage", "idle");
            String cleanup = source == null ? "none" : source.optString("cleanup_stage", "none");
            Long waited = source == null ? null : traceInteger(source.opt("cleanup_wait_ms"));
            Long boundary = source == null ? null : traceInteger(source.opt("boundary_entries"));
            target.put("job_stage", stage.matches("[A-Za-z0-9_]{1,63}") ? stage : "unknown")
                    .put("cleanup_stage", cleanup.matches("[A-Za-z0-9_]{1,63}") ? cleanup : "none")
                    .put("cleanup_wait_ms", waited == null ? 0L : waited)
                    .put("boundary_entries", boundary == null ? 0L : boundary);
        } catch (Exception ignored) { /* Keep the bounded status already parsed. */ }
    }
    private static void rememberNativeTrace(JSONObject trace) {
        if (trace == null) return;
        lastNativeTrace = trace;
        Context context = application; if (context == null) return;
        try {
            String encoded = new JSONObject().put("export_trace", trace).toString();
            long now = android.os.SystemClock.uptimeMillis();
            boolean failed = !trace.optString("last_error", "none").equals("none");
            if (encoded.equals(persistedTrace) || (!failed && now - tracePersistedAt < 2000)) return;
            android.content.SharedPreferences.Editor edit = context.getSharedPreferences("mp4_export", Context.MODE_PRIVATE)
                    .edit().putString("last_native_trace", encoded);
            if (failed) edit.putString("last_failed_native_trace", encoded);
            edit.apply(); persistedTrace = encoded; tracePersistedAt = now;
        } catch (Exception ignored) { /* Diagnostic writes never block an export. */ }
    }
    private static JSONObject savedNativeTrace(String key) {
        Context context = application; if (context == null) return null;
        try {
            String raw = context.getSharedPreferences("mp4_export", Context.MODE_PRIVATE).getString(key, "");
            return raw.length() <= 65536 ? exportTrace(new JSONObject(raw)) : null;
        } catch (Exception ignored) { return null; }
    }
    /** Bounded public observations only: no broker paths, capabilities or job payloads. */
    static JSONObject diagnostics() {
        JSONObject result = new JSONObject();
        try {
            Activity owner = game.get();
            result.put("schema", 1).put("available", configured).put("initialized", initialized)
                    .put("game_attached", owner != null && !owner.isDestroyed() && !owner.isFinishing())
                    .put("game_resumed", resumed).put("game_focused", gameFocused).put("game_stopped", stopped)
                    .put("verified_foreground_selection", foregroundMvSelected)
                    .put("verified_foreground_export_ready", foregroundSelectionReady);
            Context context = application;
            if (context != null) {
                String stage = context.getSharedPreferences("mp4_export", Context.MODE_PRIVATE).getString("last_save_failure_stage", "none");
                if (java.util.Arrays.asList("none", "save_validate_source", "save_open_document", "save_copy_document", "save_verify_copy").contains(stage))
                    result.put("last_save_failure_stage", stage);
                JSONObject crash = javaCrashDiagnostics(context);
                if (crash != null) result.put("last_java_crash", crash);
                JSONObject cancelled = lastCancelDiagnostics(context);
                if (cancelled != null) result.put("last_cancel", cancelled);
            }
            result.put("save_picker_pending", pendingSaveId != null).put("save_copy_active", saving)
                    .put("document_picker_events", documentDiagnostics());
            // Lifecycle and experimental transport facts that can park a queue
            // in the foreground; fixed scalars and bounded codes only.
            result.put("user_paused", userPaused).put("pending_queue_run", pendingQueueRun)
                    .put("experimental_background", context != null && experimentalBackgroundEnabled(context));
            JSONObject transport = UnifiedMP4Background.snapshot(), background = new JSONObject();
            for (String key : new String[] {"state", "error_code"}) {
                String value = transport.optString(key, "unknown");
                background.put(key, value.matches("[A-Za-z0-9_]{1,64}") ? value : "unknown");
            }
            result.put("background", background.put("heartbeat_verified", transport.optBoolean("heartbeat_verified"))
                    .put("capture_verified", transport.optBoolean("capture_verified")));
            JSONObject state = snapshot();
            if (initialized) try {
                String raw = nativeStatus();
                if (raw != null && raw.length() <= 65536) state = new JSONObject(raw);
            } catch (Exception | LinkageError ignored) { }
            JSONObject nativeDocument = readNativeDiagnostics();
            mergeSessionProgress(state, nativeDocument);
            JSONObject trace = exportTrace(nativeDocument);
            if (trace == null) trace = lastNativeTrace;
            if (trace == null) trace = savedNativeTrace("last_native_trace");
            if (trace != null) result.put("export_trace", trace);
            JSONObject previousFailure = savedNativeTrace("last_failed_native_trace");
            if (previousFailure != null) result.put("last_failed_export_trace", previousFailure);
            result.put("ready", state.optBoolean("ready")).put("selected_mv", Boolean.TRUE.equals(state.opt("selected_mv")));
            String pipelineMode = state.optString("pipeline_mode", "");
            if (pipelineMode.equals("fresh_original_scene") || pipelineMode.equals("legacy_owned_scene"))
                result.put("pipeline_mode", pipelineMode);
            for (String key : new String[] {"phase", "readiness_error", "selection_error", "error_code", "restoration_error", "pause_reason",
                    "job_stage", "cleanup_stage"}) {
                String value = state.optString(key, "unknown");
                result.put(key, value.matches("[A-Za-z0-9_]{1,96}") ? value : "unknown");
            }
            for (String key : new String[] {"unity_ticks", "capture_acks", "width", "height", "source_width", "source_height",
                    "fps_num", "fps_den", "video_bitrate", "frames", "total_frames", "cleanup_wait_ms", "boundary_entries"})
                result.put(key, Math.max(0L, Math.min(9007199254740991L, state.optLong(key))));
            JSONObject discovery = controllerDiscovery(state);
            if (discovery != null) result.put("controller_discovery", discovery);
            JSONObject queue = queueSnapshot();
            JSONArray jobs = queue.optJSONArray("jobs");
            result.put("queue_available", queueConfigured && queue.optBoolean("available"))
                    .put("queue_running", queue.optBoolean("running"))
                    .put("queue_paused", queue.optBoolean("paused"))
                    .put("queue_job_count", jobs == null ? 0 : Math.min(8, jobs.length()))
                    .put("queue_can_add", Boolean.TRUE.equals(queue.opt("can_add")));
            String addError = queue.optString("add_error", "unknown");
            result.put("queue_add_error", addError.matches("[A-Za-z0-9_]{1,96}") ? addError : "unknown");
            String queueError = queue.optString("error_code", "unknown");
            result.put("queue_error_code", queueError.matches("[A-Za-z0-9_]{1,96}") ? queueError : "unknown");
            String queuePhase = queue.optString("phase", "unknown");
            result.put("queue_phase", queuePhase.matches("[A-Za-z0-9_]{1,96}") ? queuePhase : "unknown");
            JSONArray jobStates = new JSONArray();
            for (int index = 0; jobs != null && index < Math.min(8, jobs.length()); index++) {
                JSONObject job = jobs.optJSONObject(index);
                if (job == null) continue;
                String stateCode = job.optString("state", "unknown");
                String failureCode = job.optString("error_code", "unknown");
                jobStates.put(new JSONObject().put("position", index)
                        .put("state", stateCode.matches("[A-Za-z0-9_]{1,96}") ? stateCode : "unknown")
                        .put("error_code", failureCode.matches("[A-Za-z0-9_]{1,96}") ? failureCode : "unknown"));
            }
            result.put("queue_job_states", jobStates);
            String storageStage = queue.optString("storage_stage", "none");
            if (java.util.Arrays.asList("none", "allocate_state", "allocate_store", "allocate_wire",
                    "open_temp", "stat_temp", "write_temp", "sync_temp", "validate_temp",
                    "install_new", "replace_journal", "validate_installed", "sync_directory").contains(storageStage))
                result.put("queue_storage_stage", storageStage);
            Object storageErrno = queue.opt("storage_errno");
            if (storageErrno instanceof Byte || storageErrno instanceof Short
                    || storageErrno instanceof Integer || storageErrno instanceof Long)
                result.put("queue_storage_errno", Math.max(0L, Math.min(4095L, ((Number) storageErrno).longValue())));
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
        if (!canEnqueueSelection() || (fps != 30 && fps != 60 && fps != 120) || (codec != 1 && codec != 2)
                || !Mp4ExportSettings.validBitrate(bitrate)
                || !Mp4ExportSettings.validResolution(outputWidth, outputHeight)) return false;
        Activity current = game.get();
        if (current == null || current.isDestroyed() || current.isFinishing()) return false;
        try {
            if (nativeQueueEnqueueV2(fps, 1, codec, bitrate, 192_000, outputWidth, outputHeight) != 0) return false;
            // Add commits an already observed selection; only Run or immediate
            // export needs to bring the original player window forward.
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
        if (operation == 1) recordCancel("queue_command");
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
        return pending != null || pendingQueueRun || lastQueue.optBoolean("running") || lastQueue.optBoolean("command_pending")
                || phase.equals("preparing_audio") || phase.equals("rendering")
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
        if (!ready() || (fps != 30 && fps != 60 && fps != 120) || (codec != 1 && codec != 2)
                || !Mp4ExportSettings.validBitrate(bitrate)
                || !Mp4ExportSettings.validResolution(outputWidth, outputHeight) || !oneShotCompletionReady()) return false;
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

    private static void observeGameOwner(Activity activity) {
        if (game.get() != activity) {
            invalidateQueueSelection(); resumed = false; stopped = true;
        }
        game = new WeakReference<>(activity);
        foregroundSelectionReady = false; foregroundMvSelected = false; gameFocused = false; menuHandoffDeadline = 0;
    }
    private static volatile boolean crashRecorderInstalled;
    /** Keeps the class chain and top frames of an uncaught Java crash for the next diagnostics export. */
    private static void installCrashRecorder(Context context) {
        if (crashRecorderInstalled || context == null) return;
        crashRecorderInstalled = true;
        final Context owner = context.getApplicationContext();
        final Thread.UncaughtExceptionHandler previous = Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler((thread, error) -> {
            try {
                JSONArray causes = new JSONArray(), frames = new JSONArray();
                Throwable root = error;
                for (Throwable at = error; at != null && causes.length() < 4; at = at.getCause()) { causes.put(at.getClass().getName()); root = at; }
                for (StackTraceElement frame : root.getStackTrace()) {
                    if (frames.length() >= 16) break;
                    frames.put(frame.getClassName() + "." + frame.getMethodName() + ":" + frame.getLineNumber());
                }
                owner.getSharedPreferences("mp4_export", Context.MODE_PRIVATE).edit().putString("last_java_crash",
                        new JSONObject().put("time_ms", System.currentTimeMillis())
                                .put("thread", thread.getName().replaceAll("[^A-Za-z0-9_.-]", "_"))
                                .put("causes", causes).put("frames", frames).toString()).commit();
            } catch (Throwable ignored) { /* Never replace the original crash. */ }
            if (previous != null) previous.uncaughtException(thread, error);
        });
    }
    /** Only a cancel of live work is kept: who asked, when, and the job/queue stage it hit. */
    private static void recordCancel(String origin) {
        Context context = application;
        if (context == null || !initialized || !(busy() || backgroundQueueHasWork())) return;
        // Keep the cancel that ended the job, not a later one during its cleanup.
        String phase = last.optString("phase", ""), stage = last.optString("job_stage", "");
        if (phase.equals("cancelling") || phase.equals("cancelled") || stage.equals("restore_retire")) return;
        try {
            context.getSharedPreferences("mp4_export", Context.MODE_PRIVATE).edit().putString("last_cancel",
                    new JSONObject().put("origin", origin).put("time_ms", System.currentTimeMillis())
                            .put("detail", origin.equals("geometry_changed") ? geometryDetail : "none")
                            .put("phase", publicCode(last.optString("phase", ""))).put("job_stage", publicCode(last.optString("job_stage", "")))
                            .put("queue_phase", publicCode(lastQueue.optString("phase", ""))).toString()).apply();
        } catch (Exception ignored) { /* Diagnostics never block a cancel. */ }
    }
    private static JSONObject lastCancelDiagnostics(Context context) {
        try {
            String raw = context.getSharedPreferences("mp4_export", Context.MODE_PRIVATE).getString("last_cancel", "");
            if (raw.isEmpty() || raw.length() > 4096) return null;
            JSONObject source = new JSONObject(raw), result = new JSONObject();
            result.put("time_ms", Math.max(0L, source.optLong("time_ms")));
            for (String key : new String[] {"origin", "detail", "phase", "job_stage", "queue_phase"}) {
                String value = source.optString(key, "");
                result.put(key, value.matches("[A-Za-z0-9_]{1,64}") ? value : "unknown");
            }
            return result;
        } catch (Exception invalid) { return null; }
    }
    /** Bounded class/frame names only: no exception message, path or payload is ever recorded. */
    private static JSONObject javaCrashDiagnostics(Context context) {
        try {
            String raw = context.getSharedPreferences("mp4_export", Context.MODE_PRIVATE).getString("last_java_crash", "");
            if (raw.isEmpty() || raw.length() > 16384) return null;
            JSONObject source = new JSONObject(raw), result = new JSONObject();
            result.put("time_ms", Math.max(0L, source.optLong("time_ms")));
            String thread = source.optString("thread", "");
            result.put("thread", thread.matches("[A-Za-z0-9_.-]{1,64}") ? thread : "unknown");
            for (String key : new String[] {"causes", "frames"}) {
                JSONArray input = source.optJSONArray(key), output = new JSONArray();
                for (int i = 0; input != null && i < Math.min(16, input.length()); i++) {
                    String value = input.optString(i, "");
                    output.put(value.matches("[A-Za-z0-9_.$<>:-]{1,200}") ? value : "unknown");
                }
                result.put(key, output);
            }
            return result;
        } catch (Exception invalid) { return null; }
    }
    static void attachGame(Activity activity) {
        installCrashRecorder(activity);
        observeGameOwner(activity);
        restoreCompleted(activity);
        LinearLayout bar = new LinearLayout(activity); bar.setOrientation(LinearLayout.VERTICAL);
        bar.setGravity(Gravity.CENTER_VERTICAL); bar.setBackgroundColor(0xff222630);
        bar.setOnClickListener(view -> { /* Export controls own input while the internal scene is rendered. */ });
        int padding = Math.round(10 * activity.getResources().getDisplayMetrics().density);
        bar.setPadding(padding, padding / 2, padding, padding / 2);
        TextView message = new TextView(activity); message.setTextColor(Color.WHITE); message.setTextSize(14);
        bar.addView(message, new LinearLayout.LayoutParams(-1, -2));
        // Keep each action in its own stable slot. Completing an export must
        // never replace the Cancel button underneath an existing pointer.
        LinearLayout actions = new LinearLayout(activity); actions.setOrientation(LinearLayout.HORIZONTAL);
        bar.addView(actions, new LinearLayout.LayoutParams(-1, -2));
        Button pause = new Button(activity); pause.setText(R.string.mp4_pause);
        pause.setOnClickListener(view -> togglePause()); actions.addView(pause, new LinearLayout.LayoutParams(0, -2, 1));
        Button stop = new Button(activity); stop.setText(R.string.mp4_cancel); stop.setOnClickListener(view -> cancelFrom("overlay_button")); actions.addView(stop, new LinearLayout.LayoutParams(0, -2, 1));
        Button save = new Button(activity); save.setText(R.string.mp4_save); actions.addView(save, new LinearLayout.LayoutParams(0, -2, 1));
        Button dismiss = new Button(activity); dismiss.setText(R.string.mp4_dismiss);
        dismiss.setOnClickListener(view -> { dismissed = true; bar.setVisibility(View.GONE); }); actions.addView(dismiss, new LinearLayout.LayoutParams(0, -2, 1));
        FrameLayout.LayoutParams layout = new FrameLayout.LayoutParams(-1, -1, Gravity.BOTTOM);
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
        if (initialized) try {
            if (nativeReady()) foregroundSelectionReady = true;
            if (nativeSelectionReady()) foregroundMvSelected = true;
        }
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
        if (initialized) try {
            if (nativeReady()) foregroundSelectionReady = true;
            if (nativeSelectionReady()) foregroundMvSelected = true;
        }
        catch (LinkageError unavailable) { /* Only retain an actually verified selection. */ }
    }
    static void serverMenuOpenFailed(Activity activity) {
        if (game.get() == activity) menuHandoffDeadline = 0;
    }
    static void geometryChanged(Activity activity) {
        if (game.get() == activity && !UnifiedMP4Background.ownsSurface(activity)) {
            boolean menuHandoff = menuHandoffDeadline > 0
                    && android.os.SystemClock.uptimeMillis() <= menuHandoffDeadline;
            boolean activePlayerWindow = resumed || (!stopped && activity.isInMultiWindowMode());
            // Keep the last immutable MV through the explicit server-menu
            // handoff. A real active-window resize requires a fresh snapshot.
            if (!menuHandoff && activePlayerWindow) invalidateQueueSelection();
            // A capture with its output geometry applied still cancels on a
            // real geometry change. Scene preparation re-reads the window at
            // render setup, and finishing/cleanup no longer use it: the fresh
            // scene reload itself reshapes the window on device (11.23.3).
            if (pending == null && !geometryFreeStage()) cancelFrom("geometry_changed");
        }
    }
    private static boolean geometryFreeStage() {
        String stage = last.optString("job_stage", "");
        return stage.equals("begin") || stage.equals("scene_acquire") || stage.equals("audio_setup")
                || stage.equals("encoder_finish_save") || stage.equals("restore_retire");
    }
    private static String geometryDetail = "none";
    /** Called by the game window just before geometryChanged: which signal and the old/new shape. */
    static void geometrySource(String source, int oldWidth, int oldHeight, int width, int height) {
        geometryDetail = source + "_" + Math.max(0, oldWidth) + "x" + Math.max(0, oldHeight)
                + "_" + Math.max(0, width) + "x" + Math.max(0, height);
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
        invalidateQueueSelection();
        cancelFrom("game_destroyed"); pending = null; game.clear(); resumed = false; stopped = true;
        foregroundSelectionReady = false; foregroundMvSelected = false; gameFocused = false; menuHandoffDeadline = 0;
        if (overlay != null && overlay.getParent() instanceof ViewGroup) ((ViewGroup) overlay.getParent()).removeView(overlay);
        overlay = null; overlayText = null; overlaySave = null; overlayCancel = null; overlayPause = null; overlayDismiss = null;
    }
    private static String cancelOrigin = "unknown";
    /** Names the caller so a cancel of live work is attributable in diagnostics. */
    static void cancelFrom(String origin) { cancelOrigin = origin; cancel(); }
    static void cancel() {
        String origin = cancelOrigin; cancelOrigin = "unknown";
        recordCancel(origin);
        UnifiedMP4Background.stopCurrent();
        pendingQueueRun = false;
        boolean releasedUserPause = userPaused;
        userPaused = false;
        if (pending != null) { pending = null; MAIN.removeCallbacks(BEGIN); }
        if (initialized) try {
            nativeCancel();
            // A user pause request outlives the cancelled session natively and
            // would park the next queued job forever. Hand it back to the real
            // lifecycle: a visible player resumes, a hidden one stays parked.
            if (releasedUserPause) {
                Activity activity = game.get();
                if (activity != null && !stopped && (resumed || activity.isInMultiWindowMode())) nativeResume();
                else nativeSuspend(1);
            }
        } catch (LinkageError unavailable) { /* Optional addon. */ }
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
        JSONObject nativeDiagnostics = readNativeDiagnostics();
        mergeSessionProgress(last, nativeDiagnostics);
        rememberNativeTrace(exportTrace(nativeDiagnostics));
        rememberCompletedOutputs();
        UnifiedMP4Background.sample(last);
        Activity activity = game.get();
        if (activity != null) {
            observeForegroundReadiness(last.optBoolean("ready"));
            observeForegroundSelection(Boolean.TRUE.equals(last.opt("selected_mv")));
        }
        if (activity != null && resumed && !userPaused && (busy() || backgroundQueueHasWork())
                && UnifiedMP4Background.snapshot().optString("state").equals("off")) prepareBackground(activity);
        if (overlay != null && activity != null) {
            String phase = last.optString("phase");
            boolean complete = !busy() && hasCompletedOutput();
            boolean terminal = complete || phase.equals("failed") || phase.equals("cancelled");
            if (busy()) dismissed = false;
            overlay.setVisibility(!dismissed && (busy() || terminal || saving) ? View.VISIBLE : View.GONE);
            String overlayStatus;
            try { overlayStatus = statusText(activity); }
            catch (RuntimeException failed) { overlayStatus = activity.getString(R.string.mp4_progress_title); }
            overlayText.setText(overlayStatus);
            bindSaveButton(overlaySave, activity);
            overlaySave.setText(phase.equals("completed") ? R.string.mp4_save : R.string.mp4_save_completed);
            overlaySave.setVisibility(complete ? View.VISIBLE : View.INVISIBLE);
            overlaySave.setEnabled(complete && canSave());
            overlayCancel.setVisibility(busy() ? View.VISIBLE : View.INVISIBLE);
            boolean pausable = phase.equals("preparing_audio") || phase.equals("rendering")
                    || phase.equals("pausing") || phase.equals("paused");
            overlayPause.setVisibility(pausable ? View.VISIBLE : View.INVISIBLE);
            overlayPause.setText(userPaused || phase.equals("paused") ? R.string.mp4_resume : R.string.mp4_pause);
            overlayPause.setEnabled(!stopped && (resumed || activity.isInMultiWindowMode()));
            // While queue work owns the scene the next poll re-shows the panel;
            // offer Close only when dismissing actually hides it.
            overlayDismiss.setVisibility(terminal && !saving && !busy() ? View.VISIBLE : View.INVISIBLE);
        }
        Context notice = application != null ? application : activity;
        if (notice != null && initialized && (busy() || backgroundQueueHasWork())) try {
            UnifiedMP4Service.update(statusText(notice),
                    last.optString("phase").equals("rendering") ? last.optLong("frames") : 0,
                    last.optString("phase").equals("rendering") ? last.optLong("total_frames") : 0);
        } catch (RuntimeException ignored) { /* The notification mirror never ends the process. */ }
        for (Runnable observer : new ArrayList<>(observers)) observer.run();
        if (configured && (resumed || !observers.isEmpty()) || initialized && (busy() || backgroundQueueHasWork())
                || UnifiedMP4Background.expectsService() || saving) {
            polling = true; MAIN.postDelayed(POLL, 400);
        }
    }
    static String enqueueFailureText(Context context) {
        String reason = queueSnapshot().optString("add_error", "");
        if (reason.matches("[A-Za-z0-9_]{1,96}") && !reason.equals("none") && !reason.equals("unknown"))
            return context.getString(R.string.mp4_queue_error, reason);
        return statusText(context);
    }
    private static String publicCode(String value) {
        return value != null && value.matches("[A-Za-z0-9_]{1,96}") && !value.equals("none") && !value.equals("unknown") ? value : "";
    }
    /** A terminal session row belongs to the running queue job only by its exact output identity or live cleanup. */
    private static boolean sessionOwnsCurrentQueueJob() {
        if (!publicCode(last.optString("cleanup_stage", "none")).isEmpty()) return true;
        String output = last.optString("export_id", ""), current = lastQueue.optString("current_job_id", "");
        JSONArray jobs = lastQueue.optJSONArray("jobs");
        if (output.isEmpty() || current.isEmpty() || jobs == null) return false;
        for (int index = 0; index < Math.min(8, jobs.length()); index++) {
            JSONObject job = jobs.optJSONObject(index);
            if (job != null && current.equals(job.optString("job_id"))) return output.equals(job.optString("output_id"));
        }
        return false;
    }
    /** Names the original cleanup join that still owns the scene; never a generic "preparing" line. */
    private static String cleanupText(Context context) {
        String stage = publicCode(last.optString("cleanup_stage", "none"));
        if (stage.isEmpty()) stage = publicCode(lastQueue.optString("phase", ""));
        if (stage.isEmpty()) return context.getString(R.string.mp4_finishing);
        long seconds = Math.max(0L, Math.min(86_400L, last.optLong("cleanup_wait_ms") / 1000L));
        String text = context.getString(R.string.mp4_cleanup_waiting, stage, seconds);
        return seconds >= 60 ? text + "\n" + context.getString(R.string.mp4_cleanup_stalled, seconds) : text;
    }
    static String statusText(Context context) {
        if (saving) return context.getString(R.string.mp4_finishing);
        if (pending != null) return context.getString(R.string.mp4_preparing_audio);
        String phase = last.optString("phase", "idle");
        String preparationError = lastQueue.optString("error_code", "none");
        boolean terminalSession = phase.equals("failed") || phase.equals("cancelled");
        if (phase.equals("failed") && backgroundQueueHasWork() && !preparationError.equals("none")
                && preparationError.matches("[A-Za-z0-9_]{1,96}") && preparationError.equals(last.optString("error_code")))
            return context.getString(R.string.mp4_failed, preparationError) + "\n" + cleanupText(context);
        // The current job's own failure or cancellation stays visible through
        // its original cleanup join. Only an older job's row yields to the next.
        if (terminalSession && backgroundQueueHasWork() && sessionOwnsCurrentQueueJob()) {
            String code = publicCode(last.optString("error_code"));
            return (phase.equals("failed") ? context.getString(R.string.mp4_failed, code.isEmpty() ? "export_failed" : code)
                    : context.getString(R.string.mp4_cancelled)) + "\n" + cleanupText(context);
        }
        String queuePhase = publicCode(lastQueue.optString("phase", ""));
        String queueError = publicCode(preparationError);
        if (backgroundQueueHasWork() && !queueError.isEmpty()
                && (queuePhase.equals("draining_navigation") || queuePhase.equals("restoring_selection")))
            return context.getString(R.string.mp4_failed, queueError) + "\n" + cleanupText(context);
        if (backgroundQueueHasWork() && (phase.isEmpty() || phase.equals("idle") || phase.equals("completed")
                || phase.equals("failed") || phase.equals("cancelled")))
            return context.getString(R.string.mp4_queue_waiting_scene) + (queuePhase.isEmpty() ? "" : "\n(" + queuePhase + ")");
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
                if (hasCompletedOutput()) return context.getString(R.string.mp4_completed);
                if (!configured) return context.getString(R.string.mp4_unavailable);
                JSONArray queued = lastQueue.optJSONArray("jobs");
                if (lastQueue.optBoolean("can_run") && queued != null)
                    for (int index = 0; index < Math.min(8, queued.length()); index++) {
                        JSONObject item = queued.optJSONObject(index);
                        if (item != null && item.optString("state").equals("pending"))
                            return context.getString(R.string.mp4_queue_ready);
                    }
                if (ready()) return context.getString(R.string.mp4_idle);
                String reason = last.optString("readiness_error");
                if (selectedMv()) return reason.matches("[A-Za-z0-9_]{1,96}") && !reason.equals("none")
                        ? context.getString(R.string.mp4_selected_not_ready_reason, reason)
                        : context.getString(R.string.mp4_selected_not_ready);
                String selectionError = last.optString("selection_error");
                if (!selectionError.isEmpty() && !selectionError.equals("none")) reason = selectionError;
                return reason.matches("[A-Za-z0-9_]{1,96}") && !reason.equals("none")
                        && !reason.equals("open_selected_mv_first")
                        ? context.getString(R.string.mp4_not_ready_reason, reason)
                        : context.getString(R.string.mp4_not_ready);
        }
    }

    static final class SaveTarget {
        final File root;
        final String outputId, jobId;
        SaveTarget(File root, String outputId, String jobId) { this.root = root; this.outputId = outputId; this.jobId = jobId; }
        String identity() { return root.getPath() + "\n" + outputId; }
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
    private static SaveTarget sessionSaveTarget() throws IOException {
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
    private static synchronized void restoreCompleted(Context context) {
        application = context.getApplicationContext();
        if (documentHistory == null) {
            try {
                android.content.SharedPreferences preferences = application.getSharedPreferences("mp4_export", Context.MODE_PRIVATE);
                documentHistory = new DocumentPickerHistory(new DocumentPickerHistory.Store() {
                    public String read() { return preferences.getString("document_picker_events", ""); }
                    public void write(String value) { preferences.edit().putString("document_picker_events", value).apply(); }
                });
            } catch (RuntimeException unavailable) { /* Optional diagnostics never prevent a save. */ }
        }
        if (completedExports != null) return;
        try {
            android.content.SharedPreferences preferences = application.getSharedPreferences("mp4_export", Context.MODE_PRIVATE);
            completedExports = new Mp4CompletedExports(application.getFilesDir(), new Mp4CompletedExports.Store() {
                public Set<String> read() { return new HashSet<>(preferences.getStringSet("completed_outputs", java.util.Collections.emptySet())); }
                public boolean write(Set<String> values) { return preferences.edit().putStringSet("completed_outputs", new HashSet<>(values)).commit(); }
            });
            completedExports.recoverLegacyOneShots();
        } catch (IOException | RuntimeException unavailable) { /* Native queue rows remain reachable while storage recovers. */ }
    }
    private static void rememberCompletedOutputs() {
        Mp4CompletedExports registry = completedExports;
        if (registry == null) return;
        try {
            SaveTarget target = sessionSaveTarget(); registry.remember(target.root, target.outputId, target.jobId);
        } catch (IOException | RuntimeException unavailable) { /* A transient session is never a completed bookmark. */ }
        JSONArray jobs = lastQueue.optJSONArray("jobs");
        if (jobs != null) for (int index = 0; index < Math.min(8, jobs.length()); index++) {
            JSONObject job = jobs.optJSONObject(index);
            if (job == null || !"completed".equals(job.optString("state"))) continue;
            try {
                SaveTarget target = queuedSaveTarget(job.optString("job_id"));
                registry.remember(target.root, target.outputId, target.jobId);
            } catch (IOException | RuntimeException unavailable) { /* Never adopt partial or missing output. */ }
        }
    }
    static ArrayList<SaveTarget> completedOutputs() {
        ArrayList<SaveTarget> result = new ArrayList<>();
        try { result.add(sessionSaveTarget()); } catch (IOException unavailable) { }
        Mp4CompletedExports registry = completedExports;
        if (registry != null) for (Mp4CompletedExports.Entry entry : registry.entries())
            addCompleted(result, new SaveTarget(entry.root, entry.outputId, entry.jobId));
        JSONArray jobs = lastQueue.optJSONArray("jobs");
        if (jobs != null) for (int index = jobs.length() - 1; index >= 0; index--) {
            JSONObject job = jobs.optJSONObject(index); if (job == null) continue;
            try { addCompleted(result, queuedSaveTarget(job.optString("job_id"))); } catch (IOException unavailable) { }
        }
        return result;
    }
    private static void addCompleted(ArrayList<SaveTarget> outputs, SaveTarget target) {
        for (SaveTarget known : outputs) if (known.identity().equals(target.identity())) return;
        outputs.add(target);
    }
    private static SaveTarget currentSaveTarget() throws IOException {
        ArrayList<SaveTarget> outputs = completedOutputs();
        if (outputs.isEmpty()) throw new IOException("No completed export");
        return outputs.get(0);
    }
    static boolean hasCompletedOutput() {
        try { currentSaveTarget(); return true; } catch (IOException invalid) { return false; }
    }
    static boolean oneShotCompletionReady() {
        try { return completedExports != null && exportRoot != null && completedExports.rememberDirectory(exportRoot); }
        catch (IOException | RuntimeException unavailable) { return false; }
    }
    static boolean canSave() {
        if (saving || pendingSaveId != null) return false;
        try { currentSaveTarget(); return true; } catch (IOException invalid) { return false; }
    }
    static boolean saveInProgress() { return saving || pendingSaveId != null; }
    static void noteDocumentLaunch(Context context, int request, Intent intent, String origin) {
        try {
            restoreCompleted(context);
            if (documentHistory != null && intent != null) documentHistory.launch(request, intent.getAction(), intent.getType(), origin);
        } catch (RuntimeException unavailable) { /* Optional diagnostics. */ }
    }
    static void noteDocumentResult(Context context, int request, int result) {
        try {
            restoreCompleted(context);
            if (documentHistory != null) documentHistory.result(request,
                    result == Activity.RESULT_OK ? "ok" : result == Activity.RESULT_CANCELED ? "cancelled" : "other");
        } catch (RuntimeException unavailable) { /* Optional diagnostics. */ }
    }
    static void noteDocumentUnavailable(Context context, int request) {
        try {
            restoreCompleted(context);
            if (documentHistory != null) documentHistory.result(request, "unavailable");
        } catch (RuntimeException unavailable) { /* Optional diagnostics. */ }
    }
    private static JSONArray documentDiagnostics() {
        JSONArray rows = new JSONArray();
        if (documentHistory != null) for (DocumentPickerHistory.Event event : documentHistory.snapshot()) try {
            rows.put(new JSONObject().put("request_code", event.request).put("event", event.event).put("action", event.action)
                    .put("mime", event.mime).put("origin", event.origin).put("result", event.result));
        } catch (Exception invalid) { /* Only fixed bounded scalars are exported. */ }
        return rows;
    }
    static void bindSaveButton(Button button, Activity activity) {
        SaveTarget target = null;
        try { target = currentSaveTarget(); } catch (IOException unavailable) { }
        bindSaveButton(button, activity, target);
    }
    static void bindSaveButton(Button button, Activity activity, SaveTarget target) {
        final SaveTarget rendered = target;
        final String binding = last.optString("phase") + "\n" + (target == null ? "" : target.identity());
        button.setEnabled(target != null && !saveInProgress());
        if (binding.equals(button.getTag())) return;
        button.cancelPendingInputEvents(); button.setPressed(false); button.setTag(binding);
        button.setOnClickListener(view -> {
            // A queued click from a replaced phase/output cannot select a
            // different completed movie or launch an external Activity.
            if (rendered == null || !binding.equals(button.getTag())
                    || !binding.equals(last.optString("phase") + "\n" + rendered.identity())) return;
            requestSave(activity, rendered);
        });
    }
    private static void openSave(Activity activity, SaveTarget target) {
        if (activity == null || activity.isDestroyed() || activity.isFinishing() || saving || pendingSaveId != null) return;
        pendingSaveId = target.outputId; pendingSaveRoot = target.root; pendingSaveOwner = activity.getClass().getName();
        dismissed = false;
        Intent picker = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("video/mp4")
                .putExtra(Intent.EXTRA_TITLE, activity.getString(R.string.mp4_export_filename, pendingSaveId));
        try { noteDocumentLaunch(activity, SAVE_DOCUMENT, picker, "mp4_save"); activity.startActivityForResult(picker, SAVE_DOCUMENT); }
        catch (RuntimeException unavailable) { noteDocumentUnavailable(activity, SAVE_DOCUMENT); clearPendingSave(); Toast.makeText(activity, R.string.mp4_save_failed, Toast.LENGTH_LONG).show(); wake(); }
    }
    static void requestSave(Activity activity) {
        if (saving || pendingSaveId != null) return;
        try { openSave(activity, currentSaveTarget()); } catch (IOException invalid) { /* Keep unavailable outputs private. */ }
    }
    static void requestSave(Activity activity, String jobId) {
        if (saving || pendingSaveId != null) return;
        try { openSave(activity, queuedSaveTarget(jobId)); } catch (IOException invalid) { /* The completed file stays available for retry. */ }
    }
    static void requestSave(Activity activity, SaveTarget target) {
        if (target == null || saving || pendingSaveId != null) return;
        for (SaveTarget known : completedOutputs()) if (known.identity().equals(target.identity())) {
            try { completedFile(known.root, known.outputId); openSave(activity, known); } catch (IOException unavailable) { }
            return;
        }
    }
    static boolean canDeleteCompleted(SaveTarget target) {
        return target != null && !saveInProgress() && (target.jobId == null
                || queueConfigured && lastQueue.optBoolean("available") && !lastQueue.optBoolean("command_pending"));
    }
    /** Called only by the affirmative button of the completed-video deletion dialog. */
    static boolean deleteCompleted(SaveTarget target) {
        if (!canDeleteCompleted(target)) return false;
        for (SaveTarget known : completedOutputs()) if (known.identity().equals(target.identity())) {
            if (known.jobId != null) return queueCommand(2, known.jobId, 1);
            try {
                File source = completedFile(known.root, known.outputId);
                Files.delete(source.toPath());
                if (completedExports != null) completedExports.forget(new Mp4CompletedExports.Entry(known.root, known.outputId, known.jobId));
                wake(); return true;
            } catch (IOException | RuntimeException unavailable) { return false; }
        }
        return false;
    }
    private static void clearPendingSave() { pendingSaveId = null; pendingSaveRoot = null; pendingSaveOwner = null; }
    static boolean activityResult(Activity activity, int request, int result, Intent data) {
        if (request != SAVE_DOCUMENT) return false;
        noteDocumentResult(activity, request, result);
        if (pendingSaveOwner != null && !pendingSaveOwner.equals(activity.getClass().getName())) return true;
        String id = pendingSaveId; File root = pendingSaveRoot; clearPendingSave(); dismissed = false;
        if (result != Activity.RESULT_OK || data == null || data.getData() == null || id == null) { wake(); return true; }
        Uri destination = data.getData(); Context context = activity.getApplicationContext(); saving = true; wake();
        new Thread(() -> {
            boolean success = false; String copyStage = "save_validate_source";
            try {
                File source = completedFile(root, id); long expected = source.length(), copied = 0;
                copyStage = "save_open_document";
                try (FileInputStream input = new FileInputStream(source); OutputStream output = context.getContentResolver().openOutputStream(destination, "w")) {
                    if (output == null) throw new IOException("Document output unavailable");
                    copyStage = "save_copy_document";
                    byte[] buffer = new byte[131072]; int read;
                    while ((read = input.read(buffer)) != -1) { output.write(buffer, 0, read); copied += read; }
                    output.flush();
                }
                copyStage = "save_verify_copy";
                if (copied != expected || source.length() != expected) throw new IOException("Completed file changed");
                success = true;
            } catch (Exception ignored) {
                try { context.getSharedPreferences("mp4_export", Context.MODE_PRIVATE).edit()
                        .putString("last_save_failure_stage", copyStage).apply(); }
                catch (RuntimeException unavailable) { /* The completed file remains retryable. */ }
            }
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
        if (pendingSaveId != null && pendingSaveRoot != null) {
            state.putString("mp4_save_id", pendingSaveId); state.putString("mp4_save_root", pendingSaveRoot.getPath());
            state.putString("mp4_save_owner", pendingSaveOwner);
        }
    }
    static void restoreState(Context context, Bundle state) {
        restoreCompleted(context);
        if (state == null || pendingSaveId != null) return;
        try {
            String id = state.getString("mp4_save_id"), path = state.getString("mp4_save_root");
            if (id == null || path == null) return;
            File root = privateDirectory(context.getFilesDir().getCanonicalFile(), path); completedFile(root, id);
            pendingSaveId = id; pendingSaveRoot = root; pendingSaveOwner = state.getString("mp4_save_owner");
        } catch (IOException invalid) { /* A stale picker cannot select an arbitrary private file. */ }
    }
}
