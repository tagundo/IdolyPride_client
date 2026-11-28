package game.qualiarts.idolypride.queueqa;

import android.app.Activity;
import android.os.Bundle;
import android.os.Process;
import android.system.Os;
import android.widget.TextView;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONArray;
import org.json.JSONObject;

/** Loads only a small JNI probe compiled against the actual production queue header. */
public final class QueueProbeActivity extends Activity {
    private static final AtomicBoolean STARTED = new AtomicBoolean();
    private static native String probe(String directory, String challenge);

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        TextView label = new TextView(this);
        label.setText("Running production queue storage proof…");
        setContentView(label);
        if (!STARTED.compareAndSet(false, true)) return;
        String challenge = getIntent().getStringExtra("challenge");
        new Thread(() -> {
            JSONObject report = new JSONObject();
            File root = new File(getFilesDir(), "queue-qa");
            try {
                report.put("schema", 1).put("package", getPackageName()).put("challenge", challenge)
                        .put("java_uid", Process.myUid()).put("java_pid", Process.myPid())
                        .put("android_api", android.os.Build.VERSION.SDK_INT);
                if (challenge == null || !challenge.matches("[0-9a-f]{64}")) throw new Exception("invalid_challenge");
                if (!root.mkdir()) throw new Exception("fresh_probe_directory_required");
                Os.chmod(root.getPath(), 0700);
                System.loadLibrary("idoly_queue_qa");
                JSONObject nativeReport = new JSONObject(probe(root.getAbsolutePath(), challenge));
                report.put("native", nativeReport);
                if (nativeReport.has("error")) throw new Exception(nativeReport.getString("error"));
                if (nativeReport.getInt("uid") != Process.myUid()
                        || nativeReport.getInt("pid") != Process.myPid()) throw new Exception("native_process_differs");
                JSONArray cases = nativeReport.getJSONArray("cases");
                for (int i = 0; i < cases.length(); i++) {
                    if (!"passed".equals(cases.getJSONObject(i).getString("status"))) throw new Exception("required_case_failed");
                }
                report.put("phase", "completed").put("passed", true);
                runOnUiThread(() -> label.setText("PASS: production queue storage in ordinary Android app"));
            } catch (Throwable error) {
                try { report.put("phase", "failed").put("passed", false).put("error", error.getClass().getSimpleName()); }
                catch (Exception ignored) { }
                runOnUiThread(() -> label.setText("FAIL: queue storage proof"));
            }
            try {
                byte[] bytes = (report.toString(2) + "\n").getBytes(StandardCharsets.UTF_8);
                if (bytes.length > 32768) throw new Exception("report_bound");
                File temporary = new File(root, "report.tmp");
                try (FileOutputStream output = new FileOutputStream(temporary)) {
                    Os.chmod(temporary.getPath(), 0600); output.write(bytes); output.getFD().sync();
                }
                Os.rename(temporary.getPath(), new File(root, "report.json").getPath());
            } catch (Exception ignored) { /* A missing report fails the host gate. */ }
        }, "IdolyQueueQA").start();
    }
}
