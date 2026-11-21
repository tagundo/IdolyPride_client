package game.qualiarts.idolypride.localserver;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

/** A restored game record safely returns to the launcher without initializing Unity. */
public final class UnifiedGameRecoveryActivity extends Activity {
    @Override protected void onCreate(Bundle state) {
        // This transient replacement must not restore Unity's fragment/UI state.
        super.onCreate(null);
        Intent menu = new Intent(Intent.ACTION_MAIN).setClass(this, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        UnifiedRuntime.copyLaunchPayload(menu, getIntent());
        menu.removeExtra(UnifiedRuntime.EXPECTED_LANGUAGE);
        startActivity(menu);
        finish();
    }
}
