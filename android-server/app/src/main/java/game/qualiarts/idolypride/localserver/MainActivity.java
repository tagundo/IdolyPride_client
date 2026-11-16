package game.qualiarts.idolypride.localserver;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.SystemClock;
import android.net.Uri;
import android.provider.DocumentsContract;
import android.provider.Settings;
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
import java.io.File;
import org.json.JSONObject;

/** Native controls for a server contained entirely in this installed app. */
public final class MainActivity extends Activity implements ServerService.Observer {
    static final String SERVER_PREFS = "local_server";
    static final String EXPERIMENTAL_MAIN_LIVE = "experimental_main_live";
    static final String DOWNLOAD_MISSING_RESOURCES = "download_missing_resources";
    static final String MEDIA_MODE = "media_mode";
    static final String RESOURCE_PUBLIC_DOWNLOADS = "resource_public_downloads";
    static final String RESOURCE_DOWNLOAD_PARALLELISM = "resource_download_parallelism";

    private static final int EXPORT_ACCOUNT = 50055, IMPORT_ACCOUNT = 50056;
    private final java.util.ArrayList<Button> accountButtons = new java.util.ArrayList<>();
    private org.json.JSONArray accountRows = new org.json.JSONArray(), restoreRows = new org.json.JSONArray();
    private JSONObject accountStatus = new JSONObject(), activeAccount = new JSONObject(), durableHistory = new JSONObject();
    private JSONObject pendingAccountExport, pendingAccountPreview;
    private Spinner accountPicker, restorePicker;
    private TextView accountOverview, accountPage, restorePage, accountOperation, serverChecks, durableFailure;
    private Button accountPrevious, accountNext, restoreNext, restoreAccount;
    private ProgressBar accountProgress;
    private int accountOffset, restoreOffset;
    private boolean accountLifecycleBusy, accountDialogOpen;

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
    private static final int EXPORT_RESOURCES = 50053, IMPORT_RESOURCES = 50054;
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
    private PlaybackSettings playbackSettings;
    private CheckBox waitForOrientation;
    private TextView playbackStatus;
    private boolean playbackLoading, playbackInvalid, playbackSaveFailed, playbackRuntimeRunning;
    private JSONObject playbackRuntime;
    private CheckBox multithreadedRendering;
    private TextView renderingStatus;
    private JSONObject renderProbeRuntime;
    private boolean renderProbeRuntimeRunning;
    private LibrarySettings librarySettings;
    private boolean libraryLoading, libraryInvalid, librarySaveFailed;
    private boolean libraryInvalidLanguage, libraryInvalidMedia;
    private Spinner libraryLanguage, libraryMvSort, libraryOutfitSort, resourcePlatform, resourceParallelism;
    private CheckBox hideVideoMv;
    private TextView libraryStatus, libraryTransferStatus;
    private Button downloadLibrary, importLibrary, exportLibrary, cancelLibrary;
    private ProgressBar libraryProgress;
    private String currentLibraryJob, pendingResourcePlatform;
    private Spinner resourceStorage;
    private TextView resourceStorageNotice;
    private boolean retryStartAfterStoragePermission;
    private final Runnable playbackRefresh = new Runnable() {
        @Override public void run() {
            updatePlaybackStatus();
            updateRenderingStatus();
            if (presentationObserved && playbackStatus != null) playbackStatus.postDelayed(this, 1000);
        }
    };

    private static final int PAGE_BACKGROUND = 0xfff3f5fc;
    private static final int CARD_BACKGROUND = 0xffffffff;
    private static final int STATUS_BACKGROUND = 0xffe9eefc;
    private static final int CONTROL_BACKGROUND = 0xffe8edf7;
    private static final int TEXT_PRIMARY = 0xff192337;
    private static final int TEXT_MUTED = 0xff566478;
    private static final int ACCENT = 0xff3454d1;
    private static final int SUCCESS = 0xff157f3d;
    private static final int WARNING = 0xffa34f0d;
    private static final int[][] ENABLED_STATES = {{-android.R.attr.state_enabled}, {}};

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private TextView sectionTitle(int label) {
        TextView title = text(label, 20, TEXT_PRIMARY);
        title.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        title.setPadding(0, 0, 0, dp(12));
        if (Build.VERSION.SDK_INT >= 28) title.setAccessibilityHeading(true);
        return title;
    }

    private LinearLayout card(LinearLayout parent, int title) {
        LinearLayout result = new LinearLayout(this);
        result.setOrientation(LinearLayout.VERTICAL);
        result.setPadding(dp(16), dp(16), dp(16), dp(16));
        GradientDrawable surface = new GradientDrawable();
        surface.setColor(CARD_BACKGROUND);
        surface.setCornerRadius(dp(16));
        surface.setStroke(dp(1), 0xffdee4f0);
        result.setBackground(surface);
        LinearLayout.LayoutParams placement = new LinearLayout.LayoutParams(-1, -2);
        placement.setMargins(0, 0, 0, dp(16));
        parent.addView(result, placement);
        if (title != 0) result.addView(sectionTitle(title));
        return result;
    }

    private void primaryButton(Button control) {
        control.setBackgroundTintList(new ColorStateList(ENABLED_STATES,
                new int[]{CONTROL_BACKGROUND, ACCENT}));
        control.setTextColor(new ColorStateList(ENABLED_STATES,
                new int[]{TEXT_MUTED, 0xffffffff}));
    }

    private void readableControls(View root) {
        if (root instanceof TextView) {
            TextView label = (TextView) root;
            float currentSp = label.getTextSize() / getResources().getDisplayMetrics().scaledDensity;
            if (currentSp < 16) label.setTextSize(16);
            label.setLineSpacing(dp(2), 1.1f);
        }
        if (root instanceof CheckBox) {
            CheckBox control = (CheckBox) root;
            control.setMinHeight(dp(48));
            control.setButtonTintList(new ColorStateList(ENABLED_STATES,
                    new int[]{TEXT_MUTED, ACCENT}));
        }
        if (root instanceof ViewGroup && !(root instanceof Spinner)) {
            ViewGroup group = (ViewGroup) root;
            for (int index = 0; index < group.getChildCount(); index++) readableControls(group.getChildAt(index));
        }
    }

    private TextView text(int resource, int size, int color) {
        TextView result = new TextView(this);
        result.setText(resource);
        result.setTextSize(Math.max(16, size));
        result.setLineSpacing(dp(2), 1.1f);
        result.setTextColor(color);
        return result;
    }

