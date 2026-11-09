package game.qualiarts.idolypride.diagnostics;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.widget.TextView;

/** Disposable emulator fixture: the production provider and sanitizer are unchanged. */
public final class ProbeActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        TextView text = new TextView(this);
        text.setText("Diagnostics channel probe\nSynthetic Unity logs follow after 1.5 seconds.");
        text.setPadding(24, 48, 24, 24);
        setContentView(text);
        new Handler(Looper.getMainLooper()).postDelayed(() -> {
            Log.e("Unity", "NullReferenceException: IDOLY_DIAGNOSTICS_FAKE_SECRET\n"
                + "  at Solis.DiagnosticsProbe.SafeFrame (System.String value=IDOLY_DIAGNOSTICS_FAKE_SECRET)"
                + " [0x00000] in /FAKE_DIAGNOSTICS_PRIVATE/secret.cs:123");
            Log.i("Unity", "ShaderWarmUpが終わっていないので待機する");
        }, 1500);
    }
}
