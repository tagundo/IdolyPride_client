#import "IdolyEmbeddedServer.h"
#import "IdolyNativeUI.h"
#import "IdolyHTTP.h"
#import "IdolyClientData.h"
#import "GatePolicy.h"
#if !IDOLY_SMOKE_SIMULATOR
#import "UnityStartupProfile.h"
#endif
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import <CommonCrypto/CommonCryptor.h>
#include <Python.h>
#include <stdatomic.h>
#include <dlfcn.h>
#include <mach-o/loader.h>

static const NSUInteger IDJSONLimit = 65536;
static IDGate gate;
static IMP originalStartUnity;
static _Atomic(IMP) originalKeyboardTextField;
static atomic_bool unityKeyboardReady;
static BOOL keyboardGuardInstalled;
static id savedController, savedApplication;
static SEL startSelector;
static NSString *hookError, *lastError, *lastGameError, *dataDirectory;
static BOOL recovering;
static BOOL hookInstalled;
static atomic_bool pythonReady;
static PyObject *hostModule;
static PyThreadState *pythonThread;

// One persistent native thread owns interpreter initialization and all control
// calls. Serving Python threads are created by app_runtime, never by UIKit.
@interface IDServerWorker : NSObject
@property (nonatomic,strong) NSCondition *condition;
@property (nonatomic,strong) NSMutableArray *tasks;
@property (nonatomic,strong) NSThread *thread;
- (void)enqueue:(void (^)(void))block;
- (void)run;
@end
@implementation IDServerWorker
- (instancetype)init {
    if ((self = [super init])) {
        _condition = [NSCondition new]; _tasks = [NSMutableArray new];
        _thread = [[NSThread alloc] initWithTarget:self selector:@selector(run) object:nil];
        _thread.name = @"idoly-embedded-server"; [_thread start];
    }
    return self;
}
- (void)enqueue:(void (^)(void))block {
    [_condition lock]; [_tasks addObject:[block copy]]; [_condition signal]; [_condition unlock];
}
- (void)run {
    for (;;) {
        @autoreleasepool {
            [_condition lock];
            while (!_tasks.count) [_condition wait];
            void (^task)(void) = _tasks[0]; [_tasks removeObjectAtIndex:0]; [_condition unlock];
            task();
        }
    }
}
@end
static IDServerWorker *worker;

