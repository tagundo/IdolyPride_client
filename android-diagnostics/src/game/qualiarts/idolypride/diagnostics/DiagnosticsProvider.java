package game.qualiarts.idolypride.diagnostics;

import android.app.Application;
import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.net.Uri;
import android.net.TrafficStats;
import android.os.Process;
import android.os.SystemClock;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.Proxy;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONObject;

/** Optional diagnostics in a separately installed game; never reads another UID. */
public final class DiagnosticsProvider extends ContentProvider {
    private static final String PACKAGE = "game.qualiarts.idolypride.local.diagnostics";
    private static final String ENDPOINT = "http://127.0.0.1:8080/diagnostics/client";
    private static final long SESSION_MS = 30 * 60 * 1000L;
    private static final int MAX_BODY = 32768;
    private final LogSanitizer sanitizer = new LogSanitizer();
    private final ArrayDeque<JSONObject> queue = new ArrayDeque<>();
    private volatile java.lang.Process readerProcess;
    private final CountDownLatch readerStarted = new CountDownLatch(1);
    private volatile boolean active = true;

    private static final class AndroidCounters implements TrafficSampler.Counters {
        private final int uid;

        AndroidCounters(int uid) { this.uid = uid; }

        @Override public long elapsedRealtime() { return SystemClock.elapsedRealtime(); }
        @Override public long rxBytes() { return TrafficStats.getUidRxBytes(uid); }
        @Override public long txBytes() { return TrafficStats.getUidTxBytes(uid); }
    }

    @Override public boolean onCreate() {
        if (getContext() == null || !PACKAGE.equals(getContext().getPackageName())
                || !PACKAGE.equals(Application.getProcessName())) return false;
        Thread sender = new Thread(this::runSession, "idoly-safe-diagnostics");
        sender.setDaemon(true);
        sender.start();
        return true;
    }

    private JSONObject status(String code) throws Exception {
        return new JSONObject().put("kind", "status").put("code", code);
    }

    private void enqueue(JSONObject event) {
        synchronized (queue) {
            if (queue.size() >= 200) queue.removeFirst();
            queue.addLast(event);
        }
    }

    private void collect() throws Exception {
        List<LogSanitizer.Event> events;
        synchronized (sanitizer) { events = sanitizer.drain(); }
        for (LogSanitizer.Event event : events) {
            JSONObject json = new JSONObject().put("kind", event.kind);
            if ("exception".equals(event.kind)) {
                json.put("type", event.type).put("frames", new JSONArray(event.frames));
            } else { json.put("code", event.code); }
            enqueue(json);
        }
    }

    private void readLogs() {
        try {
            readerProcess = new ProcessBuilder("/system/bin/logcat", "-b", "main",
                    "--pid=" + Process.myPid(), "-v", "brief", "-T", "1",
                    "Unity:V", "IdolyprideLog:V", "AndroidRuntime:E", "*:S")
                    .redirectErrorStream(true).start();
            enqueue(status("logcat_started"));
            readerStarted.countDown();
            try (BufferedReader input = new BufferedReader(new InputStreamReader(
                    readerProcess.getInputStream(), StandardCharsets.UTF_8), 2048)) {
                StringBuilder line = new StringBuilder();
                boolean oversized = false;
                int value;
                while (active && (value = input.read()) != -1) {
                    if (value == '\n') {
                        if (!oversized) synchronized (sanitizer) { sanitizer.accept(line.toString()); }
                        line.setLength(0);
                        oversized = false;
                    } else if (line.length() < 4096) { line.append((char) value); }
                    else { oversized = true; }
                }
            }
        } catch (Exception ignored) {
            // Collection is optional and must never block or crash the game.
        } finally {
            if (readerProcess != null) readerProcess.destroy();
            try { enqueue(status("logcat_stopped")); } catch (Exception ignored) { }
        }
    }

    private void sampleTraffic(TrafficSampler sampler, long deadline) {
        try {
            while (active && SystemClock.elapsedRealtime() < deadline) {
                TrafficSampler.Sample sample = sampler.poll();
                if (sample != null) {
                    if (sample.unavailable) {
                        enqueue(status("network_unavailable"));
                        return;
                    }
                    enqueue(new JSONObject().put("kind", "network").put("rx_bytes", sample.rxBytes)
                            .put("tx_bytes", sample.txBytes).put("elapsed_ms", sample.elapsedMs));
                }
                Thread.sleep(1000);
            }
        } catch (Exception ignored) {
            if (active) try { enqueue(status("network_unavailable")); } catch (Exception ignoredAgain) { }
        }
    }

    private void runSession() {
        long deadline = SystemClock.elapsedRealtime() + SESSION_MS;
        long retryDelay = 2000;
        try {
            enqueue(status("collector_started"));
            final int uid = Process.myUid();
            try {
                TrafficSampler sampler = new TrafficSampler(new AndroidCounters(uid));
                Thread traffic = new Thread(() -> sampleTraffic(sampler, deadline), "idoly-own-uid-bytes");
                traffic.setDaemon(true);
                traffic.start();
            } catch (Exception ignored) { enqueue(status("network_unavailable")); }
            Thread reader = new Thread(this::readLogs, "idoly-own-pid-logcat");
            reader.setDaemon(true);
            reader.start();
            // Wait for the own-PID logcat reader before the optional native
            // probe logs its first fixed checkpoint. Java-only probes omit it.
            if (readerStarted.await(2, TimeUnit.SECONDS)) {
                try { NativePhaseProbe.start(); } catch (Throwable ignored) { enqueue(status("probe_unavailable")); }
            } else { enqueue(status("probe_unavailable")); }
            while (SystemClock.elapsedRealtime() < deadline) {
                collect();
                List<JSONObject> batch = new ArrayList<>();
                byte[] body = null;
                synchronized (queue) {
                    for (JSONObject event : queue) {
                        if (batch.size() >= 32) break;
                        batch.add(event);
                        byte[] candidate = new JSONObject().put("schema", 1).put("source", "android-game")
                                .put("events", new JSONArray(batch)).toString().getBytes(StandardCharsets.UTF_8);
                        if (candidate.length > MAX_BODY) { batch.remove(batch.size() - 1); break; }
                        body = candidate;
                    }
                }
                if (body == null) { Thread.sleep(500); continue; }
                if (send(body)) {
                    synchronized (queue) {
                        for (JSONObject event : batch) queue.removeFirstOccurrence(event);
                    }
                    retryDelay = 2000;
                } else { retryDelay = Math.min(30000, retryDelay * 2); }
                Thread.sleep(retryDelay);
            }
        } catch (Exception ignored) {
            // No raw log, exception message or transport error is emitted.
        } finally {
            active = false;
            if (readerProcess != null) readerProcess.destroy();
        }
    }

    private boolean send(byte[] body) {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(ENDPOINT).openConnection(Proxy.NO_PROXY);
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(1000);
            connection.setReadTimeout(1000);
            connection.setRequestMethod("POST");
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            connection.setFixedLengthStreamingMode(body.length);
            connection.setDoOutput(true);
            try (OutputStream output = connection.getOutputStream()) { output.write(body); }
            int status = connection.getResponseCode();
            return status >= 200 && status < 300;
        } catch (Exception ignored) { return false; }
        finally { if (connection != null) connection.disconnect(); }
    }

    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] args, String order) { return null; }
    @Override public String getType(Uri uri) { return null; }
    @Override public Uri insert(Uri uri, ContentValues values) { return null; }
    @Override public int delete(Uri uri, String selection, String[] args) { return 0; }
    @Override public int update(Uri uri, ContentValues values, String selection, String[] args) { return 0; }
}
