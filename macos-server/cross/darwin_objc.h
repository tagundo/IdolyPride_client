#ifndef IDOLY_DARWIN_OBJC_H
#define IDOLY_DARWIN_OBJC_H

/* SDK-free, typed ARM64 Cocoa dispatch. Frameworks are the system frameworks. */
typedef void *IDObj;
typedef void *IDSel;
typedef signed char IDBool;
typedef unsigned long IDSize;
typedef struct { double x, y; } IDPoint;
typedef struct { double width, height; } IDDimensions;
typedef struct { IDPoint origin; IDDimensions size; } IDRect;
typedef struct { IDSize location, length; } IDRange;

extern void *dlopen(const char *, int);
extern void *dlsym(void *, const char *);
extern void *malloc(IDSize);
extern void free(void *);
extern void *memcpy(void *, const void *, IDSize);
extern void *memmove(void *, const void *, IDSize);
extern IDSize strlen(const char *);
extern int strcmp(const char *, const char *);
extern int snprintf(char *, IDSize, const char *, ...);
extern char *setlocale(int, const char *);
extern long read(int, void *, IDSize);
extern long write(int, const void *, IDSize);
extern int open(const char *, int, ...);
extern int close(int);
extern int kill(int, int);
extern void (*signal(int, void (*)(int)))(int);
struct IDPollFD { int fd; short events, revents; };
extern int poll(struct IDPollFD *, unsigned int, int);

static struct {
    void *message;
    IDObj (*getClass)(const char *);
    IDSel (*selector)(const char *);
    IDObj (*allocateClass)(IDObj, const char *, IDSize);
    IDBool (*addMethod)(IDObj, IDSel, void *, const char *);
    void (*registerClass)(IDObj);
    void *(*poolPush)(void);
    void (*poolPop)(void *);
    unsigned long (*typeID)(const void *);
    unsigned long (*booleanTypeID)(void);
} IDRuntime;

static int id_runtime_load(void) {
    void *objc = dlopen("/usr/lib/libobjc.A.dylib", 2);
    if (!objc || !dlopen("/System/Library/Frameworks/Foundation.framework/Foundation", 2)
            || !dlopen("/System/Library/Frameworks/AppKit.framework/AppKit", 2)) return 0;
    IDRuntime.message = dlsym(objc, "objc_msgSend");
    IDRuntime.getClass = (IDObj (*)(const char *))dlsym(objc, "objc_getClass");
    IDRuntime.selector = (IDSel (*)(const char *))dlsym(objc, "sel_registerName");
    IDRuntime.allocateClass = (IDObj (*)(IDObj, const char *, IDSize))dlsym(objc, "objc_allocateClassPair");
    IDRuntime.addMethod = (IDBool (*)(IDObj, IDSel, void *, const char *))dlsym(objc, "class_addMethod");
    IDRuntime.registerClass = (void (*)(IDObj))dlsym(objc, "objc_registerClassPair");
    IDRuntime.poolPush = (void *(*)(void))dlsym(objc, "objc_autoreleasePoolPush");
    IDRuntime.poolPop = (void (*)(void *))dlsym(objc, "objc_autoreleasePoolPop");
    void *core = dlopen("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation", 2);
    IDRuntime.typeID = core ? (unsigned long (*)(const void *))dlsym(core, "CFGetTypeID") : 0;
    IDRuntime.booleanTypeID = core ? (unsigned long (*)(void))dlsym(core, "CFBooleanGetTypeID") : 0;
    return IDRuntime.message && IDRuntime.getClass && IDRuntime.selector && IDRuntime.allocateClass
        && IDRuntime.addMethod && IDRuntime.registerClass && IDRuntime.poolPush && IDRuntime.poolPop
        && IDRuntime.typeID && IDRuntime.booleanTypeID;
}

