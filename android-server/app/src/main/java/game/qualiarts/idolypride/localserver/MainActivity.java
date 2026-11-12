package game.qualiarts.idolypride.localserver;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.net.Uri;
import android.text.TextUtils;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import java.util.List;
import java.util.Locale;
import java.io.IOException;
import org.json.JSONObject;

/** Native controls for a server contained entirely in this installed app. */
public final class MainActivity extends Activity implements ServerService.Observer {
    static final String SERVER_PREFS = "local_server";
    static final String EXPERIMENTAL_MAIN_LIVE = "experimental_main_live";
    static final String DOWNLOAD_MISSING_RESOURCES = "download_missing_resources";
    static final String MEDIA_MODE = "media_mode";
    private CheckBox experimentalMainLive;
    private CheckBox downloadMissingResources;
    private CheckBox mediaMode;
    private TextView status;
    private TextView logs;
    private TextView gameStatus;
    private TextView transferStatus;
    private TextView lastException;
    private TextView networkStatus;
    private TextView resourceStatus;
    private TextView resourceReceived;
    private TextView resourceServed;
    private ProgressBar transferProgress;
    private Button export;
    private static final int EXPORT_DIAGNOSTICS = 50052;
    private Button start;
    private Button stop;
    private ScrollView logScroll;
    private PresentationSettings presentationSettings;
    private CheckBox customGraphics;
    private CheckBox expandPhotography;
    private Spinner graphicsQuality;
    private Spinner targetFps;
    private Spinner renderScale;
    private Spinner maxBufferPixel;
    private Spinner antiAliasing;
    private Spinner shadowResolution;
    private TextView presentationStatus;
    private boolean presentationLoading;
    private boolean presentationSaveFailed;
    private boolean presentationInvalid;
    private JSONObject presentationRuntime;
    private boolean presentationServerRunning;
    private boolean presentationObserved;
    private Button installPresentation;
    private Button launchPresentation;
    private TextView presentationInstallStatus;
    private TextView presentationInstallDetails;
    private TextView presentationInstallStorage;
    private CheckBox presentationFeatureOnly;
    private boolean presentationFeatureOnlyLoading;
    private Button copyPresentationInstallDetails;
    private PresentationAddonInstaller.Snapshot presentationInstallation;

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
        mediaMode = new CheckBox(this);
        mediaMode.setText(R.string.media_mode);
        mediaMode.setTextColor(Color.WHITE);
        mediaMode.setTextSize(13);
        mediaMode.setChecked(getSharedPreferences(SERVER_PREFS, MODE_PRIVATE)
                .getBoolean(MEDIA_MODE, false));
        mediaMode.setOnCheckedChangeListener((button, enabled) ->
                getSharedPreferences(SERVER_PREFS, MODE_PRIVATE).edit()
                        .putBoolean(MEDIA_MODE, enabled).apply());
        body.addView(mediaMode);
        TextView mediaNotice = text(R.string.media_mode_notice, 12, Color.rgb(180, 199, 211));
        mediaNotice.setPadding(0, 0, 0, dp(6));
        body.addView(mediaNotice);
        experimentalMainLive = new CheckBox(this);
        experimentalMainLive.setText(R.string.experimental_main_live);
        experimentalMainLive.setTextColor(Color.WHITE);
        experimentalMainLive.setTextSize(13);
        experimentalMainLive.setChecked(getSharedPreferences(SERVER_PREFS, MODE_PRIVATE)
                .getBoolean(EXPERIMENTAL_MAIN_LIVE, false));
        experimentalMainLive.setOnCheckedChangeListener((button, enabled) ->
                getSharedPreferences(SERVER_PREFS, MODE_PRIVATE).edit()
                        .putBoolean(EXPERIMENTAL_MAIN_LIVE, enabled).apply());
        body.addView(experimentalMainLive);
        TextView liveNotice = text(R.string.experimental_main_live_notice, 12, Color.rgb(180, 199, 211));
        body.addView(liveNotice);
        downloadMissingResources = new CheckBox(this);
        downloadMissingResources.setText(R.string.download_missing_resources);
        downloadMissingResources.setTextColor(Color.WHITE);
        downloadMissingResources.setTextSize(13);
        downloadMissingResources.setChecked(getSharedPreferences(SERVER_PREFS, MODE_PRIVATE)
                .getBoolean(DOWNLOAD_MISSING_RESOURCES, true));
        downloadMissingResources.setOnCheckedChangeListener((button, enabled) ->
                getSharedPreferences(SERVER_PREFS, MODE_PRIVATE).edit()
                        .putBoolean(DOWNLOAD_MISSING_RESOURCES, enabled).apply());
        body.addView(downloadMissingResources);
        TextView resourceNotice = text(R.string.download_missing_resources_notice, 12, Color.rgb(180, 199, 211));
        resourceNotice.setPadding(0, 0, 0, dp(6));
        body.addView(resourceNotice);
        addPresentationControls(body);
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
        TextView resourceHeading = text(R.string.resource_transfer_title, 15, Color.WHITE);
        resourceHeading.setPadding(0, dp(10), 0, dp(4));
        body.addView(resourceHeading);
        resourceStatus = text(R.string.resource_transfer_waiting, 12, Color.rgb(192, 212, 222));
        resourceStatus.setTextIsSelectable(true);
        body.addView(resourceStatus);
        resourceReceived = text(R.string.resource_transfer_waiting, 12, Color.rgb(160, 181, 194));
        resourceReceived.setTextIsSelectable(true);
        resourceReceived.setVisibility(View.GONE);
        body.addView(resourceReceived);
        resourceServed = text(R.string.resource_transfer_waiting, 12, Color.rgb(160, 181, 194));
        resourceServed.setTextIsSelectable(true);
        resourceServed.setVisibility(View.GONE);
        body.addView(resourceServed);
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
        launch.setOnClickListener(view -> launchClient(R.string.client_missing,
                "game.qualiarts.idolypride.local.resources", "game.qualiarts.idolypride.local"));
        diagnosticLaunch.setOnClickListener(view -> launchClient(R.string.diagnostic_client_missing,
                "game.qualiarts.idolypride.local.diagnostics"));
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

