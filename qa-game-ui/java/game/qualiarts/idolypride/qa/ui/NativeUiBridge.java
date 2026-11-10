package game.qualiarts.idolypride.qa.ui;

/** Fixed JNI entry points; callers must already be on UnityMain. */
final class NativeUiBridge {
    private NativeUiBridge() {}

    static void load() { System.loadLibrary("idoly_qa_ui_bridge"); }
    static native String nativeSnapshot();
    static native String nativeClick(int instanceId, long generation);
}
