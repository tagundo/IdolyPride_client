package game.qualiarts.idolypride.localserver;

/** Startup request policy and independently observed rendering-mode freshness. */
final class RenderingExperiment {
    static final String PREFERENCE = "experimental_multithreaded_rendering";
    static final boolean DEFAULT_ENABLED = false;
    static final String UNITY_ARGUMENTS = "unity";
    static final String MT_ARGUMENT = "-force-gfx-mt";
    static final int WAIT_SERVER = 0, WAIT_CLIENT = 1, STALE = 2, OBSERVED = 3,
            UNSUPPORTED = 4, INIT_FAILED = 5;
    private static final double MAX_AGE_SECONDS = 10;

    static boolean knownClient(String name) {
        return "game.qualiarts.idolypride.local".equals(name)
                || "game.qualiarts.idolypride.local.resources".equals(name)
                || "game.qualiarts.idolypride.local.diagnostics".equals(name);
    }

    /** Preserve all existing arguments; refuse contradictory modes or malformed quoting. */
    static String launchArguments(String existing, boolean requested) {
        if (!requested) return existing;
        if (existing == null) return MT_ARGUMENT;
        if (existing.length() > 1024) throw new IllegalArgumentException("Unity argument size");
        StringBuilder token = new StringBuilder();
        char quote = 0;
        boolean escaped = false, found = false;
        for (int index = 0; index < existing.length(); index++) {
            char value = existing.charAt(index);
            if (value < 32 || value == 127) throw new IllegalArgumentException("Unity argument control");
            if (escaped) {
                token.append(value); escaped = false;
            } else if (value == '\\') {
                escaped = true;
            } else if (quote != 0) {
                if (value == quote) quote = 0;
                else token.append(value);
            } else if (value == '\'' || value == '"') {
                quote = value;
            } else if (value == ' ') {
                String argument = token.toString();
                if (argument.equals(MT_ARGUMENT)) found = true;
                else if (argument.startsWith("-force-gfx-"))
                    throw new IllegalArgumentException("Conflicting Unity rendering mode");
                token.setLength(0);
            } else token.append(value);
        }
        if (quote != 0 || escaped) throw new IllegalArgumentException("Unity argument quoting");
        String last = token.toString();
        if (last.equals(MT_ARGUMENT)) found = true;
        else if (last.startsWith("-force-gfx-"))
            throw new IllegalArgumentException("Conflicting Unity rendering mode");
        return found ? existing : (existing.trim().isEmpty() ? "" : existing + " ") + MT_ARGUMENT;
    }

    static long snapshotAgeMs(long now, long received) {
        return received > 0 && now >= received ? now - received : -1;
    }

    static boolean ageFresh(Long nativeAgeMs, Double receiptAgeSeconds, long snapshotAgeMs) {
        return nativeAgeMs != null && nativeAgeMs >= 0 && receiptAgeSeconds != null
                && Double.isFinite(receiptAgeSeconds) && receiptAgeSeconds >= 0 && snapshotAgeMs >= 0
                && nativeAgeMs / 1000.0 + receiptAgeSeconds + snapshotAgeMs / 1000.0 < MAX_AGE_SECONDS;
    }

    static int feedback(boolean active, boolean running, long now, long received, int schema,
            String state, Boolean stale, Double receiptAgeSeconds, Long nativeAgeMs,
            int mode, long observations, boolean validObservedFields) {
        long snapshotAge = snapshotAgeMs(now, received);
        if (!active || !running || snapshotAge < 0 || snapshotAge >= 10_000) return WAIT_SERVER;
        if (schema != 1 || stale == null || receiptAgeSeconds == null
                || !Double.isFinite(receiptAgeSeconds) || receiptAgeSeconds < 0) return WAIT_CLIENT;
        if (!ageFresh(0L, receiptAgeSeconds, snapshotAge)) return STALE;
        if ("unsupported".equals(state)) return UNSUPPORTED;
        if ("init_failed".equals(state)) return INIT_FAILED;
        if (!"observed".equals(state)) return WAIT_CLIENT;
        if (stale || !ageFresh(nativeAgeMs, receiptAgeSeconds, snapshotAge)) return STALE;
        return mode >= 0 && mode <= 5 && observations > 0 && validObservedFields ? OBSERVED : WAIT_CLIENT;
    }

    static boolean timingFresh(Long timingAgeMs, Double receiptAgeSeconds, long now, long received) {
        return ageFresh(timingAgeMs, receiptAgeSeconds, snapshotAgeMs(now, received));
    }

    private RenderingExperiment() { }
}
