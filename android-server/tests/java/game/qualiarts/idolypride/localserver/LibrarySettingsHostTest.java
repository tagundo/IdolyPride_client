package game.qualiarts.idolypride.localserver;

public final class LibrarySettingsHostTest {
    private static int checks;
    private static void check(boolean condition) { checks++; if (!condition) throw new AssertionError("Library check " + checks); }
    private static void reject(String value, boolean language) {
        try { if (language) LibrarySettings.parseLanguage(value); else LibrarySettings.parseMedia(value); }
        catch (IllegalArgumentException expected) { checks++; return; }
        throw new AssertionError("Invalid library settings accepted");
    }
    public static void main(String[] args) {
        LibrarySettings initial = LibrarySettings.defaults();
        check(initial.language.equals("ja") && initial.mvSort.equals("recent") && initial.outfitSort.equals("original") && !initial.hideVideoMv && initial.revision == 0);
        for (String language : LibrarySettings.LANGUAGES) check(LibrarySettings.parseLanguage(initial.changedLanguage(language).languageJson()).equals(language));
        LibrarySettings first = initial.changedMedia(true, "title", "recent", 100);
        LibrarySettings second = first.changedMedia(false, "old", "id", 100);
        LibrarySettings third = second.changedMedia(true, "id", "old", 1);
        check(first.revision == 100 && second.revision == 101 && third.revision == 102 && initial.revision == 0);
        LibrarySettings parsed = LibrarySettings.parseMedia(third.mediaJson());
        check(parsed.revision == 102 && parsed.hideVideoMv && parsed.mvSort.equals("id") && parsed.outfitSort.equals("old"));
        String media = initial.mediaJson(), language = initial.languageJson();
        for (String bad : new String[]{media.replace("\"schema\":1", "\"schema\":true"),
                media.replace("\"revision\":0", "\"revision\":1.0"), media.replace("\"revision\":0", "\"revision\":-1"),
                media.replace("\"revision\":0", "\"revision\":9223372036854775808"), media.replace("false", "0"),
                media.replace("\"recent\"", "\"original\""), media.replace("\"schema\":1", "\"schema\":1,\"schema\":1"),
                media.replace("\"schema\":1", "\"schema\":1,\"\\u0073chema\":1"), media + "{}", "{}", "[]", "null"}) reject(bad, false);
        for (String bad : new String[]{language.replace("ja", "zh"), language.replace("\"schema\":1", "\"schema\":1.0"),
                language.replace("\"schema\":1", "\"schema\":1,\"schema\":1"), language + "x", "{}"}) reject(bad, true);
        check(LibrarySettings.parseMedia(media.replace("\"schema\"", "\"\\u0073chema\"")).revision == 0);
        parsed = LibrarySettings.parseMedia(media.replace("\"revision\":0", "\"revision\":9223372036854775807"));
        try { parsed.changedMedia(true, "id", "id", 100); throw new AssertionError("Revision wrapped"); }
        catch (IllegalStateException expected) { checks++; }
        System.out.println("PASS: " + checks + " independent library JSON/revision checks");
    }
}
