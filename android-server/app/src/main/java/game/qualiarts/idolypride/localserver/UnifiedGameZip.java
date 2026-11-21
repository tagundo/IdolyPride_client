package game.qualiarts.idolypride.localserver;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.security.DigestOutputStream;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** ZIP32 compressed-span transport. It never extracts paths or executes code. */
final class UnifiedGameZip {
    static final long MAX_BYTES = 1024L * 1024 * 1024;
    static final int MAX_ENTRIES = 16000;
    static final String DATA = "assets/bin/Data/";
    static final java.util.Set<String> STATIC_ASSETS = java.util.Collections.unmodifiableSet(new java.util.HashSet<>(java.util.Arrays.asList(
        "assets/UnityServicesProjectConfiguration.json", "assets/WebView/Inquiry.html",
        "assets/WebView/Scripts/Common.js", "assets/WebView/Scripts/Inquiry.js",
        "assets/WebView/Scripts/ResponsiveZoom.js", "assets/WebView/Styles/Common.css",
        "assets/WebView/Styles/Inquiry.css", "assets/WebView/Svg/Pencil.svg",
        "assets/ad-viewer/155.3702126d.js", "assets/ad-viewer/245.b30b6372.js",
        "assets/ad-viewer/44.348bc690.js", "assets/ad-viewer/ad-viewer-vendors.d9d1c22a.js",
        "assets/ad-viewer/ad-viewer.v1.32.14-ad-viewer.html", "assets/ad-viewer/adViewer.375b5d46.js",
        "assets/ad-viewer/config.ad-viewer.json", "assets/ad-viewer/da_DK.b28daa43.js",
        "assets/ad-viewer/de.217602b4.js", "assets/ad-viewer/es.9d1bca2b.js",
        "assets/ad-viewer/fi.e8ed832a.js", "assets/ad-viewer/fr.c27766d8.js",
        "assets/ad-viewer/is.7b423306.js", "assets/ad-viewer/it.944d3766.js",
        "assets/ad-viewer/ja.4a7c2a26.js", "assets/ad-viewer/ko.48e4bc29.js",
        "assets/ad-viewer/lt.2d96e2c4.js", "assets/ad-viewer/mraid.0.0.4.js",
        "assets/ad-viewer/nb.36dbde1f.js", "assets/ad-viewer/omid-session-client-v1.js",
        "assets/ad-viewer/omsdk-v1.js", "assets/ad-viewer/pt.87216b1c.js",
        "assets/ad-viewer/pt_BR.f97205cf.js", "assets/ad-viewer/ro.5e220f49.js",
        "assets/ad-viewer/ru.51df9ac7.js", "assets/ad-viewer/sv.c8af148a.js",
        "assets/ad-viewer/tr.909011ff.js", "assets/ad-viewer/zh_Hans.0320c043.js",
        "assets/ad-viewer/zh_Hant.e7c3056e.js", "assets/google-services-desktop.json",
        "assets/idoly-diagnostics-licenses/ShadowHook-MIT.txt", "assets/idoly-diagnostics-licenses/ShadowHook-third-party.txt",
        "assets/idoly-diagnostics-native.json", "assets/idoly-fonts/IdolyFontSupport.json",
        "assets/idoly-fonts/OFL-Pretendard.txt", "assets/idoly-local.json",
        "assets/idoly-presentation-licenses/NDK-RUNTIME-NOTICES.txt", "assets/idoly-presentation-standalone.json"
    )));
    static boolean carrierMember(String name) { return name.startsWith(DATA) || STATIC_ASSETS.contains(name); }

    static IOException bad(String code) { return new IOException(code); }
    static void require(boolean value, String code) throws IOException { if (!value) throw bad(code); }
    static boolean name(String value) {
        if (value == null || value.length() == 0 || value.length() >= 1024 || value.startsWith("/")) return false;
        for (int i = 0; i < value.length(); ++i) if (value.charAt(i) < 32 || value.charAt(i) > 126 || value.charAt(i) == '\\') return false;
        for (String part : value.split("/", -1)) if (part.isEmpty() || part.equals(".") || part.equals("..")) return false;
        return true;
    }
    static MessageDigest digest() {
        try { return MessageDigest.getInstance("SHA-256"); }
        catch (java.security.NoSuchAlgorithmException impossible) { throw new AssertionError(impossible); }
    }
    static String hex(byte[] raw) {
        char[] result = new char[raw.length * 2]; String alphabet = "0123456789abcdef";
        for (int i = 0; i < raw.length; ++i) { result[i * 2] = alphabet.charAt((raw[i] & 255) >>> 4); result[i * 2 + 1] = alphabet.charAt(raw[i] & 15); }
        return new String(result);
    }
    static String hash(File file) throws IOException {
        MessageDigest hash = digest(); byte[] buffer = new byte[128 * 1024];
        try (FileInputStream source = new FileInputStream(file)) { int count; while ((count = source.read(buffer)) != -1) hash.update(buffer, 0, count); }
        return hex(hash.digest());
    }
    private static int u16(byte[] raw, int at) { return (raw[at] & 255) | (raw[at + 1] & 255) << 8; }
    private static long u32(byte[] raw, int at) { return ((long) u16(raw, at)) | (long) u16(raw, at + 2) << 16; }

