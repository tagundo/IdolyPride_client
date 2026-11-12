package game.qualiarts.idolypride.localserver;

/** Actual settings parser/revision/ACK policy, without Android or game execution. */
public final class PlaybackSettingsHostTest {
    private static int checks;
    private static void check(boolean condition) {
        checks++;
        if (!condition) throw new AssertionError("Playback check " + checks);
    }
    private static void reject(String text) {
        try { PlaybackSettings.parse(text); throw new AssertionError("Accepted invalid playback JSON"); }
        catch (IllegalArgumentException expected) { checks++; }
    }
    private static int feedback(PlaybackSettings saved, long revision, Boolean wait, Boolean supported, Boolean applied) {
        return PlaybackSettings.feedback(true, true, true, saved, 1, 1, revision, wait, supported, applied);
    }
    public static void main(String[] args) {
        PlaybackSettings initial = PlaybackSettings.defaults();
        check(initial.revision == 0 && initial.waitForOrientation);
        check(initial.changed(true) == initial);
        PlaybackSettings off = initial.changed(false);
        check(off.revision == 1 && !off.waitForOrientation);
        check(off.changed(false) == off);
        PlaybackSettings again = off.changed(true);
        check(again.revision == 2 && again.waitForOrientation);
        PlaybackSettings parsed = PlaybackSettings.parse(again.json());
        check(parsed.revision == again.revision && parsed.waitForOrientation);
        parsed = PlaybackSettings.parse(" \n{\"wait_for_orientation\": false,\"revision\":9223372036854775807,\"schema\":1}\t");
        check(parsed.revision == Long.MAX_VALUE && !parsed.waitForOrientation);
        check(parsed.changed(false) == parsed);
        try { parsed.changed(true); throw new AssertionError("Overflowed playback revision"); }
        catch (IllegalStateException expected) { checks++; }
        parsed = PlaybackSettings.parse("{\"\\u0073chema\":1,\"revision\":3,\"wait_for_orientation\":true}");
        check(parsed.revision == 3 && parsed.waitForOrientation);
        for (String bad : new String[]{
                "", "{}", "[]", "null", "{\"schema\":1}",
                "{\"schema\":1,\"schema\":1,\"wait_for_orientation\":true}",
                "{\"schema\":1,\"\\u0073chema\":1,\"wait_for_orientation\":true}",
                "{\"schema\":1,\"revision\":0,\"wait_for_orientation\":true,\"extra\":false}",
                "{\"schema\":2,\"revision\":0,\"wait_for_orientation\":true}",
                "{\"schema\":true,\"revision\":0,\"wait_for_orientation\":true}",
                "{\"schema\":1.0,\"revision\":0,\"wait_for_orientation\":true}",
                "{\"schema\":1,\"revision\":-1,\"wait_for_orientation\":true}",
                "{\"schema\":1,\"revision\":-0,\"wait_for_orientation\":true}",
                "{\"schema\":1,\"revision\":01,\"wait_for_orientation\":true}",
                "{\"schema\":1,\"revision\":1e3,\"wait_for_orientation\":true}",
                "{\"schema\":1,\"revision\":true,\"wait_for_orientation\":true}",
                "{\"schema\":1,\"revision\":\"0\",\"wait_for_orientation\":true}",
                "{\"schema\":1,\"revision\":9223372036854775808,\"wait_for_orientation\":true}",
                "{\"schema\":1,\"revision\":0,\"wait_for_orientation\":\"true\"}",
                "{\"schema\":1,\"revision\":0,\"wait_for_orientation\":1}",
                "{\"schema\":1,\"revision\":0,\"wait_for_orientation\":null}",
                "{\"schema\":1,\"revision\":0,\"wait_for_orientation\":true,}",
                "{\"schema\":1,\"revision\":0,\"wait_for_orientation\":true}x",
                "{\"schema\":1,\"revision\":0,\"wait_for_orientation\":true}{}",
                "{\"\\u００７3chema\":1,\"revision\":0,\"wait_for_orientation\":true}",
                "{\"schema\":1,\"revision\":0,\"wait_for_orientation\":true/*comment*/}"}) reject(bad);
        reject(null);
        reject(" ".repeat(PlaybackSettings.MAX_BYTES + 1));
        check(feedback(off, 1, false, true, true) == PlaybackSettings.APPLIED);
        check(feedback(off, 1, true, true, true) == PlaybackSettings.PENDING);
        check(feedback(off, 0, false, true, true) == PlaybackSettings.PENDING);
        check(feedback(off, 2, false, true, true) == PlaybackSettings.PENDING);
        check(feedback(off, 1, false, true, false) == PlaybackSettings.PENDING);
        check(feedback(off, 1, false, false, true) == PlaybackSettings.UNSUPPORTED);
        check(feedback(off, 1, null, true, true) == PlaybackSettings.WAIT_CLIENT);
        check(feedback(off, -1, false, true, true) == PlaybackSettings.WAIT_CLIENT);
        check(feedback(off, 1, false, null, true) == PlaybackSettings.WAIT_CLIENT);
        check(feedback(off, 1, false, true, null) == PlaybackSettings.WAIT_CLIENT);
        check(PlaybackSettings.feedback(false, true, true, off, 1, 1, 1, false, true, true) == PlaybackSettings.WAIT_SERVER);
        check(PlaybackSettings.feedback(true, false, true, off, 1, 1, 1, false, true, true) == PlaybackSettings.WAIT_SERVER);
        check(PlaybackSettings.feedback(true, true, false, off, 1, 1, 1, false, true, true) == PlaybackSettings.WAIT_SERVER);
        check(PlaybackSettings.feedback(true, true, true, off, 2, 1, 1, false, true, true) == PlaybackSettings.WAIT_CLIENT);
        check(PlaybackSettings.feedback(true, true, true, off, 1, 2, 1, false, true, true) == PlaybackSettings.WAIT_CLIENT);
        check(!PlaybackSettings.fresh(10_000, 0));
        check(PlaybackSettings.fresh(10_001, 1));
        check(!PlaybackSettings.fresh(10_002, 1));
        check(!PlaybackSettings.fresh(99, 100));
        System.out.println("PASS: " + checks + " playback settings and acknowledgement checks");
    }
}
