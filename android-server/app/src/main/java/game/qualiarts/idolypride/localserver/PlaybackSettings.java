package game.qualiarts.idolypride.localserver;

/** Independent rotation preferences; never extends the graphics JSON schema. */
final class PlaybackSettings {
    static final int MAX_BYTES = 8192;
    static final int WAIT_SERVER = 0, WAIT_CLIENT = 1, PENDING = 2, APPLIED = 3, UNSUPPORTED = 4;
    final long revision;
    final boolean waitForOrientation;

    PlaybackSettings(long revision, boolean waitForOrientation) {
        if (revision < 0) throw new IllegalArgumentException("Negative playback revision");
        this.revision = revision;
        this.waitForOrientation = waitForOrientation;
    }

    static PlaybackSettings defaults() { return new PlaybackSettings(0, true); }

    PlaybackSettings changed(boolean wait) {
        if (wait == waitForOrientation) return this;
        if (revision == Long.MAX_VALUE) throw new IllegalStateException("Playback revision exhausted");
        return new PlaybackSettings(revision + 1, wait);
    }

    String json() {
        return "{\"schema\":1,\"revision\":" + revision
                + ",\"wait_for_orientation\":" + waitForOrientation + "}";
    }

    /** Parse exactly three typed keys, rejecting duplicates and trailing input. */
    static PlaybackSettings parse(String raw) {
        if (raw == null || raw.length() > MAX_BYTES) throw new IllegalArgumentException("Playback size");
        Reader reader = new Reader(raw);
        reader.expect('{');
        boolean schema = false, revision = false, wait = false;
        long number = 0;
        boolean enabled = true;
        for (int count = 0; count < 3; count++) {
            if (count != 0) reader.expect(',');
            String key = reader.string();
            reader.expect(':');
            if ("schema".equals(key) && !schema) {
                schema = true;
                if (reader.integer() != 1) throw new IllegalArgumentException("Playback schema");
            } else if ("revision".equals(key) && !revision) {
                revision = true; number = reader.integer();
            } else if ("wait_for_orientation".equals(key) && !wait) {
                wait = true; enabled = reader.bool();
            } else throw new IllegalArgumentException("Unknown or duplicate playback key");
        }
        reader.expect('}');
        reader.space();
        if (!schema || !revision || !wait || reader.at != raw.length()) {
            throw new IllegalArgumentException("Playback fields");
        }
        return new PlaybackSettings(number, enabled);
    }

    static int feedback(boolean observed, boolean running, boolean fresh, PlaybackSettings saved,
            int schema, int bridgeVersion, long revision, Boolean wait, Boolean supported, Boolean applied) {
        if (!observed || !running || !fresh) return WAIT_SERVER;
        if (schema != 1 || bridgeVersion != 1 || revision < 0 || wait == null
                || supported == null || applied == null) return WAIT_CLIENT;
        if (!supported) return UNSUPPORTED;
        return revision == saved.revision && wait == saved.waitForOrientation && applied ? APPLIED : PENDING;
    }

    static boolean fresh(long now, long received) {
        return received > 0 && now >= received && now - received <= 10_000;
    }

    private static final class Reader {
        final String raw;
        int at;
        Reader(String raw) { this.raw = raw; }
        void space() {
            while (at < raw.length() && (raw.charAt(at) == ' ' || raw.charAt(at) == '\n'
                    || raw.charAt(at) == '\r' || raw.charAt(at) == '\t')) at++;
        }
        void expect(char character) {
            space();
            if (at == raw.length() || raw.charAt(at++) != character) {
                throw new IllegalArgumentException("Playback JSON token");
            }
        }
        String string() {
            expect('"');
            StringBuilder value = new StringBuilder();
            while (at < raw.length()) {
                char c = raw.charAt(at++);
                if (c == '"') return value.toString();
                if (c < 32) throw new IllegalArgumentException("Playback JSON string");
                if (c == '\\') {
                    if (at == raw.length()) throw new IllegalArgumentException("Playback JSON escape");
                    c = raw.charAt(at++);
                    switch (c) {
                        case '"': case '\\': case '/': break;
                        case 'b': c = '\b'; break;
                        case 'f': c = '\f'; break;
                        case 'n': c = '\n'; break;
                        case 'r': c = '\r'; break;
                        case 't': c = '\t'; break;
                        case 'u':
                            if (at + 4 > raw.length()) throw new IllegalArgumentException("Playback Unicode");
                            int code = 0;
                            for (int i = 0; i < 4; i++) {
                                char h = raw.charAt(at++);
                                int digit = h >= '0' && h <= '9' ? h - '0'
                                        : h >= 'a' && h <= 'f' ? h - 'a' + 10
                                        : h >= 'A' && h <= 'F' ? h - 'A' + 10 : -1;
                                if (digit < 0) throw new IllegalArgumentException("Playback Unicode");
                                code = code * 16 + digit;
                            }
                            c = (char) code; break;
                        default: throw new IllegalArgumentException("Playback JSON escape");
                    }
                }
                value.append(c);
            }
            throw new IllegalArgumentException("Unterminated playback key");
        }
        long integer() {
            space();
            int start = at;
            while (at < raw.length() && raw.charAt(at) >= '0' && raw.charAt(at) <= '9') at++;
            if (start == at || (at > start + 1 && raw.charAt(start) == '0')) {
                throw new IllegalArgumentException("Playback integer");
            }
            try { return Long.parseLong(raw.substring(start, at)); }
            catch (NumberFormatException error) { throw new IllegalArgumentException("Playback integer", error); }
        }
        boolean bool() {
            space();
            if (raw.startsWith("true", at)) { at += 4; return true; }
            if (raw.startsWith("false", at)) { at += 5; return false; }
            throw new IllegalArgumentException("Playback boolean");
        }
    }
}
