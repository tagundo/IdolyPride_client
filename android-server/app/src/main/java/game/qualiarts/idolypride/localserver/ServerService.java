package game.qualiarts.idolypride.localserver;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.Context;
import android.net.Uri;
import android.widget.Toast;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;
import android.os.Environment;
import java.io.File;
import android.util.Log;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import org.json.JSONObject;
import org.json.JSONArray;

import java.io.OutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.AtomicBoolean;

/** Owns one embedded Python server and serializes its start/stop lifecycle. */
public final class ServerService extends Service {
    public static final String ACTION_START = "game.qualiarts.idolypride.localserver.START";
    public static final String ACTION_STOP = "game.qualiarts.idolypride.localserver.STOP";
    private static final String CHANNEL = "local-server";
    private static final int NOTIFICATION_ID = 50051;
    private static final int LOG_LIMIT = 400;
    private static final Object PYTHON_LOCK = new Object();
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final CopyOnWriteArrayList<Observer> OBSERVERS = new CopyOnWriteArrayList<>();
    private static final ArrayDeque<String> LOGS = new ArrayDeque<>();
    private static volatile String status = "중지됨";
    private static volatile boolean running = false;
    private static volatile boolean busy = false;
    private static volatile String runtimeDetails = "{}";
    private static volatile long runtimeDetailsReceivedAt;
    private static volatile String lastDiagnostics = "{}";
    private static volatile ServerService activeService;
    private static final AtomicBoolean EXPORT_BUSY = new AtomicBoolean(false);
    private static final ExecutorService EXPORT_IO = Executors.newSingleThreadExecutor(task -> {
        Thread thread = new Thread(task, "diagnostic-export");
        thread.setDaemon(true);
        return thread;
    });

    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final AtomicBoolean stopQueued = new AtomicBoolean(false);
    private final AtomicBoolean startQueued = new AtomicBoolean(false);
    private PyObject runtime;
    private volatile boolean destroyed = false;
    private final AtomicBoolean pollQueued = new AtomicBoolean(false);
    private final AtomicBoolean resourceCancelQueued = new AtomicBoolean(false);
    private final Runnable pollState = () -> queuePoll();

    public interface Observer {
        void onServerChanged(String state, boolean isRunning, boolean isBusy, List<String> logs, String detailsJson);
    }

    /** Advances only for a validated Python status response, never a log replay. */
    static long runtimeDetailsReceivedAt() { return runtimeDetailsReceivedAt; }

    static boolean resourceServerRunning() {
        ServerService service = activeService;
        return running && !busy && service != null && !service.destroyed && !service.stopQueued.get();
    }
    static void resourceTransferChanged() { dispatch(); }
    /** Called only by the app-context resource I/O worker, not the lifecycle worker. */
    static String importResourceFd(int fd, String platform) throws IOException {
        ServerService service = activeService;
        if (!resourceServerRunning() || service == null || service.runtime == null || fd < 0 || !ResourceTransfers.platform(platform))
            throw new IOException("Resource server unavailable");
        return service.runtime.callAttr("import_resources_fd", fd, platform).toString();
    }
    static void cancelResourceJob(String identifier) {
        ResourceTransfers.cancelLocal();
        ServerService service = activeService;
        if (identifier == null || !identifier.matches("[A-Za-z0-9_-]{1,64}") || service == null
                || service.destroyed || !service.resourceCancelQueued.compareAndSet(false, true)) return;
        try {
            service.worker.execute(() -> {
                try { if (service.runtime != null) service.runtime.callAttr("cancel_resource_job", identifier); }
                catch (Exception error) { Log.w("IdolyLocalServer", "Resource cancellation unavailable: " + error.getClass().getSimpleName()); }
                finally { service.resourceCancelQueued.set(false); dispatch(); }
            });
        } catch (RejectedExecutionException stopped) { service.resourceCancelQueued.set(false); }
    }

    public static void observe(Observer observer) {
        OBSERVERS.addIfAbsent(observer);
        dispatch();
    }

    public static void removeObserver(Observer observer) {
        OBSERVERS.remove(observer);
    }

    private static void dispatch() {
        final List<String> snapshot;
        synchronized (LOGS) {
            snapshot = new ArrayList<>(LOGS);
        }
        final String currentStatus = status;
        final boolean currentRunning = running;
        final boolean currentBusy = busy;
        final String currentDetails = runtimeDetails;
        MAIN.post(() -> {
            for (Observer observer : OBSERVERS) {
                observer.onServerChanged(currentStatus, currentRunning, currentBusy, snapshot, currentDetails);
            }
        });
    }

    private static void state(String value, boolean isRunning, boolean isBusy) {
        status = value;
        running = isRunning;
        busy = isBusy;
        dispatch();
    }

    private static void appendLog(String message) {
        if (message == null || message.isEmpty()) return;
        synchronized (LOGS) {
            for (String line : message.split("\\r?\\n")) {
                if (line.isEmpty()) continue;
                LOGS.addLast(line.length() > 2000 ? line.substring(0, 2000) : line);
                while (LOGS.size() > LOG_LIMIT) LOGS.removeFirst();
            }
        }
        dispatch();
    }

