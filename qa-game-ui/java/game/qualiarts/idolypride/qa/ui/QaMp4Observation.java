package game.qualiarts.idolypride.qa.ui;

import android.content.Context;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Iterator;
import org.json.JSONArray;
import org.json.JSONObject;

/** Read cached native observations only; never enter a Unity API or start work. */
final class QaMp4Observation {
    private static final String CLASS = "game.qualiarts.idolypride.localserver.UnifiedMP4Export";
    private static final String[] STATUS = {"schema", "ready", "phase", "readiness_error", "error_code",
        "export_id", "unity_ticks", "capture_acks", "width", "height", "source_width", "source_height",
        "fps_num", "fps_den", "video_codec", "video_bitrate", "frames", "total_frames",
        "audio_frames", "total_audio_frames", "bytes_written", "paused", "pause_requested", "pause_reason",
        "selected_mv", "selection_error", "restoration_error", "pipeline_mode", "resume_phase"};
    private static final String[] OBSERVATION = {"schema", "pipeline", "source_valid", "playerloop_frame", "source_kind",
        "source_identity", "source_time", "source_paused", "coordinator_active", "native_clock_owned",
        "native_clock_held", "simulation_tick", "accepted_frames", "source_restored",
        "clock_settings_restored", "camera_audio_restored", "dependent_state_restored", "world_admission", "sample_phase",
        "acquired_source_valid", "acquired_source_identity", "acquired_source_time", "acquired_source_paused",
        // The QA verdict gates read the actual render target, draw count and the
        // native restoration checkpoint; without them no export could ever pass.
        "render_width", "render_height", "rendered_simulation_ticks",
        "restored_source_valid", "restored_source_identity", "restored_source_time", "restored_source_paused"};
    private static final String SAFE_TEXT = "[A-Za-z0-9_:.\\-/+$#<>(), ]{0,200}";
    private static final int MAX_DIAGNOSTICS = 60000;

    static String snapshot(Context context) {
        try {
            Class<?> type = Class.forName(CLASS, false, context.getClassLoader());
            Field initialized = type.getDeclaredField("initialized");
            if (initialized.getType() != boolean.class) return LoopbackUiServer.error("mp4_observer_type_differs");
            initialized.setAccessible(true);
            if (!initialized.getBoolean(null)) return LoopbackUiServer.error("mp4_observer_not_initialized");
            Method status = type.getDeclaredMethod("nativeStatus");
            if (status.getReturnType() != String.class) return LoopbackUiServer.error("mp4_observer_type_differs");
            status.setAccessible(true);
            Object result = status.invoke(null);
            if (!(result instanceof String) || ((String) result).length() > 65536)
                return LoopbackUiServer.error("mp4_observer_payload_invalid");
            JSONObject raw = new JSONObject((String) result), selected = copyScalars(raw, STATUS);
            JSONObject observed = raw.optJSONObject("observation");
            if (observed != null) selected.put("observation", copyScalars(observed, OBSERVATION));
            Method queueStatus = type.getDeclaredMethod("nativeQueueStatus");
            if (queueStatus.getReturnType() != String.class) return LoopbackUiServer.error("mp4_observer_type_differs");
            queueStatus.setAccessible(true);
            Object queued = queueStatus.invoke(null);
            if (!(queued instanceof String) || ((String) queued).length() > 65536)
                return LoopbackUiServer.error("mp4_observer_payload_invalid");
            JSONObject queue = new JSONObject((String) queued);
            JSONObject safeQueue = copyScalars(queue, new String[] {"schema", "available", "command_pending",
                "error_code", "running", "paused", "phase", "last_added_job_id", "current_job_id"});
            JSONArray jobs = queue.optJSONArray("jobs");
            if (jobs == null || jobs.length() > 8) return LoopbackUiServer.error("mp4_observer_queue_invalid");
            safeQueue.put("job_count", jobs.length());
            return new JSONObject().put("ok", true).put("schema", 1).put("qa_only", true)
                .put("read_only", true).put("native", selected).put("queue", safeQueue).toString();
        } catch (ReflectiveOperationException | RuntimeException | LinkageError | org.json.JSONException unavailable) {
            return LoopbackUiServer.error("mp4_observer_unavailable");
        }
    }

