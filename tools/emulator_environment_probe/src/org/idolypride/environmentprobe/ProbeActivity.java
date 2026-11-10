package org.idolypride.environmentprobe;

import android.app.Activity;
import android.os.Bundle;
import android.util.Log;
import android.widget.ScrollView;
import android.widget.TextView;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;

/** Synthetic graphics/CPU checks only; no game, account or network code. */
public final class ProbeActivity extends Activity {
    private static final String TAG = "IdolyEnvironmentProbe";
    private static String cached = "점검 준비 중…";
    private static boolean started;
    private static ProbeActivity current;
    private TextView text;
    private static native String nativeGraphics();
    private static native String nativeConversion();
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        text = new TextView(this);
        text.setPadding(24,24,24,24);
        text.setTextIsSelectable(true);
        text.setText(cached);
        ScrollView scroll = new ScrollView(this);
        scroll.addView(text);
        setContentView(scroll);
        synchronized (ProbeActivity.class) {
            current = this;
            if (!started) { started = true; new Thread(new RunProbe(this), "SyntheticProbe").start(); }
        }
    }
    @Override public void onDestroy() {
        synchronized (ProbeActivity.class) { if (current == this) current = null; }
        super.onDestroy();
    }
    private static void publish(ProbeActivity owner, JSONObject report) throws Exception {
        String value = report.toString();
        byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
        File temp = new File(owner.getFilesDir(), "report.tmp");
        try (FileOutputStream output = new FileOutputStream(temp)) { output.write(bytes); output.getFD().sync(); }
        if (!temp.renameTo(new File(owner.getFilesDir(), "report.json"))) throw new IllegalStateException("report_write_failed");
        cached = value;
        Log.i(TAG, value);
        synchronized (ProbeActivity.class) {
            if (current != null) current.runOnUiThread(new ShowReport(current, value));
        }
    }
    private static final class ShowReport implements Runnable {
        private final ProbeActivity owner; private final String value;
        ShowReport(ProbeActivity owner, String value) { this.owner=owner; this.value=value; }
        public void run() { if (!owner.isDestroyed()) owner.text.setText(value); }
    }
    private static final class RunProbe implements Runnable {
        private final ProbeActivity owner;
        RunProbe(ProbeActivity owner) { this.owner=owner; }
        public void run() {
            try {
                System.loadLibrary("idoly_environment_probe");
                JSONObject report = new JSONObject();
                report.put("schema",1); report.put("synthetic_only",true);
                report.put("stage","graphics_complete");
                report.put("graphics",new JSONObject(nativeGraphics()));
                publish(owner,report); // Preserve GPU evidence even if unsupported FCVTZS kills the process.
                report.put("stage","conversion_begin"); publish(owner,report);
                report.put("conversion",new JSONObject(nativeConversion()));
                report.put("stage","complete"); publish(owner,report);
            } catch (Throwable failure) {
                try { JSONObject report=new JSONObject();report.put("schema",1);report.put("stage","java_failure");
                    report.put("error_type",failure.getClass().getName());publish(owner,report); }
                catch (Throwable ignored) { Log.e(TAG,"report_write_failed"); }
            }
        }
    }
}
