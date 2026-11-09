package game.qualiarts.idolypride.localserver;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.util.List;

/** Native controls for a server contained entirely in this installed app. */
public final class MainActivity extends Activity implements ServerService.Observer {
    private TextView status;
    private TextView logs;
    private Button start;
    private Button stop;
    private ScrollView logScroll;

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private TextView text(int resource, int size, int color) {
        TextView result = new TextView(this);
        result.setText(resource);
        result.setTextSize(size);
        result.setTextColor(color);
        return result;
    }

    private Button button(int label) {
        Button result = new Button(this);
        result.setText(label);
        result.setAllCaps(false);
        result.setMinHeight(dp(52));
        return result;
    }

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.rgb(19, 29, 36));
        getWindow().setNavigationBarColor(Color.rgb(19, 29, 36));
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(20), dp(24), dp(20), dp(12));
        content.setBackgroundColor(Color.rgb(19, 29, 36));
        TextView heading = text(R.string.app_name, 28, Color.WHITE);
        heading.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        content.addView(heading);
        TextView description = text(R.string.server_description, 15, Color.rgb(180, 199, 211));
        description.setPadding(0, dp(6), 0, dp(18));
        content.addView(description);

        status = text(R.string.status_stopped, 21, Color.WHITE);
        status.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        status.setPadding(dp(16), dp(14), dp(16), dp(14));
        GradientDrawable background = new GradientDrawable();
        background.setColor(Color.rgb(32, 48, 59));
        background.setCornerRadius(dp(12));
        status.setBackground(background);
        content.addView(status, new LinearLayout.LayoutParams(-1, -2));
        TextView ports = text(R.string.server_ports, 15, Color.rgb(180, 199, 211));
        ports.setPadding(0, dp(12), 0, dp(14));
        content.addView(ports);

        LinearLayout controls = new LinearLayout(this);
        controls.setOrientation(LinearLayout.HORIZONTAL);
        start = button(R.string.start_server);
        stop = button(R.string.stop_server);
        LinearLayout.LayoutParams half = new LinearLayout.LayoutParams(0, -2, 1);
        half.setMargins(0, 0, dp(4), 0);
        controls.addView(start, half);
        LinearLayout.LayoutParams otherHalf = new LinearLayout.LayoutParams(0, -2, 1);
        otherHalf.setMargins(dp(4), 0, 0, 0);
        controls.addView(stop, otherHalf);
        content.addView(controls);
        Button launch = button(R.string.launch_client);
        content.addView(launch, new LinearLayout.LayoutParams(-1, -2));
        TextView note = text(R.string.first_launch_note, 13, Color.rgb(160, 181, 194));
        note.setPadding(0, dp(8), 0, dp(14));
        content.addView(note);
        content.addView(text(R.string.server_logs, 16, Color.WHITE));
        logs = text(R.string.waiting_logs, 12, Color.rgb(192, 212, 222));
        logs.setTypeface(Typeface.MONOSPACE);
        logs.setTextIsSelectable(true);
        logs.setPadding(0, dp(8), 0, dp(16));
        logScroll = new ScrollView(this);
        logScroll.addView(logs);
        content.addView(logScroll, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(content);

        start.setOnClickListener(view -> {
            try {
                startForegroundService(new Intent(this, ServerService.class).setAction(ServerService.ACTION_START));
            } catch (RuntimeException error) {
                Toast.makeText(this, R.string.server_start_failed, Toast.LENGTH_LONG).show();
            }
        });
        stop.setOnClickListener(view -> startService(new Intent(this, ServerService.class).setAction(ServerService.ACTION_STOP)));
        launch.setOnClickListener(view -> {
            Intent client = getPackageManager().getLaunchIntentForPackage("game.qualiarts.idolypride.local");
            if (client == null) {
                Toast.makeText(this, R.string.client_missing, Toast.LENGTH_LONG).show();
                return;
            }
            try {
                startActivity(client);
            } catch (RuntimeException error) {
                Toast.makeText(this, R.string.client_launch_failed, Toast.LENGTH_LONG).show();
            }
        });
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 50051);
        }
    }

    @Override protected void onStart() {
        super.onStart();
        ServerService.observe(this);
    }

    @Override protected void onStop() {
        ServerService.removeObserver(this);
        super.onStop();
    }

    @Override public void onServerChanged(String value, boolean running, boolean busy, List<String> lines) {
        status.setText(value);
        status.setTextColor(running ? Color.rgb(117, 226, 177) : Color.WHITE);
        start.setEnabled(!running && !busy);
        stop.setEnabled(running || busy);
        logs.setText(lines.isEmpty() ? getString(R.string.waiting_logs) : String.join("\n", lines));
        logScroll.post(() -> logScroll.fullScroll(View.FOCUS_DOWN));
    }
}