    private Button button(int label) {
        Button result = new Button(this);
        result.setText(label);
        result.setAllCaps(false);
        result.setTextSize(16);
        result.setMinHeight(dp(52));
        result.setPadding(dp(12), dp(8), dp(12), dp(8));
        result.setBackgroundTintList(ColorStateList.valueOf(CONTROL_BACKGROUND));
        result.setTextColor(new ColorStateList(ENABLED_STATES,
                new int[]{TEXT_MUTED, TEXT_PRIMARY}));
        return result;
    }

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (savedInstanceState != null) {
            pendingResourcePlatform = savedInstanceState.getString("resource_platform");
            retryStartAfterStoragePermission = savedInstanceState.getBoolean("storage_retry", false);
            accountOffset = Math.max(0, savedInstanceState.getInt("account_offset", 0));
            restoreOffset = Math.max(0, savedInstanceState.getInt("restore_offset", 0));
            try {
                String exported = savedInstanceState.getString("account_export"), preview = savedInstanceState.getString("account_preview");
                if (exported != null) pendingAccountExport = new JSONObject(exported);
                if (preview != null) pendingAccountPreview = new JSONObject(preview);
            } catch (org.json.JSONException invalid) { pendingAccountExport = null; pendingAccountPreview = null; }
        }
        getWindow().setStatusBarColor(PAGE_BACKGROUND);
        getWindow().setNavigationBarColor(PAGE_BACKGROUND);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR
                | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        boolean compact = getResources().getConfiguration().screenHeightDp < 520;
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(16), dp(compact ? 8 : 12), dp(16), dp(8));
        content.setBackgroundColor(PAGE_BACKGROUND);
        TextView heading = text(R.string.app_name, compact ? 20 : 25, TEXT_PRIMARY);
        heading.setText(getString(R.string.app_name) + "  " + BuildConfig.VERSION_NAME);
        heading.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        content.addView(heading);
        TextView description = text(R.string.server_description, 16, TEXT_MUTED);
        description.setPadding(0, dp(4), 0, dp(8));
        description.setVisibility(compact ? View.GONE : View.VISIBLE);
        content.addView(description);

        status = text(R.string.status_stopped, 21, TEXT_PRIMARY);
        status.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        status.setPadding(dp(14), dp(8), dp(14), dp(8));
        GradientDrawable background = new GradientDrawable();
        background.setColor(STATUS_BACKGROUND);
        background.setCornerRadius(dp(12));
        status.setBackground(background);
        content.addView(status, new LinearLayout.LayoutParams(-1, -2));

        LinearLayout controls = new LinearLayout(this);
        controls.setOrientation(LinearLayout.HORIZONTAL);
        start = button(R.string.start_server);
        primaryButton(start);
        stop = button(R.string.stop_server);
        LinearLayout.LayoutParams half = new LinearLayout.LayoutParams(0, -2, 1);
        half.setMargins(0, 0, dp(4), 0);
        controls.addView(start, half);
        LinearLayout.LayoutParams otherHalf = new LinearLayout.LayoutParams(0, -2, 1);
        otherHalf.setMargins(dp(4), 0, 0, 0);
        controls.addView(stop, otherHalf);
        content.addView(controls);
        Button launch = button(R.string.launch_diagnostic_client);
        primaryButton(launch);
        content.addView(launch, new LinearLayout.LayoutParams(-1, -2));

        // The settings scroll independently; the single game action stays visible.
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(0, dp(12), 0, 0);
        TextView automatic = text(R.string.settings_automatic_notice, 16, TEXT_MUTED);
        automatic.setPadding(dp(2), 0, dp(2), dp(12));
        body.addView(automatic);
        LinearLayout modeCard = card(body, R.string.mode_section_title);
        mediaMode = new CheckBox(this);
        mediaMode.setText(R.string.media_mode);
        mediaMode.setTextColor(TEXT_PRIMARY);
        mediaMode.setTextSize(13);
        mediaMode.setChecked(getSharedPreferences(SERVER_PREFS, MODE_PRIVATE)
                .getBoolean(MEDIA_MODE, false));
        mediaMode.setOnCheckedChangeListener((button, enabled) ->
                getSharedPreferences(SERVER_PREFS, MODE_PRIVATE).edit()
                        .putBoolean(MEDIA_MODE, enabled).apply());
        modeCard.addView(mediaMode);
        TextView mediaNotice = text(R.string.media_mode_notice, 12, TEXT_MUTED);
        mediaNotice.setPadding(0, 0, 0, dp(6));
        modeCard.addView(mediaNotice);
        TextView note = text(R.string.first_launch_note, 13, TEXT_MUTED);
        note.setPadding(0, dp(8), 0, dp(14));
        modeCard.addView(note);

        addServerChecksControls(card(body, R.string.server_checks_title));
        addAccountControls(card(body, R.string.accounts_title));

        LinearLayout libraryCard = card(body, 0);
        addLibraryControls(libraryCard);

        LinearLayout experimentCard = card(body, R.string.experiment_section_title);
        experimentalMainLive = new CheckBox(this);
        experimentalMainLive.setText(R.string.experimental_main_live);
        experimentalMainLive.setTextColor(TEXT_PRIMARY);
        experimentalMainLive.setTextSize(13);
        experimentalMainLive.setChecked(getSharedPreferences(SERVER_PREFS, MODE_PRIVATE)
                .getBoolean(EXPERIMENTAL_MAIN_LIVE, false));
        experimentalMainLive.setOnCheckedChangeListener((button, enabled) ->
                getSharedPreferences(SERVER_PREFS, MODE_PRIVATE).edit()
                        .putBoolean(EXPERIMENTAL_MAIN_LIVE, enabled).apply());
        experimentCard.addView(experimentalMainLive);
        TextView liveNotice = text(R.string.experimental_main_live_notice, 12, TEXT_MUTED);
        experimentCard.addView(liveNotice);
        TextView replayNotice = text(R.string.tutorial_replay_notice, 16, TEXT_MUTED);
        replayNotice.setPadding(0, dp(6), 0, dp(8));
        experimentCard.addView(replayNotice);
        addRenderingExperiment(experimentCard);

        LinearLayout graphicsCard = card(body, 0);
        addPresentationControls(graphicsCard);
        LinearLayout playbackCard = card(body, R.string.playback_section_title);
        addPlaybackControls(playbackCard);

        LinearLayout resourcesCard = card(body, R.string.resources_section_title);
        addResourceStorageControls(resourcesCard);
        downloadMissingResources = new CheckBox(this);
        downloadMissingResources.setText(R.string.download_missing_resources);
        downloadMissingResources.setTextColor(TEXT_PRIMARY);
        downloadMissingResources.setTextSize(13);
        downloadMissingResources.setChecked(getSharedPreferences(SERVER_PREFS, MODE_PRIVATE)
                .getBoolean(DOWNLOAD_MISSING_RESOURCES, true));
        downloadMissingResources.setOnCheckedChangeListener((button, enabled) ->
                getSharedPreferences(SERVER_PREFS, MODE_PRIVATE).edit()
                        .putBoolean(DOWNLOAD_MISSING_RESOURCES, enabled).apply());
        resourcesCard.addView(downloadMissingResources);
        TextView resourceNotice = text(R.string.download_missing_resources_notice, 12, TEXT_MUTED);
        resourceNotice.setPadding(0, 0, 0, dp(6));
        resourcesCard.addView(resourceNotice);
        TextView resourceHeading = text(R.string.resource_transfer_title, 15, TEXT_PRIMARY);
        resourceHeading.setPadding(0, dp(10), 0, dp(4));
        resourcesCard.addView(resourceHeading);
        resourceStatus = text(R.string.resource_transfer_waiting, 12, TEXT_MUTED);
        resourceStatus.setTextIsSelectable(true);
        resourcesCard.addView(resourceStatus);
        resourceReceived = text(R.string.resource_transfer_waiting, 12, TEXT_MUTED);
        resourceReceived.setTextIsSelectable(true);
        resourceReceived.setVisibility(View.GONE);
        resourcesCard.addView(resourceReceived);
        resourceServed = text(R.string.resource_transfer_waiting, 12, TEXT_MUTED);
        resourceServed.setTextIsSelectable(true);
        resourceServed.setVisibility(View.GONE);
        resourcesCard.addView(resourceServed);
        addResourceLibraryControls(resourcesCard);

        LinearLayout diagnosticsCard = card(body, R.string.diagnostics_section_title);
        gameStatus = text(R.string.game_state_waiting, 13, TEXT_MUTED);
        gameStatus.setTextIsSelectable(true);
        gameStatus.setMaxLines(3);
        gameStatus.setEllipsize(TextUtils.TruncateAt.END);
        gameStatus.setPadding(0, dp(4), 0, dp(8));
        diagnosticsCard.addView(gameStatus);
        lastException = text(R.string.game_state_waiting, 12, WARNING);
        lastException.setTextIsSelectable(true);
        lastException.setMaxLines(3);
        lastException.setEllipsize(TextUtils.TruncateAt.END);
        lastException.setVisibility(View.GONE);
        diagnosticsCard.addView(lastException);
        export = button(R.string.export_diagnostics);
        diagnosticsCard.addView(export, new LinearLayout.LayoutParams(-1, -2));
        TextView exportNotice = text(R.string.diagnostics_export_notice, 16, TEXT_MUTED);
        exportNotice.setPadding(0, dp(4), 0, dp(8));
        diagnosticsCard.addView(exportNotice);
        Button detailsHeading = button(R.string.diagnostics_details);
        diagnosticsCard.addView(detailsHeading, new LinearLayout.LayoutParams(-1, -2));
        LinearLayout diagnosticDetails = new LinearLayout(this);
        diagnosticDetails.setOrientation(LinearLayout.VERTICAL);
        diagnosticDetails.setPadding(0, dp(8), 0, 0);
        diagnosticDetails.setVisibility(View.GONE);
        diagnosticsCard.addView(diagnosticDetails, new LinearLayout.LayoutParams(-1, -2));
        detailsHeading.setOnClickListener(view -> {
            boolean expanded = diagnosticDetails.getVisibility() != View.VISIBLE;
            diagnosticDetails.setVisibility(expanded ? View.VISIBLE : View.GONE);
            detailsHeading.setText(expanded ? R.string.diagnostics_details_expanded : R.string.diagnostics_details);
        });
        TextView ports = text(R.string.server_ports, 16, TEXT_MUTED);
        ports.setPadding(0, 0, 0, dp(8));
        diagnosticDetails.addView(ports);
        networkStatus = text(R.string.game_network_waiting, 12, TEXT_MUTED);
        networkStatus.setTextIsSelectable(true);
        networkStatus.setPadding(0, dp(4), 0, dp(8));
        diagnosticDetails.addView(networkStatus);
        transferStatus = text(R.string.master_transfer_waiting, 12, TEXT_MUTED);
        diagnosticDetails.addView(transferStatus);
        transferProgress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        transferProgress.setMax(1000);
        transferProgress.setVisibility(View.GONE);
        diagnosticDetails.addView(transferProgress, new LinearLayout.LayoutParams(-1, dp(12)));
        diagnosticDetails.addView(sectionTitle(R.string.server_logs));
        logs = text(R.string.waiting_logs, 12, TEXT_MUTED);
        logs.setTypeface(Typeface.MONOSPACE);
        logs.setTextIsSelectable(true);
        logs.setPadding(0, dp(8), 0, dp(16));
        logScroll = new ScrollView(this);
        logScroll.addView(logs);
        logScroll.setNestedScrollingEnabled(true);
        diagnosticDetails.addView(logScroll, new LinearLayout.LayoutParams(-1, dp(220)));
        ScrollView detailsScroll = new ScrollView(this);
        detailsScroll.setFillViewport(true);
        detailsScroll.addView(body, new ScrollView.LayoutParams(-1, -2));
        content.addView(detailsScroll, new LinearLayout.LayoutParams(-1, 0, 1));
        readableControls(content);
        setContentView(content);

        start.setOnClickListener(view -> requestServerStart());
        stop.setOnClickListener(view -> startService(new Intent(this, ServerService.class).setAction(ServerService.ACTION_STOP)));
        launch.setOnClickListener(view -> launchClient(R.string.diagnostic_client_missing,
                "game.qualiarts.idolypride.local.diagnostics"));
        export.setOnClickListener(view -> requestDiagnosticsExport());
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 50051);
        }
    }


    private Button accountButton(LinearLayout body, int label, String identifier, View.OnClickListener listener) {
        Button control = button(label); control.setContentDescription(identifier);
        control.setOnClickListener(listener); accountButtons.add(control);
        body.addView(control, new LinearLayout.LayoutParams(-1, -2)); return control;
    }

    private void addAccountControls(LinearLayout body) {
        TextView notice = text(R.string.accounts_notice, 16, TEXT_MUTED); body.addView(notice);
        accountOverview = text(R.string.accounts_waiting, 16, TEXT_PRIMARY); accountOverview.setTextIsSelectable(true); body.addView(accountOverview);
        accountPicker = new Spinner(this); accountPicker.setContentDescription("idoly.accounts.list");
        body.addView(accountPicker, new LinearLayout.LayoutParams(-1, dp(52)));
        accountPicker.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, View view, int position, long id) { updateAccountControls(); }
            @Override public void onNothingSelected(AdapterView<?> parent) {}
        });
        accountPage = text(R.string.accounts_waiting, 16, TEXT_MUTED); body.addView(accountPage);
        accountPrevious = accountButton(body, R.string.accounts_previous, "idoly.accounts.previous", view -> {
            accountOffset = Math.max(0, accountOffset - 24); refreshAccounts();
        });
        accountNext = accountButton(body, R.string.accounts_next, "idoly.accounts.next", view -> {
            int next = accountStatus.optInt("next_offset", -1); if (next >= 0) { accountOffset = next; refreshAccounts(); }
        });
        accountButton(body, R.string.accounts_refresh, "idoly.accounts.refresh", view -> refreshAccounts());
        accountButton(body, R.string.accounts_create, "idoly.accounts.create", view -> showAccountNameDialog("create", null));
        accountButton(body, R.string.accounts_clone, "idoly.accounts.clone", view -> {
            JSONObject source = selectedAccount(); if (source != null) showAccountNameDialog("clone", source); else accountChooseNotice();
        });
        accountButton(body, R.string.accounts_select, "idoly.accounts.select", view -> {
            JSONObject row = selectedAccount(); if (row == null) { accountChooseNotice(); return; }
            performAccount("accounts_select", accountPayload("mode", row.optString("mode"), "profile", row.optString("profile"),
                    "expected_revision", row.optString("revision"), "selection_revision", accountStatus.optString("selection_revision")));
        });
        accountButton(body, R.string.accounts_export, "idoly.accounts.export", view -> {
            JSONObject row = selectedAccount(); if (row == null) { accountChooseNotice(); return; }
            if (pendingAccountExport != null) ServerService.discardAccountDocument(getApplicationContext(), pendingAccountExport.optString("path"));
            pendingAccountExport = null;
            performAccount("accounts_export", accountPayload("mode", row.optString("mode"), "profile", row.optString("profile"),
                    "expected_revision", row.optString("revision")));
        });
        accountButton(body, R.string.accounts_import, "idoly.accounts.import", view -> {
            if (pendingAccountPreview != null) { showAccountImportChoices(); return; }
            Intent picker = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION).setType("application/zip")
                    .putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"application/zip", "application/x-zip-compressed", "application/octet-stream"});
            try { startActivityForResult(picker, IMPORT_ACCOUNT); }
            catch (RuntimeException error) { accountError("account_picker_unavailable"); }
        });
        body.addView(text(R.string.accounts_restore_notice, 16, TEXT_MUTED));
        restorePicker = new Spinner(this); restorePicker.setContentDescription("idoly.accounts.restore-list");
        body.addView(restorePicker, new LinearLayout.LayoutParams(-1, dp(52)));
        restorePage = text(R.string.accounts_restore_empty, 16, TEXT_MUTED); body.addView(restorePage);
        restoreNext = accountButton(body, R.string.accounts_restore_next, "idoly.accounts.restore-next", view -> {
            int next = accountStatus.optInt("next_restore_offset", -1);
            restoreOffset = next >= 0 ? next : 0; refreshAccounts();
        });
        restoreAccount = accountButton(body, R.string.accounts_restore, "idoly.accounts.restore", view -> requestAccountRestore());
        accountProgress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        accountProgress.setIndeterminate(true); accountProgress.setVisibility(View.GONE);
        body.addView(accountProgress, new LinearLayout.LayoutParams(-1, dp(12)));
        accountOperation = text(R.string.accounts_ready, 16, TEXT_MUTED);
        accountOperation.setTextIsSelectable(true); accountOperation.setContentDescription("idoly.accounts.result");
        body.addView(accountOperation); updateAccountControls();
    }

    private void addServerChecksControls(LinearLayout body) {
        serverChecks = text(R.string.server_checks_waiting, 16, TEXT_MUTED); serverChecks.setTextIsSelectable(true); body.addView(serverChecks);
        durableFailure = text(R.string.server_history_empty, 16, TEXT_MUTED); durableFailure.setTextIsSelectable(true); body.addView(durableFailure);
        Button refresh = button(R.string.server_checks_refresh); refresh.setContentDescription("idoly.settings.refresh");
        refresh.setOnClickListener(view -> performAccount("server_settings_status", new JSONObject())); body.addView(refresh);
        Button history = button(R.string.server_history_view); history.setOnClickListener(view -> {
            TextView content = text(R.string.server_history_empty, 16, TEXT_PRIMARY);
            try { content.setText(durableHistory.toString(2)); } catch (org.json.JSONException ignored) { content.setText(R.string.server_history_empty); } content.setTextIsSelectable(true); content.setPadding(dp(16), dp(12), dp(16), dp(12));
            ScrollView scroll = new ScrollView(this); scroll.addView(content);
            new AlertDialog.Builder(this).setTitle(R.string.server_history_view).setView(scroll)
                    .setPositiveButton(R.string.accounts_confirm, null).show();
        }); body.addView(history);
        Button clear = button(R.string.server_history_clear); clear.setOnClickListener(view ->
                new AlertDialog.Builder(this).setTitle(R.string.server_history_clear).setMessage(R.string.server_history_clear_confirm)
                        .setNegativeButton(R.string.accounts_cancel, null)
                        .setPositiveButton(R.string.accounts_confirm, (dialog, which) -> performAccount("server_history_clear", new JSONObject())).show());
        body.addView(clear);
    }

    private static JSONObject accountPayload(Object... pairs) {
        JSONObject value = new JSONObject();
        try { for (int index = 0; index < pairs.length; index += 2)
            value.put((String) pairs[index], pairs[index + 1] == null ? JSONObject.NULL : pairs[index + 1]); }
        catch (org.json.JSONException impossible) { throw new IllegalArgumentException(impossible); }
        return value;
    }

    private JSONObject selectedAccount() {
        return accountPicker == null ? null : accountRows.optJSONObject(accountPicker.getSelectedItemPosition());
    }

    private void accountChooseNotice() { Toast.makeText(this, R.string.accounts_choose, Toast.LENGTH_LONG).show(); }

    private void refreshAccounts() {
        performAccount("accounts_status", accountPayload("offset", accountOffset, "restore_offset", restoreOffset));
    }

    private void performAccount(String action, JSONObject payload) {
        if (ServerService.isManagingAccounts()) return;
        accountOperation.setText(R.string.accounts_working); accountOperation.setTextColor(TEXT_MUTED);
        ServerService.manageAccounts(getApplicationContext(), action, payload, accountCallback(action));
        updateAccountControls();
    }

    private ServerService.AccountCallback accountCallback(String action) {
        return new ServerService.AccountCallback() {
            @Override public void progress(String phase, long bytes, long total) {
                if (isFinishing() || isDestroyed()) return;
                accountProgress.setVisibility(View.VISIBLE); accountProgress.setIndeterminate(total <= 0);
                if ("preparing".equals(phase)) { accountOperation.setText(R.string.accounts_preparing); return; }
                if (total > 0) { accountProgress.setMax(1000); accountProgress.setProgress((int) Math.min(1000, bytes * 1000 / total)); }
                accountOperation.setText(getString(total > 0 ? R.string.accounts_transfer_total : R.string.accounts_transfer,
                        getString("saving".equals(phase) ? R.string.accounts_transfer_saving : R.string.accounts_transfer_copying),
                        formatBytes(bytes), formatBytes(Math.max(0, total))));
            }
            @Override public void completed(JSONObject result) {
                if (isFinishing() || isDestroyed()) {
                    if ("accounts_export".equals(action) && result.optBoolean("ok", false))
                        ServerService.discardAccountDocument(getApplicationContext(), result.optString("path"));
                    return;
                }
                applyAccountResult(action, result); updateAccountControls();
            }
        };
    }

    private void applyAccountResult(String action, JSONObject result) {
        if (!result.optBoolean("ok", false)) { accountError(result.optString("error", "account_operation_failed")); return; }
        JSONObject active = result.optJSONObject("active"); if (active != null) activeAccount = active;
        JSONObject values = result.optJSONObject("status"); if (values != null) renderAccounts(values);
        JSONObject settings = result.optJSONObject("settings"); if (settings != null) renderServerChecks(settings);
        accountOperation.setTextColor(SUCCESS); accountOperation.setText(R.string.accounts_complete);
        if ("accounts_select".equals(action)) {
            accountOperation.setText(R.string.accounts_selected);
        } else if ("accounts_export".equals(action)) {
            pendingAccountExport = accountPayload("path", result.optString("path"), "filename", result.optString("filename"),
                    "bytes", result.optLong("bytes", -1), "sha256", result.optString("sha256"));
            Intent picker = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                    .addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION).setType("application/zip")
                    .putExtra(Intent.EXTRA_TITLE, result.optString("filename", "IdolyPride-Account.zip"));
            try { startActivityForResult(picker, EXPORT_ACCOUNT); }
            catch (RuntimeException error) { accountError("account_picker_unavailable"); }
        } else if ("accounts_preview".equals(action)) {
            pendingAccountPreview = accountPayload("token", result.optString("token"), "archive", result.optJSONObject("archive"));
            showAccountImportChoices();
        } else if ("accounts_import".equals(action) || "accounts_restore".equals(action)) {
            pendingAccountPreview = null; accountOperation.setText(R.string.accounts_restored);
        } else if ("accounts_save_document".equals(action)) {
            pendingAccountExport = null; accountOperation.setText(R.string.accounts_exported);
        } else if ("accounts_status".equals(action)) {
            accountOperation.setText(R.string.accounts_ready);
            if (pendingAccountPreview != null && !accountDialogOpen) showAccountImportChoices();
        }
        renderAccountOverview();
    }

    private void renderAccounts(JSONObject value) {
        JSONObject selected = selectedAccount();
        String previousMode = selected == null ? "" : selected.optString("mode");
        String previousProfile = selected == null ? "" : selected.optString("profile");
        if (previousProfile.isEmpty()) {
            previousMode = activeAccount.optBoolean("running", false) ? activeAccount.optString("mode") : mediaMode.isChecked() ? "media" : "normal";
            JSONObject queued = value.optJSONObject("selected");
            previousProfile = activeAccount.optBoolean("running", false) ? activeAccount.optString("profile")
                    : queued == null ? "sandbox" : queued.optString(previousMode, "sandbox");
        }
        accountStatus = value; accountOffset = value.optInt("offset", 0); restoreOffset = value.optInt("restore_offset", 0);
        accountRows = value.optJSONArray("accounts"); if (accountRows == null) accountRows = new org.json.JSONArray();
        restoreRows = value.optJSONArray("restore_points"); if (restoreRows == null) restoreRows = new org.json.JSONArray();
        java.util.ArrayList<String> names = new java.util.ArrayList<>(); int selection = 0;
        for (int index = 0; index < accountRows.length(); index++) {
            JSONObject row = accountRows.optJSONObject(index); if (row == null) continue;
            names.add(accountMode(row.optString("mode")) + " · " + row.optString("profile")
                    + (row.optBoolean("has_snapshot", false) ? "" : " · " + getString(R.string.accounts_unprepared)));
            if (previousMode.equals(row.optString("mode")) && previousProfile.equals(row.optString("profile"))) selection = index;
        }
        if (names.isEmpty()) names.add(getString(R.string.accounts_empty));
        accountPicker.setAdapter(new ArrayAdapter<String>(this, android.R.layout.simple_spinner_dropdown_item, names));
        accountPicker.setSelection(selection);
        names = new java.util.ArrayList<>();
        for (int index = 0; index < restoreRows.length(); index++) {
            JSONObject row = restoreRows.optJSONObject(index); if (row != null)
                names.add(accountMode(row.optString("mode")) + " · " + row.optString("profile") + " · " + accountDate(row.optLong("created_at", 0)));
        }
        if (names.isEmpty()) names.add(getString(R.string.accounts_restore_empty));
        restorePicker.setAdapter(new ArrayAdapter<String>(this, android.R.layout.simple_spinner_dropdown_item, names));
        accountPage.setText(getString(R.string.accounts_page, accountRows.length() == 0 ? 0 : accountOffset + 1,
                accountOffset + accountRows.length(), value.optInt("accounts_total", accountRows.length())));
        restorePage.setText(getString(R.string.accounts_restore_page, restoreRows.length() == 0 ? 0 : restoreOffset + 1,
                restoreOffset + restoreRows.length(), value.optInt("restore_points_total", restoreRows.length())));
        renderAccountOverview(); updateAccountControls();
    }

    private String accountDate(long timestamp) {
        if (timestamp <= 0) return getString(R.string.accounts_date_unknown);
        return java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.MEDIUM, java.text.DateFormat.SHORT)
                .format(new java.util.Date(timestamp));
    }

    private String accountDate(String timestamp) {
        try { return accountDate(java.time.Instant.parse(timestamp).toEpochMilli()); }
        catch (RuntimeException invalid) { return getString(R.string.accounts_date_unknown); }
    }

    private String accountMode(String value) { return getString("media".equals(value) ? R.string.accounts_media : R.string.accounts_normal); }

    private void renderAccountOverview() {
        if (accountOverview == null) return;
        JSONObject selected = accountStatus.optJSONObject("selected");
        String selection = selected == null ? getString(R.string.accounts_waiting)
                : getString(R.string.accounts_next_selection, selected.optString("normal", "sandbox"), selected.optString("media", "sandbox"));
        String active = activeAccount.optBoolean("running", false)
                ? getString(R.string.accounts_active, accountMode(activeAccount.optString("mode")), activeAccount.optString("profile"))
                : getString(R.string.accounts_not_running);
        accountOverview.setText(active + "\n" + selection);
    }

    private void updateAccountControls() {
        if (accountPicker == null) return;
        boolean busy = ServerService.isManagingAccounts() || accountLifecycleBusy;
        for (Button control : accountButtons) control.setEnabled(!busy);
        accountPicker.setEnabled(!busy && accountRows.length() > 0);
        restorePicker.setEnabled(!busy && restoreRows.length() > 0);
        if (accountProgress != null) accountProgress.setVisibility(ServerService.isManagingAccounts() ? View.VISIBLE : View.GONE);
        accountPrevious.setEnabled(!busy && accountOffset > 0);
        accountNext.setEnabled(!busy && accountStatus.optInt("next_offset", -1) >= 0);
        restoreNext.setEnabled(!busy && (restoreOffset > 0 || accountStatus.optInt("next_restore_offset", -1) >= 0));
        restoreAccount.setEnabled(!busy && restoreRows.length() > 0 && accountRows.length() > 0);
    }

    private void showAccountNameDialog(String kind, JSONObject source) {
        LinearLayout fields = new LinearLayout(this); fields.setOrientation(LinearLayout.VERTICAL); fields.setPadding(dp(20), dp(8), dp(20), 0);
        if ("clone".equals(kind)) fields.addView(text(R.string.accounts_clone_notice, 16, TEXT_MUTED));
        android.widget.EditText profile = new android.widget.EditText(this);
        profile.setSingleLine(true); profile.setHint(R.string.accounts_profile_hint); profile.setContentDescription("idoly.accounts.profile-input");
        fields.addView(profile);
        android.widget.EditText manager = new android.widget.EditText(this);
        manager.setSingleLine(true); manager.setHint(R.string.accounts_manager_hint); manager.setText(R.string.accounts_manager_default);
        manager.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(10)});
        manager.setContentDescription("idoly.accounts.manager-input");
        Spinner mode = new Spinner(this); mode.setContentDescription("idoly.accounts.mode-input");
        mode.setAdapter(new ArrayAdapter<String>(this, android.R.layout.simple_spinner_dropdown_item,
                new String[]{getString(R.string.accounts_normal), getString(R.string.accounts_media)}));
        mode.setSelection(mediaMode.isChecked() ? 1 : 0);
        if ("create".equals(kind)) { fields.addView(manager); fields.addView(mode); }
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle("clone".equals(kind) ? R.string.accounts_clone : R.string.accounts_create)
                .setView(fields).setNegativeButton(R.string.accounts_cancel, null).setPositiveButton(R.string.accounts_confirm, null).create();
        dialog.setOnShowListener(ignored -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(view -> {
            String name = profile.getText().toString().trim();
            if (name.isEmpty()) { profile.setError(getString(R.string.accounts_profile_required)); return; }
            dialog.dismiss();
            if ("clone".equals(kind) && source != null)
                performAccount("accounts_clone", accountPayload("mode", source.optString("mode"), "source_profile", source.optString("profile"),
                        "profile", name, "expected_revision", source.optString("revision")));
            else performAccount("accounts_create", accountPayload("mode", mode.getSelectedItemPosition() == 1 ? "media" : "normal",
                    "profile", name, "manager_name", manager.getText().toString()));
        })); dialog.show();
    }

    private void showAccountImportChoices() {
        if (pendingAccountPreview == null || accountDialogOpen) return;
        JSONObject archive = pendingAccountPreview.optJSONObject("archive");
        if (archive == null) { pendingAccountPreview = null; accountError("account_archive_invalid"); return; }
        JSONObject selected = selectedAccount();
        boolean replace = selected != null && archive.optString("mode").equals(selected.optString("mode"));
        LinearLayout preview = new LinearLayout(this); preview.setOrientation(LinearLayout.VERTICAL);
        preview.setPadding(dp(20), dp(8), dp(20), dp(8));
        String summary = accountMode(archive.optString("mode")) + " · " + archive.optString("profile")
                + "\n" + getString(R.string.accounts_archive_summary, archive.optLong("bytes", 0),
                archive.optJSONObject("counts") == null ? 0 : archive.optJSONObject("counts").optInt("main_live_attempts", 0),
                archive.optJSONObject("counts") == null ? 0 : archive.optJSONObject("counts").optInt("preference_receipts", 0));
        TextView details = text(R.string.accounts_import_preview, 16, TEXT_PRIMARY); details.setText(summary);
        details.setTextIsSelectable(true); preview.addView(details);
        Button create = button(R.string.accounts_import_new); create.setContentDescription("idoly.accounts.import-new"); preview.addView(create);
        Button overwrite = button(R.string.accounts_import_replace); overwrite.setContentDescription("idoly.accounts.import-replace");
        if (replace) preview.addView(overwrite);
        accountDialogOpen = true;
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle(R.string.accounts_import_preview).setView(preview)
                .setNegativeButton(R.string.accounts_cancel, (choice, which) -> pendingAccountPreview = null).create();
        create.setOnClickListener(view -> { dialog.dismiss(); requestNewAccountImport(archive); });
        overwrite.setOnClickListener(view -> { dialog.dismiss(); requestReplaceAccountImport(archive, selected); });
        dialog.setOnDismissListener(ignored -> accountDialogOpen = false); dialog.show();
    }

    private void requestNewAccountImport(JSONObject archive) {
        android.widget.EditText field = new android.widget.EditText(this); field.setSingleLine(true);
        field.setHint(R.string.accounts_profile_hint); field.setContentDescription("idoly.accounts.profile-input");
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle(R.string.accounts_import_new).setView(field)
                .setNegativeButton(R.string.accounts_cancel, null).setPositiveButton(R.string.accounts_confirm, null).create();
        dialog.setOnShowListener(ignored -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(view -> {
            String name = field.getText().toString().trim();
            if (name.isEmpty()) { field.setError(getString(R.string.accounts_profile_required)); return; }
            String token = pendingAccountPreview == null ? "" : pendingAccountPreview.optString("token");
            dialog.dismiss(); performAccount("accounts_import", accountPayload("token", token, "mode", archive.optString("mode"),
                    "profile", name, "replace", false, "expected_revision", null));
        })); dialog.show();
    }

    private boolean activeAccountTarget(String mode, String profile) {
        return activeAccount.optBoolean("running", false) && mode.equals(activeAccount.optString("mode"))
                && profile.equals(activeAccount.optString("profile"));
    }

    private void requestReplaceAccountImport(JSONObject archive, JSONObject selected) {
        String mode = selected.optString("mode"), profile = selected.optString("profile");
        if (activeAccountTarget(mode, profile)) { accountError("account_active_restart_required"); return; }
        new AlertDialog.Builder(this).setTitle(R.string.accounts_import_replace)
                .setMessage(getString(R.string.accounts_replace_confirm, accountMode(mode), profile))
                .setNegativeButton(R.string.accounts_cancel, null)
                .setPositiveButton(R.string.accounts_confirm, (dialog, which) -> performAccount("accounts_import", accountPayload(
                        "token", pendingAccountPreview == null ? "" : pendingAccountPreview.optString("token"),
                        "mode", mode, "profile", profile, "replace", true, "expected_revision", selected.optString("revision")))).show();
    }

    private void requestAccountRestore() {
        JSONObject point = restoreRows.optJSONObject(restorePicker.getSelectedItemPosition()), row = selectedAccount();
        if (point == null || row == null) { accountChooseNotice(); return; }
        if (!point.optString("mode").equals(row.optString("mode")) || !point.optString("profile").equals(row.optString("profile"))) {
            Toast.makeText(this, R.string.accounts_restore_choose_target, Toast.LENGTH_LONG).show(); return;
        }
        if (activeAccountTarget(row.optString("mode"), row.optString("profile"))) { accountError("account_active_restart_required"); return; }
        new AlertDialog.Builder(this).setTitle(R.string.accounts_restore).setMessage(getString(R.string.accounts_replace_confirm,
                accountMode(row.optString("mode")), row.optString("profile"))).setNegativeButton(R.string.accounts_cancel, null)
                .setPositiveButton(R.string.accounts_confirm, (dialog, which) -> performAccount("accounts_restore", accountPayload(
                        "id", point.optString("id"), "mode", row.optString("mode"), "profile", row.optString("profile"),
                        "expected_revision", row.optString("revision")))).show();
    }

    private void accountError(String code) {
        if (code == null || !code.matches("[a-z][a-z0-9_]{0,95}")) code = "account_operation_failed";
        accountOperation.setTextColor(WARNING);
        int message = "account_active_restart_required".equals(code) ? R.string.accounts_stop_to_restore
                : "account_archive_too_large".equals(code) ? R.string.accounts_too_large
                : "account_archive_empty".equals(code) ? R.string.accounts_empty_archive
                : "account_document_permission".equals(code) ? R.string.accounts_provider_permission : 0;
        accountOperation.setText(message == 0 ? getString(R.string.accounts_failed, code) : getString(message));
        updateAccountControls();
    }

    private String checkState(String state) {
        if ("ready".equals(state)) return getString(R.string.server_check_ready);
        if ("blocked".equals(state) || "missing".equals(state)) return getString(R.string.server_check_blocked);
        if ("attention".equals(state)) return getString(R.string.server_check_attention);
        if ("stopped".equals(state)) return getString(R.string.server_check_stopped);
        return getString(R.string.server_check_unchecked);
    }

    private String checkName(String id) {
        String[] ids = {"protocol", "catalog", "master", "storage", "http", "grpc", "resources", "account"};
        int[] names = {R.string.server_check_protocol, R.string.server_check_catalog, R.string.server_check_master, R.string.server_check_storage,
                R.string.server_check_http, R.string.server_check_grpc, R.string.server_check_resources, R.string.server_check_account};
        for (int index = 0; index < ids.length; index++) if (ids[index].equals(id)) return getString(names[index]);
        return getString(R.string.server_check_unknown);
    }

    private void renderServerChecks(JSONObject settings) {
        if (serverChecks == null) return;
        JSONObject checks = settings.optJSONObject("startup_checks");
        if (checks == null) { serverChecks.setText(R.string.server_checks_waiting); return; }
        String scope = checks.optString("scope", "not_run");
        StringBuilder message = new StringBuilder(getString("current_run".equals(scope) ? R.string.server_checks_current
                : "previous_run".equals(scope) ? R.string.server_checks_previous : R.string.server_checks_waiting));
        org.json.JSONArray items = checks.optJSONArray("checks");
        if (items != null) for (int index = 0; index < Math.min(items.length(), 16); index++) {
            JSONObject row = items.optJSONObject(index); if (row != null)
                message.append("\n").append(checkName(row.optString("id"))).append(" · ").append(checkState(row.optString("state")));
        }
        setTextIfChanged(serverChecks, message.toString());
        JSONObject history = settings.optJSONObject("durable_history");
        if (history != null) durableHistory = history;
        JSONObject failure = durableHistory.optJSONObject("last_failure");
        if (failure == null) durableFailure.setText(R.string.server_history_empty);
        else durableFailure.setText(getString(R.string.server_history_last, accountDate(failure.optString("timestamp")), failure.optString("code")));
    }

    private void requestDiagnosticsExport() {
        Intent destination = new Intent(Intent.ACTION_CREATE_DOCUMENT)
                .addCategory(Intent.CATEGORY_OPENABLE)
                .addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
                .setType("application/json")
                .putExtra(Intent.EXTRA_TITLE, "IdolyPride-diagnostics.json");
        try {
            startActivityForResult(destination, EXPORT_DIAGNOSTICS);
        } catch (RuntimeException error) {
            Toast.makeText(this, R.string.export_picker_failed, Toast.LENGTH_LONG).show();
        }
    }

    private void finishDiagnosticsExport(int resultCode, Intent data) {
        if (resultCode != RESULT_OK || data == null) return;
        Uri destination = data.getData();
        if (destination != null) ServerService.exportDiagnostics(getApplicationContext(), destination);
    }

    private static int optionIndex(String[] values, String selected) {
        for (int index = 0; index < values.length; index++) if (values[index].equals(selected)) return index;
        return 0;
    }
    private boolean downloadsSelected() {
        return getSharedPreferences(SERVER_PREFS, MODE_PRIVATE).getBoolean(RESOURCE_PUBLIC_DOWNLOADS, true);
    }
    private void addResourceStorageControls(LinearLayout body) {
        resourceStorage = presentationSpinner(body, R.string.resource_storage, R.array.resource_storage_options);
        resourceStorage.setSelection(downloadsSelected() ? 0 : 1);
        resourceStorageNotice = text(R.string.resource_storage_public_notice, 12, TEXT_MUTED);
        resourceStorageNotice.setPadding(0, 0, 0, dp(8)); body.addView(resourceStorageNotice);
        resourceStorage.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                boolean selected = position == 0;
                getSharedPreferences(SERVER_PREFS, MODE_PRIVATE).edit().putBoolean(RESOURCE_PUBLIC_DOWNLOADS, selected).apply();
                resourceStorageNotice.setText(selected ? R.string.resource_storage_public_notice : R.string.resource_storage_private_notice);
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });
        resourceStorageNotice.setText(downloadsSelected() ? R.string.resource_storage_public_notice : R.string.resource_storage_private_notice);
    }
    private void startServerWithSelectedStorage() {
        try { startForegroundService(new Intent(this, ServerService.class).setAction(ServerService.ACTION_START)); }
        catch (RuntimeException failed) { Toast.makeText(this, R.string.server_start_failed, Toast.LENGTH_LONG).show(); }
    }
    private void choosePrivateStorageAndStart() {
        getSharedPreferences(SERVER_PREFS, MODE_PRIVATE).edit().putBoolean(RESOURCE_PUBLIC_DOWNLOADS, false).apply();
        resourceStorage.setSelection(1); retryStartAfterStoragePermission = false;
        startServerWithSelectedStorage();
    }
    private void requestServerStart() {
        boolean granted = Build.VERSION.SDK_INT >= 30 && Environment.isExternalStorageManager();
        int decision = ResourceTransfers.storageAccess(Build.VERSION.SDK_INT, downloadsSelected(), granted);
        if (decision == ResourceTransfers.STORAGE_PRIVATE || decision == ResourceTransfers.STORAGE_DOWNLOADS) {
            startServerWithSelectedStorage(); return;
        }
        AlertDialog.Builder dialog = new AlertDialog.Builder(this).setTitle(R.string.resource_storage_permission_title)
                .setMessage(decision == ResourceTransfers.STORAGE_UNSUPPORTED ? R.string.resource_storage_older_android : R.string.resource_storage_permission_notice)
                .setNegativeButton(R.string.resource_storage_use_private, (view, which) -> choosePrivateStorageAndStart())
                .setNeutralButton(R.string.resource_storage_later, null);
        if (decision == ResourceTransfers.STORAGE_PERMISSION) dialog.setPositiveButton(R.string.resource_storage_open_settings, (view, which) -> {
            retryStartAfterStoragePermission = true;
            Intent settings = new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                    Uri.parse("package:" + getPackageName()));
            try { startActivity(settings); }
            catch (RuntimeException unavailable) {
                retryStartAfterStoragePermission = false;
                Toast.makeText(this, R.string.resource_storage_settings_unavailable, Toast.LENGTH_LONG).show();
            }
        });
        dialog.show();
    }
    @Override protected void onResume() {
        super.onResume();
        if (retryStartAfterStoragePermission) {
            retryStartAfterStoragePermission = false;
            if (downloadsSelected() && Build.VERSION.SDK_INT >= 30 && Environment.isExternalStorageManager()) startServerWithSelectedStorage();
            else Toast.makeText(this, R.string.resource_storage_permission_denied, Toast.LENGTH_LONG).show();
        }
    }
    private void resourcePickerLocation(Intent picker) {
        try {
            File exports = new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), "IdolyPride/exports");
            if (exports.isDirectory()) picker.putExtra(DocumentsContract.EXTRA_INITIAL_URI,
                    DocumentsContract.buildDocumentUri("com.android.externalstorage.documents", "primary:Download/IdolyPride/exports"));
        } catch (SecurityException unavailable) { /* The system picker remains the explicit fallback. */ }
    }
    private void addLibraryControls(LinearLayout body) {
        LibrarySettings.Loaded loaded = LibrarySettings.load(getFilesDir());
        librarySettings = loaded.settings;
        libraryInvalidLanguage = loaded.invalidLanguage; libraryInvalidMedia = loaded.invalidMedia;
        libraryInvalid = libraryInvalidLanguage || libraryInvalidMedia;
        body.addView(sectionTitle(R.string.library_settings_title));
        libraryLanguage = presentationSpinner(body, R.string.library_language, R.array.library_language_options);
        hideVideoMv = new CheckBox(this); hideVideoMv.setText(R.string.library_hide_video_mv);
        hideVideoMv.setTextSize(13); hideVideoMv.setTextColor(TEXT_PRIMARY); body.addView(hideVideoMv);
        libraryMvSort = presentationSpinner(body, R.string.library_mv_sort, R.array.library_mv_sort_options);
        libraryOutfitSort = presentationSpinner(body, R.string.library_outfit_sort, R.array.library_outfit_sort_options);
        libraryStatus = text(R.string.library_settings_notice, 12, TEXT_MUTED);
        libraryStatus.setTextIsSelectable(true); libraryStatus.setPadding(0, dp(4), 0, dp(8)); body.addView(libraryStatus);
        restoreLibraryControls();
        AdapterView.OnItemSelectedListener changed = new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, View view, int position, long id) { saveLibraryControls(); }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        };
        libraryLanguage.setOnItemSelectedListener(changed); libraryMvSort.setOnItemSelectedListener(changed);
        libraryOutfitSort.setOnItemSelectedListener(changed);
        hideVideoMv.setOnCheckedChangeListener((button, enabled) -> saveLibraryControls());
        updateLibraryStatus();
    }
    private void restoreLibraryControls() {
        libraryLoading = true;
        libraryLanguage.setSelection(optionIndex(LibrarySettings.LANGUAGES, librarySettings.language));
        libraryMvSort.setSelection(optionIndex(LibrarySettings.MV_SORTS, librarySettings.mvSort));
        libraryOutfitSort.setSelection(optionIndex(LibrarySettings.OUTFIT_SORTS, librarySettings.outfitSort));
        hideVideoMv.setChecked(librarySettings.hideVideoMv); libraryLoading = false;
    }
    private void saveLibraryControls() {
        if (libraryLoading) return;
        String language = LibrarySettings.LANGUAGES[libraryLanguage.getSelectedItemPosition()];
        String mv = LibrarySettings.MV_SORTS[libraryMvSort.getSelectedItemPosition()];
        String outfit = LibrarySettings.OUTFIT_SORTS[libraryOutfitSort.getSelectedItemPosition()];
        boolean hide = hideVideoMv.isChecked();
        boolean languageChanged = !language.equals(librarySettings.language);
        boolean mediaChanged = hide != librarySettings.hideVideoMv || !mv.equals(librarySettings.mvSort) || !outfit.equals(librarySettings.outfitSort);
        if (!languageChanged && !mediaChanged) return;
        try {
            if (languageChanged) {
                LibrarySettings next = librarySettings.changedLanguage(language); next.saveLanguage(getFilesDir()); librarySettings = next;
                libraryInvalidLanguage = false;
            }
            if (mediaChanged) {
                LibrarySettings next = librarySettings.changedMedia(hide, mv, outfit, System.currentTimeMillis());
                next.saveMedia(getFilesDir()); librarySettings = next;
                libraryInvalidMedia = false;
            }
            librarySaveFailed = false; libraryInvalid = libraryInvalidLanguage || libraryInvalidMedia;
        } catch (IOException | IllegalArgumentException | IllegalStateException error) {
            librarySaveFailed = true; restoreLibraryControls();
            Toast.makeText(this, R.string.library_settings_failed, Toast.LENGTH_LONG).show();
        }
        updateLibraryStatus();
    }
    private void updateLibraryStatus() {
        if (libraryStatus == null) return;
        setTextIfChanged(libraryStatus, getString(librarySaveFailed ? R.string.library_settings_failed
                : libraryInvalid ? R.string.library_settings_invalid : R.string.library_settings_notice));
        libraryStatus.setTextColor(librarySaveFailed || libraryInvalid ? WARNING : TEXT_MUTED);
    }
    private String selectedResourcePlatform() { return resourcePlatform.getSelectedItemPosition() == 1 ? "ios" : "android"; }
    private int selectedResourceParallelism() {
        return ResourceTransfers.downloadParallelismAt(resourceParallelism.getSelectedItemPosition());
    }
    private void addResourceLibraryControls(LinearLayout body) {
        TextView heading = sectionTitle(R.string.library_resources_title);
        heading.setPadding(0, dp(12), 0, dp(4)); body.addView(heading);
        resourcePlatform = presentationSpinner(body, R.string.library_resource_platform, R.array.library_resource_platform_options);
        String selected = getSharedPreferences(SERVER_PREFS, MODE_PRIVATE).getString("resource_platform", "android");
        resourcePlatform.setSelection("ios".equals(selected) ? 1 : 0);
        resourceParallelism = presentationSpinner(body, R.string.library_download_parallelism, R.array.library_download_parallelism_options);
        int parallelism = 4;
        try { parallelism = getSharedPreferences(SERVER_PREFS, MODE_PRIVATE).getInt(RESOURCE_DOWNLOAD_PARALLELISM, 4); }
        catch (ClassCastException invalidPreference) { /* A malformed preference uses the normal default. */ }
        resourceParallelism.setSelection(ResourceTransfers.downloadParallelismPosition(parallelism));
        AdapterView.OnItemSelectedListener selectionChanged = new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                getSharedPreferences(SERVER_PREFS, MODE_PRIVATE).edit()
                        .putString("resource_platform", selectedResourcePlatform())
                        .putInt(RESOURCE_DOWNLOAD_PARALLELISM, selectedResourceParallelism()).apply();
                updateResourceLibrary(new JSONObject());
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        };
        resourcePlatform.setOnItemSelectedListener(selectionChanged);
        resourceParallelism.setOnItemSelectedListener(selectionChanged);
        body.addView(text(R.string.library_download_parallelism_notice, 12, TEXT_MUTED));
        body.addView(text(R.string.library_resources_notice, 12, TEXT_MUTED));
        downloadLibrary = button(R.string.library_download_all); body.addView(downloadLibrary);
        importLibrary = button(R.string.library_import); body.addView(importLibrary);
        exportLibrary = button(R.string.library_export); body.addView(exportLibrary);
        cancelLibrary = button(R.string.library_cancel); body.addView(cancelLibrary);
        libraryTransferStatus = text(R.string.library_resources_waiting, 12, TEXT_MUTED);
        libraryTransferStatus.setTextIsSelectable(true); libraryTransferStatus.setPadding(0, dp(6), 0, dp(6)); body.addView(libraryTransferStatus);
        libraryProgress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        libraryProgress.setMax(1000); libraryProgress.setVisibility(View.GONE); body.addView(libraryProgress, new LinearLayout.LayoutParams(-1, dp(12)));
        downloadLibrary.setOnClickListener(view -> {
            if (!ResourceTransfers.download(getApplicationContext(), selectedResourcePlatform(), selectedResourceParallelism())) resourceUnavailable();
        });
        exportLibrary.setOnClickListener(view -> exportResourceLibrary());
        importLibrary.setOnClickListener(view -> {
            pendingResourcePlatform = selectedResourcePlatform();
            Intent picker = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/zip");
            resourcePickerLocation(picker);
            picker.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            try { startActivityForResult(picker, IMPORT_RESOURCES); }
            catch (RuntimeException unavailable) { Toast.makeText(this, R.string.library_picker_failed, Toast.LENGTH_LONG).show(); }
        });
        cancelLibrary.setOnClickListener(view -> ServerService.cancelResourceJob(currentLibraryJob));
        updateResourceLibrary(new JSONObject());
    }
    private void resourceUnavailable() { Toast.makeText(this, R.string.library_resources_unavailable, Toast.LENGTH_LONG).show(); }
    private void exportResourceLibrary() {
        pendingResourcePlatform = selectedResourcePlatform();
        if (Build.VERSION.SDK_INT >= 29) {
            if (!ResourceTransfers.exportArchive(getApplicationContext(), pendingResourcePlatform, null)) resourceUnavailable();
        } else {
            Intent picker = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/zip");
            resourcePickerLocation(picker);
            picker.putExtra(Intent.EXTRA_TITLE, "IdolyPride-Resources-" + pendingResourcePlatform + ".zip");
            try { startActivityForResult(picker, EXPORT_RESOURCES); }
            catch (RuntimeException unavailable) { Toast.makeText(this, R.string.library_picker_failed, Toast.LENGTH_LONG).show(); }
        }
    }
    private static boolean terminalResourceJob(String state) {
        return state.equals("completed") || state.equals("partial") || state.equals("failed") || state.equals("cancelled");
    }
    private void updateResourceLibrary(JSONObject details) {
        if (libraryTransferStatus == null) return;
        JSONObject library = details.optJSONObject("resource_library");
        if (library == null) library = resourceLibraryRuntime;
        else resourceLibraryRuntime = library;
        JSONObject catalogs = library == null ? null : library.optJSONObject("catalogs");
        JSONObject catalog = catalogs == null ? null : catalogs.optJSONObject(selectedResourcePlatform());
        JSONObject job = library == null ? null : library.optJSONObject("job");
        String jobState = job == null ? "" : job.optString("state", "");
        boolean active = job != null && !terminalResourceJob(jobState);
        currentLibraryJob = active ? job.optString("job_id", "") : null;
        ResourceTransfers.Snapshot local = ResourceTransfers.snapshot();
        boolean enabled = ServerService.resourceServerRunning() && !local.busy && !active && catalog != null && catalog.optBoolean("available", false);
        downloadLibrary.setEnabled(enabled); importLibrary.setEnabled(enabled); exportLibrary.setEnabled(enabled);
        resourcePlatform.setEnabled(!local.busy && !active);
        resourceParallelism.setEnabled(!local.busy && !active);
        cancelLibrary.setEnabled(local.busy && local.action.equals("export") || active && currentLibraryJob != null && !currentLibraryJob.isEmpty());
        String message;
        if (local.busy) message = getString(local.state.equals("cancelling") ? R.string.library_resources_cancelling
                : local.state.equals("preparing") ? R.string.library_resources_preparing : R.string.library_resources_working,
                local.action.equals("import") ? getString(R.string.library_import) : local.action.equals("export") ? getString(R.string.library_export) : getString(R.string.library_download_all),
                formatBytes(local.bytes));
        else if (!ServerService.resourceServerRunning()) message = getString(R.string.library_resources_waiting);
        else if (local.state.equals("failed")) message = getString(local.error != null && local.error.equals("seekable_required")
                ? R.string.library_import_seekable : R.string.library_resources_failed);
        else if (local.state.equals("cancelled")) message = getString(R.string.library_resources_cancelled);
        else if (catalog == null || !catalog.optBoolean("available", false)) message = getString(R.string.library_catalog_unavailable);
        else message = getString(R.string.library_resources_ready);
        if (job != null) {
            long total = Math.max(0, job.optLong("total_files", 0)), verified = Math.max(0, job.optLong("verified_files", 0));
            long missing = Math.max(0, job.optLong("missing_files", 0)), failed = Math.max(0, job.optLong("failed_files", 0));
            String state = jobState.equals("completed") ? getString(R.string.library_job_completed) : jobState.equals("partial") ? getString(R.string.library_job_partial)
                    : jobState.equals("failed") ? getString(R.string.library_job_failed) : jobState.equals("cancelled") ? getString(R.string.library_job_cancelled)
                    : jobState.equals("cancelling") ? getString(R.string.library_job_cancelling) : getString(R.string.library_job_running);
            message += "\n" + getString(R.string.library_job_summary, job.optString("platform", "—"), state, verified, total, missing, failed);
            int parallelism = job.optInt("parallelism", 0);
            if ("download".equals(job.optString("action", "")) && ResourceTransfers.downloadParallelism(parallelism))
                message += "\n" + getString(R.string.library_job_parallelism, parallelism, Math.max(0, job.optInt("active_files", 0)));
            if ("download".equals(job.optString("action", "")) && job.has("elapsed_seconds")) {
                double rate = job.optDouble("average_bytes_per_second", 0);
                double elapsed = job.optDouble("elapsed_seconds", 0);
                long rateBytes = Double.isNaN(rate) || Double.isInfinite(rate) || rate < 0 ? 0 : (long) Math.min(Long.MAX_VALUE, rate);
                long elapsedSeconds = Double.isNaN(elapsed) || Double.isInfinite(elapsed) || elapsed < 0 ? 0 : (long) Math.min(Long.MAX_VALUE, elapsed);
                message += "\n" + getString(R.string.library_job_transfer_metrics,
                        formatBytes(Math.max(0, job.optLong("received_bytes", 0))), formatBytes(rateBytes), elapsedSeconds);
                message += "\n" + getString(R.string.library_job_bytes,
                        formatBytes(Math.max(0, job.optLong("verified_bytes", 0))), formatBytes(Math.max(0, job.optLong("total_bytes", 0))));
                JSONObject phases = job.optJSONObject("phase_active_files");
                if (phases != null) message += "\n" + getString(R.string.library_job_phase_summary,
                        Math.max(0, phases.optInt("connecting", 0)), Math.max(0, phases.optInt("receiving", 0)),
                        Math.max(0, phases.optInt("checking", 0)), Math.max(0, phases.optInt("saving", 0)), Math.max(0, phases.optInt("copying", 0)));
                message += "\n" + getString(R.string.library_job_cached, Math.max(0, job.optLong("cache_hit_files", 0)));
            }
            libraryProgress.setVisibility(active || local.busy ? View.VISIBLE : View.GONE);
            libraryProgress.setIndeterminate(total == 0 || !active && local.busy);
            if (active && total > 0) libraryProgress.setProgress((int) Math.min(1000, 1000.0 * Math.min(total, verified + missing + failed) / total));
        } else libraryProgress.setVisibility(local.busy ? View.VISIBLE : View.GONE);
        if (job == null) libraryProgress.setIndeterminate(local.busy);
        if (!local.busy && local.action.equals("export") && (local.state.equals("completed") || local.state.equals("partial")))
            message += "\n" + getString("downloads".equals(local.destination) ? R.string.library_export_downloads : R.string.library_export_document)
                    + (local.state.equals("partial") ? "\n" + getString(R.string.library_job_partial) : "");
        if (!local.busy && local.action.equals("import") && local.importedFiles >= 0) {
            message += "\n" + getString(R.string.library_import_result, local.importedFiles, local.failedFiles);
            if (local.error != null) message += "\n" + getString(R.string.library_import_partial);
        }
        setTextIfChanged(libraryTransferStatus, message);
    }
    private JSONObject resourceLibraryRuntime;

    @Override protected void onSaveInstanceState(Bundle state) {
        state.putString("resource_platform", pendingResourcePlatform);
        state.putBoolean("storage_retry", retryStartAfterStoragePermission);
        state.putInt("account_offset", accountOffset); state.putInt("restore_offset", restoreOffset);
        if (pendingAccountExport != null) state.putString("account_export", pendingAccountExport.toString());
        if (pendingAccountPreview != null) state.putString("account_preview", pendingAccountPreview.toString());
        super.onSaveInstanceState(state);
    }

    private void addPlaybackControls(LinearLayout body) {
        PlaybackStorage.Loaded loaded = PlaybackStorage.load(getFilesDir());
        playbackSettings = loaded.settings;
        playbackInvalid = loaded.invalid;
        waitForOrientation = new CheckBox(this);
        waitForOrientation.setText(R.string.playback_wait_for_orientation);
        waitForOrientation.setTextColor(TEXT_PRIMARY);
        waitForOrientation.setTextSize(14);
        waitForOrientation.setChecked(playbackSettings.waitForOrientation);
        body.addView(waitForOrientation);
        TextView notice = text(R.string.playback_wait_notice, 12, TEXT_MUTED);
        notice.setPadding(0, 0, 0, dp(4));
        body.addView(notice);
        playbackStatus = text(R.string.playback_waiting, 12, TEXT_MUTED);
        playbackStatus.setTextIsSelectable(true);
        playbackStatus.setPadding(0, 0, 0, dp(8));
        body.addView(playbackStatus);
        waitForOrientation.setOnCheckedChangeListener((button, checked) -> savePlaybackControl(checked));
        updatePlaybackStatus();
    }

    private void addRenderingExperiment(LinearLayout body) {
        multithreadedRendering = new CheckBox(this);
        multithreadedRendering.setText(R.string.rendering_mt_experiment);
        multithreadedRendering.setTextColor(TEXT_PRIMARY);
        multithreadedRendering.setTextSize(14);
        multithreadedRendering.setChecked(getSharedPreferences(SERVER_PREFS, MODE_PRIVATE)
                .getBoolean(RenderingExperiment.PREFERENCE, RenderingExperiment.DEFAULT_ENABLED));
        body.addView(multithreadedRendering);
        TextView notice = text(R.string.rendering_mt_notice, 12, TEXT_MUTED);
        notice.setPadding(0, 0, 0, dp(4));
        body.addView(notice);
        renderingStatus = text(R.string.rendering_probe_waiting, 12, TEXT_MUTED);
        renderingStatus.setTextIsSelectable(true);
        renderingStatus.setPadding(0, 0, 0, dp(8));
        body.addView(renderingStatus);
        multithreadedRendering.setOnCheckedChangeListener((button, enabled) -> {
            getSharedPreferences(SERVER_PREFS, MODE_PRIVATE).edit()
                    .putBoolean(RenderingExperiment.PREFERENCE, enabled).apply();
            updateRenderingStatus();
        });
        updateRenderingStatus();
    }

    private static Long renderProbeLong(JSONObject object, String name) {
        Object value = object == null ? null : object.opt(name);
        if (!(value instanceof Integer || value instanceof Long)) return null;
        long number = ((Number) value).longValue();
        return number >= 0 ? number : null;
    }

    private static Double renderProbeNumber(JSONObject object, String name) {
        Object value = object == null ? null : object.opt(name);
        if (!(value instanceof Number)) return null;
        double number = ((Number) value).doubleValue();
        return Double.isFinite(number) && number >= 0 ? number : null;
    }

    private void updateRenderingStatus() {
        if (renderingStatus == null) return;
        boolean requested = multithreadedRendering.isChecked();
        String request = getString(requested ? R.string.rendering_request_mt : R.string.rendering_request_original);
        JSONObject client = renderProbeRuntime == null ? null : renderProbeRuntime.optJSONObject("client");
        int mode = playbackInteger(client, "actual_mode");
        Long observations = renderProbeLong(client, "observations");
        Long thread = renderProbeLong(client, "callback_tid");
        int api = playbackInteger(client, "graphics_api");
        Object rawState = client == null ? null : client.opt("state");
        Double receiptAge = renderProbeNumber(renderProbeRuntime, "age_seconds");
        long now = SystemClock.elapsedRealtime(), received = ServerService.runtimeDetailsReceivedAt();
        int feedback = RenderingExperiment.feedback(presentationObserved,
                presentationServerRunning && renderProbeRuntimeRunning, now, received,
                playbackInteger(client, "schema"), rawState instanceof String ? (String) rawState : null,
                playbackBoolean(renderProbeRuntime, "stale"), receiptAge,
                renderProbeLong(client, "sample_age_ms"), mode, observations == null ? -1 : observations,
                client != null && client.length() == 10 && api >= 0 && api <= 255
                        && thread != null && thread > 0 && thread <= Integer.MAX_VALUE);
        int message = feedback == RenderingExperiment.STALE ? R.string.rendering_probe_stale
                : feedback == RenderingExperiment.UNSUPPORTED ? R.string.rendering_probe_unsupported
                : feedback == RenderingExperiment.INIT_FAILED ? R.string.rendering_probe_init_failed
                : feedback == RenderingExperiment.WAIT_CLIENT ? R.string.rendering_probe_client_waiting
                : R.string.rendering_probe_waiting;
        String actual = getString(message);
        if (feedback == RenderingExperiment.OBSERVED) {
            int[] modes = {R.string.rendering_mode_direct, R.string.rendering_mode_single,
                    R.string.rendering_mode_multi, R.string.rendering_mode_legacy_jobs,
                    R.string.rendering_mode_native_jobs, R.string.rendering_mode_native_jobs_without_render};
            actual = getString(R.string.rendering_probe_observed, getString(modes[mode]), api);
            if (requested && (mode == 0 || mode == 1)) actual += "\n" + getString(R.string.rendering_mt_not_observed);
            Double cpu = renderProbeNumber(client, "cpu_frame_ms"), gpu = renderProbeNumber(client, "gpu_frame_ms");
            boolean timingFresh = RenderingExperiment.timingFresh(renderProbeLong(client, "timing_age_ms"),
                    receiptAge, now, received);
            if (timingFresh && (cpu != null && cpu > 0 && cpu <= 60_000 || gpu != null && gpu > 0 && gpu <= 60_000)) {
                String cpuText = cpu != null && cpu > 0 && cpu <= 60_000 ? String.format(Locale.ROOT, "%.2f", cpu) : "—";
                String gpuText = gpu != null && gpu > 0 && gpu <= 60_000 ? String.format(Locale.ROOT, "%.2f", gpu) : "—";
                actual += "\n" + getString(R.string.rendering_frame_times, cpuText, gpuText);
            } else actual += "\n" + getString(R.string.rendering_frame_times_unavailable);
        }
        setTextIfChanged(renderingStatus, request + "\n" + actual);
        renderingStatus.setTextColor(feedback == RenderingExperiment.OBSERVED ? TEXT_MUTED
                : feedback == RenderingExperiment.UNSUPPORTED || feedback == RenderingExperiment.INIT_FAILED
                ? WARNING : TEXT_MUTED);
    }

    private void savePlaybackControl(boolean wait) {
        if (playbackLoading || playbackSettings.waitForOrientation == wait) return;
        try {
            PlaybackSettings requested = playbackSettings.changed(wait);
            PlaybackStorage.save(getFilesDir(), requested);
            playbackSettings = requested;
            playbackSaveFailed = playbackInvalid = false;
        } catch (IOException | IllegalStateException error) {
            playbackSaveFailed = true;
            playbackLoading = true;
            waitForOrientation.setChecked(playbackSettings.waitForOrientation);
            playbackLoading = false;
            Toast.makeText(this, R.string.playback_save_failed, Toast.LENGTH_LONG).show();
        }
        updatePlaybackStatus();
    }

    private static int playbackInteger(JSONObject object, String name) {
        Object value = object == null ? null : object.opt(name);
        if (!(value instanceof Integer || value instanceof Long)) return -1;
        long number = ((Number) value).longValue();
        return number >= 0 && number <= Integer.MAX_VALUE ? (int) number : -1;
    }

    private static Boolean playbackBoolean(JSONObject object, String name) {
        Object value = object == null ? null : object.opt(name);
        return value instanceof Boolean ? (Boolean) value : null;
    }

    private void updatePlaybackStatus() {
        if (playbackStatus == null) return;
        if (playbackSaveFailed || playbackInvalid || (playbackRuntime != null
                && playbackRuntime.optBoolean("invalid_settings_file", false))) {
            setTextIfChanged(playbackStatus, getString(playbackSaveFailed
                    ? R.string.playback_save_failed : R.string.playback_invalid));
            playbackStatus.setTextColor(WARNING);
            return;
        }
        JSONObject client = playbackRuntime == null ? null : playbackRuntime.optJSONObject("client");
        if (client != null && client.length() != 6) client = null;
        Object revision = client == null ? null : client.opt("revision");
        long ackRevision = revision instanceof Integer || revision instanceof Long
                ? ((Number) revision).longValue() : -1;
        int feedback = PlaybackSettings.feedback(presentationObserved, presentationServerRunning && playbackRuntimeRunning,
                PlaybackSettings.fresh(SystemClock.elapsedRealtime(), ServerService.runtimeDetailsReceivedAt()),
                playbackSettings, playbackInteger(client, "schema"), playbackInteger(client, "bridge_version"),
                ackRevision, playbackBoolean(client, "wait_for_orientation"),
                playbackBoolean(client, "supported"), playbackBoolean(client, "applied"));
        int message = feedback == PlaybackSettings.APPLIED ? R.string.playback_received
                : feedback == PlaybackSettings.UNSUPPORTED ? R.string.playback_unsupported
                : feedback == PlaybackSettings.WAIT_CLIENT ? R.string.playback_client_waiting
                : feedback == PlaybackSettings.PENDING ? R.string.playback_saved_waiting
                : R.string.playback_waiting;
        setTextIfChanged(playbackStatus, getString(message));
        playbackStatus.setTextColor(feedback == PlaybackSettings.APPLIED ? SUCCESS
                : feedback == PlaybackSettings.UNSUPPORTED ? WARNING
                : TEXT_MUTED);
    }

    private void addPresentationControls(LinearLayout body) {
        PresentationSettings.Loaded loaded = PresentationSettings.load(getFilesDir());
        presentationSettings = loaded.settings;
        presentationInvalid = loaded.invalid;
        Button heading = button(R.string.presentation_title_expanded);
        body.addView(heading, new LinearLayout.LayoutParams(-1, -2));
        LinearLayout settings = new LinearLayout(this);
        settings.setOrientation(LinearLayout.VERTICAL);
        settings.setPadding(dp(8), 0, dp(8), dp(8));
        settings.setVisibility(View.VISIBLE);
        body.addView(settings, new LinearLayout.LayoutParams(-1, -2));
        heading.setOnClickListener(view -> {
            boolean expanded = settings.getVisibility() != View.VISIBLE;
            settings.setVisibility(expanded ? View.VISIBLE : View.GONE);
            heading.setText(expanded ? R.string.presentation_title_expanded : R.string.presentation_title);
        });
        TextView notice = text(R.string.presentation_notice, 12, TEXT_MUTED);
        notice.setPadding(0, dp(4), 0, dp(8));
        settings.addView(notice);
        TextView clientNotice = text(R.string.presentation_client_notice, 12, TEXT_MUTED);
        clientNotice.setPadding(0, 0, 0, dp(6));
        settings.addView(clientNotice);
        customGraphics = new CheckBox(this);
        customGraphics.setText(R.string.presentation_custom_graphics);
        customGraphics.setTextColor(TEXT_PRIMARY);
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
        expandPhotography.setTextColor(TEXT_PRIMARY);
        expandPhotography.setTextSize(14);
        settings.addView(expandPhotography);
        TextView photographyNotice = text(R.string.presentation_photography_notice, 12,
                TEXT_MUTED);
        photographyNotice.setPadding(0, 0, 0, dp(8));
        settings.addView(photographyNotice);
        presentationStatus = text(R.string.presentation_waiting, 12, TEXT_MUTED);
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

    private Spinner presentationSpinner(LinearLayout parent, int labelResource, int optionsResource) {
        TextView label = text(labelResource, 13, TEXT_MUTED);
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
                value.setTextColor(TEXT_PRIMARY);
                value.setTextSize(16);
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
            presentationStatus.setTextColor(WARNING);
            return;
        }
        if (presentationInvalid) {
            setTextIfChanged(presentationStatus, getString(R.string.presentation_invalid));
            presentationStatus.setTextColor(WARNING);
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
                        ? SUCCESS : "unsupported".equals(state) || "init_failed".equals(state)
                        ? WARNING : TEXT_MUTED);
                return;
            }
        }
        setTextIfChanged(presentationStatus, getString(presentationSettings.revision > 0
                ? R.string.presentation_saved_waiting : R.string.presentation_waiting));
        presentationStatus.setTextColor(TEXT_MUTED);
    }

    private void launchClient(int missingMessage, String... packageNames) {
        Intent client = null;
        String selectedPackage = null;
        for (String packageName : packageNames) {
            client = getPackageManager().getLaunchIntentForPackage(packageName);
            if (client != null) { selectedPackage = packageName; break; }
        }
        if (client == null) {
            Toast.makeText(this, missingMessage, Toast.LENGTH_LONG).show();
            return;
        }
        try {
            if (getSharedPreferences(SERVER_PREFS, MODE_PRIVATE)
                    .getBoolean(RenderingExperiment.PREFERENCE, RenderingExperiment.DEFAULT_ENABLED)) {
                String arguments;
                try {
                    if (!RenderingExperiment.knownClient(selectedPackage)) throw new IllegalArgumentException("Unknown client");
                    Bundle extras = client.getExtras();
                    Object previous = extras == null ? null : extras.get(RenderingExperiment.UNITY_ARGUMENTS);
                    if (previous != null && !(previous instanceof String)) throw new IllegalArgumentException("Unity argument type");
                    arguments = RenderingExperiment.launchArguments((String) previous, true);
                }
                catch (IllegalArgumentException error) {
                    Toast.makeText(this, R.string.rendering_launch_conflict, Toast.LENGTH_LONG).show();
                    return;
                }
                client.putExtra(RenderingExperiment.UNITY_ARGUMENTS, arguments);
            }
            startActivity(client);
        } catch (RuntimeException error) {
            Toast.makeText(this, R.string.client_launch_failed, Toast.LENGTH_LONG).show();
        }
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == EXPORT_ACCOUNT || requestCode == IMPORT_ACCOUNT) {
            if (resultCode != RESULT_OK || data == null || data.getData() == null) {
                if (requestCode == EXPORT_ACCOUNT && pendingAccountExport != null) {
                    ServerService.discardAccountDocument(getApplicationContext(), pendingAccountExport.optString("path")); pendingAccountExport = null;
                }
                return;
            }
            accountOperation.setText(R.string.accounts_working);
            if (requestCode == IMPORT_ACCOUNT)
                ServerService.previewAccountDocument(getApplicationContext(), data.getData(), accountCallback("accounts_preview"));
            else if (pendingAccountExport != null)
                ServerService.saveAccountDocument(getApplicationContext(), data.getData(), pendingAccountExport, accountCallback("accounts_save_document"));
            else accountError("account_export_unavailable");
            updateAccountControls(); return;
        }
        if (requestCode == EXPORT_RESOURCES || requestCode == IMPORT_RESOURCES) {
            if (resultCode != RESULT_OK || data == null || data.getData() == null) return;
            String platform = ResourceTransfers.platform(pendingResourcePlatform) ? pendingResourcePlatform : selectedResourcePlatform();
            boolean started = requestCode == EXPORT_RESOURCES
                    ? ResourceTransfers.exportArchive(getApplicationContext(), platform, data.getData())
                    : ResourceTransfers.importArchive(getApplicationContext(), data.getData(), platform);
            if (!started) resourceUnavailable();
            return;
        }
        if (requestCode == EXPORT_DIAGNOSTICS) finishDiagnosticsExport(resultCode, data);
    }

    @Override protected void onStart() {
        super.onStart();
        presentationObserved = true;
        ServerService.observe(this);
        playbackStatus.removeCallbacks(playbackRefresh);
        playbackStatus.post(playbackRefresh);
        if (!ServerService.isManagingAccounts()) refreshAccounts();
    }

    @Override protected void onStop() {
        presentationObserved = false;
        presentationRuntime = null;
        playbackRuntime = null;
        playbackRuntimeRunning = false;
        renderProbeRuntime = null;
        renderProbeRuntimeRunning = false;
        playbackStatus.removeCallbacks(playbackRefresh);
        updatePlaybackStatus();
        updateRenderingStatus();
        updatePresentationStatus();
        ServerService.removeObserver(this);
        super.onStop();
    }

    @Override public void onServerChanged(String value, boolean running, boolean busy, List<String> lines, String detailsJson) {
        presentationServerRunning = running;
        status.setText(value);
        status.setTextColor(running ? SUCCESS : TEXT_PRIMARY);
        accountLifecycleBusy = busy;
        start.setEnabled(!running && !busy && !ServerService.isManagingAccounts());
        updateAccountControls();
        experimentalMainLive.setEnabled(!running && !busy);
        downloadMissingResources.setEnabled(!running && !busy);
        mediaMode.setEnabled(!running && !busy);
        resourceStorage.setEnabled(!running && !busy);
        stop.setEnabled(running || busy);
        export.setEnabled(!ServerService.isExporting());
        updateDiagnostics(detailsJson);
        try {
            JSONObject observed = new JSONObject(detailsJson);
            if (observed.has("startup_checks") || observed.has("durable_history")) renderServerChecks(observed);
            if (running) activeAccount = accountPayload("running", true, "mode", observed.optBoolean("media_mode", false) ? "media" : "normal", "profile", observed.optString("profile"));
            else activeAccount = accountPayload("running", false);
            renderAccountOverview();
        } catch (org.json.JSONException ignored) {}
        String currentLogs = lines.isEmpty() ? getString(R.string.waiting_logs) : String.join("\n", lines);
        if (!currentLogs.contentEquals(logs.getText())) {
            boolean follow = logs.getHeight() - logScroll.getScrollY() <= logScroll.getHeight() + dp(32);
            logs.setText(currentLogs);
            if (follow) logScroll.post(() -> logScroll.fullScroll(View.FOCUS_DOWN));
        }
    }
    private static boolean infrastructureExceptionFrame(String frame) {
        return frame.startsWith("System.") || frame.startsWith("Cysharp.Threading.Tasks.")
                || frame.startsWith("UnityEngine.") || frame.startsWith("Unity.")
                || frame.startsWith("Google.Protobuf.") || frame.startsWith("Grpc.");
    }

    private static String exceptionFrameSummary(org.json.JSONArray frames) {
        if (frames == null || frames.length() == 0) return "";
        String first = frames.optString(0, "");
        if (infrastructureExceptionFrame(first)) {
            for (int index = 1; index < Math.min(frames.length(), 16); index++) {
                String candidate = frames.optString(index, "");
                if (!candidate.isEmpty() && !infrastructureExceptionFrame(candidate))
                    return candidate + " [" + first + "]";
            }
        }
        return first;
    }

    private void updateDiagnostics(String serialized) {
        JSONObject details;
        try { details = new JSONObject(serialized); }
        catch (Exception ignored) { details = new JSONObject(); }
        updateResourceLibrary(details);
        presentationRuntime = details.optJSONObject("presentation");
        playbackRuntime = details.optJSONObject("playback");
        playbackRuntimeRunning = Boolean.TRUE.equals(details.opt("running"));
        renderProbeRuntime = details.optJSONObject("render_probe");
        renderProbeRuntimeRunning = Boolean.TRUE.equals(details.opt("running"));
        updatePlaybackStatus();
        updateRenderingStatus();
        updatePresentationStatus();
        JSONObject client = details.optJSONObject("client_diagnostics");
        String summary = client == null ? "" : client.optString("summary", "");
        JSONObject phase = client == null ? null : client.optJSONObject("phase");
        String phaseSummary = phase == null ? "" : phase.optString("summary", "");
        if (!phaseSummary.isEmpty()) summary = getString(R.string.game_last_phase, phaseSummary);
        if (client == null || client.optLong("received_events", 0) == 0 || summary.isEmpty()) {
            setTextIfChanged(gameStatus, getString(R.string.game_state_waiting));
            gameStatus.setTextColor(TEXT_MUTED);
        } else {
            setTextIfChanged(gameStatus, summary);
            gameStatus.setTextColor(client.optJSONObject("latest_exception") == null
                    ? TEXT_MUTED : WARNING);
        }
        JSONObject exception = client == null ? null : client.optJSONObject("latest_exception");
        if (exception != null) {
            String identity = exception.optString("type", "");
            org.json.JSONArray frames = exception.optJSONArray("frames");
            if (frames != null && frames.length() > 0) identity += " @ " + exceptionFrameSummary(frames);
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
            resourceStatus.setTextColor(TEXT_MUTED);
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
        Long httpFailures = resourceDiagnosticInteger(resources, "session_http_failures", 0, Long.MAX_VALUE);
        resourceStatus.setTextColor("failed".equals(resourceState) || (httpFailures != null && httpFailures > 0)
                ? WARNING : TEXT_MUTED);
        long received = Math.max(0, resources.optLong("session_received_bytes", 0));
        long verified = Math.max(0, resources.optLong("session_verified_files", 0));
        long served = Math.max(0, resources.optLong("session_served_bytes", 0));
        // These are measured session totals for different links, not a combined
        // percentage or proof that all of the game's resources are downloaded.
        setTextIfChanged(resourceReceived, getString(R.string.resource_transfer_received,
                formatBytes(received), verified));
        String httpDetails = resourceHttpDiagnostics(resources);
        setTextIfChanged(resourceServed, getString(R.string.resource_transfer_served, formatBytes(served))
                + (httpDetails.isEmpty() ? "" : "\n" + httpDetails));
        resourceReceived.setVisibility(View.VISIBLE);
        resourceServed.setVisibility(View.VISIBLE);
    }

    // Resource HTTP diagnostics formatter begins. Pure, bounded and Android-free.
    private static Long resourceDiagnosticInteger(JSONObject row, String key, long minimum, long maximum) {
        Object value = row == null ? null : row.opt(key);
        // JSONObject.optLong also coerces strings and floating point values.
        // Diagnostic protocol numbers must retain their actual integral type.
        if (!(value instanceof Integer) && !(value instanceof Long)) return null;
        long number = ((Number) value).longValue();
        return number >= minimum && number <= maximum ? number : null;
    }

    private static String resourceDiagnosticString(JSONObject row, String key, int maximum) {
        Object value = row == null ? null : row.opt(key);
        if (!(value instanceof String)) return "";
        String text = (String) value;
        return text.length() <= maximum ? text : "";
    }

    private static String resourceDiagnosticCode(JSONObject row, String key) {
        String code = resourceDiagnosticString(row, key, 40);
        switch (code) {
            case "octo_gateway_closed": case "octo_invalid_request": case "octo_forbidden":
            case "octo_not_found": case "octo_revision_unavailable": case "octo_manifest_unavailable":
            case "octo_invalid_range": case "octo_cache_invalid": case "octo_cache_miss":
            case "octo_resource_unavailable": case "client_disconnected": case "request_aborted":
            case "cache_closed": case "download_disabled": case "cache_io": case "upstream_redirect":
            case "upstream_http": case "upstream_size": case "upstream_encoding": case "upstream_timeout":
            case "upstream_data": case "upstream_digest": case "budget_exceeded": case "conflicting_metadata":
            case "upstream_tls": case "upstream_dns": case "upstream_connect":
                return code;
            default: return "";
        }
    }

    private static String resourceDiagnosticObject(JSONObject row) {
        String name = resourceDiagnosticString(row, "object_name", 160);
        boolean safe = !name.isEmpty() && !name.startsWith("/") && !name.endsWith("/")
                && !name.contains("..") && !name.contains("//");
        for (int i = 0; safe && i < name.length(); i++) {
            char c = name.charAt(i);
            safe = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9')
                    || c == '_' || c == '-' || c == '.' || c == '/';
        }
        if (safe) return "파일 " + name;
        String key = resourceDiagnosticString(row, "cache_key", 64);
        if (key.length() != 64) return "";
        for (int i = 0; i < key.length(); i++) {
            char c = key.charAt(i);
            if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return "";
        }
        return "파일 키 " + key;
    }

    private static boolean appendResourceRequest(StringBuilder text, JSONObject row, boolean failure) {
        if (row == null) return false;
        String kind = resourceDiagnosticString(row, "kind", 8);
        if (!"manifest".equals(kind) && !"object".equals(kind)) return false;
        String phase = resourceDiagnosticString(row, "phase", 16);
        if (failure ? !"failed".equals(phase) : !("received".equals(phase) || "resolving".equals(phase)
                || "waiting_cache".equals(phase) || "sending".equals(phase) || "completed".equals(phase)
                || "failed".equals(phase))) return false;
        Long status = resourceDiagnosticInteger(row, "http_status", 100, 599);
        String error = resourceDiagnosticCode(row, "error_code");
        String cause = resourceDiagnosticCode(row, "cause_code");
        text.append(failure ? "\n마지막 실패 기록" : "\n최근 요청");
        text.append(" · ").append("manifest".equals(kind) ? "리소스 목록" : "파일");
        if (status != null) text.append(" · HTTP ").append(status);
        if (!error.isEmpty()) text.append(" · ").append(error);
        if (!cause.isEmpty()) text.append(" · ").append(cause);
        if ("object".equals(kind)) {
            String object = resourceDiagnosticObject(row);
            if (!object.isEmpty()) text.append("\n").append(object);
        } else {
            Long application = resourceDiagnosticInteger(row, "application_version", 0, Integer.MAX_VALUE);
            Long requested = resourceDiagnosticInteger(row, "requested_revision", 0, Integer.MAX_VALUE);
            Long served = resourceDiagnosticInteger(row, "served_revision", 1, Integer.MAX_VALUE);
            String mode = resourceDiagnosticString(row, "response_mode", 9);
            if (status == null || status != 200 || requested == null
                    || !("full".equals(mode) || "unchanged".equals(mode))
                    || ("unchanged".equals(mode) && !requested.equals(served))
                    || ("full".equals(mode) && served != null && requested != 0 && requested >= served)) served = null;
            if (application != null && (application == 205051 || application == 105051) && requested != null) {
                text.append("\n앱 ").append(application).append(" · 요청 개정 ").append(requested)
                        .append(" · 제공 개정 ").append(served == null ? "확인 안 됨" : served.toString());
            }
        }
        return true;
    }

    private static boolean resourceHasCacheResponse(JSONObject resources) {
        Long served = resourceDiagnosticInteger(resources, "session_served_bytes", 0, Long.MAX_VALUE);
        if (served != null && served > 0) return true;
        JSONObject latest = resources.optJSONObject("last_request");
        Long status = resourceDiagnosticInteger(latest, "http_status", 100, 599);
        return "object".equals(resourceDiagnosticString(latest, "kind", 8))
                && "completed".equals(resourceDiagnosticString(latest, "phase", 16))
                && "cache_hit".equals(resourceDiagnosticString(latest, "cache_result", 16))
                && status != null && (status == 200 || status == 206);
    }

    private static String resourceHttpDiagnostics(JSONObject resources) {
        // Older server snapshots omit these keys entirely. Keep their byte-only
        // display rather than treating missing observations as zero requests.
        if (resources == null || !resources.has("session_http_requests")) return "";
        Long requests = resourceDiagnosticInteger(resources, "session_http_requests", 0, Long.MAX_VALUE);
        Long failures = resourceDiagnosticInteger(resources, "session_http_failures", 0, Long.MAX_VALUE);
        Long hits = resourceDiagnosticInteger(resources, "session_cache_hits", 0, Long.MAX_VALUE);
        Long misses = resourceDiagnosticInteger(resources, "session_cache_misses", 0, Long.MAX_VALUE);
        JSONObject failed = resources.optJSONObject("last_failed_request");
        JSONObject latest = resources.optJSONObject("last_request");
        if (requests == null || (requests == 0 && ((failures != null && failures > 0)
                || failed != null || latest != null))) {
            return "로컬 HTTP 요청 기록 형식 오류";
        }
        StringBuilder text = new StringBuilder(512);
        text.append("로컬 HTTP 요청 ").append(requests).append(" · 실패 ")
                .append(failures == null ? "확인 안 됨" : failures.toString());
        text.append("\n캐시 적중 ").append(hits == null ? "확인 안 됨" : hits.toString())
                .append(" · 미적중 ").append(misses == null ? "확인 안 됨" : misses.toString());
        if (requests == 0) text.append("\n로컬 요청 수신 없음 · 현재 서버 실행 기준");
        else if (failures != null && failures > 0) text.append("\n로컬 요청 실패 기록 있음");
        else if (resourceHasCacheResponse(resources)) text.append("\n서버 캐시에서 응답한 기록 있음");
        else text.append("\n로컬 요청 수신됨");
        boolean failedShown = appendResourceRequest(text, failed, true);
        // The sticky failure and the latest request can be the same operation.
        // Avoid repeating it; include a newer response when the IDs differ.
        Long failedId = resourceDiagnosticInteger(failed, "request_id", 1, Long.MAX_VALUE);
        Long latestId = resourceDiagnosticInteger(latest, "request_id", 1, Long.MAX_VALUE);
        if (!failedShown || failedId == null || !failedId.equals(latestId)) {
            appendResourceRequest(text, latest, false);
        }
        // A fixed number of validated fields is formatted, never raw paths,
        // headers, URLs, account state or the overall game UID traffic totals.
        return text.length() <= 1024 ? text.toString() : text.substring(0, 1023) + "…";
    }
    // Resource HTTP diagnostics formatter ends.

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
