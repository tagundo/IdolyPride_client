package game.qualiarts.idolypride.qa.ui;

import android.content.Context;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import org.json.JSONArray;
import org.json.JSONObject;

/** Read cached native observations only; never enter a Unity API or start work. */
final class QaMp4Observation {
    private static final String CLASS = "game.qualiarts.idolypride.localserver.UnifiedMP4Export";
    private static final String[] STATUS = {"schema", "ready", "phase", "readiness_error", "error_code",
        "export_id", "unity_ticks", "capture_acks", "width", "height", "source_width", "source_height",
        "fps_num", "fps_den", "video_codec", "video_bitrate", "frames", "total_frames",
        "audio_frames", "total_audio_frames", "bytes_written", "paused", "pause_requested", "pause_reason"};
    private static final String[] OBSERVATION = {"schema", "pipeline", "source_valid", "playerloop_frame", "source_kind",
        "source_identity", "source_time", "source_paused", "coordinator_active", "native_clock_owned",
        "native_clock_held", "simulation_tick", "accepted_frames", "source_restored",
        "clock_settings_restored", "camera_audio_restored", "dependent_state_restored", "world_admission", "sample_phase",
        "acquired_source_valid", "acquired_source_identity", "acquired_source_time", "acquired_source_paused"};

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
