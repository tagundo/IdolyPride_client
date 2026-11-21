package game.qualiarts.idolypride.localserver;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Base64;

/** Last eight fixed document-launch/result facts. Never accepts a URI, path or extras. */
final class DocumentPickerHistory {
    interface Store { String read(); void write(String value); }
    static final class Event {
        final int request;
        final String event, action, mime, origin, result;
        Event(int request, String event, String action, String mime, String origin, String result) {
            this.request = request; this.event = event; this.action = action; this.mime = mime; this.origin = origin; this.result = result;
        }
    }
    private final Store store;
    private final ArrayList<Event> events = new ArrayList<>();
    DocumentPickerHistory(Store store) {
        this.store = store;
        try {
            String saved = store.read();
            if (saved == null || saved.isEmpty()) return;
            if (saved.length() > 8192) throw new IOException();
            try (DataInputStream input = new DataInputStream(new ByteArrayInputStream(Base64.getUrlDecoder().decode(saved)))) {
                if (input.readInt() != 1) throw new IOException();
                int count = input.readInt(); if (count < 0 || count > 8) throw new IOException();
                ArrayList<Event> restored = new ArrayList<>();
                for (int index = 0; index < count; index++) {
                    Event row = new Event(input.readInt(), input.readUTF(), input.readUTF(), input.readUTF(), input.readUTF(), input.readUTF());
                    if (!valid(row)) throw new IOException(); restored.add(row);
                }
                if (input.read() != -1) throw new IOException(); events.addAll(restored);
            }
        } catch (IOException | RuntimeException invalid) { events.clear(); }
    }
    synchronized void launch(int request, String action, String mime, String origin) {
        Event row = new Event(request, "launch", action, mime, origin, "requested");
        if (valid(row)) append(row);
    }
    synchronized void result(int request, String result) {
        if (request < 50052 || request > 50057 || !Arrays.asList("ok", "cancelled", "other", "unavailable").contains(result)) return;
        Event launch = null;
        for (int index = events.size() - 1; index >= 0; index--) {
            Event row = events.get(index);
            if (row.request == request && row.event.equals("launch")) { launch = row; break; }
        }
        append(new Event(request, "result", launch == null ? "unknown" : launch.action,
                launch == null ? "unknown" : launch.mime, launch == null ? "unknown" : launch.origin, result));
    }
    synchronized ArrayList<Event> snapshot() { return new ArrayList<>(events); }
    private void append(Event row) {
        events.add(row); while (events.size() > 8) events.remove(0);
        try {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            try (DataOutputStream output = new DataOutputStream(bytes)) {
                output.writeInt(1); output.writeInt(events.size());
                for (Event event : events) {
                    output.writeInt(event.request); output.writeUTF(event.event); output.writeUTF(event.action);
                    output.writeUTF(event.mime); output.writeUTF(event.origin); output.writeUTF(event.result);
                }
            }
            store.write(Base64.getUrlEncoder().withoutPadding().encodeToString(bytes.toByteArray()));
        } catch (IOException | RuntimeException unavailable) { /* Diagnostics never block or launch an Activity. */ }
    }
    private static boolean valid(Event row) {
        if (row.request < 50052 || row.request > 50057 || !Arrays.asList("launch", "result").contains(row.event)) return false;
        String origin = row.request == 50052 ? "diagnostics_export" : row.request == 50053 ? "resource_export"
                : row.request == 50054 ? "resource_import" : row.request == 50055 ? "account_export"
                : row.request == 50056 ? "account_import" : "mp4_save";
        String mime = row.request == 50052 ? "application/json" : row.request == 50057 ? "video/mp4" : "application/zip";
        String action = row.request == 50054 || row.request == 50056 ? "android.intent.action.OPEN_DOCUMENT" : "android.intent.action.CREATE_DOCUMENT";
        boolean known = origin.equals(row.origin) && mime.equals(row.mime) && action.equals(row.action);
        if (!known && !(row.event.equals("result") && "unknown".equals(row.action) && "unknown".equals(row.mime) && "unknown".equals(row.origin))) return false;
        return row.event.equals("launch") ? "requested".equals(row.result)
                : Arrays.asList("ok", "cancelled", "other", "unavailable").contains(row.result);
    }
}
