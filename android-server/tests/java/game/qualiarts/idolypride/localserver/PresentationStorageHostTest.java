package game.qualiarts.idolypride.localserver;

import java.io.ByteArrayOutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Real ZIP sizes and unknown arithmetic; no Android runtime or device files. */
public final class PresentationStorageHostTest {
    private static int checks;
    private static void check(boolean value) {
        checks++;
        if (!value) throw new AssertionError("storage check " + checks);
    }
    private static byte[] archive(String[] names, int[] sizes) throws Exception {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        try (ZipOutputStream zip = new ZipOutputStream(output)) {
            for (int index = 0; index < names.length; index++) {
                zip.putNextEntry(new ZipEntry(names[index]));
                zip.write(new byte[sizes[index]]);
                zip.closeEntry();
            }
        }
        return output.toByteArray();
    }
    public static void main(String[] args) throws Exception {
        check(PresentationStorage.total(270744, 159549324, 210182656) == 370002724);
        check(PresentationStorage.total(270744, 0, 210182656) == 210453400);
        check(PresentationStorage.total(1, -1, 3) == -1);
        check(PresentationStorage.total(Long.MAX_VALUE, 1) == -1);
        check(PresentationStorage.total(0, 0) == 0);
        PresentationStorage.Estimate unknown = new PresentationStorage.Estimate("diagnostics", 123, 0,
                -1, -1, -1, "unknown");
        check(unknown.totalBytes == -1 && unknown.existingCopyBytes == 0);
        check(unknown.availableBytes == -1 && unknown.freeBytes == -1);
        byte[] zip = archive(new String[]{"lib/arm64-v8a/liba.so", "lib/armeabi-v7a/liba.so",
                "assets/ignored", "lib/arm64-v8a/nested/not-a-library.so"}, new int[]{7, 11, 3, 13});
        check(PresentationStorage.nativeBytes(zip) == 7);
        Path file = Files.createTempFile("presentation-storage-host-", ".apk");
        try {
            Files.write(file, zip);
            check(PresentationStorage.nativeBytes(file.toFile()) == 7);
            byte[] before = Files.readAllBytes(file);
            PresentationStorage.nativeBytes(file.toFile());
            check(java.util.Arrays.equals(before, Files.readAllBytes(file)));
        } finally { Files.deleteIfExists(file); }
        check(PresentationStorage.nativeBytes(new byte[0]) == -1);
        check(PresentationStorage.nativeBytes(new byte[]{'P', 'K', 3, 4}) == -1);
        check(PresentationStorage.nativeBytes(new byte[1024 * 1024 + 1]) == -1);
        byte[] expanded = archive(new String[]{"lib/arm64-v8a/large.so"}, new int[]{9 * 1024 * 1024});
        check(expanded.length < 1024 * 1024);
        check(PresentationStorage.nativeBytes(expanded) == -1);
        String[] names = new String[65];
        for (int index = 0; index < names.length; index++) names[index] = "assets/" + index;
        check(PresentationStorage.nativeBytes(archive(names, new int[65])) == -1);
        System.out.println("Presentation storage host checks PASS: " + checks);
    }
}
