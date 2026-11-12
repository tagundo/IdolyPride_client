package game.qualiarts.idolypride.presentation;

/** JNI snapshots only; the native bridge applies Unity changes on Unity's thread. */
public final class NativePresentation {
    private NativePresentation() {}
    public static native void start();
    public static native boolean configure(int schema, long revision, boolean custom, int quality,
            int fps, float scale, int maxBufferPixel, int aaMode, int shadow,
            boolean expandPhotography);
    public static native String status();
    public static native boolean configurePlayback(int schema, long revision, boolean waitForOrientation);
    public static native String playbackStatus();
    public static native String renderProbeStatus();
    public static native boolean configureMedia(int schema, long revision, boolean useMasterCostumeOrder);
    public static native String wardrobeStatus();
}
