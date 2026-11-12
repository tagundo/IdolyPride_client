package game.qualiarts.idolypride.localserver;

import android.util.AtomicFile;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

/** Small independent language/menu files; no account database or ownership edits. */
final class LibrarySettings {
    static final int MAX_BYTES = 8192;
    static final String[] LANGUAGES = {"ja", "ko", "en"};
    static final String[] MV_SORTS = {"recent", "old", "title", "id"};
    static final String[] OUTFIT_SORTS = {"original", "recent", "old", "title", "id"};
    final String language, mvSort, outfitSort;
    final long revision;
    final boolean hideVideoMv;

    LibrarySettings(String language, long revision, boolean hide, String mv, String outfit) {
        if (!choice(language, LANGUAGES) || revision < 0 || !choice(mv, MV_SORTS) || !choice(outfit, OUTFIT_SORTS))
            throw new IllegalArgumentException("Invalid library settings");
        this.language = language; this.revision = revision; hideVideoMv = hide; mvSort = mv; outfitSort = outfit;
    }
    static LibrarySettings defaults() { return new LibrarySettings("ja", 0, false, "recent", "original"); }
    private static boolean choice(String value, String[] choices) {
        for (String candidate : choices) if (candidate.equals(value)) return true;
        return false;
    }
    LibrarySettings changedMedia(boolean hide, String mv, String outfit, long now) {
        if (revision == Long.MAX_VALUE) throw new IllegalStateException("Menu revision exhausted");
        return new LibrarySettings(language, Math.max(revision + 1, Math.max(0, now)), hide, mv, outfit);
    }
    LibrarySettings changedLanguage(String selected) { return new LibrarySettings(selected, revision, hideVideoMv, mvSort, outfitSort); }
    String languageJson() { return "{\"schema\":1,\"language\":\"" + language + "\"}"; }
    String mediaJson() { return "{\"schema\":1,\"revision\":" + revision + ",\"hide_video_mv\":" + hideVideoMv
            + ",\"mv_sort\":\"" + mvSort + "\",\"outfit_sort\":\"" + outfitSort + "\"}"; }

