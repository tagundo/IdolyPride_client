package game.qualiarts.idolypride.localserver;

import android.content.Context;
import android.content.pm.PackageInfo;
import android.os.StatFs;
import android.os.storage.StorageManager;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.util.Enumeration;
import java.util.UUID;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import java.util.zip.ZipInputStream;

/** Read-only code-volume observations; estimates never authorize or block an install. */
final class PresentationStorage {
    static final long UNKNOWN = -1;
    private static final long MAX_NATIVE_BYTES = 512L * 1024 * 1024;

    static final class Estimate {
        final String profileId;
        final long addonBytes, existingCopyBytes, nativeExtractBytes, totalBytes, availableBytes, freeBytes;
        final String volume;
        Estimate(String profileId, long addonBytes, long existingCopyBytes, long nativeExtractBytes,
                long availableBytes, long freeBytes, String volume) {
            this.profileId = profileId;
            this.addonBytes = addonBytes;
            this.existingCopyBytes = existingCopyBytes;
            this.nativeExtractBytes = nativeExtractBytes;
            this.totalBytes = total(addonBytes, existingCopyBytes, nativeExtractBytes);
            this.availableBytes = availableBytes;
            this.freeBytes = freeBytes;
            this.volume = volume;
        }
    }

    static Estimate inspect(Context context, PresentationAddonInstaller.Profile profile,
            PackageInfo installed, boolean featureOnly) {
        long copied = featureOnly ? 0 : UNKNOWN, nativeBytes = UNKNOWN, available = UNKNOWN, free = UNKNOWN;
        String volume = "unknown";
        File code = installed.applicationInfo == null || installed.applicationInfo.sourceDir == null
                ? null : new File(installed.applicationInfo.sourceDir);
        if (code != null) {
            try { free = new StatFs(code.getParent()).getAvailableBytes(); }
            catch (RuntimeException ignored) { }
            try {
                StorageManager manager = context.getSystemService(StorageManager.class);
                if (manager != null) {
                    UUID uuid = manager.getUuidForPath(code);
                    volume = StorageManager.UUID_DEFAULT.equals(uuid) ? "internal" : "other";
                    available = manager.getAllocatableBytes(uuid);
                }
            } catch (Exception ignored) { }
        }
        try {
            PresentationAddonInstaller.ExistingPlan plan = PresentationAddonInstaller.ExistingApkPolicy.plan(
                    installed.applicationInfo.sourceDir, installed.splitNames,
                    installed.applicationInfo.splitSourceDirs, profile.apkBytes);
            copied = featureOnly ? 0 : plan.sessionBytes - profile.apkBytes;
            nativeBytes = 0;
            for (PresentationAddonInstaller.ExistingApk apk : plan.files) {
                nativeBytes = total(nativeBytes, nativeBytes(apk.file));
                if (nativeBytes < 0) break;
            }
            if (nativeBytes >= 0) {
                try (InputStream source = context.getAssets().open(profile.asset)) {
                    ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                    byte[] buffer = new byte[8192];
                    int count;
                    while ((count = source.read(buffer)) != -1) {
                        if (bytes.size() + count > 1024 * 1024) throw new java.io.IOException();
                        bytes.write(buffer, 0, count);
                    }
                    nativeBytes = total(nativeBytes, nativeBytes(bytes.toByteArray()));
                }
            }
        } catch (Exception ignored) { nativeBytes = UNKNOWN; }
        return new Estimate(profile.id, profile.apkBytes, copied, nativeBytes, available, free, volume);
    }

    /** Sum known bytes only. Unknown inputs, negative numbers and overflow stay unknown. */
    static long total(long... values) {
        long result = 0;
        for (long value : values) {
            if (value < 0 || value > Long.MAX_VALUE - result) return UNKNOWN;
            result += value;
        }
        return result;
    }

    private static boolean arm64Library(String name) {
        String prefix = "lib/arm64-v8a/";
        return name.startsWith(prefix) && name.endsWith(".so")
                && name.indexOf('/', prefix.length()) < 0;
    }

    /** Installed APK central-directory sizes only: no extraction or native-code loading. */
    static long nativeBytes(File apk) throws java.io.IOException {
        long sum = 0;
        try (ZipFile archive = new ZipFile(apk)) {
            Enumeration<? extends ZipEntry> entries = archive.entries();
            int count = 0;
            while (entries.hasMoreElements()) {
                if (++count > 8192) return UNKNOWN;
                ZipEntry entry = entries.nextElement();
                if (arm64Library(entry.getName())) {
                    sum = total(sum, entry.getSize());
                    if (sum < 0 || sum > MAX_NATIVE_BYTES) return UNKNOWN;
                }
            }
        }
        return sum;
    }

    /** The bundled feature is at most 1 MiB; bound expanded reads as well. */
    static long nativeBytes(byte[] apk) throws java.io.IOException {
        if (apk == null || apk.length < 4 || apk.length > 1024 * 1024
                || apk[0] != 'P' || apk[1] != 'K' || apk[2] != 3 || apk[3] != 4) return UNKNOWN;
        long sum = 0, expanded = 0;
        int count = 0;
        try (ZipInputStream archive = new ZipInputStream(new ByteArrayInputStream(apk))) {
            ZipEntry entry;
            byte[] buffer = new byte[8192];
            while ((entry = archive.getNextEntry()) != null) {
                if (++count > 64) return UNKNOWN;
                boolean library = arm64Library(entry.getName());
                long size = 0;
                int read;
                while ((read = archive.read(buffer)) != -1) {
                    expanded += read;
                    if (expanded > 8L * 1024 * 1024) return UNKNOWN;
                    size += read;
                }
                if (library) sum = total(sum, size);
            }
        }
        return count == 0 ? UNKNOWN : sum;
    }
}
