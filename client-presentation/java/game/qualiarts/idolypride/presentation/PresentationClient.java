package game.qualiarts.idolypride.presentation;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.math.BigDecimal;
import java.net.HttpURLConnection;
import java.net.Proxy;
import java.net.URL;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.Callable;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Future;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.SynchronousQueue;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicReference;

/** A bounded, account-free loopback protocol. No Android or JSON-library dependency. */
public final class PresentationClient {
    public static final int MAX_BYTES = 8192;
    public static final int MAX_RENDER_PROBE_BYTES = 2048;
    private static final String ORIGIN = "http://127.0.0.1:8080";
    private static final Set<String> CONFIG_KEYS = keys("schema", "revision", "custom_graphics", "quality",
            "target_fps", "render_scale", "max_buffer_pixel", "anti_aliasing", "shadow_resolution", "expand_photography");
    private static final Set<String> STATUS_KEYS = keys("schema", "bridge_version", "revision", "status", "capabilities", "metrics");
    private static final Set<String> CAPABILITIES = keys("fps", "quality", "resolution", "anti_aliasing", "shadow", "expanded_photography");
    private static final Set<String> METRICS = keys("screen_width", "screen_height", "render_width", "render_height",
            "camera_aspect", "base_vertical_fov", "vertical_fov");
    private static final Set<String> STATUSES = keys("waiting", "applied", "disabled", "unsupported", "waiting_for_scene", "init_failed");
    private static final Set<String> PLAYBACK_KEYS = keys("schema", "revision", "wait_for_orientation");
    private static final Set<String> PLAYBACK_STATUS_KEYS = keys("schema", "bridge_version", "revision",
            "wait_for_orientation", "supported", "applied");
    private static final Set<String> RENDER_PROBE_KEYS = keys("schema", "state", "actual_mode", "graphics_api",
            "callback_tid", "observations", "sample_age_ms", "cpu_frame_ms", "gpu_frame_ms", "timing_age_ms");
    private static final Set<String> RENDER_PROBE_STATES = keys("waiting", "observed", "unsupported", "init_failed");
    // No native code ran, so no preference revision or capability was applied.
    static String startupFailureStatus() {
        return "{\"schema\":1,\"bridge_version\":1,\"revision\":0,\"status\":\"init_failed\","
            + "\"capabilities\":{\"fps\":false,\"quality\":false,\"resolution\":false,"
            + "\"anti_aliasing\":false,\"shadow\":false,\"expanded_photography\":false},"
            + "\"metrics\":{\"screen_width\":0,\"screen_height\":0,\"render_width\":0,\"render_height\":0,"
            + "\"camera_aspect\":0,\"base_vertical_fov\":0,\"vertical_fov\":0}}";
    }

    public static final class Config {
        public final long revision;
        public final boolean custom, expand;
        public final int quality, fps, maxBufferPixel, aa, shadow;
        public final float scale;
        Config(Map<String, Object> row) throws IOException {
            if (!row.keySet().equals(CONFIG_KEYS) || integer(row.get("schema")) != 1) throw invalid();
            revision = integer(row.get("revision"));
            custom = bool(row.get("custom_graphics"));
            expand = bool(row.get("expand_photography"));
            quality = choice(row.get("quality"), 0, 10, 20, 30, 40, 100);
            fps = choice(row.get("target_fps"), 0, 30, 60, 90, 120);
            aa = choice(row.get("anti_aliasing"), -1, 0, 1, 2);
            shadow = choice(row.get("shadow_resolution"), 0, 512, 1024, 2048, 4096);
            long maximum = integer(row.get("max_buffer_pixel"));
            double value = number(row.get("render_scale"));
            if (revision < 0 || maximum < 256 || maximum > 4096 || maximum % 2 != 0 || value < .25 || value > 2) throw invalid();
            maxBufferPixel = (int) maximum;
            scale = (float) value;
        }
    }

    public static final class PlaybackConfig {
        public final long revision;
        public final boolean waitForOrientation;
        PlaybackConfig(Map<String, Object> row) throws IOException {
            if (!row.keySet().equals(PLAYBACK_KEYS) || integer(row.get("schema")) != 1) throw invalid();
            revision = integer(row.get("revision"));
            waitForOrientation = bool(row.get("wait_for_orientation"));
            if (revision < 0) throw invalid();
        }
    }

    public interface PlaybackNative {
        boolean configure(int schema, long revision, boolean waitForOrientation);
        String status();
    }

