package game.qualiarts.idolypride.localserver;

import java.nio.charset.StandardCharsets;
import java.util.Iterator;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONObject;

/** Public display text only. Queue identity always remains the native job ID. */
final class Mp4TitleCatalog {
    private static final String[] LANGUAGES = {"ja", "ko", "en"};
    private final JSONObject catalog;

    private Mp4TitleCatalog(JSONObject catalog) { this.catalog = catalog; }

    static Mp4TitleCatalog empty() { return new Mp4TitleCatalog(new JSONObject()); }

    static Mp4TitleCatalog parse(JSONObject source) {
        if (source == null || source.length() != 3
                || source.toString().getBytes(StandardCharsets.UTF_8).length > 48 * 1024) return empty();
        JSONObject accepted = new JSONObject();
        try {
            for (String language : LANGUAGES) {
                JSONObject rows = source.optJSONObject(language);
                if (rows == null || rows.length() > 512) return empty();
                JSONObject titles = new JSONObject();
                Iterator<String> keys = rows.keys();
                while (keys.hasNext()) {
                    String timeline = keys.next(); Object value = rows.opt(timeline);
                    if (!timeline.matches("tln_live_[A-Za-z0-9_.-]{1,183}") || !(value instanceof String)
                            || !validTitle((String) value)) return empty();
                    titles.put(timeline, value);
                }
                accepted.put(language, titles);
            }
            return new Mp4TitleCatalog(accepted);
        } catch (Exception invalid) { return empty(); }
    }

    private static boolean validTitle(String title) {
        if (title.isEmpty() || title.length() > 192 || title.getBytes(StandardCharsets.UTF_8).length > 768) return false;
        for (int at = 0; at < title.length(); at++) {
            char value = title.charAt(at);
            if (Character.isISOControl(value) || value == '\u2028' || value == '\u2029') return false;
            if (Character.isHighSurrogate(value)) {
                if (++at >= title.length() || !Character.isLowSurrogate(title.charAt(at))) return false;
            } else if (Character.isLowSurrogate(value)) return false;
        }
        return true;
    }

    JSONObject enrich(JSONObject snapshot) {
        try {
            JSONObject copy = new JSONObject(snapshot.toString()); JSONArray jobs = copy.optJSONArray("jobs");
            if (jobs == null) return copy;
            for (int index = 0; index < Math.min(8, jobs.length()); index++) {
                JSONObject job = jobs.optJSONObject(index); if (job == null) continue;
                JSONObject localized = new JSONObject(); String timeline = job.optString("timeline");
                for (String language : LANGUAGES) {
                    JSONObject rows = catalog.optJSONObject(language);
                    String title = rows == null ? "" : rows.optString(timeline);
                    if (!title.isEmpty()) localized.put(language, title);
                }
                job.put("title_localizations", localized);
            }
            return copy;
        } catch (Exception invalid) { return new JSONObject(); }
    }

    static String title(JSONObject job, Locale locale) {
        JSONObject localized = job == null ? null : job.optJSONObject("title_localizations");
        if (localized == null) return "";
        String language = locale == null ? "ko" : locale.getLanguage();
        if (!language.equals("ja") && !language.equals("en")) language = "ko";
        String title = localized.optString(language);
        if (validTitle(title)) return title;
        title = localized.optString("ja");
        return validTitle(title) ? title : "";
    }
}
