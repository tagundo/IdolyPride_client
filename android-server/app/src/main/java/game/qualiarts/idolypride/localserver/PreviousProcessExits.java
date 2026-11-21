package game.qualiarts.idolypride.localserver;

import android.app.ActivityManager;
import android.app.ApplicationExitInfo;
import android.content.Context;
import android.os.Build;
import android.util.Base64;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/** App-owned exit metadata only; no logcat, other packages, paths or descriptions. */
final class PreviousProcessExits {
    static final int MAX_RECORDS = 5;
    static final int TRACE_LIMIT = 128 * 1024;
    static final long TIMEOUT_MILLIS = 2500;
    private static final Collector COLLECTOR = new Collector();
    private static final AtomicBoolean CLOSE_BUSY = new AtomicBoolean();
    private static final ExecutorService CLOSE_IO = Executors.newSingleThreadExecutor(task -> daemon(task, "exit-trace-close"));

    interface ExitRecord {
        int reason(); int status(); long timestamp(); int importance(); int pid(); String processName();
        InputStream trace() throws IOException;
    }
    interface Backend { List<ExitRecord> query(int maximum) throws Exception; }

    static JSONObject collect(Context context) {
        final int api = Build.VERSION.SDK_INT;
        if (api < 30) return document(api, "unsupported", "android_api_below_30", Collections.emptyList(), false);
        Context app = context.getApplicationContext();
        return COLLECTOR.collect(maximum -> Api30.query(app, maximum), api, TIMEOUT_MILLIS);
    }

    private static Thread daemon(Runnable task, String name) {
        Thread thread = new Thread(task, name); thread.setDaemon(true); return thread;
    }

