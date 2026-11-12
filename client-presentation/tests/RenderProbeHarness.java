package game.qualiarts.idolypride.presentation;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** Host-only read-only-observation protocol; no JNI, Android or network runs. */
public final class RenderProbeHarness {
    private static int checks;
    private static final String WAITING = "{\"schema\":1,\"state\":\"waiting\",\"actual_mode\":null,\"graphics_api\":null,"
            + "\"callback_tid\":null,\"observations\":0,\"sample_age_ms\":null,\"cpu_frame_ms\":null,\"gpu_frame_ms\":null,\"timing_age_ms\":null}";
    private static final String OBSERVED = "{\"schema\":1,\"state\":\"observed\",\"actual_mode\":1,\"graphics_api\":21,"
            + "\"callback_tid\":123,\"observations\":2,\"sample_age_ms\":0,\"cpu_frame_ms\":null,\"gpu_frame_ms\":null,\"timing_age_ms\":null}";
    private static final String CONFIG = "{\"schema\":1,\"revision\":0,\"custom_graphics\":false,\"quality\":0,\"target_fps\":0,"
            + "\"render_scale\":1,\"max_buffer_pixel\":4096,\"anti_aliasing\":-1,\"shadow_resolution\":0,\"expand_photography\":false}";
    private static final String PLAYBACK = "{\"schema\":1,\"revision\":0,\"wait_for_orientation\":true}";
    private static final String PLAYBACK_STATUS = "{\"schema\":1,\"bridge_version\":1,\"revision\":0,"
            + "\"wait_for_orientation\":true,\"supported\":true,\"applied\":true}";

    private static void check(boolean condition) { ++checks; if (!condition) throw new AssertionError("render probe boundary " + checks); }
    private static String field(String source, String name, String value) {
        int start = source.indexOf("\"" + name + "\":") + name.length() + 3;
        int end = source.indexOf(',', start);
        if (end < 0) end = source.lastIndexOf('}');
        return source.substring(0, start) + value + source.substring(end);
    }
    private static void accept(String json) throws IOException { PresentationClient.validateRenderProbe(json); ++checks; }
    private static void reject(String json) throws Exception {
        try { PresentationClient.validateRenderProbe(json); }
        catch (IOException expected) { ++checks; return; }
        throw new AssertionError("Invalid render probe accepted");
    }

    private static final class Fake extends HttpURLConnection {
        byte[] bytes = "{}".getBytes(StandardCharsets.UTF_8);
        int code = 200;
        long declared = -1;
        boolean slow;
        volatile boolean disconnected, closed;
        String encoding;
        String contentType;
        ByteArrayOutputStream posted = new ByteArrayOutputStream();
        Fake() throws Exception { super(new URL("http://127.0.0.1:8080")); }
        @Override public void connect() { connected = true; }
        @Override public void disconnect() { disconnected = true; }
        @Override public boolean usingProxy() { return false; }
        @Override public int getResponseCode() {
            if (slow) {
                long end = System.nanoTime() + 1500000000L;
                while (System.nanoTime() < end) try { Thread.sleep(5); } catch (InterruptedException ignored) {}
            }
            return code;
        }
        @Override public long getContentLengthLong() { return declared; }
        @Override public String getContentEncoding() { return encoding; }
        @Override public void setRequestProperty(String key, String value) {
            super.setRequestProperty(key, value);
            if (key.equals("Content-Type")) contentType = value;
        }
        @Override public java.io.OutputStream getOutputStream() { return posted; }
        @Override public InputStream getInputStream() {
            return new ByteArrayInputStream(bytes) {
                @Override public void close() throws IOException { closed = true; super.close(); }
            };
        }
    }
    private static final class Router implements PresentationClient.Connections {
        final Fake probe;
        int calls;
        Router(Fake probe) { this.probe = probe; }
        @Override public HttpURLConnection open(URL url) throws IOException {
            ++calls;
            check(url.getProtocol().equals("http") && url.getHost().equals("127.0.0.1") && url.getPort() == 8080
                && url.getUserInfo() == null && url.getQuery() == null && url.getRef() == null);
            if (url.getPath().equals("/client/render-probe")) return probe;
            try {
                Fake next = new Fake();
                if (url.getPath().equals("/client/presentation")) next.bytes = CONFIG.getBytes(StandardCharsets.UTF_8);
                else if (url.getPath().equals("/client/playback")) next.bytes = PLAYBACK.getBytes(StandardCharsets.UTF_8);
                else check(url.getPath().equals("/client/presentation/status") || url.getPath().equals("/client/playback/status"));
                return next;
            } catch (Exception error) { throw new IOException(error); }
        }
    }

