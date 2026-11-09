package game.qualiarts.idolypride.diagnostics;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Converts game log lines into bounded events containing no free-form text. */
public final class LogSanitizer {
    private static final int MAX_LINE = 4096;
    private static final int MAX_TYPE = 128;
    private static final int MAX_FRAME = 192;
    private static final int MAX_FRAMES = 16;
    private static final int MAX_EVENTS = 64;
    private static final String SHADER_WAIT = "ShaderWarmUpが終わっていないので待機する";
    private static final String ACTOR_LOAD_FAILED = "想定外の状況によりActorロード失敗";
    private static final String PHASE_PREFIX = "IDOLY_PHASE:";
    private static final Set<String> PHASE_CODES = Collections.unmodifiableSet(new HashSet<String>(Arrays.asList(
            "home_enter", "environment_begin", "background_begin", "background_load_returned",
            "shader_completion_flag", "shader_wait_begin", "home_open_begin", "loading_hide", "front_loading_finished",
            "home_show_in_returned",
            "actors_begin", "actor_motion_wait", "actor_cache_build", "actor_result_received",
            "actor_cache_wait", "buttons_begin", "probe_ready", "probe_unavailable",
            "probe_init_failed", "probe_selftest_failed", "probe_profile_mismatch", "probe_install_failed")));
    private static final Pattern BRIEF = Pattern.compile(
            "^[VDIWEFAS]/[^\\r\\n:]{1,64}\\(\\s*[0-9]+\\): ?(.*)$");
    private static final Pattern TYPE_START = Pattern.compile(
            "^(?:--->\\s*)?([A-Za-z_][A-Za-z0-9_]*(?:[.+][A-Za-z_][A-Za-z0-9_]*)*)(?=\\s*(?::|$))");
    private static final Pattern FRAME = Pattern.compile(
            "[A-Za-z_<][A-Za-z0-9_`<>]*(?:[.+][A-Za-z_<][A-Za-z0-9_`<>]*)+");

    public static final class Event {
        public final String kind;
        public final String type;
        public final String code;
        public final List<String> frames;

        private Event(String kind, String type, String code, List<String> frames) {
            this.kind = kind;
            this.type = type;
            this.code = code;
            this.frames = Collections.unmodifiableList(new ArrayList<String>(frames));
        }
    }

    private final ArrayDeque<Event> pending = new ArrayDeque<Event>();
    private String exceptionType;
    private final ArrayList<String> exceptionFrames = new ArrayList<String>();
    private boolean shaderPending;

    /** Accepts one logcat or managed-log line. Arbitrary messages are discarded. */
    public synchronized void accept(String line) {
        if (line == null || line.length() > MAX_LINE
                || line.indexOf('\n') >= 0 || line.indexOf('\r') >= 0) {
            return;
        }
        Matcher brief = BRIEF.matcher(line);
        String content = (brief.matches() ? brief.group(1) : line).trim();
        if (content.startsWith(PHASE_PREFIX) && PHASE_CODES.contains(content.substring(PHASE_PREFIX.length()))) {
            flushException();
            enqueue(new Event("status", null, content.substring(PHASE_PREFIX.length()), Collections.<String>emptyList()));
            return;
        }
        if (content.contains(SHADER_WAIT)) {
            if (!shaderPending) {
                flushException();
                enqueue(new Event("status", null, "shader_warmup_wait", Collections.<String>emptyList()));
                shaderPending = true;
            }
            return;
        }
        if (content.contains(ACTOR_LOAD_FAILED)) {
            flushException();
            enqueue(new Event("status", null, "actor_load_failed", Collections.<String>emptyList()));
            return;
        }
        Matcher type = TYPE_START.matcher(content);
        if (type.find()) {
            String name = type.group(1);
            if (name.length() <= MAX_TYPE && (name.endsWith("Exception") || name.endsWith("Error"))) {
                flushException();
                exceptionType = name;
                return;
            }
        }
        if (exceptionType == null || exceptionFrames.size() >= MAX_FRAMES) {
            return;
        }
        String frame = frameName(content);
        if (frame != null) {
            exceptionFrames.add(frame);
        }
    }

    /** Flushes a pending exception and removes all currently available events. */
    public synchronized List<Event> drain() {
        flushException();
        ArrayList<Event> result = new ArrayList<Event>(pending);
        pending.clear();
        shaderPending = false;
        return result;
    }

    private static String frameName(String content) {
        if (content.startsWith("at ")) {
            content = content.substring(3).trim();
        }
        int arguments = content.indexOf('(');
        if (arguments <= 0) {
            return null;
        }
        String name = content.substring(0, arguments).trim();
        // Generic type/method arguments can contain runtime type names. Retain
        // only the static method path; never copy brackets, arguments or paths.
        StringBuilder stripped = new StringBuilder();
        int depth = 0;
        for (int i = 0; i < name.length(); i++) {
            char character = name.charAt(i);
            if (character == '[') {
                depth++;
            } else if (character == ']') {
                if (depth == 0) {
                    return null;
                }
                depth--;
            } else if (depth == 0) {
                stripped.append(character);
            }
        }
        if (depth != 0 || stripped.length() > MAX_FRAME) {
            return null;
        }
        String result = stripped.toString();
        return FRAME.matcher(result).matches() ? result : null;
    }

    private void flushException() {
        if (exceptionType != null) {
            enqueue(new Event("exception", exceptionType, null, exceptionFrames));
            exceptionType = null;
            exceptionFrames.clear();
        }
    }

    private void enqueue(Event event) {
        if (pending.size() == MAX_EVENTS) {
            Event removed = pending.removeFirst();
            if ("shader_warmup_wait".equals(removed.code)) {
                shaderPending = false;
            }
        }
        pending.addLast(event);
    }
}
