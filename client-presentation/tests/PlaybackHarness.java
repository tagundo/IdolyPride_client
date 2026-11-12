package game.qualiarts.idolypride.presentation;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** Host-only loopback protocol checks; no JNI or Android process executes. */
public final class PlaybackHarness {
    private static int checks;
    private static final String CONFIG = "{\"schema\":1,\"revision\":8,\"wait_for_orientation\":false}";
    private static final String STATUS = "{\"schema\":1,\"bridge_version\":1,\"revision\":8,"
            + "\"wait_for_orientation\":false,\"supported\":true,\"applied\":true}";
    private static void check(boolean value) { ++checks; if (!value) throw new AssertionError("playback boundary " + checks); }
    private static void reject(String json, boolean status) throws Exception {
        try { if (status) PresentationClient.validatePlaybackStatus(json); else PresentationClient.parsePlayback(json); }
        catch (IOException expected) { ++checks; return; }
        throw new AssertionError("Invalid playback message accepted");
    }
    private static final class Fake extends HttpURLConnection {
        byte[] bytes;
        int code = 200;
        boolean disconnected, closed;
        ByteArrayOutputStream posted = new ByteArrayOutputStream();
        Fake(String data) throws Exception { super(new URL("http://127.0.0.1:8080")); bytes = data.getBytes(StandardCharsets.UTF_8); }
        @Override public void connect() { connected = true; }
        @Override public void disconnect() { disconnected = true; }
        @Override public boolean usingProxy() { return false; }
        @Override public int getResponseCode() { return code; }
        @Override public long getContentLengthLong() { return bytes.length; }
        @Override public java.io.OutputStream getOutputStream() { return posted; }
        @Override public InputStream getInputStream() {
            return new ByteArrayInputStream(bytes) {
                @Override public void close() throws IOException { closed = true; super.close(); }
            };
        }
    }
    private static final class Native implements PresentationClient.PlaybackNative {
        int configurations, statuses;
        boolean accepted = true, wait = true;
        @Override public boolean configure(int schema, long revision, boolean value) {
            check(schema == 1 && revision == 8); ++configurations;
            if (accepted) wait = value;
            return accepted;
        }
        @Override public String status() { ++statuses; return STATUS; }
    }
    private static final class Router implements PresentationClient.Connections {
        final Fake get, post, graphics;
        int posts;
        Router(Fake get, Fake post) throws Exception { this.get = get; this.post = post; graphics = new Fake("{}"); graphics.code = 404; }
        @Override public HttpURLConnection open(URL url) {
            check(url.getProtocol().equals("http") && url.getHost().equals("127.0.0.1") && url.getPort() == 8080
                && url.getUserInfo() == null && url.getQuery() == null && url.getRef() == null);
            if (url.getPath().equals("/client/playback")) return get;
            if (url.getPath().equals("/client/playback/status")) { ++posts; return post; }
            if (url.getPath().equals("/client/presentation")) return graphics;
            throw new AssertionError("Unexpected route");
        }
    }
    public static void main(String[] args) throws Exception {
        PresentationClient.PlaybackConfig value = PresentationClient.parsePlayback(CONFIG);
        check(value.revision == 8 && !value.waitForOrientation);
        value = PresentationClient.parsePlayback(" { \"wait_for_orientation\":true,\"revision\":9223372036854775807,\"schema\":1 } ");
        check(value.revision == Long.MAX_VALUE && value.waitForOrientation);
        for (String bad : new String[]{CONFIG.replace("\"schema\":1", "\"schema\":1.0"),
                CONFIG.replace("\"schema\":1", "\"schema\":true"), CONFIG.replace("\"schema\":1", "\"schema\":2"),
                CONFIG.replace("\"revision\":8", "\"revision\":-1"), CONFIG.replace("\"revision\":8", "\"revision\":8.0"),
                CONFIG.replace("\"revision\":8", "\"revision\":8e0"), CONFIG.replace("\"revision\":8", "\"revision\":true"),
                CONFIG.replace("\"revision\":8", "\"revision\":9223372036854775808"),
                CONFIG.replace("false", "0"), CONFIG.replace("false", "\"false\""), CONFIG.replace("false", "null"),
                CONFIG.replace("\"schema\":1", "\"schema\":1,\"schema\":1"),
                CONFIG.substring(0, CONFIG.length() - 1) + ",\"custom_graphics\":false}",
                CONFIG.replace("\"wait_for_orientation\"", "\"custom_graphics\""), CONFIG + "{}", "[]", "null", ""}) reject(bad, false);
        for (int at = 1; at < CONFIG.length(); ++at) reject(CONFIG.substring(0, at), false);
        PresentationClient.validatePlaybackStatus(STATUS); ++checks;
        PresentationClient.validatePlaybackStatus(STATUS.replace("\"supported\":true,\"applied\":true", "\"supported\":false,\"applied\":false")); ++checks;
        for (String bad : new String[]{STATUS.replace("\"bridge_version\":1", "\"bridge_version\":2"),
                STATUS.replace("\"revision\":8", "\"revision\":-1"), STATUS.replace("\"revision\":8", "\"revision\":8.0"),
                STATUS.replace("\"wait_for_orientation\":false", "\"wait_for_orientation\":0"),
                STATUS.replace("\"supported\":true", "\"supported\":false"),
                STATUS.replace("\"supported\":true", "\"supported\":1"),
                STATUS.replace("\"applied\":true", "\"applied\":\"true\""),
                STATUS.replace("\"schema\":1", "\"schema\":1,\"schema\":1"),
                STATUS.substring(0, STATUS.length() - 1) + ",\"error\":\"private\"}"}) reject(bad, true);
        {
            Fake get = new Fake(CONFIG), post = new Fake("{}"); Router router = new Router(get, post);
            Native target = new Native(); PresentationClient client = new PresentationClient(router);
            // An older server's graphics endpoint can fail independently.
            try { client.fetch(); throw new AssertionError("Unexpected graphics success"); }
            catch (IOException expected) { ++checks; }
            check(client.pollPlayback(target) && !target.wait && target.configurations == 1 && target.statuses == 1);
            check(get.closed && get.disconnected && post.closed && post.disconnected && !get.getInstanceFollowRedirects());
            check(new String(post.posted.toByteArray(), StandardCharsets.UTF_8).equals(STATUS) && router.posts == 1);
        }
        for (String data : new String[]{CONFIG, "{}"}) {
            Fake get = new Fake(data), post = new Fake("{}");
            if (data.equals(CONFIG)) get.code = 404;
            Router router = new Router(get, post); Native target = new Native();
            try { new PresentationClient(router).pollPlayback(target); throw new AssertionError("Expected rejected settings"); }
            catch (IOException expected) { check(target.wait && target.configurations == 0 && target.statuses == 0 && router.posts == 0); }
        }
        {
            Router router = new Router(new Fake(CONFIG), new Fake("{}")); Native target = new Native(); target.accepted = false;
            check(!new PresentationClient(router).pollPlayback(target) && target.wait && target.configurations == 1 && target.statuses == 0 && router.posts == 0);
        }
        {
            Fake post = new Fake("{}"); post.code = 404;
            Router router = new Router(new Fake(CONFIG), post); Native target = new Native();
            try { new PresentationClient(router).pollPlayback(target); throw new AssertionError("Missing ACK endpoint accepted"); }
            catch (IOException expected) { check(!target.wait && target.configurations == 1 && target.statuses == 1); }
        }
        {
            // Future completion can precede the executor worker becoming idle.
            // Rapid sequential polls must still succeed with bounded queuing.
            PresentationClient client = new PresentationClient(new PresentationClient.Connections() {
                @Override public HttpURLConnection open(URL url) throws IOException {
                    try {
                        return new Fake(url.getPath().equals("/client/playback") ? CONFIG : "{}");
                    } catch (Exception failure) { throw new IOException("Synthetic connection failed"); }
                }
            });
            Native target = new Native();
            for (int iteration = 0; iteration < 100; ++iteration) check(client.pollPlayback(target));
            check(target.configurations == 100 && target.statuses == 100);
        }
        System.out.println("PASS " + checks);
    }
}
