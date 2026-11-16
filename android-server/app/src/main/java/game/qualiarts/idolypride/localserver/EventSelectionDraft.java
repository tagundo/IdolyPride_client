package game.qualiarts.idolypride.localserver;

import java.util.Collections;
import java.util.Map;
import java.util.TreeMap;

/** UI-thread intent queue. An old save acknowledgement cannot erase newer edits. */
final class EventSelectionDraft {
    static final class Window {
        final long start, end;
        Window(long start, long end) { this.start = start; this.end = end; }
        @Override public boolean equals(Object other) {
            return other instanceof Window && start == ((Window) other).start && end == ((Window) other).end;
        }
        @Override public int hashCode() { return Long.hashCode(start) * 31 + Long.hashCode(end); }
    }
    static final class Save {
        final long revision;
        final Map<String, Window> rows;
        private final Map<String, Long> versions;
        Save(long revision, Map<String, Window> rows, Map<String, Long> versions) {
            this.revision = revision;
            this.rows = Collections.unmodifiableMap(new TreeMap<>(rows));
            this.versions = new TreeMap<>(versions);
        }
    }
    private final boolean media;
    private final TreeMap<String, Window> saved = new TreeMap<>(), edits = new TreeMap<>();
    private final TreeMap<String, Long> versions = new TreeMap<>();
    private long revision, generation;
    private boolean loaded;
    EventSelectionDraft(boolean media) { this.media = media; }
    boolean loaded() { return loaded; }
    long revision() { return revision; }
    boolean dirty() { return !edits.isEmpty(); }
    private void check(String identifier, Window window) {
        if (identifier == null || !identifier.matches("[A-Za-z0-9_.-]{1,128}"))
            throw new IllegalArgumentException("event_settings_invalid");
        if (window != null && !(media ? window.start == 0 && window.end == 0 : EventWindow.valid(window.start, window.end)))
            throw new IllegalArgumentException("event_settings_invalid");
    }
    void observe(long value, Map<String, Window> rows) {
        if (value < 0 || value > EventWindow.MAX_SAFE || (loaded && value < revision))
            throw new IllegalArgumentException("event_settings_revision_conflict");
        for (Map.Entry<String, Window> row : rows.entrySet()) {
            check(row.getKey(), row.getValue());
            if (row.getValue() == null) throw new IllegalArgumentException("event_settings_invalid");
        }
        saved.clear(); saved.putAll(rows); revision = value; loaded = true;
    }
    void edit(String identifier, Window window) {
        check(identifier, window);
        edits.put(identifier, window); versions.put(identifier, ++generation);
    }
    Map<String, Window> rows() {
        TreeMap<String, Window> result = new TreeMap<>(saved);
        for (Map.Entry<String, Window> edit : edits.entrySet()) {
            if (edit.getValue() == null) result.remove(edit.getKey());
            else result.put(edit.getKey(), edit.getValue());
        }
        return Collections.unmodifiableMap(result);
    }
    Map<String, Window> pending() { return Collections.unmodifiableMap(new TreeMap<>(edits)); }
    Save prepare() { return loaded && dirty() ? new Save(revision, rows(), versions) : null; }
    void acknowledge(long value, Map<String, Window> rows, Save sent) {
        if (sent == null || value < sent.revision || !sent.rows.equals(rows))
            throw new IllegalArgumentException("event_settings_response_invalid");
        observe(value, rows);
        for (Map.Entry<String, Long> row : sent.versions.entrySet()) {
            if (row.getValue().equals(versions.get(row.getKey()))) {
                edits.remove(row.getKey()); versions.remove(row.getKey());
            }
        }
    }
}