    private void addPresentationControls(LinearLayout body) {
        PresentationSettings.Loaded loaded = PresentationSettings.load(getFilesDir());
        presentationSettings = loaded.settings;
        presentationInvalid = loaded.invalid;
        Button heading = button(R.string.presentation_title);
        body.addView(heading, new LinearLayout.LayoutParams(-1, -2));
        LinearLayout settings = new LinearLayout(this);
        settings.setOrientation(LinearLayout.VERTICAL);
        settings.setPadding(dp(8), 0, dp(8), dp(8));
        settings.setVisibility(View.GONE);
        body.addView(settings, new LinearLayout.LayoutParams(-1, -2));
        heading.setOnClickListener(view -> {
            boolean expanded = settings.getVisibility() != View.VISIBLE;
            settings.setVisibility(expanded ? View.VISIBLE : View.GONE);
            heading.setText(expanded ? R.string.presentation_title_expanded : R.string.presentation_title);
        });
        TextView notice = text(R.string.presentation_notice, 12, Color.rgb(180, 199, 211));
        notice.setPadding(0, dp(4), 0, dp(8));
        settings.addView(notice);
        TextView installNotice = text(R.string.presentation_install_notice, 12, Color.rgb(180, 199, 211));
        installNotice.setPadding(0, 0, 0, dp(6));
        settings.addView(installNotice);
        presentationFeatureOnly = new CheckBox(this);
        presentationFeatureOnly.setText(R.string.presentation_install_feature_only);
        presentationFeatureOnly.setTextColor(Color.WHITE);
        presentationFeatureOnly.setTextSize(13);
        presentationFeatureOnly.setChecked(PresentationAddonInstaller.featureOnly(this));
        settings.addView(presentationFeatureOnly);
        TextView compatibilityNotice = text(R.string.presentation_install_feature_only_notice, 12,
                Color.rgb(180, 199, 211));
        compatibilityNotice.setPadding(0, 0, 0, dp(6));
        settings.addView(compatibilityNotice);
        presentationInstallStorage = text(R.string.presentation_install_storage_checking, 12,
                Color.rgb(192, 212, 222));
        presentationInstallStorage.setTextIsSelectable(true);
        presentationInstallStorage.setPadding(0, 0, 0, dp(8));
        settings.addView(presentationInstallStorage);
        installPresentation = button(R.string.presentation_install_button);
        installPresentation.setEnabled(false);
        installPresentation.setOnClickListener(view -> requestPresentationInstall());
        settings.addView(installPresentation, new LinearLayout.LayoutParams(-1, -2));
        launchPresentation = button(R.string.presentation_launch_button);
        launchPresentation.setEnabled(false);
        launchPresentation.setOnClickListener(view -> launchPresentationClient());
        settings.addView(launchPresentation, new LinearLayout.LayoutParams(-1, -2));
        presentationInstallStatus = text(R.string.presentation_install_checking, 12, Color.rgb(192, 212, 222));
        presentationInstallStatus.setPadding(0, dp(4), 0, dp(8));
        settings.addView(presentationInstallStatus);
        presentationInstallDetails = text(R.string.presentation_install_checking, 12, Color.rgb(255, 192, 154));
        presentationInstallDetails.setTextIsSelectable(true);
        presentationInstallDetails.setPadding(0, 0, 0, dp(8));
        presentationInstallDetails.setVisibility(View.GONE);
        settings.addView(presentationInstallDetails);
        copyPresentationInstallDetails = button(R.string.presentation_install_copy);
        copyPresentationInstallDetails.setEnabled(false);
        copyPresentationInstallDetails.setOnClickListener(view -> {
            ClipboardManager clipboard = (ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
            if (clipboard != null) {
                clipboard.setPrimaryClip(ClipData.newPlainText(getString(R.string.presentation_install_copy),
                        presentationInstallDetails.getText()));
                Toast.makeText(this, R.string.presentation_install_copied, Toast.LENGTH_SHORT).show();
            }
        });
        settings.addView(copyPresentationInstallDetails, new LinearLayout.LayoutParams(-1, -2));
        presentationFeatureOnly.setOnCheckedChangeListener((button, enabled) -> {
            if (presentationFeatureOnlyLoading) return;
            PresentationAddonInstaller.setFeatureOnly(this, enabled);
            installPresentation.setEnabled(false);
            setTextIfChanged(presentationInstallStorage, getString(R.string.presentation_install_storage_checking));
            refreshPresentationInstallation();
        });
        customGraphics = new CheckBox(this);
        customGraphics.setText(R.string.presentation_custom_graphics);
        customGraphics.setTextColor(Color.WHITE);
        customGraphics.setTextSize(14);
        settings.addView(customGraphics);
        graphicsQuality = presentationSpinner(settings, R.string.presentation_quality,
                R.array.presentation_quality_options);
        targetFps = presentationSpinner(settings, R.string.presentation_target_fps,
                R.array.presentation_target_fps_options);
        renderScale = presentationSpinner(settings, R.string.presentation_render_scale,
                R.array.presentation_render_scale_options);
        maxBufferPixel = presentationSpinner(settings, R.string.presentation_max_buffer_pixel,
                R.array.presentation_max_buffer_pixel_options);
        antiAliasing = presentationSpinner(settings, R.string.presentation_anti_aliasing,
                R.array.presentation_anti_aliasing_options);
        shadowResolution = presentationSpinner(settings, R.string.presentation_shadow_resolution,
                R.array.presentation_shadow_resolution_options);
        expandPhotography = new CheckBox(this);
        expandPhotography.setText(R.string.presentation_expand_photography);
        expandPhotography.setTextColor(Color.WHITE);
        expandPhotography.setTextSize(14);
        settings.addView(expandPhotography);
        TextView photographyNotice = text(R.string.presentation_photography_notice, 12,
                Color.rgb(180, 199, 211));
        photographyNotice.setPadding(0, 0, 0, dp(8));
        settings.addView(photographyNotice);
        presentationStatus = text(R.string.presentation_waiting, 12, Color.rgb(192, 212, 222));
        presentationStatus.setTextIsSelectable(true);
        presentationStatus.setPadding(0, dp(4), 0, dp(8));
        body.addView(presentationStatus);
        restorePresentationControls();
        customGraphics.setOnCheckedChangeListener((button, checked) -> savePresentationControls());
        expandPhotography.setOnCheckedChangeListener((button, checked) -> savePresentationControls());
        AdapterView.OnItemSelectedListener selected = new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                savePresentationControls();
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        };
        for (Spinner spinner : presentationSpinners()) spinner.setOnItemSelectedListener(selected);
        updatePresentationStatus();
    }