    static final class Span {
        final String name; final int method, flags; final long bytes, compressed, crc, offset;
        Span(String n, int m, int f, long b, long c, long r, long o) { name = n; method = m; flags = f; bytes = b; compressed = c; crc = r; offset = o; }
    }
    static final class Source implements AutoCloseable {
        final RandomAccessFile file; final Map<String, Span> members = new HashMap<>();
        Source(File path) throws IOException {
            file = new RandomAccessFile(path, "r");
            try { inspect(); } catch (Throwable failure) { file.close(); throw failure; }
        }
        private byte[] read(int count) throws IOException { byte[] raw = new byte[count]; file.readFully(raw); return raw; }
        private void inspect() throws IOException {
            long length = file.length(); require(length >= 22 && length <= MAX_BYTES, "unified_zip_size_invalid");
            int tailSize = (int) Math.min(length, 65557); file.seek(length - tailSize); byte[] tail = read(tailSize); int end = -1;
            for (int at = tail.length - 22; at >= 0; --at) {
                if (u32(tail, at) == 0x06054b50L && at + 22 + u16(tail, at + 20) == tail.length) { end = at; break; }
            }
            require(end >= 0, "unified_zip_directory_missing");
            int count = u16(tail, end + 10); long directorySize = u32(tail, end + 12), start = u32(tail, end + 16);
            require(u16(tail, end + 4) == 0 && u16(tail, end + 6) == 0 && u16(tail, end + 8) == count
                    && count > 0 && count <= MAX_ENTRIES && count < 65535
                    && start + directorySize == length - tailSize + end, "unified_zip_directory_invalid");
            long cursor = start; List<long[]> ranges = new ArrayList<>();
            for (int index = 0; index < count; ++index) {
                require(cursor + 46 <= start + directorySize, "unified_zip_directory_truncated");
                file.seek(cursor); byte[] row = read(46);
                require(u32(row, 0) == 0x02014b50L && u16(row, 34) == 0, "unified_zip_central_invalid");
                int flags = u16(row, 8), method = u16(row, 10), nameLength = u16(row, 28), extraLength = u16(row, 30), commentLength = u16(row, 32);
                long compressed = u32(row, 20), plain = u32(row, 24), local = u32(row, 42), crc = u32(row, 16);
                require((flags & ~(8 | 2048 | 6)) == 0 && (method == 0 || method == 8) && plain <= MAX_BYTES && compressed <= MAX_BYTES
                        && nameLength > 0 && nameLength < 1024 && cursor + 46 + nameLength + extraLength + commentLength <= start + directorySize,
                        "unified_zip_member_invalid");
                byte[] rawName = read(nameLength); String member = new String(rawName, StandardCharsets.US_ASCII);
                byte[] extra = read(extraLength); inspectExtra(extra);
                boolean directory = member.endsWith("/");
                require(name(directory ? member.substring(0, member.length() - 1) : member), "unified_zip_name_invalid");
                require(!members.containsKey(member), "unified_zip_duplicate_member");
                file.seek(local); byte[] header = read(30);
                require(u32(header, 0) == 0x04034b50L && u16(header, 6) == flags && u16(header, 8) == method
                        && u16(header, 26) == nameLength && java.util.Arrays.equals(read(nameLength), rawName), "unified_zip_local_differs");
                int localExtra = u16(header, 28); inspectExtra(read(localExtra));
                long offset = local + 30 + nameLength + localExtra;
                require(local >= 0 && local < start && offset >= local && offset + compressed <= start, "unified_zip_span_invalid");
                if ((flags & 8) == 0) require(u32(header, 14) == crc && u32(header, 18) == compressed && u32(header, 22) == plain,
                        "unified_zip_local_size_differs");
                members.put(member, new Span(member, method, flags, plain, compressed, crc, offset)); ranges.add(new long[]{local, offset + compressed});
                cursor += 46 + nameLength + extraLength + commentLength;
            }
            require(cursor == start + directorySize, "unified_zip_directory_trailing");
            Collections.sort(ranges, Comparator.comparingLong(value -> value[0]));
            long previous = 0; for (long[] range : ranges) { require(range[0] >= previous, "unified_zip_overlapping_members"); previous = range[1]; }
        }
        private static void inspectExtra(byte[] raw) throws IOException {
            int at = 0; while (at < raw.length) {
                // Android zipalign also uses zero padding which need not form a complete extra record.
                boolean zeros = true; for (int i = at; i < raw.length; ++i) if (raw[i] != 0) { zeros = false; break; }
                if (zeros) return;
                require(at + 4 <= raw.length, "unified_zip_extra_truncated"); int id = u16(raw, at), size = u16(raw, at + 2); at += 4;
                require(id != 1 && at + size <= raw.length, "unified_zip64_unsupported"); at += size;
            }
        }
        @Override public void close() throws IOException { file.close(); }
    }

