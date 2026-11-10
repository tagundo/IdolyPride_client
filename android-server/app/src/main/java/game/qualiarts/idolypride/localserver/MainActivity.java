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
import android.net.Uri;
import android.text.TextUtils;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.util.List;
import java.util.Locale;
import org.json.JSONObject;

/** Native controls for a server contained entirely in this installed app. */
public final class MainActivity extends Activity implements ServerService.Observer {
    private TextView status;
    private TextView logs;
    private TextView gameStatus;
    private TextView transferStatus;
    private TextView lastException;
    private TextView networkStatus;
    private ProgressBar transferProgress;
    private Button export;
    private static final int EXPORT_DIAGNOSTICS = 50052;
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
        content.setPadding(dp(20), dp(16), dp(20), dp(8));
        content.setBackgroundColor(Color.rgb(19, 29, 36));
        TextView heading = text(R.string.app_name, 25, Color.WHITE);
        heading.setText(getString(R.string.app_name) + "  " + BuildConfig.VERSION_NAME);
        heading.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        content.addView(heading);
        TextView description = text(R.string.server_description, 13, Color.rgb(180, 199, 211));
        description.setPadding(0, dp(4), 0, dp(10));
        content.addView(description);

        status = text(R.string.status_stopped, 21, Color.WHITE);
        status.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        status.setPadding(dp(14), dp(10), dp(14), dp(10));
        GradientDrawable background = new GradientDrawable();
        background.setColor(Color.rgb(32, 48, 59));
        background.setCornerRadius(dp(12));
        status.setBackground(background);
        content.addView(status, new LinearLayout.LayoutParams(-1, -2));
        TextView ports = text(R.string.server_ports, 13, Color.rgb(180, 199, 211));
        ports.setPadding(0, dp(6), 0, dp(6));
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
        // Keep lifecycle controls visible while diagnostics and logs scroll.
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        TextView replayNotice = text(R.string.tutorial_replay_notice, 12, Color.rgb(180, 199, 211));
        replayNotice.setPadding(0, dp(6), 0, dp(8));
        body.addView(replayNotice);
        Button launch = button(R.string.launch_client);
        body.addView(launch, new LinearLayout.LayoutParams(-1, -2));
        LinearLayout diagnosticControls = new LinearLayout(this);
        diagnosticControls.setOrientation(LinearLayout.HORIZONTAL);
        Button diagnosticLaunch = button(R.string.launch_diagnostic_client);
        export = button(R.string.export_diagnostics);
        LinearLayout.LayoutParams diagnosticHalf = new LinearLayout.LayoutParams(0, -2, 1);
        diagnosticHalf.setMargins(0, 0, dp(4), 0);
        diagnosticControls.addView(diagnosticLaunch, diagnosticHalf);
        LinearLayout.LayoutParams exportHalf = new LinearLayout.LayoutParams(0, -2, 1);
        exportHalf.setMargins(dp(4), 0, 0, 0);
        diagnosticControls.addView(export, exportHalf);
        body.addView(diagnosticControls);
        body.addView(text(R.string.game_state_title, 15, Color.WHITE));
        gameStatus = text(R.string.game_state_waiting, 13, Color.rgb(192, 212, 222));
        gameStatus.setTextIsSelectable(true);
        gameStatus.setMaxLines(3);
        gameStatus.setEllipsize(TextUtils.TruncateAt.END);
        gameStatus.setPadding(0, dp(4), 0, dp(8));
        body.addView(gameStatus);
        lastException = text(R.string.game_state_waiting, 12, Color.rgb(255, 192, 154));
        lastException.setTextIsSelectable(true);
        lastException.setMaxLines(3);
        lastException.setEllipsize(TextUtils.TruncateAt.END);
        lastException.setVisibility(View.GONE);
        body.addView(lastException);
        networkStatus = text(R.string.game_network_waiting, 12, Color.rgb(160, 181, 194));
        networkStatus.setTextIsSelectable(true);
        networkStatus.setPadding(0, dp(4), 0, dp(8));
        body.addView(networkStatus);
        transferStatus = text(R.string.master_transfer_waiting, 12, Color.rgb(160, 181, 194));
        body.addView(transferStatus);
        transferProgress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        transferProgress.setMax(1000);
        transferProgress.setVisibility(View.GONE);
        body.addView(transferProgress, new LinearLayout.LayoutParams(-1, dp(12)));
        TextView note = text(R.string.first_launch_note, 13, Color.rgb(160, 181, 194));
        note.setPadding(0, dp(8), 0, dp(14));
        body.addView(note);
        body.addView(text(R.string.server_logs, 16, Color.WHITE));
        logs = text(R.string.waiting_logs, 12, Color.rgb(192, 212, 222));
        logs.setTypeface(Typeface.MONOSPACE);
        logs.setTextIsSelectable(true);
        logs.setPadding(0, dp(8), 0, dp(16));
        logScroll = new ScrollView(this);
        logScroll.addView(logs);
        logScroll.setNestedScrollingEnabled(true);
        body.addView(logScroll, new LinearLayout.LayoutParams(-1, dp(220)));
        ScrollView detailsScroll = new ScrollView(this);
        detailsScroll.setFillViewport(true);
        detailsScroll.addView(body, new ScrollView.LayoutParams(-1, -2));
        content.addView(detailsScroll, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(content);

        start.setOnClickListener(view -> {
            try {
                startForegroundService(new Intent(this, ServerService.class).setAction(ServerService.ACTION_START));
            } catch (RuntimeException error) {
                Toast.makeText(this, R.string.server_start_failed, Toast.LENGTH_LONG).show();
            }
        });
        stop.setOnClickListener(view -> startService(new Intent(this, ServerService.class).setAction(ServerService.ACTION_STOP)));
        launch.setOnClickListener(view -> launchClient("game.qualiarts.idolypride.local", R.string.client_missing));
        diagnosticLaunch.setOnClickListener(view -> launchClient("game.qualiarts.idolypride.local.diagnostics", R.string.diagnostic_client_missing));
        export.setOnClickListener(view -> {
            Intent destination = new Intent(Intent.ACTION_CREATE_DOCUMENT)
                    .addCategory(Intent.CATEGORY_OPENABLE)
                    .setType("application/json")
                    .putExtra(Intent.EXTRA_TITLE, "IdolyPride-diagnostics.json");
            try {
                startActivityForResult(destination, EXPORT_DIAGNOSTICS);
            } catch (RuntimeException error) {
                Toast.makeText(this, R.string.export_picker_failed, Toast.LENGTH_LONG).show();
            }
        });
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 50051);
        }
    }

    private void launchClient(String packageName, int missingMessage) {
        Intent client = getPackageManager().getLaunchIntentForPackage(packageName);
        if (client == null) {
            Toast.makeText(this, missingMessage, Toast.LENGTH_LONG).show();
            return;
        }
        try {
            startActivity(client);
        } catch (RuntimeException error) {
            Toast.makeText(this, R.string.client_launch_failed, Toast.LENGTH_LONG).show();
        }
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != EXPORT_DIAGNOSTICS || resultCode != RESULT_OK || data == null) return;
        Uri destination = data.getData();
        if (destination != null) ServerService.exportDiagnostics(getApplicationContext(), destination);
    }

    @Override protected void onStart() {
        super.onStart();
        ServerService.observe(this);
    }

    @Override protected void onStop() {
        ServerService.removeObserver(this);
        super.onStop();
    }

    @Override public void onServerChanged(String value, boolean running, boolean busy, List<String> lines, String detailsJson) {
        status.setText(value);
        status.setTextColor(running ? Color.rgb(117, 226, 177) : Color.WHITE);
        start.setEnabled(!running && !busy);
        stop.setEnabled(running || busy);
        export.setEnabled(!ServerService.isExporting());
        updateDiagnostics(detailsJson);
        String currentLogs = lines.isEmpty() ? getString(R.string.waiting_logs) : String.join("\n", lines);
        if (!currentLogs.contentEquals(logs.getText())) {
            boolean follow = logs.getHeight() - logScroll.getScrollY() <= logScroll.getHeight() + dp(32);
            logs.setText(currentLogs);
            if (follow) logScroll.post(() -> logScroll.fullScroll(View.FOCUS_DOWN));
        }
    }
    private void updateDiagnostics(String serialized) {
        JSONObject details;
        try { details = new JSONObject(serialized); }
        catch (Exception ignored) { details = new JSONObject(); }
        JSONObject client = details.optJSONObject("client_diagnostics");
        String summary = client == null ? "" : client.optString("summary", "");
        JSONObject phase = client == null ? null : client.optJSONObject("phase");
        String phaseSummary = phase == null ? "" : phase.optString("summary", "");
        if (!phaseSummary.isEmpty()) summary = getString(R.string.game_last_phase, phaseSummary);
        if (client == null || client.optLong("received_events", 0) == 0 || summary.isEmpty()) {
            setTextIfChanged(gameStatus, getString(R.string.game_state_waiting));
            gameStatus.setTextColor(Color.rgb(192, 212, 222));
        } else {
            setTextIfChanged(gameStatus, summary);
            gameStatus.setTextColor(client.optJSONObject("latest_exception") == null
                    ? Color.rgb(192, 212, 222) : Color.rgb(255, 192, 154));
        }
        JSONObject exception = client == null ? null : client.optJSONObject("latest_exception");
        if (exception != null) {
            String identity = exception.optString("type", "");
            org.json.JSONArray frames = exception.optJSONArray("frames");
            if (frames != null && frames.length() > 0) identity += " @ " + frames.optString(0, "");
            setTextIfChanged(lastException, getString(R.string.latest_game_exception, identity));
            lastException.setVisibility(View.VISIBLE);
        } else {
            lastException.setVisibility(View.GONE);
        }
        JSONObject network = client == null ? null : client.optJSONObject("network");
        if (client != null && client.optBoolean("network_unavailable", false)) {
            setTextIfChanged(networkStatus, getString(R.string.game_network_unavailable));
        } else if (network != null) {
            long rx = Math.max(0, network.optLong("rx_bytes", 0));
            long tx = Math.max(0, network.optLong("tx_bytes", 0));
            long elapsedSeconds = Math.max(0, network.optLong("elapsed_ms", 0)) / 1000;
            setTextIfChanged(networkStatus, getString(R.string.game_network_totals, formatBytes(rx), formatBytes(tx), elapsedSeconds));
        } else {
            setTextIfChanged(networkStatus, getString(R.string.game_network_waiting));
        }
        JSONObject transfer = details.optJSONObject("asset_transfer");
        long sent = transfer == null ? 0 : Math.max(0, transfer.optLong("sent_bytes", 0));
        long total = transfer == null ? 0 : Math.max(0, transfer.optLong("total_bytes", 0));
        long completed = transfer == null ? 0 : Math.max(0, transfer.optLong("completed_requests", 0));
        int active = transfer == null ? 0 : Math.max(0, transfer.optInt("active_requests", 0));
        String transferState = transfer == null ? "" : transfer.optString("status", "");
        boolean failed = "error".equals(transferState) || "failed".equals(transferState)
                || (transfer != null && transfer.optInt("status", 0) >= 400);
        if (failed) {
            transferStatus.setText(getString(R.string.master_transfer_failed, formatBytes(sent), formatBytes(total)));
        } else if (active > 0) {
            transferStatus.setText(getString(R.string.master_transfer_active, formatBytes(sent), formatBytes(total)));
        } else if (completed > 0 || sent > 0) {
            transferStatus.setText(getString(R.string.master_transfer_finished, completed, formatBytes(sent)));
        } else {
            transferStatus.setText(R.string.master_transfer_waiting);
        }
        boolean hasProgress = !failed && active > 0 && total > 0;
        transferProgress.setVisibility(hasProgress ? View.VISIBLE : View.GONE);
        if (hasProgress) {
            transferProgress.setIndeterminate(false);
            transferProgress.setProgress((int) Math.max(0, Math.min(1000, ((double) sent / total) * 1000)));
        }
    }

    private static void setTextIfChanged(TextView view, String value) {
        // Repeated service polls must not reset an unchanged text selection.
        if (!value.contentEquals(view.getText())) view.setText(value);
    }

    private static String formatBytes(long bytes) {
        if (bytes < 1024) return bytes + " B";
        if (bytes < 1024 * 1024) return String.format(Locale.getDefault(), "%.1f KiB", bytes / 1024.0);
        return String.format(Locale.getDefault(), "%.1f MiB", bytes / (1024.0 * 1024.0));
    }

}