    private void refreshPresentationInstallation() {
        PresentationAddonInstaller.refresh(this, this::showPresentationInstallation);
    }

    private String presentationStorageSummary(PresentationAddonInstaller.Profile profile, long addonBytes,
            long existingCopyBytes, long nativeExtractBytes, long totalBytes, long availableBytes,
            long freeBytes, String volume, boolean featureOnly) {
        return getString(R.string.presentation_install_storage_profile, getString(profile.label()),
                presentationStorageBytes(addonBytes), featureOnly ? getString(R.string.presentation_install_storage_none)
                        : presentationStorageBytes(existingCopyBytes),
                presentationStorageBytes(nativeExtractBytes), presentationStorageBytes(totalBytes),
                presentationStorageBytes(availableBytes), presentationStorageBytes(freeBytes),
                getString("internal".equals(volume) ? R.string.presentation_install_volume_internal
                        : "other".equals(volume) ? R.string.presentation_install_volume_other
                        : R.string.presentation_install_storage_unknown));
    }

    private String presentationStorageBytes(long bytes) {
        return bytes < 0 ? getString(R.string.presentation_install_storage_unknown) : formatBytes(bytes);
    }

    private void showPresentationInstallation(PresentationAddonInstaller.Snapshot snapshot) {
        if (isFinishing() || isDestroyed()) return;
        presentationInstallation = snapshot;
        presentationFeatureOnlyLoading = true;
        presentationFeatureOnly.setChecked(snapshot.featureOnly);
        presentationFeatureOnlyLoading = false;
        presentationFeatureOnly.setEnabled(!snapshot.busy && Build.VERSION.SDK_INT >= 28);
        StringBuilder storage = new StringBuilder();
        for (PresentationAddonInstaller.Profile profile : snapshot.compatible) {
            PresentationStorage.Estimate estimate = null;
            for (PresentationStorage.Estimate candidate : snapshot.storage)
                if (profile.id.equals(candidate.profileId)) { estimate = candidate; break; }
            if (storage.length() > 0) storage.append("\n\n");
            storage.append(presentationStorageSummary(profile, estimate == null ? -1 : estimate.addonBytes,
                    estimate == null ? -1 : estimate.existingCopyBytes, estimate == null ? -1 : estimate.nativeExtractBytes,
                    estimate == null ? -1 : estimate.totalBytes, estimate == null ? -1 : estimate.availableBytes,
                    estimate == null ? -1 : estimate.freeBytes, estimate == null ? "unknown" : estimate.volume,
                    snapshot.featureOnly));
        }
        if (storage.length() > 0) storage.append("\n").append(getString(R.string.presentation_install_storage_basis));
        setTextIfChanged(presentationInstallStorage, storage.length() == 0
                ? getString(R.string.presentation_install_storage_no_game) : storage.toString());
        installPresentation.setEnabled(!snapshot.busy && !snapshot.compatible.isEmpty());
        launchPresentation.setEnabled(!snapshot.busy && !snapshot.installed.isEmpty());
        int message;
        if (Build.VERSION.SDK_INT < 28) message = R.string.presentation_install_android_required;
        else if (!snapshot.bundleAvailable) message = R.string.presentation_install_bundle_unavailable;
        else if (snapshot.busy) message = "confirmation".equals(snapshot.state)
                ? R.string.presentation_install_confirming : R.string.presentation_install_in_progress;
        else if ("interrupted".equals(snapshot.state)) message = R.string.presentation_install_interrupted;
        else if ("failed".equals(snapshot.state)) {
            message = snapshot.failure != null && "storage_or_io_error".equals(snapshot.failure.category)
                    ? R.string.presentation_install_storage_insufficient : R.string.presentation_install_failed;
        } else if (!snapshot.installed.isEmpty()) message = R.string.presentation_install_available;
        else if (snapshot.compatible.isEmpty()) message = R.string.presentation_install_incompatible;
        else message = R.string.presentation_install_ready;
        setTextIfChanged(presentationInstallStatus, getString(message));
        presentationInstallStatus.setTextColor("failed".equals(snapshot.state) || "interrupted".equals(snapshot.state)
                ? Color.rgb(255, 192, 154) : Color.rgb(192, 212, 222));
        PresentationAddonInstaller.Failure failure = snapshot.failure;
        presentationInstallDetails.setVisibility(failure == null ? View.GONE : View.VISIBLE);
        copyPresentationInstallDetails.setEnabled(failure != null);
        if (failure != null) {
            String details = getString(R.string.presentation_install_failure_details, failure.stage, failure.reason,
                    failure.exceptionClass, Build.VERSION.SDK_INT, snapshot.profile);
            if (failure.status != PresentationAddonInstaller.FailurePolicy.NO_STATUS)
                details += getString(R.string.presentation_install_failure_status, failure.status);
            if (failure.legacyStatus != PresentationAddonInstaller.FailurePolicy.NO_STATUS)
                details += getString(R.string.presentation_install_failure_legacy, failure.legacyStatus);
            if (!failure.installToken.isEmpty()) details += "\n" + failure.installToken;
            if (!failure.member.isEmpty()) details += "\n" + failure.member;
            if (!failure.expectedSha.isEmpty()) details += getString(R.string.presentation_install_failure_hash,
                    failure.expectedSha, failure.actualSha);
            details += getString(R.string.presentation_install_failure_category, failure.category);
            if (!failure.errno.isEmpty()) details += "\nerrno: " + failure.errno;
            if (!failure.osMessage.isEmpty()) details += getString(R.string.presentation_install_failure_message,
                    failure.osMessage);
            setTextIfChanged(presentationInstallDetails, details);
        }
    }

