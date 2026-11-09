package game.qualiarts.idolypride.diagnostics;

import java.util.concurrent.atomic.AtomicBoolean;

/** Optional, observation-only native checkpoints for the pinned game build. */
public final class NativePhaseProbe {
    private static final AtomicBoolean STARTED = new AtomicBoolean();

    private NativePhaseProbe() { }

    public static void start() {
        if (!STARTED.compareAndSet(false, true)) return;
        try {
            System.loadLibrary("idoly_phase_probe");
            nativeStart();
        } catch (Throwable ignored) {
            // The Java-only probe APK intentionally has no native libraries.
            // Optional diagnostics must never prevent normal game startup.
            android.util.Log.i("Unity", "IDOLY_PHASE:probe_unavailable");
        }
    }

    private static native void nativeStart();
}
