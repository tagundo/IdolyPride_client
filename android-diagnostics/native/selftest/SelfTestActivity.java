package game.qualiarts.idolypride.phase_selftest;

import android.app.Activity;
import android.os.Bundle;
import android.util.Log;
import android.widget.TextView;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;

/** Separate disposable fixture; contains no game or production profile data. */
public final class SelfTestActivity extends Activity implements Runnable {
    private static native String runNative();
    private TextView view;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        view = new TextView(this);
        view.setText("ARM64 instruction interceptor self-test running");
        setContentView(view);
        new Thread(this, "synthetic-intercept-test").start();
    }

    @Override public void run() {
        String result;
        try {
            System.loadLibrary("idoly_phase_selftest");
            result = runNative();
        } catch (Throwable failure) {
            result = "{\"schema\":1,\"ok\":false,\"synthetic_only\":true,\"load_failed\":true}";
        }
        try {
            File file = new File(getFilesDir(), "selftest.json");
            FileOutputStream output = new FileOutputStream(file, false);
            try { output.write(result.getBytes(StandardCharsets.UTF_8)); }
            finally { output.close(); }
        } catch (Exception failure) {
            result = "{\"schema\":1,\"ok\":false,\"synthetic_only\":true,\"report_write_failed\":true}";
        }
        Log.i("IDOLY_SELFTEST", result);
        runOnUiThread(new ShowReport(view, result));
    }

    private static final class ShowReport implements Runnable {
        private final TextView view;
        private final String report;

        ShowReport(TextView view, String report) {
            this.view = view;
            this.report = report;
        }

        @Override public void run() { view.setText(report); }
    }
}
