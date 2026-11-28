package game.qualiarts.idolypride.localserver;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.Map;

/** App-private completed-output bookmarks. Forgetting metadata never deletes a video. */
final class Mp4CompletedExports {
    interface Store { Set<String> read(); boolean write(Set<String> values); }
    static final class Entry {
        final File root;
        final String outputId, jobId;
        Entry(File root, String outputId, String jobId) {
            this.root = root; this.outputId = outputId; this.jobId = jobId;
        }
        String key() { return root.getPath() + "\n" + outputId; }
    }
    private final File files;
    private final Store store;
    private final LinkedHashMap<String, Entry> known = new LinkedHashMap<>();
    private final LinkedHashSet<File> oneShotDirectories = new LinkedHashSet<>();
    private boolean dirty;

    Mp4CompletedExports(File filesDirectory, Store store) throws IOException {
        files = filesDirectory.getCanonicalFile();
        if (!files.isDirectory()) throw new IOException("Private files directory unavailable");
        this.store = store;
        Set<String> saved = store.read();
        if (saved != null) for (String encoded : saved) {
            try {
                File directory = decodeDirectory(encoded);
                if (directory != null) { oneShotDirectories.add(directory); continue; }
                Entry entry = decode(encoded);
                // The bookmark retains only a previously recorded app-private
                // location. A missing file is hidden, never recreated or adopted.
                known.put(entry.key(), entry);
            } catch (IOException | IllegalArgumentException invalid) { /* Ignore an invalid bookmark. */ }
        }
    }

    /** Register only the trusted one-shot export directory supplied by native configuration. */
    synchronized boolean rememberDirectory(File root) throws IOException {
        File checked = checked(root, "directory", null).root;
        if (!oneShotDirectories.add(checked)) return !dirty || persist();
        dirty = true; return persist();
    }
    /** One-level migration of this app's pre-bookmark native audio-session exports. */
    synchronized void recoverLegacyOneShots() {
        File[] children = files.listFiles(); if (children == null) return;
        try {
            int owner = ((Number) Files.getAttribute(files.toPath(), "unix:uid", LinkOption.NOFOLLOW_LINKS)).intValue();
            for (File broker : children) {
                try {
                    if (!broker.getName().matches("\\.idoly-mp4-audio-[a-f0-9]{32}") || !privateMember(broker, owner, true)) continue;
                    File root = new File(broker, "exports");
                    if (!privateMember(root, owner, true) || !root.getCanonicalFile().equals(root)) continue;
                    File[] outputs = root.listFiles(); if (outputs == null) continue;
                    for (File source : outputs) try {
                        if (!source.getName().matches("[a-f0-9]{32}\\.mp4") || !privateMember(source, owner, false) || source.length() < 1) continue;
                        Entry entry = checked(root, source.getName().substring(0, 32), null); requireFile(entry);
                        if (!known.containsKey(entry.key())) { known.put(entry.key(), entry); dirty = true; }
                    } catch (IOException | RuntimeException unavailable) { /* A rejected candidate never blocks another output. */ }
                } catch (IOException | RuntimeException unavailable) { /* A stale or unsafe session never blocks another session. */ }
            }
            if (dirty) persist();
        } catch (IOException | RuntimeException unavailable) { /* Unsupported ownership observations never authorize migration. */ }
    }
    private static boolean privateMember(File file, int owner, boolean directory) throws IOException {
        if (!file.getCanonicalFile().equals(file)) return false;
        Map<String, Object> attributes = Files.readAttributes(file.toPath(), "unix:uid,mode,nlink", LinkOption.NOFOLLOW_LINKS);
        int mode = ((Number) attributes.get("mode")).intValue();
        return ((Number) attributes.get("uid")).intValue() == owner
                && (mode & 0170000) == (directory ? 0040000 : 0100000)
                && (mode & 07777) == (directory ? 0700 : 0600)
                && (directory || ((Number) attributes.get("nlink")).longValue() == 1);
    }

    synchronized boolean remember(File root, String outputId, String jobId) throws IOException {
        Entry entry = checked(root, outputId, jobId);
        requireFile(entry);
        Entry previous = known.get(entry.key());
        if (previous != null && equal(previous.jobId, entry.jobId)) return !dirty || persist();
        known.remove(entry.key()); known.put(entry.key(), entry); dirty = true;
        return persist();
    }

