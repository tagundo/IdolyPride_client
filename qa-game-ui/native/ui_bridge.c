#define _GNU_SOURCE
#include <dlfcn.h>
#include <elf.h>
#include <jni.h>
#include <link.h>
#include <limits.h>
#include <math.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "ui_json.h"
#include "ui_profile.h"

/* QA-only: invoked by Java Runnable on UnityPlayer's own UnityMain queue.
 * No hooks, method pointer replacement, HTTP, credentials or game API calls.
 * No managed object/field offsets are used; all access uses IL2CPP APIs. */
#define NODE_LIMIT 512
#define JSON_LIMIT 65536
#define ARRAY_LIMIT 8192
typedef void Obj;
typedef void Klass;
typedef void Method;
typedef void Field;
typedef struct { float x, y; } Vec2;
typedef struct { float x, y, z; } Vec3;
struct bounds { float left, top, right, bottom; Vec2 center; };

static struct {
    void *(*domain_get)(void);
    const void **(*domain_get_assemblies)(const void *, size_t *);
    const void *(*assembly_get_image)(const void *);
    const char *(*image_get_name)(const void *);
    Klass *(*class_from_name)(const void *, const char *, const char *);
    const Method *(*class_get_method_from_name)(Klass *, const char *, int);
    const Method *(*class_get_methods)(Klass *, void **);
    const Field *(*class_get_field_from_name)(Klass *, const char *);
    const void *(*field_get_type)(const Field *);
    uint32_t (*field_get_flags)(const Field *);
    void (*field_get_value)(Obj *, const Field *, void *);
    void (*field_static_get_value)(const Field *, void *);
    const void *(*class_get_type)(Klass *);
    Klass *(*object_get_class)(Obj *);
    bool (*class_is_assignable_from)(Klass *, Klass *);
    Obj *(*type_get_object)(const void *);
    Obj *(*runtime_invoke)(const Method *, Obj *, void **, Obj **);
    const Method *(*object_get_virtual_method)(Obj *, const Method *);
    void *(*object_unbox)(Obj *);
    uint32_t (*gchandle_new)(Obj *, bool);
    Obj *(*gchandle_get_target)(uint32_t);
    void (*gchandle_free)(uint32_t);
    uintptr_t (*array_length)(Obj *);
    Obj *(*array_new)(Klass *, uintptr_t);
    int32_t (*string_length)(Obj *);
    const uint16_t *(*string_chars)(Obj *);
    void *(*thread_current)(void);
    const char *(*method_get_name)(const Method *);
    uint32_t (*method_get_param_count)(const Method *);
    const void *(*method_get_param)(const Method *, uint32_t);
    int (*type_get_type)(const void *);
} api;

static struct methods {
    Klass *button, *qua_button, *text, *tmp, *rect, *vector3, *canvas;
    const Method *find_all, *array_get, *id, *name, *alive, *game_object, *transform;
    const Method *active, *enabled, *interactable, *parent, *text_value, *tmp_value;
    const Method *qua_enabled, *parent_component, *corners, *root_canvas, *render_mode, *camera;
    const Method *screen_point, *screen_width, *screen_height;
} methods;

static struct {
    Klass *title_presenter, *title_view, *solis_button, *event_system, *input_module;
    const Field *callback, *title_initialized, *view, *title_button, *interceptor;
    const Field *current_input_module, *is_releasing;
    const Method *initialization_succeeded, *content_blocking;
} observations;
struct observed_bool { bool available, value; };
static bool callback_observation_missing;

struct retained { int32_t id; uint32_t handle; bool qua; };
static struct retained buttons[NODE_LIMIT];
static size_t button_count;
static uint64_t generation;
static int64_t snapshot_time;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static bool initialized;
static void *pinned;

