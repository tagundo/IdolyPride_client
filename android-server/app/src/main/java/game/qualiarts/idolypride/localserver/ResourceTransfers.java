package game.qualiarts.idolypride.localserver;

import android.content.ContentValues;
import android.content.Context;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.os.ParcelFileDescriptor;
import android.os.SystemClock;
import android.provider.DocumentsContract;
import android.provider.MediaStore;
import android.system.Os;
import android.system.OsConstants;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.Proxy;
import java.net.URL;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Arrays;
import java.util.Date;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/** One app-context transfer worker. ZIPs stream directly to the chosen destination. */
final class ResourceTransfers {
    private static final String ORIGIN = "http://127.0.0.1:8080/client/resources";
    private static final int CONTROL_LIMIT = 128 * 1024;
    private static final AtomicBoolean BUSY = new AtomicBoolean(), CANCEL = new AtomicBoolean(), CLOSING = new AtomicBoolean();
    private static final ExecutorService IO = Executors.newSingleThreadExecutor(task -> {
        Thread thread = new Thread(task, "IdolyResourceIO"); thread.setDaemon(true); return thread;
    });
    private static volatile HttpURLConnection activeConnection;
    private static volatile InputStream activeInput;
    private static volatile OutputStream activeOutput;
    private static volatile Snapshot current = new Snapshot(false, "", "idle", 0, null, null);
    static final class Snapshot {
        final boolean busy;
        final String action, state, error, destination;
        final long bytes;
        final long importedFiles, failedFiles;
        Snapshot(boolean busy, String action, String state, long bytes, String error, String destination) {
            this(busy, action, state, bytes, error, destination, -1, -1);
        }
        Snapshot(boolean busy, String action, String state, long bytes, String error, String destination, long imported, long failed) {
            this.busy = busy; this.action = action; this.state = state; this.bytes = bytes;
            this.error = error; this.destination = destination;
            importedFiles = imported; failedFiles = failed;
        }
    }
    static final int STORAGE_PRIVATE = 0, STORAGE_DOWNLOADS = 1, STORAGE_PERMISSION = 2, STORAGE_UNSUPPORTED = 3;
    static int storageAccess(int sdk, boolean downloads, boolean permission) {
        if (!downloads) return STORAGE_PRIVATE;
        if (sdk < 30) return STORAGE_UNSUPPORTED;
        return permission ? STORAGE_DOWNLOADS : STORAGE_PERMISSION;
    }
    static String publicCachePath(File downloads) throws IOException {
        File parent = downloads.getCanonicalFile();
        File result = new File(parent, "IdolyPride").getCanonicalFile();
        if (!parent.equals(result.getParentFile()) || !"IdolyPride".equals(result.getName()))
            throw new IOException("Public resource directory is not the selected Downloads folder");
        return result.getPath();
    }
    private static final class Failure extends IOException {
        final String code;
        Failure(String code) { super(code); this.code = code; }
    }
    private interface Work { Snapshot run(Context context) throws Exception; }
    static Snapshot snapshot() { return current; }
    static boolean busy() { return BUSY.get(); }
    static boolean platform(String value) { return "android".equals(value) || "ios".equals(value); }
    private static void changed() { ServerService.resourceTransferChanged(); }
    private static void checkCancelled() throws Failure { if (CANCEL.get()) throw new Failure("cancelled"); }
    private static void progress(long bytes) {
        current = new Snapshot(true, current.action, "running", bytes, null, null); changed();
    }
    private static boolean begin(Context context, String action, Work work) {
        if (!ServerService.resourceServerRunning() || !BUSY.compareAndSet(false, true)) return false;
        final Context application = context.getApplicationContext();
        CANCEL.set(false); current = new Snapshot(true, action, "preparing", 0, null, null); changed();
        IO.execute(() -> {
            Snapshot finished;
            try { checkCancelled(); finished = work.run(application); }
            catch (Exception error) {
                String code = CANCEL.get() ? "cancelled" : error instanceof Failure ? ((Failure) error).code
                        : error instanceof SecurityException ? "permission" : "transfer_failed";
                finished = new Snapshot(false, action, code.equals("cancelled") ? "cancelled" : "failed", current.bytes, code, null);
            } finally { activeConnection = null; activeInput = null; activeOutput = null; }
            current = finished; BUSY.set(false); changed();
        });
        return true;
    }
    static void cancelLocal() {
        if (!BUSY.get()) return;
        CANCEL.set(true);
        current = new Snapshot(true, current.action, "cancelling", current.bytes, null, null); changed();
        // A provider close/disconnect may block; never do it on the Android UI
        // or serialize it behind the running transfer. At most one cleanup exists.
        if (CLOSING.compareAndSet(false, true)) {
            final HttpURLConnection connection = activeConnection;
            final InputStream input = activeInput;
            final OutputStream output = activeOutput;
            Thread cleanup = new Thread(() -> {
                try {
                    if (connection != null) connection.disconnect();
                    try { if (input != null) input.close(); } catch (IOException ignored) { }
                    try { if (output != null) output.close(); } catch (IOException ignored) { }
                } finally { CLOSING.set(false); }
            }, "IdolyResourceClose");
            cleanup.setDaemon(true); cleanup.start();
        }
    }
    private static HttpURLConnection connection(String suffix) throws IOException {
        HttpURLConnection value = (HttpURLConnection) new URL(ORIGIN + suffix).openConnection(Proxy.NO_PROXY);
        value.setInstanceFollowRedirects(false); value.setUseCaches(false);
        value.setConnectTimeout(5000); value.setReadTimeout(5000);
        value.setRequestProperty("Accept-Encoding", "identity");
        activeConnection = value;
        return value;
    }
    private static JSONObject control(String suffix, JSONObject body) throws Exception {
        HttpURLConnection value = connection(suffix);
        try {
            if (body != null) {
                byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
                if (bytes.length > 4096) throw new Failure("invalid_request");
                value.setRequestMethod("POST"); value.setDoOutput(true); value.setFixedLengthStreamingMode(bytes.length);
                value.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                try (OutputStream stream = value.getOutputStream()) { stream.write(bytes); }
            }
            int code = value.getResponseCode();
            if (code != 200 && code != 202) throw new Failure(code == 409 ? "busy" : code == 404 ? "unavailable" : "server_error");
            if (value.getContentLengthLong() > CONTROL_LIMIT) throw new Failure("response_limit");
            String encoding = value.getContentEncoding();
            if (encoding != null && !encoding.equalsIgnoreCase("identity")) throw new Failure("invalid_response");
            try (InputStream stream = value.getInputStream(); ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
                byte[] block = new byte[4096]; int count;
                while ((count = stream.read(block)) != -1) {
                    checkCancelled();
                    if (bytes.size() + count > CONTROL_LIMIT) throw new Failure("response_limit");
                    bytes.write(block, 0, count);
                }
                String text = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                        .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes.toByteArray())).toString();
                return new JSONObject(text);
            }
        } finally { value.disconnect(); activeConnection = null; }
    }
    static boolean download(Context context, String platform) {
        if (!platform(platform)) return false;
        return begin(context, "download", app -> {
            control("/download", new JSONObject().put("platform", platform).put("kind", "all"));
            return new Snapshot(false, "download", "requested", 0, null, null);
        });
    }
    static boolean importArchive(Context context, Uri source, String platform) {
        if (source == null || !platform(platform)) return false;
        return begin(context, "import", app -> {
            try (ParcelFileDescriptor descriptor = app.getContentResolver().openFileDescriptor(source, "r")) {
                if (descriptor == null) throw new Failure("permission");
                try { Os.lseek(descriptor.getFileDescriptor(), 0, OsConstants.SEEK_CUR); }
                catch (Exception unseekable) { throw new Failure("seekable_required"); }
                checkCancelled();
                String raw = ServerService.importResourceFd(descriptor.getFd(), platform);
                JSONObject result = new JSONObject(raw);
                String state = result.optString("state", "failed");
                if (CANCEL.get() || state.equals("cancelled") || state.equals("cancelling")) throw new Failure("cancelled");
                Object error = result.opt("error_code");
                boolean hasError = error != null && error != JSONObject.NULL && !"".equals(error);
                return importOutcome(state, counter(result, "imported_files"), counter(result, "failed_files"),
                        counter(result, "imported_bytes"), hasError);
            }
        });
    }
    private static long counter(JSONObject value, String name) throws IOException {
        Object field = value.opt(name);
        if (!(field instanceof Integer || field instanceof Long) || ((Number) field).longValue() < 0)
            throw new Failure("invalid_response");
        return ((Number) field).longValue();
    }
    static Snapshot importOutcome(String state, long imported, long failed, long bytes, boolean hasError) throws IOException {
        if ((!"completed".equals(state) && !"partial".equals(state)) || imported < 0 || failed < 0 || bytes < 0)
            throw new Failure("import_failed");
        boolean warning = failed > 0 || hasError;
        return new Snapshot(false, "import", warning ? "partial" : state, bytes,
                warning ? "partial_import" : null, null, imported, failed);
    }
    private static Uri createDownload(Context context, String platform) throws Exception {
        String timestamp = new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT).format(new Date());
        ContentValues values = new ContentValues();
        values.put(MediaStore.MediaColumns.DISPLAY_NAME, "IdolyPride-Resources-" + platform + "-" + timestamp + ".zip");
        values.put(MediaStore.MediaColumns.MIME_TYPE, "application/zip");
        values.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/IdolyPride/exports");
        values.put(MediaStore.MediaColumns.IS_PENDING, 1);
        Uri result = context.getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
        if (result == null) throw new Failure("permission");
        return result;
    }
    private static void removeIncomplete(Context context, Uri destination, boolean shared) {
        if (destination == null) return;
        try {
            if (shared) context.getContentResolver().delete(destination, null, null);
            else DocumentsContract.deleteDocument(context.getContentResolver(), destination);
        } catch (Exception ignored) { /* Never delete any file except this newly created destination. */ }
    }
    static boolean exportArchive(Context context, String platform, Uri pickedDestination) {
        if (!platform(platform) || pickedDestination == null && Build.VERSION.SDK_INT < 29) return false;
        return begin(context, "export", app -> {
            HttpURLConnection value = connection("/export?platform=" + platform + "&kind=all");
            Uri destination = pickedDestination; boolean shared = destination == null, complete = false;
            long copied = 0; long lastProgress = 0;
            try {
                if (value.getResponseCode() != 200) throw new Failure("server_error");
                String encoding = value.getContentEncoding();
                if (encoding != null && !encoding.equalsIgnoreCase("identity")) throw new Failure("invalid_response");
                String job = value.getHeaderField("X-Idoly-Resource-Job");
                if (job == null || !job.matches("[A-Za-z0-9_-]{1,64}")) throw new Failure("invalid_response");
                if (shared) destination = createDownload(app, platform);
                checkCancelled(); Tail tail = new Tail();
                try (InputStream input = value.getInputStream(); OutputStream output = app.getContentResolver().openOutputStream(destination, "w")) {
                    if (output == null) throw new Failure("permission");
                    activeInput = input; activeOutput = output;
                    byte[] block = new byte[64 * 1024]; int count;
                    while ((count = input.read(block)) != -1) {
                        checkCancelled();
                        if (copied > Long.MAX_VALUE - count) throw new Failure("response_limit");
                        output.write(block, 0, count); tail.add(block, count); copied += count;
                        long now = SystemClock.elapsedRealtime();
                        if (now - lastProgress >= 1000) { progress(copied); lastProgress = now; }
                    }
                    output.flush();
                } finally { activeInput = null; activeOutput = null; }
                if (!zipComplete(tail.bytes(), copied)) throw new Failure("incomplete_archive");
                value.disconnect(); activeConnection = null;
                JSONObject result = control("?platform=" + platform, null).optJSONObject("job");
                if (result == null || !job.equals(result.optString("job_id"))) throw new Failure("unconfirmed_archive");
                String state = result.optString("state", "failed");
                Object failedFiles = result.opt("failed_files");
                long failed = failedFiles instanceof Integer || failedFiles instanceof Long ? ((Number) failedFiles).longValue() : -1;
                if (!exportConfirmed(job, result.optString("job_id"), state,
                        Boolean.TRUE.equals(result.opt("archive_complete")), failed)) throw new Failure("unconfirmed_archive");
                checkCancelled();
                if (shared) {
                    ContentValues visible = new ContentValues(); visible.put(MediaStore.MediaColumns.IS_PENDING, 0);
                    if (app.getContentResolver().update(destination, visible, null, null) != 1) throw new Failure("permission");
                }
                complete = true;
                return new Snapshot(false, "export", state, copied, null, shared ? "downloads" : "document");
            } finally {
                value.disconnect(); activeConnection = null;
                if (!complete) removeIncomplete(app, destination, shared);
            }
        });
    }
    private static final class Tail {
        final byte[] value = new byte[128 * 1024]; int size;
        void add(byte[] bytes, int count) {
            if (size + count > value.length) {
                int keep = value.length - count;
                System.arraycopy(value, size - keep, value, 0, keep); size = keep;
            }
            System.arraycopy(bytes, 0, value, size, count); size += count;
        }
        byte[] bytes() { return Arrays.copyOf(value, size); }
    }
    /** Validate the bounded ZIP/ZIP64 footer before exposing an EOF-terminated stream. */
    static boolean exportConfirmed(String expected, String actual, String state, boolean archiveComplete, long failedFiles) {
        return expected != null && expected.equals(actual) && archiveComplete && failedFiles == 0
                && ("completed".equals(state) || "partial".equals(state));
    }
    static boolean zipComplete(byte[] tail, long total) {
        if (total < 22 || tail.length > total) return false;
        ByteBuffer value = ByteBuffer.wrap(tail).order(ByteOrder.LITTLE_ENDIAN);
        for (int end = tail.length - 22; end >= Math.max(0, tail.length - 65557); end--) {
            if (value.getInt(end) != 0x06054b50 || end + 22 + Short.toUnsignedInt(value.getShort(end + 20)) != tail.length) continue;
            if (value.getShort(end + 4) != 0 || value.getShort(end + 6) != 0 || value.getShort(end + 8) != value.getShort(end + 10)) return false;
            long size = Integer.toUnsignedLong(value.getInt(end + 12)), start = Integer.toUnsignedLong(value.getInt(end + 16));
            long entries = Short.toUnsignedInt(value.getShort(end + 10));
            long boundary = total - tail.length + end;
            if (size == 0xffffffffL || start == 0xffffffffL || Short.toUnsignedInt(value.getShort(end + 10)) == 65535) {
                int locator = end - 20;
                if (locator < 0 || value.getInt(locator) != 0x07064b50 || value.getInt(locator + 4) != 0 || value.getInt(locator + 16) != 1) return false;
                long record = value.getLong(locator + 8), inTail = record - (total - tail.length);
                if (record < 0 || inTail < 0 || inTail > locator - 56) return false;
                int at = (int) inTail;
                long length = value.getLong(at + 4);
                if (value.getInt(at) != 0x06064b50 || length < 44 || length != locator - at - 12
                        || value.getInt(at + 16) != 0 || value.getInt(at + 20) != 0
                        || value.getLong(at + 24) != value.getLong(at + 32) || value.getLong(at + 32) < 0) return false;
                entries = value.getLong(at + 32);
                size = value.getLong(at + 40); start = value.getLong(at + 48); boundary = record;
            }
            return start >= 0 && size >= 0 && entries >= 0 && entries <= size / 46
                    && start <= boundary && size == boundary - start;
        }
        return false;
    }
    private ResourceTransfers() { }
}