    private static Set<String> keys(String... values) { return new HashSet<String>(Arrays.asList(values)); }
    private static IOException invalid() { return new IOException("Invalid presentation protocol"); }
    private static boolean bool(Object value) throws IOException { if (!(value instanceof Boolean)) throw invalid(); return (Boolean) value; }
    private static long integer(Object value) throws IOException {
        if (!(value instanceof Numeric) || !((Numeric) value).token.matches("-?(0|[1-9][0-9]*)")) throw invalid();
        try { return ((Numeric) value).value.longValueExact(); } catch (ArithmeticException error) { throw invalid(); }
    }
    private static double number(Object value) throws IOException {
        if (!(value instanceof Numeric)) throw invalid();
        double result = ((Numeric) value).value.doubleValue();
        if (Double.isInfinite(result) || Double.isNaN(result)) throw invalid();
        return result;
    }
    private static int choice(Object value, int... allowed) throws IOException {
        long result = integer(value);
        for (int candidate : allowed) if (candidate == result) return candidate;
        throw invalid();
    }

    public static Config parseConfig(String json) throws IOException { return new Config(new Json(json).parse()); }
    public static PlaybackConfig parsePlayback(String json) throws IOException { return new PlaybackConfig(new Json(json).parse()); }
    public static void validatePlaybackStatus(String json) throws IOException {
        Map<String, Object> row = new Json(json).parse();
        if (!row.keySet().equals(PLAYBACK_STATUS_KEYS) || integer(row.get("schema")) != 1
                || integer(row.get("bridge_version")) != 1 || integer(row.get("revision")) < 0) throw invalid();
        bool(row.get("wait_for_orientation"));
        boolean supported = bool(row.get("supported")), applied = bool(row.get("applied"));
        if (applied && !supported) throw invalid();
    }
    private static Long nullableInteger(Object value, long minimum, long maximum) throws IOException {
        if (value == null) return null;
        long result = integer(value);
        if (result < minimum || result > maximum) throw invalid();
        return result;
    }
    private static Double nullableFrameTime(Object value) throws IOException {
        if (value == null) return null;
        double result = number(value);
        if (result <= 0 || result > 60000) throw invalid();
        return result;
    }
    /** An observation, not a rendering command or proof of a CPU/GPU bottleneck. */
    public static void validateRenderProbe(String json) throws IOException {
        if (json == null || json.getBytes(StandardCharsets.UTF_8).length > MAX_RENDER_PROBE_BYTES) throw invalid();
        Map<String, Object> row = new Json(json).parse();
        if (!row.keySet().equals(RENDER_PROBE_KEYS) || integer(row.get("schema")) != 1
                || !RENDER_PROBE_STATES.contains(row.get("state"))) throw invalid();
        long observations = integer(row.get("observations"));
        if (observations < 0) throw invalid();
        Long mode = nullableInteger(row.get("actual_mode"), 0, 5);
        Long api = nullableInteger(row.get("graphics_api"), 0, 255);
        Long tid = nullableInteger(row.get("callback_tid"), 1, Integer.MAX_VALUE);
        Long age = nullableInteger(row.get("sample_age_ms"), 0, Long.MAX_VALUE);
        Double cpu = nullableFrameTime(row.get("cpu_frame_ms"));
        Double gpu = nullableFrameTime(row.get("gpu_frame_ms"));
        Long timingAge = nullableInteger(row.get("timing_age_ms"), 0, Long.MAX_VALUE);
        if ((cpu != null || gpu != null) != (timingAge != null)) throw invalid();
        String state = (String) row.get("state");
        if (state.equals("waiting") || state.equals("init_failed")) {
            if (observations != 0 || mode != null || api != null || tid != null || age != null
                    || cpu != null || gpu != null || timingAge != null) throw invalid();
        } else {
            if (observations < 1) throw invalid();
            if (state.equals("observed")) {
                if (mode == null || api == null || tid == null || age == null) throw invalid();
            } else if (mode != null) throw invalid();
        }
    }
    @SuppressWarnings("unchecked")
    public static void validateStatus(String json) throws IOException {
        Map<String, Object> row = new Json(json).parse();
        if (!row.keySet().equals(STATUS_KEYS)
                || integer(row.get("schema")) != 1 || integer(row.get("bridge_version")) != 1
                || integer(row.get("revision")) < 0 || !STATUSES.contains(row.get("status"))) throw invalid();
        for (String section : new String[]{"capabilities", "metrics"}) {
            if (!(row.get(section) instanceof Map)) throw invalid();
            Map<String, Object> fields = (Map<String, Object>) row.get(section);
            if (!fields.keySet().equals(section.equals("capabilities") ? CAPABILITIES : METRICS)) throw invalid();
            for (Map.Entry<String, Object> field : fields.entrySet()) {
                if (section.equals("capabilities")) bool(field.getValue());
                else {
                    double value = number(field.getValue());
                    int limit = field.getKey().endsWith("fov") ? 179 : field.getKey().equals("camera_aspect") ? 100 : 32768;
                    if (value < 0 || value > limit) throw invalid();
                }
            }
        }
    }