    /** Keep API30 classes/methods out of the path executed on earlier Android. */
    private static final class Api30 {
        static List<ExitRecord> query(Context context, int maximum) {
            ActivityManager manager = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);
            if (manager == null) throw new IllegalStateException("Activity manager unavailable");
            List<ApplicationExitInfo> exits = manager.getHistoricalProcessExitReasons(context.getPackageName(), 0, maximum);
            List<ExitRecord> result = new ArrayList<>();
            if (exits != null) for (int i = 0; i < Math.min(maximum, exits.size()); i++) {
                ApplicationExitInfo info = exits.get(i);
                if (info == null) continue;
                result.add(new ExitRecord() {
                    public int reason() { return info.getReason(); }
                    public int status() { return info.getStatus(); }
                    public long timestamp() { return info.getTimestamp(); }
                    public int importance() { return info.getImportance(); }
                    public int pid() { return info.getPid(); }
                    public String processName() { return info.getProcessName(); }
                    public InputStream trace() throws IOException { return info.getTraceInputStream(); }
                });
            }
            return result;
        }
    }

    private static final class Trace {
        final String status, error;
        final byte[] bytes;
        Trace(String status, byte[] bytes, String error) { this.status = status; this.bytes = bytes; this.error = error; }
    }
    private static final class Record {
        final ExitRecord source;
        final int reason, status, importance, pid;
        final long timestamp;
        final String processName;
        volatile Trace trace;
        Record(ExitRecord source) {
            this.source = source; reason = source.reason(); status = source.status(); importance = source.importance();
            pid = source.pid(); timestamp = source.timestamp(); processName = boundedName(source.processName());
            // Public Android API supplies ANR traces, and Android12+ can also
            // supply binary native tombstones. Null streams remain normal.
            trace = new Trace(reason == 5 || reason == 6 ? "pending" : "not_applicable", null, null);
        }
    }
    private static String boundedName(String value) {
        if (value == null) return "";
        StringBuilder result = new StringBuilder();
        for (int i = 0; i < value.length() && result.length() < 256; i++) {
            char c = value.charAt(i); if (c >= 32 && c != 127) result.append(c);
        }
        return result.toString();
    }
    private static final class Handle {
        final InputStream stream;
        final AtomicBoolean claimed = new AtomicBoolean();
        Handle(InputStream stream) { this.stream = stream; }
        void close() throws IOException { if (claimed.compareAndSet(false, true)) stream.close(); }
        void closeWithoutBlockingExport() {
            if (!CLOSE_BUSY.compareAndSet(false, true)) return;
            if (!claimed.compareAndSet(false, true)) { CLOSE_BUSY.set(false); return; }
            try {
                CLOSE_IO.execute(() -> {
                    try { stream.close(); } catch (Exception ignored) { }
                    finally { CLOSE_BUSY.set(false); }
                });
            } catch (RuntimeException rejected) { claimed.set(false); CLOSE_BUSY.set(false); }
        }
    }
    private static final class Work {
        final long started = System.nanoTime(), timeoutNanos;
        final AtomicReference<Handle> active = new AtomicReference<>();
        volatile List<Record> records = Collections.emptyList();
        volatile boolean cancelled, queried;
        volatile Thread thread;
        volatile String error;
        Work(long timeoutMillis) { timeoutNanos = TimeUnit.MILLISECONDS.toNanos(timeoutMillis); }
        boolean expired() { return cancelled || System.nanoTime() - started >= timeoutNanos; }
        void stop() {
            cancelled = true;
            Thread running = thread; if (running != null) running.interrupt();
            Handle handle = active.get(); if (handle != null) handle.closeWithoutBlockingExport();
        }
    }

    /** One outstanding reader even when a vendor Binder/stream ignores interrupts. */
    static final class Collector {
        private final AtomicBoolean busy = new AtomicBoolean();
        private final ExecutorService io = Executors.newSingleThreadExecutor(task -> daemon(task, "previous-process-exits"));
        JSONObject collect(Backend backend, int api, long timeoutMillis) {
            if (api < 30) return document(api, "unsupported", "android_api_below_30", Collections.emptyList(), false);
            if (!busy.compareAndSet(false, true)) return document(api, "busy", "previous_collection_pending", Collections.emptyList(), false);
            Work work = new Work(timeoutMillis);
            FutureTask<Void> task = new FutureTask<>(() -> {
                work.thread = Thread.currentThread();
                try { read(backend, work); }
                finally { work.thread = null; Thread.interrupted(); busy.set(false); }
                return null;
            });
            try { io.execute(task); }
            catch (RuntimeException rejected) { busy.set(false); return document(api, "failed", "history_worker_unavailable", work.records, false); }
            try {
                task.get(timeoutMillis, TimeUnit.MILLISECONDS);
                return document(api, work.error == null ? "complete" : work.queried ? "partial" : "failed", work.error, work.records,
                        "history_collection_timeout".equals(work.error));
            } catch (TimeoutException timeout) {
                work.stop();
                return document(api, work.queried ? "partial" : "timed_out", "history_collection_timeout", work.records, true);
            } catch (InterruptedException interrupted) {
                work.stop(); Thread.currentThread().interrupt();
                return document(api, "partial", "history_collection_interrupted", work.records, true);
            } catch (ExecutionException failed) {
                work.stop(); return document(api, "failed", "history_collection_failed", work.records, false);
            }
        }
    }
    private static void read(Backend backend, Work work) {
        try {
            List<ExitRecord> incoming = backend.query(MAX_RECORDS);
            List<Record> records = new ArrayList<>();
            if (incoming != null) for (int i = 0; i < Math.min(MAX_RECORDS, incoming.size()); i++) {
                try { records.add(new Record(incoming.get(i))); }
                catch (RuntimeException invalid) { work.error = "exit_record_unavailable"; }
            }
            work.records = Collections.unmodifiableList(records); work.queried = true;
            for (Record record : records) {
                if (work.expired()) { work.error = "history_collection_timeout"; return; }
                if (!record.trace.status.equals("pending")) continue;
                record.trace = readTrace(record.source, work);
                if (record.trace.error != null) work.error = "exit_trace_unavailable";
            }
        } catch (Exception failure) { work.error = "history_query_failed"; }
        catch (LinkageError unavailable) { work.error = "history_api_unavailable"; }
    }
    private static Trace readTrace(ExitRecord record, Work work) {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream(); Handle handle = null;
        String status = "available", error = null;
        try {
            InputStream stream = record.trace();
            if (stream == null) return new Trace("unavailable", null, null);
            handle = new Handle(stream); work.active.set(handle);
            byte[] buffer = new byte[4096]; int zeroReads = 0;
            while (bytes.size() < TRACE_LIMIT) {
                if (work.expired()) { status = "timed_out"; error = "trace_timeout"; break; }
                int amount = stream.read(buffer, 0, Math.min(buffer.length, TRACE_LIMIT - bytes.size()));
                if (work.expired()) { status = "timed_out"; error = "trace_timeout"; break; }
                if (amount < 0) break;
                if (amount == 0) { if (++zeroReads >= 16) throw new IOException("No trace progress"); continue; }
                zeroReads = 0; bytes.write(buffer, 0, amount);
            }
            // Never consume a byte beyond128KiB, even just to test for EOF.
            if (bytes.size() == TRACE_LIMIT) status = "truncated";
        } catch (Exception failure) { status = work.expired() ? "timed_out" : "failed"; error = work.expired() ? "trace_timeout" : "trace_read_failed"; }
        finally {
            if (handle != null) {
                work.active.compareAndSet(handle, null);
                try { handle.close(); }
                catch (Exception failure) { status = "failed"; error = "trace_close_failed"; }
            }
        }
        return new Trace(status, bytes.toByteArray(), error);
    }
    private static JSONObject document(int api, String status, String error, List<Record> records, boolean timedOut) {
        JSONObject result = new JSONObject(); JSONArray rows = new JSONArray();
        try {
            for (Record record : records) {
                Trace trace = record.trace;
                String traceStatus = timedOut && trace.status.equals("pending") ? "timed_out" : trace.status;
                JSONObject detail = new JSONObject().put("status", traceStatus).put("limit_bytes", TRACE_LIMIT).put("bytes", trace.bytes == null ? 0 : trace.bytes.length);
                if (trace.bytes != null) detail.put("encoding", "base64").put("format", record.reason == 5 && api >= 31
                        ? "android_native_tombstone_proto" : record.reason == 6 ? "android_anr_trace" : "android_application_exit_trace")
                        .put("data", Base64.encodeToString(trace.bytes, Base64.NO_WRAP));
                if (trace.error != null) detail.put("error_code", trace.error);
                rows.put(new JSONObject().put("reason", record.reason).put("status", record.status).put("timestamp_ms", record.timestamp)
                        .put("importance", record.importance).put("pid", record.pid).put("process_name", record.processName).put("trace", detail));
            }
            result.put("schema", 1).put("scope", "self_package").put("supported", api >= 30).put("api_level", api)
                    .put("status", status).put("max_records", MAX_RECORDS).put("trace_limit_bytes", TRACE_LIMIT).put("timeout_ms", TIMEOUT_MILLIS).put("records", rows);
            if (error != null) result.put("error_code", error);
        } catch (JSONException impossible) { throw new IllegalStateException(impossible); }
        return result;
    }
    private PreviousProcessExits() { }
}