struct image { uintptr_t base; const ElfW(Phdr) *phdr; size_t count; char name[PATH_MAX]; };
static int find_image(struct dl_phdr_info *i, size_t ignored, void *opaque) {
    (void)ignored; struct image *out = opaque;
    size_t n = strlen(i->dlpi_name), end = strlen("/libil2cpp.so");
    if (n < end || n >= sizeof(out->name) || strcmp(i->dlpi_name + n - end, "/libil2cpp.so")) return 0;
    out->base = i->dlpi_addr; out->phdr = i->dlpi_phdr; out->count = i->dlpi_phnum;
    memcpy(out->name, i->dlpi_name, n + 1); return 1;
}
static bool mapped(const struct image *i, uintptr_t p, size_t n, unsigned flags) {
    if (p + n < p) return false;
    for (size_t j = 0; j < i->count; ++j) {
        const ElfW(Phdr) *h = i->phdr + j; uintptr_t begin = i->base + h->p_vaddr;
        if (h->p_type == PT_LOAD && (h->p_flags & flags) == flags && p >= begin
                && p + n <= begin + h->p_filesz) return true;
    }
    return false;
}
static bool build_id(const struct image *i) {
    for (size_t j = 0; j < i->count; ++j) {
        const ElfW(Phdr) *h = i->phdr + j;
        if (h->p_type != PT_NOTE || !mapped(i, i->base + h->p_vaddr, h->p_filesz, PF_R)) continue;
        size_t pos = 0;
        while (pos + sizeof(ElfW(Nhdr)) <= h->p_filesz) {
            const ElfW(Nhdr) *n = (const void *)(i->base + h->p_vaddr + pos);
            size_t names = ((size_t)n->n_namesz + 3) & ~(size_t)3;
            size_t desc = ((size_t)n->n_descsz + 3) & ~(size_t)3;
            size_t left = h->p_filesz - pos - sizeof(*n);
            if (names > left || desc > left - names) return false;
            const unsigned char *name = (const void *)(n + 1);
            if (n->n_type == NT_GNU_BUILD_ID && n->n_namesz == 4 && !memcmp(name, "GNU", 4)
                    && n->n_descsz == sizeof(UI_BUILD_ID))
                return !memcmp(name + names, UI_BUILD_ID, sizeof(UI_BUILD_ID));
            pos += sizeof(*n) + names + desc;
        }
    }
    return false;
}
static bool load_api(void) {
    struct image first = {0}, held = {0}; dl_iterate_phdr(find_image, &first);
    if (!first.name[0]) return false;
    void *handle = dlopen(first.name, RTLD_NOW | RTLD_NOLOAD);
    if (!handle) return false;
    dl_iterate_phdr(find_image, &held);
    if (strcmp(held.name, first.name) || !build_id(&held)) { dlclose(handle); return false; }
    for (size_t j = 0; j < UI_EXPORT_COUNT; ++j) {
        void *p = dlsym(handle, UI_EXPORTS[j].name);
        if ((uintptr_t)p != held.base + UI_EXPORTS[j].rva || !mapped(&held, (uintptr_t)p, 16, PF_R | PF_X)
                || memcmp(p, UI_EXPORTS[j].bytes, 16)) { dlclose(handle); return false; }
    }
#define LOAD(field) do { void *p = dlsym(handle, "il2cpp_" #field); memcpy(&api.field, &p, sizeof(p)); } while (0)
    LOAD(domain_get); LOAD(domain_get_assemblies); LOAD(assembly_get_image); LOAD(image_get_name);
    LOAD(class_from_name); LOAD(class_get_method_from_name); LOAD(class_get_type); LOAD(type_get_object);
    LOAD(class_get_methods); LOAD(method_get_name); LOAD(method_get_param_count); LOAD(method_get_param); LOAD(type_get_type);
    LOAD(class_get_field_from_name); LOAD(field_get_type); LOAD(field_get_flags); LOAD(field_get_value); LOAD(field_static_get_value);
    LOAD(object_get_class); LOAD(class_is_assignable_from); LOAD(array_new);
    LOAD(runtime_invoke); LOAD(object_get_virtual_method); LOAD(object_unbox);
    LOAD(gchandle_new); LOAD(gchandle_get_target); LOAD(gchandle_free); LOAD(array_length);
    LOAD(string_length); LOAD(string_chars); LOAD(thread_current);
#undef LOAD
    pinned = handle; return true;
}
static Klass *klass(const char *image, const char *ns, const char *name) {
    void *domain = api.domain_get(); if (!domain) return NULL;
    size_t count = 0; const void **assemblies = api.domain_get_assemblies(domain, &count);
    if (!assemblies || count > 4096) return NULL;
    for (size_t j = 0; j < count; ++j) {
        const void *im = api.assembly_get_image(assemblies[j]);
        const char *n = im ? api.image_get_name(im) : NULL;
        if (n && !strcmp(n, image)) return api.class_from_name(im, ns, name);
    }
    return NULL;
}
static const Method *method(Klass *k, const char *name, int args) {
    return k ? api.class_get_method_from_name(k, name, args) : NULL;
}
static const Method *array_get_int32(Klass *k) {
    if (!k) return NULL;
    void *iter = NULL; const Method *m;
    while ((m = api.class_get_methods(k, &iter))) {
        if (!strcmp(api.method_get_name(m), "GetValue") && api.method_get_param_count(m) == 1
                && api.type_get_type(api.method_get_param(m, 0)) == 0x08) return m;
    }
    return NULL;
}
static Obj *invoke(const Method *m, Obj *o, void **args, bool virt, bool *ok) {
    if (!*ok || !m) { *ok = false; return NULL; }
    if (virt) { if (!o) { *ok = false; return NULL; } m = api.object_get_virtual_method(o, m); }
    if (!m) { *ok = false; return NULL; }
    Obj *exception = NULL; Obj *result = api.runtime_invoke(m, o, args, &exception);
    if (exception) { *ok = false; return NULL; }
    return result;
}
static bool value_bool(Obj *o, bool *ok) {
    void *p = o ? api.object_unbox(o) : NULL;
    if (!p) { *ok = false; return false; }
    return *(const bool *)p;
}
static int32_t value_int(Obj *o, bool *ok) {
    void *p = o ? api.object_unbox(o) : NULL;
    if (!p) { *ok = false; return 0; }
    int32_t n; memcpy(&n, p, sizeof(n)); return n;
}
static bool initialize(void) {
    if (initialized) return true;
    if (!pinned && !load_api()) return false;
    if (!api.thread_current()) return false;
    Klass *object = klass("UnityEngine.CoreModule.dll", "UnityEngine", "Object");
    Klass *component = klass("UnityEngine.CoreModule.dll", "UnityEngine", "Component");
    Klass *behaviour = klass("UnityEngine.CoreModule.dll", "UnityEngine", "Behaviour");
    Klass *game = klass("UnityEngine.CoreModule.dll", "UnityEngine", "GameObject");
    Klass *transform = klass("UnityEngine.CoreModule.dll", "UnityEngine", "Transform");
    Klass *resources = klass("UnityEngine.CoreModule.dll", "UnityEngine", "Resources");
    Klass *array = klass("mscorlib.dll", "System", "Array");
    Klass *selectable = klass("UnityEngine.UI.dll", "UnityEngine.UI", "Selectable");
    Klass *rect_utility = klass("UnityEngine.UIModule.dll", "UnityEngine", "RectTransformUtility");
    Klass *screen = klass("UnityEngine.CoreModule.dll", "UnityEngine", "Screen");
    methods.button = klass("UnityEngine.UI.dll", "UnityEngine.UI", "Button");
    methods.text = klass("UnityEngine.UI.dll", "UnityEngine.UI", "Text");
    methods.tmp = klass("Unity.TextMeshPro.dll", "TMPro", "TMP_Text");
    methods.qua_button = klass("quaunity-ui.Runtime.dll", "Qua.UI", "ButtonBase");
    methods.rect = klass("UnityEngine.CoreModule.dll", "UnityEngine", "RectTransform");
    methods.vector3 = klass("UnityEngine.CoreModule.dll", "UnityEngine", "Vector3");
    methods.canvas = klass("UnityEngine.UIModule.dll", "UnityEngine", "Canvas");
    methods.find_all = method(resources, "FindObjectsOfTypeAll", 1);
    methods.array_get = array_get_int32(array);
    methods.id = method(object, "GetInstanceID", 0); methods.name = method(object, "get_name", 0);
    methods.alive = method(object, "op_Implicit", 1);
    methods.game_object = method(component, "get_gameObject", 0);
    methods.transform = method(component, "get_transform", 0);
    methods.active = method(game, "get_activeInHierarchy", 0);
    methods.enabled = method(behaviour, "get_isActiveAndEnabled", 0);
    methods.interactable = method(selectable, "IsInteractable", 0);
    methods.parent = method(transform, "get_parent", 0);
    methods.text_value = method(methods.text, "get_text", 0);
    /* TMP's text getter consumes a dirty flag without updating its cached
     * m_text in this client. Read the parsed render characters instead. */
    methods.tmp_value = method(methods.tmp, "GetParsedText", 0);
    methods.qua_enabled = method(methods.qua_button, "get_IsEnabled", 0);
    methods.parent_component = method(component, "GetComponentInParent", 1);
    methods.corners = method(methods.rect, "GetWorldCorners", 1);
    methods.root_canvas = method(methods.canvas, "get_rootCanvas", 0);
    methods.render_mode = method(methods.canvas, "get_renderMode", 0);
    methods.camera = method(methods.canvas, "get_worldCamera", 0);
    methods.screen_point = method(rect_utility, "WorldToScreenPoint", 2);
    methods.screen_width = method(screen, "get_width", 0);
    methods.screen_height = method(screen, "get_height", 0);
    const Method *required[] = {methods.find_all, methods.array_get, methods.id, methods.name, methods.alive,
        methods.game_object, methods.transform, methods.active, methods.enabled, methods.interactable,
        methods.parent, methods.text_value, methods.tmp_value, methods.qua_enabled};
    if (!methods.button || !methods.text || !methods.tmp || !methods.qua_button) return false;
    for (size_t j = 0; j < sizeof(required)/sizeof(required[0]); ++j) if (!required[j]) return false;
    observations.title_presenter = klass("Assembly-CSharp.dll", "Solis.Title", "TitlePresenter");
    observations.title_view = klass("Assembly-CSharp.dll", "Solis.Title", "TitleView");
    observations.solis_button = klass("solis-submodule.Runtime.dll", "Solis.Common", "SolisButtonBase");
    observations.event_system = klass("UnityEngine.UI.dll", "UnityEngine.EventSystems", "EventSystem");
    observations.input_module = klass("Assembly-CSharp.dll", "Solis.Common", "SolisInputModule");
    observations.callback = api.class_get_field_from_name(methods.qua_button, "onClickedCallback");
    if (observations.title_presenter) {
        observations.title_initialized = api.class_get_field_from_name(observations.title_presenter, "_isInitialized");
        observations.view = api.class_get_field_from_name(observations.title_presenter, "_view");
    }
    if (observations.title_view)
        observations.title_button = api.class_get_field_from_name(observations.title_view, "_titleButton");
    if (observations.solis_button)
        observations.interceptor = api.class_get_field_from_name(observations.solis_button, "clickInterceptor");
    if (observations.event_system)
        observations.current_input_module = api.class_get_field_from_name(observations.event_system, "m_CurrentInputModule");
    if (observations.input_module)
        observations.is_releasing = api.class_get_field_from_name(observations.input_module, "<IsReleasing>k__BackingField");
    observations.initialization_succeeded = method(klass("Assembly-CSharp.dll", "Solis.Common", "SolisInitializer"), "get_IsSuccess", 0);
    observations.content_blocking = method(klass("Assembly-CSharp.dll", "Solis.Common", "SolisBlockingManager"), "IsActive", 1);
    initialized = true; return true;
}
static bool unity_thread(JNIEnv *e) {
    jclass thread = (*e)->FindClass(e, "java/lang/Thread");
    if (!thread) return false;
    jmethodID current = (*e)->GetStaticMethodID(e, thread, "currentThread", "()Ljava/lang/Thread;");
    jmethodID get_name = (*e)->GetMethodID(e, thread, "getName", "()Ljava/lang/String;");
    jobject self = current ? (*e)->CallStaticObjectMethod(e, thread, current) : NULL;
    jstring name = self && get_name ? (*e)->CallObjectMethod(e, self, get_name) : NULL;
    const char *chars = name ? (*e)->GetStringUTFChars(e, name, NULL) : NULL;
    bool ok = chars && !strcmp(chars, "UnityMain");
    if (chars) (*e)->ReleaseStringUTFChars(e, name, chars);
    if (name) (*e)->DeleteLocalRef(e, name);
    if (self) (*e)->DeleteLocalRef(e, self);
    (*e)->DeleteLocalRef(e, thread);
    return ok && !(*e)->ExceptionCheck(e);
}
static jstring error(JNIEnv *e, const char *code) {
    if ((*e)->ExceptionCheck(e)) (*e)->ExceptionClear(e);
    char message[128]; snprintf(message, sizeof(message), "{\"ok\":false,\"error\":\"%s\"}", code);
    return (*e)->NewStringUTF(e, message);
}
static void clear_buttons(void) {
    for (size_t j = 0; j < button_count; ++j) api.gchandle_free(buttons[j].handle);
    button_count = 0;
}
static void advance(void) { generation = generation >= INT64_MAX ? 1 : generation + 1; }
static int64_t now_ms(void) {
    struct timespec t; if (clock_gettime(CLOCK_MONOTONIC, &t)) return 0;
    return (int64_t)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}
