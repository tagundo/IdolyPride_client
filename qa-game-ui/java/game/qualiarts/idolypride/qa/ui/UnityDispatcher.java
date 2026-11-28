package game.qualiarts.idolypride.qa.ui;

import android.app.Activity;
import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import java.lang.ref.WeakReference;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/** Resolve the current Unity player on Android's main queue, then use its GL queue. */
final class UnityDispatcher implements LoopbackUiServer.Actions {
    private static final long REQUEST_MILLIS = 8000;
    private final Context context;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final long sessionDeadline;
    private volatile boolean stopped;
    private volatile boolean unityReady;

    UnityDispatcher(Context context, long sessionMillis) {
        this.context = context.getApplicationContext();
        sessionDeadline = SystemClock.elapsedRealtime() + LoopbackUiServer.checkedSessionMillis(sessionMillis);
    }

    void start() { main.post(new Poll(this)); }
    void stop() { stopped = true; unityReady = false; main.removeCallbacksAndMessages(this); }

    @Override public String health() {
        return "{\"ok\":true,\"schema\":1,\"qa_only\":true,\"emulator_only\":true,\"native_loaded\":true,\"native_click_available\":false,\"unity_ready\":"
            + unityReady + "}";
    }

    @Override public String snapshot() { return execute(false, 0, 0); }
    @Override public String mp4Status() {
        if (stopped || SystemClock.elapsedRealtime() >= sessionDeadline) return LoopbackUiServer.error("session_ended");
        return QaMp4Observation.snapshot(context);
    }
    @Override public String mp4Diagnostics() {
        if (stopped || SystemClock.elapsedRealtime() >= sessionDeadline) return LoopbackUiServer.error("session_ended");
        // The app builds its diagnostics-export document on the main thread; do the same, bounded.
        ApplicationDiagnostics read = new ApplicationDiagnostics(context);
        main.post(read);
        boolean finished;
        try {
            finished = read.finished.await(3000, TimeUnit.MILLISECONDS);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            finished = false;
        }
        return QaMp4Observation.diagnostics(context, finished ? read.document : null,
            finished ? "app_diagnostics_unavailable" : "app_diagnostics_main_thread_timeout");
    }
    @Override public String click(int instanceId, long generation) { return execute(true, instanceId, generation); }

    private static final class ApplicationDiagnostics implements Runnable {
        private final Context context;
        final CountDownLatch finished = new CountDownLatch(1);
        volatile String document;
        ApplicationDiagnostics(Context context) { this.context = context; }
        @Override public void run() {
            try { document = QaMp4Observation.applicationDiagnostics(context); }
            finally { finished.countDown(); }
        }
    }

    private String execute(boolean click, int instanceId, long generation) {
        if (stopped || SystemClock.elapsedRealtime() >= sessionDeadline) return LoopbackUiServer.error("session_ended");
        Operation operation = new Operation(click, instanceId, generation);
        main.post(new Enqueue(this, operation));
        try {
            if (!operation.finished.await(REQUEST_MILLIS, TimeUnit.MILLISECONDS)) operation.cancel("unity_timeout");
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            operation.cancel("request_interrupted");
        }
        return operation.response == null ? LoopbackUiServer.error("unity_timeout") : operation.response;
    }

    private Object resolvePlayer() {
        if (Looper.myLooper() != Looper.getMainLooper()) return null;
        try {
            Class<?> unity = Class.forName("com.unity3d.player.UnityPlayer", false, context.getClassLoader());
            Field current = unity.getDeclaredField("currentActivity");
            current.setAccessible(true);
            Object value = current.get(null);
            if (!(value instanceof Activity)) return null;
            Activity activity = (Activity) value;
            if (activity.isFinishing() || activity.isDestroyed()) return null;
            for (Class<?> type = activity.getClass(); type != null; type = type.getSuperclass()) {
                try {
                    Field player = type.getDeclaredField("mUnityPlayer");
                    player.setAccessible(true);
                    Object found = player.get(activity);
                    return unity.isInstance(found) ? found : null;
                } catch (NoSuchFieldException ignored) { /* The field belongs to UnityPlayerActivity. */ }
            }
        } catch (ReflectiveOperationException | RuntimeException | LinkageError ignored) {
            // Fixed failure only. Reflection exceptions may contain app state.
        }
        return null;
    }

