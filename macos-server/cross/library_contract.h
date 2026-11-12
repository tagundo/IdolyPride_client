#ifndef IDOLY_LIBRARY_CONTRACT_H
#define IDOLY_LIBRARY_CONTRACT_H
#include "presentation_contract.h"

/* Public startup preferences only; no account data or game file operations. */
typedef struct { long long revision; int hideVideo, mvSort, outfitSort, language; } IDLibraryPrefs;
static const char *const id_mv_sorts[] = {"recent", "old", "title", "id"};
static const char *const id_outfit_sorts[] = {"original", "recent", "old", "title", "id"};
static const char *const id_languages[] = {"ja", "ko", "en"};
static inline IDLibraryPrefs id_library_defaults(void) { IDLibraryPrefs v = {0, 0, 0, 0, 0}; return v; }
static inline int id_library_valid(const IDLibraryPrefs *v) {
    return v && v->revision >= 0 && (v->hideVideo == 0 || v->hideVideo == 1)
        && v->mvSort >= 0 && v->mvSort < 4 && v->outfitSort >= 0 && v->outfitSort < 5
        && v->language >= 0 && v->language < 3;
}
static inline int id_library_choice(const char *word, const char *const *choices, int count) {
    for (int i = 0; i < count; ++i) if (strcmp(word, choices[i]) == 0) return i;
    return -1;
}
static inline int id_library_decode(const char *s, IDPSize n, IDLibraryPrefs *output, int languageOnly) {
    static const char *keys[] = {"schema", "revision", "hide_video_mv", "mv_sort", "outfit_sort"};
    if (!s || !output || !n || n > 8192) return 0;
    IDLibraryPrefs value = id_library_defaults(); IDPSize i = 0; unsigned seen = 0;
    id_skip_space(s, n, &i); if (i >= n || s[i++] != '{') return 0;
    for (;;) {
        char key[64], word[64]; int field = -1;
        id_skip_space(s, n, &i); if (!id_key(s, n, &i, key)) return 0;
        if (languageOnly) { if (!strcmp(key,"schema")) field=0; else if (!strcmp(key,"language")) field=1; }
        else for (int k = 0; k < 5; ++k) if (!strcmp(key, keys[k])) field=k;
        if (field < 0 || (seen & (1u << field))) return 0;
        seen |= 1u << field; id_skip_space(s,n,&i);
        if (i >= n || s[i++] != ':') return 0;
        id_skip_space(s,n,&i);
        if ((languageOnly && field == 1) || (!languageOnly && field >= 3)) {
            if (!id_key(s,n,&i,word)) return 0;
            int choice = languageOnly ? id_library_choice(word,id_languages,3)
                : field == 3 ? id_library_choice(word,id_mv_sorts,4) : id_library_choice(word,id_outfit_sorts,5);
            if (choice < 0) return 0;
            if (languageOnly) value.language=choice; else if (field == 3) value.mvSort=choice; else value.outfitSort=choice;
        } else if (field == 2) { if (!id_boolean(s,n,&i,&value.hideVideo)) return 0; }
        else {
            long long number; if (!id_integer(s,n,&i,&number)) return 0;
            if (field == 0) { if (number != 1) return 0; } else value.revision=number;
        }
        id_skip_space(s,n,&i); if (i >= n) return 0;
        if (s[i] == '}') { ++i; break; }
        if (s[i++] != ',') return 0;
    }
    id_skip_space(s,n,&i);
    if (i != n || seen != (languageOnly ? 3u : 31u) || !id_library_valid(&value)) return 0;
    *output=value; return 1;
}
static inline int id_library_encode(const IDLibraryPrefs *v, char *bytes, IDPSize capacity, int languageOnly) {
    if (!bytes || !capacity || !id_library_valid(v)) return 0;
    int n = languageOnly ? snprintf(bytes,capacity,"{\"schema\":1,\"language\":\"%s\"}",id_languages[v->language])
        : snprintf(bytes,capacity,"{\"schema\":1,\"revision\":%lld,\"hide_video_mv\":%s,\"mv_sort\":\"%s\",\"outfit_sort\":\"%s\"}",
            v->revision,v->hideVideo ? "true" : "false",id_mv_sorts[v->mvSort],id_outfit_sorts[v->outfitSort]);
    return n > 0 && (IDPSize)n < capacity ? n : 0;
}
static inline int id_library_next(const IDLibraryPrefs *current, long long now, IDLibraryPrefs *next) {
    if (!next || !id_library_valid(current) || current->revision == 9223372036854775807LL) return 0;
    *next=*current; next->revision=current->revision+1; if (now > next->revision) next->revision=now; return 1;
}
static inline int id_resource_job_valid(const char *id) {
    if (!id) return 0;
    IDPSize n=0;
    for (; id[n]; ++n) if (n >= 64 || !((id[n]>='a' && id[n]<='z') || (id[n]>='A' && id[n]<='Z')
        || (id[n]>='0' && id[n]<='9') || id[n]=='-' || id[n]=='_')) return 0;
    return n > 0;
}
static inline int id_resource_active(const char *state) {
    return state && (!strcmp(state,"preparing") || !strcmp(state,"running")
        || !strcmp(state,"export_ready") || !strcmp(state,"cancelling"));
}
/* Only an explicitly stored Boolean false opts out of the Downloads default. */
static inline int id_resources_in_downloads(int hasBoolean, int value) { return !hasBoolean || value != 0; }
static inline int id_library_escape(const char *argument, char *escaped, IDPSize capacity) {
    if (!argument || !escaped || !capacity) return 0;
    IDPSize used=0;
    for (IDPSize i=0;argument[i];++i) {
        unsigned char c=(unsigned char)argument[i];
        if (c=='"' || c=='\\') { if (used+2 >= capacity) return 0; escaped[used++]='\\'; escaped[used++]=(char)c; }
        else if (c<32) {
            static const char hex[]="0123456789abcdef";
            if (used+6 >= capacity) return 0;
            escaped[used++]='\\';escaped[used++]='u';escaped[used++]='0';escaped[used++]='0';
            escaped[used++]=hex[c>>4];escaped[used++]=hex[c&15];
        } else { if (used+1 >= capacity) return 0; escaped[used++]=(char)c; }
    }
    escaped[used]=0;return 1;
}
static inline int id_server_start_command(int live, int media, int download, const char *cacheDirectory,
        char *output, IDPSize capacity) {
    if (!output || !capacity || (live != 0 && live != 1) || (media != 0 && media != 1)
        || (download != 0 && download != 1) || (cacheDirectory && cacheDirectory[0] != '/')) return 0;
    char escaped[513];
    if (cacheDirectory && !id_library_escape(cacheDirectory,escaped,sizeof escaped)) return 0;
    int count = cacheDirectory ? snprintf(output,capacity,
        "{\"action\":\"start\",\"experimental_main_live\":%s,\"media_mode\":%s,\"download_missing_resources\":%s,\"resource_cache_dir\":\"%s\"}\n",
        live ? "true" : "false",media ? "true" : "false",download ? "true" : "false",escaped)
        : snprintf(output,capacity,
        "{\"action\":\"start\",\"experimental_main_live\":%s,\"media_mode\":%s,\"download_missing_resources\":%s,\"resource_cache_dir\":null}\n",
        live ? "true" : "false",media ? "true" : "false",download ? "true" : "false");
    return count > 0 && count <= 512 && (IDPSize)count < capacity ? count : 0;
}
/* Escaping and the complete serialized command stay below the atomic PIPE_BUF
   contract. Oversized paths fail before a byte is sent; UTF-8 is preserved. */
