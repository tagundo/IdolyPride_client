package game.qualiarts.idolypride.localserver;

/** Pure pointer policy; Android event dispatch and menu navigation stay in the activity. */
final class UnifiedMenuGesture {
    static final long HOLD_MILLIS = 2000;
    private boolean pending, claimed;
    private float downX, downY, slop;
    private long started;

    void down(int pointers, float x, float y, float width, float height,
              float density, float movementSlop, long now) {
        cancel();
        if (pointers != 1 || !Float.isFinite(x) || !Float.isFinite(y)
                || !Float.isFinite(width) || !Float.isFinite(height) || !Float.isFinite(density)
                || !Float.isFinite(movementSlop) || width <= 0 || height <= 0 || density <= 0
                || movementSlop < 0 || now < 0 || x < 0 || x >= width || y < 0 || y >= height) return;
        float cornerWidth = Math.min(width, Math.max(160 * density, width * .25f));
        float cornerHeight = Math.min(height, Math.max(120 * density, height * .25f));
        if (x < width - cornerWidth || y > cornerHeight) return;
        downX = x; downY = y; slop = movementSlop; started = now; pending = true;
    }

    void move(int pointers, float x, float y) {
        if (!pending) return;
        float dx = x - downX, dy = y - downY;
        if (pointers != 1 || !Float.isFinite(x) || !Float.isFinite(y) || dx * dx + dy * dy > slop * slop)
            cancel();
    }

    boolean claim(long now) {
        if (!pending || now < started || now - started < HOLD_MILLIS) return false;
        pending = false; claimed = true; return true;
    }

    boolean pending() { return pending; }
    boolean claimed() { return claimed; }
    long remaining(long now) { return pending ? Math.max(0, HOLD_MILLIS - Math.max(0, now - started)) : 0; }
    void cancel() { pending = false; claimed = false; }
}
