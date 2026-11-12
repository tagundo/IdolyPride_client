package game.qualiarts.idolypride.presentation;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

public final class PresentationHarness {
    private static int checks;
    private static final String CONFIG = "{\"schema\":1,\"revision\":7,\"custom_graphics\":true,\"quality\":100,\"target_fps\":120,\"render_scale\":1.25,\"max_buffer_pixel\":4096,\"anti_aliasing\":-1,\"shadow_resolution\":2048,\"expand_photography\":true}";
    private static final String STATUS = "{\"schema\":1,\"bridge_version\":1,\"revision\":3,\"status\":\"waiting_for_scene\",\"capabilities\":{\"fps\":true,\"quality\":true,\"resolution\":false,\"anti_aliasing\":false,\"shadow\":false,\"expanded_photography\":false},\"metrics\":{\"screen_width\":2400,\"screen_height\":1080,\"render_width\":1920,\"render_height\":1080,\"camera_aspect\":2.2,\"base_vertical_fov\":60,\"vertical_fov\":60}}";
    private static void check(boolean value) { checks++; if (!value) throw new AssertionError("presentation boundary " + checks); }
    private static void reject(String value, boolean status) throws Exception {
        try { if (status) PresentationClient.validateStatus(value); else PresentationClient.parseConfig(value); }
        catch (IOException expected) { checks++; return; }
        throw new AssertionError("accepted invalid protocol");
    }
    private static final class Fake extends HttpURLConnection {
        byte[] bytes = CONFIG.getBytes(StandardCharsets.UTF_8);
        volatile boolean disconnected, closed;
        boolean failConnect, failRead, slowHeader;
        long headerDelayNanos = 1500000000L;
        int code = 200; long length = -1; String encoding;
        ByteArrayOutputStream posted = new ByteArrayOutputStream();
        Fake() throws Exception { super(new URL("http://127.0.0.1:8080")); }
        @Override public void connect() throws IOException { if (failConnect) throw new IOException("synthetic"); connected = true; }
        @Override public void disconnect() { disconnected = true; }
        @Override public boolean usingProxy() { return false; }
        @Override public int getResponseCode() {
            if (slowHeader) {
                long end = System.nanoTime() + headerDelayNanos;
                while (System.nanoTime() < end) try { Thread.sleep(10); } catch (InterruptedException ignored) {}
            }
            return code;
        }
        @Override public long getContentLengthLong() { return length; }
        @Override public String getContentEncoding() { return encoding; }
        @Override public java.io.OutputStream getOutputStream() { return posted; }
        @Override public InputStream getInputStream() {
            return new ByteArrayInputStream(bytes) {
                @Override public int read(byte[] buffer, int at, int size) {
                    if (failRead) throw new IllegalStateException("synthetic read failure");
                    return super.read(buffer, at, size);
                }
                @Override public void close() throws IOException { closed = true; super.close(); }
            };
        }
    }
    private static PresentationClient client(final Fake fake, final String path) {
        return new PresentationClient(new PresentationClient.Connections() {
            public HttpURLConnection open(URL url) {
                check(url.getProtocol().equals("http") && url.getHost().equals("127.0.0.1")
                    && url.getPort() == 8080 && url.getPath().equals(path) && url.getUserInfo() == null);
                return fake;
            }
        });
    }
    private static void badTransport(Fake fake) throws Exception {
        try { client(fake, "/client/presentation").fetch(); }
        catch (IOException expected) { check(fake.disconnected); return; }
        throw new AssertionError("transport accepted invalid response");
    }
    public static void main(String[] arguments) throws Exception {
        PresentationClient.Config config = PresentationClient.parseConfig(CONFIG);
        check(config.revision == 7 && config.custom && config.expand && config.quality == 100 && config.fps == 120);
        check(config.scale == 1.25f && config.maxBufferPixel == 4096 && config.aa == -1 && config.shadow == 2048);
        for (String bad : new String[]{CONFIG.replace("\"schema\":1", "\"schema\":1.0"),
            CONFIG.replace("\"revision\":7", "\"revision\":true"), CONFIG.replace("\"revision\":7", "\"revision\":-1"),
            CONFIG.replace("\"revision\":7", "\"revision\":9223372036854775808"),
            CONFIG.replace("\"quality\":100", "\"quality\":2"), CONFIG.replace("\"target_fps\":120", "\"target_fps\":121"),
            CONFIG.replace("1.25", "2.0001"), CONFIG.replace("1.25", "1e9999"),
            CONFIG.replace("4096", "4095"), CONFIG.replace("\"anti_aliasing\":-1", "\"anti_aliasing\":8"),
            CONFIG.replace("2048", "128"), CONFIG.replace("\"custom_graphics\":true", "\"custom_graphics\":1"),
            CONFIG.replace("\"schema\":1", "\"schema\":1,\"schema\":1"), CONFIG.substring(0, CONFIG.length()-1)+",\"account\":0}",
            CONFIG + "{}", CONFIG.substring(0, CONFIG.length()-1)+",}", CONFIG.replace("1.25", "NaN")}) reject(bad, false);
        PresentationClient.validateStatus(STATUS); checks++;
        String startupFailure = PresentationClient.startupFailureStatus();
        PresentationClient.validateStatus(startupFailure);
        check(startupFailure.contains("\"revision\":0") && startupFailure.contains("\"status\":\"init_failed\"")
            && !startupFailure.contains(":true") && !startupFailure.contains("error"));
        Fake failedStart = new Fake(); failedStart.bytes = new byte[0];
        client(failedStart, "/client/presentation/status").postStatus(startupFailure);
        check(new String(failedStart.posted.toByteArray(), StandardCharsets.UTF_8).equals(startupFailure)
            && failedStart.disconnected && failedStart.closed);
        Fake fallbackIo = new Fake(); fallbackIo.failConnect = true;
        client(fallbackIo, "/client/presentation/status").reportStartupFailure();
        check(fallbackIo.disconnected);
        Fake fallbackRuntime = new Fake(); fallbackRuntime.failRead = true;
        client(fallbackRuntime, "/client/presentation/status").reportStartupFailure();
        check(fallbackRuntime.closed && fallbackRuntime.disconnected);
        for (String bad : new String[]{STATUS.replace("waiting_for_scene", "arbitrary exception"),
            STATUS.replace("\"revision\":3", "\"revision\":-1"), STATUS.replace("\"fps\":true", "\"fps\":1"),
            STATUS.replace("\"screen_width\":2400", "\"screen_width\":true"), STATUS.replace("\"camera_aspect\":2.2", "\"account\":2.2"),
            STATUS.replace("\"screen_width\":2400", "\"screen_width\":-1"), STATUS.replace("2400", "32769"),
            STATUS.replace("2.2", "100.1"), STATUS.replace("\"vertical_fov\":60", "\"vertical_fov\":180"),
            STATUS.replace("\"quality\":true,", ""), STATUS.replace("\"screen_height\":1080,", ""),
            STATUS.replace("2.2", "1e9999"), STATUS.replace("\"bridge_version\":1", "\"bridge_version\":2"),
            STATUS.substring(0, STATUS.length()-1)+",\"error\":\"sensitive\"}"}) reject(bad, true);
        Fake get = new Fake(); config = client(get, "/client/presentation").fetch();
        check(config.revision == 7 && get.closed && get.disconnected && !get.getInstanceFollowRedirects());
        check(get.getConnectTimeout() == 1000 && get.getReadTimeout() > 0 && get.getReadTimeout() <= 1000 && !get.getUseCaches());
        Fake post = new Fake(); post.bytes = new byte[0]; client(post, "/client/presentation/status").postStatus(STATUS);
        check(new String(post.posted.toByteArray(), StandardCharsets.UTF_8).equals(STATUS));
        check(post.getRequestMethod().equals("POST") && post.disconnected && post.closed);
        Fake redirect = new Fake(); redirect.code = 302; badTransport(redirect);
        Fake oversized = new Fake(); oversized.bytes = new byte[8193]; badTransport(oversized);
        Fake declared = new Fake(); declared.length = 8193; badTransport(declared);
        Fake encoded = new Fake(); encoded.encoding = "gzip"; badTransport(encoded);
        Fake invalidUtf8 = new Fake(); invalidUtf8.bytes = new byte[]{(byte)0xc3,(byte)0x28}; badTransport(invalidUtf8);
        Fake failed = new Fake(); failed.failConnect = true; badTransport(failed);
        Fake readFailed = new Fake(); readFailed.failRead = true;
        try { client(readFailed, "/client/presentation").fetch(); throw new AssertionError(); }
        catch (IllegalStateException expected) { check(readFailed.closed && readFailed.disconnected); }
        Fake slow = new Fake(); slow.slowHeader = true; slow.headerDelayNanos = 3500000000L;
        PresentationClient bounded = client(slow, "/client/presentation");
        long start = System.nanoTime();
        try { bounded.fetch(); throw new AssertionError("unbounded header call"); }
        catch (IOException expected) { check((System.nanoTime() - start) / 1000000 < 1400); }
        for (int i=0; i<20 && !slow.disconnected; i++) Thread.sleep(5);
        check(slow.disconnected);
        // The one pending slot must time out and be cancelled while the first
        // platform call is still ignoring interruption; it cannot start a new
        // network operation or grow an unbounded queue.
        try { bounded.fetch(); throw new AssertionError("ran a second blocked operation"); }
        catch (IOException expected) { checks++; }
        System.out.println("PASS " + checks);
    }
}
