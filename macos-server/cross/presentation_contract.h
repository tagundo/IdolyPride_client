#ifndef IDOLY_PRESENTATION_CONTRACT_H
#define IDOLY_PRESENTATION_CONTRACT_H

/* Foundation-free contract, shared by the Cocoa fallback and host tests. */
typedef unsigned long IDPSize;
extern int strcmp(const char *, const char *);
extern IDPSize strlen(const char *);
extern int snprintf(char *, IDPSize, const char *, ...);
extern double strtod(const char *, char **);

typedef struct {
    long long revision;
    int custom, quality, fps;
    double scale;
    int maximum, aa, shadow, expand;
} IDPrefs;

static IDPrefs id_prefs_defaults(void) {
    IDPrefs value = {0, 0, 0, 0, 1.0, 4096, -1, 0, 0}; return value;
}

static int id_prefs_valid(const IDPrefs *p) {
    return p->revision >= 0 && (p->custom == 0 || p->custom == 1) && (p->expand == 0 || p->expand == 1)
        && (p->quality == 0 || p->quality == 10 || p->quality == 20 || p->quality == 30 || p->quality == 40 || p->quality == 100)
        && (p->fps == 0 || p->fps == 30 || p->fps == 60 || p->fps == 90 || p->fps == 120)
        && __builtin_isfinite(p->scale) && p->scale >= 0.25 && p->scale <= 2.0
        && p->maximum >= 256 && p->maximum <= 4096 && p->maximum % 2 == 0
        && p->aa >= -1 && p->aa <= 2
        && (p->shadow == 0 || p->shadow == 512 || p->shadow == 1024 || p->shadow == 2048 || p->shadow == 4096);
}

static void id_skip_space(const char *s, IDPSize n, IDPSize *i) {
    while (*i < n && (s[*i] == ' ' || s[*i] == '\n' || s[*i] == '\r' || s[*i] == '\t')) ++*i;
}

static int id_key(const char *s, IDPSize n, IDPSize *i, char out[64]) {
    IDPSize written = 0;
    if (*i >= n || s[(*i)++] != '"') return 0;
    while (*i < n) {
        unsigned int c = (unsigned char)s[(*i)++];
        if (c == '"') { out[written] = 0; return 1; }
        if (c == '\\') {
            if (*i >= n) return 0;
            c = (unsigned char)s[(*i)++];
            if (c == 'u') {
                unsigned int value = 0;
                for (int k = 0; k < 4; ++k) {
                    if (*i >= n) return 0;
                    unsigned int h = (unsigned char)s[(*i)++];
                    if (h >= '0' && h <= '9') h -= '0';
                    else if (h >= 'a' && h <= 'f') h = h - 'a' + 10;
                    else if (h >= 'A' && h <= 'F') h = h - 'A' + 10;
                    else return 0;
                    value = value * 16 + h;
                }
                c = value;
            } else if (c != '"' && c != '\\' && c != '/') return 0;
        }
        /* Contract member names are ASCII; all other names are unknown. */
        if (c < 32 || c > 126 || written >= 63) return 0;
        out[written++] = (char)c;
    }
    return 0;
}

static int id_integer(const char *s, IDPSize n, IDPSize *i, long long *result) {
    int negative = 0;
    unsigned long long number = 0;
    if (*i < n && s[*i] == '-') { negative = 1; ++*i; }
    if (*i >= n || s[*i] < '0' || s[*i] > '9') return 0;
    if (s[*i] == '0' && *i + 1 < n && s[*i + 1] >= '0' && s[*i + 1] <= '9') return 0;
    while (*i < n && s[*i] >= '0' && s[*i] <= '9') {
        unsigned int digit = (unsigned int)(s[(*i)++] - '0');
        if (number > (9223372036854775807ULL - digit) / 10) return 0;
        number = number * 10 + digit;
    }
    *result = negative ? -(long long)number : (long long)number;
    return 1;
}

static int id_boolean(const char *s, IDPSize n, IDPSize *i, int *result) {
    const char *word;
    if (*i < n && s[*i] == 't') { word = "true"; *result = 1; }
    else { word = "false"; *result = 0; }
    for (IDPSize k = 0; word[k]; ++k) if (*i >= n || s[(*i)++] != word[k]) return 0;
    return 1;
}

static int id_real(const char *s, IDPSize n, IDPSize *i, double *result) {
    IDPSize start = *i;
    if (*i < n && s[*i] == '-') ++*i;
    if (*i >= n || s[*i] < '0' || s[*i] > '9') return 0;
    if (s[*i] == '0') ++*i;
    else while (*i < n && s[*i] >= '0' && s[*i] <= '9') ++*i;
    if (*i < n && s[*i] == '.') {
        ++*i;
        IDPSize fraction = *i;
        while (*i < n && s[*i] >= '0' && s[*i] <= '9') ++*i;
        if (*i == fraction) return 0;
    }
    if (*i < n && (s[*i] == 'e' || s[*i] == 'E')) {
        ++*i;
        if (*i < n && (s[*i] == '+' || s[*i] == '-')) ++*i;
        IDPSize exponent = *i;
        while (*i < n && s[*i] >= '0' && s[*i] <= '9') ++*i;
        if (*i == exponent) return 0;
    }
    IDPSize count = *i - start;
    if (count > 8192) return 0;
    char number[8193];
    for (IDPSize k = 0; k < count; ++k) number[k] = s[start + k];
    number[count] = 0;
    char *end = 0;
    *result = strtod(number, &end);
    return end == number + count && __builtin_isfinite(*result);
}

