package game.qualiarts.idolypride.mp4qa;

import java.io.File;
import java.io.IOException;
import java.util.concurrent.atomic.AtomicBoolean;

/** A configuration relaunch may reattach the UI but cannot restart this proof. */
final class ProbeRunOwnership {
    private static final AtomicBoolean STARTED = new AtomicBoolean();
    private ProbeRunOwnership() {}

    static boolean claimProcessRun() { return STARTED.compareAndSet(false, true); }

    static void createFreshDirectory(File directory) throws IOException {
        if (!directory.mkdir())
            throw new IOException("QA case path already exists; clear app data before rerun");
    }
}
