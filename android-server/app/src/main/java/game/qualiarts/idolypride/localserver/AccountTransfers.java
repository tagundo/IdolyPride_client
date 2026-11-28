package game.qualiarts.idolypride.localserver;

import android.content.Context;
import android.net.Uri;
import android.os.SystemClock;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.util.UUID;

/** Only native document-picker URIs cross this boundary; never WebView paths. */
final class AccountTransfers {
    static final long MAX_ARCHIVE_BYTES = 128L * 1024 * 1024;
    private static final int CHUNK = 64 * 1024;
    interface Progress { void copied(String phase, long bytes, long total); }
    static final class Failure extends IOException {
        final String code; Failure(String code) { super(code); this.code = code; }
    }
    private AccountTransfers() {}

    private static File directory(Context context, String name) throws IOException {
        File data = new File(context.getFilesDir(), "data");
        File management = new File(data, "account-management");
        File directory = new File(management, name);
        if (Files.isSymbolicLink(data.toPath()) || Files.isSymbolicLink(management.toPath()) || Files.isSymbolicLink(directory.toPath()))
            throw new Failure("account_storage_unavailable");
        if (!directory.isDirectory() && !directory.mkdirs()) throw new Failure("account_storage_unavailable");
        return directory.getCanonicalFile();
    }

    static File stage(Context context, Uri source, Progress progress) throws IOException {
        if (source == null || !"content".equals(source.getScheme())) throw new Failure("account_document_unavailable");
        File inbox = directory(context, "inbox");
        File target = new File(inbox, "account-import-" + UUID.randomUUID().toString().replace("-", "") + ".zip");
        if (!target.createNewFile()) throw new Failure("account_document_unavailable");
        boolean complete = false;
        try (InputStream input = context.getContentResolver().openInputStream(source);
             OutputStream output = new FileOutputStream(target)) {
            if (input == null) throw new Failure("account_document_unavailable");
            copy(input, output, null, progress, "copying", 0);
            complete = true;
            return target;
        } finally {
            if (!complete) target.delete();
        }
    }

    static File approvedExport(Context context, String path) throws IOException {
        if (path == null) throw new Failure("account_export_unavailable");
        File file = new File(path);
        File exports = directory(context, "exports");
        if (!file.isAbsolute() || !file.getName().matches("IdolyPride-Account-[0-9a-f]{32}\\.zip")
                || Files.isSymbolicLink(file.toPath()) || !file.isFile()
                || !exports.equals(file.getCanonicalFile().getParentFile())
                || file.length() <= 0 || file.length() > MAX_ARCHIVE_BYTES)
            throw new Failure("account_export_unavailable");
        return file;
    }

    static void save(Context context, Uri destination, String path, long expected, String sha256, Progress progress) throws IOException {
        if (destination == null || !"content".equals(destination.getScheme()))
            throw new Failure("account_document_unavailable");
        File file = approvedExport(context, path);
        if (expected != file.length() || sha256 == null || !sha256.matches("[0-9a-f]{64}"))
            throw new Failure("account_export_identity_invalid");
        MessageDigest digest;
        try { digest = MessageDigest.getInstance("SHA-256"); }
        catch (NoSuchAlgorithmException impossible) { throw new Failure("account_digest_unavailable"); }
        try (InputStream input = new FileInputStream(file);
             OutputStream output = context.getContentResolver().openOutputStream(destination, "wt")) {
            if (output == null) throw new Failure("account_document_unavailable");
            if (copy(input, output, digest, progress, "saving", expected) != expected
                    || !hex(digest.digest()).equals(sha256)) throw new Failure("account_export_identity_invalid");
        }
        // This exact owned temporary export is no longer needed after successful document I/O.
        file.delete();
    }

    static void discardExport(Context context, String path) {
        try { approvedExport(context, path).delete(); } catch (IOException ignored) { }
    }

    private static String hex(byte[] bytes) {
        char[] hex = "0123456789abcdef".toCharArray(); char[] result = new char[bytes.length * 2];
        for (int index = 0; index < bytes.length; index++) { int value = bytes[index] & 255; result[index * 2] = hex[value >>> 4]; result[index * 2 + 1] = hex[value & 15]; }
        return new String(result);
    }

    private static long copy(InputStream input, OutputStream output, MessageDigest digest, Progress progress, String phase, long total) throws IOException {
        byte[] bytes = new byte[CHUNK];
        long count = 0, lastReport = 0;
        for (int length; (length = input.read(bytes)) != -1;) {
            if (length == 0) continue;
            count += length;
            if (count > MAX_ARCHIVE_BYTES) throw new Failure("account_archive_too_large");
            output.write(bytes, 0, length);
            if (digest != null) digest.update(bytes, 0, length);
            long now = SystemClock.uptimeMillis();
            if (progress != null && now - lastReport >= 250) { progress.copied(phase, count, total); lastReport = now; }
        }
        if (count == 0) throw new Failure("account_archive_empty");
        output.flush();
        if (progress != null) progress.copied(phase, count, total);
        return count;
    }
}