static int id_prefs_decode(const char *s, IDPSize n, IDPrefs *output) {
    static const char *keys[] = {"schema", "revision", "custom_graphics", "quality", "target_fps",
        "render_scale", "max_buffer_pixel", "anti_aliasing", "shadow_resolution", "expand_photography"};
    if (!s || n == 0 || n > 8192) return 0;
    IDPrefs p = id_prefs_defaults();
    IDPSize i = 0;
    unsigned int seen = 0;
    id_skip_space(s, n, &i);
    if (i >= n || s[i++] != '{') return 0;
    for (;;) {
        char key[64];
        id_skip_space(s, n, &i);
        if (!id_key(s, n, &i, key)) return 0;
        int field = -1;
        for (int k = 0; k < 10; ++k) if (strcmp(keys[k], key) == 0) field = k;
        if (field < 0 || (seen & (1U << field))) return 0;
        seen |= 1U << field;
        id_skip_space(s, n, &i);
        if (i >= n || s[i++] != ':') return 0;
        id_skip_space(s, n, &i);
        long long value = 0;
        if (field == 2 || field == 9) {
            int flag;
            if (!id_boolean(s, n, &i, &flag)) return 0;
            if (field == 2) p.custom = flag; else p.expand = flag;
        } else if (field == 5) {
            if (!id_real(s, n, &i, &p.scale)) return 0;
        } else {
            if (!id_integer(s, n, &i, &value)) return 0;
            if (field == 0) { if (value != 1) return 0; }
            else if (field == 1) p.revision = value;
            else {
                if (value < -1 || value > 4096) return 0;
                if (field == 3) p.quality = (int)value;
                if (field == 4) p.fps = (int)value;
                if (field == 6) p.maximum = (int)value;
                if (field == 7) p.aa = (int)value;
                if (field == 8) p.shadow = (int)value;
            }
        }
        id_skip_space(s, n, &i);
        if (i >= n) return 0;
        if (s[i] == '}') { ++i; break; }
        if (s[i++] != ',') return 0;
    }
    id_skip_space(s, n, &i);
    if (i != n || seen != 1023 || !id_prefs_valid(&p)) return 0;
    *output = p;
    return 1;
}

static int id_prefs_encode(const IDPrefs *p, char *output, IDPSize capacity) {
    if (!id_prefs_valid(p)) return 0;
    int count = snprintf(output, capacity,
        "{\"schema\":1,\"revision\":%lld,\"custom_graphics\":%s,\"quality\":%d,\"target_fps\":%d,"
        "\"render_scale\":%.17g,\"max_buffer_pixel\":%d,\"anti_aliasing\":%d,\"shadow_resolution\":%d,\"expand_photography\":%s}",
        p->revision, p->custom ? "true" : "false", p->quality, p->fps, p->scale, p->maximum,
        p->aa, p->shadow, p->expand ? "true" : "false");
    return count > 0 && (IDPSize)count < capacity ? count : 0;
}

static int id_prefs_next(const IDPrefs *current, long long now, IDPrefs *next) {
    if (!id_prefs_valid(current) || current->revision == 9223372036854775807LL) return 0;
    *next = *current;
    next->revision = current->revision + 1;
    if (now > next->revision) next->revision = now;
    return 1;
}

typedef struct { int outstanding, received; double time; } IDPolling;
static int id_poll_begin(IDPolling *p) { if (p->outstanding) return 0; p->outstanding = 1; return 1; }
static void id_poll_received(IDPolling *p, double now) { p->outstanding = 0; p->received = __builtin_isfinite(now); p->time = now; }
static int id_poll_fresh(const IDPolling *p, double now) {
    return p->received && __builtin_isfinite(now) && now >= p->time && now - p->time <= 5.0;
}

/* 0/1 pending, 2/3 actual successful ACKs, 4..6 actual non-success states. */
static int id_ack_feedback(int running, int fresh, long long requested, int bridge, long long applied, const char *state) {
    int pending = requested > 0 ? 1 : 0;
    if (!running || !fresh || bridge != 1 || applied < 0 || !state) return pending;
    if (strcmp(state, "applied") == 0) return applied == requested ? 2 : pending;
    if (strcmp(state, "disabled") == 0) return applied == requested ? 3 : pending;
    if (strcmp(state, "unsupported") == 0) return 4;
    if (strcmp(state, "waiting_for_scene") == 0) return 5;
    if (strcmp(state, "init_failed") == 0) return 6;
    return pending;
}

#endif
