package game.qualiarts.idolypride.phase_selftest;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

/** Synthetic-only phone report: no game, accounts or network access. */
public final class SelfTestActivity extends Activity implements Runnable, View.OnClickListener {
    private static native String runNative();
    private static String cached;
    private TextView summary;
    private TextView reportView;
    private Button copy;
    private String displayed;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        int padding = Math.round(16 * getResources().getDisplayMetrics().density);
        layout.setPadding(padding, padding, padding, padding);
        TextView title = new TextView(this);
        title.setText("아이프라 네이티브 점검");
        title.setTextSize(23);
        layout.addView(title);
        summary = new TextView(this);
        summary.setText("검사 중…");
        summary.setTextSize(20);
        summary.setPadding(0, padding, 0, padding);
        layout.addView(summary);
        TextView explanation = new TextView(this);
        explanation.setText("게임이나 계정 정보를 읽지 않습니다. 검사 후 전체 결과를 복사해 전달해 주세요.");
        layout.addView(explanation);
        copy = new Button(this);
        copy.setText("전체 결과 복사");
        copy.setEnabled(false);
        copy.setOnClickListener(this);
        layout.addView(copy, new LinearLayout.LayoutParams(-1, -2));
        reportView = new TextView(this);
        reportView.setTextIsSelectable(true);
        reportView.setTypeface(Typeface.MONOSPACE);
        reportView.setTextSize(13);
        reportView.setPadding(0, padding, 0, padding);
        ScrollView scroll = new ScrollView(this);
        scroll.addView(reportView);
        layout.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(layout);
        new Thread(this, "synthetic-native-check").start();
    }

    private static synchronized String performOnce() {
        if (cached != null) return cached;
        try {
            System.loadLibrary("idoly_phase_selftest");
            cached = runNative();
        } catch (Throwable ignored) {
            cached = "{\"schema\":2,\"ok\":false,\"synthetic_only\":true,\"load_failed\":true}";
        }
        return cached;
    }

    @Override public void run() {
        String result = performOnce();
        try {
            FileOutputStream stream = new FileOutputStream(new File(getFilesDir(), "selftest.json"), false);
            try { stream.write(result.getBytes(StandardCharsets.UTF_8)); }
            finally { stream.close(); }
        } catch (Exception ignored) { }
        runOnUiThread(new ShowReport(this, result));
    }

    private void show(String raw) {
        boolean success = false;
        try {
            JSONObject json = new JSONObject(raw);
            displayed = json.toString(2);
            success = json.optBoolean("ok", false);
        } catch (Exception ignored) { displayed = raw; }
        summary.setText(success ? "검사 통과" : "검사 실패 · 결과를 복사해 주세요");
        summary.setTextColor(success ? Color.rgb(20, 120, 60) : Color.rgb(170, 65, 20));
        reportView.setText(displayed);
        copy.setEnabled(true);
    }

    @Override public void onClick(View ignored) {
        if (displayed == null) return;
        ClipboardManager clipboard = (ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
        if (clipboard != null) {
            clipboard.setPrimaryClip(ClipData.newPlainText("네이티브 검사 결과", displayed));
            Toast.makeText(this, "전체 결과를 복사했습니다", Toast.LENGTH_SHORT).show();
        }
    }

    private static final class ShowReport implements Runnable {
        private final SelfTestActivity activity;
        private final String report;
        ShowReport(SelfTestActivity activity, String report) { this.activity = activity; this.report = report; }
        @Override public void run() { if (!activity.isFinishing() && !activity.isDestroyed()) activity.show(report); }
    }
}
