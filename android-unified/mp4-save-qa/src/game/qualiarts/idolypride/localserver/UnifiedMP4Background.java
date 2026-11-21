package game.qualiarts.idolypride.localserver;

/** No game, EGL transport, background service or encoder is loaded by this UI fixture. */
final class UnifiedMP4Background {
    interface Host { org.json.JSONObject status(); void park(); void resume(); boolean userPaused(); void changed(); }
    static org.json.JSONObject snapshot() { return new org.json.JSONObject(); }
    static void prepare(android.app.Activity activity, Host host) { }
    static void stopCurrent() { }
    static void backgrounded(android.app.Activity activity) { }
    static void foregrounding(android.app.Activity activity) { }
    static void focusLost(android.app.Activity activity) { }
    static boolean ownsSurface(android.app.Activity activity) { return false; }
    static void sample(org.json.JSONObject value) { }
    static boolean expectsService() { return false; }
}
