package game.qualiarts.idolypride.localserver;

import android.app.Activity;
import android.content.Intent;

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
        return super.instantiateActivity(loader, name, intent);
    }
}
