package game.qualiarts.idolypride.localserver;

import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Arrays;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

public final class ResourceTransfersHostTest {
    private static int checks;
    private static void check(boolean value) { checks++; if (!value) throw new AssertionError("Resource footer " + checks); }
    public static void main(String[] args) throws Exception {
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
