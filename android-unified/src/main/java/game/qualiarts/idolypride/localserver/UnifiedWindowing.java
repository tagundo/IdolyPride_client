package game.qualiarts.idolypride.localserver;

/** Supplies the actual OS window mode without changing the saved playback preference. */
final class UnifiedWindowing {
    private static boolean attempted, loaded;

    private UnifiedWindowing() {}

    static synchronized void update(boolean multiWindow) {
        if (!attempted) {
            attempted = true;
            try {
                System.loadLibrary("idoly_presentation");
                loaded = true;
            } catch (LinkageError | SecurityException unavailable) {
                // The optional native addon may be absent in a packaging test.
                loaded = false;
            }
        }
        if (!loaded) return;
        try { setMultiWindow(multiWindow); }
        catch (LinkageError | SecurityException unavailable) { loaded = false; }
    }

    private static native void setMultiWindow(boolean multiWindow);
}