    public static void main(String[] args) throws Exception {
        accept(WAITING);
        accept(field(WAITING, "state", "\"init_failed\""));
        accept(OBSERVED);
        for (int mode = 0; mode <= 5; ++mode) accept(field(OBSERVED, "actual_mode", Integer.toString(mode)));
        accept(field(OBSERVED, "graphics_api", "255"));
        accept(field(OBSERVED, "graphics_api", "0"));
        accept(field(OBSERVED, "callback_tid", "2147483647"));
        accept(field(OBSERVED, "observations", "9223372036854775807"));
        accept(field(OBSERVED, "sample_age_ms", "9223372036854775807"));
        String unsupported = field(field(OBSERVED, "state", "\"unsupported\""), "actual_mode", "null");
        accept(unsupported);
        accept(field(field(field(unsupported, "graphics_api", "null"), "callback_tid", "null"), "sample_age_ms", "null"));
        String timed = field(field(field(OBSERVED, "cpu_frame_ms", "1.25"), "gpu_frame_ms", "60000"), "timing_age_ms", "0");
        accept(timed);
        accept(field(timed, "cpu_frame_ms", "null"));
        accept(field(timed, "gpu_frame_ms", "null"));

        for (String key : new String[]{"schema", "actual_mode", "graphics_api", "callback_tid", "observations", "sample_age_ms"}) {
            reject(field(OBSERVED, key, "true"));
            reject(field(OBSERVED, key, "1.0"));
            reject(field(OBSERVED, key, "1e0"));
            reject(field(OBSERVED, key, "\"1\""));
        }
        for (String bad : new String[]{"", "null", "[]", "{}", OBSERVED + "{}", OBSERVED + "x",
                OBSERVED.replace("\"schema\":1", "\"schema\":1,\"schema\":1"),
                OBSERVED.substring(0, OBSERVED.length() - 1) + ",\"account\":\"private\"}",
                field(OBSERVED, "schema", "2"), field(OBSERVED, "schema", "null"), field(OBSERVED, "state", "null"),
                field(OBSERVED, "state", "\"applied\""), field(OBSERVED, "actual_mode", "null"),
                field(OBSERVED, "actual_mode", "-1"), field(OBSERVED, "actual_mode", "6"),
                field(OBSERVED, "graphics_api", "null"), field(OBSERVED, "graphics_api", "-1"), field(OBSERVED, "graphics_api", "256"),
                field(OBSERVED, "callback_tid", "null"), field(OBSERVED, "callback_tid", "0"), field(OBSERVED, "callback_tid", "2147483648"),
                field(OBSERVED, "observations", "null"), field(OBSERVED, "observations", "0"), field(OBSERVED, "observations", "-1"),
                field(OBSERVED, "observations", "9223372036854775808"), field(OBSERVED, "sample_age_ms", "null"),
                field(OBSERVED, "sample_age_ms", "-1"), field(OBSERVED, "sample_age_ms", "9223372036854775808"),
                field(OBSERVED, "timing_age_ms", "0"), field(timed, "timing_age_ms", "null"),
                field(timed, "timing_age_ms", "-1"), field(timed, "timing_age_ms", "0.0"),
                field(timed, "cpu_frame_ms", "0"), field(timed, "cpu_frame_ms", "-1"), field(timed, "cpu_frame_ms", "60000.1"),
                field(timed, "cpu_frame_ms", "true"), field(timed, "gpu_frame_ms", "NaN"), field(timed, "gpu_frame_ms", "1e9999"),
                field(unsupported, "actual_mode", "0"), field(unsupported, "observations", "0"),
                field(WAITING, "actual_mode", "0"), field(WAITING, "observations", "1"),
                field(OBSERVED, "state", "\"waiting\""), field(OBSERVED, "state", "\"init_failed\"")}) reject(bad);
        for (int end = 1; end < OBSERVED.length(); ++end) reject(OBSERVED.substring(0, end));
        StringBuilder over = new StringBuilder(OBSERVED);
        while (over.length() <= PresentationClient.MAX_RENDER_PROBE_BYTES) over.append(' ');
        reject(over.toString());

        Fake post = new Fake(); Router good = new Router(post);
        new PresentationClient(good).postRenderProbe(OBSERVED);
        check(post.getRequestMethod().equals("POST") && !post.getInstanceFollowRedirects() && !post.getUseCaches());
        check(post.getConnectTimeout() == 1000 && post.getReadTimeout() > 0 && post.getReadTimeout() <= 1000);
        check(new String(post.posted.toByteArray(), StandardCharsets.UTF_8).equals(OBSERVED) && post.closed && post.disconnected);
        check("application/json; charset=utf-8".equals(post.contentType));
        Fake never = new Fake(); Router invalid = new Router(never);
        try { new PresentationClient(invalid).postRenderProbe(over.toString()); throw new AssertionError(); }
        catch (IOException expected) { check(invalid.calls == 0); }

        // A missing optional endpoint cannot poison the same client's existing protocols.
        Fake oldServer = new Fake(); oldServer.code = 404;
        PresentationClient compatible = new PresentationClient(new Router(oldServer));
        try { compatible.postRenderProbe(OBSERVED); throw new AssertionError(); }
        catch (IOException expected) { check(oldServer.disconnected); }
        check(compatible.fetch().revision == 0 && compatible.fetchPlayback().waitForOrientation);
        compatible.postStatus(PresentationClient.startupFailureStatus());
        compatible.postPlaybackStatus(PLAYBACK_STATUS); ++checks;
        try { PresentationClient.parsePlayback(field(PLAYBACK, "wait_for_orientation", "null")); throw new AssertionError(); }
        catch (IOException expected) { ++checks; }
        try { PresentationClient.parseConfig(field(CONFIG, "render_scale", "null")); throw new AssertionError(); }
        catch (IOException expected) { ++checks; }

        for (int scenario = 0; scenario < 5; ++scenario) {
            Fake failure = new Fake();
            if (scenario == 0) failure.code = 302;
            if (scenario == 1) failure.bytes = new byte[PresentationClient.MAX_BYTES + 1];
            if (scenario == 2) failure.declared = PresentationClient.MAX_BYTES + 1;
            if (scenario == 3) failure.encoding = "gzip";
            if (scenario == 4) failure.bytes = new byte[]{(byte) 0xc3, (byte) 0x28};
            try { new PresentationClient(new Router(failure)).postRenderProbe(OBSERVED); throw new AssertionError(); }
            catch (IOException expected) { check(failure.disconnected); }
        }
        Fake slow = new Fake(); slow.slow = true;
        long started = System.nanoTime();
        try { new PresentationClient(new Router(slow)).postRenderProbe(OBSERVED); throw new AssertionError(); }
        catch (IOException expected) { check((System.nanoTime() - started) / 1000000 < 1400); }
        System.out.println("PASS " + checks);
    }
}
