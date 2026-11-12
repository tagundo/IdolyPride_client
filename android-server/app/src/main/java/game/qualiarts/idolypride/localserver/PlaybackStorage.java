package game.qualiarts.idolypride.localserver;

import android.util.AtomicFile;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

/** App-private, atomic rotation preference storage beside graphics preferences. */
final class PlaybackStorage {
    static File path(File filesDirectory) {
        return new File(new File(filesDirectory, "data"), "client-playback.json");
    }

    static final class Loaded {
        final PlaybackSettings settings;
        final boolean invalid;
        Loaded(PlaybackSettings settings, boolean invalid) { this.settings = settings; this.invalid = invalid; }
    }

    static Loaded load(File filesDirectory) {
        AtomicFile source = new AtomicFile(path(filesDirectory));
        if (!source.getBaseFile().exists()
                && !new File(source.getBaseFile().getPath() + ".bak").exists()) {
            return new Loaded(PlaybackSettings.defaults(), false);
        }
        try (FileInputStream input = source.openRead();
                ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[1024];
            int count;
            while ((count = input.read(buffer)) != -1) {
                if (output.size() + count > PlaybackSettings.MAX_BYTES) throw new IOException("Playback size");
                output.write(buffer, 0, count);
            }
            return new Loaded(PlaybackSettings.parse(output.toString(StandardCharsets.UTF_8.name())), false);
        } catch (IOException | IllegalArgumentException error) {
            // Preserve damaged input until the user explicitly changes this option.
            return new Loaded(PlaybackSettings.defaults(), true);
        }
    }

    static void save(File filesDirectory, PlaybackSettings value) throws IOException {
        File destination = path(filesDirectory);
        File directory = destination.getParentFile();
        if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("Playback directory");
        AtomicFile target = new AtomicFile(destination);
        FileOutputStream output = null;
        try {
            output = target.startWrite();
            output.write(value.json().getBytes(StandardCharsets.UTF_8));
            target.finishWrite(output);
        } catch (IOException error) {
            if (output != null) target.failWrite(output);
            throw error;
        }
    }
}
