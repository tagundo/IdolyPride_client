package game.qualiarts.idolypride.localserver;

import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.content.Intent;
import android.content.res.Configuration;
import android.view.Display;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;
import java.lang.ref.WeakReference;

/** Internal Unity entry point. The public launcher prepares the server and Data first. */
public final class UnifiedGameActivity extends com.google.firebase.MessagingUnityPlayerActivity {
    private static WeakReference<UnifiedGameActivity> windowOwner = new WeakReference<>(null);
    private String selectedDataPath;
    private final UnifiedMenuGesture menuGesture = new UnifiedMenuGesture();
    private final Handler menuTimer = new Handler(Looper.getMainLooper());
    private MotionEvent lastMenuEvent;
    private View menuSurface;
    private boolean discardResizedTouch;
    private int menuDisplay = Display.INVALID_DISPLAY;
    private final Runnable showMenu = this::recognizeMenuHold;
    private final View.OnLayoutChangeListener menuLayout = (view, left, top, right, bottom,
            oldLeft, oldTop, oldRight, oldBottom) -> {
        if (left != oldLeft || top != oldTop || right != oldRight || bottom != oldBottom) {
            cancelWindowMenuHold();
            UnifiedMP4Export.geometryChanged(this);
        }
    };

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
        windowOwner = new WeakReference<>(this);
        updateWindowing(isInMultiWindowMode());
        menuSurface = getWindow().getDecorView();
        menuSurface.addOnLayoutChangeListener(menuLayout);
        UnifiedMP4Export.restoreState(this, state);
        UnifiedMP4Export.attachGame(this);
    }

    private void updateWindowing(boolean multiWindow) {
        if (windowOwner.get() == this) UnifiedWindowing.update(multiWindow);
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
        menuDisplay = Display.INVALID_DISPLAY;
        if (lastMenuEvent != null) { lastMenuEvent.recycle(); lastMenuEvent = null; }
    }

    /** An old pointer's coordinates cannot span window geometry or display changes. */
    private void cancelWindowMenuHold() {
        MotionEvent previous = lastMenuEvent;
        lastMenuEvent = null;
        if (menuGesture.pending() || menuGesture.claimed()) discardResizedTouch = true;
        cancelMenuHold();
        if (previous != null) {
            MotionEvent cancelled = MotionEvent.obtain(previous);
            cancelled.setAction(MotionEvent.ACTION_CANCEL);
            try { super.dispatchTouchEvent(cancelled); }
            finally { cancelled.recycle(); previous.recycle(); }
        }
    }

    @Override public void onConfigurationChanged(Configuration configuration) {
        cancelWindowMenuHold();
        UnifiedMP4Export.geometryChanged(this);
        updateWindowing(isInMultiWindowMode());
        // Unity owns updating its configuration, SurfaceView and render lifecycle.
        super.onConfigurationChanged(configuration);
    }

    @Override public void onMultiWindowModeChanged(boolean multiWindow, Configuration configuration) {
        cancelWindowMenuHold();
        UnifiedMP4Export.geometryChanged(this);
        updateWindowing(multiWindow);
        super.onMultiWindowModeChanged(multiWindow, configuration);
    }

    @Override public void onWindowFocusChanged(boolean focused) {
        if (!focused) cancelWindowMenuHold();
        UnifiedMP4Export.focusChanged(this, focused);
        super.onWindowFocusChanged(focused);
    }

    private void recognizeMenuHold() {
        if (!menuGesture.pending() || isFinishing() || isDestroyed()) return;
        if (menuDisplay != currentDisplay()) {
            cancelWindowMenuHold();
            return;
        }
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

    private int currentDisplay() {
        Display display = getWindow().getDecorView().getDisplay();
        return display == null ? Display.INVALID_DISPLAY : display.getDisplayId();
    }

    @Override public boolean dispatchTouchEvent(MotionEvent event) {
        int action = event.getActionMasked();
        if (menuGesture.pending() && menuDisplay != currentDisplay()) cancelWindowMenuHold();
        if (discardResizedTouch) {
            if (action == MotionEvent.ACTION_DOWN) discardResizedTouch = false;
            else {
                if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) discardResizedTouch = false;
                return true;
            }
        }
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
                menuDisplay = currentDisplay();
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
        discardResizedTouch = false;
        cancelMenuHold();
        UnifiedMP4Export.gamePaused(this);
        super.onPause();
    }

    @Override protected void onResume() {
        updateWindowing(isInMultiWindowMode());
        super.onResume();
        UnifiedMP4Export.gameResumed(this);
    }

    @Override protected void onDestroy() {
        UnifiedMP4Export.gameDestroyed(this);
        if (windowOwner.get() == this) {
            windowOwner.clear();
            UnifiedWindowing.update(false);
        }
        if (menuSurface != null) {
            menuSurface.removeOnLayoutChangeListener(menuLayout);
            menuSurface = null;
        }
        discardResizedTouch = false;
        cancelMenuHold();
        super.onDestroy();
    }

    @Override protected void onSaveInstanceState(Bundle state) {
        UnifiedMP4Export.saveState(state);
        super.onSaveInstanceState(state);
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        UnifiedMP4Export.activityResult(this, request, result, data);
    }
}