static IDObj id_class(const char *name) { return IDRuntime.getClass(name); }
static IDSel id_sel(const char *name) { return IDRuntime.selector(name); }
static IDObj id_get(IDObj object, const char *name) {
    return ((IDObj (*)(IDObj, IDSel))IDRuntime.message)(object, id_sel(name));
}
static IDObj id_arg(IDObj object, const char *name, IDObj argument) {
    return ((IDObj (*)(IDObj, IDSel, IDObj))IDRuntime.message)(object, id_sel(name), argument);
}
static IDObj id_index(IDObj object, const char *name, long value) {
    return ((IDObj (*)(IDObj, IDSel, long))IDRuntime.message)(object, id_sel(name), value);
}
static IDObj id_double(IDObj object, const char *name, double value) {
    return ((IDObj (*)(IDObj, IDSel, double))IDRuntime.message)(object, id_sel(name), value);
}
static void id_void(IDObj object, const char *name) {
    ((void (*)(IDObj, IDSel))IDRuntime.message)(object, id_sel(name));
}
static void id_set(IDObj object, const char *name, IDObj value) {
    ((void (*)(IDObj, IDSel, IDObj))IDRuntime.message)(object, id_sel(name), value);
}
static void id_set_long(IDObj object, const char *name, long value) {
    ((void (*)(IDObj, IDSel, long))IDRuntime.message)(object, id_sel(name), value);
}
static void id_set_bool(IDObj object, const char *name, IDBool value) {
    ((void (*)(IDObj, IDSel, IDBool))IDRuntime.message)(object, id_sel(name), value);
}
static void id_set_selector(IDObj object, const char *name, IDSel value) {
    ((void (*)(IDObj, IDSel, IDSel))IDRuntime.message)(object, id_sel(name), value);
}
static long id_long(IDObj object, const char *name) {
    return ((long (*)(IDObj, IDSel))IDRuntime.message)(object, id_sel(name));
}
static long long id_int64(IDObj object, const char *name) {
    return ((long long (*)(IDObj, IDSel))IDRuntime.message)(object, id_sel(name));
}
static int id_int(IDObj object, const char *name) {
    return ((int (*)(IDObj, IDSel))IDRuntime.message)(object, id_sel(name));
}
static double id_number(IDObj object, const char *name) {
    return ((double (*)(IDObj, IDSel))IDRuntime.message)(object, id_sel(name));
}
static IDBool id_bool(IDObj object, const char *name) {
    return ((IDBool (*)(IDObj, IDSel))IDRuntime.message)(object, id_sel(name));
}
static IDBool id_bool_arg(IDObj object, const char *name, IDObj value) {
    return ((IDBool (*)(IDObj, IDSel, IDObj))IDRuntime.message)(object, id_sel(name), value);
}
static IDBool id_is(IDObj object, const char *name) {
    return object && ((IDBool (*)(IDObj, IDSel, IDObj))IDRuntime.message)(object, id_sel("isKindOfClass:"), id_class(name));
}
static IDObj id_string(const char *text) {
    IDObj result = ((IDObj (*)(IDObj, IDSel, const char *))IDRuntime.message)(id_class("NSString"),
        id_sel("stringWithUTF8String:"), text ? text : "");
    return result ? result : ((IDObj (*)(IDObj, IDSel, const char *))IDRuntime.message)(id_class("NSString"),
        id_sel("stringWithUTF8String:"), "[문자 인코딩 오류]");
}
static const char *id_utf8(IDObj string) {
    const char *value = id_is(string, "NSString") ? ((const char *(*)(IDObj, IDSel))IDRuntime.message)(string, id_sel("UTF8String")) : 0;
    return value ? value : "";
}
static IDObj id_keep(IDObj object) { return id_get(object, "retain"); }
static IDObj id_item(IDObj object, const char *key) {
    return id_is(object, "NSDictionary") ? id_arg(object, "objectForKey:", id_string(key)) : 0;
}
static long long id_json_integer(IDObj object, long long fallback) {
    if (!id_is(object, "NSNumber") || IDRuntime.typeID(object) == IDRuntime.booleanTypeID()) return fallback;
    const char *type = ((const char *(*)(IDObj, IDSel))IDRuntime.message)(object, id_sel("objCType"));
    if (!type || type[0] == 'f' || type[0] == 'd') return fallback;
    return id_int64(object, "longLongValue");
}
static IDObj id_array(const IDObj *values, IDSize count) {
    return ((IDObj (*)(IDObj, IDSel, const IDObj *, IDSize))IDRuntime.message)(id_class("NSArray"),
        id_sel("arrayWithObjects:count:"), values, count);
}
static IDObj id_data(const void *bytes, IDSize count) {
    return ((IDObj (*)(IDObj, IDSel, const void *, IDSize))IDRuntime.message)(id_class("NSData"),
        id_sel("dataWithBytes:length:"), bytes, count);
}
static IDObj id_json(IDObj data) {
    return ((IDObj (*)(IDObj, IDSel, IDObj, unsigned long, IDObj *))IDRuntime.message)(id_class("NSJSONSerialization"),
        id_sel("JSONObjectWithData:options:error:"), data, 0, 0);
}
static IDRect id_rect(double x, double y, double width, double height) {
    IDRect value = {{x, y}, {width, height}}; return value;
}
static IDObj id_init_frame(IDObj object, IDRect frame) {
    return ((IDObj (*)(IDObj, IDSel, IDRect))IDRuntime.message)(object, id_sel("initWithFrame:"), frame);
}
static void id_frame(IDObj object, IDRect frame) {
    ((void (*)(IDObj, IDSel, IDRect))IDRuntime.message)(object, id_sel("setFrame:"), frame);
}

#endif
