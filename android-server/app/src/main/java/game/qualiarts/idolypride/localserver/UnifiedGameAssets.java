package game.qualiarts.idolypride.localserver;

import android.content.Context;
import android.os.Looper;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** One selected, verified native Unity Data ZIP; no runtime native patching. */
public final class UnifiedGameAssets {
    private static final String INDEX = "idoly-unified/game-data.json";
    private static final String OBJECTS = "assets/idoly-unified/game-data/";
    private static final int MAX_INDEX = 8 * 1024 * 1024;
    private static final UnifiedGamePreparation PREPARATION = new UnifiedGamePreparation();
    private UnifiedGameAssets() {}

    private static void require(boolean value, String code) throws IOException { UnifiedGameZip.require(value, code); }
    private static boolean language(String value) { return "ko".equals(value) || "ja".equals(value) || "en".equals(value); }
    private static boolean hash(String value) { return value != null && value.matches("[0-9a-f]{64}"); }
    private static byte[] bounded(InputStream input, int maximum) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream(); byte[] buffer = new byte[8192]; int count;
        while ((count = input.read(buffer)) != -1) { require(out.size() + count <= maximum, "unified_data_index_bound"); out.write(buffer, 0, count); }
        return out.toByteArray();
    }
    private static long number(JSONObject row, String key) throws Exception {
        Object value = row.get(key); require(value instanceof Integer || value instanceof Long, "unified_data_number_invalid"); return ((Number) value).longValue();
    }
    private static String text(JSONObject row, String key) throws Exception {
        Object value = row.get(key); require(value instanceof String, "unified_data_string_invalid"); return (String) value;
    }
    private static JSONObject object(JSONObject row, String key) throws Exception {
        Object value = row.get(key); require(value instanceof JSONObject, "unified_data_object_invalid"); return (JSONObject) value;
    }
    private static File directory(Context context) throws Exception {
        File root = context.getCodeCacheDir().getCanonicalFile();
        File folder = new File(root, "idoly-unified-data");
        require(folder.isDirectory() || folder.mkdir(), "unified_data_directory_unavailable");
        StructStat status = Os.lstat(folder.getPath());
        require(OsConstants.S_ISDIR(status.st_mode) && !OsConstants.S_ISLNK(status.st_mode)
                && folder.getCanonicalFile().getParentFile().equals(root), "unified_data_directory_invalid");
        return folder;
    }
    private static boolean regular(File file) {
        try { StructStat status = Os.lstat(file.getPath()); return OsConstants.S_ISREG(status.st_mode) && !OsConstants.S_ISLNK(status.st_mode); }
        catch (Exception absent) { return false; }
    }

    /** Runs before Unity is initialized, on a worker. A failed replacement preserves the old verified ZIP. */
    public static File prepare(Context context, String selectedLanguage) throws IOException {
        require(Looper.myLooper() != Looper.getMainLooper(), "unified_data_prepare_requires_worker");
        synchronized (PREPARATION.workerLock) { return prepareOnWorker(context, selectedLanguage); }
    }

    private static File prepareOnWorker(Context context, String selectedLanguage) throws IOException {
        require(Looper.myLooper() != Looper.getMainLooper(), "unified_data_prepare_requires_worker");
        require(language(selectedLanguage), "unified_data_language_invalid");
        String frozenLanguage = PREPARATION.frozenLanguage();
        require(frozenLanguage == null || frozenLanguage.equals(selectedLanguage), "unified_data_cold_restart_required");
        File temporary = null;
        try {
            JSONObject marker = UnifiedRuntime.configuration(context);
            require(marker != null, "unified_data_marker_missing");
            JSONObject pack = object(marker, "data_pack");
            String identity = text(pack, "sha256"); long indexBytes = number(pack, "bytes");
            require(INDEX.equals(text(pack, "asset")) && hash(identity) && indexBytes > 0 && indexBytes <= MAX_INDEX,
                    "unified_data_pack_invalid");
            JSONArray advertised = marker.getJSONArray("languages"); boolean supported = false;
            for (int i = 0; i < advertised.length(); ++i) if (selectedLanguage.equals(advertised.get(i))) supported = true;
            require(supported, "unified_data_language_unavailable");
            byte[] raw;
            try (InputStream input = context.getAssets().open(INDEX)) { raw = bounded(input, MAX_INDEX); }
            require(raw.length == indexBytes && UnifiedGameZip.hex(UnifiedGameZip.digest().digest(raw)).equals(identity),
                    "unified_data_index_hash_differs");
            JSONObject index = new JSONObject(new String(raw, StandardCharsets.UTF_8));
            require(number(index, "schema") == 1 && "selected-data-zip-v1".equals(text(index, "strategy"))
                    && "ko".equals(text(index, "base_language")), "unified_data_index_invalid");
            JSONArray staticAssets = index.getJSONArray("static_assets"); Set<String> staticNames = new HashSet<>();
            for (int at = 0; at < staticAssets.length(); ++at) {
                Object value = staticAssets.get(at);
                require(value instanceof String && staticNames.add((String) value), "unified_data_static_assets_invalid");
            }
            require(staticNames.equals(UnifiedGameZip.STATIC_ASSETS), "unified_data_static_assets_invalid");
            JSONObject languages = object(index, "languages");
            require(languages.length() == 3 && languages.has("ko") && languages.has("ja") && languages.has("en"), "unified_data_languages_invalid");
            JSONObject data = object(languages, selectedLanguage), carrier = object(data, "carrier");
            long bytes = number(carrier, "bytes"); String digest = text(carrier, "sha256");
            require(bytes > 22 && bytes < UnifiedGameZip.MAX_BYTES && hash(digest), "unified_data_carrier_identity_invalid");
            JSONArray rows = data.getJSONArray("entries");
            require(rows.length() > 0 && rows.length() <= UnifiedGameZip.MAX_ENTRIES, "unified_data_entry_bound");
            List<UnifiedGameZip.Entry> entries = new ArrayList<>(); Set<String> required = new HashSet<>(); String previous = "";
            for (int at = 0; at < rows.length(); ++at) {
                JSONObject row = rows.getJSONObject(at), source = object(row, "source");
                String name = text(row, "name"), member = text(source, "member"), kind = text(source, "kind"), encodedHash = text(row, "compressed_sha256");
                long plain = number(row, "bytes"), compressed = number(row, "compressed_bytes"), crc = number(row, "crc32"), method = number(row, "method");
                require(UnifiedGameZip.name(name) && UnifiedGameZip.carrierMember(name) && previous.compareTo(name) < 0
                        && plain >= 0 && plain <= UnifiedGameZip.MAX_BYTES && compressed >= 0 && compressed <= UnifiedGameZip.MAX_BYTES
                        && crc >= 0 && crc <= 0xffffffffL && (method == 0 || method == 8) && hash(text(row, "sha256")) && hash(encodedHash),
                        "unified_data_entry_invalid");
                boolean object = "object".equals(kind);
                require(object ? member.equals(OBJECTS + encodedHash + ".bin")
                        : "base".equals(kind) && UnifiedGameZip.name(member) && UnifiedGameZip.carrierMember(member),
                        "unified_data_source_invalid");
                previous = name; required.add(name);
                entries.add(new UnifiedGameZip.Entry(name, member, object, plain, compressed, crc, (int) method, encodedHash));
            }
            require(required.contains(UnifiedGameZip.DATA + "Managed/Metadata/global-metadata.dat")
                    && required.contains(UnifiedGameZip.DATA + "unity_app_guid")
                    && required.contains(UnifiedGameZip.DATA + "boot.config"), "unified_data_required_member_missing");
            File folder = directory(context), target = new File(folder, "selected-" + identity + "-" + selectedLanguage + ".zip");
            boolean replacesFile = !regular(target) || target.length() != bytes || !UnifiedGameZip.hash(target).equals(digest);
            if (replacesFile) {
                require(PREPARATION.frozenLanguage() == null, "unified_data_active_carrier_invalid");
                require(!target.exists() || regular(target), "unified_data_existing_carrier_invalid");
                temporary = new File(folder, target.getName() + ".partial");
                if (temporary.exists()) { require(regular(temporary) && temporary.delete(), "unified_data_partial_cleanup_failed"); }
                require(temporary.createNewFile(), "unified_data_partial_exists");
                try (UnifiedGameZip.Source apk = new UnifiedGameZip.Source(new File(context.getApplicationInfo().sourceDir))) {
                    Set<String> dataNames = new HashSet<>(); for (String name : apk.members.keySet()) if (UnifiedGameZip.carrierMember(name) && !name.endsWith("/")) dataNames.add(name);
                    require(dataNames.equals(required), "unified_data_base_inventory_differs");
                    UnifiedGameZip.assemble(apk, entries, temporary, bytes, digest);
                }
                require(temporary.setReadOnly(), "unified_data_carrier_permissions_failed");
            }
            final File prepared = temporary;
            UnifiedGamePreparation.Snapshot snapshot = new UnifiedGamePreparation.Snapshot(selectedLanguage, target.getAbsolutePath(), identity, bytes);
            boolean coldPublication = PREPARATION.publish(snapshot, replacesFile, () -> {
                if (prepared != null) Os.rename(prepared.getPath(), target.getPath());
            });
            temporary = null;
            if (coldPublication) {
                File[] others = folder.listFiles();
                if (others != null) for (File old : others) {
                    if (!old.equals(target) && old.getName().matches("selected-[0-9a-f]{64}-(ko|ja|en)\\.zip(\\.partial)?") && regular(old)) old.delete();
                }
            }
            return target;
        } catch (Exception failure) {
            if (failure instanceof IOException) throw (IOException) failure;
            throw new IOException("unified_data_prepare_failed", failure);
        } finally { if (temporary != null && regular(temporary)) temporary.delete(); }
    }

    /** UI-thread cheap barrier. getPackageCodePath() may return this value before super.onCreate(). */
    public static String freeze(Context context, String selectedLanguage) throws IOException {
        require(language(selectedLanguage), "unified_data_language_invalid");
        return PREPARATION.freeze(selectedLanguage);
    }

    public static boolean isPrepared(String selectedLanguage) { return PREPARATION.isPrepared(selectedLanguage); }
    public static String frozenLanguage() { return PREPARATION.frozenLanguage(); }

    /** A process-local preparation result; obtaining it never touches the filesystem. */
    public static final class ReadySnapshot {
        public final String language, path, identity; public final long bytes;
        private ReadySnapshot(UnifiedGamePreparation.Snapshot value) {
            language = value.language; path = value.path; identity = value.identity; bytes = value.bytes;
        }
    }
    public static ReadySnapshot readySnapshot() {
        UnifiedGamePreparation.Snapshot value = PREPARATION.ready();
        return value == null ? null : new ReadySnapshot(value);
    }
    public static ReadySnapshot frozenSnapshot() {
        UnifiedGamePreparation.Snapshot value = PREPARATION.frozen();
        return value == null ? null : new ReadySnapshot(value);
    }
}