    synchronized ArrayList<Entry> entries() {
        ArrayList<Entry> result = new ArrayList<>();
        for (Entry entry : known.values()) try {
            requireFile(entry); result.add(0, entry);
        } catch (IOException unavailable) { /* Keep metadata for diagnosis; do not touch the source. */ }
        // Register the directory before capture starts, so a process death
        // between atomic .mp4 publication and the next UI poll loses no output.
        // Queue roots are never scanned: their journal owns output admission.
        for (File root : oneShotDirectories) {
            File[] files = root.listFiles(); if (files == null) continue;
            for (File file : files) {
                String name = file.getName(); if (!name.endsWith(".mp4")) continue;
                try {
                    Entry entry = checked(root, name.substring(0, name.length() - 4), null); requireFile(entry);
                    boolean duplicate = false;
                    for (Entry previous : result) if (previous.key().equals(entry.key())) { duplicate = true; break; }
                    if (!duplicate) result.add(entry);
                } catch (IOException unavailable) { /* Partial, symlinked, empty or unrelated filenames are excluded. */ }
            }
        }
        result.sort((a, b) -> {
            int time = Long.compare(new File(b.root, b.outputId + ".mp4").lastModified(), new File(a.root, a.outputId + ".mp4").lastModified());
            return time != 0 ? time : a.key().compareTo(b.key());
        });
        return result;
    }

    synchronized boolean forget(Entry entry) {
        if (entry == null || known.remove(entry.key()) == null) return !dirty || persist();
        dirty = true;
        return persist();
    }

    private boolean persist() {
        LinkedHashSet<String> result = new LinkedHashSet<>();
        try {
            for (Entry entry : known.values()) result.add(encode(entry));
            for (File root : oneShotDirectories) {
                ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                try (DataOutputStream output = new DataOutputStream(bytes)) { output.writeInt(2); output.writeUTF(root.getPath()); }
                result.add(Base64.getUrlEncoder().withoutPadding().encodeToString(bytes.toByteArray()));
            }
            if (!store.write(result)) return false;
            dirty = false; return true;
        } catch (IOException invalid) { return false; }
    }

    private Entry checked(File root, String id, String job) throws IOException {
        if (root == null || !validId(id) || job != null && !validId(job)) throw new IOException("Invalid completed identity");
        File canonical = root.getCanonicalFile();
        if (!root.isAbsolute() || !canonical.equals(root) || !root.isDirectory()
                || !root.getPath().startsWith(files.getPath() + File.separator)
                || Files.isSymbolicLink(root.toPath())) throw new IOException("Invalid completed directory");
        return new Entry(root, id, job);
    }

    private void requireFile(Entry entry) throws IOException {
        checked(entry.root, entry.outputId, entry.jobId);
        File source = new File(entry.root, entry.outputId + ".mp4");
        if (!source.getCanonicalFile().equals(source)
                || !Files.isRegularFile(source.toPath(), LinkOption.NOFOLLOW_LINKS) || source.length() < 1)
            throw new IOException("Completed video unavailable");
    }

    private String encode(Entry entry) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (DataOutputStream output = new DataOutputStream(bytes)) {
            output.writeInt(1); output.writeUTF(entry.root.getPath()); output.writeUTF(entry.outputId);
            output.writeUTF(entry.jobId == null ? "" : entry.jobId);
        }
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes.toByteArray());
    }

    private Entry decode(String encoded) throws IOException {
        if (encoded == null || encoded.length() > 16384) throw new IOException("Invalid completed bookmark");
        byte[] bytes = Base64.getUrlDecoder().decode(encoded);
        try (DataInputStream input = new DataInputStream(new ByteArrayInputStream(bytes))) {
            if (input.readInt() != 1) throw new IOException("Unsupported completed bookmark");
            File root = new File(input.readUTF()); String id = input.readUTF(), job = input.readUTF();
            if (input.read() != -1) throw new IOException("Trailing completed bookmark bytes");
            return checked(root, id, job.isEmpty() ? null : job);
        }
    }
    private File decodeDirectory(String encoded) throws IOException {
        if (encoded == null || encoded.length() > 16384) throw new IOException("Invalid completed bookmark");
        try (DataInputStream input = new DataInputStream(new ByteArrayInputStream(Base64.getUrlDecoder().decode(encoded)))) {
            if (input.readInt() != 2) return null;
            File root = new File(input.readUTF());
            if (input.read() != -1) throw new IOException("Trailing completed directory bytes");
            return checked(root, "directory", null).root;
        }
    }
    private static boolean validId(String value) { return value != null && value.matches("[A-Za-z0-9_-]{1,80}"); }
    private static boolean equal(String a, String b) { return a == null ? b == null : a.equals(b); }
}
