package game.qualiarts.idolypride.presentation;

import android.app.Application;
import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.net.Uri;

/** Starts only an account-free loopback poller in the supported game's main process. */
public final class PresentationProvider extends ContentProvider {
    @Override public boolean onCreate() {
        final String name = getContext().getPackageName();
        if (!(name.equals("game.qualiarts.idolypride.local.diagnostics")
                || name.equals("game.qualiarts.idolypride.local.resources"))
                || !name.equals(Application.getProcessName())) return false;
        try { if (getContext().getPackageManager().getPackageInfo(name, 0).getLongVersionCode() != 414) return false; }
        catch (Exception ignored) { return false; }
        Thread worker = new Thread(new Runnable() { @Override public void run() { poll(); } }, "IdolyPresentation");
        worker.setDaemon(true); worker.start(); return true;
    }
    private static void poll() {
        boolean loaded = false;
        PresentationClient client = new PresentationClient();
        while (!Thread.currentThread().isInterrupted()) {
            long nextPoll = System.nanoTime() + 2000000000L;
            try {
                if (!loaded) { System.loadLibrary("idoly_presentation"); NativePresentation.start(); loaded = true; }
                PresentationClient.Config config = client.fetch();
                // configure acknowledges only publication. The POST revision is
                // always the native Unity-thread acknowledgement, never this request.
                NativePresentation.configure(1, config.revision, config.custom, config.quality, config.fps,
                        config.scale, config.maxBufferPixel, config.aa, config.shadow, config.expand);
                client.postStatus(NativePresentation.status());
            } catch (Exception ignored) { /* Optional feature: leave the game running. */ }
              catch (LinkageError ignored) {
                  loaded = false;
                  client.reportStartupFailure();
              }
            long delay = nextPoll - System.nanoTime();
            try { if (delay > 0) Thread.sleep(delay / 1000000L, (int) (delay % 1000000L)); }
            catch (InterruptedException stopped) { Thread.currentThread().interrupt(); return; }
        }
    }
    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] arguments, String sort) { return null; }
    @Override public String getType(Uri uri) { return null; }
    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException(); }
    @Override public int delete(Uri uri, String selection, String[] arguments) { throw new UnsupportedOperationException(); }
    @Override public int update(Uri uri, ContentValues values, String selection, String[] arguments) { throw new UnsupportedOperationException(); }
}
