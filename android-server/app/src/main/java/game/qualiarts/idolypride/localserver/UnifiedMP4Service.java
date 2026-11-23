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
import android.os.SystemClock;
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
    private String shown = "";
    private final Runnable expired = () -> stopJob("background_time_budget", false);
    // startForegroundService() obliges the started record to reach
    // startForeground(); bringing it down first makes the system crash the
    // whole app ("did not then call Service.startForeground()"). A stop that
    // arrives while a start is in flight is applied right after promotion.
    // Main thread only, like every caller.
    private static final long START_GRACE_MS = 10_000L;
    private static boolean startPending, stopRequested;
    private static long startRequestedAt;
    static boolean start(Context context) {
        try { context.startForegroundService(new Intent(context, UnifiedMP4Service.class)); }
        catch (RuntimeException unavailable) { return false; }
        startPending = true; stopRequested = false; startRequestedAt = SystemClock.uptimeMillis();
        return true;
    }
    static void stop(Context context) {
        UnifiedMP4Service owner = current.get();
        if (owner != null) owner.stopping = true;
        if (startPending && SystemClock.uptimeMillis() - startRequestedAt < START_GRACE_MS) { stopRequested = true; return; }
        startPending = false; stopRequested = false;
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
        // Promote first, with a constant notification, on every start: this
        // record came from startForegroundService even when it is unwanted.
        boolean promoted = foreground;
        if (!promoted) try {
            // Public SDK constants: mediaProcessing=8192(API35), dataSync=1.
            startForeground(NOTIFICATION, notification(getString(R.string.mp4_progress_title), 0, 0),
                    Build.VERSION.SDK_INT >= 35 ? 8192 : 1);
            promoted = true;
        } catch (RuntimeException unavailable) { /* Stopped below. */ }
        boolean wanted = promoted && !stopping && !stopRequested && UnifiedMP4Background.expectsService();
        startPending = false; stopRequested = false;
        if (!promoted) { stopJob("background_service_unavailable", false); return START_NOT_STICKY; }
        if (!wanted) { stopping = true; stopForeground(STOP_FOREGROUND_REMOVE); stopSelf(); return START_NOT_STICKY; }
        if (!foreground) try {
            PowerManager power = (PowerManager)getSystemService(POWER_SERVICE);
            wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, getPackageName() + ":mp4-export");
            wakeLock.setReferenceCounted(false); wakeLock.acquire(BUDGET_MS + 10_000);
            foreground = true; main.postDelayed(expired, BUDGET_MS); UnifiedMP4Background.serviceStarted();
        } catch (RuntimeException unavailable) { stopJob("background_service_unavailable", false); }
        return START_NOT_STICKY;
    }
    private Notification notification(String text, long frames, long total) {
        PendingIntent open = PendingIntent.getActivity(this, NOTIFICATION, new Intent(this, MainActivity.class),
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        PendingIntent cancel = PendingIntent.getService(this, NOTIFICATION,
            new Intent(this, UnifiedMP4Service.class).setAction(CANCEL), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        String body = text == null || text.isEmpty() ? getString(R.string.mp4_progress_title) : text;
        int newline = body.indexOf('\n');
        Notification.Builder builder = new Notification.Builder(this, CHANNEL)
            .setSmallIcon(UnifiedRuntime.notificationIcon(this, R.drawable.ic_server))
            .setContentTitle(getString(R.string.mp4_progress_title)).setContentText(newline < 0 ? body : body.substring(0, newline))
            .setStyle(new Notification.BigTextStyle().bigText(body))
            .setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true)
            .addAction(new Notification.Action.Builder(null, getString(R.string.mp4_cancel), cancel).build());
        // Show real encoder progress only; preparation and cleanup are not 0/0 frames.
        if (total > 0 && total <= Integer.MAX_VALUE && frames >= 0)
            builder.setProgress((int) total, (int) Math.min(frames, total), false);
        return builder.build();
    }
    /** Main thread only: mirror the same status text the in-game overlay shows. */
    static void update(String text, long frames, long total) {
        UnifiedMP4Service owner = current.get();
        if (owner == null || !owner.foreground || owner.stopping || text == null) return;
        String key = text + "\n" + frames + "/" + total;
        if (key.equals(owner.shown)) return;
        owner.shown = key;
        try {
            NotificationManager manager = (NotificationManager) owner.getSystemService(NOTIFICATION_SERVICE);
            manager.notify(NOTIFICATION, owner.notification(text, frames, total));
        } catch (RuntimeException ignored) { /* A notification update never changes export ownership. */ }
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