    private static Method queueMethod(Object player) throws NoSuchMethodException {
        for (Class<?> type = player.getClass(); type != null; type = type.getSuperclass()) {
            try {
                Method result = type.getDeclaredMethod("queueGLThreadEvent", Runnable.class);
                result.setAccessible(true);
                return result;
            } catch (NoSuchMethodException ignored) { /* Try the exact Unity superclass method. */ }
        }
        throw new NoSuchMethodException("Unity queue unavailable");
    }

    private static final class Poll implements Runnable {
        private final WeakReference<UnityDispatcher> owner;
        Poll(UnityDispatcher owner) { this.owner = new WeakReference<>(owner); }
        @Override public void run() {
            UnityDispatcher dispatcher = owner.get();
            if (dispatcher == null || dispatcher.stopped || SystemClock.elapsedRealtime() >= dispatcher.sessionDeadline) return;
            dispatcher.unityReady = dispatcher.resolvePlayer() != null;
            dispatcher.main.postAtTime(this, dispatcher, SystemClock.uptimeMillis() + 250);
        }
    }

    private static final class Enqueue implements Runnable {
        private final UnityDispatcher owner;
        private final Operation operation;
        Enqueue(UnityDispatcher owner, Operation operation) { this.owner = owner; this.operation = operation; }
        @Override public void run() {
            if (operation.expired() || owner.stopped) { operation.cancel("unity_unavailable"); return; }
            Object player = owner.resolvePlayer();
            owner.unityReady = player != null;
            if (player == null) {
                owner.main.postAtTime(this, owner, SystemClock.uptimeMillis() + 100);
                return;
            }
            try { queueMethod(player).invoke(player, new NativeOperation(operation)); }
            catch (ReflectiveOperationException | RuntimeException | LinkageError ignored) {
                operation.cancel("unity_queue_unavailable");
            }
        }
    }

    private static final class NativeOperation implements Runnable {
        private final Operation operation;
        NativeOperation(Operation operation) { this.operation = operation; }
        @Override public void run() {
            if (operation.expired()) { operation.cancel("unity_timeout"); return; }
            if (!Thread.currentThread().getName().equals("UnityMain")) {
                operation.cancel("wrong_unity_thread"); return;
            }
            try {
                String response = operation.click
                    ? NativeUiBridge.nativeClick(operation.instanceId, operation.generation)
                    : NativeUiBridge.nativeSnapshot();
                operation.complete(response == null ? LoopbackUiServer.error("native_unavailable") : response);
            } catch (Throwable ignored) { operation.complete(LoopbackUiServer.error("native_failure")); }
        }
    }

    private static final class Operation {
        final boolean click;
        final int instanceId;
        final long generation;
        final long deadline = SystemClock.elapsedRealtime() + REQUEST_MILLIS;
        final CountDownLatch finished = new CountDownLatch(1);
        final AtomicBoolean completed = new AtomicBoolean();
        final AtomicBoolean cancelled = new AtomicBoolean();
        volatile String response;
        Operation(boolean click, int instanceId, long generation) {
            this.click = click; this.instanceId = instanceId; this.generation = generation;
        }
        boolean expired() { return cancelled.get() || completed.get() || SystemClock.elapsedRealtime() >= deadline; }
        void cancel(String code) { cancelled.set(true); complete(LoopbackUiServer.error(code)); }
        void complete(String value) {
            if (!completed.compareAndSet(false, true)) return;
            response = value;
            finished.countDown();
        }
    }
}
