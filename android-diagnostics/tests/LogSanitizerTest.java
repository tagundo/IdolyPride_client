import game.qualiarts.idolypride.diagnostics.LogSanitizer;
import java.util.List;

/** Pure Java harness: javac --release 8 -d <tmp> <sanitizer> <this>; java -cp <tmp> LogSanitizerTest. */
public final class LogSanitizerTest {
    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    public static void main(String[] args) {
        LogSanitizer log = new LogSanitizer();
        log.accept("E/Unity   ( 1234): NullReferenceException: token=PRIVATE https://example.invalid/secret");
        log.accept("E/Unity   ( 1234):   at Solis.OutGame.HomeTop.SetHomeEnterData (String token=PRIVATE) [0x0123] in /private/profile:3");
        log.accept("E/Unity   ( 1234): Solis.OutGame.HomeTop+<OnEnterAsync>d__143.MoveNext () (at /private/profile:0)");
        log.accept("E/Unity   ( 1234): Cysharp.Threading.Tasks.UniTask`1+Awaiter[PRIVATE].GetResult ()");
        log.accept("E/Unity   ( 1234):   at https://example.invalid/secret (PRIVATE)");
        log.accept("E/Unity   ( 1234): token=PRIVATE");
        List<LogSanitizer.Event> events = log.drain();
        check(events.size() == 1, "one grouped exception");
        LogSanitizer.Event event = events.get(0);
        check("exception".equals(event.kind), "exception kind");
        check("NullReferenceException".equals(event.type) && event.code == null, "only exception type");
        check(event.frames.size() == 3, "only managed frames");
        check("Solis.OutGame.HomeTop.SetHomeEnterData".equals(event.frames.get(0)), "strip arguments and paths");
        check("Solis.OutGame.HomeTop+<OnEnterAsync>d__143.MoveNext".equals(event.frames.get(1)), "state machine frame");
        check("Cysharp.Threading.Tasks.UniTask`1+Awaiter.GetResult".equals(event.frames.get(2)), "strip generic arguments");
        check(!event.frames.toString().contains("PRIVATE"), "no secret text");
        check(log.drain().isEmpty(), "drain consumes events");

        log.accept("System.AggregateException: PRIVATE");
        log.accept(" ---> Custom.Runtime+TransportError: PRIVATE");
        events = log.drain();
        check(events.size() == 2, "inner exceptions retained");
        check("System.AggregateException".equals(events.get(0).type), "namespace retained");
        check("Custom.Runtime+TransportError".equals(events.get(1).type), "nested Error type retained");

        for (int i = 0; i < 100; i++) log.accept("E/Unity (1): ShaderWarmUpが終わっていないので待機する");
        events = log.drain();
        check(events.size() == 1 && "shader_warmup_wait".equals(events.get(0).code), "status deduplicated");
        check(events.get(0).type == null && events.get(0).frames.isEmpty(), "fixed status only");
        log.accept("[logger PRIVATE] ShaderWarmUpが終わっていないので待機する PRIVATE");
        events = log.drain();
        check(events.size() == 1 && "shader_warmup_wait".equals(events.get(0).code), "recognize shader literal inside logger prefix");
        check(events.get(0).type == null && events.get(0).frames.isEmpty(), "shader message never copied");

        String[] phases = {"home_enter", "environment_begin", "background_begin", "background_load_returned",
                "shader_completion_flag", "shader_wait_begin", "home_open_begin", "loading_hide", "front_loading_finished",
                "home_show_in_returned", "actors_begin", "actor_motion_wait", "actor_cache_build", "actor_result_received",
                "actor_cache_wait", "buttons_begin", "probe_ready", "probe_unavailable",
                "probe_init_failed", "probe_selftest_failed", "probe_profile_mismatch", "probe_install_failed"};
        for (String phase : phases) log.accept("I/Unity (1234): IDOLY_PHASE:" + phase);
        events = log.drain();
        check(events.size() == phases.length, "all audited phase codes accepted");
        for (int i = 0; i < phases.length; i++) {
            check("status".equals(events.get(i).kind) && phases[i].equals(events.get(i).code), "fixed phase code only");
            check(events.get(i).type == null && events.get(i).frames.isEmpty(), "phase has no copied log text");
        }
        for (String line : new String[]{"IDOLY_PHASE:home_enter PRIVATE", "PRIVATE IDOLY_PHASE:home_enter",
                "IDOLY_PHASE:unknown", "IDOLY_PHASE:shader_ready", "IDOLY_PHASE:actor_ready",
                "IDOLY_PHASE:https://example.invalid/PRIVATE", "IDOLY_PHASE:home_enter\nPRIVATE"}) log.accept(line);
        check(log.drain().isEmpty(), "reject arbitrary, unknown, legacy and multiline phase payloads");

        log.accept("E/Unity(123): [ActorManager] 想定外の状況によりActorロード失敗 PRIVATE https://example.invalid/secret");
        events = log.drain();
        check(events.size() == 1 && "actor_load_failed".equals(events.get(0).code)
                && events.get(0).frames.isEmpty(), "fixed actor failure contains no message or address");

        log.accept("NullReferenceException: PRIVATE");
        for (int i = 0; i < 30; i++) log.accept(" at Solis.Home.Method" + i + " (PRIVATE)");
        check(log.drain().get(0).frames.size() == 16, "frame cap");
        for (int i = 0; i < 100; i++) log.accept("Custom.Exception" + i + "Exception: PRIVATE");
        check(log.drain().size() == 64, "pending event cap");

        log.accept("https://example.invalid/NullReferenceException: PRIVATE");
        log.accept("PRIVATE NullReferenceException: message");
        log.accept("NullReferenceException:\nPRIVATE");
        log.accept(repeat('X', 4097) + "Exception: PRIVATE");
        log.accept(repeat('X', 129) + "Exception: PRIVATE");
        check(log.drain().isEmpty(), "reject non-type, multiline and oversize lines");
        log.accept("Exception: PRIVATE");
        log.accept(" at Solis.Home." + repeat('X', 200) + " (PRIVATE)");
        log.accept(" at Solis.Home.Method[PRIVATE (PRIVATE)");
        events = log.drain();
        check(events.size() == 1 && events.get(0).frames.isEmpty(), "base Exception and invalid frames");
        try {
            events.get(0).frames.add("PRIVATE");
            throw new AssertionError("frames must be immutable");
        } catch (UnsupportedOperationException expected) {
            // Immutable output owns no mutable parser buffers.
        }
        System.out.println("LogSanitizerTest passed");
    }

    private static String repeat(char character, int length) {
        StringBuilder value = new StringBuilder();
        for (int i = 0; i < length; i++) value.append(character);
        return value.toString();
    }
}
