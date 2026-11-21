package game.qualiarts.idolypride.localserver;

import android.app.Activity;
import android.graphics.SurfaceTexture;
import android.opengl.EGL14;
import android.opengl.EGLConfig;
import android.opengl.EGLContext;
import android.opengl.EGLDisplay;
import android.opengl.EGLSurface;
import android.opengl.GLES20;
import android.opengl.GLES11Ext;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Looper;
import android.os.SystemClock;
import android.view.Surface;
import java.lang.ref.WeakReference;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import org.json.JSONObject;

/** Experimental original-Unity transport. A valid Surface alone is never proof of rendering. */
final class UnifiedMP4Background {
    interface Host {
        JSONObject status();
        void park();
        void resume();
        boolean userPaused();
        void changed();
    }
    interface Player {
        boolean display(Surface surface) throws Exception;
        void focus(boolean focused) throws Exception;
        void resume() throws Exception;
        void pause() throws Exception;
    }
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static UnifiedMP4Background current;
    private static String lastState = "off", lastError = "none";
    private final WeakReference<Activity> activity;
    private final Host host;
    private final Player player;
    private final ProgressGate gate = new ProgressGate();
    private Drain drain;
    private boolean serviceReady, hidden, attached, awaitingDetach, releaseRequested, disposed;
    private long detachTicks;
    private long attemptDrained;
    private String state = "preparing", error = "none";

