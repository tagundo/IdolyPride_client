package game.qualiarts.idolypride.localserver;

import android.app.Activity;
import android.content.Intent;
import android.util.Log;

/** Gate process-restored game activities before any Unity constructor can run. */
public final class UnifiedComponentFactory extends androidx.core.app.CoreComponentFactory {
    @Override public Activity instantiateActivity(ClassLoader loader, String name, Intent intent)
            throws InstantiationException, IllegalAccessException, ClassNotFoundException {
        if (UnifiedRuntime.GAME.equals(name)) {
            UnifiedGameAssets.ReadySnapshot ready = UnifiedGameAssets.readySnapshot();
            String selected = UnifiedRuntime.expectedLanguage(intent);
            if (ready == null || selected == null || !selected.equals(ready.language)
                    || !ServerService.resourceServerRunning()) {
                return super.instantiateActivity(loader, UnifiedGameRecoveryActivity.class.getName(), intent);
            }
        }
        if (!"game.qualiarts.idolypride.localserver.MainActivity".equals(name))
            return super.instantiateActivity(loader, name, intent);
        Log.i("IdolyLauncher", "launcher_constructor_begin");
        try {
            Activity activity = super.instantiateActivity(loader, name, intent);
            Log.i("IdolyLauncher", "launcher_constructor_returned");
            return activity;
        } catch (InstantiationException | IllegalAccessException | ClassNotFoundException
                | RuntimeException | Error failure) {
            // No Intent contents, exception messages or account data. Preserve
            // the original failure even if diagnostic logging is unavailable.
            try {
                Log.i("IdolyLauncher", "launcher_constructor_failed:" + failure.getClass().getName());
                StackTraceElement[] frames = failure.getStackTrace();
                for (int i = 0; i < Math.min(frames.length, 8); i++)
                    Log.i("IdolyLauncher", "launcher_constructor_frame:" + frames[i].toString());
            } catch (Throwable ignored) { }
            throw failure;
        }
    }
}
