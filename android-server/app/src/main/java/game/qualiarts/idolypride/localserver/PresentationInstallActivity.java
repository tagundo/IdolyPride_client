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
        int status = result == null ? PackageInstaller.STATUS_FAILURE
                : result.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
        int legacy = result == null ? PresentationAddonInstaller.FailurePolicy.NO_STATUS
                : result.getIntExtra(PresentationAddonInstaller.EXTRA_LEGACY_STATUS,
                PresentationAddonInstaller.FailurePolicy.NO_STATUS);
        String osMessage = result == null ? null : result.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
        String installToken = PresentationAddonInstaller.FailurePolicy.installToken(osMessage);
        if (!PresentationAddonInstaller.expectedCallback(this, result)) {
            PresentationAddonInstaller.rejectedCallback(this, status, legacy, installToken);
            finish();
            return;
        }
        PresentationAddonInstaller.Failure failure = result.hasExtra(PackageInstaller.EXTRA_STATUS) ? null
                : PresentationAddonInstaller.FailurePolicy.make("callback", "callback_status_missing", null,
                null, null, null, PresentationAddonInstaller.FailurePolicy.NO_STATUS, legacy, installToken);
        if (failure == null && status != PackageInstaller.STATUS_SUCCESS
                && status != PackageInstaller.STATUS_PENDING_USER_ACTION) {
            failure = PresentationAddonInstaller.FailurePolicy.make("callback",
                    PresentationAddonInstaller.FailurePolicy.osReason(osMessage), null, null, null, null,
                    status, legacy, installToken);
        }
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            Intent confirmation = null;
            RuntimeException readFailure = null;
            try { confirmation = result.getParcelableExtra(Intent.EXTRA_INTENT); }
            catch (RuntimeException error) { readFailure = error; }
            if (confirmation != null) {
                try {
                    PresentationAddonInstaller.confirmationRequested(this);
                    startActivity(confirmation);
                    finish();
                    return;
                } catch (RuntimeException error) {
                    failure = PresentationAddonInstaller.FailurePolicy.make("confirmation", "confirmation_start_failed",
                            error, null, null, null, status, legacy, installToken);
                }
            } else {
                failure = PresentationAddonInstaller.FailurePolicy.make("confirmation", "confirmation_missing", readFailure,
                        null, null, null, status, legacy, installToken);
            }
        }
        int sessionId = result.getIntExtra(PresentationAddonInstaller.EXTRA_REQUESTED_SESSION, -1);
        PresentationAddonInstaller.completeInstall(this, sessionId, status, legacy, installToken, failure, snapshot -> {
            Toast.makeText(this, "installed".equals(snapshot.state)
                    ? R.string.presentation_install_success : R.string.presentation_install_failed,
                    Toast.LENGTH_LONG).show();
            finish();
        });
    }
}