    static final class Entry {
        final String name, member, compressedHash; final boolean object; final long bytes, compressed, crc; final int method;
        Entry(String n, String m, boolean o, long b, long c, long r, int t, String h) { name = n; member = m; object = o; bytes = b; compressed = c; crc = r; method = t; compressedHash = h; }
    }
    private static void le(ByteArrayOutputStream out, long value, int bytes) { for (int n = 0; n < bytes; ++n) out.write((int) (value >>> (n * 8)) & 255); }
    private static byte[] local(Entry row, long offset) {
        byte[] name = row.name.getBytes(StandardCharsets.US_ASCII);
        int pad = row.method == 0 ? (int) (-(offset + 30 + name.length + 4) & 3) : 0;
        int extra = row.method == 0 ? pad + 4 : 0; ByteArrayOutputStream out = new ByteArrayOutputStream();
        le(out, 0x04034b50L, 4); le(out, 20, 2); le(out, 0, 2); le(out, row.method, 2); le(out, 0, 2); le(out, 33, 2);
        le(out, row.crc, 4); le(out, row.compressed, 4); le(out, row.bytes, 4); le(out, name.length, 2); le(out, extra, 2); out.write(name, 0, name.length);
        if (extra > 0) { le(out, 0xd935, 2); le(out, pad, 2); for (int i = 0; i < pad; ++i) out.write(0); }
        return out.toByteArray();
    }
    private static byte[] central(Entry row, long offset) {
        byte[] name = row.name.getBytes(StandardCharsets.US_ASCII); ByteArrayOutputStream out = new ByteArrayOutputStream();
        le(out, 0x02014b50L, 4); le(out, 20, 2); le(out, 20, 2); le(out, 0, 2); le(out, row.method, 2); le(out, 0, 2); le(out, 33, 2);
        le(out, row.crc, 4); le(out, row.compressed, 4); le(out, row.bytes, 4); le(out, name.length, 2);
        le(out, 0, 2); le(out, 0, 2); le(out, 0, 2); le(out, 0, 2); le(out, 0, 4); le(out, offset, 4); out.write(name, 0, name.length);
        return out.toByteArray();
    }
    static void assemble(Source apk, List<Entry> entries, File output, long expectedBytes, String expectedHash) throws IOException {
        require(entries.size() > 0 && entries.size() <= MAX_ENTRIES, "unified_data_entry_bound");
        MessageDigest digest = digest(); List<byte[]> directory = new ArrayList<>(); long offset = 0; String previous = ""; byte[] buffer = new byte[128 * 1024];
        try (FileOutputStream file = new FileOutputStream(output); DigestOutputStream writer = new DigestOutputStream(file, digest)) {
            for (Entry entry : entries) {
                require(name(entry.name) && carrierMember(entry.name) && previous.compareTo(entry.name) < 0, "unified_data_names_invalid"); previous = entry.name;
                Span span = apk.members.get(entry.member);
                require(span != null && entry.bytes >= 0 && entry.bytes <= MAX_BYTES && entry.compressed >= 0 && entry.compressed <= MAX_BYTES
                        && entry.crc >= 0 && entry.crc <= 0xffffffffL && (entry.method == 0 || entry.method == 8)
                        && entry.compressedHash.matches("[0-9a-f]{64}"), "unified_data_entry_invalid");
                require(entry.object ? span.method == 0 && span.bytes == entry.compressed && span.compressed == entry.compressed
                        : span.method == entry.method && span.bytes == entry.bytes && span.compressed == entry.compressed && span.crc == entry.crc,
                        "unified_data_source_differs");
                byte[] header = local(entry, offset); writer.write(header); directory.add(central(entry, offset)); offset += header.length;
                apk.file.seek(span.offset); long remaining = span.compressed; MessageDigest encoded = digest();
                while (remaining > 0) { int count = apk.file.read(buffer, 0, (int) Math.min(buffer.length, remaining)); require(count > 0, "unified_data_span_truncated"); writer.write(buffer, 0, count); encoded.update(buffer, 0, count); remaining -= count; }
                require(hex(encoded.digest()).equals(entry.compressedHash), "unified_data_span_hash_differs"); offset += span.compressed;
                require(offset <= MAX_BYTES, "unified_data_carrier_bound");
            }
            long start = offset; for (byte[] row : directory) { writer.write(row); offset += row.length; }
            ByteArrayOutputStream end = new ByteArrayOutputStream(); le(end, 0x06054b50L, 4); le(end, 0, 2); le(end, 0, 2); le(end, entries.size(), 2); le(end, entries.size(), 2);
            le(end, offset - start, 4); le(end, start, 4); le(end, 0, 2); writer.write(end.toByteArray()); offset += 22; writer.flush(); file.getFD().sync();
            require(offset == expectedBytes && hex(digest.digest()).equals(expectedHash), "unified_data_carrier_hash_differs");
        }
        try (Source verified = new Source(output)) {
            require(verified.members.size() == entries.size(), "unified_data_carrier_inventory_differs");
            for (Entry row : entries) { Span span = verified.members.get(row.name); require(span != null && span.bytes == row.bytes && span.compressed == row.compressed && span.method == row.method && span.crc == row.crc, "unified_data_carrier_inventory_differs"); }
        }
    }
}
