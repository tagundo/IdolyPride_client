package game.qualiarts.idolypride.localserver;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.Process;
import android.system.Os;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.lang.reflect.Field;
import java.security.MessageDigest;
import org.json.JSONArray;
import org.json.JSONObject;

/** Real Android DocumentsUI/lifecycle fixture. The only video is a tiny bundled complete MP4. */
public final class SaveProbeActivity extends Activity {
    static final String OUTPUT = "11111111111111111111111111111111";
    private static boolean processCounted;
    public static String nativeSession;
    private final Handler main = new Handler(Looper.getMainLooper());
    private SharedPreferences preferences;
    private File root, oneShot, fixtureRoot;
    private String challenge, failure, launchMode;
    private boolean attached;
    private TextView label;
    private final Runnable observer = this::writeReport;
    private final Runnable tick = this::tickReport;
    private void tickReport() { writeReport(); main.postDelayed(tick, 500); }
    private static native String nativeReceipt();

    public static void fixtureCancel() {
        try { nativeSession = new JSONObject().put("phase", "idle").put("ready", false).toString(); }
        catch (Exception impossible) { throw new AssertionError(impossible); }
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout body = new LinearLayout(this); body.setOrientation(LinearLayout.VERTICAL);
        int padding = Math.round(16 * getResources().getDisplayMetrics().density);
        body.setPadding(padding, padding * 4, padding, padding * 10);
        label = new TextView(this); label.setTextSize(18); body.addView(label);
        Button complete = new Button(this); complete.setText("Complete fixture"); complete.setContentDescription("qa_complete");
        complete.setOnClickListener(view -> publishFixture()); body.addView(complete);
        Button recreate = new Button(this); recreate.setText("Recreate screen"); recreate.setContentDescription("qa_recreate");
        recreate.setOnClickListener(view -> recreate()); body.addView(recreate);
        Button finish = new Button(this); finish.setText("Finish proof"); finish.setContentDescription("qa_finish");
        finish.setOnClickListener(view -> finishProof()); body.addView(finish);
        setContentView(body);
        try {
            preferences = getSharedPreferences("save_ui_qa", MODE_PRIVATE);
            String supplied = getIntent().getStringExtra("challenge");
            launchMode = getIntent().getStringExtra("mode");
            require("fresh".equals(launchMode) || "cold".equals(launchMode), "explicit_launch_mode_required");
            challenge = preferences.getString("challenge", supplied);
            require(challenge != null && challenge.matches("[0-9a-f]{64}")
                    && (supplied == null || challenge.equals(supplied)), "fresh_challenge_required");
            SharedPreferences.Editor editor = preferences.edit().putString("challenge", challenge)
                    .putInt("creations", preferences.getInt("creations", 0) + 1);
            if (!processCounted) { editor.putInt("boots", preferences.getInt("boots", 0) + 1); processCounted = true; }
            require(editor.commit(), "fixture_state_commit");
            root = directory(getFilesDir(), "save-qa");
            File broker = directory(root, "broker-" + preferences.getInt("boots", 0)), queue = directory(root, "queue"), persistent = directory(root, "queue-exports");
            oneShot = directory(broker, "exports");
            String publishedRoot = preferences.getString("published_root", null);
            fixtureRoot = publishedRoot == null ? oneShot : new File(publishedRoot);
            require(fixtureRoot.getCanonicalFile().equals(fixtureRoot) && fixtureRoot.isDirectory()
                    && "exports".equals(fixtureRoot.getName()) && fixtureRoot.getParentFile().getName().matches("broker-[0-9]{1,6}")
                    && root.equals(fixtureRoot.getParentFile().getParentFile()), "private_published_fixture_root");
            if (nativeSession == null) nativeSession = new JSONObject().put("phase", source().isFile() ? "idle" : "rendering")
                    .put("ready", false).put("export_id", OUTPUT).toString();
            UnifiedMP4Export.restoreState(this, state);
            if (state != null && OUTPUT.equals(state.getString("mp4_save_id"))) {
                Bundle restored = new Bundle(); UnifiedMP4Export.saveState(restored);
                require(UnifiedMP4Export.saveInProgress() && OUTPUT.equals(restored.getString("mp4_save_id"))
                        && oneShot.getPath().equals(restored.getString("mp4_save_root")), "actual_pending_bundle_not_restored");
                require(preferences.edit().putInt("pending_recreated", preferences.getInt("pending_recreated", 0) + 1)
                        .putBoolean("pending_restored_active", true).putInt("pending_restored_launches", preferences.getInt("launches", 0)).commit(), "pending_restore_commit");
            }
            JSONObject descriptor = new JSONObject().put("schema", 1).put("available", true).put("epoch", 1)
                    .put("capability", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa").put("directory", broker.getCanonicalPath())
                    .put("export_directory", oneShot.getCanonicalPath()).put("queue_directory", queue.getCanonicalPath())
                    .put("persistent_export_directory", persistent.getCanonicalPath());
            require(UnifiedMP4Export.prepare(this, descriptor.toString()), "production_prepare_failed");
            UnifiedMP4Export.attachGame(this); attached = true;
            Field save = UnifiedMP4Export.class.getDeclaredField("overlaySave"); save.setAccessible(true);
            ((Button) save.get(null)).setContentDescription("qa_production_save");
            UnifiedMP4Export.observe(observer); main.post(tick);
        } catch (Throwable error) { fail(error); }
    }

    private static File directory(File parent, String name) throws Exception {
        File result = new File(parent, name);
        require(result.isDirectory() || result.mkdir(), "private_directory"); Os.chmod(result.getPath(), 0700);
        return result.getCanonicalFile();
    }
    private File source() { return new File(fixtureRoot, OUTPUT + ".mp4"); }
    private void publishFixture() {
        try {
            require(!source().exists() && preferences.getInt("launches", 0) == 0, "fresh_publication_required");
            File partial = new File(oneShot, OUTPUT + ".partial.mp4");
            require(!partial.exists(), "fresh_partial_required");
            try (InputStream input = getAssets().open("fixture.mp4"); FileOutputStream output = new FileOutputStream(partial)) {
                Os.chmod(partial.getPath(), 0600); byte[] bytes = new byte[4096]; int count;
                while ((count = input.read(bytes)) >= 0) output.write(bytes, 0, count);
                output.getFD().sync();
            }
            Os.rename(partial.getPath(), source().getPath());
            require(preferences.edit().putBoolean("published", true).putString("published_root", fixtureRoot.getPath()).commit(), "publication_state_commit");
            nativeSession = new JSONObject().put("phase", "completed").put("ready", false).put("export_id", OUTPUT).toString();
            writeReport();
        } catch (Throwable error) { fail(error); }
    }
    private void finishProof() {
        try {
            require(preferences.getInt("launches", 0) == 3 && preferences.getInt("results", 0) == 3
                    && preferences.getInt("cancelled", 0) == 3 && preferences.getInt("boots", 0) >= 2
                    && preferences.getInt("creations", 0) >= 3 && UnifiedMP4Export.canSave()
                    && preferences.getInt("pending_recreated", 0) >= 1
                    && source().isFile() && sha(source()).equals(assetSha()), "required_real_ui_steps_missing");
            require(preferences.edit().putBoolean("finished", true).commit(), "finish_state_commit"); writeReport();
        } catch (Throwable error) { fail(error); }
    }
    @Override public void startActivityForResult(Intent intent, int request) {
        super.startActivityForResult(intent, request);
        if (Intent.ACTION_CREATE_DOCUMENT.equals(intent.getAction()) || Intent.ACTION_OPEN_DOCUMENT.equals(intent.getAction())) {
            try {
                require(request == UnifiedMP4Export.SAVE_DOCUMENT && Intent.ACTION_CREATE_DOCUMENT.equals(intent.getAction())
                        && "video/mp4".equals(intent.getType()), "unexpected_picker_intent");
                JSONArray records = new JSONArray(preferences.getString("launch_records", "[]"));
                android.content.ComponentName component = intent.resolveActivity(getPackageManager());
                records.put(new JSONObject().put("request", request).put("action", intent.getAction()).put("mime", intent.getType())
                        .put("component", component == null ? "unresolved" : component.flattenToShortString()));
                require(records.length() <= 3 && preferences.edit().putInt("launches", preferences.getInt("launches", 0) + 1)
                        .putString("launch_records", records.toString()).commit(), "launch_state_commit");
                if (records.length() == 2) main.postDelayed(() -> {
                    try {
                        require(UnifiedMP4Export.saveInProgress(), "picker_closed_before_pending_recreation");
                        recreate();
                    } catch (Throwable error) { fail(error); }
                }, 1500);
                writeReport();
            } catch (Throwable error) { fail(error); }
        }
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        UnifiedMP4Export.activityResult(this, request, result, data);
        if (request == UnifiedMP4Export.SAVE_DOCUMENT) {
            SharedPreferences.Editor editor = preferences.edit().putInt("results", preferences.getInt("results", 0) + 1);
            if (result == RESULT_CANCELED) editor.putInt("cancelled", preferences.getInt("cancelled", 0) + 1);
            if (!editor.commit()) failure = "result_state_commit";
            writeReport();
        }
    }
    @Override protected void onStart() { super.onStart(); if (attached) UnifiedMP4Export.gameStarted(this); }
    @Override protected void onResume() { super.onResume(); if (attached) { UnifiedMP4Export.gameResuming(this); UnifiedMP4Export.gameResumed(this); } }
    @Override protected void onPause() { if (attached) UnifiedMP4Export.gamePaused(this); super.onPause(); }
    @Override protected void onStop() { if (attached) UnifiedMP4Export.gameStopped(this); super.onStop(); }
    @Override protected void onDestroy() {
        main.removeCallbacks(tick); UnifiedMP4Export.removeObserver(observer);
        if (attached) UnifiedMP4Export.gameDestroyed(this); super.onDestroy();
    }
    @Override protected void onSaveInstanceState(Bundle state) {
        UnifiedMP4Export.saveState(state);
        if (preferences != null && OUTPUT.equals(state.getString("mp4_save_id"))) {
            if (!preferences.edit().putInt("pending_saved", preferences.getInt("pending_saved", 0) + 1)
                    .putInt("pending_saved_launches", preferences.getInt("launches", 0)).commit()) failure = "pending_state_commit";
        }
        super.onSaveInstanceState(state);
    }

    private void fail(Throwable error) { failure = error.getClass().getSimpleName() + ":" + String.valueOf(error.getMessage()); writeReport(); }
    private JSONObject nativeProof() throws Exception {
        try { return new JSONObject(nativeReceipt()); }
        catch (Throwable error) {
            // A failed JNI load must become an immediate failed receipt. It
            // must not prevent all reporting and appear as a UI timeout.
            if (failure == null) failure = error.getClass().getSimpleName() + ":native_receipt_unavailable";
            return new JSONObject().put("error", "native_receipt_unavailable");
        }
    }
    private void writeReport() {
        if (root == null || preferences == null) { label.setText("FAIL: fixture setup"); return; }
        try {
            JSONObject nativeReceipt = nativeProof();
            JSONObject report = new JSONObject().put("schema", 1).put("package", getPackageName()).put("challenge", challenge)
                    .put("phase", failure != null ? "failed" : preferences.getBoolean("finished", false) ? "completed" : "observing")
                    .put("scope", "synthetic_mp4_save_ui_only").put("java_uid", Process.myUid()).put("java_pid", Process.myPid())
                    .put("launch_mode", launchMode)
                    .put("android_api", android.os.Build.VERSION.SDK_INT).put("native", nativeReceipt)
                    .put("launches", preferences.getInt("launches", 0)).put("results", preferences.getInt("results", 0))
                    .put("cancelled", preferences.getInt("cancelled", 0)).put("boots", preferences.getInt("boots", 0))
                    .put("creations", preferences.getInt("creations", 0)).put("can_save", UnifiedMP4Export.canSave())
                    .put("pending_saved", preferences.getInt("pending_saved", 0)).put("pending_saved_launches", preferences.getInt("pending_saved_launches", 0))
                    .put("pending_recreated", preferences.getInt("pending_recreated", 0)).put("pending_restored_active", preferences.getBoolean("pending_restored_active", false))
                    .put("pending_restored_launches", preferences.getInt("pending_restored_launches", 0))
                    .put("picker_or_copy_active", UnifiedMP4Export.saveInProgress()).put("completed_outputs", UnifiedMP4Export.completedOutputs().size())
                    .put("native_phase", new JSONObject(nativeSession).optString("phase"))
                    .put("configured_output_changed", !oneShot.equals(fixtureRoot))
                    .put("fixture_asset_sha256", assetSha()).put("source_exists", source().isFile())
                    .put("source_bytes", source().isFile() ? source().length() : 0)
                    .put("source_sha256", source().isFile() ? sha(source()) : JSONObject.NULL)
                    .put("document_launches", new JSONArray(preferences.getString("launch_records", "[]")))
                    .put("document_events", UnifiedMP4Export.diagnostics().optJSONArray("document_picker_events"));
            if (failure != null) report.put("error", failure.substring(0, Math.min(256, failure.length())));
            byte[] bytes = (report.toString(2) + "\n").getBytes(java.nio.charset.StandardCharsets.UTF_8);
            require(bytes.length <= 32768, "bounded_report");
            File temporary = new File(root, "report.tmp");
            try (FileOutputStream output = new FileOutputStream(temporary)) { Os.chmod(temporary.getPath(), 0600); output.write(bytes); output.getFD().sync(); }
            Os.rename(temporary.getPath(), new File(root, "report.json").getPath());
            label.setText(failure != null ? "FAIL: " + failure : preferences.getBoolean("finished", false)
                    ? "PASS: actual Android Save/cancel/recreation/cold restore" : "Synthetic MP4 Save UI fixture · launches " + preferences.getInt("launches", 0));
        } catch (Throwable error) { label.setText("FAIL: bounded report unavailable"); }
    }
    private String assetSha() throws Exception { try (InputStream input = getAssets().open("fixture.mp4")) { return digest(input); } }
    private static String sha(File file) throws Exception { try (InputStream input = new FileInputStream(file)) { return digest(input); } }
    private static String digest(InputStream input) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256"); byte[] bytes = new byte[4096]; int count;
        while ((count = input.read(bytes)) >= 0) digest.update(bytes, 0, count);
        StringBuilder result = new StringBuilder(); for (byte value : digest.digest()) result.append(String.format(java.util.Locale.ROOT, "%02x", value & 255)); return result.toString();
    }
    private static void require(boolean value, String code) { if (!value) throw new IllegalStateException(code); }
}
