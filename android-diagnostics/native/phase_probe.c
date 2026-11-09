#define _GNU_SOURCE
#include <android/log.h>
#include <dlfcn.h>
#include <elf.h>
#include <jni.h>
#include <link.h>
#include <limits.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <time.h>

#include "shadowhook.h"
#include "phase_sites.h"

static atomic_bool started = false;
static atomic_uint emitted = 0;
static void *pinned_il2cpp;

JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM *vm, void *reserved) {
    (void)vm; (void)reserved;
    // Stop nativeLoad's symbol search here: the C-only ShadowHook dependency's
    // JNI_OnLoad expects its optional Java wrapper, which this APK does not use.
    return JNI_VERSION_1_6;
}

static void emit(unsigned index, const char *code) {
    unsigned bit = 1u << index;
    if (!(atomic_fetch_or_explicit(&emitted, bit, memory_order_relaxed) & bit)) {
        char message[96] = "IDOLY_PHASE:";
        size_t prefix = sizeof("IDOLY_PHASE:") - 1;
        size_t length = strlen(code);
        if (prefix + length < sizeof(message)) {
            memcpy(message + prefix, code, length + 1);
            __android_log_write(ANDROID_LOG_INFO, "Unity", message);
        }
    }
}

static void unavailable(void) { emit(PHASE_COUNT + 1, "probe_unavailable"); }

static void checkpoint(shadowhook_cpu_context_t *context, void *data) {
    (void)context;  // Never read managed memory, change registers or invoke JNI.
    uintptr_t index = (uintptr_t)data;
    if (index < PHASE_COUNT) emit((unsigned)index, PHASE_SITES[index].code);
}

struct image {
    uintptr_t base;
    const ElfW(Phdr) *headers;
    size_t count;
    bool unity;
    bool il2cpp;
    char name[PATH_MAX];
};

static bool ends_with(const char *name, const char *suffix) {
    size_t length = strlen(name), tail = strlen(suffix);
    return length >= tail && memcmp(name + length - tail, suffix, tail) == 0;
}

static int find_image(struct dl_phdr_info *info, size_t size, void *data) {
    (void)size;
    struct image *image = data;
    if (ends_with(info->dlpi_name, "/libunity.so")) image->unity = true;
    if (ends_with(info->dlpi_name, "/libil2cpp.so")) {
        size_t length = strnlen(info->dlpi_name, sizeof(image->name));
        if (length == sizeof(image->name)) return 0;
        image->base = info->dlpi_addr;
        image->headers = info->dlpi_phdr;
        image->count = info->dlpi_phnum;
        image->il2cpp = true;
        memcpy(image->name, info->dlpi_name, length + 1);
    }
    return 0;
}

static bool mapped(const struct image *image, uintptr_t address, size_t size, unsigned flags) {
    if (address + size < address) return false;
    for (size_t i = 0; i < image->count; ++i) {
        const ElfW(Phdr) *header = image->headers + i;
        uintptr_t begin = image->base + header->p_vaddr;
        if (header->p_type == PT_LOAD && (header->p_flags & flags) == flags
                && address >= begin && address + size <= begin + header->p_filesz) return true;
    }
    return false;
}

static bool build_id_matches(const struct image *image) {
    for (size_t i = 0; i < image->count; ++i) {
        const ElfW(Phdr) *header = image->headers + i;
        if (header->p_type != PT_NOTE) continue;
        uintptr_t begin = image->base + header->p_vaddr;
        if (!mapped(image, begin, header->p_filesz, PF_R)) return false;
        size_t offset = 0;
        while (offset + sizeof(ElfW(Nhdr)) <= header->p_filesz) {
            const ElfW(Nhdr) *note = (const void *)(begin + offset);
            size_t names = (note->n_namesz + 3u) & ~3u;
            size_t desc = (note->n_descsz + 3u) & ~3u;
            size_t remaining = header->p_filesz - offset - sizeof(*note);
            if (names > remaining || desc > remaining - names) return false;
            const unsigned char *name = (const void *)(note + 1);
            const unsigned char *value = name + names;
            if (note->n_type == NT_GNU_BUILD_ID && note->n_namesz == 4
                    && memcmp(name, "GNU", 4) == 0 && note->n_descsz == sizeof(EXPECTED_BUILD_ID)) {
                return memcmp(value, EXPECTED_BUILD_ID, sizeof(EXPECTED_BUILD_ID)) == 0;
            }
            offset += sizeof(*note) + names + desc;
        }
    }
    return false;
}

static bool profile_matches(const struct image *image) {
    if (!build_id_matches(image)) return false;
    for (size_t i = 0; i < PHASE_COUNT; ++i) {
        uintptr_t address = image->base + PHASE_SITES[i].rva;
        if (!mapped(image, address, 16, PF_R | PF_X)
                || memcmp((const void *)address, PHASE_SITES[i].expected, 16) != 0) return false;
    }
    return true;
}

static void pause_ms(long milliseconds) {
    struct timespec interval = {.tv_sec = milliseconds / 1000,
                                .tv_nsec = (milliseconds % 1000) * 1000000};
    nanosleep(&interval, NULL);
}

static void *install(void *unused) {
    (void)unused;
    struct image image = {0};
    bool ready = false;
    for (unsigned attempt = 0; attempt < 900; ++attempt) {
        memset(&image, 0, sizeof(image));
        dl_iterate_phdr(find_image, &image);
        if (image.unity && image.il2cpp) {
            ready = true;
            break;
        }
        pause_ms(200);
    }
    if (!ready) { unavailable(); return NULL; }
    // Defer until Unity/IL2CPP and native SDK startup have begun. Upstream
    // documents signal-handler-ordering risks; this delay is not a guarantee.
    pause_ms(500);
    void *pin = dlopen(image.name, RTLD_NOW | RTLD_NOLOAD);
    if (!pin) { unavailable(); return NULL; }
    struct image held = {0};
    dl_iterate_phdr(find_image, &held);
    if (!held.unity || !held.il2cpp || strcmp(held.name, image.name) != 0) {
        dlclose(pin); unavailable(); return NULL;
    }
    image = held;
    if (!profile_matches(&image) || shadowhook_init(SHADOWHOOK_MODE_UNIQUE, false) != 0) {
        dlclose(pin); unavailable(); return NULL;
    }
    shadowhook_set_recordable(false);
    void *stubs[PHASE_COUNT] = {0};
    for (size_t i = 0; i < PHASE_COUNT; ++i) {
        stubs[i] = shadowhook_intercept_instr_addr((void *)(image.base + PHASE_SITES[i].rva),
            checkpoint, (void *)(uintptr_t)i, SHADOWHOOK_INTERCEPT_WITH_FPSIMD_READ_WRITE);
        if (!stubs[i]) {
            bool removed = true;
            for (size_t j = 0; j < i; ++j) {
                if (shadowhook_unintercept(stubs[j]) != 0) removed = false;
            }
            if (removed) dlclose(pin);
            else pinned_il2cpp = pin;
            unavailable(); return NULL;
        }
    }
    pinned_il2cpp = pin;  // Retain the ELF for the lifetime of active hooks.
    emit(PHASE_COUNT, "probe_ready");
    return NULL;
}

JNIEXPORT void JNICALL
Java_game_qualiarts_idolypride_diagnostics_NativePhaseProbe_nativeStart(JNIEnv *env, jclass type) {
    (void)env; (void)type;
    if (atomic_exchange_explicit(&started, true, memory_order_relaxed)) return;
    pthread_t worker;
    if (pthread_create(&worker, NULL, install, NULL) == 0) pthread_detach(worker);
    else unavailable();
}