    interface Connections { HttpURLConnection open(URL url) throws IOException; }
    private final Connections connections;
    private static ThreadPoolExecutor daemon(final String name, boolean allowPending) {
        BlockingQueue<Runnable> queue = allowPending ? new ArrayBlockingQueue<Runnable>(1) : new SynchronousQueue<Runnable>();
        return new ThreadPoolExecutor(0, 1, 5, TimeUnit.SECONDS, queue,
            new ThreadFactory() { public Thread newThread(Runnable task) {
                Thread thread = new Thread(task, name); thread.setDaemon(true); return thread;
            }});
    }
    // One active request, one bounded pending request, and one cleanup at most.
    // The pending slot covers Future completion before its worker becomes idle;
    // cancelled queued calls are removed and can never accumulate behind a
    // platform operation that ignores interruption.
    private final ThreadPoolExecutor requests = daemon("IdolyPresentationHttp", true);
    private final ThreadPoolExecutor cleanup = daemon("IdolyPresentationClose", false);
    public PresentationClient() {
        this(new Connections() { public HttpURLConnection open(URL url) throws IOException {
            return (HttpURLConnection) url.openConnection(Proxy.NO_PROXY);
        }});
    }
    PresentationClient(Connections connections) { this.connections = connections; }
    public Config fetch() throws IOException { return parseConfig(request("/client/presentation", null)); }
    public PlaybackConfig fetchPlayback() throws IOException { return parsePlayback(request("/client/playback", null)); }
    public void postPlaybackStatus(String status) throws IOException {
        validatePlaybackStatus(status);
        request("/client/playback/status", status.getBytes(StandardCharsets.UTF_8));
    }
    public void postRenderProbe(String status) throws IOException {
        validateRenderProbe(status);
        request("/client/render-probe", status.getBytes(StandardCharsets.UTF_8));
    }
    /** Only native acknowledgement is posted; a stored preference is not playback completion. */
    public boolean pollPlayback(PlaybackNative receiver) throws IOException {
        PlaybackConfig config = fetchPlayback();
        if (!receiver.configure(1, config.revision, config.waitForOrientation)) return false;
        postPlaybackStatus(receiver.status());
        return true;
    }
    public void postStatus(String status) throws IOException {
        validateStatus(status);
        request("/client/presentation/status", status.getBytes(StandardCharsets.UTF_8));
    }
    void reportStartupFailure() {
        try { postStatus(startupFailureStatus()); }
        catch (Exception unavailable) { /* Optional reporting must leave the game running. */ }
    }
    private String request(final String path, final byte[] body) throws IOException {
        final long deadline = System.nanoTime() + 1000000000L;
        final AtomicReference<HttpURLConnection> active = new AtomicReference<HttpURLConnection>();
        Future<String> future;
        try { future = requests.submit(new Callable<String>() { public String call() throws IOException {
            return networkRequest(path, body, deadline, active);
        }}); } catch (RejectedExecutionException busy) { throw new IOException("Presentation request busy"); }
        try {
            long remaining = deadline - System.nanoTime();
            if (remaining <= 0) throw new TimeoutException();
            return future.get(remaining, TimeUnit.NANOSECONDS);
        } catch (TimeoutException timeout) {
            cancel(future, active); throw new IOException("Presentation request timeout");
        } catch (InterruptedException stopped) {
            cancel(future, active); Thread.currentThread().interrupt(); throw new IOException("Presentation request interrupted");
        } catch (ExecutionException failure) {
            Throwable cause = failure.getCause();
            if (cause instanceof IOException) throw (IOException) cause;
            if (cause instanceof RuntimeException) throw (RuntimeException) cause;
            if (cause instanceof Error) throw (Error) cause;
            throw new IOException("Presentation request failed");
        }
    }
    private void cancel(Future<String> future, final AtomicReference<HttpURLConnection> active) {
        future.cancel(true);
        requests.purge();
        try { cleanup.execute(new Runnable() { public void run() {
            HttpURLConnection connection = active.get(); if (connection != null) connection.disconnect();
        }}); } catch (RejectedExecutionException alreadyClosing) { /* Bounded daemon cleanup. */ }
    }
    private String networkRequest(String path, byte[] body, long deadline,
                                  AtomicReference<HttpURLConnection> active) throws IOException {
        HttpURLConnection connection = connections.open(new URL(ORIGIN + path));
        active.set(connection);
        InputStream incoming = null;
        try {
            remaining(connection, deadline);
            connection.setInstanceFollowRedirects(false);
            connection.setUseCaches(false);
            connection.setConnectTimeout(1000);
            connection.setReadTimeout(1000);
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("Accept-Encoding", "identity");
            if (body != null) {
                if (body.length > MAX_BYTES) throw invalid();
                connection.setRequestMethod("POST"); connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                connection.setFixedLengthStreamingMode(body.length);
            }
            connection.connect();
            remaining(connection, deadline);
            if (body != null) { try (java.io.OutputStream output = connection.getOutputStream()) { output.write(body); } }
            remaining(connection, deadline);
            if (connection.getResponseCode() != 200 || connection.getContentLengthLong() > MAX_BYTES) throw invalid();
            String encoding = connection.getContentEncoding();
            if (encoding != null && !encoding.equalsIgnoreCase("identity")) throw invalid();
            incoming = connection.getInputStream();
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] buffer = new byte[1024];
            while (true) {
                remaining(connection, deadline);
                int count = incoming.read(buffer, 0, Math.min(buffer.length, MAX_BYTES + 1 - bytes.size()));
                if (count < 0) break;
                bytes.write(buffer, 0, count);
                if (bytes.size() > MAX_BYTES) throw invalid();
            }
            remaining(connection, deadline);
            return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes.toByteArray())).toString();
        } finally {
            try { if (incoming != null) incoming.close(); } finally { connection.disconnect(); }
        }
    }
    private static void remaining(HttpURLConnection connection, long deadline) throws IOException {
        long nanos = deadline - System.nanoTime();
        if (nanos <= 0 || Thread.currentThread().isInterrupted()) throw new IOException("Presentation request timeout");
        connection.setReadTimeout((int) Math.max(1, Math.min(1000, (nanos + 999999) / 1000000)));
    }

    private static final class Numeric {
        final String token; final BigDecimal value;
        Numeric(String token) { this.token = token; this.value = new BigDecimal(token); }
    }
    /** Just objects and scalar values; only the render-probe validator permits null. */
    private static final class Json {
        final String text; int at;
        Json(String text) throws IOException {
            if (text == null || text.getBytes(StandardCharsets.UTF_8).length > MAX_BYTES) throw invalid();
            this.text = text;
        }
        Map<String, Object> parse() throws IOException {
            Map<String, Object> result = object(0); space(); if (at != text.length()) throw invalid(); return result;
        }
        void space() { while (at < text.length() && " \t\r\n".indexOf(text.charAt(at)) >= 0) at++; }
        boolean take(char value) { space(); if (at < text.length() && text.charAt(at) == value) { at++; return true; } return false; }
        Map<String, Object> object(int depth) throws IOException {
            if (depth > 1 || !take('{')) throw invalid();
            Map<String, Object> result = new HashMap<String, Object>();
            if (take('}')) return result;
            do {
                space(); String key = string(); if (key.length() > 64 || result.containsKey(key) || !take(':')) throw invalid();
                result.put(key, value(depth)); if (result.size() > 16) throw invalid();
                if (take('}')) return result;
            } while (take(','));
            throw invalid();
        }
        Object value(int depth) throws IOException {
            space(); if (at == text.length()) throw invalid();
            char first = text.charAt(at);
            if (first == '{') return object(depth + 1);
            if (first == '"') return string();
            for (String literal : new String[]{"true", "false"}) if (text.startsWith(literal, at)) {
                at += literal.length(); return literal.equals("true");
            }
            if (text.startsWith("null", at)) { at += 4; return null; }
            int start = at;
            while (at < text.length() && "-+0123456789.eE".indexOf(text.charAt(at)) >= 0) at++;
            String token = text.substring(start, at);
            if (!token.matches("-?(0|[1-9][0-9]*)(\\.[0-9]+)?([eE][+-]?[0-9]+)?") || token.length() > 64) throw invalid();
            try { return new Numeric(token); } catch (NumberFormatException error) { throw invalid(); }
        }
        String string() throws IOException {
            if (!take('"')) throw invalid(); StringBuilder result = new StringBuilder();
            while (at < text.length()) {
                char value = text.charAt(at++);
                if (value == '"') return result.toString();
                if (value < 32 || value > 126) throw invalid();
                if (value == '\\') {
                    if (at == text.length()) throw invalid(); value = text.charAt(at++);
                    if (value != '"' && value != '\\' && value != '/') throw invalid();
                }
                result.append(value); if (result.length() > 64) throw invalid();
            }
            throw invalid();
        }
    }
}
