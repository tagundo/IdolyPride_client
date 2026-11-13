package game.qualiarts.idolypride.localserver;

import java.io.ByteArrayOutputStream;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Arrays;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

public final class ResourceTransfersHostTest {
    private static int checks;
    private static void check(boolean value) { checks++; if (!value) throw new AssertionError("Resource footer " + checks); }
    private static final class ShortInput extends ByteArrayInputStream {
        private final int step;
        int reads;
        ShortInput(byte[] bytes, int step) { super(bytes); this.step = step; }
        @Override public synchronized int read(byte[] bytes, int offset, int length) {
            reads++;
            return super.read(bytes, offset, Math.min(length, step));
        }
    }
    private static void resourceChunks() throws Exception {
        byte[] payload = new byte[1024 * 1024];
        for (int i = 0; i < payload.length; i++) payload[i] = (byte)(i * 31 + 7);
        byte[] buffer = new byte[64 * 1024];
        long oldCalls = 0, chunkCalls = 0, networkReads = 0;
        for (int worker = 0; worker < 8; worker++) {
            ShortInput before = new ShortInput(payload, 16 * 1024);
            while (true) { oldCalls++; if (before.read(buffer, 0, buffer.length) < 0) break; }
            ShortInput after = new ShortInput(payload, 16 * 1024);
            ByteArrayOutputStream copied = new ByteArrayOutputStream();
            while (true) {
                chunkCalls++;
                int count = ResourceTransfers.readResourceChunk(after, buffer, buffer.length);
                if (count < 0) break;
                check(count > 0 && count <= buffer.length);
                copied.write(buffer, 0, count);
            }
            check(Arrays.equals(payload, copied.toByteArray()));
            networkReads += after.reads;
        }
        // A preempted worker can legitimately hit the 50ms yield budget.
        check(oldCalls == 520 && chunkCalls <= 264 && networkReads == 520);
        ShortInput oneByte = new ShortInput(new byte[]{0, (byte)255, 17}, 1);
        check(ResourceTransfers.readResourceChunk(oneByte, buffer, 16) == 3);
        check(buffer[0] == 0 && buffer[1] == (byte)255 && buffer[2] == 17);
        check(ResourceTransfers.readResourceChunk(oneByte, buffer, 1) == -1);
        ByteArrayInputStream excess = new ByteArrayInputStream(new byte[]{1, 2, 3, 4, 5});
        check(ResourceTransfers.readResourceChunk(excess, buffer, 4) == 4);
        check(ResourceTransfers.readResourceChunk(excess, buffer, 1) == 1 && buffer[0] == 5);
        InputStream zero = new InputStream() {
            private int value;
            @Override public int read(byte[] bytes, int offset, int length) { return 0; }
            @Override public int read() { return value < 3 ? ++value : -1; }
        };
        check(ResourceTransfers.readResourceChunk(zero, buffer, 16) == 3);
        check(buffer[0] == 1 && buffer[1] == 2 && buffer[2] == 3);
        InputStream slow = new InputStream() {
            int reads;
            @Override public int read() { throw new AssertionError("Unexpected single-byte read"); }
            @Override public int read(byte[] bytes, int offset, int length) throws IOException {
                if (++reads > 1) throw new AssertionError("Slow stream did not return to deadline checks");
                try { Thread.sleep(65); } catch (InterruptedException error) { throw new IOException(error); }
                bytes[offset] = 11;
                return 1;
            }
        };
        check(ResourceTransfers.readResourceChunk(slow, buffer, 64) == 1 && buffer[0] == 11);
        for (int invalid : new int[]{Integer.MIN_VALUE, -1, 0, buffer.length + 1, Integer.MAX_VALUE}) {
            try { ResourceTransfers.readResourceChunk(excess, buffer, invalid); throw new AssertionError("Invalid chunk accepted"); }
            catch (IOException expected) { checks++; }
        }
        try { ResourceTransfers.readResourceChunk(excess, new byte[65537], 65537); throw new AssertionError("Oversized buffer read accepted"); }
        catch (IOException expected) { checks++; }
        try { ResourceTransfers.readResourceChunk(null, buffer, 1); throw new AssertionError("Null stream accepted"); }
        catch (IOException expected) { checks++; }
        try { ResourceTransfers.readResourceChunk(excess, null, 1); throw new AssertionError("Null buffer accepted"); }
        catch (IOException expected) { checks++; }
        InputStream broken = new InputStream() {
            @Override public int read() throws IOException { throw new IOException("synthetic failure"); }
        };
        try { ResourceTransfers.readResourceChunk(broken, buffer, 1); throw new AssertionError("Read failure suppressed"); }
        catch (IOException expected) { checks++; }
        CountDownLatch blocked = new CountDownLatch(1);
        AtomicReference<Throwable> failure = new AtomicReference<>();
        InputStream cancellable = new InputStream() {
            private boolean closed;
            @Override public synchronized int read() throws IOException {
                blocked.countDown();
                while (!closed) {
                    try { wait(); } catch (InterruptedException error) { throw new IOException(error); }
                }
                throw new IOException("closed");
            }
            @Override public synchronized void close() { closed = true; notifyAll(); }
        };
        Thread reader = new Thread(() -> {
            try { ResourceTransfers.readResourceChunk(cancellable, buffer, buffer.length); }
            catch (Throwable error) { failure.set(error); }
        }, "ResourceChunkCancellationTest");
        reader.setDaemon(true); reader.start();
        try { check(blocked.await(1, TimeUnit.SECONDS)); }
        finally { cancellable.close(); }
        reader.join(1000);
        check(!reader.isAlive() && failure.get() instanceof IOException);
        System.out.println("PASS: Android 16KiB-short-read model, 8x1MiB; bridge calls " + oldCalls
                + " -> " + chunkCalls + "; network reads unchanged " + networkReads + "; byte equality and cancellation verified");
    }
    public static void main(String[] args) throws Exception {
        resourceChunks();
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (ZipOutputStream zip = new ZipOutputStream(bytes)) {
            zip.putNextEntry(new ZipEntry("public/manifest.json")); zip.write("{\"schema\":1}".getBytes("UTF-8")); zip.closeEntry();
            zip.setComment("complete public archive");
        }
        byte[] normal = bytes.toByteArray();
        check(ResourceTransfers.zipComplete(normal, normal.length));
        check(!ResourceTransfers.zipComplete(Arrays.copyOf(normal, normal.length - 1), normal.length - 1));
        check(!ResourceTransfers.zipComplete(new byte[22], 22));
        byte[] changed = normal.clone();
        int end = normal.length - 22 - "complete public archive".length();
        changed[end + 16] ^= 1;
        check(!ResourceTransfers.zipComplete(changed, changed.length));
        long boundary = (1L << 32) + 100;
        ByteBuffer zip64 = ByteBuffer.allocate(98).order(ByteOrder.LITTLE_ENDIAN);
        zip64.putInt(0x06064b50).putLong(44).putShort((short)45).putShort((short)45).putInt(0).putInt(0)
                .putLong(1).putLong(1).putLong(95).putLong(boundary - 95);
        zip64.putInt(0x07064b50).putInt(0).putLong(boundary).putInt(1);
        zip64.putInt(0x06054b50).putShort((short)0).putShort((short)0).putShort((short)-1).putShort((short)-1)
                .putInt(-1).putInt(-1).putShort((short)0);
        check(ResourceTransfers.zipComplete(zip64.array(), boundary + 98));
        changed = zip64.array().clone(); changed[56 + 16] = 2;
        check(!ResourceTransfers.zipComplete(changed, boundary + 98));
        changed = zip64.array().clone(); changed[4] = 45;
        check(!ResourceTransfers.zipComplete(changed, boundary + 98));
        byte[] fake = new byte[22]; ByteBuffer f = ByteBuffer.wrap(fake).order(ByteOrder.LITTLE_ENDIAN);
        f.putInt(0x06054b50).putShort((short)0).putShort((short)0).putShort((short)1).putShort((short)1);
        check(!ResourceTransfers.zipComplete(fake, 22));
        check(ResourceTransfers.platform("android") && ResourceTransfers.platform("ios") && !ResourceTransfers.platform("../other"));
        for (int parallelism : new int[]{1, 2, 4, 8}) {
            check(ResourceTransfers.downloadParallelism(parallelism));
            check(ResourceTransfers.downloadParallelismAt(ResourceTransfers.downloadParallelismPosition(parallelism)) == parallelism);
            for (String platform : new String[]{"android", "ios"})
                check(ResourceTransfers.downloadPayload(platform, parallelism).equals("{\"platform\":\"" + platform
                        + "\",\"kind\":\"all\",\"parallelism\":" + parallelism + "}"));
        }
        for (int invalid : new int[]{Integer.MIN_VALUE, -1, 0, 3, 5, 9, Integer.MAX_VALUE}) {
            check(!ResourceTransfers.downloadParallelism(invalid));
            check(ResourceTransfers.downloadParallelismAt(ResourceTransfers.downloadParallelismPosition(invalid)) == 4);
            check(!ResourceTransfers.download(null, "android", invalid));
            try { ResourceTransfers.downloadPayload("android", invalid); throw new AssertionError("Invalid parallelism accepted"); }
            catch (java.io.IOException expected) { checks++; }
        }
        check(ResourceTransfers.downloadParallelismAt(-1) == 4 && ResourceTransfers.downloadParallelismAt(4) == 4);
        for (String invalid : new String[]{null, "", "../other", "android\""}) {
            check(!ResourceTransfers.download(null, invalid, 4));
            try { ResourceTransfers.downloadPayload(invalid, 4); throw new AssertionError("Invalid platform accepted"); }
            catch (java.io.IOException expected) { checks++; }
        }
        check(ResourceTransfers.exportConfirmed("job", "job", "completed", true, 0));
        check(ResourceTransfers.exportConfirmed("job", "job", "partial", true, 0));
        check(!ResourceTransfers.exportConfirmed("job", "job", "partial", false, 0));
        check(!ResourceTransfers.exportConfirmed("job", "job", "partial", true, 1));
        check(!ResourceTransfers.exportConfirmed("job", "other", "completed", true, 0));
        check(!ResourceTransfers.exportConfirmed("job", "job", "cancelled", true, 0));
        ResourceTransfers.Snapshot imported = ResourceTransfers.importOutcome("completed", 12, 0, 4096, false);
        check(imported.importedFiles == 12 && imported.failedFiles == 0 && imported.error == null && imported.state.equals("completed"));
        imported = ResourceTransfers.importOutcome("partial", 10, 0, 1024, false);
        check(imported.error == null && imported.state.equals("partial") && imported.importedFiles == 10);
        imported = ResourceTransfers.importOutcome("partial", 10, 2, 1024, false);
        check(imported.error.equals("partial_import") && imported.failedFiles == 2 && imported.importedFiles == 10);
        imported = ResourceTransfers.importOutcome("completed", 10, 0, 1024, true);
        check(imported.state.equals("partial") && imported.error.equals("partial_import") && imported.importedFiles == 10);
        try { ResourceTransfers.importOutcome("failed", 0, 2, 0, true); throw new AssertionError("Failed import accepted"); }
        catch (java.io.IOException expected) { checks++; }
        for (int sdk : new int[]{26, 28, 29}) {
            check(ResourceTransfers.storageAccess(sdk, true, true) == ResourceTransfers.STORAGE_UNSUPPORTED);
            check(ResourceTransfers.storageAccess(sdk, false, false) == ResourceTransfers.STORAGE_PRIVATE);
        }
        for (int sdk : new int[]{30, 37}) {
            check(ResourceTransfers.storageAccess(sdk, true, false) == ResourceTransfers.STORAGE_PERMISSION);
            check(ResourceTransfers.storageAccess(sdk, true, true) == ResourceTransfers.STORAGE_DOWNLOADS);
            check(ResourceTransfers.storageAccess(sdk, false, false) == ResourceTransfers.STORAGE_PRIVATE);
            check(ResourceTransfers.storageAccess(sdk, false, true) == ResourceTransfers.STORAGE_PRIVATE);
        }
        java.nio.file.Path root = java.nio.file.Files.createTempDirectory("resource-storage-policy");
        try {
            String expected = root.toFile().getCanonicalPath() + java.io.File.separator + "IdolyPride";
            check(ResourceTransfers.publicCachePath(root.resolve(".").toFile()).equals(expected));
            check(!java.nio.file.Files.exists(root.resolve("IdolyPride")));
        } finally { java.nio.file.Files.delete(root); }
        System.out.println("PASS: " + checks + " ZIP/ZIP64 complete-stream and platform checks");
    }
}