    /** Only called as a direct consequence of an export started in the foreground. */
    static void prepare(Activity activity, Host host) {
        if (current != null) return;
        try {
            UnifiedMP4Background next = new UnifiedMP4Background(activity, host, originalPlayer(activity));
            lastState = "preparing"; lastError = "none";
            current = next;
            if (!UnifiedMP4Service.start(activity)) { next.fail("service_start_failed"); return; }
            int width = activity.getWindow().getDecorView().getWidth();
            int height = activity.getWindow().getDecorView().getHeight();
            if (width < 16 || height < 16 || width > 8192 || height > 8192
                    || (long) width * height > 16_777_216L) { next.fail("surface_geometry_invalid"); return; }
            next.drain = new Drain(width, height, surface -> {
                if (current != next || next.disposed) return;
                next.state = next.serviceReady ? "ready" : "preparing";
                if (next.hidden && next.serviceReady) backgrounded(activity);
                next.host.changed();
            }, () -> next.fail("surface_consumer_failed"));
            next.drain.start();
        } catch (Exception | LinkageError unavailable) {
            lastState = "paused"; lastError = "original_player_unavailable";
            host.park(); host.changed(); UnifiedMP4Service.stop(activity);
        }
    }
    private UnifiedMP4Background(Activity activity, Host host, Player player) {
        this.activity = new WeakReference<>(activity); this.host = host; this.player = player;
    }
    static void serviceStarted() {
        if (current != null) {
            current.serviceReady = true;
            if (current.drain != null && current.drain.surface != null) current.state = "ready";
            Activity target = current.activity.get();
            if (current.hidden && target != null && current.drain != null && current.drain.surface != null) backgrounded(target);
            current.host.changed();
        }
    }
    static boolean expectsService() { return current != null && !current.disposed && !current.releaseRequested; }
    static void serviceStopped(String reason, boolean cancelled) {
        if (current == null) return;
        if (cancelled) { UnifiedMP4Export.queuePause(); UnifiedMP4Export.cancel(); }
        else current.fail(reason);
    }
    static void backgrounded(Activity activity) {
        UnifiedMP4Background owner = current;
        if (owner == null || owner.activity.get() != activity || owner.disposed) return;
        owner.hidden = true;
        if (owner.host.userPaused() || !owner.error.equals("none")) return;
        if (owner.attached) { owner.reassert(); return; }
        if (owner.awaitingDetach) { owner.fail("surface_detach_unconfirmed"); return; }
        if (!owner.serviceReady || owner.drain == null || owner.drain.surface == null) {
            owner.host.park();
            MAIN.postDelayed(() -> {
                if (current == owner && owner.hidden && !owner.attached && !owner.disposed) owner.fail("transport_not_ready");
            }, ProgressGate.TIMEOUT_MS);
            return;
        }
        try {
            owner.host.park();
            // This public wrapper queues nativeRecreateGfxState on UnityMain,
            // sets its primary-display override, and detaches the SurfaceView.
            if (!owner.player.display(owner.drain.surface)) throw new IllegalStateException();
            owner.attached = true; owner.state = "probing";
            JSONObject status = owner.host.status();
            owner.attemptDrained = owner.drain.frames;
            owner.gate.begin(SystemClock.elapsedRealtime(), status.optLong("unity_ticks"), status.optLong("capture_acks"));
            owner.reassert(); owner.host.changed();
        } catch (Exception | LinkageError unavailable) { owner.fail("surface_attach_failed"); }
    }
    static void foregrounding(Activity activity) {
        UnifiedMP4Background owner = current;
        if (owner == null || owner.activity.get() != activity) return;
        owner.hidden = false; owner.detach();
    }
    static void focusLost(Activity activity) {
        UnifiedMP4Background owner = current;
        if (owner != null && owner.activity.get() == activity && owner.hidden && owner.attached) owner.reassert();
    }
    static boolean ownsSurface(Activity activity) {
        return current != null && current.activity.get() == activity && (current.attached || current.awaitingDetach);
    }
    static boolean runningHidden() { return current != null && current.hidden && current.attached && !current.host.userPaused(); }
    static void sample(JSONObject status) {
        UnifiedMP4Background owner = current;
        if (owner == null) return;
        long ticks = status.optLong("unity_ticks");
        if (owner.awaitingDetach && ticks - owner.detachTicks >= 2) {
            // A later actual Unity tick proves its message queue passed the
            // preceding primary-window detach. Never trust displayChanged's
            // boolean alone: its original timeout path also returns true.
            owner.awaitingDetach = false;
            if (owner.releaseRequested) owner.release();
        }
        if (owner.disposed) return;
        String phase = status.optString("phase");
        if (!UnifiedMP4Export.backgroundQueueHasWork() &&
                (phase.equals("completed") || phase.equals("cancelled") || phase.equals("failed") || phase.equals("idle"))) {
            owner.stop(); return;
        }
        if (!owner.hidden || !owner.attached || owner.host.userPaused()) return;
        if (!owner.gate.sample(SystemClock.elapsedRealtime(), ticks, status.optLong("capture_acks"),
                phase.equals("rendering") || status.optString("resume_phase").equals("rendering"), owner.drain.frames - owner.attemptDrained)) {
            owner.fail("background_progress_stalled"); return;
        }
        owner.state = owner.gate.captureVerified ? "running" : "probing";
    }
    static void stopCurrent() { if (current != null) current.stop(); }
    static JSONObject snapshot() {
        JSONObject result = new JSONObject();
        try {
            UnifiedMP4Background owner = current;
            result.put("experimental", true).put("device_verified", false)
                .put("state", owner == null ? lastState : owner.state)
                .put("error_code", owner == null ? lastError : owner.error)
                .put("heartbeat_verified", owner != null && owner.gate.heartbeatVerified)
                .put("capture_verified", owner != null && owner.gate.captureVerified);
        } catch (Exception ignored) { /* Fixed scalar values only. */ }
        return result;
    }
    private void reassert() {
        if (!hidden || !attached || disposed || host.userPaused()) return;
        try {
            // Original onPause/onStop/focus callbacks have already run. This
            // scoped focus belongs only to the owned, drained offscreen surface.
            player.focus(true); player.resume(); host.resume();
        } catch (Exception | LinkageError unavailable) { fail("player_resume_failed"); }
    }
    private void detach() {
        if (!attached) return;
        host.park();
        try {
            player.pause();
            detachTicks = host.status().optLong("unity_ticks");
            awaitingDetach = true;
            if (!player.display(null)) throw new IllegalStateException();
            attached = false;
            player.focus(false);
            state = error.equals("none") ? "ready" : "paused";
        } catch (Exception | LinkageError unavailable) {
            // Keep draining and retain the single surface until foreground
            // recovery; releasing it under a stalled Unity render is unsafe.
            state = "paused"; error = "surface_detach_unconfirmed";
        }
    }
    private void fail(String reason) {
        if (disposed) return;
        error = reason; state = "paused"; host.park(); detach();
        Activity target = activity.get();
        if (target != null) UnifiedMP4Service.stop(target);
        releaseRequested = true;
        if (!attached && !awaitingDetach) release();
        host.changed();
    }
    private void stop() {
        if (disposed) return;
        releaseRequested = true; detach();
        Activity target = activity.get();
        if (target != null) UnifiedMP4Service.stop(target);
        if (!attached && !awaitingDetach) release();
    }
    private void release() {
        if (disposed || attached || awaitingDetach) return;
        disposed = true;
        lastState = error.equals("none") ? "off" : "paused"; lastError = error;
        if (drain != null) drain.close();
        if (current == this) current = null;
    }
    private static Player originalPlayer(Activity activity) throws Exception {
        Class<?> owner = activity.getClass();
        while (owner != null && !owner.getName().equals("com.unity3d.player.UnityPlayerActivity")) owner = owner.getSuperclass();
        if (owner == null) throw new IllegalStateException("original_unity_activity_missing");
        Field field = owner.getDeclaredField("mUnityPlayer"); field.setAccessible(true);
        Object player = field.get(activity);
        if (player == null || !player.getClass().getName().equals("com.unity3d.player.UnityPlayer")) throw new IllegalStateException();
        Method display = player.getClass().getMethod("displayChanged", int.class, Surface.class);
        Method focus = player.getClass().getMethod("windowFocusChanged", boolean.class);
        Method resume = player.getClass().getMethod("resume"), pause = player.getClass().getMethod("pause");
        return new Player() {
            public boolean display(Surface surface) throws Exception { return Boolean.TRUE.equals(display.invoke(player, 0, surface)); }
            public void focus(boolean value) throws Exception { focus.invoke(player, value); }
            public void resume() throws Exception { resume.invoke(player); }
            public void pause() throws Exception { pause.invoke(player); }
        };
    }

