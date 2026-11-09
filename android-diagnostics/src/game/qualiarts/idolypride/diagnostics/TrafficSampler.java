package game.qualiarts.idolypride.diagnostics;

/** Cumulative own-UID byte deltas, with no host, URL or packet information. */
public final class TrafficSampler {
    public static final long INTERVAL_MS = 5000;

    public interface Counters {
        long elapsedRealtime();
        long rxBytes();
        long txBytes();
    }

    public static final class Sample {
        public final boolean unavailable;
        public final long rxBytes;
        public final long txBytes;
        public final long elapsedMs;

        private Sample(boolean unavailable, long rxBytes, long txBytes, long elapsedMs) {
            this.unavailable = unavailable;
            this.rxBytes = rxBytes;
            this.txBytes = txBytes;
            this.elapsedMs = elapsedMs;
        }
    }

    private final Counters counters;
    private final long startedAt;
    private final long initialRx;
    private final long initialTx;
    private long lastRx;
    private long lastTx;
    private long nextElapsedMs = INTERVAL_MS;
    private boolean unavailable;
    private boolean unavailableReported;

    public TrafficSampler(Counters counters) {
        this.counters = counters;
        startedAt = counters.elapsedRealtime();
        initialRx = lastRx = counters.rxBytes();
        initialTx = lastTx = counters.txBytes();
        unavailable = startedAt < 0 || initialRx < 0 || initialTx < 0;
    }

    /** Null means not yet due; an unsupported/reset counter reports once. */
    public Sample poll() {
        if (unavailableReported) return null;
        if (unavailable) return reportUnavailable();
        long now = counters.elapsedRealtime();
        if (now < startedAt) return reportUnavailable();
        long elapsed = now - startedAt;
        if (elapsed < nextElapsedMs) return null;
        long rx = counters.rxBytes();
        long tx = counters.txBytes();
        if (rx < lastRx || tx < lastTx || rx < 0 || tx < 0) return reportUnavailable();
        lastRx = rx;
        lastTx = tx;
        nextElapsedMs = elapsed > Long.MAX_VALUE - INTERVAL_MS ? Long.MAX_VALUE : elapsed + INTERVAL_MS;
        return new Sample(false, rx - initialRx, tx - initialTx, elapsed);
    }

    private Sample reportUnavailable() {
        unavailable = true;
        unavailableReported = true;
        return new Sample(true, 0, 0, 0);
    }
}
