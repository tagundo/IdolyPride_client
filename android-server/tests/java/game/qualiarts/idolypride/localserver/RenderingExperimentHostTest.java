package game.qualiarts.idolypride.localserver;

/** Pure policy checks: no Android runtime, launch, settings changes, or measured device. */
final class RenderingExperimentHostTest {
    private static int checks;
    private static void check(boolean condition) {
        checks++;
        if (!condition) throw new AssertionError("Rendering experiment check " + checks);
    }
    private static void reject(String arguments) {
        try {
            RenderingExperiment.launchArguments(arguments, true);
            throw new AssertionError("Expected rejection");
        } catch (IllegalArgumentException expected) { checks++; }
    }
    private static int feedback(String state, Boolean stale, Double receiptAge, Long nativeAge,
            int mode, long observations, boolean valid) {
        return RenderingExperiment.feedback(true, true, 2000, 1000, 1, state, stale,
                receiptAge, nativeAge, mode, observations, valid);
    }
    public static void main(String[] args) {
        check(!RenderingExperiment.DEFAULT_ENABLED);
        check(RenderingExperiment.launchArguments(null, false) == null);
        String preserved = "-force-vulkan -screen-width 1280 -logFile \"/some path/game.log\"";
        check(RenderingExperiment.launchArguments(preserved, false) == preserved);
        check(RenderingExperiment.launchArguments(null, true).equals("-force-gfx-mt"));
        check(RenderingExperiment.launchArguments("", true).equals("-force-gfx-mt"));
        check(RenderingExperiment.launchArguments("   ", true).equals("-force-gfx-mt"));
        check(RenderingExperiment.launchArguments(preserved, true).equals(preserved + " -force-gfx-mt"));
        String existingMt = "-force-vulkan -force-gfx-mt";
        check(RenderingExperiment.launchArguments(existingMt, true) == existingMt);
        check(RenderingExperiment.launchArguments("'-force-gfx-mt' -screen-height 720", true)
                .equals("'-force-gfx-mt' -screen-height 720"));
        for (String conflicting : new String[]{"-force-gfx-direct", "-force-gfx-st", "-force-gfx-jobs",
                "-force-vulkan \"-force-gfx-direct\"", "'-force-gfx-st' -screen-height 720"}) reject(conflicting);
        for (String malformed : new String[]{"-logFile \"unclosed", "unclosed'", "dangling\\", "line\nfeed",
                "\t", "nul\0value", "a".repeat(1025), " ".repeat(1025)}) reject(malformed);
        // An unchecked experiment never sanitizes or rewrites an original launch.
        check(RenderingExperiment.launchArguments("-force-gfx-st", false).equals("-force-gfx-st"));
        check(RenderingExperiment.knownClient("game.qualiarts.idolypride.local"));
        check(RenderingExperiment.knownClient("game.qualiarts.idolypride.local.resources"));
        check(RenderingExperiment.knownClient("game.qualiarts.idolypride.local.diagnostics"));
        check(!RenderingExperiment.knownClient("game.qualiarts.idolypride"));
        check(!RenderingExperiment.knownClient("game.qualiarts.idolypride.local.other"));

        for (int mode = 0; mode <= 5; mode++) {
            check(feedback("observed", false, 0.2, 0L, mode, 1, true) == RenderingExperiment.OBSERVED);
        }
        // A request flag is deliberately not an input to actual-mode feedback.
        check(feedback("observed", false, 0.2, 0L, -1, 1, true) == RenderingExperiment.WAIT_CLIENT);
        check(feedback("observed", false, 0.2, 0L, 6, 1, true) == RenderingExperiment.WAIT_CLIENT);
        check(feedback("observed", false, 0.2, 0L, 2, 0, true) == RenderingExperiment.WAIT_CLIENT);
        check(feedback("observed", false, 0.2, 0L, 2, 1, false) == RenderingExperiment.WAIT_CLIENT);
        check(feedback("waiting", false, 0.2, null, -1, 0, false) == RenderingExperiment.WAIT_CLIENT);
        check(feedback("observed", true, 0.2, 0L, 2, 1, true) == RenderingExperiment.STALE);
        check(feedback("observed", false, 0.2, 8800L, 2, 1, true) == RenderingExperiment.STALE);
        check(feedback("observed", false, 0.2, null, 2, 1, true) == RenderingExperiment.STALE);
        check(feedback("observed", false, 9.0, 0L, 2, 1, true) == RenderingExperiment.STALE);
        check(feedback("observed", false, Double.NaN, 0L, 2, 1, true) == RenderingExperiment.WAIT_CLIENT);
        check(feedback("observed", null, 0.2, 0L, 2, 1, true) == RenderingExperiment.WAIT_CLIENT);
        check(feedback("unsupported", true, 0.2, null, -1, 1, false) == RenderingExperiment.UNSUPPORTED);
        check(feedback("init_failed", true, 0.2, null, -1, 0, false) == RenderingExperiment.INIT_FAILED);
        check(RenderingExperiment.feedback(false, true, 2000, 1000, 1, "observed", false,
                0.2, 0L, 2, 1, true) == RenderingExperiment.WAIT_SERVER);
        check(RenderingExperiment.feedback(true, false, 2000, 1000, 1, "observed", false,
                0.2, 0L, 2, 1, true) == RenderingExperiment.WAIT_SERVER);
        check(RenderingExperiment.feedback(true, true, 12000, 1000, 1, "observed", false,
                0.2, 0L, 2, 1, true) == RenderingExperiment.WAIT_SERVER);
        check(RenderingExperiment.feedback(true, true, 2000, 3000, 1, "observed", false,
                0.2, 0L, 2, 1, true) == RenderingExperiment.WAIT_SERVER);
        check(RenderingExperiment.timingFresh(8000L, 0.5, 2000, 1000));
        check(!RenderingExperiment.timingFresh(8500L, 0.5, 2000, 1000));
        check(!RenderingExperiment.timingFresh(null, 0.5, 2000, 1000));
        check(!RenderingExperiment.timingFresh(Long.MAX_VALUE, 0.5, 2000, 1000));
        check(!RenderingExperiment.timingFresh(0L, Double.POSITIVE_INFINITY, 2000, 1000));
        System.out.println("PASS: " + checks + " rendering experiment launch and observation checks");
    }
}