static void string_json(struct ui_json *j, Obj *s, size_t limit) {
    if (!s) { ui_raw(j, "\"\""); return; }
    int32_t n = api.string_length(s);
    const uint16_t *p = api.string_chars(s);
    if (n < 0 || n > 1048576 || !p) { j->failed = true; return; }
    ui_utf16(j, p, (size_t)n, limit);
}
static int32_t object_id(Obj *o, bool *ok) { return value_int(invoke(methods.id, o, NULL, false, ok), ok); }
static bool usable(Obj *o, bool *ok) {
    if (!o) return false;
    void *args[] = {o};
    if (!value_bool(invoke(methods.alive, NULL, args, false, ok), ok)) return false;
    Obj *game = invoke(methods.game_object, o, NULL, false, ok);
    return game && value_bool(invoke(methods.active, game, NULL, false, ok), ok)
        && value_bool(invoke(methods.enabled, o, NULL, false, ok), ok);
}
static bool field_valid(Klass *owner, Obj *o, const Field *field, bool is_static, bool reference) {
    if (!owner || !field || (((api.field_get_flags(field) & 0x10u) != 0) != is_static)) return false;
    if (!is_static && (!o || !api.class_is_assignable_from(owner, api.object_get_class(o)))) return false;
    const void *type = api.field_get_type(field);
    if (!type) return false;
    int kind = api.type_get_type(type);
    /* Only references or the one-byte IL2CPP Boolean may be copied into our buffers. */
    return reference ? (kind == 0x12 || kind == 0x15 || kind == 0x1c) : kind == 0x02;
}
static bool field_reference(Klass *owner, Obj *o, const Field *field, bool is_static, Obj **value) {
    *value = NULL;
    if (!field_valid(owner, o, field, is_static, true)) return false;
    if (is_static) api.field_static_get_value(field, value);
    else api.field_get_value(o, field, value);
    return true;
}
static struct observed_bool field_boolean(Klass *owner, Obj *o, const Field *field) {
    if (!field_valid(owner, o, field, false, false)) return (struct observed_bool){false, false};
    unsigned char value = 0;
    api.field_get_value(o, field, &value);
    if (value > 1) return (struct observed_bool){false, false};
    return (struct observed_bool){true, value != 0};
}
static struct observed_bool query_boolean(const Method *m, void **args) {
    bool ok = true;
    Obj *value = invoke(m, NULL, args, false, &ok);
    bool state = ok && value_bool(value, &ok);
    return (struct observed_bool){ok, state};
}
static void boolean_json(struct ui_json *j, struct observed_bool value) {
    ui_raw(j, !value.available ? "null" : value.value ? "true" : "false");
}
static struct observed_bool callback_registered(Obj *button) {
    Obj *callback = NULL;
    bool ok = field_reference(methods.qua_button, button, observations.callback, false, &callback);
    return (struct observed_bool){ok, callback != NULL};
}
static struct observed_bool input_releasing(void) {
    struct observed_bool result = {false, false};
    if (!observations.event_system || !observations.input_module || !observations.current_input_module
            || !observations.is_releasing) return result;
    bool ok = true;
    Obj *type = api.type_get_object(api.class_get_type(observations.event_system)); void *args[] = {type};
    Obj *array = invoke(methods.find_all, NULL, args, false, &ok);
    uint32_t root = array ? api.gchandle_new(array, false) : 0;
    if (!ok || !root) { if (root) api.gchandle_free(root); return result; }
    uintptr_t count = api.array_length(array); unsigned active = 0;
    if (count > 64) { api.gchandle_free(root); return result; }
    for (uintptr_t ix = 0; ix < count; ++ix) {
        int32_t index = (int32_t)ix; void *at[] = {&index};
        Obj *event = invoke(methods.array_get, array, at, false, &ok);
        if (!ok) break;
        if (!usable(event, &ok)) { if (!ok) break; continue; }
        if (++active > 1) { ok = false; break; }
        Obj *module = NULL;
        if (!field_reference(observations.event_system, event, observations.current_input_module, false, &module)) { ok = false; break; }
        /* No EventSystem.current or static SolisInputModule method is invoked:
         * the latter would run its reflection-writing managed .cctor. */
        if (!module) { result = (struct observed_bool){true, false}; continue; }
        void *alive[] = {module};
        bool live = value_bool(invoke(methods.alive, NULL, alive, false, &ok), &ok);
        if (!ok) break;
        if (!live || !api.class_is_assignable_from(observations.input_module, api.object_get_class(module))) {
            result = (struct observed_bool){true, false}; continue;
        }
        result = field_boolean(observations.input_module, module, observations.is_releasing);
    }
    api.gchandle_free(root);
    if (!ok || active != 1) result.available = false;
    return result;
}
static void unavailable_key(struct ui_json *out, const char *key, bool missing, size_t *count) {
    if (!missing) return;
    if ((*count)++) ui_raw(out, ",");
    ui_raw(out, "\""); ui_raw(out, key); ui_raw(out, "\"");
}
static void startup_json(struct ui_json *out) {
    struct observed_bool success = query_boolean(observations.initialization_succeeded, NULL);
    struct observed_bool releasing = input_releasing();
    int32_t content_order = 155; void *content_args[] = {&content_order};
    struct observed_bool blocking = query_boolean(observations.content_blocking, content_args);
    Obj *interceptor = NULL;
    bool interceptor_ok = field_reference(observations.solis_button, NULL, observations.interceptor, true, &interceptor);
    bool titles_ok = observations.title_presenter != NULL, initialized_missing = false, button_missing = false;
    ui_raw(out, ",\"startup_observation\":{\"title_presenters\":");
    Obj *array = NULL; uint32_t array_root = 0;
    uintptr_t count = 0;
    if (titles_ok) {
        Obj *type = api.type_get_object(api.class_get_type(observations.title_presenter)); void *args[] = {type};
        array = invoke(methods.find_all, NULL, args, false, &titles_ok);
        array_root = array ? api.gchandle_new(array, false) : 0;
        titles_ok = titles_ok && array_root != 0;
        if (titles_ok) { count = api.array_length(array); if (count > 8) titles_ok = false; }
    }
    if (!titles_ok) ui_raw(out, "null");
    else {
        size_t list_start = out->length;
        ui_raw(out, "["); size_t emitted = 0;
        for (uintptr_t ix = 0; ix < count; ++ix) {
            int32_t index = (int32_t)ix; void *args[] = {&index}; bool ok = true;
            Obj *presenter = invoke(methods.array_get, array, args, false, &ok);
            if (!ok) { titles_ok = false; break; }
            if (!usable(presenter, &ok)) { if (!ok) { titles_ok = false; break; } continue; }
            int32_t id = object_id(presenter, &ok);
            if (!ok || !id) { titles_ok = false; break; }
            struct observed_bool initialized_value = field_boolean(observations.title_presenter, presenter, observations.title_initialized);
            Obj *view = NULL, *button = NULL;
            bool button_ok = field_reference(observations.title_presenter, presenter, observations.view, false, &view)
                && view && field_reference(observations.title_view, view, observations.title_button, false, &button) && button;
            if (button_ok) { void *alive[] = {button}; button_ok = value_bool(invoke(methods.alive, NULL, alive, false, &ok), &ok); }
            int32_t button_id = button_ok ? object_id(button, &ok) : 0;
            button_ok = button_ok && ok && button_id != 0;
            if (emitted++) ui_raw(out, ",");
            ui_raw(out, "{\"instance_id\":"); ui_number(out, id);
            ui_raw(out, ",\"is_initialized\":"); boolean_json(out, initialized_value);
            ui_raw(out, ",\"title_button_id\":");
            if (button_ok) ui_number(out, button_id); else ui_raw(out, "null");
            ui_raw(out, "}");
            initialized_missing |= !initialized_value.available; button_missing |= !button_ok;
        }
        if (titles_ok) ui_raw(out, "]");
        else {
            out->length = list_start; out->data[list_start] = 0;
            initialized_missing = button_missing = false;
            ui_raw(out, "null");
        }
    }
    if (array_root) api.gchandle_free(array_root);
    ui_raw(out, ",\"solis_initialization_succeeded\":"); boolean_json(out, success);
    ui_raw(out, ",\"click_interceptor_present\":"); boolean_json(out, (struct observed_bool){interceptor_ok, interceptor != NULL});
    ui_raw(out, ",\"input_releasing\":"); boolean_json(out, releasing);
    ui_raw(out, ",\"content_blocking\":"); boolean_json(out, blocking);
    ui_raw(out, ",\"unavailable\":["); size_t missing = 0;
    unavailable_key(out, "callback_registered", callback_observation_missing, &missing);
    unavailable_key(out, "title_presenters", !titles_ok, &missing);
    unavailable_key(out, "title_presenters.is_initialized", initialized_missing, &missing);
    unavailable_key(out, "title_presenters.title_button_id", button_missing, &missing);
    unavailable_key(out, "solis_initialization_succeeded", !success.available, &missing);
    unavailable_key(out, "click_interceptor_present", !interceptor_ok, &missing);
    unavailable_key(out, "input_releasing", !releasing.available, &missing);
    unavailable_key(out, "content_blocking", !blocking.available, &missing);
    ui_raw(out, "]}");
}
static bool button_bounds(Obj *button, struct bounds *out) {
    bool ok = true;
    if (!methods.rect || !methods.vector3 || !methods.canvas || !methods.parent_component || !methods.corners
            || !methods.root_canvas || !methods.render_mode || !methods.camera || !methods.screen_point
            || !methods.screen_width || !methods.screen_height) return false;
    Obj *transform = invoke(methods.transform, button, NULL, false, &ok);
    if (!ok || !transform || !api.class_is_assignable_from(methods.rect, api.object_get_class(transform))) return false;
    Obj *canvas_type = api.type_get_object(api.class_get_type(methods.canvas));
    void *parent_args[] = {canvas_type};
    Obj *canvas = invoke(methods.parent_component, button, parent_args, false, &ok);
    if (!ok || !canvas) return false;
    canvas = invoke(methods.root_canvas, canvas, NULL, false, &ok);
    int32_t mode = value_int(invoke(methods.render_mode, canvas, NULL, false, &ok), &ok);
    Obj *camera = mode == 0 ? NULL : invoke(methods.camera, canvas, NULL, false, &ok);
    if (!ok || (mode != 0 && !camera)) return false;
    int32_t width = value_int(invoke(methods.screen_width, NULL, NULL, false, &ok), &ok);
    int32_t height = value_int(invoke(methods.screen_height, NULL, NULL, false, &ok), &ok);
    if (!ok || width <= 0 || height <= 0 || width > 32768 || height > 32768) return false;
    Obj *corners = api.array_new(methods.vector3, 4);
    uint32_t root = corners ? api.gchandle_new(corners, false) : 0;
    if (!root) return false;
    void *args[] = {corners}; invoke(methods.corners, transform, args, false, &ok);
    float min_x = INFINITY, min_y = INFINITY, max_x = -INFINITY, max_y = -INFINITY;
    for (int32_t i = 0; i < 4 && ok; ++i) {
        void *at[] = {&i}; Obj *boxed = invoke(methods.array_get, corners, at, false, &ok);
        void *value = boxed ? api.object_unbox(boxed) : NULL;
        if (!value) { ok = false; break; }
        Vec3 point; memcpy(&point, value, sizeof(point));
        void *project[] = {camera, &point}; boxed = invoke(methods.screen_point, NULL, project, false, &ok);
        value = boxed ? api.object_unbox(boxed) : NULL;
        if (!value) { ok = false; break; }
        Vec2 screen; memcpy(&screen, value, sizeof(screen));
        if (!isfinite(screen.x) || !isfinite(screen.y)) { ok = false; break; }
        min_x = fminf(min_x, screen.x); max_x = fmaxf(max_x, screen.x);
        min_y = fminf(min_y, screen.y); max_y = fmaxf(max_y, screen.y);
    }
    api.gchandle_free(root);
    min_x = fmaxf(0, min_x); max_x = fminf((float)width, max_x);
    min_y = fmaxf(0, min_y); max_y = fminf((float)height, max_y);
    if (!ok || min_x >= max_x || min_y >= max_y) return false;
    *out = (struct bounds){min_x, height - max_y, max_x, height - min_y,
        {(min_x + max_x) / 2, (min_y + max_y) / 2}};
    return true;
}
static void path_json(struct ui_json *j, Obj *transform, bool *ok) {
    uint16_t path[512]; size_t used = 0; unsigned depth = 0;
    /* Prepend each parent's name; fixed depth and character budget. */
    while (transform && *ok && depth++ < 32) {
        Obj *s = invoke(methods.name, transform, NULL, false, ok);
        int32_t length = s ? api.string_length(s) : 0;
        const uint16_t *p = s ? api.string_chars(s) : NULL;
        if (length < 0 || length > 1048576) { *ok = false; break; }
        size_t n = length > 96 ? 96 : (size_t)length;
        if (n + used + (used ? 1u : 0u) > 512) break;
        memmove(path + n + (used ? 1 : 0), path, used * sizeof(uint16_t));
        if (n && p) memcpy(path, p, n * sizeof(uint16_t));
        if (used) path[n] = '/';
        used += n + (used ? 1 : 0);
        transform = invoke(methods.parent, transform, NULL, false, ok);
    }
    ui_utf16(j, path, used, 512);
}
static bool add_kind(struct ui_json *out, Klass *k, const char *kind, const Method *text_method, bool qua,
                     size_t *node_count, bool *truncated) {
    bool ok = true;
    Obj *type = api.type_get_object(api.class_get_type(k)); void *args[] = {type};
    Obj *array = invoke(methods.find_all, NULL, args, false, &ok);
    if (!ok || !array) return false;
    uint32_t root = api.gchandle_new(array, false); if (!root) return false;
    uintptr_t count = api.array_length(array);
    if (count > ARRAY_LIMIT) { count = ARRAY_LIMIT; *truncated = true; }
    for (uintptr_t ix = 0; ix < count && *node_count < NODE_LIMIT; ++ix) {
        if (now_ms() - snapshot_time > 500) { *truncated = true; break; }
        int32_t index = (int32_t)ix; void *get_args[] = {&index}; ok = true;
        Obj *o = invoke(methods.array_get, array, get_args, false, &ok);
        if (!ok || !usable(o, &ok) || !ok) continue;
        int32_t id = object_id(o, &ok); if (!ok || !id) continue;
        bool button = text_method == NULL;
        const Method *enabled = qua ? methods.qua_enabled : methods.interactable;
        bool interactable = button && value_bool(invoke(enabled, o, NULL, !qua, &ok), &ok);
        Obj *transform = invoke(methods.transform, o, NULL, false, &ok);
        Obj *parent = transform ? invoke(methods.parent, transform, NULL, false, &ok) : NULL;
        int32_t parent_id = parent ? object_id(parent, &ok) : 0;
        int32_t transform_id = transform ? object_id(transform, &ok) : 0;
        Obj *game = invoke(methods.game_object, o, NULL, false, &ok);
        int32_t game_id = game ? object_id(game, &ok) : 0;
        if (!ok) continue;
        size_t before = out->length;
        if (*node_count) ui_raw(out, ",");
        ui_raw(out, "{\"instance_id\":"); ui_number(out, id);
        ui_raw(out, ",\"parent_instance_id\":"); ui_number(out, parent_id);
        ui_raw(out, ",\"transform_instance_id\":"); ui_number(out, transform_id);
        ui_raw(out, ",\"game_object_id\":"); ui_number(out, game_id);
        ui_raw(out, ",\"kind\":\""); ui_raw(out, kind); ui_raw(out, "\",\"name\":");
        Obj *name = invoke(methods.name, o, NULL, false, &ok); string_json(out, name, 128);
        ui_raw(out, ",\"path\":"); path_json(out, transform, &ok);
        ui_raw(out, ",\"text\":");
        Obj *text = text_method ? invoke(text_method, o, NULL, true, &ok) : NULL;
        string_json(out, text, 512);
        ui_raw(out, ",\"active\":true,\"interactable\":"); ui_raw(out, interactable ? "true" : "false");
        ui_raw(out, ",\"bounds\":");
        struct bounds rect;
        if (button_bounds(o, &rect)) {
            char numbers[128]; snprintf(numbers, sizeof(numbers), "[%.2f,%.2f,%.2f,%.2f]", rect.left, rect.top, rect.right, rect.bottom); ui_raw(out, numbers);
        } else ui_raw(out, "null");
        if (button) { ui_raw(out, ",\"button_type\":\""); ui_raw(out, qua ? "qua" : "unity"); ui_raw(out, "\""); }
        if (button && qua) {
            struct observed_bool callback = callback_registered(o);
            ui_raw(out, ",\"callback_registered\":"); boolean_json(out, callback);
            callback_observation_missing |= !callback.available;
        }
        ui_raw(out, "}");
        if (!ok || out->failed || out->length > JSON_LIMIT - 4096) {
            out->length = before; out->data[before] = 0; out->failed = false;
            *truncated = true; break;
        }
        if (button) {
            uint32_t handle = api.gchandle_new(o, false);
            if (!handle) { out->length = before; out->data[before] = 0; *truncated = true; break; }
            buttons[button_count++] = (struct retained){id, handle, qua};
        }
        ++*node_count;
    }
    if (*node_count == NODE_LIMIT) *truncated = true;
    api.gchandle_free(root); return true;
}

JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM *vm, void *reserved) {
    (void)vm; (void)reserved; return JNI_VERSION_1_6;
}
JNIEXPORT jstring JNICALL
Java_game_qualiarts_idolypride_qa_ui_NativeUiBridge_nativeSnapshot(JNIEnv *e, jclass ignored) {
    (void)ignored;
    if (!unity_thread(e)) return error(e, "wrong_thread");
    if (pthread_mutex_trylock(&mutex)) return error(e, "busy");
    if (!initialize()) { pthread_mutex_unlock(&mutex); return error(e, "runtime_not_ready"); }
    if (!api.thread_current()) { pthread_mutex_unlock(&mutex); return error(e, "wrong_runtime_thread"); }
    clear_buttons(); advance(); snapshot_time = now_ms(); callback_observation_missing = false;
    char *buffer = calloc(1, JSON_LIMIT); if (!buffer) { pthread_mutex_unlock(&mutex); return error(e, "allocation_failed"); }
    struct ui_json out = {buffer, JSON_LIMIT, 0, false};
    ui_raw(&out, "{\"ok\":true,\"generation\":"); ui_number(&out, (int64_t)generation);
    bool screen_ok = true;
    int32_t width = value_int(invoke(methods.screen_width, NULL, NULL, false, &screen_ok), &screen_ok);
    int32_t height = value_int(invoke(methods.screen_height, NULL, NULL, false, &screen_ok), &screen_ok);
    ui_raw(&out, ",\"screen\":{\"width\":"); ui_number(&out, screen_ok ? width : 0);
    ui_raw(&out, ",\"height\":"); ui_number(&out, screen_ok ? height : 0);
    ui_raw(&out, ",\"origin\":\"top-left\",\"units\":\"unity-screen-pixels\"}");
    ui_raw(&out, ",\"nodes\":["); size_t nodes = 0; bool truncated = false;
    bool ok = (!methods.qua_button || add_kind(&out, methods.qua_button, "button", NULL, true, &nodes, &truncated))
        && add_kind(&out, methods.button, "button", NULL, false, &nodes, &truncated)
        && add_kind(&out, methods.text, "text", methods.text_value, false, &nodes, &truncated)
        && add_kind(&out, methods.tmp, "tmp_text", methods.tmp_value, false, &nodes, &truncated);
    ui_raw(&out, "]"); startup_json(&out);
    ui_raw(&out, ",\"truncated\":"); ui_raw(&out, truncated ? "true}" : "false}");
    jstring result = NULL;
    if (ok && !out.failed) result = (*e)->NewStringUTF(e, buffer);
    else { clear_buttons(); advance(); result = error(e, "snapshot_failed"); }
    free(buffer); pthread_mutex_unlock(&mutex); return result;
}
JNIEXPORT jstring JNICALL
Java_game_qualiarts_idolypride_qa_ui_NativeUiBridge_nativeClick(JNIEnv *e, jclass ignored, jint id, jlong version) {
    (void)ignored;
    if (!unity_thread(e)) return error(e, "wrong_thread");
    if (pthread_mutex_trylock(&mutex)) return error(e, "busy");
    const char *failure = "stale_generation"; bool ok = false;
    if (!initialized || !api.thread_current()) { failure = "runtime_not_ready"; goto done; }
    if (version <= 0 || (uint64_t)version != generation || now_ms() - snapshot_time > 3000) goto done;
    Obj *button = NULL;
    bool qua = false;
    for (size_t j = 0; j < button_count; ++j) if (buttons[j].id == id) { button = api.gchandle_get_target(buttons[j].handle); qua = buttons[j].qua; break; }
    if (!button) { failure = "node_not_found"; goto done; }
    ok = true;
    if (!usable(button, &ok) || !ok || object_id(button, &ok) != id
            || !value_bool(invoke(qua ? methods.qua_enabled : methods.interactable, button, NULL, !qua, &ok), &ok) || !ok) {
        failure = "node_not_interactable"; ok = false; goto done;
    }
    /* MVP deliberately uses Android input derived from this real UI tree.
     * Direct Unity/Qua handlers can bypass nested handlers or modal interceptors.
     * Do not present a handler invocation as a successful real pointer click. */
    failure = "native_click_disabled_use_adb"; ok = false;
done:
    pthread_mutex_unlock(&mutex);
    return error(e, failure);
}