static inline int id_resource_command(const char *action, const char *platform, const char *argument,
        char *output, IDPSize capacity) {
    if (!action || !output || capacity < 2) return 0;
    int cancel=!strcmp(action,"resources_cancel"), archive=!strcmp(action,"resources_export") || !strcmp(action,"resources_import");
    if (!cancel && !archive && strcmp(action,"resources_preview") && strcmp(action,"resources_download")) return 0;
    if (!cancel && (!platform || (strcmp(platform,"ios") && strcmp(platform,"android")))) return 0;
    if (cancel && !id_resource_job_valid(argument)) return 0;
    IDPSize length=argument ? strlen(argument) : 0;
    if (archive && (!argument || length < 5 || argument[0] != '/' || argument[length-4] != '.'
        || (argument[length-3] != 'z' && argument[length-3] != 'Z')
        || (argument[length-2] != 'i' && argument[length-2] != 'I')
        || (argument[length-1] != 'p' && argument[length-1] != 'P'))) return 0;
    if (!archive && !cancel && argument) return 0;
    char escaped[513];
    if ((archive || cancel) && !id_library_escape(argument,escaped,sizeof escaped)) return 0;
    int n = cancel ? snprintf(output,capacity,"{\"action\":\"resources_cancel\",\"job_id\":\"%s\"}\n",escaped)
        : archive ? snprintf(output,capacity,"{\"action\":\"%s\",\"platform\":\"%s\",\"path\":\"%s\"}\n",action,platform,escaped)
        : snprintf(output,capacity,"{\"action\":\"%s\",\"platform\":\"%s\"}\n",action,platform);
    return n > 0 && n <= 512 && (IDPSize)n < capacity ? n : 0;
}
#endif