    /** Called by the Python runtime. No request bodies or credentials belong here. */
    public static final class LogCallback {
        public void log(String message) { appendLog(message); }
    }

    @Override public void onCreate() {
        super.onCreate();
        activeService = this;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(CHANNEL,
                    getString(R.string.notification_channel), NotificationManager.IMPORTANCE_LOW);
            getSystemService(NotificationManager.class).createNotificationChannel(channel);
        }
    }

    private Notification notification() {
        int flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE;
        PendingIntent open = PendingIntent.getActivity(this, 0,
                new Intent(this, MainActivity.class), flags);
        PendingIntent stop = PendingIntent.getService(this, 1,
                new Intent(this, ServerService.class).setAction(ACTION_STOP), flags);
        return new Notification.Builder(this, CHANNEL)
                .setSmallIcon(R.drawable.ic_server)
                .setContentTitle(getString(R.string.app_name))
                .setContentText(getString(R.string.notification_text))
                .setContentIntent(open)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .addAction(new Notification.Action.Builder(null, getString(R.string.stop_server), stop).build())
                .build();
    }

    private void foreground() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIFICATION_ID, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        } else {
            startForeground(NOTIFICATION_ID, notification());
        }
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? null : intent.getAction();
        if (ACTION_STOP.equals(action)) {
            queueStop(true);
            return START_NOT_STICKY;
        }
        if (!ACTION_START.equals(action)) {
            stopSelf();
            return START_NOT_STICKY;
        }
        final boolean experimentalMainLive = getSharedPreferences(MainActivity.SERVER_PREFS, MODE_PRIVATE)
                .getBoolean(MainActivity.EXPERIMENTAL_MAIN_LIVE, false);
        final boolean downloadMissingResources = getSharedPreferences(MainActivity.SERVER_PREFS, MODE_PRIVATE)
                .getBoolean(MainActivity.DOWNLOAD_MISSING_RESOURCES, true);
        final boolean mediaMode = getSharedPreferences(MainActivity.SERVER_PREFS, MODE_PRIVATE)
                .getBoolean(MainActivity.MEDIA_MODE, false);
        final boolean publicDownloads = getSharedPreferences(MainActivity.SERVER_PREFS, MODE_PRIVATE)
                .getBoolean(MainActivity.RESOURCE_PUBLIC_DOWNLOADS, true);
        foreground();
        if (!startQueued.compareAndSet(false, true)) return START_NOT_STICKY;
        runtimeDetails = "{}";
        state(getString(R.string.status_starting), false, true);
        appendLog("서버 데이터를 준비하고 있습니다.");
        worker.execute(() -> {
            if (stopQueued.get()) return;
            try {
                String resourceCacheDirectory = null;
                if (publicDownloads) {
                    boolean permission = Build.VERSION.SDK_INT >= 30 && Environment.isExternalStorageManager();
                    if (ResourceTransfers.storageAccess(Build.VERSION.SDK_INT, true, permission) != ResourceTransfers.STORAGE_DOWNLOADS)
                        throw new SecurityException("Downloads storage permission is required");
                    resourceCacheDirectory = ResourceTransfers.publicCachePath(
                            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS));
                }
                synchronized (PYTHON_LOCK) {
                    if (!Python.isStarted()) Python.start(new AndroidPlatform(getApplicationContext()));
                }
                runtime = Python.getInstance().getModule("android_server_runtime");
                runtime.callAttr("start", getFilesDir().getAbsolutePath(), getAssets(), new LogCallback(),
                        getApplicationInfo().nativeLibraryDir, experimentalMainLive, downloadMissingResources, mediaMode, resourceCacheDirectory);
                JSONObject details = new JSONObject(runtime.callAttr("status_json").toString());
                runtimeDetails = details.toString();
                if (!details.optBoolean("running", false)) {
                    throw new IllegalStateException("Runtime did not start");
                }
                runtimeDetailsReceivedAt = SystemClock.elapsedRealtime();
                if (!stopQueued.get()) {
                    state(getString(R.string.status_running), true, false);
                    appendLog("게임 연결 127.0.0.1:50051 · 파일 전송 127.0.0.1:8080");
                    MAIN.postDelayed(pollState, 1500);
                }
            } catch (Throwable error) {
                Log.e("IdolyLocalServer", "Embedded server startup failed", error);
                appendLog("서버 시작 실패 (" + error.getClass().getSimpleName() + "). 앱 데이터와 포함된 서버 파일을 확인해 주세요.");
                state(getString(R.string.status_failed), false, false);
                queueStop(true, true);
            }
        });
        return START_NOT_STICKY;
    }

    private void queueStop(boolean finishService) { queueStop(finishService, false); }

    private void queueStop(boolean finishService, boolean keepFailure) {
        if (!stopQueued.compareAndSet(false, true)) return;
        ResourceTransfers.cancelLocal();
        MAIN.removeCallbacks(pollState);
        if (!keepFailure) state(getString(R.string.status_stopping), running, true);
        try {
            worker.execute(() -> {
                try {
                    if (runtime != null) {
                        lastDiagnostics = captureDiagnostics();
                        runtime.callAttr("stop");
                        runtimeDetails = runtime.callAttr("status_json").toString();
                        lastDiagnostics = captureDiagnostics();
                    }
                } catch (Throwable error) {
                    appendLog("서버 정리 중 오류 (" + error.getClass().getSimpleName() + ").");
                } finally {
                    if (!keepFailure) {
                        appendLog("서버를 중지했습니다.");
                        state(getString(R.string.status_stopped), false, false);
                    }
                    MAIN.post(() -> {
                        stopForeground(STOP_FOREGROUND_REMOVE);
                        if (finishService) stopSelf();
                    });
                }
            });
        } catch (RejectedExecutionException ignored) {
            // The serialized cleanup was already queued by onDestroy.
        }
    }

    @Override public void onDestroy() {
        destroyed = true;
        MAIN.removeCallbacks(pollState);
        if (activeService == this) activeService = null;
        queueStop(false);
        worker.shutdown();
        super.onDestroy();
    }

    /** Poll only on the same worker that owns Python lifecycle calls. */
    private void queuePoll() {
        if (destroyed || stopQueued.get() || !running || !pollQueued.compareAndSet(false, true)) return;
        try {
            worker.execute(() -> {
                try {
                    if (runtime != null && !stopQueued.get()) {
                        String value = runtime.callAttr("status_json").toString();
                        JSONObject details = new JSONObject(value);
                        if (!(details.opt("running") instanceof Boolean)) {
                            throw new IllegalArgumentException("Invalid runtime status");
                        }
                        runtimeDetailsReceivedAt = SystemClock.elapsedRealtime();
                        if (!value.equals(runtimeDetails)) {
                            runtimeDetails = value;
                            dispatch();
                        }
                    }
                } catch (Throwable error) {
                    // Keep the server running when only a display refresh fails.
                    Log.w("IdolyLocalServer", "Diagnostic status refresh failed: " + error.getClass().getSimpleName());
                } finally {
                    pollQueued.set(false);
                    if (!destroyed && !stopQueued.get() && running) MAIN.postDelayed(pollState, 1500);
                }
            });
        } catch (RejectedExecutionException ignored) {
            pollQueued.set(false);
        }
    }

    private String captureDiagnostics() {
        try {
            if (runtime != null) return runtime.callAttr("diagnostics_json").toString();
        } catch (Throwable error) {
            Log.w("IdolyLocalServer", "Diagnostic snapshot unavailable: " + error.getClass().getSimpleName());
        }
        return lastDiagnostics;
    }

    public static boolean isExporting() { return EXPORT_BUSY.get(); }

    /** User-picked document only; capture Python on the service worker, write off it. */
    public static void exportDiagnostics(Context context, Uri destination) {
        Context application = context.getApplicationContext();
        if (!EXPORT_BUSY.compareAndSet(false, true)) return;
        dispatch();
        ServerService service = activeService;
        if (service != null && !service.destroyed) {
            try {
                service.worker.execute(() -> {
                    lastDiagnostics = service.captureDiagnostics();
                    writeExport(application, destination, lastDiagnostics);
                });
                return;
            } catch (RejectedExecutionException ignored) {
                // The stopped service's last safe snapshot remains available.
            }
        }
        writeExport(application, destination, lastDiagnostics);
    }

    private static void writeExport(Context context, Uri destination, String snapshot) {
        final String details = runtimeDetails;
        final List<String> lines;
        synchronized (LOGS) { lines = new ArrayList<>(LOGS); }
        EXPORT_IO.execute(() -> {
            boolean success = false;
            try {
                JSONObject document = new JSONObject();
                document.put("schema", 1);
                document.put("server_version", BuildConfig.VERSION_NAME);
                document.put("server_version_code", BuildConfig.VERSION_CODE);
                document.put("bundled_data_sha256", BuildConfig.SERVER_DATA_SHA256);
                document.put("runtime", new JSONObject(details));
                document.put("diagnostics", new JSONObject(snapshot));
                document.put("server_logs", new JSONArray(lines));
                byte[] encoded = document.toString(2).getBytes(StandardCharsets.UTF_8);
                try (OutputStream stream = context.getContentResolver().openOutputStream(destination, "wt")) {
                    if (stream == null) throw new java.io.IOException("Document is unavailable");
                    stream.write(encoded);
                }
                success = true;
            } catch (Exception error) {
                Log.w("IdolyLocalServer", "Diagnostic export failed: " + error.getClass().getSimpleName());
            } finally {
                EXPORT_BUSY.set(false);
                boolean saved = success;
                MAIN.post(() -> Toast.makeText(context, saved ? R.string.export_saved : R.string.export_failed,
                                               Toast.LENGTH_LONG).show());
                dispatch();
            }
        });
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
