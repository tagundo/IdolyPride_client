package game.qualiarts.idolypride.localserver;

/** Explicit local event windows; no game clock, reward or progress mutation. */
final class EventWindow {
    static final long MAX_SAFE = 9007199254740991L;
    static final long MAX_DURATION = 366L * 24 * 60 * 60 * 1000;
    static final long DEFAULT_DURATION = 30L * 24 * 60 * 60 * 1000;
    private EventWindow() {}

    static boolean valid(long start, long end) {
        return start >= 0 && start < end && end <= MAX_SAFE && end - start <= MAX_DURATION;
    }

    static long[] preset(long now) {
        if (now < 0 || now > MAX_SAFE - DEFAULT_DURATION) throw new IllegalArgumentException("event_settings_invalid");
        return new long[]{now, now + DEFAULT_DURATION};
    }

    static long[] shiftStart(long start, long previousStart, long previousEnd) {
        if (!valid(previousStart, previousEnd) || start < 0 || start > MAX_SAFE - (previousEnd - previousStart))
            throw new IllegalArgumentException("event_settings_invalid");
        return new long[]{start, start + previousEnd - previousStart};
    }
}
