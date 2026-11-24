package game.qualiarts.idolypride.qa.ui;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.InetAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicInteger;

/** Host protocol checks; this never loads Unity, JNI, Android or account data. */
public final class LoopbackHarness {
    private static final String TOKEN = "0000000000000000000000000000000000000000000000000000000000000000";

    private static final class Actions implements LoopbackUiServer.Actions {
        final AtomicInteger clicks = new AtomicInteger();
        volatile boolean oversized;
        @Override public String health() { return "{\"ok\":true,\"unity_ready\":false}"; }
        @Override public String snapshot() {
            if (oversized) return new String(new char[70000]).replace('\0', 'x');
            return "{\"ok\":true,\"generation\":1,\"nodes\":[]}";
        }
        @Override public String mp4Status() { return "{\"ok\":true,\"qa_only\":true,\"read_only\":true,\"native\":{\"schema\":1}}"; }
        @Override public String mp4Diagnostics() { return "{\"ok\":true,\"qa_only\":true,\"read_only\":true,\"native_initialized\":false}"; }
        @Override public String click(int instanceId, long generation) {
            if (instanceId != -7 || generation != 3) throw new AssertionError("Unexpected semantic click arguments");
            clicks.incrementAndGet();
            return "{\"ok\":true}";
        }
    }

    private static String exchange(String request) throws Exception {
        try (Socket socket = new Socket(InetAddress.getByName("127.0.0.1"), LoopbackUiServer.PORT)) {
            socket.setSoTimeout(5000);
            socket.getOutputStream().write(request.getBytes(StandardCharsets.UTF_8));
            socket.shutdownOutput();
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            InputStream input = socket.getInputStream();
            byte[] chunk = new byte[1024];
            int count;
            while ((count = input.read(chunk)) >= 0) output.write(chunk, 0, count);
            return new String(output.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    private static String request(String method, String path, String headers, String body) {
        return method + " " + path + " HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer "
            + TOKEN + "\r\n" + headers + "\r\n" + body;
    }

    private static void status(String response, int expected) {
        if (!response.startsWith("HTTP/1.1 " + expected + " ")) throw new AssertionError("Unexpected HTTP status");
        if (response.contains("Access-Control-Allow-Origin")) throw new AssertionError("Unexpected cross-origin access");
    }

    private static String click(String body) {
        return request("POST", "/click", "Content-Type: application/json\r\nContent-Length: "
            + body.getBytes(StandardCharsets.UTF_8).length + "\r\n", body);
    }

    public static void main(String[] args) throws Exception {
        Actions actions = new Actions();
        LoopbackUiServer server = new LoopbackUiServer(TOKEN, actions, 30000);
        Thread worker = new Thread(server, "HostQaProtocol");
        worker.setDaemon(true);
        worker.start();
        try {
            status(exchange("GET /snapshot HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"), 401);
            status(exchange(request("GET", "/health", "", "")), 200);
            status(exchange(request("GET", "/snapshot", "", "")), 200);
            status(exchange("GET /mp4-status HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"), 401);
            String observed = exchange(request("GET", "/mp4-status", "", ""));
            status(observed, 200);
            if (!observed.contains("\"read_only\":true")) throw new AssertionError("Missing read-only MP4 observation");
            status(exchange(request("POST", "/mp4-status", "", "")), 404);
            status(exchange("GET /mp4-diagnostics HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"), 401);
            String diagnosed = exchange(request("GET", "/mp4-diagnostics", "", ""));
            status(diagnosed, 200);
            if (!diagnosed.contains("\"native_initialized\":false")) throw new AssertionError("Missing read-only MP4 diagnostics");
            status(exchange(request("POST", "/mp4-diagnostics", "", "")), 404);
            status(exchange(request("GET", "/mp4-diagnostics?all=1", "", "")), 404);
            status(exchange(request("GET", "/snapshot?unsafe=1", "", "")), 404);
            status(exchange(request("POST", "/arbitrary", "", "")), 404);
            status(exchange(request("POST", "/click", "", "")), 411);
            status(exchange(request("POST", "/click", "Content-Length: 4097\r\n", "")), 413);
            status(exchange(request("POST", "/click", "Transfer-Encoding: chunked\r\n", "")), 400);
            status(exchange(request("POST", "/click", "Content-Length: 2\r\nContent-Length: 2\r\n", "{}")), 400);
            status(exchange(request("POST", "/click", "Content-Length: 2\r\n", "{}")), 415);
            for (String invalid : new String[]{"{}", "{\"instance_id\":-7}",
                    "{\"instance_id\":-7,\"generation\":0}", "{\"instance_id\":0,\"generation\":3}",
                    "{\"instance_id\":2147483648,\"generation\":3}", "{\"instance_id\":-7,\"generation\":1e0}",
                    "{\"instance_id\":\"-7\",\"generation\":3}", "{\"instance_id\":-7,\"generation\":9223372036854775808}",
                    "{\"instance_id\":-7,\"generation\":3,\"arbitrary\":1}"}) {
                status(exchange(click(invalid)), 400);
            }
            if (actions.clicks.get() != 0) throw new AssertionError("Rejected request reached an action");
            status(exchange(click("{\"instance_id\":-7,\"generation\":3}")), 200);
            status(exchange(click("{ \"generation\" : 3, \"instance_id\" : -7 }")), 200);
            if (actions.clicks.get() != 2) throw new AssertionError("Valid click was not dispatched");
            actions.oversized = true;
            status(exchange(request("GET", "/snapshot", "", "")), 503);
        } finally {
            server.stop();
            worker.join(2000);
        }
        if (worker.isAlive()) throw new AssertionError("QA listener did not close");
        LoopbackUiServer restarted = new LoopbackUiServer(TOKEN, actions, 30000);
        restarted.stop();
        System.out.println("QA loopback protocol checks passed");
    }
}
