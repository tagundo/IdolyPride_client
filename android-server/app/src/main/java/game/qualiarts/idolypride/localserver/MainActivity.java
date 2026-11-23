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
import android.text.Editable;
import android.text.TextWatcher;
import android.text.InputType;
import android.text.InputFilter;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.widget.EditText;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.PopupMenu;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import java.util.List;
import java.util.Locale;
import java.util.ArrayList;
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
    private boolean unifiedPreparing;
    private final java.util.ArrayList<Button> accountButtons = new java.util.ArrayList<>();
    private org.json.JSONArray accountRows = new org.json.JSONArray(), restoreRows = new org.json.JSONArray();
    private JSONObject accountStatus = new JSONObject(), activeAccount = new JSONObject(), durableHistory = new JSONObject();
    private JSONObject pendingAccountExport, pendingAccountPreview;
    private int pendingAccountPicker;
    private Spinner accountPicker, restorePicker;
    private TextView accountOverview, accountPage, restorePage, accountOperation, serverChecks, durableFailure;
    private Button accountPrevious, accountNext, restoreNext, restoreAccount;
    private ProgressBar accountProgress;
    private int accountOffset, restoreOffset;
    private boolean accountLifecycleBusy, accountDialogOpen;

    private JSONObject officialJob = new JSONObject(), officialAppliedAccount;
    private TextView officialStatus, officialPreview;
    private ProgressBar officialProgress;
    private Button officialInspect, officialFetch, officialNew, officialReplace, officialCancel, officialSelect, officialNormal, officialLocalRefresh;
    private boolean officialRequest, officialPolling;
    private String officialRenderedJob;
    private String officialDeferredAction;
    private JSONObject officialDeferredPayload;
    private int officialLastError, officialWarnings;
    private static final int OFFICIAL_WARNING_CLEANUP = 1, OFFICIAL_WARNING_REFRESH = 2;
    private AlertDialog officialCredentials, officialWizardDialog;
    private final Runnable officialRefresh = new Runnable() {
        @Override public void run() {
            if (!presentationObserved || officialStatus == null) return;
            if (!officialRequest && !ServerService.isImportingOfficial() && officialCredentials == null && officialWizardDialog == null)
                requestOfficial("official_status", new JSONObject(), true);
            scheduleOfficialRefresh();
        }
    };

    private JSONObject eventsSnapshot = new JSONObject(), eventsDraft;
    private org.json.JSONArray eventsCatalog = new org.json.JSONArray();
    private static final class EventUiState {
        final boolean media;
        final EventSelectionDraft selection;
        JSONObject snapshot = new JSONObject();
        String error = "";
        int conflictRetries;
        boolean refresh = true, blocked;
        EventUiState(boolean media) { this.media = media; selection = new EventSelectionDraft(media); }
    }
    private final EventUiState normalEvents = new EventUiState(false), mediaEvents = new EventUiState(true);
    private LinearLayout eventsChoices, eventsSchedule;
    private final java.util.LinkedHashMap<String, CheckBox> eventChecks = new java.util.LinkedHashMap<>();
    private String eventsCatalogKey, eventsRenderedKey;
    private EventUiState eventsRequestState;
    private int eventsBusyRetries;
    private boolean startAfterEventsSave;
    private Button eventsAll;
    private TextView eventsModeNotice;
    private Spinner eventsPicker;
    private CheckBox eventsEnabled;
    private Button eventsStart, eventsEnd, eventsOff, eventsReload;
    private TextView eventsSummary, eventsSelected, eventsNotice;
    private String eventsSelectedId = "", eventsError = "";
    private boolean eventsRequest, eventsSaving, eventsLoading, eventsUnsaved, eventsLoaded;
    private android.app.Dialog eventsDialog;

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
    private Spinner mp4Fps, mp4Codec, mp4Bitrate, mp4Resolution;
    private EditText mp4BitrateValue, mp4Width, mp4Height;
    private LinearLayout mp4CustomBitrate, mp4CustomResolution;
    private TextView mp4OptionsSummary, mp4OptionsError;
    private Mp4ExportSettings mp4Settings;
    private boolean mp4OptionsLoading;
    private TextView mp4Status;
    private Button mp4Start, mp4Cancel, mp4Save;
    private LinearLayout mp4CompletedRows;
    private String mp4CompletedRendered = "";
    private Button mp4Enqueue, mp4QueueRun, mp4QueuePause, mp4QueueResume;
    private TextView mp4QueueStatus, mp4BackgroundStatus;
    private LinearLayout mp4QueueRows;
    private CheckBox mp4Background;
    private boolean mp4BackgroundLoading;
    private String mp4QueueRendered;
    private final Runnable mp4Refresh = this::refreshMp4;
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

    private final java.util.LinkedHashMap<String, LinearLayout> categoryPages = new java.util.LinkedHashMap<>();
    private final java.util.LinkedHashMap<String, Button> categoryButtons = new java.util.LinkedHashMap<>();
    private final java.util.HashMap<String, LinearLayout[]> categoryColumns = new java.util.HashMap<>();
    private final java.util.HashMap<String, Integer> categoryPositions = new java.util.HashMap<>();
    private ScrollView settingsScroll;
    private String selectedCategory = "console";
    private boolean wideSettings, splitSettings, compactHeader;

    private LinearLayout category(LinearLayout parent, String key) {
        LinearLayout page = new LinearLayout(this);
        page.setOrientation(splitSettings && !"console".equals(key) ? LinearLayout.HORIZONTAL : LinearLayout.VERTICAL);
        parent.addView(page, new LinearLayout.LayoutParams(-1, -2));
        categoryPages.put(key, page);
        if (splitSettings && !"console".equals(key)) {
            LinearLayout[] columns = new LinearLayout[2];
            for (int index = 0; index < 2; index++) {
                columns[index] = new LinearLayout(this); columns[index].setOrientation(LinearLayout.VERTICAL);
                LinearLayout.LayoutParams placement = new LinearLayout.LayoutParams(0, -2, 1);
                placement.setMargins(index == 0 ? 0 : dp(8), 0, index == 0 ? dp(8) : 0, 0);
                page.addView(columns[index], placement);
            }
            categoryColumns.put(key, columns);
        }
        return page;
    }

    private LinearLayout categoryParent(String key) {
        LinearLayout[] columns = categoryColumns.get(key);
        if (columns == null) return categoryPages.get(key);
        int position = categoryPositions.containsKey(key) ? categoryPositions.get(key) : 0;
        categoryPositions.put(key, position + 1); return columns[position % columns.length];
    }

    private void showCategory(String key) {
        if (!categoryPages.containsKey(key)) key = "console";
        selectedCategory = key;
        for (java.util.Map.Entry<String, LinearLayout> entry : categoryPages.entrySet())
            entry.getValue().setVisibility(key.equals(entry.getKey()) ? View.VISIBLE : View.GONE);
        for (java.util.Map.Entry<String, Button> entry : categoryButtons.entrySet()) {
            boolean selected = key.equals(entry.getKey()); Button control = entry.getValue();
            control.setSelected(selected); control.setTextColor(selected ? 0xffffffff : TEXT_PRIMARY);
            control.setBackgroundTintList(ColorStateList.valueOf(selected ? ACCENT : CONTROL_BACKGROUND));
        }
        if (settingsScroll != null) settingsScroll.smoothScrollTo(0, 0);
    }

    private void addCategoryButton(LinearLayout navigation, String key, int title) {
        Button control = button(title); control.setContentDescription("idoly.nav." + key);
        control.setMinWidth(0); control.setMinimumWidth(0); control.setMaxLines(2);
        control.setPadding(dp(3), dp(8), dp(3), dp(8));
        compactHeaderAction(control, 3);
        navigation.addView(control, wideSettings ? new LinearLayout.LayoutParams(-1, -2)
                : new LinearLayout.LayoutParams(0, -2, 1));
        categoryButtons.put(key, control); control.setOnClickListener(view -> showCategory(key));
    }

    private LinearLayout panel(LinearLayout parent, int title, String key, boolean initiallyOpen) {
        LinearLayout frame = card(parent, 0);
        Button heading = button(title); heading.setContentDescription("idoly.panel." + key);
        heading.setGravity(android.view.Gravity.START | android.view.Gravity.CENTER_VERTICAL);
        frame.addView(heading, new LinearLayout.LayoutParams(-1, -2));
        LinearLayout contents = new LinearLayout(this); contents.setOrientation(LinearLayout.VERTICAL);
        contents.setPadding(0, dp(10), 0, 0); frame.addView(contents, new LinearLayout.LayoutParams(-1, -2));
        boolean expanded = getSharedPreferences(SERVER_PREFS, MODE_PRIVATE).getBoolean("panel_open_" + key, initiallyOpen);
        setPanelExpanded(heading, contents, title, expanded);
        heading.setOnClickListener(view -> {
            boolean open = contents.getVisibility() != View.VISIBLE;
            setPanelExpanded(heading, contents, title, open);
            getSharedPreferences(SERVER_PREFS, MODE_PRIVATE).edit().putBoolean("panel_open_" + key, open).apply();
        });
        return contents;
    }

    private void setPanelExpanded(Button heading, LinearLayout contents, int title, boolean open) {
        heading.setText(getString(title) + (open ? "  ▴" : "  ▾")); heading.setSelected(open);
        contents.setVisibility(open ? View.VISIBLE : View.GONE);
        if (Build.VERSION.SDK_INT >= 30) heading.setStateDescription(getString(open ? R.string.panel_expanded : R.string.panel_collapsed));
    }

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

    private void addHelp(LinearLayout body, int title, int... details) {
        Button help = button(R.string.help_details);
        help.setContentDescription(getString(R.string.help_for, getString(title)));
        help.setOnClickListener(view -> {
            StringBuilder message = new StringBuilder();
            for (int detail : details) {
                if (message.length() > 0) message.append("\n\n");
                message.append(getString(detail));
            }
            new AlertDialog.Builder(this).setTitle(title).setMessage(message.toString())
                    .setPositiveButton(android.R.string.ok, null).show();
        });
        body.addView(help, new LinearLayout.LayoutParams(-1, -2));
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

    private void addNativeHeading(LinearLayout content, boolean compact) {
        TextView heading = text(R.string.app_name, compactHeader ? 18 : compact ? 20 : 25, TEXT_PRIMARY);
        heading.setText(getString(R.string.app_name) + "  " + BuildConfig.VERSION_NAME);
        heading.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        status = text(R.string.status_stopped, compactHeader ? 16 : 21, TEXT_PRIMARY);
        status.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        status.setPadding(dp(compactHeader ? 8 : 14), dp(compactHeader ? 2 : 8),
                dp(compactHeader ? 8 : 14), dp(compactHeader ? 2 : 8));
        GradientDrawable background = new GradientDrawable();
        background.setColor(STATUS_BACKGROUND); background.setCornerRadius(dp(12)); status.setBackground(background);
        if (compactHeader) {
            LinearLayout row = new LinearLayout(this); row.setOrientation(LinearLayout.HORIZONTAL);
            row.setGravity(android.view.Gravity.CENTER_VERTICAL); row.setMinimumHeight(dp(36));
            heading.setMaxLines(1); heading.setEllipsize(TextUtils.TruncateAt.END);
            status.setMinHeight(dp(36)); status.setGravity(android.view.Gravity.CENTER_VERTICAL);
            row.addView(heading, new LinearLayout.LayoutParams(0, -2, 1));
            LinearLayout.LayoutParams statePlacement = new LinearLayout.LayoutParams(-2, -2);
            statePlacement.setMargins(dp(8), 0, 0, 0); row.addView(status, statePlacement);
            content.addView(row, new LinearLayout.LayoutParams(-1, -2));
        } else {
            content.addView(heading);
            content.addView(status, new LinearLayout.LayoutParams(-1, -2));
        }
    }

    private void compactHeaderAction(Button control, int horizontalPadding) {
        if (!compactHeader) return;
        control.setMinHeight(dp(44)); control.setMinimumHeight(dp(44));
        control.setPadding(dp(horizontalPadding), dp(4), dp(horizontalPadding), dp(4));
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
        UnifiedRuntime.installResources(this);
        UnifiedMP4Export.restoreState(this, savedInstanceState);
        if (savedInstanceState != null) {
            pendingResourcePlatform = savedInstanceState.getString("resource_platform");
            retryStartAfterStoragePermission = savedInstanceState.getBoolean("storage_retry", false);
            accountOffset = Math.max(0, savedInstanceState.getInt("account_offset", 0));
            restoreOffset = Math.max(0, savedInstanceState.getInt("restore_offset", 0));
            pendingAccountPicker = restoredAccountPicker(savedInstanceState.getInt("account_picker", 0));
            try {
                String exported = savedInstanceState.getString("account_export"), preview = savedInstanceState.getString("account_preview");
                if (exported != null) pendingAccountExport = new JSONObject(exported);
                if (preview != null) pendingAccountPreview = new JSONObject(preview);
            } catch (org.json.JSONException invalid) { pendingAccountExport = null; pendingAccountPreview = null; }
            // Only the local slot/revision is restorable; no official ID,
            // password, ticket, job preview or authentication state enters Bundle.
            String importedProfile = savedInstanceState.getString("official_local_profile");
            String importedRevision = savedInstanceState.getString("official_local_revision");
            if (importedProfile != null && importedProfile.length() <= 64 && importedRevision != null
                    && importedRevision.matches("[0-9a-f]{64}"))
                officialAppliedAccount = accountPayload("profile", importedProfile, "revision", importedRevision);
            officialWarnings = savedInstanceState.getInt("official_local_warnings", 0) & 3;
            eventsSelectedId = savedInstanceState.getString("events_selected_id", "");
            restoreEventEdits(savedInstanceState, normalEvents);
            restoreEventEdits(savedInstanceState, mediaEvents);
        }
        getWindow().setStatusBarColor(PAGE_BACKGROUND);
        getWindow().setNavigationBarColor(PAGE_BACKGROUND);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR
                | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        boolean compact = getResources().getConfiguration().screenHeightDp < 520;
        compactHeader = compact && getResources().getConfiguration().screenWidthDp
                > getResources().getConfiguration().screenHeightDp;
        // Short landscape windows need horizontal navigation to keep all tabs visible.
        wideSettings = getResources().getConfiguration().screenWidthDp >= 760 && !compact;
        splitSettings = getResources().getConfiguration().screenWidthDp >= 1000;
        if (savedInstanceState != null) selectedCategory = savedInstanceState.getString("settings_category", "console");
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(16), dp(compactHeader ? 4 : compact ? 8 : 12), dp(16), dp(compactHeader ? 4 : 8));
        content.setBackgroundColor(PAGE_BACKGROUND);
        addNativeHeading(content, compact);

        LinearLayout controls = new LinearLayout(this);
        controls.setOrientation(LinearLayout.HORIZONTAL);
        start = button(R.string.start_server);
        primaryButton(start);
        stop = button(R.string.stop_server);
        compactHeaderAction(start, 12); compactHeaderAction(stop, 12);
        LinearLayout.LayoutParams half = new LinearLayout.LayoutParams(0, -2, 1);
        half.setMargins(0, 0, dp(4), 0);
        controls.addView(start, half);
        LinearLayout.LayoutParams otherHalf = new LinearLayout.LayoutParams(0, -2, 1);
        otherHalf.setMargins(dp(4), 0, 0, 0);
        controls.addView(stop, otherHalf);
        Button launch = button(R.string.launch_diagnostic_client);
        primaryButton(launch); compactHeaderAction(launch, 12);
        if (wideSettings || compact) {
            controls.addView(launch, new LinearLayout.LayoutParams(0, -2, 1)); content.addView(controls);
        } else {
            content.addView(controls); content.addView(launch, new LinearLayout.LayoutParams(-1, -2));
        }

        // The settings scroll independently; the single game action stays visible.
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(0, dp(compactHeader ? 4 : 12), 0, 0);
        category(body, "console"); category(body, "server"); category(body, "users");
        category(body, "content"); category(body, "graphics");
        for (String key : new String[]{"server", "content", "graphics"}) {
            TextView automatic = text(R.string.settings_automatic_notice, 16, TEXT_MUTED);
            automatic.setPadding(dp(2), 0, dp(2), dp(compactHeader ? 4 : 12));
            LinearLayout[] columns = categoryColumns.get(key);
            (columns == null ? categoryPages.get(key) : columns[0]).addView(automatic);
        }
        LinearLayout consoleCard = panel(categoryParent("console"), R.string.console_panel_title, "checks", false);
        addServerChecksControls(consoleCard);
        LinearLayout modeCard = panel(categoryParent("server"), R.string.mode_section_title, "mode", true);
        mediaMode = new CheckBox(this);
        mediaMode.setText(R.string.media_mode);
        mediaMode.setContentDescription("idoly.options.media-mode");
        mediaMode.setTextColor(TEXT_PRIMARY);
        mediaMode.setTextSize(13);
        mediaMode.setChecked(getSharedPreferences(SERVER_PREFS, MODE_PRIVATE)
                .getBoolean(MEDIA_MODE, false));
        mediaMode.setOnCheckedChangeListener((button, enabled) -> {
            getSharedPreferences(SERVER_PREFS, MODE_PRIVATE).edit().putBoolean(MEDIA_MODE, enabled).apply();
            if (eventsSummary != null) {
                eventState().refresh = true; syncEventView(); renderEventSettings(); pumpEventRequests();
            }
        });
        modeCard.addView(mediaMode);
        addHelp(modeCard, R.string.mode_section_title, R.string.media_mode_notice, R.string.first_launch_note);

        addAccountControls(panel(categoryParent("users"), R.string.accounts_title, "accounts", false));
        addOfficialImportControls(panel(categoryParent("users"), R.string.official_title, "official", false));
        addEventSettingsControls(panel(categoryParent("content"), R.string.events_title, "events", false));

        LinearLayout libraryCard = panel(categoryParent("content"), R.string.library_settings_title, "library", true);
        addLibraryControls(libraryCard);

        LinearLayout experimentCard = panel(categoryParent("server"), R.string.experiment_section_title, "experimental", false);
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
        addRenderingExperiment(experimentCard);
        addHelp(experimentCard, R.string.experiment_section_title, R.string.experimental_main_live_notice,
                R.string.tutorial_replay_notice, R.string.rendering_mt_notice);

        LinearLayout graphicsCard = panel(categoryParent("graphics"), R.string.graphics_panel_title, "graphics", true);
        addPresentationControls(graphicsCard);
        if (UnifiedRuntime.isEnabled(this)) addMp4Controls(graphicsCard);
        LinearLayout playbackCard = panel(categoryParent("graphics"), R.string.playback_section_title, "playback", true);
        addPlaybackControls(playbackCard);

        LinearLayout resourcesCard = panel(categoryParent("server"), R.string.resources_section_title, "resources", true);
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
        addHelp(resourcesCard, R.string.resources_section_title, R.string.download_missing_resources_notice,
                R.string.resource_storage_public_notice, R.string.resource_storage_private_notice,
                R.string.library_download_parallelism_notice, R.string.library_resources_notice);

        LinearLayout diagnosticsCard = consoleCard;
        gameStatus = text(R.string.game_state_waiting, 13, TEXT_MUTED);
        gameStatus.setTextIsSelectable(true);
        gameStatus.setMaxLines(3);
        gameStatus.setEllipsize(TextUtils.TruncateAt.END);
        gameStatus.setPadding(0, dp(4), 0, dp(8));
        categoryPages.get("console").addView(gameStatus, 0);
        lastException = text(R.string.game_state_waiting, 12, WARNING);
        lastException.setTextIsSelectable(true);
        lastException.setMaxLines(3);
        lastException.setEllipsize(TextUtils.TruncateAt.END);
        lastException.setVisibility(View.GONE);
        categoryPages.get("console").addView(lastException, 1);
        export = button(R.string.export_diagnostics);
        diagnosticsCard.addView(export, new LinearLayout.LayoutParams(-1, -2));
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
        addHelp(diagnosticsCard, R.string.console_panel_title, R.string.console_notice,
                R.string.diagnostics_export_notice);
        settingsScroll = new ScrollView(this); settingsScroll.setFillViewport(true);
        settingsScroll.addView(body, new ScrollView.LayoutParams(-1, -2));
        LinearLayout navigation = new LinearLayout(this);
        navigation.setOrientation(wideSettings ? LinearLayout.VERTICAL : LinearLayout.HORIZONTAL);
        navigation.setPadding(0, dp(compactHeader ? 4 : 8), wideSettings ? dp(12) : 0, 0);
        addCategoryButton(navigation, "console", R.string.nav_console);
        addCategoryButton(navigation, "server", R.string.nav_server);
        addCategoryButton(navigation, "users", R.string.nav_users);
        addCategoryButton(navigation, "content", R.string.nav_content);
        addCategoryButton(navigation, "graphics", R.string.nav_graphics);
        LinearLayout workspace = new LinearLayout(this);
        workspace.setOrientation(wideSettings ? LinearLayout.HORIZONTAL : LinearLayout.VERTICAL);
        workspace.addView(navigation, wideSettings ? new LinearLayout.LayoutParams(dp(160), -1)
                : new LinearLayout.LayoutParams(-1, -2));
        workspace.addView(settingsScroll, wideSettings ? new LinearLayout.LayoutParams(0, -1, 1)
                : new LinearLayout.LayoutParams(-1, 0, 1));
        content.addView(workspace, new LinearLayout.LayoutParams(-1, 0, 1));
        showCategory(selectedCategory);
        readableControls(content);
        setContentView(content);
        // Rebuild this native menu for the new window/density while the service
        // and the back-stack Unity activity keep their existing instances.
        if (savedInstanceState != null) {
            int scrollDp = Math.max(0, savedInstanceState.getInt("settings_scroll_y_dp", 0));
            settingsScroll.post(() -> settingsScroll.scrollTo(0, dp(scrollDp)));
        }

        start.setOnClickListener(view -> requestServerStart());
        stop.setOnClickListener(view -> {
            startAfterEventsSave = false;
            startService(new Intent(this, ServerService.class).setAction(ServerService.ACTION_STOP));
        });
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
            openAccountDocumentPicker(picker, IMPORT_ACCOUNT);
        });
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
        body.addView(accountOperation);
        addHelp(body, R.string.accounts_title, R.string.accounts_notice, R.string.accounts_restore_notice);
        updateAccountControls();
    }

    private boolean shouldPollOfficial() {
        if (officialRequest || ServerService.isImportingOfficial() || officialJob.optBoolean("busy", false)) return true;
        String state = officialJob.optString("state", "idle");
        return "checking".equals(state) || "verified".equals(state)
                || "fetching".equals(state) || "ready".equals(state);
    }

    private void scheduleOfficialRefresh() {
        if (officialStatus == null) return;
        officialStatus.removeCallbacks(officialRefresh);
        // Completed/idle jobs do not change. Repainting them once per second
        // prevents accessibility clients from observing a stable, idle window.
        if (presentationObserved && shouldPollOfficial()) officialStatus.postDelayed(officialRefresh, 2500);
    }

    private Button officialButton(LinearLayout body, int label, String identifier, View.OnClickListener action) {
        Button control = button(label); control.setContentDescription(identifier); control.setOnClickListener(action);
        body.addView(control, new LinearLayout.LayoutParams(-1, -2)); return control;
    }

    private void addOfficialImportControls(LinearLayout body) {
        body.addView(text(R.string.official_warning_short, 16, TEXT_MUTED));
        addHelp(body, R.string.official_title, R.string.official_notice, R.string.official_warning);
        officialStatus = text(R.string.official_stage_idle, 17, TEXT_PRIMARY);
        officialStatus.setContentDescription("idoly.official.status"); body.addView(officialStatus);
        officialProgress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        officialProgress.setIndeterminate(true); officialProgress.setVisibility(View.GONE);
        body.addView(officialProgress, new LinearLayout.LayoutParams(-1, dp(12)));
        officialPreview = text(R.string.official_stage_idle, 16, TEXT_PRIMARY); officialPreview.setTextIsSelectable(true);
        officialPreview.setContentDescription("idoly.official.preview"); body.addView(officialPreview);
        officialInspect = officialButton(body, R.string.official_inspect, "idoly.official.inspect", view -> showOfficialCredentials());
        officialFetch = officialButton(body, R.string.official_fetch, "idoly.official.fetch", view -> {
            String checkedJob = officialJob.optString("job_id");
            showOfficialDialog(new AlertDialog.Builder(this).setTitle(R.string.official_fetch_title)
                    .setMessage(officialPreview.getText() + "\n\n" + getString(R.string.official_warning))
                    .setNegativeButton(android.R.string.cancel, null)
                    .setPositiveButton(R.string.official_fetch, (dialog, which) ->
                            requestOfficial("official_fetch", accountPayload("job_id", checkedJob), false)).create());
        });
        officialNew = officialButton(body, R.string.official_apply_new, "idoly.official.apply-new", view -> showOfficialLocalName());
        officialReplace = officialButton(body, R.string.official_apply_replace, "idoly.official.apply-replace", view -> replaceOfficialAccount());
        officialCancel = officialButton(body, R.string.official_cancel, "idoly.official.cancel", view ->
                requestOfficial("official_cancel", accountPayload("job_id", officialJob.optString("job_id")), false));
        officialSelect = officialButton(body, R.string.official_select_imported, "idoly.official.select", view -> {
            if (officialAppliedAccount == null) return;
            performAccount("accounts_select", accountPayload("mode", "normal", "profile", officialAppliedAccount.optString("profile"),
                    "expected_revision", officialAppliedAccount.optString("revision"),
                    "selection_revision", accountStatus.optString("selection_revision")));
        });
        officialNormal = officialButton(body, R.string.official_normal_mode, "idoly.official.normal-mode", view -> {
            if (presentationServerRunning || accountLifecycleBusy) {
                Toast.makeText(this, R.string.official_replace_blocked, Toast.LENGTH_LONG).show(); return;
            }
            // This is an explicit user action, separate from saving or selecting an account.
            mediaMode.setChecked(false);
            Toast.makeText(this, R.string.official_normal_selected, Toast.LENGTH_LONG).show();
        });
        officialLocalRefresh = officialButton(body, R.string.official_refresh_local, "idoly.official.refresh-local", view -> refreshAccounts());
        renderOfficialJob();
    }

    private void showOfficialDialog(AlertDialog dialog) {
        officialWizardDialog = dialog;
        dialog.setOnDismissListener(ignored -> officialWizardDialog = null);
        dialog.show();
    }

    private EditText officialSecretField(int hint, boolean password, int maximum) {
        EditText control = new EditText(this); control.setHint(hint); control.setSingleLine(true);
        control.setTextSize(16); control.setTextColor(TEXT_PRIMARY); control.setHintTextColor(TEXT_MUTED);
        control.setInputType(InputType.TYPE_CLASS_TEXT | (password ? InputType.TYPE_TEXT_VARIATION_PASSWORD : InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD));
        control.setFilters(new InputFilter[]{new InputFilter.LengthFilter(maximum)});
        control.setImeOptions(EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING);
        control.setSaveEnabled(false); control.setFreezesText(false);
        if (Build.VERSION.SDK_INT >= 26) control.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);
        control.setPadding(dp(8), dp(8), dp(8), dp(8)); return control;
    }

    private static void clearOfficialInput(EditText id, EditText password) {
        id.getText().clear(); password.getText().clear();
        id.setText(""); password.setText("");
    }

    private static boolean validOfficialPassword(String value) {
        if (value.length() < 1 || value.length() > 128 || value.charAt(0) == ' ' || value.charAt(value.length() - 1) == ' ') return false;
        for (int index = 0; index < value.length(); index++)
            if (value.charAt(index) < 32 || value.charAt(index) > 126) return false;
        return true;
    }

    private void showOfficialCredentials() {
        if ((officialRequest && !officialPolling) || officialDeferredPayload != null || officialJob.optBoolean("busy", false)) return;
        LinearLayout fields = new LinearLayout(this); fields.setOrientation(LinearLayout.VERTICAL);
        fields.setPadding(dp(20), dp(8), dp(20), dp(8)); fields.setSaveEnabled(false);
        fields.addView(text(R.string.official_warning, 15, TEXT_MUTED));
        fields.addView(text(R.string.official_id_label, 16, TEXT_PRIMARY));
        EditText identifier = officialSecretField(R.string.official_id_hint, false, 64);
        identifier.setContentDescription("idoly.official.user-id"); fields.addView(identifier);
        fields.addView(text(R.string.official_password_label, 16, TEXT_PRIMARY));
        EditText password = officialSecretField(R.string.official_password_hint, true, 128);
        password.setContentDescription("idoly.official.password"); fields.addView(password);
        fields.addView(text(R.string.official_platform_label, 16, TEXT_PRIMARY));
        Spinner platform = new Spinner(this); platform.setContentDescription("idoly.official.platform");
        platform.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, new String[]{"Android", "iPhone / iPad"}));
        fields.addView(platform);
        ScrollView scroll = new ScrollView(this); scroll.addView(fields);
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle(R.string.official_credentials_title).setView(scroll)
                .setNegativeButton(android.R.string.cancel, null).setPositiveButton(R.string.official_confirm_inspect, null).create();
        officialCredentials = dialog;
        dialog.setOnDismissListener(ignored -> { clearOfficialInput(identifier, password); officialCredentials = null; });
        dialog.setOnShowListener(ignored -> {
            if (dialog.getWindow() != null) dialog.getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(view -> {
                String userId = identifier.getText().toString(), secret = password.getText().toString();
                clearOfficialInput(identifier, password);
                if (!userId.matches("[A-Za-z0-9_-]{1,64}") || !validOfficialPassword(secret)) {
                    Toast.makeText(this, R.string.official_error_input, Toast.LENGTH_LONG).show(); return;
                }
                JSONObject request = accountPayload("user_id", userId, "password", secret,
                        "platform", platform.getSelectedItemPosition() == 1 ? "ios" : "android");
                dialog.dismiss(); requestOfficial("official_inspect", request, false);
            });
        });
        dialog.show();
    }

    private void showOfficialLocalName() {
        EditText name = new EditText(this); name.setSingleLine(true); name.setHint(R.string.official_slot_hint);
        name.setContentDescription("idoly.official.profile-input"); name.setSaveEnabled(false);
        name.setFilters(new InputFilter[]{new InputFilter.LengthFilter(64)});
        showOfficialDialog(new AlertDialog.Builder(this).setTitle(R.string.official_choose_slot).setView(name)
                .setMessage(R.string.official_ready_notice).setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(R.string.official_apply_confirm, (dialog, which) -> {
                    String profile = name.getText().toString(); name.getText().clear();
                    if (profile.isEmpty() || profile.getBytes(java.nio.charset.StandardCharsets.UTF_8).length > 64
                            || profile.indexOf('/') >= 0 || profile.indexOf('\\') >= 0
                            || profile.codePoints().anyMatch(Character::isISOControl)) {
                        Toast.makeText(this, R.string.official_slot_invalid, Toast.LENGTH_LONG).show(); return;
                    }
                    requestOfficial("official_apply", accountPayload("job_id", officialJob.optString("job_id"),
                            "profile", profile, "replace", false, "expected_revision", null), false);
                }).create());
    }

    private void replaceOfficialAccount() {
        if (presentationServerRunning || accountLifecycleBusy) {
            Toast.makeText(this, R.string.official_replace_blocked, Toast.LENGTH_LONG).show(); return;
        }
        JSONObject row = selectedAccount();
        if (row == null || !"normal".equals(row.optString("mode"))) {
            Toast.makeText(this, R.string.official_choose_normal, Toast.LENGTH_LONG).show(); return;
        }
        String profile = row.optString("profile"), revision = row.optString("revision");
        showOfficialDialog(new AlertDialog.Builder(this).setTitle(R.string.official_apply_replace)
                .setMessage(getString(R.string.official_replace_confirm, profile)).setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(R.string.official_apply_confirm, (dialog, which) ->
                        requestOfficial("official_apply", accountPayload("job_id", officialJob.optString("job_id"),
                                "profile", profile, "replace", true, "expected_revision", revision), false)).create());
    }

    private boolean deferOfficialSubmission(String action, JSONObject payload, boolean poll) {
        if (poll || !officialRequest || !officialPolling || officialDeferredPayload != null) return false;
        officialDeferredAction = action; officialDeferredPayload = payload;
        updateOfficialControls(); return true;
    }

    private void clearDeferredOfficial() {
        if (officialDeferredPayload != null) {
            officialDeferredPayload.remove("password"); officialDeferredPayload.remove("user_id");
        }
        officialDeferredPayload = null; officialDeferredAction = null; officialRenderedJob = null;
    }

    private void drainDeferredOfficial() {
        if (officialDeferredPayload == null || !presentationObserved) return;
        JSONObject payload = officialDeferredPayload; String action = officialDeferredAction;
        officialDeferredPayload = null; officialDeferredAction = null;
        requestOfficial(action, payload, false);
    }

    private void requestOfficial(String action, JSONObject payload, boolean poll) {
        // A real user action takes the next slot after a harmless status read.
        // There is only one transient pending submission; it is cleared on stop.
        if (deferOfficialSubmission(action, payload, poll)) return;
        if (officialRequest || ServerService.isImportingOfficial() || officialDeferredPayload != null) {
            payload.remove("password"); payload.remove("user_id"); return;
        }
        if ("official_inspect".equals(action)) { officialAppliedAccount = null; officialWarnings = 0; }
        if (!poll) officialLastError = 0;
        officialPolling = poll; officialRequest = true;
        if (!poll) {
            officialRenderedJob = null;
            officialStatus.setText("official_inspect".equals(action) ? R.string.official_stage_checking
                    : "official_fetch".equals(action) ? R.string.official_stage_fetching
                    : "official_apply".equals(action) ? R.string.official_stage_staging : R.string.official_stage_preparing);
            officialStatus.setTextColor(TEXT_PRIMARY);
        }
        updateOfficialControls();
        ServerService.officialImport(getApplicationContext(), action, payload, result -> {
            officialRequest = false; officialPolling = false;
            if (isFinishing() || isDestroyed()) { clearDeferredOfficial(); return; }
            if (!result.optBoolean("ok", false)) {
                if (!poll) { officialLastError = officialError(result.optString("error"));
                    officialStatus.setText(officialLastError); officialStatus.setTextColor(WARNING); }
                updateOfficialControls(); scheduleOfficialRefresh(); drainDeferredOfficial(); return;
            }
            JSONObject job = result.optJSONObject("job"); if (job != null) officialJob = job;
            JSONObject active = result.optJSONObject("active"); if (active != null) activeAccount = active;
            if ("official_apply".equals(action)) {
                JSONObject imported = result.optJSONObject("account");
                if (imported != null) officialAppliedAccount = accountPayload("profile", imported.optString("profile"), "revision", imported.optString("revision"));
                officialWarnings = result.optBoolean("status_refresh_required", false) ? OFFICIAL_WARNING_REFRESH : 0;
                org.json.JSONArray notices = result.optJSONArray("warning_codes");
                if (notices != null) for (int index = 0; index < Math.min(8, notices.length()); index++) {
                    String code = notices.optString(index, "");
                    if ("account_temporary_cleanup_pending".equals(code)) officialWarnings |= OFFICIAL_WARNING_CLEANUP;
                    if ("account_status_refresh_required".equals(code)) officialWarnings |= OFFICIAL_WARNING_REFRESH;
                }
                // The account is already committed. Only reread local metadata;
                // never authenticate, fetch, or apply the official transfer again.
                JSONObject accounts = result.optJSONObject("status");
                if (accounts != null && (officialWarnings & OFFICIAL_WARNING_REFRESH) == 0) renderAccounts(accounts);
                refreshAccounts();
            }
            renderOfficialJob(); drainDeferredOfficial();
        });
    }

    private int officialError(String code) {
        if ("official_active_restart_required".equals(code)) return R.string.official_replace_blocked;
        if ("official_job_missing".equals(code) || code.contains("expired") || code.contains("cancelled")) return R.string.official_error_expired;
        if (code.contains("revision") || code.contains("stale")) return R.string.official_error_stale;
        if (code.contains("credential") || code.contains("password") || code.contains("user_id") || "official_request_invalid".equals(code)) return R.string.official_error_input;
        if (code.contains("catalog") || code.contains("master") || code.contains("schema")) return R.string.official_error_catalog;
        return R.string.official_error_generic;
    }

    private int officialStage(String stage) {
        switch (stage) {
            case "idle": return R.string.official_stage_idle;
            case "checking": return R.string.official_stage_checking;
            case "verifying": return R.string.official_stage_verifying;
            case "verified": return R.string.official_stage_verified;
            case "transferring": return R.string.official_stage_transferring;
            case "firebase": return R.string.official_stage_firebase;
            case "login": return R.string.official_stage_login;
            case "master": return R.string.official_stage_master;
            case "account": return R.string.official_stage_account;
            case "collected": return R.string.official_stage_collected;
            case "fetching": return R.string.official_stage_fetching;
            case "catalog_check": return R.string.official_stage_catalog_check;
            case "staging": return R.string.official_stage_staging;
            case "applying": return R.string.official_stage_applying;
            case "ready": return R.string.official_stage_ready;
            case "completed": return R.string.official_stage_completed;
            case "cancelled": return R.string.official_stage_cancelled;
            case "failed": return R.string.official_stage_failed;
            default: return R.string.official_stage_preparing;
        }
    }

    private boolean officialJobChanged() {
        // Time-to-expiry is informative, not structural: its countdown alone
        // must not repaint the screen or emit accessibility content changes.
        String key = accountPayload("state", officialJob.optString("state", "idle"),
                "job_id", officialJob.optString("job_id"), "progress", officialJob.optString("progress"),
                "error_code", officialJob.optString("error_code"), "busy", officialJob.optBoolean("busy", false),
                "counts", officialJob.optJSONObject("counts"), "preview", officialJob.optJSONObject("preview"),
                "local_account", officialAppliedAccount, "local_warnings", officialWarnings,
                "selection_revision", accountStatus.optString("selection_revision"),
                "selected", accountStatus.optJSONObject("selected"), "target", selectedAccount(),
                "media_mode", mediaMode != null && mediaMode.isChecked(), "local_error", officialLastError).toString();
        if (key.equals(officialRenderedJob)) return false;
        officialRenderedJob = key; return true;
    }

    private void renderOfficialJob() {
        if (officialStatus == null) return;
        if (!officialJobChanged()) { scheduleOfficialRefresh(); return; }
        String state = officialJob.optString("state", "idle");
        officialStatus.setText(officialStage(officialJob.optString("progress", state)));
        officialStatus.setTextColor("failed".equals(state) ? WARNING : TEXT_PRIMARY);
        if ("failed".equals(state)) officialStatus.setText(officialError(officialJob.optString("error_code")));
        if (officialLastError != 0) { officialStatus.setText(officialLastError); officialStatus.setTextColor(WARNING); }
        JSONObject preview = officialJob.optJSONObject("preview");
        StringBuilder summary = new StringBuilder();
        if (preview != null) {
            summary.append(getString(R.string.official_preview, preview.optString("manager_name"),
                    preview.optInt("manager_level"), preview.optString("public_id")));
            JSONObject inventory = preview.optJSONObject("inventory");
            if (inventory != null) summary.append("\n").append(getString(R.string.official_counts,
                    inventory.optInt("cards"), inventory.optInt("items"), inventory.optInt("photos")));
        }
        int expiry = officialJob.optInt("expires_in_seconds", 0);
        if (expiry > 0) summary.append("\n").append(getString(R.string.official_expiry));
        if (officialAppliedAccount != null) summary.append("\n").append(getString(R.string.official_completed_short));
        if ((officialWarnings & OFFICIAL_WARNING_CLEANUP) != 0) summary.append("\n").append(getString(R.string.official_committed_cleanup));
        if ((officialWarnings & OFFICIAL_WARNING_REFRESH) != 0) summary.append("\n").append(getString(R.string.official_committed_refresh));
        officialPreview.setText(summary.toString().trim()); updateOfficialControls(); scheduleOfficialRefresh();
    }

    private void updateOfficialControls() {
        if (officialInspect == null) return;
        String state = officialJob.optString("state", "idle");
        boolean pending = officialDeferredPayload != null
                || ((officialRequest || ServerService.isImportingOfficial()) && !officialPolling);
        boolean working = officialJob.optBoolean("busy", false);
        boolean ready = "ready".equals(state) && !working && !pending;
        officialInspect.setEnabled(!working && !pending);
        officialFetch.setEnabled("verified".equals(state) && !working && !pending);
        officialNew.setEnabled(ready && !ServerService.isManagingAccounts() && !accountLifecycleBusy);
        officialReplace.setEnabled(ready && !presentationServerRunning && !accountLifecycleBusy && !ServerService.isManagingAccounts());
        officialCancel.setEnabled(!pending && !officialJob.optString("job_id").isEmpty()
                && (working || "verified".equals(state) || "ready".equals(state)));
        boolean imported = officialAppliedAccount != null;
        officialSelect.setVisibility(imported ? View.VISIBLE : View.GONE); officialNormal.setVisibility(imported ? View.VISIBLE : View.GONE);
        officialSelect.setEnabled(imported && !pending && !ServerService.isManagingAccounts() && !accountLifecycleBusy);
        officialNormal.setEnabled(imported && !pending && !presentationServerRunning && !accountLifecycleBusy);
        officialLocalRefresh.setVisibility((officialWarnings & OFFICIAL_WARNING_REFRESH) != 0 ? View.VISIBLE : View.GONE);
        officialLocalRefresh.setEnabled(!ServerService.isManagingAccounts() && !accountLifecycleBusy);
        officialProgress.setVisibility((pending && !officialPolling) || working ? View.VISIBLE : View.GONE);
    }

    private EventUiState eventState() { return mediaMode != null && mediaMode.isChecked() ? mediaEvents : normalEvents; }

    private JSONObject eventSettingsJson(EventSelectionDraft selection, java.util.Map<String, EventSelectionDraft.Window> windows) {
        org.json.JSONArray rows = new org.json.JSONArray();
        for (java.util.Map.Entry<String, EventSelectionDraft.Window> entry : windows.entrySet()) {
            EventSelectionDraft.Window window = entry.getValue();
            rows.put(accountPayload("event_id", entry.getKey(), "start_time_ms", window.start, "end_time_ms", window.end));
        }
        return accountPayload("schema", 1, "revision", selection.revision(), "love_events", rows);
    }

    private void syncEventView() {
        EventUiState current = eventState();
        eventsSnapshot = current.snapshot;
        eventsDraft = eventSettingsJson(current.selection, current.selection.rows());
        eventsLoaded = current.selection.loaded(); eventsUnsaved = current.selection.dirty(); eventsError = current.error;
    }

    private void restoreEventEdits(Bundle state, EventUiState target) {
        String encoded = state.getString(target.media ? "events_media_edits" : "events_normal_edits");
        if (encoded == null || encoded.length() > 32768) return;
        try {
            org.json.JSONArray rows = new org.json.JSONArray(encoded);
            if (rows.length() > 64) return;
            for (int index = 0; index < rows.length(); index++) {
                JSONObject row = rows.getJSONObject(index);
                target.selection.edit(row.getString("event_id"), row.optBoolean("remove") ? null
                        : new EventSelectionDraft.Window(row.getLong("start_time_ms"), row.getLong("end_time_ms")));
            }
        } catch (org.json.JSONException | IllegalArgumentException invalid) { target.error = "event_settings_invalid"; target.blocked = true; }
    }

    private void saveEventEdits(Bundle state, EventUiState source) {
        org.json.JSONArray rows = new org.json.JSONArray();
        for (java.util.Map.Entry<String, EventSelectionDraft.Window> entry : source.selection.pending().entrySet()) {
            EventSelectionDraft.Window value = entry.getValue();
            rows.put(value == null ? accountPayload("event_id", entry.getKey(), "remove", true)
                    : accountPayload("event_id", entry.getKey(), "start_time_ms", value.start, "end_time_ms", value.end));
        }
        if (rows.length() > 0) state.putString(source.media ? "events_media_edits" : "events_normal_edits", rows.toString());
    }

    private void addEventSettingsControls(LinearLayout body) {
        eventsModeNotice = text(R.string.events_normal_short, 16, TEXT_MUTED); body.addView(eventsModeNotice);
        eventsSummary = text(R.string.events_loading, 17, TEXT_PRIMARY);
        eventsSummary.setContentDescription("idoly.events.status"); body.addView(eventsSummary);
        body.addView(text(R.string.events_catalog, 16, TEXT_PRIMARY));
        eventsChoices = new LinearLayout(this); eventsChoices.setOrientation(LinearLayout.VERTICAL);
        eventsChoices.setContentDescription("idoly.events.list"); body.addView(eventsChoices);
        LinearLayout bulk = new LinearLayout(this); bulk.setOrientation(LinearLayout.HORIZONTAL);
        eventsAll = button(R.string.events_enable_all); eventsAll.setContentDescription("idoly.events.enable-all");
        eventsOff = button(R.string.events_disable_all); eventsOff.setContentDescription("idoly.events.disable-all");
        bulk.addView(eventsAll, new LinearLayout.LayoutParams(0, -2, 1));
        bulk.addView(eventsOff, new LinearLayout.LayoutParams(0, -2, 1)); body.addView(bulk);
        eventsAll.setOnClickListener(view -> setAllEvents(true)); eventsOff.setOnClickListener(view -> setAllEvents(false));
        eventsSchedule = new LinearLayout(this); eventsSchedule.setOrientation(LinearLayout.VERTICAL); body.addView(eventsSchedule);
        eventsSchedule.addView(text(R.string.events_schedule_editor, 16, TEXT_MUTED));
        eventsPicker = new Spinner(this); eventsPicker.setContentDescription("idoly.events.catalog");
        eventsSchedule.addView(eventsPicker, new LinearLayout.LayoutParams(-1, dp(52)));
        eventsPicker.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                if (eventsLoading) return;
                JSONObject row = eventsCatalog.optJSONObject(position);
                String selected = row == null ? "" : row.optString("id");
                if (!selected.equals(eventsSelectedId)) { eventsSelectedId = selected; renderSelectedEvent(); }
            }
            @Override public void onNothingSelected(AdapterView<?> parent) {}
        });
        eventsEnabled = new CheckBox(this); eventsEnabled.setText(R.string.events_enabled);
        eventsEnabled.setTextSize(16); eventsEnabled.setTextColor(TEXT_PRIMARY);
        eventsEnabled.setContentDescription("idoly.events.enabled"); eventsSchedule.addView(eventsEnabled);
        eventsEnabled.setOnCheckedChangeListener((control, enabled) -> {
            if (eventsLoading || eventsSelectedId.isEmpty()) return;
            changeEventSelection(eventsSelectedId, enabled);
        });
        eventsStart = button(R.string.events_start_name); eventsStart.setContentDescription("idoly.events.start");
        eventsEnd = button(R.string.events_end_name); eventsEnd.setContentDescription("idoly.events.end");
        eventsStart.setOnClickListener(view -> editEventTime(true)); eventsEnd.setOnClickListener(view -> editEventTime(false));
        eventsSchedule.addView(eventsStart); eventsSchedule.addView(eventsEnd);
        eventsSelected = text(R.string.events_off, 16, TEXT_MUTED);
        eventsSelected.setContentDescription("idoly.events.applied"); body.addView(eventsSelected);
        eventsNotice = text(R.string.events_loading, 16, TEXT_MUTED); body.addView(eventsNotice);
        eventsReload = button(R.string.events_refresh); eventsReload.setContentDescription("idoly.events.reload");
        eventsReload.setOnClickListener(view -> {
            EventUiState state = eventState(); state.blocked = false; state.conflictRetries = 0;
            state.refresh = true; state.error = ""; syncEventView(); renderEventSettings(); pumpEventRequests();
        }); body.addView(eventsReload);
        addHelp(body, R.string.events_title, R.string.events_notice, R.string.events_preset_notice,
                R.string.events_media_notice, R.string.events_start_notice);
        syncEventView(); renderEventSettings();
    }

    private JSONObject savedEventSettings() {
        JSONObject value = eventsSnapshot.optJSONObject("saved");
        return value == null ? accountPayload("schema", 1, "revision", 0, "love_events", new org.json.JSONArray()) : value;
    }

    private static JSONObject eventEntry(JSONObject settings, String identifier) {
        org.json.JSONArray entries = settings == null ? null : settings.optJSONArray("love_events");
        if (entries != null) for (int index = 0; index < entries.length(); index++) {
            JSONObject entry = entries.optJSONObject(index);
            if (entry != null && identifier.equals(entry.optString("event_id"))) return entry;
        }
        return null;
    }

    private static int eventCount(JSONObject settings) {
        org.json.JSONArray entries = settings == null ? null : settings.optJSONArray("love_events");
        return entries == null ? 0 : entries.length();
    }

    private JSONObject effectiveEventSettings() {
        return presentationServerRunning ? eventsSnapshot.optJSONObject("effective") : null;
    }

    private String eventTime(long milliseconds) {
        java.util.Date date = new java.util.Date(milliseconds);
        return android.text.format.DateFormat.getMediumDateFormat(this).format(date) + " "
                + android.text.format.DateFormat.getTimeFormat(this).format(date);
    }

    private String eventWindowText(JSONObject entry) {
        if (entry == null) return getString(R.string.events_off);
        if (entry.optLong("start_time_ms") == 0 && entry.optLong("end_time_ms") == 0) return getString(R.string.events_always);
        return getString(R.string.events_window, eventTime(entry.optLong("start_time_ms")), eventTime(entry.optLong("end_time_ms")));
    }

    private void renderSelectedEvent() {
        if (eventsEnabled == null) return;
        eventsLoading = true;
        JSONObject draft = eventEntry(eventsDraft, eventsSelectedId);
        eventsEnabled.setChecked(draft != null);
        eventsStart.setText(getString(R.string.events_start, draft == null ? getString(R.string.events_off) : eventTime(draft.optLong("start_time_ms"))));
        eventsEnd.setText(getString(R.string.events_end, draft == null ? getString(R.string.events_off) : eventTime(draft.optLong("end_time_ms"))));
        JSONObject effective = effectiveEventSettings();
        eventsSelected.setText(getString(R.string.events_current_short, effective == null ? getString(R.string.events_not_running)
                : getString(eventEntry(effective, eventsSelectedId) == null ? R.string.events_off : R.string.events_on)));
        eventsLoading = false; updateEventSettingsControls();
    }

    private String eventTitle(JSONObject row) {
        JSONObject titles = row.optJSONObject("titles");
        String language = Locale.getDefault().getLanguage();
        String translated = titles == null ? "" : titles.optString(language);
        return !translated.isEmpty() ? translated : row.optString("title", row.optString("id"));
    }

    private String eventRenderKey() {
        return eventState().media + "|" + eventsSnapshot.toString() + "|" + String.valueOf(eventsDraft)
                + "|" + eventsError + "|" + eventsUnsaved + "|" + eventsSelectedId + "|" + eventsLoaded
                + "|" + presentationServerRunning + "|" + (eventsRequest && eventsRequestState == eventState())
                + "|" + eventsSaving + "|" + Locale.getDefault().getLanguage();
    }

    private void renderEventSettings() {
        if (eventsSummary == null) return;
        syncEventView();
        if (eventRenderKey().equals(eventsRenderedKey)) { updateEventSettingsControls(); return; }
        eventsLoading = true;
        JSONObject catalog = eventsSnapshot.optJSONObject("catalog");
        org.json.JSONArray source = catalog == null ? null : catalog.optJSONArray("events");
        org.json.JSONArray visible = new org.json.JSONArray(); java.util.ArrayList<String> labels = new java.util.ArrayList<>();
        StringBuilder catalogKey = new StringBuilder(); int selectedIndex = 0;
        if (source != null && catalog.optBoolean("available", false)) for (int index = 0; index < source.length(); index++) {
            JSONObject row = source.optJSONObject(index);
            if (row == null || !row.optBoolean("supported", false) || row.optString("id").isEmpty()) continue;
            if (row.optString("id").equals(eventsSelectedId)) selectedIndex = labels.size();
            visible.put(row); String title = eventTitle(row); labels.add(title);
            catalogKey.append(row.optString("id")).append('|').append(title).append('\n');
        }
        eventsCatalog = visible;
        if (labels.isEmpty()) { labels.add(getString(R.string.events_empty)); eventsSelectedId = ""; }
        else eventsSelectedId = eventsCatalog.optJSONObject(selectedIndex).optString("id");
        // Status polling and save acknowledgements must not recreate a live picker.
        if (!catalogKey.toString().equals(eventsCatalogKey)) {
            eventsCatalogKey = catalogKey.toString(); eventsChoices.removeAllViews(); eventChecks.clear();
            for (int index = 0; index < visible.length(); index++) {
                JSONObject row = visible.optJSONObject(index); final String identifier = row.optString("id");
                CheckBox choice = new CheckBox(this); choice.setText(eventTitle(row)); choice.setTextSize(16);
                choice.setTextColor(TEXT_PRIMARY); choice.setMinHeight(dp(52)); choice.setPadding(dp(4), dp(8), dp(4), dp(8));
                choice.setButtonTintList(new ColorStateList(ENABLED_STATES, new int[]{TEXT_MUTED, ACCENT}));
                choice.setContentDescription("idoly.events.toggle." + identifier);
                choice.setOnCheckedChangeListener((view, checked) -> { if (!eventsLoading) changeEventSelection(identifier, checked); });
                eventsChoices.addView(choice, new LinearLayout.LayoutParams(-1, -2)); eventChecks.put(identifier, choice);
                if ("love-extra-25-0426".equals(identifier)) {
                    TextView entry = text(R.string.events_extra_entry, 14, TEXT_MUTED);
                    entry.setPadding(dp(42), 0, dp(8), dp(12));
                    entry.setContentDescription("idoly.events.extra_entry");
                    eventsChoices.addView(entry, new LinearLayout.LayoutParams(-1, -2));
                }
            }
            eventsPicker.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, labels));
            eventsPicker.setSelection(selectedIndex);
        }
        for (java.util.Map.Entry<String, CheckBox> row : eventChecks.entrySet())
            row.getValue().setChecked(eventEntry(eventsDraft, row.getKey()) != null);
        boolean media = eventState().media;
        eventsSchedule.setVisibility(media ? View.GONE : View.VISIBLE);
        eventsModeNotice.setText(media ? R.string.events_media_short : R.string.events_normal_short);
        JSONObject effective = effectiveEventSettings();
        int state = effective == null ? R.string.events_saved_next : eventsSnapshot.optBoolean("restart_required", false)
                ? R.string.events_restart : R.string.events_saved_active;
        if (!eventsLoaded) eventsSummary.setText(eventsError.isEmpty() ? R.string.events_loading : R.string.events_error_storage);
        else if (eventsRequest && eventsSaving && eventsRequestState == eventState()) eventsSummary.setText(R.string.events_pending);
        else if (eventsSnapshot.optBoolean("invalid_settings_file", false)) eventsSummary.setText(R.string.events_invalid_file);
        else eventsSummary.setText(getString(R.string.events_summary, getString(state), eventCount(savedEventSettings()),
                effective == null ? getString(R.string.events_not_running) : getString(R.string.events_count, eventCount(effective))));
        String notice = eventsSnapshot.optBoolean("invalid_settings_file", false) ? getString(R.string.events_invalid_file)
                : !eventsError.isEmpty() ? getString(eventSettingsError(eventsError))
                : catalog == null || !catalog.optBoolean("available", false) ? getString(R.string.events_unavailable)
                : eventsUnsaved && !(eventsRequest && eventsRequestState == eventState()) ? getString(R.string.events_unsaved) : "";
        eventsNotice.setText(notice); eventsNotice.setVisibility(notice.isEmpty() ? View.GONE : View.VISIBLE);
        eventsNotice.setTextColor(eventsError.isEmpty() ? TEXT_MUTED : WARNING);
        eventsReload.setText(eventsUnsaved ? R.string.events_retry_save : R.string.events_refresh);
        eventsLoading = false; renderSelectedEvent();
        eventsRenderedKey = eventRenderKey();
    }

    private void updateEventSettingsControls() {
        if (eventsPicker == null) return;
        boolean valid = eventsLoaded && !eventsSnapshot.optBoolean("invalid_settings_file", false);
        boolean supported = eventsCatalog.length() > 0;
        boolean editable = valid && supported;
        eventsPicker.setEnabled(editable);
        eventsEnabled.setEnabled(editable);
        for (CheckBox choice : eventChecks.values()) choice.setEnabled(editable);
        boolean enabled = eventEntry(eventsDraft, eventsSelectedId) != null;
        eventsStart.setEnabled(editable && enabled); eventsEnd.setEnabled(editable && enabled);
        eventsReload.setEnabled(!eventsRequest);
        eventsAll.setEnabled(editable);
        eventsOff.setEnabled(valid && (eventCount(savedEventSettings()) > 0 || eventCount(eventsDraft) > 0));
    }

    private void refreshEventSettings(boolean discardDraft) {
        EventUiState state = eventState();
        // Explicit retry always retains per-event intent, including across modes.
        state.refresh = true; state.blocked = false; state.conflictRetries = 0;
        pumpEventRequests();
    }

    private void changeEventSelection(String identifier, boolean enabled) {
        try {
            EventUiState state = eventState(); EventSelectionDraft.Window previous = state.selection.rows().get(identifier);
            long[] window = !enabled ? null : state.media ? new long[]{0, 0}
                    : previous == null ? EventWindow.preset(System.currentTimeMillis()) : new long[]{previous.start, previous.end};
            saveEventEntry(identifier, window);
        } catch (IllegalArgumentException invalid) {
            Toast.makeText(this, R.string.events_error_invalid, Toast.LENGTH_LONG).show(); renderEventSettings();
        }
    }

    private void setAllEvents(boolean enabled) {
        EventUiState state = eventState();
        try {
            if (enabled) {
                long[] window = state.media ? new long[]{0, 0} : EventWindow.preset(System.currentTimeMillis());
                for (int index = 0; index < eventsCatalog.length(); index++) {
                    String id = eventsCatalog.optJSONObject(index).optString("id");
                    if (!state.selection.rows().containsKey(id)) state.selection.edit(id, new EventSelectionDraft.Window(window[0], window[1]));
                }
            } else {
                for (String id : new java.util.ArrayList<>(state.selection.rows().keySet())) state.selection.edit(id, null);
            }
            state.blocked = false; state.error = ""; state.conflictRetries = 0;
            renderEventSettings(); pumpEventRequests();
        } catch (IllegalArgumentException invalid) { Toast.makeText(this, R.string.events_error_invalid, Toast.LENGTH_LONG).show(); }
    }

    private void saveEventEntry(String identifier, long[] window) { saveEventEntry(eventState(), identifier, window); }

    private void saveEventEntry(EventUiState state, String identifier, long[] window) {
        state.selection.edit(identifier, window == null ? null : new EventSelectionDraft.Window(window[0], window[1]));
        state.blocked = false; state.error = ""; state.conflictRetries = 0;
        renderEventSettings(); pumpEventRequests();
    }

    private java.util.Map<String, EventSelectionDraft.Window> eventRows(JSONObject settings) throws org.json.JSONException {
        java.util.TreeMap<String, EventSelectionDraft.Window> rows = new java.util.TreeMap<>();
        org.json.JSONArray entries = settings.getJSONArray("love_events");
        for (int index = 0; index < entries.length(); index++) {
            JSONObject row = entries.getJSONObject(index); String identifier = row.getString("event_id");
            if (rows.containsKey(identifier)) throw new IllegalArgumentException("event_settings_invalid");
            rows.put(identifier, new EventSelectionDraft.Window(row.getLong("start_time_ms"), row.getLong("end_time_ms")));
        }
        return rows;
    }

    private void observeEventSettings(EventUiState state, JSONObject observed, EventSelectionDraft.Save sent) throws org.json.JSONException {
        if (observed.has("media_mode") && observed.optBoolean("media_mode") != state.media)
            throw new IllegalArgumentException("event_settings_invalid");
        JSONObject saved = observed.getJSONObject("saved");
        java.util.Map<String, EventSelectionDraft.Window> rows = eventRows(saved);
        if (sent == null) state.selection.observe(saved.getLong("revision"), rows);
        else state.selection.acknowledge(saved.getLong("revision"), rows, sent);
        state.snapshot = observed;
    }

    private void pumpEventRequests() {
        if (eventsSummary == null || eventsRequest || isFinishing() || isDestroyed()) return;
        if (ServerService.isManagingEventSettings()) {
            if (++eventsBusyRetries <= 20) eventsSummary.postDelayed(this::pumpEventRequests, 150);
            else { eventState().error = "event_settings_busy"; renderEventSettings(); }
            return;
        }
        eventsBusyRetries = 0;
        EventUiState first = eventState(), second = first == normalEvents ? mediaEvents : normalEvents;
        for (EventUiState state : new EventUiState[]{first, second}) {
            if (state.refresh && (state == first || state.selection.dirty())) {
                state.refresh = false; requestEventSettings(state, "events_status", null); return;
            }
            if (state.selection.loaded() && state.selection.dirty() && !state.blocked) {
                requestEventSettings(state, "events_save", state.selection.prepare()); return;
            }
        }
        if (startAfterEventsSave && !normalEvents.selection.dirty() && !mediaEvents.selection.dirty()) {
            startAfterEventsSave = false; startServerWithSelectedStorage();
        }
    }

    private void requestEventSettings(EventUiState state, String action, EventSelectionDraft.Save sent) {
        eventsRequest = true; eventsSaving = sent != null; eventsRequestState = state;
        JSONObject payload = accountPayload("mode", state.media ? "media" : "normal");
        if (sent != null) payload = accountPayload("mode", state.media ? "media" : "normal", "settings",
                eventSettingsJson(state.selection, sent.rows), "expected_revision", sent.revision);
        renderEventSettings();
        ServerService.manageEventSettings(getApplicationContext(), action, payload, result -> {
            eventsRequest = false; eventsSaving = false; eventsRequestState = null;
            if (isFinishing() || isDestroyed()) return;
            if (!result.optBoolean("ok", false)) {
                state.error = result.optString("error", "event_settings_io");
                boolean conflict = "event_settings_revision_conflict".equals(state.error);
                state.blocked = !conflict || ++state.conflictRetries > 3;
                state.refresh = conflict && !state.blocked;
            } else try {
                JSONObject observed = result.getJSONObject("event_settings");
                observeEventSettings(state, observed, sent); state.error = "";
                if (sent != null) state.conflictRetries = 0;
            } catch (org.json.JSONException | IllegalArgumentException invalid) {
                state.error = "event_settings_io"; state.blocked = true;
            }
            if (state.blocked && startAfterEventsSave) {
                startAfterEventsSave = false;
                Toast.makeText(this, eventSettingsError(state.error), Toast.LENGTH_LONG).show();
            }
            renderEventSettings(); pumpEventRequests();
        });
    }

    private int eventSettingsError(String code) {
        if ("event_settings_revision_conflict".equals(code)) return R.string.events_error_conflict;
        if ("event_settings_busy".equals(code)) return R.string.events_error_busy;
        if ("event_settings_catalog_unavailable".equals(code) || "event_settings_unsupported".equals(code)) return R.string.events_unavailable;
        if ("event_settings_invalid".equals(code)) return R.string.events_error_invalid;
        return R.string.events_error_storage;
    }

    private void editEventTime(boolean startTime) {
        JSONObject entry = eventEntry(eventsDraft, eventsSelectedId); if (entry == null || eventState().media) return;
        String identifier = eventsSelectedId;
        EventUiState editingState = eventState();
        long start = entry.optLong("start_time_ms"), end = entry.optLong("end_time_ms");
        java.util.Calendar date = java.util.Calendar.getInstance(); date.setTimeInMillis(startTime ? start : end);
        android.app.DatePickerDialog picker = new android.app.DatePickerDialog(this, (view, year, month, day) -> {
            if (!presentationObserved) return;
            date.set(java.util.Calendar.YEAR, year); date.set(java.util.Calendar.MONTH, month); date.set(java.util.Calendar.DAY_OF_MONTH, day);
            android.app.TimePickerDialog time = new android.app.TimePickerDialog(this, (clock, hour, minute) -> {
                date.set(java.util.Calendar.HOUR_OF_DAY, hour); date.set(java.util.Calendar.MINUTE, minute);
                date.set(java.util.Calendar.SECOND, 0); date.set(java.util.Calendar.MILLISECOND, 0);
                try {
                    long[] window = startTime ? EventWindow.shiftStart(date.getTimeInMillis(), start, end)
                            : new long[]{start, date.getTimeInMillis()};
                    saveEventEntry(editingState, identifier, window);
                } catch (IllegalArgumentException invalid) { Toast.makeText(this, R.string.events_error_invalid, Toast.LENGTH_LONG).show(); }
            }, date.get(java.util.Calendar.HOUR_OF_DAY), date.get(java.util.Calendar.MINUTE), android.text.format.DateFormat.is24HourFormat(this));
            time.setTitle(startTime ? R.string.events_start_name : R.string.events_end_name);
            time.setOnDismissListener(dialog -> { if (eventsDialog == time) eventsDialog = null; });
            eventsDialog = time; time.show();
        }, date.get(java.util.Calendar.YEAR), date.get(java.util.Calendar.MONTH), date.get(java.util.Calendar.DAY_OF_MONTH));
        picker.setTitle(startTime ? R.string.events_start_name : R.string.events_end_name);
        picker.setOnDismissListener(dialog -> { if (eventsDialog == picker) eventsDialog = null; });
        eventsDialog = picker; picker.show();
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

    private static int restoredAccountPicker(int requestCode) {
        return requestCode == EXPORT_ACCOUNT || requestCode == IMPORT_ACCOUNT ? requestCode : 0;
    }

    private void openAccountDocumentPicker(Intent picker, int requestCode) {
        pendingAccountPicker = requestCode;
        try {
            UnifiedMP4Export.noteDocumentLaunch(this, requestCode, picker, requestCode == EXPORT_ACCOUNT ? "account_export" : "account_import");
            startActivityForResult(picker, requestCode);
        }
        catch (RuntimeException error) {
            UnifiedMP4Export.noteDocumentUnavailable(this, requestCode);
            pendingAccountPicker = 0;
            accountError("account_picker_unavailable");
        }
    }

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
        if ("accounts_status".equals(action) && values != null && (officialWarnings & OFFICIAL_WARNING_REFRESH) != 0) {
            officialWarnings &= ~OFFICIAL_WARNING_REFRESH;
            renderOfficialJob();
        }
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
            openAccountDocumentPicker(picker, EXPORT_ACCOUNT);
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
            UnifiedMP4Export.noteDocumentLaunch(this, EXPORT_DIAGNOSTICS, destination, "diagnostics_export");
            startActivityForResult(destination, EXPORT_DIAGNOSTICS);
        } catch (RuntimeException error) {
            UnifiedMP4Export.noteDocumentUnavailable(this, EXPORT_DIAGNOSTICS);
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
        return !UnifiedRuntime.isEnabled(this)
                && getSharedPreferences(SERVER_PREFS, MODE_PRIVATE).getBoolean(RESOURCE_PUBLIC_DOWNLOADS, true);
    }
    private void addResourceStorageControls(LinearLayout body) {
        resourceStorage = presentationSpinner(body, R.string.resource_storage, R.array.resource_storage_options);
        resourceStorage.setSelection(downloadsSelected() ? 0 : 1);
        resourceStorageNotice = text(R.string.resource_storage_public_short, 12, TEXT_MUTED);
        resourceStorageNotice.setPadding(0, 0, 0, dp(8)); body.addView(resourceStorageNotice);
        resourceStorage.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                boolean selected = position == 0;
                getSharedPreferences(SERVER_PREFS, MODE_PRIVATE).edit().putBoolean(RESOURCE_PUBLIC_DOWNLOADS, selected).apply();
                resourceStorageNotice.setText(selected ? R.string.resource_storage_public_short : R.string.resource_storage_private_short);
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });
        resourceStorageNotice.setText(downloadsSelected() ? R.string.resource_storage_public_short : R.string.resource_storage_private_short);
        if (UnifiedRuntime.isEnabled(this)) resourceStorage.setEnabled(false);
    }
    private void startServerWithSelectedStorage() {
        if (normalEvents.selection.dirty() || mediaEvents.selection.dirty()) {
            startAfterEventsSave = true; pumpEventRequests();
            Toast.makeText(this, R.string.events_pending, Toast.LENGTH_SHORT).show(); return;
        }
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
        libraryLanguage = presentationSpinner(body, R.string.library_language, R.array.library_language_options);
        hideVideoMv = new CheckBox(this); hideVideoMv.setText(R.string.library_hide_video_mv);
        hideVideoMv.setTextSize(13); hideVideoMv.setTextColor(TEXT_PRIMARY); body.addView(hideVideoMv);
        libraryMvSort = presentationSpinner(body, R.string.library_mv_sort, R.array.library_mv_sort_options);
        libraryOutfitSort = presentationSpinner(body, R.string.library_outfit_sort, R.array.library_outfit_sort_options);
        libraryStatus = text(R.string.library_settings_short, 12, TEXT_MUTED);
        libraryStatus.setTextIsSelectable(true); libraryStatus.setPadding(0, dp(4), 0, dp(8)); body.addView(libraryStatus);
        restoreLibraryControls();
        AdapterView.OnItemSelectedListener changed = new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, View view, int position, long id) { saveLibraryControls(); }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        };
        libraryLanguage.setOnItemSelectedListener(changed); libraryMvSort.setOnItemSelectedListener(changed);
        libraryOutfitSort.setOnItemSelectedListener(changed);
        hideVideoMv.setOnCheckedChangeListener((button, enabled) -> saveLibraryControls());
        addHelp(body, R.string.library_settings_title, R.string.library_settings_notice);
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
                : libraryInvalid ? R.string.library_settings_invalid : R.string.library_settings_short));
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
            try { UnifiedMP4Export.noteDocumentLaunch(this, IMPORT_RESOURCES, picker, "resource_import"); startActivityForResult(picker, IMPORT_RESOURCES); }
            catch (RuntimeException unavailable) { UnifiedMP4Export.noteDocumentUnavailable(this, IMPORT_RESOURCES); Toast.makeText(this, R.string.library_picker_failed, Toast.LENGTH_LONG).show(); }
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
            try { UnifiedMP4Export.noteDocumentLaunch(this, EXPORT_RESOURCES, picker, "resource_export"); startActivityForResult(picker, EXPORT_RESOURCES); }
            catch (RuntimeException unavailable) { UnifiedMP4Export.noteDocumentUnavailable(this, EXPORT_RESOURCES); Toast.makeText(this, R.string.library_picker_failed, Toast.LENGTH_LONG).show(); }
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
        UnifiedMP4Export.saveState(state);
        state.putString("settings_category", selectedCategory);
        state.putInt("settings_scroll_y_dp", settingsScroll == null ? 0
                : Math.round(settingsScroll.getScrollY() / getResources().getDisplayMetrics().density));
        state.putString("resource_platform", pendingResourcePlatform);
        state.putBoolean("storage_retry", retryStartAfterStoragePermission);
        state.putInt("account_offset", accountOffset); state.putInt("restore_offset", restoreOffset);
        state.putInt("account_picker", pendingAccountPicker);
        if (pendingAccountExport != null) state.putString("account_export", pendingAccountExport.toString());
        if (pendingAccountPreview != null) state.putString("account_preview", pendingAccountPreview.toString());
        if (officialAppliedAccount != null) {
            state.putString("official_local_profile", officialAppliedAccount.optString("profile"));
            state.putString("official_local_revision", officialAppliedAccount.optString("revision"));
            state.putInt("official_local_warnings", officialWarnings & 3);
        }
        state.putString("events_selected_id", eventsSelectedId);
        saveEventEdits(state, normalEvents); saveEventEdits(state, mediaEvents);
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
        playbackStatus = text(R.string.playback_waiting, 12, TEXT_MUTED);
        playbackStatus.setTextIsSelectable(true);
        playbackStatus.setPadding(0, 0, 0, dp(8));
        body.addView(playbackStatus);
        addHelp(body, R.string.playback_section_title, R.string.playback_wait_notice);
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
        LinearLayout settings = new LinearLayout(this);
        settings.setOrientation(LinearLayout.VERTICAL);
        settings.setPadding(dp(4), 0, dp(4), dp(8));
        body.addView(settings, new LinearLayout.LayoutParams(-1, -2));
        customGraphics = new CheckBox(this);
        customGraphics.setText(R.string.presentation_custom_graphics);
        customGraphics.setTextColor(TEXT_PRIMARY);
        customGraphics.setTextSize(14);
        if (compactHeader) { customGraphics.setMinHeight(dp(44)); customGraphics.setMinimumWidth(dp(44)); }
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
        addHelp(settings, R.string.graphics_panel_title, R.string.presentation_notice,
                R.string.presentation_client_notice, R.string.presentation_photography_notice);
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

    private void addMp4Controls(LinearLayout body) {
        TextView title = text(R.string.mp4_title, 17, TEXT_PRIMARY); title.setPadding(0, dp(20), 0, dp(6)); body.addView(title);
        body.addView(text(R.string.mp4_queue_hint, 13, TEXT_MUTED));
        mp4Fps = mp4Spinner(body, R.string.mp4_fps, new String[] {"30", "60", "120"});
        mp4Codec = mp4Spinner(body, R.string.mp4_codec, new String[] {"H.264", "HEVC"});
        mp4Bitrate = mp4Spinner(body, R.string.mp4_bitrate,
                new String[] {getString(R.string.mp4_bitrate_recommended), getString(R.string.mp4_custom)});
        mp4CustomBitrate = new LinearLayout(this); mp4CustomBitrate.setOrientation(LinearLayout.VERTICAL);
        mp4BitrateValue = mp4NumberField(R.string.mp4_bitrate_mbps, true);
        mp4CustomBitrate.addView(mp4BitrateValue, new LinearLayout.LayoutParams(-1, -2)); body.addView(mp4CustomBitrate);
        mp4Resolution = mp4Spinner(body, R.string.mp4_output_resolution,
                new String[] {getString(R.string.mp4_resolution_current), getString(R.string.mp4_custom)});
        mp4CustomResolution = new LinearLayout(this); mp4CustomResolution.setOrientation(LinearLayout.HORIZONTAL);
        mp4Width = mp4NumberField(R.string.mp4_width_pixels, false);
        mp4Height = mp4NumberField(R.string.mp4_height_pixels, false);
        mp4CustomResolution.addView(mp4Width, new LinearLayout.LayoutParams(0, -2, 1));
        TextView separator = mp4Text("×", 17, TEXT_MUTED); separator.setPadding(dp(8), dp(12), dp(8), 0);
        mp4CustomResolution.addView(separator, new LinearLayout.LayoutParams(-2, -2));
        mp4CustomResolution.addView(mp4Height, new LinearLayout.LayoutParams(0, -2, 1)); body.addView(mp4CustomResolution);
        body.addView(text(R.string.mp4_output_resolution_hint, 12, TEXT_MUTED));
        mp4OptionsSummary = mp4Text("", 13, TEXT_MUTED); mp4OptionsSummary.setPadding(0, dp(8), 0, 0); body.addView(mp4OptionsSummary);
        mp4OptionsError = mp4Text("", 13, Color.rgb(180, 40, 40)); mp4OptionsError.setPadding(0, dp(4), 0, dp(4)); body.addView(mp4OptionsError);
        restoreMp4Options();
        mp4Status = text(R.string.mp4_idle, 13, TEXT_MUTED); mp4Status.setPadding(0, dp(8), 0, dp(8)); body.addView(mp4Status);

        mp4Enqueue = button(R.string.mp4_queue_add); body.addView(mp4Enqueue);
        mp4QueueRun = button(R.string.mp4_queue_run); primaryButton(mp4QueueRun); body.addView(mp4QueueRun);
        LinearLayout queueActions = new LinearLayout(this); queueActions.setOrientation(LinearLayout.HORIZONTAL);
        mp4QueuePause = button(R.string.mp4_queue_pause); queueActions.addView(mp4QueuePause, new LinearLayout.LayoutParams(0, -2, 1));
        mp4QueueResume = button(R.string.mp4_queue_resume); queueActions.addView(mp4QueueResume, new LinearLayout.LayoutParams(0, -2, 1));
        body.addView(queueActions, new LinearLayout.LayoutParams(-1, -2));
        mp4QueueStatus = text(R.string.mp4_queue_empty, 13, TEXT_MUTED); mp4QueueStatus.setPadding(0, dp(8), 0, dp(8)); body.addView(mp4QueueStatus);
        mp4QueueRows = new LinearLayout(this); mp4QueueRows.setOrientation(LinearLayout.VERTICAL);
        body.addView(mp4QueueRows, new LinearLayout.LayoutParams(-1, -2));
        TextView completedTitle = text(R.string.mp4_completed_videos, 16, TEXT_PRIMARY);
        completedTitle.setPadding(0, dp(16), 0, dp(6)); body.addView(completedTitle);
        body.addView(text(R.string.mp4_completed_hint, 12, TEXT_MUTED));
        mp4CompletedRows = new LinearLayout(this); mp4CompletedRows.setOrientation(LinearLayout.VERTICAL);
        mp4CompletedRendered = "";
        body.addView(mp4CompletedRows, new LinearLayout.LayoutParams(-1, -2));

        mp4Background = new CheckBox(this); mp4Background.setText(R.string.mp4_queue_background_experimental);
        mp4Background.setTextColor(TEXT_PRIMARY); mp4Background.setMinHeight(dp(48));
        mp4Background.setChecked(UnifiedMP4Export.experimentalBackgroundEnabled(this)); body.addView(mp4Background);
        mp4BackgroundStatus = text(R.string.mp4_queue_background_off, 13, TEXT_MUTED);
        mp4BackgroundStatus.setPadding(0, 0, 0, dp(8)); body.addView(mp4BackgroundStatus);
        mp4Background.setOnCheckedChangeListener((control, enabled) -> {
            if (mp4BackgroundLoading) return;
            UnifiedMP4Export.setExperimentalBackgroundEnabled(this, enabled);
            refreshMp4();
        });

        mp4Start = button(R.string.mp4_queue_immediate); body.addView(mp4Start);
        mp4Cancel = button(R.string.mp4_cancel); body.addView(mp4Cancel);
        mp4Save = button(R.string.mp4_save); body.addView(mp4Save);
        mp4Enqueue.setOnClickListener(view -> {
            if (!UnifiedMP4Export.requestEnqueue(this, mp4Settings.fps, mp4Settings.codec, mp4Settings.requestBitrate(),
                    mp4Settings.requestWidth(), mp4Settings.requestHeight()))
                Toast.makeText(this, UnifiedMP4Export.enqueueFailureText(this), Toast.LENGTH_LONG).show();
            refreshMp4();
        });
        mp4QueueRun.setOnClickListener(view -> {
            if (!UnifiedMP4Export.requestQueueRun(this)) Toast.makeText(this, R.string.mp4_queue_action_failed, Toast.LENGTH_LONG).show();
            refreshMp4();
        });
        mp4QueuePause.setOnClickListener(view -> { UnifiedMP4Export.queuePause(); refreshMp4(); });
        mp4QueueResume.setOnClickListener(view -> {
            if (!UnifiedMP4Export.queueResume(this)) Toast.makeText(this, R.string.mp4_queue_action_failed, Toast.LENGTH_LONG).show();
            refreshMp4();
        });
        mp4Start.setOnClickListener(view -> {
            if (!UnifiedMP4Export.requestStart(this, mp4Settings.fps, mp4Settings.codec, mp4Settings.requestBitrate(),
                    mp4Settings.requestWidth(), mp4Settings.requestHeight()))
                Toast.makeText(this, R.string.mp4_not_ready, Toast.LENGTH_LONG).show();
            refreshMp4();
        });
        mp4Cancel.setOnClickListener(view -> UnifiedMP4Export.cancelFrom("console_button"));
        UnifiedMP4Export.bindSaveButton(mp4Save, this);
        refreshMp4();
    }

    private Mp4ExportSettings.Store mp4OptionsStore() {
        android.content.SharedPreferences preferences = getSharedPreferences(Mp4ExportSettings.PREFS, MODE_PRIVATE);
        return new Mp4ExportSettings.Store() {
            @Override public String read(String key, String fallback) {
                try { return preferences.getString(key, fallback); }
                catch (ClassCastException invalid) { return fallback; }
            }
            @Override public void write(java.util.Map<String, String> values) {
                android.content.SharedPreferences.Editor editor = preferences.edit();
                for (java.util.Map.Entry<String, String> value : values.entrySet()) editor.putString(value.getKey(), value.getValue());
                editor.apply();
            }
        };
    }

    private TextView mp4Text(String value, int size, int color) {
        TextView result = new TextView(this); result.setText(value);
        result.setTextSize(Math.max(16, size)); result.setLineSpacing(dp(2), 1.1f); result.setTextColor(color);
        return result;
    }

    private EditText mp4NumberField(int hint, boolean decimal) {
        EditText field = new EditText(this); field.setSingleLine(true); field.setHint(hint);
        field.setTextColor(TEXT_PRIMARY); field.setTextSize(15); field.setMinHeight(dp(48));
        field.setContentDescription(getString(hint));
        field.setInputType(InputType.TYPE_CLASS_NUMBER | (decimal ? InputType.TYPE_NUMBER_FLAG_DECIMAL : 0));
        field.setFilters(new InputFilter[] {new InputFilter.LengthFilter(32)});
        field.setImeOptions(EditorInfo.IME_ACTION_DONE); field.setSelectAllOnFocus(true);
        return field;
    }

    private void restoreMp4Options() {
        mp4OptionsLoading = true;
        mp4Settings = Mp4ExportSettings.load(mp4OptionsStore());
        mp4Fps.setSelection(Mp4ExportSettings.fpsPosition(mp4Settings.fps)); mp4Codec.setSelection(mp4Settings.codec - 1);
        mp4Bitrate.setSelection(mp4Settings.customBitrate ? 1 : 0);
        mp4Resolution.setSelection(mp4Settings.customResolution ? 1 : 0);
        mp4BitrateValue.setText(mp4Settings.bitrateMbps); mp4Width.setText(mp4Settings.width); mp4Height.setText(mp4Settings.height);
        mp4OptionsLoading = false;
        AdapterView.OnItemSelectedListener selected = new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, View view, int position, long id) { saveMp4Options(); }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        };
        for (Spinner option : new Spinner[] {mp4Fps, mp4Codec, mp4Bitrate, mp4Resolution}) option.setOnItemSelectedListener(selected);
        TextWatcher changed = new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence text, int start, int count, int after) { }
            @Override public void onTextChanged(CharSequence text, int start, int before, int count) { saveMp4Options(); }
            @Override public void afterTextChanged(Editable text) { }
        };
        for (EditText field : new EditText[] {mp4BitrateValue, mp4Width, mp4Height}) field.addTextChangedListener(changed);
        refreshMp4Options();
    }

    private void saveMp4Options() {
        if (mp4OptionsLoading || mp4Settings == null) return;
        mp4Settings = new Mp4ExportSettings(Mp4ExportSettings.fpsAt(mp4Fps.getSelectedItemPosition()),
                mp4Codec.getSelectedItemPosition() + 1, mp4Bitrate.getSelectedItemPosition() == 1,
                mp4BitrateValue.getText().toString(), mp4Resolution.getSelectedItemPosition() == 1,
                mp4Width.getText().toString(), mp4Height.getText().toString());
        mp4Settings.save(mp4OptionsStore());
        refreshMp4Options();
        if (mp4Enqueue != null && mp4Status != null) refreshMp4();
    }

    private void refreshMp4Options() {
        if (mp4Settings == null || mp4OptionsSummary == null) return;
        mp4CustomBitrate.setVisibility(mp4Settings.customBitrate ? View.VISIBLE : View.GONE);
        mp4CustomResolution.setVisibility(mp4Settings.customResolution ? View.VISIBLE : View.GONE);
        String error = !mp4Settings.bitrateValid() ? getString(R.string.mp4_bitrate_invalid)
                : !mp4Settings.resolutionValid() ? getString(R.string.mp4_resolution_invalid) : "";
        setTextIfChanged(mp4OptionsError, error); mp4OptionsError.setVisibility(error.isEmpty() ? View.GONE : View.VISIBLE);
        JSONObject state = UnifiedMP4Export.snapshot();
        int width = mp4Settings.customResolution ? mp4Settings.requestWidth() : state.optInt("source_width", 0);
        int height = mp4Settings.customResolution ? mp4Settings.requestHeight() : state.optInt("source_height", 0);
        if (!mp4Settings.customResolution && width >= 16 && width <= Mp4ExportSettings.MAX_EDGE
                && height >= 16 && height <= Mp4ExportSettings.MAX_EDGE) {
            width -= width % 2; height -= height % 2;
        }
        int recommended = Mp4ExportSettings.recommendedBitrate(width, height, mp4Settings.fps, mp4Settings.codec);
        String bitrate = mp4Settings.customBitrate
                ? (mp4Settings.bitrateValid() ? String.format(Locale.ROOT, "%.2f Mbps", mp4Settings.requestBitrate() / 1_000_000.0) : "")
                : recommended > 0 ? getString(R.string.mp4_bitrate_recommendation, String.format(Locale.ROOT, "%.2f", recommended / 1_000_000.0))
                : getString(R.string.mp4_bitrate_recommended_waiting);
        String geometry = Mp4ExportSettings.validResolution(width, height) && width > 0
                ? String.format(Locale.ROOT, "%d × %d", width, height) : getString(R.string.mp4_resolution_current);
        setTextIfChanged(mp4OptionsSummary, geometry + " · " + mp4Settings.fps + " fps · " + bitrate);
    }

    private Spinner mp4Spinner(LinearLayout body, int label, String[] choices) {
        TextView caption = text(label, 13, TEXT_MUTED); caption.setPadding(0, dp(8), 0, 0); body.addView(caption);
        Spinner control = new Spinner(this); control.setMinimumHeight(dp(48));
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, choices);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item); control.setAdapter(adapter);
        body.addView(control, new LinearLayout.LayoutParams(-1, -2)); return control;
    }

    private void refreshMp4() {
        if (mp4Status == null) return;
        setTextIfChanged(mp4Status, UnifiedMP4Export.statusText(this));
        JSONObject queue = UnifiedMP4Export.queueSnapshot();
        org.json.JSONArray jobs = queue.optJSONArray("jobs");
        int count = jobs == null ? 0 : Math.min(Mp4QueueUiState.CAPACITY, jobs.length()), pending = 0;
        boolean ownsCurrent = false;
        String exportId = UnifiedMP4Export.snapshot().optString("export_id");
        for (int index = 0; index < count; index++) {
            JSONObject job = jobs.optJSONObject(index); if (job == null) continue;
            if ("pending".equals(job.optString("state"))) pending++;
            if (!exportId.isEmpty() && exportId.equals(job.optString("output_id"))) ownsCurrent = true;
        }
        boolean commandPending = queue.optBoolean("command_pending"), busy = UnifiedMP4Export.busy();
        boolean running = queue.optBoolean("running"), paused = queue.optBoolean("paused");
        Mp4QueueUiState.Controls controls = new Mp4QueueUiState.Controls(queue.optBoolean("available"), commandPending,
                running, paused, busy, UnifiedMP4Export.canEnqueueSelection(), UnifiedMP4Export.ready(), queue.optBoolean("can_run", false), pending, count);
        boolean optionsValid = mp4Settings != null && mp4Settings.valid();
        mp4Enqueue.setEnabled(controls.enqueue && optionsValid); mp4QueueRun.setEnabled(controls.run);
        mp4QueuePause.setEnabled(controls.pause); mp4QueueResume.setEnabled(controls.resume);
        mp4QueuePause.setVisibility(running && !paused ? View.VISIBLE : View.GONE);
        mp4QueueResume.setVisibility(paused ? View.VISIBLE : View.GONE);
        mp4Start.setEnabled(controls.immediate && optionsValid && UnifiedMP4Export.oneShotCompletionReady());
        mp4Cancel.setVisibility(busy && !ownsCurrent ? View.VISIBLE : View.GONE);
        UnifiedMP4Export.bindSaveButton(mp4Save, this);
        mp4Save.setVisibility(UnifiedMP4Export.hasCompletedOutput() && !ownsCurrent ? View.VISIBLE : View.GONE);
        for (Spinner option : new Spinner[] {mp4Fps, mp4Codec, mp4Bitrate, mp4Resolution}) option.setEnabled(!busy && !commandPending);
        for (EditText field : new EditText[] {mp4BitrateValue, mp4Width, mp4Height}) field.setEnabled(!busy && !commandPending);
        refreshMp4Options();

        String summary = count == 0 ? getString(R.string.mp4_queue_empty)
                : getString(R.string.mp4_queue_count, count, Mp4QueueUiState.CAPACITY, pending);
        if (commandPending) summary += "\n" + getString(R.string.mp4_queue_working);
        else if (paused) summary += "\n" + getString(R.string.mp4_queue_paused);
        else if ("waiting_for_scene".equals(queue.optString("phase"))) summary += "\n" + getString(R.string.mp4_queue_waiting_scene);
        else if (running) summary += "\n" + getString(R.string.mp4_queue_running);
        String error = queue.optString("error_code");
        if (!error.isEmpty() && !"none".equals(error)) summary += "\n" + getString(R.string.mp4_queue_error, mp4SafeCode(error));
        setTextIfChanged(mp4QueueStatus, summary);

        String rendered = (jobs == null ? "[]" : jobs.toString()) + ":" + commandPending
                + ":" + getResources().getConfiguration().getLocales().toLanguageTags();
        if (!rendered.equals(mp4QueueRendered)) { mp4QueueRendered = rendered; renderMp4Queue(jobs, count, commandPending); }
        refreshMp4Completed();
        refreshMp4Background();
    }

    private void refreshMp4Completed() {
        if (mp4CompletedRows == null) return;
        ArrayList<UnifiedMP4Export.SaveTarget> outputs = UnifiedMP4Export.completedOutputs();
        StringBuilder identity = new StringBuilder().append(UnifiedMP4Export.saveInProgress())
                .append(':').append(UnifiedMP4Export.snapshot().optString("phase"))
                .append(':').append(getResources().getConfiguration().getLocales().toLanguageTags());
        for (UnifiedMP4Export.SaveTarget output : outputs) identity.append('\n').append(output.identity());
        for (UnifiedMP4Export.SaveTarget output : outputs) identity.append(':').append(UnifiedMP4Export.canDeleteCompleted(output));
        String rendered = identity.toString();
        if (rendered.equals(mp4CompletedRendered)) return;
        mp4CompletedRendered = rendered; mp4CompletedRows.removeAllViews();
        if (outputs.isEmpty()) { mp4CompletedRows.addView(text(R.string.mp4_completed_empty, 13, TEXT_MUTED)); return; }
        for (int index = 0; index < outputs.size(); index++) {
            UnifiedMP4Export.SaveTarget output = outputs.get(index);
            LinearLayout row = new LinearLayout(this); row.setOrientation(LinearLayout.VERTICAL);
            row.setPadding(0, dp(8), 0, dp(8)); mp4CompletedRows.addView(row, new LinearLayout.LayoutParams(-1, -2));
            TextView title = text(R.string.mp4_completed_videos, 14, TEXT_PRIMARY);
            title.setText(getString(R.string.mp4_completed_video, index + 1)); row.addView(title);
            File source = new File(output.root, output.outputId + ".mp4");
            String completedAt = java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.SHORT, java.text.DateFormat.SHORT,
                    getResources().getConfiguration().getLocales().get(0)).format(new java.util.Date(source.lastModified()));
            row.addView(mp4Text(completedAt + " · " + formatBytes(source.length()), 12, TEXT_MUTED));
            LinearLayout actions = new LinearLayout(this); actions.setOrientation(LinearLayout.HORIZONTAL); row.addView(actions);
            Button save = button(R.string.mp4_save); UnifiedMP4Export.bindSaveButton(save, this, output);
            actions.addView(save, new LinearLayout.LayoutParams(0, -2, 1));
            Button delete = button(R.string.mp4_delete_video); delete.setEnabled(UnifiedMP4Export.canDeleteCompleted(output));
            delete.setOnClickListener(view -> new AlertDialog.Builder(this).setTitle(R.string.mp4_delete_video)
                    .setMessage(R.string.mp4_delete_video_confirm)
                    .setPositiveButton(R.string.mp4_delete_video, (dialog, which) -> {
                        if (!UnifiedMP4Export.deleteCompleted(output)) Toast.makeText(this, R.string.mp4_save_failed, Toast.LENGTH_LONG).show();
                        mp4CompletedRendered = ""; refreshMp4();
                    }).setNegativeButton(android.R.string.cancel, null).show());
            actions.addView(delete, new LinearLayout.LayoutParams(0, -2, 1));
        }
    }

    private static String mp4SafeCode(String value) {
        return value != null && value.matches("[a-z0-9_]{1,64}") ? value : "export_failed";
    }

    private int mp4QueueStateLabel(String state) {
        switch (state) {
            case "pending": return R.string.mp4_queue_pending;
            case "running": return R.string.mp4_queue_active;
            case "paused": return R.string.mp4_queue_paused;
            case "completed": return R.string.mp4_queue_completed;
            case "failed": return R.string.mp4_queue_failed;
            case "cancelled": return R.string.mp4_queue_cancelled;
            default: return R.string.mp4_queue_interrupted;
        }
    }

    private void renderMp4Queue(org.json.JSONArray jobs, int count, boolean commandPending) {
        mp4QueueRows.removeAllViews();
        for (int index = 0; index < count; index++) {
            JSONObject job = jobs.optJSONObject(index); if (job == null) continue;
            String id = job.optString("job_id"), state = job.optString("state");
            if (!Mp4QueueUiState.jobId(id) || !Mp4QueueUiState.state(state)) continue;
            final int position = index, actions = Mp4QueueUiState.actions(state, index, count, commandPending);
            LinearLayout row = new LinearLayout(this); row.setOrientation(LinearLayout.VERTICAL);
            row.setPadding(dp(12), dp(8), dp(12), dp(8));
            GradientDrawable background = new GradientDrawable(); background.setColor(CONTROL_BACKGROUND); background.setCornerRadius(dp(12)); row.setBackground(background);
            LinearLayout.LayoutParams placement = new LinearLayout.LayoutParams(-1, -2); placement.setMargins(0, 0, 0, dp(8)); mp4QueueRows.addView(row, placement);
            TextView name = text(R.string.mp4_queue_item, 16, TEXT_PRIMARY);
            String title = Mp4TitleCatalog.title(job, getResources().getConfiguration().getLocales().get(0));
            name.setText(title.isEmpty() ? getString(R.string.mp4_queue_unknown_title, index + 1)
                    : getString(R.string.mp4_queue_item, index + 1, title));
            name.setTypeface(Typeface.DEFAULT, Typeface.BOLD); row.addView(name);
            TextView details = text(mp4QueueStateLabel(state), 14, "failed".equals(state) || "interrupted".equals(state) ? WARNING : TEXT_MUTED);
            int width = job.optInt("width"), height = job.optInt("height"), fps = job.optInt("fps_num");
            String description = getString(mp4QueueStateLabel(state));
            if (width > 0 && width <= 16384 && height > 0 && height <= 16384 && Mp4ExportSettings.supportedFps(fps))
                description += " · " + getString(R.string.mp4_geometry, width, height, fps);
            int codec = job.optInt("video_codec"), bitrate = job.optInt("video_bitrate");
            if ((codec == 1 || codec == 2) && bitrate >= Mp4ExportSettings.MIN_BITRATE && bitrate <= Mp4ExportSettings.MAX_BITRATE)
                description += " · " + (codec == 2 ? "HEVC" : "H.264") + " · "
                        + java.math.BigDecimal.valueOf(bitrate, 6).stripTrailingZeros().toPlainString() + " Mbps";
            int cast = job.optInt("actor_count"); if (cast > 0 && cast <= 32) description += " · " + getString(R.string.mp4_queue_cast, cast);
            String error = job.optString("error_code");
            if ("failed".equals(state) && !error.isEmpty() && !"none".equals(error)) description += "\n" + mp4SafeCode(error);
            details.setText(description); row.addView(details);
            LinearLayout buttons = new LinearLayout(this); buttons.setOrientation(LinearLayout.HORIZONTAL); row.addView(buttons);
            if ((actions & Mp4QueueUiState.SAVE) != 0) {
                Button save = button(R.string.mp4_save); save.setOnClickListener(view -> UnifiedMP4Export.requestSave(this, id));
                buttons.addView(save, new LinearLayout.LayoutParams(0, -2, 1));
            }
            if ((actions & Mp4QueueUiState.RETRY) != 0) {
                Button retry = button(R.string.mp4_queue_retry); retry.setOnClickListener(view -> mp4QueueCommand(3, id, 0));
                buttons.addView(retry, new LinearLayout.LayoutParams(0, -2, 1));
            }
            if ((actions & Mp4QueueUiState.CANCEL) != 0 && ("running".equals(state) || "paused".equals(state))) {
                Button cancel = button(R.string.mp4_cancel); cancel.setOnClickListener(view -> mp4QueueCommand(1, id, 0));
                buttons.addView(cancel, new LinearLayout.LayoutParams(0, -2, 1));
            }
            Button menu = button(R.string.mp4_queue_actions); menu.setEnabled(actions != 0);
            menu.setContentDescription(getString(R.string.mp4_queue_item_actions, index + 1));
            menu.setOnClickListener(view -> {
                PopupMenu popup = new PopupMenu(this, menu);
                if ((actions & Mp4QueueUiState.UP) != 0) popup.getMenu().add(0, 4, 0, R.string.mp4_queue_move_up);
                if ((actions & Mp4QueueUiState.DOWN) != 0) popup.getMenu().add(0, 5, 1, R.string.mp4_queue_move_down);
                if ((actions & Mp4QueueUiState.CANCEL) != 0) popup.getMenu().add(0, 1, 2, R.string.mp4_cancel);
                if ((actions & Mp4QueueUiState.REMOVE) != 0) popup.getMenu().add(0, 2, 3,
                        "completed".equals(state) ? R.string.mp4_queue_delete_file_job : R.string.mp4_queue_remove);
                popup.setOnMenuItemClickListener(item -> {
                    int action = item.getItemId();
                    if (action == 2) requestMp4QueueRemoval(id, state);
                    else mp4QueueCommand(action == 5 ? 4 : action, id, action == 4 ? position - 1 : action == 5 ? position + 1 : 0);
                    return true;
                });
                popup.show();
            });
            // Active jobs already have an explicit cancel button, so an empty
            // duplicate menu is unnecessary while their renderer owns the MV.
            if ((actions & (Mp4QueueUiState.UP | Mp4QueueUiState.DOWN | Mp4QueueUiState.REMOVE)) != 0 || commandPending)
                buttons.addView(menu, new LinearLayout.LayoutParams(0, -2, 1));
        }
    }

    private void mp4QueueCommand(int operation, String id, int position) {
        UnifiedMP4Export.queueCommand(operation, id, position); refreshMp4();
    }

    private void requestMp4QueueRemoval(String id, String state) {
        if (!Mp4QueueUiState.jobId(id)) return;
        if (!"completed".equals(state)) { mp4QueueCommand(2, id, 0); return; }
        new AlertDialog.Builder(this).setTitle(R.string.mp4_queue_delete_file_job)
                .setMessage(R.string.mp4_queue_delete_confirm)
                .setPositiveButton(R.string.mp4_queue_delete_file_job, (dialog, which) -> mp4QueueCommand(2, id, 1))
                .setNegativeButton(android.R.string.cancel, null).show();
    }

    private void refreshMp4Background() {
        boolean enabled = UnifiedMP4Export.experimentalBackgroundEnabled(this);
        mp4BackgroundLoading = true; mp4Background.setChecked(enabled); mp4BackgroundLoading = false;
        JSONObject background = UnifiedMP4Export.backgroundSnapshot();
        String state = background.optString("state");
        int text = !enabled ? R.string.mp4_queue_background_off
                : "failed".equals(state) || "paused".equals(state) ? R.string.mp4_queue_background_fallback
                : "running".equals(state) && background.optBoolean("capture_verified") && background.optBoolean("heartbeat_verified") ? R.string.mp4_queue_background_active
                : R.string.mp4_queue_background_unverified;
        setTextIfChanged(mp4BackgroundStatus, getString(text));
        mp4BackgroundStatus.setTextColor(enabled ? WARNING : TEXT_MUTED);
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
        try {
            client = UnifiedRuntime.launchIntent(this);
            if (client != null) selectedPackage = getPackageName();
        } catch (IllegalStateException invalidUnifiedApp) {
            Toast.makeText(this, R.string.client_launch_failed, Toast.LENGTH_LONG).show();
            return;
        }
        for (String packageName : client == null ? packageNames : new String[0]) {
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
            if (UnifiedRuntime.isEnabled(this)) prepareUnifiedClient(client);
            else startActivity(client);
        } catch (RuntimeException error) {
            Toast.makeText(this, R.string.client_launch_failed, Toast.LENGTH_LONG).show();
        }
    }

    private void prepareUnifiedClient(Intent client) {
        if (unifiedPreparing) return;
        LibrarySettings.Loaded loaded = LibrarySettings.load(getFilesDir());
        final String language = loaded.settings.language;
        if (loaded.invalidLanguage || !ServerService.resourceServerRunning()) {
            Toast.makeText(this, R.string.unified_start_server, Toast.LENGTH_LONG).show(); return;
        }
        if (!language.equals(ServerService.effectiveLanguage())) {
            Toast.makeText(this, R.string.unified_restart_server, Toast.LENGTH_LONG).show(); return;
        }
        String frozen = UnifiedGameAssets.frozenLanguage();
        if (frozen != null && !frozen.equals(language)) {
            Toast.makeText(this, R.string.unified_restart_app, Toast.LENGTH_LONG).show(); return;
        }
        unifiedPreparing = true;
        Toast.makeText(this, R.string.unified_preparing, Toast.LENGTH_SHORT).show();
        final android.content.Context application = getApplicationContext();
        Thread preparation = new Thread(() -> {
            boolean prepared;
            try { UnifiedGameAssets.prepare(application, language); prepared = true; }
            catch (IOException | RuntimeException error) { prepared = false; }
            final boolean success = prepared;
            runOnUiThread(() -> {
                unifiedPreparing = false;
                if (isFinishing() || isDestroyed()) return;
                LibrarySettings.Loaded current = LibrarySettings.load(getFilesDir());
                if (!success || current.invalidLanguage || !language.equals(current.settings.language)
                        || !ServerService.resourceServerRunning() || !language.equals(ServerService.effectiveLanguage())) {
                    Toast.makeText(this, R.string.client_launch_failed, Toast.LENGTH_LONG).show(); return;
                }
                try { startActivity(client); }
                catch (RuntimeException error) { Toast.makeText(this, R.string.client_launch_failed, Toast.LENGTH_LONG).show(); }
            });
        }, "IdolyGamePrepare");
        preparation.setDaemon(true); preparation.start();
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (UnifiedMP4Export.activityResult(this, requestCode, resultCode, data)) return;
        UnifiedMP4Export.noteDocumentResult(this, requestCode, resultCode);
        if (requestCode == EXPORT_ACCOUNT || requestCode == IMPORT_ACCOUNT) {
            pendingAccountPicker = 0;
            if (resultCode != RESULT_OK || data == null || data.getData() == null) {
                if (requestCode == EXPORT_ACCOUNT && pendingAccountExport != null) {
                    ServerService.discardAccountDocument(getApplicationContext(), pendingAccountExport.optString("path")); pendingAccountExport = null;
                }
                if (!ServerService.isManagingAccounts()) refreshAccounts();
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
        if (mp4Status != null) UnifiedMP4Export.observe(mp4Refresh);
        playbackStatus.removeCallbacks(playbackRefresh);
        playbackStatus.post(playbackRefresh);
        officialStatus.removeCallbacks(officialRefresh); officialStatus.post(officialRefresh);
        refreshEventSettings(false);
        // onStart can run before onActivityResult. Reserve the single account
        // worker for the document result so a background status read cannot
        // reject ZIP save/preview as account_operation_busy.
        if (pendingAccountPicker == 0 && !ServerService.isManagingAccounts()) refreshAccounts();
    }

    @Override protected void onStop() {
        presentationObserved = false;
        if (officialStatus != null) officialStatus.removeCallbacks(officialRefresh);
        if (officialCredentials != null) officialCredentials.dismiss();
        if (officialWizardDialog != null) officialWizardDialog.dismiss();
        clearDeferredOfficial();
        if (eventsDialog != null) eventsDialog.dismiss();
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
        UnifiedMP4Export.removeObserver(mp4Refresh);
        super.onStop();
    }

    @Override public void onServerChanged(ServerService.StatusText value, boolean running, boolean busy, List<String> lines, String detailsJson) {
        presentationServerRunning = running;
        status.setText(value.render(this));
        status.setTextColor(running ? SUCCESS : TEXT_PRIMARY);
        accountLifecycleBusy = busy;
        if (eventsSummary != null) {
            if (!eventsRequest && eventsDialog == null) try {
                JSONObject observed = new JSONObject(detailsJson).optJSONObject("event_settings");
                if (observed != null && !observed.toString().equals(eventsSnapshot.toString())) {
                    EventUiState state = observed.optBoolean("media_mode", false) ? mediaEvents : normalEvents;
                    observeEventSettings(state, observed, null);
                }
            } catch (org.json.JSONException | IllegalArgumentException ignored) { }
            if (!eventsRequest && "event_settings_busy".equals(eventsError) && !ServerService.isManagingEventSettings()) refreshEventSettings(false);
            renderEventSettings(); pumpEventRequests();
        }
        updateOfficialControls();
        start.setEnabled(!running && !busy && !ServerService.isManagingAccounts());
        updateAccountControls();
        experimentalMainLive.setEnabled(!running && !busy);
        downloadMissingResources.setEnabled(!running && !busy);
        mediaMode.setEnabled(!running && !busy);
        resourceStorage.setEnabled(!UnifiedRuntime.isEnabled(this) && !running && !busy);
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