static NSString *JSON(id object) {
    NSData *raw = [NSJSONSerialization dataWithJSONObject:object options:0 error:NULL];
    return raw && raw.length <= IDJSONLimit ? [[NSString alloc] initWithData:raw encoding:NSUTF8StringEncoding] : nil;
}
static NSString *failureReply(NSString *code, NSString *message) {
    return JSON(@{@"ok":@NO, @"error":@{@"code":code, @"message":message ?: @"서버 오류"}});
}
static NSString *pythonFailure(void) {
    PyObject *type = NULL, *value = NULL, *trace = NULL;
    PyErr_Fetch(&type, &value, &trace); PyErr_NormalizeException(&type, &value, &trace);
    PyObject *text = value ? PyObject_Str(value) : NULL;
    const char *raw = text ? PyUnicode_AsUTF8(text) : NULL;
    NSString *message = raw ? [NSString stringWithUTF8String:raw] : @"Python 서버 초기화에 실패했습니다.";
    Py_XDECREF(text); Py_XDECREF(type); Py_XDECREF(value); Py_XDECREF(trace); PyErr_Clear();
    return message.length > 2000 ? [message substringToIndex:2000] : message;
}
static PyObject *aesCBC(PyObject *self, PyObject *args) {
    (void)self;
    PyObject *encrypt; Py_buffer key = {0}, iv = {0}, data = {0};
    if (!PyArg_ParseTuple(args, "Oy*y*y*:aes_cbc", &encrypt, &key, &iv, &data)) return NULL;
    PyObject *result = NULL;
    if (!PyBool_Check(encrypt) || (key.len != 16 && key.len != 24 && key.len != 32) || iv.len != 16
            || data.len < 0 || data.len > 16*1024*1024 || data.len % 16) {
        PyErr_SetString(PyExc_ValueError, "AES-CBC requires bool, AES key, 16-byte IV, and bounded aligned data");
    } else {
        result = PyBytes_FromStringAndSize(NULL, data.len);
        if (result) {
            size_t written = 0; CCCryptorStatus status;
            char *output = PyBytes_AS_STRING(result);
            Py_BEGIN_ALLOW_THREADS
            status = CCCrypt(encrypt == Py_True ? kCCEncrypt : kCCDecrypt, kCCAlgorithmAES, 0,
                             key.buf, (size_t)key.len, iv.buf, data.buf, (size_t)data.len,
                             output, (size_t)data.len, &written);
            Py_END_ALLOW_THREADS
            if (status != kCCSuccess || written != (size_t)data.len) {
                Py_CLEAR(result); PyErr_SetString(PyExc_ValueError, "CommonCrypto AES-CBC failed");
            }
        }
    }
    PyBuffer_Release(&key); PyBuffer_Release(&iv); PyBuffer_Release(&data); return result;
}
static PyObject *postEvent(PyObject *self, PyObject *arg) {
    (void)self; Py_ssize_t size = 0;
    const char *raw = PyUnicode_AsUTF8AndSize(arg, &size);
    if (!raw) return NULL;
    if (size < 1 || size > (Py_ssize_t)IDJSONLimit) {
        PyErr_SetString(PyExc_ValueError, "Native event exceeds 64 KiB"); return NULL;
    }
    NSString *event = [[NSString alloc] initWithBytes:raw length:(NSUInteger)size encoding:NSUTF8StringEncoding];
    IDNativeEvent(event); Py_RETURN_NONE;
}
static PyMethodDef methods[] = {
    {"aes_cbc", aesCBC, METH_VARARGS, "AES-CBC without padding; codec owns PKCS7."},
    {"open_url", (PyCFunction)(void (*)(void))IDOpenURL, METH_VARARGS|METH_KEYWORDS, "Bounded OS-trusted HTTPS response."},
    {"post_event", postEvent, METH_O, "Deliver one bounded event to the open settings screen."},
    {NULL, NULL, 0, NULL}
};
static struct PyModuleDef module = {PyModuleDef_HEAD_INIT, "_idoly_ios", NULL, -1, methods};
PyMODINIT_FUNC PyInit__idoly_ios(void) {
    if (IDHTTPPrepareTypes() < 0) return NULL;
    return PyModule_Create(&module);
}
static BOOL configString(PyConfig *config, wchar_t **field, NSString *value, NSString **error) {
    PyStatus status = PyConfig_SetBytesString(config, field, value.fileSystemRepresentation);
    if (PyStatus_Exception(status)) { *error = @"Python 경로 설정에 실패했습니다."; return NO; }
    return YES;
}
static BOOL initializePython(NSString *app, NSString **error) {
    if (atomic_load(&pythonReady)) return YES;
    if (Py_IsInitialized()) { *error = @"다른 Python 인터프리터가 이미 실행 중입니다."; return NO; }
    if (PyImport_AppendInittab("_idoly_ios", PyInit__idoly_ios) < 0) {
        *error = @"iOS 서버 모듈을 등록하지 못했습니다."; return NO;
    }
    PyConfig config; PyConfig_InitIsolatedConfig(&config);
    config.install_signal_handlers = 0; config.use_environment = 0;
    config.site_import = 0; config.user_site_directory = 0; config.write_bytecode = 0;
    config.parse_argv = 0; config.safe_path = 1; config.module_search_paths_set = 1;
    BOOL good = configString(&config, &config.program_name, @"IdolyEmbeddedServer", error);
    // Python's AppleFrameworkLoader resolves .fwork paths relative to the app
    // executable, not to Python.framework or an invented program-name path.
    if (good) good = configString(&config, &config.executable, NSBundle.mainBundle.executablePath, error);
    if (good) good = configString(&config, &config.base_executable, NSBundle.mainBundle.executablePath, error);
    NSString *stdlib = [app stringByAppendingPathComponent:@"python-stdlib"];
    NSArray<NSString *> *paths = @[[app stringByAppendingPathComponent:@"LocalServer/python"], stdlib,
                                    [stdlib stringByAppendingPathComponent:@"lib-dynload"]];
    for (NSString *path in paths) {
        if (!good) break;
        wchar_t *wide = Py_DecodeLocale(path.fileSystemRepresentation, NULL);
        if (!wide) { *error = @"Python 경로의 문자를 변환하지 못했습니다."; good = NO; break; }
        PyStatus status = PyWideStringList_Append(&config.module_search_paths, wide); PyMem_RawFree(wide);
        if (PyStatus_Exception(status)) { *error = @"Python 검색 경로를 준비하지 못했습니다."; good = NO; }
    }
    if (good) {
        PyStatus status = Py_InitializeFromConfig(&config);
        if (PyStatus_Exception(status)) {
            *error = status.err_msg ? [NSString stringWithUTF8String:status.err_msg] : @"Python 초기화 실패";
            good = NO;
        }
    }
    PyConfig_Clear(&config);
    if (!good) return NO;
    // Set protobuf before any idoly/protobuf import, independent of environment.
    PyObject *os = PyImport_ImportModule("os"), *env = os ? PyObject_GetAttrString(os, "environ") : NULL;
    PyObject *key = PyUnicode_FromString("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION");
    PyObject *value = PyUnicode_FromString("python");
    good = env && key && value && PyObject_SetItem(env, key, value) == 0;
    Py_XDECREF(os); Py_XDECREF(env); Py_XDECREF(key); Py_XDECREF(value);
    if (good) hostModule = PyImport_ImportModule("idoly_local.ios_host");
    good = good && hostModule != NULL;
    if (!good) *error = pythonFailure();
    // The interpreter is process-lifetime. It is never finalized while any game
    // or serving thread can still use it; a failed import may be retried safely.
    pythonThread = PyEval_SaveThread(); atomic_store(&pythonReady, true);
    return good;
}
static NSString *callHost(const char *name, NSString *argument, NSString **error) {
    NSCAssert(![NSThread isMainThread], @"Python must run on its serial native worker");
    if (!pythonThread) { *error = @"Python 서버가 준비되지 않았습니다."; return nil; }
    PyEval_RestoreThread(pythonThread); pythonThread = NULL;
    if (!hostModule) hostModule = PyImport_ImportModule("idoly_local.ios_host");
    PyObject *reply = NULL;
    if (hostModule) {
        if (argument) reply = PyObject_CallMethod(hostModule, name, "s", argument.UTF8String);
        else reply = PyObject_CallMethod(hostModule, name, NULL);
    }
    NSString *result = nil;
    if (reply) {
        if (PyUnicode_Check(reply)) {
            Py_ssize_t count; const char *raw = PyUnicode_AsUTF8AndSize(reply, &count);
            if (raw && count >= 0 && count <= (Py_ssize_t)IDJSONLimit)
                result = [[NSString alloc] initWithBytes:raw length:(NSUInteger)count encoding:NSUTF8StringEncoding];
        } else {
            PyObject *json = PyImport_ImportModule("json");
            PyObject *encoded = json ? PyObject_CallMethod(json, "dumps", "O", reply) : NULL;
            if (encoded) {
                Py_ssize_t count; const char *raw = PyUnicode_AsUTF8AndSize(encoded, &count);
                if (raw && count >= 0 && count <= (Py_ssize_t)IDJSONLimit)
                    result = [[NSString alloc] initWithBytes:raw length:(NSUInteger)count encoding:NSUTF8StringEncoding];
            }
            Py_XDECREF(encoded); Py_XDECREF(json);
        }
        Py_DECREF(reply);
    }
    if (!result) *error = PyErr_Occurred() ? pythonFailure() : @"서버 응답이 64 KiB를 초과했습니다.";
    pythonThread = PyEval_SaveThread(); return result;
}
static id guardedUnityKeyboardTextField(id self, SEL selector) {
    // UIKit/PlayCover can query the Unity field while our WK launcher is open.
    // The original getter lazily creates KeyboardDelegate, but Unity's later
    // +Initialize asserts that it has not been created yet (Keyboard.mm:260).
    // Keep internal initialization untouched; expose the original field only
    // after the complete original initialization call has returned.
    if (!atomic_load(&unityKeyboardReady)) return nil;
    IMP original = atomic_load(&originalKeyboardTextField);
    return original ? ((id (*)(id, SEL))original)(self, selector) : nil;
}
static void forwardUnityIfVisible(void) {
    NSCAssert(NSThread.isMainThread, @"Unity startup belongs to main thread");
    if (!IDGateForwardVisible(&gate, UIApplication.sharedApplication.applicationState == UIApplicationStateBackground)) return;
    lastError = nil; lastGameError = nil; IDNativeDismissFailure();
    IDNativeSetServerState(YES, NO, @"서버 실행 중");
    IDNativeSetGameStartAvailable(NO);
    IDNativeHideLauncher();
    id controller = savedController, application = savedApplication;
    savedController = nil; savedApplication = nil;
    ((void (*)(id, SEL, id))originalStartUnity)(controller, startSelector, application);
    atomic_store(&unityKeyboardReady, true);
}
static void beginServer(void) {
    NSCAssert([NSThread isMainThread], @"Gate state belongs to main thread");
    if (!IDGateBegin(&gate)) return;
    lastError = nil; lastGameError = nil; IDNativeDismissFailure();
    IDNativeSetServerState(NO, YES, @"서버를 준비하고 있습니다…");
    if (!worker) worker = [IDServerWorker new];
    [worker enqueue:^{
        NSString *error = nil, *app = NSBundle.mainBundle.bundlePath;
        NSString *interfaceLanguage = @"system";
        NSFileManager *fm = NSFileManager.defaultManager;
        NSURL *support = [[fm URLsForDirectory:NSApplicationSupportDirectory inDomains:NSUserDomainMask] firstObject];
        NSURL *documents = [[fm URLsForDirectory:NSDocumentDirectory inDomains:NSUserDomainMask] firstObject];
        NSString *data = [[support URLByAppendingPathComponent:@"IdolyPrideLocal" isDirectory:YES] path];
        NSString *resources = [[documents URLByAppendingPathComponent:@"IdolyPride" isDirectory:YES] path];
        @synchronized (IDServerWorker.class) { dataDirectory = data; }
        BOOL good = data && resources && initializePython(app, &error);
        if (good) {
            PyEval_RestoreThread(pythonThread); pythonThread = NULL;
            if (!hostModule) hostModule = PyImport_ImportModule("idoly_local.ios_host");
            PyObject *reply = hostModule ? PyObject_CallMethod(hostModule, "start", "sss",
                [app stringByAppendingPathComponent:@"LocalServer"].fileSystemRepresentation,
                data.fileSystemRepresentation, resources.fileSystemRepresentation) : NULL;
            PyObject *running = reply && PyDict_Check(reply) ? PyDict_GetItemString(reply, "running") : NULL;
            PyObject *state = reply && PyDict_Check(reply) ? PyDict_GetItemString(reply, "state") : NULL;
            good = running == Py_True && state && PyUnicode_Check(state)
                && PyUnicode_CompareWithASCIIString(state, "ready") == 0;
            PyObject *options = reply && PyDict_Check(reply) ? PyDict_GetItemString(reply, "options") : NULL;
            PyObject *locale = options && PyDict_Check(options) ? PyDict_GetItemString(options, "interface_language") : NULL;
            if (locale && PyUnicode_Check(locale)) {
                const char *name = PyUnicode_AsUTF8(locale);
                if (name) interfaceLanguage = [NSString stringWithUTF8String:name];
            }
            if (!good) error = PyErr_Occurred() ? pythonFailure() : @"로컬 서버가 준비 완료 상태를 보고하지 않았습니다.";
            Py_XDECREF(reply); pythonThread = PyEval_SaveThread();
        }
        dispatch_async(dispatch_get_main_queue(), ^{
            if (good && IDGateSucceeded(&gate)) {
                IDNativeSetInterfaceLanguage(interfaceLanguage);
                lastError = nil; IDNativeDismissFailure();
                IDNativeSetServerState(YES, NO, @"서버 실행 중");
            } else if (!good && IDGateFailedAttempt(&gate)) {
                lastError = error ?: @"서버 시작 실패";
                IDNativeSetServerState(NO, NO, @"서버를 시작하지 못했습니다");
                IDNativeStartupFailure(lastError);
            }
        });
    }];
}
static void recoverForeground(void) {
    if ((gate.phase != IDGateRunning && gate.phase != IDGateReady) || !atomic_load(&pythonReady) || recovering) return;
    recovering = YES;
    IDNativeSetServerState(YES, YES, @"서버 연결을 확인하고 있습니다…");
    [worker enqueue:^{
        NSString *error = nil, *reply = callHost("foreground", nil, &error);
        NSData *bytes = [reply dataUsingEncoding:NSUTF8StringEncoding];
        NSDictionary *status = bytes ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:NULL] : nil;
        if (!error && (![status isKindOfClass:NSDictionary.class] || ![status[@"running"] isEqual:@YES]))
            error = @"로컬 서버 연결을 복구하지 못했습니다. 게임을 다시 열어 주세요.";
        dispatch_async(dispatch_get_main_queue(), ^{
            recovering = NO;
            if (error) { lastError = error; IDGateServerUnavailable(&gate); IDNativeSetServerState(NO, NO, @"서버 연결 확인 실패"); IDNativeStartupFailure(error); }
            else { lastError = nil; IDNativeDismissFailure(); IDNativeSetServerState(YES, NO, @"서버 실행 중"); }
        });
    }];
}
static void deferredStart(id self, SEL selector, id application) {
    // Capture initialization before NoGraphics loads localized client data.
    // Unexpected cross-thread calls
    // are queued instead of touching Unity or waiting on the Python worker.
    void (^capture)(void) = ^{
        if (!IDGateCapture(&gate)) return;
        savedController = self; savedApplication = application; startSelector = selector;
        IDNativeSetGameStartAvailable(hookInstalled && gate.captured);
        IDNativeShowLauncher();
        beginServer();
    };
    if (NSThread.isMainThread) capture(); else dispatch_async(dispatch_get_main_queue(), capture);
}
static BOOL exactType(Method method, unsigned index, const char *expected) {
    char *type = method_copyArgumentType(method, index); BOOL matches = type && !strcmp(type, expected);
    free(type); return matches;
}
static BOOL auditedUnityEntry(IMP implementation, unsigned long rva, const void *prefix, size_t prefixSize) {
#if IDOLY_SMOKE_SIMULATOR
    (void)implementation; (void)rva; (void)prefix; (void)prefixSize;
    return YES; // The explicit simulator probe owns a fake Unity class.
#else
    Dl_info image = {0};
    if (!dladdr((const void *)implementation, &image) || !image.dli_fbase || !image.dli_fname) return NO;
    const char *suffix = "/UnityFramework.framework/UnityFramework";
    size_t pathSize = strlen(image.dli_fname), suffixSize = strlen(suffix);
    if (pathSize < suffixSize || strcmp(image.dli_fname+pathSize-suffixSize,suffix)) return NO;
    const struct mach_header_64 *header = image.dli_fbase;
    if (header->magic != MH_MAGIC_64 || header->cputype != CPU_TYPE_ARM64 || header->ncmds > 256 || header->sizeofcmds > 65536) return NO;
    const unsigned char *cursor = (const unsigned char *)(header+1), *end = cursor+header->sizeofcmds;
    BOOL uuidMatches = NO;
    for (unsigned i=0; i<header->ncmds; ++i) {
        if ((size_t)(end-cursor) < sizeof(struct load_command)) return NO;
        const struct load_command *command = (const void *)cursor;
        if (command->cmdsize < sizeof(*command) || command->cmdsize > (size_t)(end-cursor)) return NO;
        if (command->cmd == LC_UUID && command->cmdsize == sizeof(struct uuid_command))
            uuidMatches = !memcmp(((const struct uuid_command *)command)->uuid,IDUnityUUID,16);
        cursor += command->cmdsize;
    }
    return cursor == end && uuidMatches
        && (const unsigned char *)implementation == (const unsigned char *)header+rva
        && !memcmp((const void *)implementation,prefix,prefixSize);
#endif
}
static BOOL auditedInitialization(IMP implementation) {
#if IDOLY_SMOKE_SIMULATOR
    return auditedUnityEntry(implementation, 0, NULL, 0);
#else
    return auditedUnityEntry(implementation, IDUnityStartRVA, IDUnityStartPrefix, sizeof IDUnityStartPrefix);
#endif
}
static BOOL selectClientData(NSDictionary *prepared, NSString *effectiveLanguage, NSString **error) {
    NSString *language = [prepared[@"language"] isKindOfClass:NSString.class] ? prepared[@"language"] : nil;
    if (![prepared[@"schema"] isEqual:@1] || ![prepared[@"bundle_id"] isEqual:@"local.idoly.client-data"]
            || ![@[@"ko", @"ja", @"en"] containsObject:language ?: @""] || ![language isEqual:effectiveLanguage]) {
        *error = @"서버와 게임의 언어 데이터가 일치하지 않습니다."; return NO;
    }
    NSString *path = [prepared[@"bundle_path"] isKindOfClass:NSString.class] ? prepared[@"bundle_path"] : nil;
    NSString *root = [IDNativeDataDirectory() stringByAppendingPathComponent:@"client-data"];
    if (!path || !root || ![path.lastPathComponent isEqual:[language stringByAppendingString:@".bundle"]]) {
        *error = @"게임 언어 데이터가 준비되지 않았습니다."; return NO;
    }
    Class cls = objc_getClass("UnityFramework"); SEL getter = sel_registerName("getInstance");
    SEL setter = sel_registerName("setDataBundleId:");
    Method get = cls ? class_getClassMethod(cls, getter) : NULL;
    Method set = cls ? class_getInstanceMethod(cls, setter) : NULL;
    char *ret = get ? method_copyReturnType(get) : NULL;
    BOOL valid = get && set && ret && !strcmp(ret, "@") && method_getNumberOfArguments(get) == 2
        && exactType(get, 0, "@") && exactType(get, 1, ":");
    free(ret);
#if !IDOLY_SMOKE_SIMULATOR
    valid = valid && auditedUnityEntry(method_getImplementation(get), IDUnityGetInstanceRVA,
        IDUnityGetInstancePrefix, sizeof IDUnityGetInstancePrefix)
        && auditedUnityEntry(method_getImplementation(set), IDUnitySetDataRVA,
            IDUnitySetDataPrefix, sizeof IDUnitySetDataPrefix);
#endif
    if (!valid) { *error = @"이 게임의 언어 데이터 진입점을 확인하지 못했습니다."; return NO; }
    id framework = ((id (*)(id, SEL))method_getImplementation(get))((id)cls, getter);
    if (!framework || object_getClass(framework) != cls) { *error = @"게임 데이터 컨트롤러를 확인하지 못했습니다."; return NO; }
    NSError *nativeError = nil;
    BOOL selected = IDClientDataSelectBundle([NSURL fileURLWithPath:path isDirectory:YES],
        [NSURL fileURLWithPath:root isDirectory:YES], framework, &nativeError);
    if (!selected) *error = nativeError.localizedDescription ?: @"게임 언어 데이터를 선택하지 못했습니다.";
    return selected;
}
static void installGate(void) {
    Class cls = objc_getClass("UnityAppController"); SEL selector = sel_registerName("initUnityWithApplication:");
    Method target = NULL; unsigned count = 0;
    Method *methods = cls ? class_copyMethodList(cls, &count) : NULL;
    for (unsigned i = 0; i < count; ++i) if (method_getName(methods[i]) == selector) target = methods[i];
    free(methods);
    char *ret = target ? method_copyReturnType(target) : NULL;
    BOOL valid = cls && target && method_getNumberOfArguments(target) == 3 && ret && !strcmp(ret, "v")
        && exactType(target, 0, "@") && exactType(target, 1, ":") && exactType(target, 2, "@")
        && auditedInitialization(method_getImplementation(target));
    free(ret);
    if (!valid) { hookError = @"이 게임의 Unity 초기화 진입점을 확인하지 못했습니다. 서버는 독립적으로 시작합니다."; return; }
    Class framework = objc_getClass("UnityFramework");
    SEL keyboardSelector = sel_registerName("keyboardTextField");
    Method keyboard = framework ? class_getInstanceMethod(framework, keyboardSelector) : NULL;
    char *keyboardReturn = keyboard ? method_copyReturnType(keyboard) : NULL;
    BOOL keyboardValid = keyboard && method_getNumberOfArguments(keyboard) == 2
        && keyboardReturn && !strcmp(keyboardReturn, "@")
        && exactType(keyboard, 0, "@") && exactType(keyboard, 1, ":");
    free(keyboardReturn);
#if !IDOLY_SMOKE_SIMULATOR
    keyboardValid = keyboardValid && auditedUnityEntry(method_getImplementation(keyboard),
        IDUnityKeyboardFieldRVA, IDUnityKeyboardFieldPrefix, sizeof IDUnityKeyboardFieldPrefix);
#endif
    if (!keyboardValid) {
        hookError = @"이 게임의 Unity 키보드 진입점을 확인하지 못했습니다. 서버는 독립적으로 시작합니다.";
        return;
    }
    atomic_store(&originalKeyboardTextField, method_getImplementation(keyboard));
    IMP previousKeyboard = method_setImplementation(keyboard, (IMP)guardedUnityKeyboardTextField);
    keyboardGuardInstalled = previousKeyboard != NULL;
    if (!keyboardGuardInstalled) {
        atomic_store(&originalKeyboardTextField, NULL);
        hookError = @"Unity 키보드 초기화 보호를 연결하지 못했습니다."; return;
    }
    atomic_store(&originalKeyboardTextField, previousKeyboard);
    originalStartUnity = method_setImplementation(target, (IMP)deferredStart);
    hookInstalled = originalStartUnity != NULL;
    if (!hookInstalled) {
        method_setImplementation(keyboard, previousKeyboard);
        atomic_store(&originalKeyboardTextField, NULL); keyboardGuardInstalled = NO;
        hookError = @"Unity 시작 진입점을 연결하지 못했습니다.";
    }
}
NSString *IDNativeDataDirectory(void) {
    @synchronized (IDServerWorker.class) { return dataDirectory; }
}
NSString *IdolyEmbeddedServerStatusJSON(void) {
    __block NSString *result;
    void (^read)(void) = ^{ result = JSON(@{@"schema":@1, @"hook_installed":@(hookInstalled),
        @"keyboard_guard_installed":@(keyboardGuardInstalled), @"keyboard_ready":@(atomic_load(&unityKeyboardReady)),
        @"phase":@(gate.phase), @"captured":@(gate.captured), @"forwarded":@(gate.forwarded),
        @"attempts":@(gate.attempts), @"python_initialized":@(atomic_load(&pythonReady)),
        @"launch_requested":@((BOOL)gate.launch_requested), @"launch_prepared":@((BOOL)gate.launch_prepared),
        @"launcher_visible":@(IDNativeLauncherVisible()),
        @"game_hook_error":hookError ?: (id)NSNull.null,
        @"game_error":lastGameError ?: (id)NSNull.null, @"client_data":IDClientDataSelectionInfo(),
        @"error":lastError ?: (id)NSNull.null}); };
    if (NSThread.isMainThread) read(); else dispatch_sync(dispatch_get_main_queue(), read);
    return result;
}
void IdolyEmbeddedServerRetry(void) {
    dispatch_async(dispatch_get_main_queue(), ^{
        if (gate.phase == IDGateReady) {
            if (gate.captured) IDNativeShowLauncher();
            recoverForeground();
        }
        else if (gate.phase == IDGateRunning) recoverForeground();
        else beginServer();
    });
}
void IdolyEmbeddedServerLaunchGame(void) {
    void (^request)(void) = ^{
        if (!worker || !atomic_load(&pythonReady) || !IDGateRequestLaunch(&gate)) return;
        lastGameError = nil;
        IDNativeSetServerState(YES, YES, @"게임 데이터와 선택한 언어를 준비하고 있습니다…");
        [worker enqueue:^{
            // Prepare the selected immutable data before Unity initializes.
            NSString *error = nil, *reply = callHost("prepare_game_start", nil, &error);
            NSData *bytes = [reply dataUsingEncoding:NSUTF8StringEncoding];
            id status = bytes ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:NULL] : nil;
            BOOL ready = !error && [status isKindOfClass:NSDictionary.class]
                && [status[@"running"] isEqual:@YES] && [status[@"state"] isEqual:@"ready"];
            BOOL serving = ready;
            if (!ready) {
                NSString *healthError = nil, *health = callHost("readiness", nil, &healthError);
                id observed = health ? [NSJSONSerialization JSONObjectWithData:[health dataUsingEncoding:NSUTF8StringEncoding] options:0 error:NULL] : nil;
                serving = !healthError && [observed isKindOfClass:NSDictionary.class] && [observed[@"running"] isEqual:@YES];
            }
            dispatch_async(dispatch_get_main_queue(), ^{
                NSString *selectionError = nil;
                id effective = ready ? status[@"effective_options"] : nil;
                NSString *language = [effective isKindOfClass:NSDictionary.class]
                    && [effective[@"language"] isKindOfClass:NSString.class] ? effective[@"language"] : nil;
                BOOL selected = ready && [status[@"client_data"] isKindOfClass:NSDictionary.class]
                    && selectClientData(status[@"client_data"], language, &selectionError);
                if (selected && IDGatePreparedLaunch(&gate)) forwardUnityIfVisible();
                else if (!selected && IDGateLaunchFailed(&gate)) {
                    lastGameError = error ?: selectionError ?: @"게임 시작을 준비하지 못했습니다. 다시 시도해 주세요.";
                    if (!serving) IDGateServerUnavailable(&gate);
                    IDNativeSetServerState(serving, NO, serving ? @"서버 실행 중 · 게임 데이터 준비 실패" : @"서버 연결 확인 실패");
                    IDNativeStartupFailure(lastGameError);
                }
            });
        }];
    };
    if (NSThread.isMainThread) request(); else dispatch_async(dispatch_get_main_queue(), request);
}
void IdolyEmbeddedServerCommand(NSString *request, void (^completion)(NSString *)) {
    void (^dispatchRequest)(void) = ^{
        NSData *raw = [request dataUsingEncoding:NSUTF8StringEncoding];
        id decoded = raw && raw.length <= IDJSONLimit ? [NSJSONSerialization JSONObjectWithData:raw options:0 error:NULL] : nil;
        NSDictionary *object = [decoded isKindOfClass:NSDictionary.class] ? decoded : nil;
        NSNumber *identifier = [object[@"id"] isKindOfClass:NSNumber.class] ? object[@"id"] : nil;
        if (identifier && (CFGetTypeID((__bridge CFTypeRef)identifier) == CFBooleanGetTypeID()
                || identifier.longLongValue < 1 || identifier.longLongValue > INT32_MAX)) identifier = nil;
        NSString *(^failure)(NSString *, NSString *) = ^NSString *(NSString *code, NSString *message) {
            return JSON(@{@"id":identifier ?: (id)NSNull.null, @"ok":@NO,
                @"error":@{@"code":code, @"message":message ?: @"서버 오류"}});
        };
        if (!raw || raw.length > IDJSONLimit || !object || !identifier) {
            completion(failure(@"invalid_request", @"설정 요청 형식이 올바르지 않습니다.")); return;
        }
        if ([object[@"action"] isEqual:@"status"] && gate.phase != IDGateReady && gate.phase != IDGateRunning) {
            NSString *state = gate.phase == IDGateStarting ? @"starting" : gate.phase == IDGateFailed ? @"failed" : @"idle";
            NSDictionary *native = [NSJSONSerialization JSONObjectWithData:[IdolyEmbeddedServerStatusJSON() dataUsingEncoding:NSUTF8StringEncoding] options:0 error:NULL];
            completion(JSON(@{@"id":identifier, @"ok":@YES, @"result":@{@"state":state, @"running":@NO,
                @"options":@{}, @"runtime":@{}, @"native":native ?: @{},
                @"last_error":lastError ?: (id)NSNull.null, @"restart_required":@NO}})); return;
        }
        if (!worker || !atomic_load(&pythonReady)) {
            completion(failure(@"not_ready", @"서버가 준비되지 않았습니다. 서버 시작 버튼을 눌러 주세요.")); return;
        }
        [worker enqueue:^{
            NSString *error = nil, *reply = callHost("command", request, &error);
            dispatch_async(dispatch_get_main_queue(), ^{
                if (!reply) { completion(failure(@"native_failure", error)); return; }
                id parsed = [NSJSONSerialization JSONObjectWithData:[reply dataUsingEncoding:NSUTF8StringEncoding] options:NSJSONReadingMutableContainers error:NULL];
                if ([parsed isKindOfClass:NSMutableDictionary.class] && [parsed[@"ok"] isEqual:@YES]
                        && [parsed[@"result"] isKindOfClass:NSMutableDictionary.class]) {
                    id options = parsed[@"result"][@"options"];
                    if ([options isKindOfClass:NSDictionary.class] && [options[@"interface_language"] isKindOfClass:NSString.class])
                        IDNativeSetInterfaceLanguage(options[@"interface_language"]);
                    parsed[@"result"][@"native"] = [NSJSONSerialization JSONObjectWithData:[IdolyEmbeddedServerStatusJSON() dataUsingEncoding:NSUTF8StringEncoding] options:0 error:NULL] ?: @{};
                    completion(JSON(parsed) ?: failure(@"native_failure", @"서버 응답이 너무 큽니다."));
                } else completion(reply);
            });
        }];
    };
    if (NSThread.isMainThread) dispatchRequest(); else dispatch_async(dispatch_get_main_queue(), dispatchRequest);
}
void IdolyEmbeddedServerCryptoSelfTest(void (^completion)(NSString *)) {
    if (!worker || !atomic_load(&pythonReady)) {
        dispatch_async(dispatch_get_main_queue(), ^{ completion(failureReply(@"not_ready", @"서버가 준비되지 않았습니다.")); }); return;
    }
    [worker enqueue:^{
        static const unsigned char key[16] = {0x2b,0x7e,0x15,0x16,0x28,0xae,0xd2,0xa6,0xab,0xf7,0x15,0x88,0x09,0xcf,0x4f,0x3c};
        static const unsigned char iv[16] = {0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15};
        static const unsigned char plain[16] = {0x6b,0xc1,0xbe,0xe2,0x2e,0x40,0x9f,0x96,0xe9,0x3d,0x7e,0x11,0x73,0x93,0x17,0x2a};
        static const unsigned char cipher[16] = {0x76,0x49,0xab,0xac,0x81,0x19,0xb2,0x46,0xce,0xe9,0x8e,0x9b,0x12,0xe9,0x19,0x7d};
        PyEval_RestoreThread(pythonThread); pythonThread = NULL;
        PyObject *k = PyBytes_FromStringAndSize((const char *)key,16), *v = PyBytes_FromStringAndSize((const char *)iv,16);
        PyObject *p = PyBytes_FromStringAndSize((const char *)plain,16), *c = PyBytes_FromStringAndSize((const char *)cipher,16);
        PyObject *args = k && v && p ? PyTuple_Pack(4,Py_True,k,v,p) : NULL;
        PyObject *encrypted = args ? aesCBC(NULL,args) : NULL; Py_XDECREF(args);
        BOOL enc = encrypted && PyBytes_Check(encrypted) && PyBytes_GET_SIZE(encrypted)==16 && !memcmp(PyBytes_AS_STRING(encrypted),cipher,16);
        Py_XDECREF(encrypted); PyErr_Clear();
        args = k && v && c ? PyTuple_Pack(4,Py_False,k,v,c) : NULL;
        PyObject *decrypted = args ? aesCBC(NULL,args) : NULL; Py_XDECREF(args);
        BOOL dec = decrypted && PyBytes_Check(decrypted) && PyBytes_GET_SIZE(decrypted)==16 && !memcmp(PyBytes_AS_STRING(decrypted),plain,16);
        Py_XDECREF(decrypted); PyErr_Clear();
        PyObject *shortIV = PyBytes_FromStringAndSize((const char *)iv,15);
        args = k && shortIV && p ? PyTuple_Pack(4,Py_True,k,shortIV,p) : NULL;
        PyObject *invalid = args ? aesCBC(NULL,args) : NULL; Py_XDECREF(args);
        BOOL rejects = !invalid && PyErr_ExceptionMatches(PyExc_ValueError);
        Py_XDECREF(invalid); Py_XDECREF(shortIV); Py_XDECREF(k); Py_XDECREF(v); Py_XDECREF(p); Py_XDECREF(c); PyErr_Clear();
        pythonThread = PyEval_SaveThread();
        // C logical expressions have type int. Box a BOOL so JSON carries
        // true/false rather than 1/0 across the native/Python boundary.
        BOOL passed = enc && dec && rejects;
        NSString *reply = JSON(@{@"ok":@(passed), @"nist_encrypt":@(enc), @"nist_decrypt":@(dec),
            @"invalid_iv_rejected":@(rejects), @"worker_main_thread":@(NSThread.isMainThread)});
        dispatch_async(dispatch_get_main_queue(), ^{ completion(reply); });
    }];
}
__attribute__((constructor)) static void embeddedServerLoaded(void) {
    // The framework has a required dependency on the original presentation
    // dylib. Its constructor installs the early font gates before this runs.
    // No interpreter, payload, disk I/O, UIKit UI, or waiting under dyld.
    installGate();
    dispatch_async(dispatch_get_main_queue(), ^{
        if (!worker) worker = [IDServerWorker new];
        IDNativeInstallSettings();
        IDNativeSetGameStartAvailable(hookInstalled && gate.captured && !gate.forwarded);
        [NSNotificationCenter.defaultCenter addObserverForName:UIApplicationDidBecomeActiveNotification
            object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *note) {
                (void)note;
                if (lastError) IDNativeStartupFailure(lastError);
                forwardUnityIfVisible();
                recoverForeground();
            }];
        // Server ownership is independent of Unity's initialization hook.
        // PlayCover may open the settings menu before Unity calls that entry.
        beginServer();
    });
}