    /** Clock policy is executed on a host JVM in tests, not replaced by a model. */
    static final class ProgressGate {
        static final long TIMEOUT_MS = 5000;
        long lastTicks, lastHeartbeat, firstCapture, lastCaptures, lastCaptureProgress, renderingSince;
        boolean heartbeatVerified, captureVerified, wasRendering;
        void begin(long now, long ticks, long captures) {
            lastTicks = ticks; lastHeartbeat = now; firstCapture = captures; renderingSince = -1;
            lastCaptures = captures; lastCaptureProgress = now;
            heartbeatVerified = false; captureVerified = false;
            wasRendering = false;
        }
        boolean sample(long now, long ticks, long captures, boolean rendering, long drainedFrames) {
            if (ticks < lastTicks || captures < lastCaptures) return false;
            if (ticks > lastTicks) { lastTicks = ticks; lastHeartbeat = now; heartbeatVerified = true; }
            if (rendering && !wasRendering) {
                if (renderingSince >= 0) { firstCapture = lastCaptures; captureVerified = false; }
                renderingSince = now; lastCaptureProgress = now;
            }
            wasRendering = rendering;
            if (captures > lastCaptures) { lastCaptures = captures; lastCaptureProgress = now; }
            if (captures - firstCapture >= 2 && drainedFrames >= 2 && heartbeatVerified) captureVerified = true;
            if (now - lastHeartbeat >= TIMEOUT_MS) return false;
            if (rendering && captureVerified && now - lastCaptureProgress >= TIMEOUT_MS) return false;
            return !rendering || captureVerified || now - renderingSince < TIMEOUT_MS;
        }
    }
    private interface SurfaceReady { void ready(Surface surface); }
    private static final class Drain {
        final int width, height;
        final SurfaceReady ready;
        final Runnable failed;
        final HandlerThread thread = new HandlerThread("IdolyMp4Surface");
        Handler handler;
        volatile Surface surface;
        volatile long frames;
        EGLDisplay display = EGL14.EGL_NO_DISPLAY;
        EGLContext context = EGL14.EGL_NO_CONTEXT;
        EGLSurface pbuffer = EGL14.EGL_NO_SURFACE;
        SurfaceTexture texture;
        int textureId;
        boolean closed, initializedDisplay;
        Drain(int width, int height, SurfaceReady ready, Runnable failed) {
            this.width = width; this.height = height; this.ready = ready; this.failed = failed;
        }
        void start() { thread.start(); handler = new Handler(thread.getLooper()); handler.post(this::create); }
        void create() {
            try {
                display = EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY);
                int[] versions = new int[2];
                if (display == EGL14.EGL_NO_DISPLAY || !EGL14.eglInitialize(display, versions, 0, versions, 1)) throw new IllegalStateException();
                initializedDisplay = true;
                int[] attrs = {EGL14.EGL_SURFACE_TYPE, EGL14.EGL_PBUFFER_BIT, EGL14.EGL_RENDERABLE_TYPE,
                    EGL14.EGL_OPENGL_ES2_BIT, EGL14.EGL_RED_SIZE, 8, EGL14.EGL_GREEN_SIZE, 8, EGL14.EGL_BLUE_SIZE, 8, EGL14.EGL_NONE};
                EGLConfig[] configs = new EGLConfig[1]; int[] count = new int[1];
                if (!EGL14.eglChooseConfig(display, attrs, 0, configs, 0, 1, count, 0) || count[0] != 1) throw new IllegalStateException();
                context = EGL14.eglCreateContext(display, configs[0], EGL14.EGL_NO_CONTEXT,
                    new int[] {EGL14.EGL_CONTEXT_CLIENT_VERSION, 2, EGL14.EGL_NONE}, 0);
                pbuffer = EGL14.eglCreatePbufferSurface(display, configs[0],
                    new int[] {EGL14.EGL_WIDTH, 1, EGL14.EGL_HEIGHT, 1, EGL14.EGL_NONE}, 0);
                if (context == EGL14.EGL_NO_CONTEXT || pbuffer == EGL14.EGL_NO_SURFACE
                        || !EGL14.eglMakeCurrent(display, pbuffer, pbuffer, context)) throw new IllegalStateException();
                int[] names = new int[1]; GLES20.glGenTextures(1, names, 0); textureId = names[0];
                if (textureId == 0) throw new IllegalStateException();
                int[] maxTexture = new int[1], viewport = new int[2];
                GLES20.glGetIntegerv(GLES20.GL_MAX_TEXTURE_SIZE, maxTexture, 0);
                GLES20.glGetIntegerv(GLES20.GL_MAX_VIEWPORT_DIMS, viewport, 0);
                if (width > maxTexture[0] || height > maxTexture[0] || width > viewport[0] || height > viewport[1]) throw new IllegalStateException();
                GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, textureId);
                GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_LINEAR);
                GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_LINEAR);
                GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_CLAMP_TO_EDGE);
                GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_CLAMP_TO_EDGE);
                if (GLES20.glGetError() != GLES20.GL_NO_ERROR) throw new IllegalStateException();
                texture = new SurfaceTexture(textureId);
                texture.setDefaultBufferSize(width, height);
                texture.setOnFrameAvailableListener(value -> {
                    if (closed) return;
                    try { value.updateTexImage(); frames++; }
                    catch (RuntimeException failure) { MAIN.post(failed); }
                }, handler);
                surface = new Surface(texture); MAIN.post(() -> ready.ready(surface));
            } catch (RuntimeException | LinkageError unavailable) { release(); MAIN.post(failed); }
        }
        void close() { if (handler != null) handler.post(this::release); }
        void release() {
            if (closed) return; closed = true;
            if (surface != null) { surface.release(); surface = null; }
            if (texture != null) { texture.setOnFrameAvailableListener(null); texture.release(); texture = null; }
            if (textureId != 0 && context != EGL14.EGL_NO_CONTEXT) GLES20.glDeleteTextures(1, new int[] {textureId}, 0);
            // Android ref-counts display initialization, including the process's
            // shared default display. Balance only this helper's successful
            // initialize; eglGetDisplay or a failed initialize owns no reference.
            boolean ownedDisplayReference = initializedDisplay; initializedDisplay = false;
            if (ownedDisplayReference && display != EGL14.EGL_NO_DISPLAY) {
                EGL14.eglMakeCurrent(display, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_CONTEXT);
                if (pbuffer != EGL14.EGL_NO_SURFACE) EGL14.eglDestroySurface(display, pbuffer);
                if (context != EGL14.EGL_NO_CONTEXT) EGL14.eglDestroyContext(display, context);
                EGL14.eglReleaseThread(); EGL14.eglTerminate(display);
            }
            thread.quitSafely();
        }
    }
}
