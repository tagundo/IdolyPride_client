package game.qualiarts.idolypride.localserver;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.util.Log;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import org.json.JSONObject;

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

    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final AtomicBoolean stopQueued = new AtomicBoolean(false);
    private final AtomicBoolean startQueued = new AtomicBoolean(false);
    private PyObject runtime;

    public interface Observer {
        void onServerChanged(String state, boolean isRunning, boolean isBusy, List<String> logs);
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
        MAIN.post(() -> {
            for (Observer observer : OBSERVERS) {
                observer.onServerChanged(currentStatus, currentRunning, currentBusy, snapshot);
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
        foreground();
        if (!startQueued.compareAndSet(false, true)) return START_NOT_STICKY;
        state(getString(R.string.status_starting), false, true);
        appendLog("서버 데이터를 준비하고 있습니다.");
        worker.execute(() -> {
            if (stopQueued.get()) return;
            try {
                synchronized (PYTHON_LOCK) {
                    if (!Python.isStarted()) Python.start(new AndroidPlatform(getApplicationContext()));
                }
                runtime = Python.getInstance().getModule("android_server_runtime");
                runtime.callAttr("start", getFilesDir().getAbsolutePath(), getAssets(), new LogCallback());
                JSONObject details = new JSONObject(runtime.callAttr("status_json").toString());
                if (!details.optBoolean("running", false)) {
                    throw new IllegalStateException("Runtime did not start");
                }
                if (!stopQueued.get()) {
                    state(getString(R.string.status_running), true, false);
                    appendLog("게임 연결 127.0.0.1:50051 · 파일 전송 127.0.0.1:8080");
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
        if (!keepFailure) state(getString(R.string.status_stopping), running, true);
        try {
            worker.execute(() -> {
                try {
                    if (runtime != null) runtime.callAttr("stop");
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
        queueStop(false);
        worker.shutdown();
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
