package game.qualiarts.idolypride.localserver;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import java.lang.ref.WeakReference;

/** Dedicated, bounded media job service. Stopping it never stops ServerService. */
public final class UnifiedMP4Service extends Service {
    private static final String CHANNEL = "mp4-export";
    private static final String CANCEL = "game.qualiarts.idolypride.localserver.MP4_CANCEL";
    private static final int NOTIFICATION = 50058;
    private static final long BUDGET_MS = 45 * 60 * 1000L;
    private static WeakReference<UnifiedMP4Service> current = new WeakReference<>(null);
    private final Handler main = new Handler(Looper.getMainLooper());
    private PowerManager.WakeLock wakeLock;
    private boolean stopping, foreground;
    private final Runnable expired = () -> stopJob("background_time_budget", false);
    static boolean start(Context context) {
        try { context.startForegroundService(new Intent(context, UnifiedMP4Service.class)); return true; }
        catch (RuntimeException unavailable) { return false; }
    }
    static void stop(Context context) {
        UnifiedMP4Service owner = current.get();
        if (owner != null) owner.stopping = true;
        context.stopService(new Intent(context, UnifiedMP4Service.class));
    }
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public void onCreate() {
        super.onCreate();
        current = new WeakReference<>(this);
        NotificationManager manager = (NotificationManager)getSystemService(NOTIFICATION_SERVICE);
        manager.createNotificationChannel(new NotificationChannel(CHANNEL,
            getString(R.string.mp4_progress_title), NotificationManager.IMPORTANCE_LOW));
    }
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && CANCEL.equals(intent.getAction())) { stopJob("user_cancelled", true); return START_NOT_STICKY; }
        if (!UnifiedMP4Background.expectsService()) { stopping = true; stopSelf(); return START_NOT_STICKY; }
        if (!foreground && !stopping) try {
            PendingIntent open = PendingIntent.getActivity(this, NOTIFICATION, new Intent(this, MainActivity.class),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            PendingIntent cancel = PendingIntent.getService(this, NOTIFICATION,
                new Intent(this, UnifiedMP4Service.class).setAction(CANCEL), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            Notification notification = new Notification.Builder(this, CHANNEL)
                .setSmallIcon(UnifiedRuntime.notificationIcon(this, R.drawable.ic_server))
                .setContentTitle(getString(R.string.mp4_progress_title)).setContentText(getString(R.string.mp4_rendering, 0, 0))
                .setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true)
                .addAction(new Notification.Action.Builder(null, getString(R.string.mp4_cancel), cancel).build()).build();
            // Public SDK constants: mediaProcessing=8192(API35), dataSync=1.
            startForeground(NOTIFICATION, notification, Build.VERSION.SDK_INT >= 35 ? 8192 : 1);
            PowerManager power = (PowerManager)getSystemService(POWER_SERVICE);
            wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, getPackageName() + ":mp4-export");
            wakeLock.setReferenceCounted(false); wakeLock.acquire(BUDGET_MS + 10_000);
            foreground = true; main.postDelayed(expired, BUDGET_MS); UnifiedMP4Background.serviceStarted();
        } catch (RuntimeException unavailable) { stopJob("background_service_unavailable", false); }
        return START_NOT_STICKY;
    }
    // Public callback added in API35; deliberately compiles against SDK34 too.
    public void onTimeout(int startId, int fgsType) { stopJob("background_service_timeout", false); }
    private void stopJob(String reason, boolean cancelled) {
        if (stopping) return; stopping = true;
        stopForeground(STOP_FOREGROUND_REMOVE); stopSelf();
        releaseWakeLock();
        // Meet the OS service deadline before Unity's own bounded detach wait.
        main.post(() -> UnifiedMP4Background.serviceStopped(reason, cancelled));
    }
    private void releaseWakeLock() {
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        wakeLock = null;
    }
    @Override public void onDestroy() {
        main.removeCallbacks(expired);
        releaseWakeLock();
        if (!stopping) UnifiedMP4Background.serviceStopped("background_service_stopped", false);
        if (current.get() == this) current.clear();
        super.onDestroy();
    }
}
