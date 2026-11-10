package game.qualiarts.idolypride.qa.ui;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Deliberately small authenticated HTTP protocol; no logs or arbitrary RPCs. */
final class LoopbackUiServer implements Runnable {
    static final int PORT = 50052;
    static final int MAX_RESPONSE = 65536;
    private static final int MAX_HEADERS = 8192;
    private static final int MAX_BODY = 4096;
    private static final long INPUT_NANOS = 3000000000L;
    private static final String W = "[ \\t\\r\\n]*";
    private static final String ID = "(-?(?:0|[1-9][0-9]*))";
    private static final String GENERATION = "([1-9][0-9]*)";
    private static final Pattern CLICK = Pattern.compile("\\{" + W
        + "(?:\"instance_id\"" + W + ":" + W + ID + W + "," + W + "\"generation\"" + W + ":" + W + GENERATION
        + "|\"generation\"" + W + ":" + W + GENERATION + W + "," + W + "\"instance_id\"" + W + ":" + W + ID + ")"
        + W + "\\}");

    interface Actions {
        String health();
        String snapshot();
        String click(int instanceId, long generation);
    }

    private final byte[] authorization;
    private final Actions actions;
    private final ServerSocket listener;
    private final long deadline;
    private volatile boolean stopped;

    LoopbackUiServer(String token, Actions actions, long sessionMillis) throws IOException {
        if (token == null || !token.matches("[0-9a-f]{64}") || actions == null
                || sessionMillis <= 0 || sessionMillis > 1800000L) throw new IllegalArgumentException("QA bridge configuration");
        this.authorization = ("Bearer " + token).getBytes(StandardCharsets.US_ASCII);
        this.actions = actions;
        this.deadline = System.nanoTime() + sessionMillis * 1000000L;
        listener = new ServerSocket();
        // A force-stopped disposable game may restart while prior HTTP
        // connections are still in TIME_WAIT. This does not enable REUSEPORT.
        listener.setReuseAddress(true);
        listener.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), PORT), 2);
        listener.setSoTimeout(1000);
    }

    void stop() {
        stopped = true;
        try { listener.close(); } catch (IOException ignored) {}
    }

    @Override public void run() {
        try {
            while (!stopped && System.nanoTime() < deadline) {
                try (Socket socket = listener.accept()) {
                    socket.setSoTimeout(3000);
                    handle(socket);
                } catch (SocketTimeoutException ignored) {
                    // Bound accept and request reads; never retain request data.
                } catch (IOException ignored) {
                    if (stopped) break;
                } catch (RuntimeException ignored) {
                    // A malformed request cannot terminate the game or bridge.
                }
            }
        } finally { stop(); }
    }

    private void handle(Socket socket) throws IOException {
        InputStream incoming = socket.getInputStream();
        long inputDeadline = System.nanoTime() + INPUT_NANOS;
        byte[] headerBytes;
        try { headerBytes = headers(incoming, inputDeadline); }
        catch (BadRequest failure) { reply(socket, failure.status, error(failure.code)); return; }
        String[] lines = new String(headerBytes, StandardCharsets.US_ASCII).split("\\r\\n");
        String[] request = lines[0].split(" ", -1);
        if (request.length != 3 || !(request[2].equals("HTTP/1.1") || request[2].equals("HTTP/1.0"))) {
            reply(socket, 400, error("invalid_request")); return;
        }
        Map<String, String> fields = new HashMap<>();
        for (int index = 1; index < lines.length; index++) {
            String line = lines[index];
            int colon = line.indexOf(':');
            if (colon <= 0 || line.charAt(0) == ' ' || line.charAt(0) == '\t') {
                reply(socket, 400, error("invalid_headers")); return;
            }
            String key = line.substring(0, colon).toLowerCase(Locale.ROOT);
            if (!key.matches("[a-z0-9-]+") || fields.put(key, line.substring(colon + 1).trim()) != null) {
                reply(socket, 400, error("duplicate_or_invalid_header")); return;
            }
        }
        byte[] supplied = fields.getOrDefault("authorization", "").getBytes(StandardCharsets.US_ASCII);
        if (!MessageDigest.isEqual(authorization, supplied)) { reply(socket, 401, error("unauthorized")); return; }
        if (fields.containsKey("transfer-encoding")) { reply(socket, 400, error("unsupported_transfer_encoding")); return; }
        int length = 0;
        if (fields.containsKey("content-length")) {
            String value = fields.get("content-length");
            if (!value.matches("0|[1-9][0-9]{0,9}")) { reply(socket, 400, error("invalid_content_length")); return; }
            try { length = Integer.parseInt(value); }
            catch (NumberFormatException failure) { reply(socket, 413, error("body_too_large")); return; }
        }
        if (length > MAX_BODY) { reply(socket, 413, error("body_too_large")); return; }
        if (request[0].equals("GET")) {
            if (length != 0) { reply(socket, 400, error("unexpected_body")); return; }
            if (request[1].equals("/health")) reply(socket, 200, actions.health());
            else if (request[1].equals("/snapshot")) reply(socket, 200, actions.snapshot());
            else reply(socket, 404, error("unknown_endpoint"));
            return;
        }
        if (!request[0].equals("POST")) { reply(socket, 405, error("unsupported_method")); return; }
        if (!request[1].equals("/click")) { reply(socket, 404, error("unknown_endpoint")); return; }
        if (!fields.containsKey("content-length")) { reply(socket, 411, error("content_length_required")); return; }
        String contentType = fields.getOrDefault("content-type", "");
        if (!(contentType.equals("application/json") || contentType.equals("application/json; charset=utf-8"))) {
            reply(socket, 415, error("json_required")); return;
        }
        byte[] body = new byte[length];
        int offset = 0;
        while (offset < length) {
            if (System.nanoTime() >= inputDeadline) { reply(socket, 408, error("input_timeout")); return; }
            int count = incoming.read(body, offset, length - offset);
            if (count < 0) { reply(socket, 400, error("incomplete_body")); return; }
            offset += count;
        }
        Matcher match = CLICK.matcher(new String(body, StandardCharsets.UTF_8));
        if (!match.matches()) { reply(socket, 400, error("invalid_click")); return; }
        try {
            String rawId = match.group(1) == null ? match.group(4) : match.group(1);
            String rawGeneration = match.group(2) == null ? match.group(3) : match.group(2);
            int instanceId = Integer.parseInt(rawId);
            long generation = Long.parseLong(rawGeneration);
            if (instanceId == 0 || generation <= 0) { reply(socket, 400, error("invalid_click")); return; }
            reply(socket, 200, actions.click(instanceId, generation));
        } catch (NumberFormatException failure) { reply(socket, 400, error("invalid_click")); }
    }

    private static byte[] headers(InputStream stream, long deadline) throws IOException, BadRequest {
        ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        int matched = 0;
        byte[] end = {'\r', '\n', '\r', '\n'};
        while (buffer.size() < MAX_HEADERS) {
            if (System.nanoTime() >= deadline) throw new BadRequest(408, "input_timeout");
            int value = stream.read();
            if (value < 0) throw new BadRequest(400, "incomplete_headers");
            if (value != '\r' && value != '\n' && value != '\t' && (value < 32 || value > 126)) {
                throw new BadRequest(400, "invalid_headers");
            }
            buffer.write(value);
            matched = value == end[matched] ? matched + 1 : (value == '\r' ? 1 : 0);
            if (matched == end.length) {
                byte[] raw = buffer.toByteArray();
                byte[] result = new byte[raw.length - end.length];
                System.arraycopy(raw, 0, result, 0, result.length);
                return result;
            }
        }
        throw new BadRequest(431, "headers_too_large");
    }

    static String error(String code) { return "{\"ok\":false,\"error\":\"" + code + "\"}"; }

    private static void reply(Socket socket, int status, String value) throws IOException {
        byte[] body = value == null ? new byte[0] : value.getBytes(StandardCharsets.UTF_8);
        if (body.length == 0 || body.length > MAX_RESPONSE) {
            status = 503;
            body = error("native_response_unavailable").getBytes(StandardCharsets.UTF_8);
        }
        String header = "HTTP/1.1 " + status + " QA\r\nContent-Type: application/json; charset=utf-8\r\n"
            + "Content-Length: " + body.length + "\r\nConnection: close\r\nCache-Control: no-store\r\n\r\n";
        OutputStream outgoing = socket.getOutputStream();
        outgoing.write(header.getBytes(StandardCharsets.US_ASCII));
        outgoing.write(body);
        outgoing.flush();
    }

    private static final class BadRequest extends Exception {
        final int status;
        final String code;
        BadRequest(int status, String code) { this.status = status; this.code = code; }
    }
}
