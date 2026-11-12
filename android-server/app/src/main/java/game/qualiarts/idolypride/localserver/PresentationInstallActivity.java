package game.qualiarts.idolypride.localserver;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import android.os.Bundle;
import android.widget.Toast;

/** Receives only the explicit, session-bound PackageInstaller PendingIntent. */
public final class PresentationInstallActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        handleResult(getIntent());
    }

    private void handleResult(Intent result) {
        if (!PresentationAddonInstaller.expectedCallback(this, result)) {
            finish();
            return;
        }
        int status = result.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            Intent confirmation = result.getParcelableExtra(Intent.EXTRA_INTENT);
            if (confirmation != null) {
                try {
                    PresentationAddonInstaller.confirmationRequested(this);
                    startActivity(confirmation);
                    finish();
                    return;
                } catch (RuntimeException ignored) { }
            }
            status = PackageInstaller.STATUS_FAILURE;
        }
        int sessionId = result.getIntExtra(PresentationAddonInstaller.EXTRA_REQUESTED_SESSION, -1);
        PresentationAddonInstaller.completeInstall(this, sessionId, status, snapshot -> {
            Toast.makeText(this, "installed".equals(snapshot.state)
                    ? R.string.presentation_install_success : R.string.presentation_install_failed,
                    Toast.LENGTH_LONG).show();
            finish();
        });
    }
}
