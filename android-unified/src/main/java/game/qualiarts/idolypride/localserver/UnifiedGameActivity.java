package game.qualiarts.idolypride.localserver;

import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.content.Intent;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;

/** Internal Unity entry point. The public launcher prepares the server and Data first. */
public final class UnifiedGameActivity extends com.google.firebase.MessagingUnityPlayerActivity {
    private String selectedDataPath;
    private final UnifiedMenuGesture menuGesture = new UnifiedMenuGesture();
    private final Handler menuTimer = new Handler(Looper.getMainLooper());
    private MotionEvent lastMenuEvent;
    private final Runnable showMenu = this::recognizeMenuHold;

    @Override protected void onCreate(Bundle state) {
        if (!UnifiedRuntime.isEnabled(this)) throw new IllegalStateException("unified_marker_missing");
        UnifiedRuntime.installResources(this);
        String selectedLanguage = UnifiedRuntime.expectedLanguage(getIntent());
        if (selectedLanguage == null) throw new IllegalStateException("unified_language_invalid");
        try {
            selectedDataPath = UnifiedGameAssets.freeze(this, selectedLanguage);
        } catch (java.io.IOException failure) {
            throw new IllegalStateException("unified_data_not_prepared", failure);
        }
        super.onCreate(state);
    }

    /** Unity's native VFS mounts Data here; applicationInfo/nativeLibraryDir stay real. */
    @Override public String getPackageCodePath() {
        return selectedDataPath == null ? super.getPackageCodePath() : selectedDataPath;
    }

    private void rememberMenuEvent(MotionEvent event) {
        if (lastMenuEvent != null) lastMenuEvent.recycle();
        lastMenuEvent = MotionEvent.obtain(event);
    }

    private void cancelMenuHold() {
        menuTimer.removeCallbacks(showMenu);
        menuGesture.cancel();
        if (lastMenuEvent != null) { lastMenuEvent.recycle(); lastMenuEvent = null; }
    }

    private void recognizeMenuHold() {
        if (!menuGesture.pending() || isFinishing() || isDestroyed()) return;
        long now = SystemClock.uptimeMillis();
        if (!menuGesture.claim(now)) {
            menuTimer.postDelayed(showMenu, menuGesture.remaining(now));
            return;
        }
        if (lastMenuEvent != null) {
            MotionEvent previous = lastMenuEvent;
            lastMenuEvent = null;
            MotionEvent cancelled = MotionEvent.obtain(previous);
            cancelled.setAction(MotionEvent.ACTION_CANCEL);
            try { super.dispatchTouchEvent(cancelled); }
            finally { cancelled.recycle(); previous.recycle(); }
        }
        if (isFinishing() || isDestroyed()) return;
        // Preserve the live Unity instance while bringing the existing menu forward.
        Intent menu = new Intent(this, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        try { startActivity(menu); }
        catch (RuntimeException unavailable) { cancelMenuHold(); }
    }

    @Override public boolean dispatchTouchEvent(MotionEvent event) {
        int action = event.getActionMasked();
        if (menuGesture.claimed()) {
            if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) cancelMenuHold();
            return true;
        }
        if (action == MotionEvent.ACTION_DOWN) {
            cancelMenuHold();
            View surface = getWindow().getDecorView();
            menuGesture.down(event.getPointerCount(), event.getX(), event.getY(), surface.getWidth(), surface.getHeight(),
                    getResources().getDisplayMetrics().density, ViewConfiguration.get(this).getScaledTouchSlop(),
                    event.getEventTime());
            if (menuGesture.pending()) {
                rememberMenuEvent(event);
                menuTimer.postDelayed(showMenu, menuGesture.remaining(SystemClock.uptimeMillis()));
            }
        } else if (action == MotionEvent.ACTION_MOVE) {
            menuGesture.move(event.getPointerCount(), event.getX(), event.getY());
            if (menuGesture.pending()) rememberMenuEvent(event); else cancelMenuHold();
        } else if (action == MotionEvent.ACTION_POINTER_DOWN || action == MotionEvent.ACTION_POINTER_UP
                || action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL
                || action == MotionEvent.ACTION_OUTSIDE) {
            cancelMenuHold();
        }
        return super.dispatchTouchEvent(event);
    }

    @Override protected void onPause() {
        cancelMenuHold();
        super.onPause();
    }

    @Override protected void onDestroy() {
        cancelMenuHold();
        super.onDestroy();
    }
}