    static String parseLanguage(String raw) {
        Map<String, Object> row = new Reader(raw).object();
        if (row.size() != 2 || !Long.valueOf(1).equals(row.get("schema")) || !(row.get("language") instanceof String)
                || !choice((String) row.get("language"), LANGUAGES)) throw new IllegalArgumentException("Language fields");
        return (String) row.get("language");
    }
    static LibrarySettings parseMedia(String raw) {
        Map<String, Object> row = new Reader(raw).object();
        if (row.size() != 5 || !Long.valueOf(1).equals(row.get("schema")) || !(row.get("revision") instanceof Long)
                || !(row.get("hide_video_mv") instanceof Boolean) || !(row.get("mv_sort") instanceof String)
                || !(row.get("outfit_sort") instanceof String)) throw new IllegalArgumentException("Menu fields");
        return new LibrarySettings("ja", (Long) row.get("revision"), (Boolean) row.get("hide_video_mv"),
                (String) row.get("mv_sort"), (String) row.get("outfit_sort"));
    }
    static final class Loaded {
        final LibrarySettings settings;
        final boolean invalidLanguage, invalidMedia;
        Loaded(LibrarySettings value, boolean language, boolean media) { settings = value; invalidLanguage = language; invalidMedia = media; }
    }
    private static File file(File files, String name) { return new File(new File(files, "data"), name); }
    private static String read(File path) throws IOException {
        AtomicFile source = new AtomicFile(path);
        if (!path.exists() && !new File(path + ".bak").exists()) return null;
        try (FileInputStream input = source.openRead(); ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[1024]; int count;
            while ((count = input.read(buffer)) >= 0) {
                if (bytes.size() + count > MAX_BYTES) throw new IOException("Settings size");
                bytes.write(buffer, 0, count);
            }
            return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes.toByteArray())).toString();
        }
    }
    static Loaded load(File files) {
        LibrarySettings value = defaults(); boolean language = false, media = false;
        try { String raw = read(file(files, "client-media.json")); if (raw != null) value = parseMedia(raw); }
        catch (IOException | IllegalArgumentException bad) { media = true; }
        try { String raw = read(file(files, "client-language.json")); if (raw != null) value = value.changedLanguage(parseLanguage(raw)); }
        catch (IOException | IllegalArgumentException bad) { language = true; }
        return new Loaded(value, language, media);
    }
    private static void write(File path, String json) throws IOException {
        File directory = path.getParentFile();
        if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("Settings directory");
        AtomicFile target = new AtomicFile(path); FileOutputStream output = null;
        try {
            output = target.startWrite(); output.write(json.getBytes(StandardCharsets.UTF_8)); target.finishWrite(output);
        } catch (IOException failed) { if (output != null) target.failWrite(output); throw failed; }
    }
    void saveLanguage(File files) throws IOException { write(file(files, "client-language.json"), languageJson()); }
    void saveMedia(File files) throws IOException { write(file(files, "client-media.json"), mediaJson()); }

    private static final class Reader {
        final String raw; int at;
        Reader(String value) {
            if (value == null || value.length() > MAX_BYTES || value.getBytes(StandardCharsets.UTF_8).length > MAX_BYTES)
                throw new IllegalArgumentException("Settings size");
            raw = value;
        }
        void space() { while (at < raw.length() && " \t\r\n".indexOf(raw.charAt(at)) >= 0) at++; }
        boolean take(char c) { space(); if (at < raw.length() && raw.charAt(at) == c) { at++; return true; } return false; }
        void expect(char c) { if (!take(c)) throw new IllegalArgumentException("Settings token"); }
        Map<String, Object> object() {
            Map<String, Object> result = new HashMap<>(); expect('{');
            if (!take('}')) {
                do {
                    String key = string(); expect(':');
                    if (result.containsKey(key) || result.size() >= 5) throw new IllegalArgumentException("Settings duplicate");
                    result.put(key, value());
                    if (take('}')) { space(); if (at != raw.length()) throw new IllegalArgumentException("Settings trailing"); return result; }
                } while (take(','));
                throw new IllegalArgumentException("Settings object");
            }
            space(); if (at != raw.length()) throw new IllegalArgumentException("Settings trailing"); return result;
        }
        Object value() {
            space();
            if (at < raw.length() && raw.charAt(at) == '"') return string();
            if (raw.startsWith("true", at)) { at += 4; return Boolean.TRUE; }
            if (raw.startsWith("false", at)) { at += 5; return Boolean.FALSE; }
            int start = at;
            if (at < raw.length() && raw.charAt(at) == '-') at++;
            int digits = at;
            while (at < raw.length() && raw.charAt(at) >= '0' && raw.charAt(at) <= '9') at++;
            if (at == digits || at - digits > 1 && raw.charAt(digits) == '0') throw new IllegalArgumentException("Settings integer");
            try { return Long.valueOf(raw.substring(start, at)); }
            catch (NumberFormatException bad) { throw new IllegalArgumentException("Settings integer"); }
        }
        String string() {
            expect('"'); StringBuilder text = new StringBuilder();
            while (at < raw.length()) {
                char c = raw.charAt(at++);
                if (c == '"') return text.toString();
                if (c < 32 || text.length() >= 64) throw new IllegalArgumentException("Settings string");
                if (c == '\\') {
                    if (at == raw.length()) throw new IllegalArgumentException("Settings escape");
                    c = raw.charAt(at++);
                    if (c == 'u') {
                        if (at + 4 > raw.length()) throw new IllegalArgumentException("Settings unicode");
                        int code = 0;
                        for (int i = 0; i < 4; i++) {
                            char h = raw.charAt(at++);
                            int n = h >= '0' && h <= '9' ? h - '0' : h >= 'a' && h <= 'f' ? h - 'a' + 10 : h >= 'A' && h <= 'F' ? h - 'A' + 10 : -1;
                            if (n < 0) throw new IllegalArgumentException("Settings unicode");
                            code = code * 16 + n;
                        }
                        c = (char) code;
                    } else if (c != '"' && c != '\\' && c != '/') throw new IllegalArgumentException("Settings escape");
                }
                text.append(c);
            }
            throw new IllegalArgumentException("Settings string");
        }
    }
}