    private interface PresentationProfileAction {
        void run(PresentationAddonInstaller.Profile profile);
    }

    private void choosePresentationProfile(List<PresentationAddonInstaller.Profile> profiles,
            int title, PresentationProfileAction action) {
        if (profiles.size() == 1) {
            action.run(profiles.get(0));
            return;
        }
        String[] labels = new String[profiles.size()];
        for (int index = 0; index < profiles.size(); index++) labels[index] = getString(profiles.get(index).label());
        new AlertDialog.Builder(this).setTitle(title).setItems(labels,
                (dialog, which) -> action.run(profiles.get(which)))
                .setNegativeButton(android.R.string.cancel, null).show();
    }

    private void requestPresentationInstall() {
        if (presentationInstallation == null || presentationInstallation.busy
                || presentationInstallation.compatible.isEmpty()) return;
        if (Build.VERSION.SDK_INT < 28) return;
        if (!getPackageManager().canRequestPackageInstalls()) {
            try {
                startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                        Uri.parse("package:" + getPackageName())));
                Toast.makeText(this, R.string.presentation_install_permission, Toast.LENGTH_LONG).show();
            } catch (RuntimeException error) {
                PresentationAddonInstaller.permissionScreenFailed(this, error);
                Toast.makeText(this, R.string.presentation_install_permission_failed, Toast.LENGTH_LONG).show();
                refreshPresentationInstallation();
            }
            return;
        }
        final boolean featureOnly = presentationFeatureOnly.isChecked();
        choosePresentationProfile(presentationInstallation.compatible, R.string.presentation_install_choose,
                profile -> {
                    installPresentation.setEnabled(false);
                    launchPresentation.setEnabled(false);
                    presentationInstallDetails.setVisibility(View.GONE);
                    copyPresentationInstallDetails.setEnabled(false);
                    presentationFeatureOnly.setEnabled(false);
                    setTextIfChanged(presentationInstallStatus, getString(R.string.presentation_install_in_progress));
                    PresentationAddonInstaller.install(this, profile, featureOnly, this::showPresentationInstallation);
                });
    }

    private void launchPresentationClient() {
        launchPresentation.setEnabled(false);
        PresentationAddonInstaller.refresh(this, snapshot -> {
            showPresentationInstallation(snapshot);
            if (isFinishing() || isDestroyed()) return;
            if (snapshot.installed.isEmpty() || snapshot.busy) {
                Toast.makeText(this, R.string.presentation_install_launch_missing, Toast.LENGTH_LONG).show();
                return;
            }
            choosePresentationProfile(snapshot.installed, R.string.presentation_launch_choose,
                    profile -> launchClient(R.string.presentation_install_launch_missing, profile.targetPackage));
        });
    }

    private Spinner presentationSpinner(LinearLayout parent, int labelResource, int optionsResource) {
        TextView label = text(labelResource, 13, Color.rgb(192, 212, 222));
        label.setPadding(0, dp(6), 0, 0);
        parent.addView(label);
        Spinner spinner = new Spinner(this);
        spinner.setId(View.generateViewId());
        label.setLabelFor(spinner.getId());
        spinner.setMinimumHeight(dp(48));
        ArrayAdapter<String> adapter = new ArrayAdapter<String>(this,
                android.R.layout.simple_spinner_item, getResources().getStringArray(optionsResource)) {
            @Override public View getView(int position, View convertView, ViewGroup parentView) {
                TextView value = (TextView) super.getView(position, convertView, parentView);
                value.setTextColor(Color.WHITE);
                value.setTextSize(14);
                return value;
            }
        };
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        spinner.setAdapter(adapter);
        parent.addView(spinner, new LinearLayout.LayoutParams(-1, -2));
        return spinner;
    }

    private Spinner[] presentationSpinners() {
        return new Spinner[]{graphicsQuality, targetFps, renderScale, maxBufferPixel,
                antiAliasing, shadowResolution};
    }

    private void restorePresentationControls() {
        presentationLoading = true;
        customGraphics.setChecked(presentationSettings.customGraphics);
        expandPhotography.setChecked(presentationSettings.expandPhotography);
        graphicsQuality.setSelection(presentationPosition(PresentationSettings.QUALITY, presentationSettings.quality));
        targetFps.setSelection(presentationPosition(PresentationSettings.TARGET_FPS, presentationSettings.targetFps));
        int scalePosition = 0;
        while (Double.compare(PresentationSettings.RENDER_SCALE[scalePosition], presentationSettings.renderScale) != 0) {
            scalePosition++;
        }
        renderScale.setSelection(scalePosition);
        maxBufferPixel.setSelection(presentationPosition(PresentationSettings.MAX_BUFFER_PIXEL, presentationSettings.maxBufferPixel));
        antiAliasing.setSelection(presentationPosition(PresentationSettings.ANTI_ALIASING, presentationSettings.antiAliasing));
        shadowResolution.setSelection(presentationPosition(PresentationSettings.SHADOW_RESOLUTION, presentationSettings.shadowResolution));
        for (Spinner spinner : presentationSpinners()) spinner.setEnabled(presentationSettings.customGraphics);
        presentationLoading = false;
    }

    private static int presentationPosition(int[] choices, int value) {
        for (int index = 0; index < choices.length; index++) if (choices[index] == value) return index;
        return 0;
    }

    private void savePresentationControls() {
        if (presentationLoading) return;
        PresentationSettings requested = new PresentationSettings(presentationSettings.revision,
                customGraphics.isChecked(), PresentationSettings.QUALITY[graphicsQuality.getSelectedItemPosition()],
                PresentationSettings.TARGET_FPS[targetFps.getSelectedItemPosition()],
                PresentationSettings.RENDER_SCALE[renderScale.getSelectedItemPosition()],
                PresentationSettings.MAX_BUFFER_PIXEL[maxBufferPixel.getSelectedItemPosition()],
                PresentationSettings.ANTI_ALIASING[antiAliasing.getSelectedItemPosition()],
                PresentationSettings.SHADOW_RESOLUTION[shadowResolution.getSelectedItemPosition()],
                expandPhotography.isChecked());
        if (presentationSettings.sameValues(requested)) return;
        try {
            presentationSettings = requested.save(getFilesDir());
            presentationSaveFailed = false;
            presentationInvalid = false;
            for (Spinner spinner : presentationSpinners()) spinner.setEnabled(presentationSettings.customGraphics);
        } catch (IOException error) {
            presentationSaveFailed = true;
            restorePresentationControls();
            Toast.makeText(this, R.string.presentation_save_failed, Toast.LENGTH_LONG).show();
        }
        updatePresentationStatus();
    }

    private void updatePresentationStatus() {
        if (presentationSaveFailed) {
            setTextIfChanged(presentationStatus, getString(R.string.presentation_save_failed));
            presentationStatus.setTextColor(Color.rgb(255, 192, 154));
            return;
        }
        if (presentationInvalid) {
            setTextIfChanged(presentationStatus, getString(R.string.presentation_invalid));
            presentationStatus.setTextColor(Color.rgb(255, 192, 154));
            return;
        }
        JSONObject client = !presentationObserved || !presentationServerRunning || presentationRuntime == null
                ? null : presentationRuntime.optJSONObject("client");
        if (client != null) {
            String state = client.optString("status", "waiting");
            boolean currentRevision = client.optLong("revision", -1) == presentationSettings.revision;
            int message = 0;
            if (currentRevision && "applied".equals(state)) message = R.string.presentation_applied;
            else if (currentRevision && "disabled".equals(state)) message = R.string.presentation_disabled;
            else if ("unsupported".equals(state)) message = R.string.presentation_unsupported;
            else if ("waiting_for_scene".equals(state)) message = R.string.presentation_waiting_for_scene;
            else if ("init_failed".equals(state)) message = R.string.presentation_init_failed;
            if (message != 0) {
                setTextIfChanged(presentationStatus, getString(message));
                presentationStatus.setTextColor("applied".equals(state) || "disabled".equals(state)
                        ? Color.rgb(117, 226, 177) : "unsupported".equals(state) || "init_failed".equals(state)
                        ? Color.rgb(255, 192, 154) : Color.rgb(192, 212, 222));
                return;
            }
        }
        setTextIfChanged(presentationStatus, getString(presentationSettings.revision > 0
                ? R.string.presentation_saved_waiting : R.string.presentation_waiting));
        presentationStatus.setTextColor(Color.rgb(192, 212, 222));
    }

    private void launchClient(int missingMessage, String... packageNames) {
        Intent client = null;
        for (String packageName : packageNames) {
            client = getPackageManager().getLaunchIntentForPackage(packageName);
            if (client != null) break;
        }
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
        presentationObserved = true;
        ServerService.observe(this);
    }

    @Override protected void onResume() {
        super.onResume();
        refreshPresentationInstallation();
    }

    @Override protected void onStop() {
        presentationObserved = false;
        presentationRuntime = null;
        updatePresentationStatus();
        ServerService.removeObserver(this);
        super.onStop();
    }

    @Override public void onServerChanged(String value, boolean running, boolean busy, List<String> lines, String detailsJson) {
        presentationServerRunning = running;
        status.setText(value);
        status.setTextColor(running ? Color.rgb(117, 226, 177) : Color.WHITE);
        start.setEnabled(!running && !busy);
        experimentalMainLive.setEnabled(!running && !busy);
        downloadMissingResources.setEnabled(!running && !busy);
        mediaMode.setEnabled(!running && !busy);
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
        presentationRuntime = details.optJSONObject("presentation");
        updatePresentationStatus();
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
        updateResources(details);
    }

    private void updateResources(JSONObject details) {
        JSONObject resources = details.optJSONObject("resource_transfer");
        boolean available = resources != null && resources.optBoolean("available", false);
        if (!available) {
            boolean missing = resources != null || details.optBoolean("running", false);
            setTextIfChanged(resourceStatus, getString(missing
                    ? R.string.resource_transfer_unavailable : R.string.resource_transfer_waiting));
            resourceStatus.setTextColor(Color.rgb(192, 212, 222));
            resourceReceived.setVisibility(View.GONE);
            resourceServed.setVisibility(View.GONE);
            return;
        }
        String resourceState = resources.optString("status", "idle");
        int active = Math.max(0, resources.optInt("active_requests", 0));
        boolean allowDownloads = resources.optBoolean("allow_downloads", false);
        String summary;
        if ("failed".equals(resourceState)) {
            summary = getString(R.string.resource_transfer_failed);
        } else if ("downloading".equals(resourceState)) {
            summary = active > 0 ? getString(R.string.resource_transfer_active, active)
                    : getString(R.string.resource_transfer_downloading);
        } else if ("ready".equals(resourceState)) {
            summary = getString(R.string.resource_transfer_ready);
        } else {
            summary = getString(allowDownloads
                    ? R.string.resource_transfer_idle : R.string.resource_transfer_cache_only);
        }
        setTextIfChanged(resourceStatus, summary);
        resourceStatus.setTextColor("failed".equals(resourceState)
                ? Color.rgb(255, 192, 154) : Color.rgb(192, 212, 222));
        long received = Math.max(0, resources.optLong("session_received_bytes", 0));
        long verified = Math.max(0, resources.optLong("session_verified_files", 0));
        long served = Math.max(0, resources.optLong("session_served_bytes", 0));
        // These are measured session totals for different links, not a combined
        // percentage or proof that all of the game's resources are downloaded.
        setTextIfChanged(resourceReceived, getString(R.string.resource_transfer_received,
                formatBytes(received), verified));
        setTextIfChanged(resourceServed, getString(R.string.resource_transfer_served, formatBytes(served)));
        resourceReceived.setVisibility(View.VISIBLE);
        resourceServed.setVisibility(View.VISIBLE);
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
