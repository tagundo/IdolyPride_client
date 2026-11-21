package game.qualiarts.idolypride.localserver;

import java.io.IOException;

/** A slow worker may prepare files without blocking the game/activity state. */
final class UnifiedGamePreparation {
    final Object workerLock = new Object();
    private final Object stateLock = new Object();
    private volatile Snapshot ready;
    private volatile Snapshot frozen;

    static final class Snapshot {
        final String language, path, identity; final long bytes;
        Snapshot(String language, String path, String identity, long bytes) {
            this.language = language; this.path = path; this.identity = identity; this.bytes = bytes;
        }
        boolean same(Snapshot other) {
            return other != null && language.equals(other.language) && path.equals(other.path)
                    && identity.equals(other.identity) && bytes == other.bytes;
        }
    }
    interface Publication { void publish() throws Exception; }
    Snapshot ready() { return ready; }
    Snapshot frozen() { return frozen; }
    String frozenLanguage() { Snapshot value = frozen; return value == null ? null : value.language; }
    boolean isPrepared(String language) { Snapshot value = ready; return value != null && value.language.equals(language); }

    String freeze(String language) throws IOException {
        synchronized (stateLock) {
            Snapshot value = ready;
            if (value == null || !value.language.equals(language)) throw new IOException("unified_data_not_prepared");
            if (frozen != null && !frozen.same(value)) throw new IOException("unified_data_cold_restart_required");
            frozen = value;
            return value.path;
        }
    }

    /** The callback may only atomically rename a fully verified file, never hash or copy it. */
    boolean publish(Snapshot value, boolean replacesFile, Publication publication) throws Exception {
        synchronized (stateLock) {
            if (frozen != null && (replacesFile || !frozen.same(value)))
                throw new IOException("unified_data_cold_restart_required");
            publication.publish();
            ready = value;
            return frozen == null;
        }
    }
}