    /**
     * The app's own export trace for QA evidence: native status (with scene
     * diagnostics), the native export-trace document and the app's user
     * diagnostics-export document. Read-only; every value is re-bounded here.
     */
    static String diagnostics(Context context, String application, String applicationError) {
        try {
            Class<?> type = Class.forName(CLASS, false, context.getClassLoader());
            Field initialized = type.getDeclaredField("initialized");
            if (initialized.getType() != boolean.class) return LoopbackUiServer.error("mp4_observer_type_differs");
            initialized.setAccessible(true);
            boolean ready = initialized.getBoolean(null);
            JSONObject result = new JSONObject().put("ok", true).put("schema", 1).put("qa_only", true)
                .put("read_only", true).put("native_initialized", ready);
            if (ready) {
                result.put("native_status", nativeDocument(type, "nativeStatus"));
                result.put("native_diagnostics", nativeDocument(type, "nativeDiagnostics"));
            }
            if (application != null) result.put("app_diagnostics", bounded(new JSONObject(application), 0));
            else result.put("app_diagnostics_error", applicationError);
            String encoded = result.toString();
            return encoded.length() <= MAX_DIAGNOSTICS ? encoded : LoopbackUiServer.error("mp4_diagnostics_oversized");
        } catch (ReflectiveOperationException | RuntimeException | LinkageError | org.json.JSONException unavailable) {
            return LoopbackUiServer.error("mp4_diagnostics_unavailable");
        }
    }

    /** UnifiedMP4Export.diagnostics(), the user diagnostics-export document; call on the main thread. */
    static String applicationDiagnostics(Context context) {
        try {
            Class<?> type = Class.forName(CLASS, false, context.getClassLoader());
            Method method = type.getDeclaredMethod("diagnostics");
            if (method.getReturnType() != JSONObject.class) return null;
            method.setAccessible(true);
            Object value = method.invoke(null);
            return value instanceof JSONObject ? value.toString() : null;
        } catch (ReflectiveOperationException | RuntimeException | LinkageError unavailable) {
            return null;
        }
    }

    private static Object nativeDocument(Class<?> type, String name) {
        try {
            Method method = type.getDeclaredMethod(name);
            if (method.getReturnType() != String.class) return "type_differs";
            method.setAccessible(true);
            Object value = method.invoke(null);
            if (!(value instanceof String) || ((String) value).isEmpty() || ((String) value).length() > 65536)
                return "payload_unavailable";
            return bounded(new JSONObject((String) value), 0);
        } catch (ReflectiveOperationException | RuntimeException | LinkageError | org.json.JSONException unavailable) {
            return "unavailable";
        }
    }

    /** Structural copy: fixed-shape keys, finite numbers, short code-like strings, bounded depth/width. */
    static Object bounded(Object value, int depth) throws org.json.JSONException {
        if (value == JSONObject.NULL || value instanceof Boolean || value instanceof Integer || value instanceof Long)
            return value;
        if (value instanceof Number) return Double.isFinite(((Number) value).doubleValue()) ? value : JSONObject.NULL;
        if (value instanceof String) return ((String) value).matches(SAFE_TEXT) ? value : "omitted_text";
        if (depth >= 8) return "omitted_depth";
        if (value instanceof JSONObject) {
            JSONObject source = (JSONObject) value, result = new JSONObject();
            Iterator<String> keys = source.keys();
            for (int count = 0; keys.hasNext() && count < 128; count++) {
                String key = keys.next();
                if (key.matches("[A-Za-z0-9_]{1,64}")) result.put(key, bounded(source.get(key), depth + 1));
            }
            return result;
        }
        if (value instanceof JSONArray) {
            JSONArray source = (JSONArray) value, result = new JSONArray();
            for (int index = 0; index < Math.min(64, source.length()); index++) result.put(bounded(source.get(index), depth + 1));
            return result;
        }
        return "omitted_value";
    }

    private static JSONObject copyScalars(JSONObject source, String[] keys) throws org.json.JSONException {
        JSONObject result = new JSONObject();
        for (String key : keys) {
            if (!source.has(key)) continue;
            Object value = source.get(key);
            if (value == JSONObject.NULL || value instanceof Boolean
                    || value instanceof Integer || value instanceof Long) result.put(key, value);
            else if (value instanceof Number && Double.isFinite(((Number) value).doubleValue())) result.put(key, value);
            else if (value instanceof String && ((String) value).matches("[A-Za-z0-9_:.\\-]{0,96}")) result.put(key, value);
            else throw new org.json.JSONException("non_scalar_observation");
        }
        return result;
    }
}
