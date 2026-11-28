package game.qualiarts.idolypride.localserver;

/** Button policy shared by the native queue panel and executable UI tests. */
final class Mp4QueueUiState {
    static final int CAPACITY = 8;
    static final int CANCEL = 1, REMOVE = 2, RETRY = 4, UP = 8, DOWN = 16, SAVE = 32;

    static boolean jobId(String value) {
        if (value == null || value.length() != 32) return false;
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            if (!((character >= '0' && character <= '9') || (character >= 'a' && character <= 'f'))) return false;
        }
        return true;
    }

    static boolean state(String value) {
        return "pending".equals(value) || "running".equals(value) || "paused".equals(value)
                || "completed".equals(value) || "failed".equals(value)
                || "cancelled".equals(value) || "interrupted".equals(value);
    }

    static int actions(String value, int position, int count, boolean commandPending) {
        if (commandPending || !state(value) || count < 1 || count > CAPACITY || position < 0 || position >= count) return 0;
        if ("running".equals(value) || "paused".equals(value)) return CANCEL;
        if ("pending".equals(value)) return CANCEL | REMOVE | (position > 0 ? UP : 0) | (position + 1 < count ? DOWN : 0);
        if ("completed".equals(value)) return REMOVE | SAVE;
        return REMOVE | RETRY;
    }

    static final class Controls {
        final boolean enqueue, run, pause, resume, immediate;

        Controls(boolean available, boolean commandPending, boolean running, boolean paused,
                 boolean exportBusy, boolean mvReady, boolean canRunWorld, int pendingJobs, int totalJobs) {
            this(available, commandPending, running, paused, exportBusy, mvReady, mvReady, canRunWorld, pendingJobs, totalJobs);
        }
        Controls(boolean available, boolean commandPending, boolean running, boolean paused,
                 boolean exportBusy, boolean canAddSelection, boolean exportReady, boolean canRunWorld, int pendingJobs, int totalJobs) {
            boolean valid = available && !commandPending && totalJobs >= 0 && totalJobs <= CAPACITY
                    && pendingJobs >= 0 && pendingJobs <= totalJobs;
            enqueue = valid && totalJobs < CAPACITY && canAddSelection && !exportBusy && !running;
            run = valid && canRunWorld && pendingJobs > 0 && !running && !paused && !exportBusy;
            pause = valid && running && !paused;
            resume = valid && canRunWorld && paused;
            // The existing single export remains usable if only the journal
            // is unavailable. exportReady may retain the current Activity's verified
            // foreground selection; capture is rechecked after Unity resumes.
            immediate = !commandPending && exportReady && !running && !paused && !exportBusy;
        }
    }

    private Mp4QueueUiState() { }
}
