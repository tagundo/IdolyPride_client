#import "IdolyEmbeddedServer.h"
#import "IdolyNativeUI.h"
#import "IdolyHTTP.h"
#import "IdolyClientData.h"
#import "IdolyKeyboardLifecycle.h"
#import "IdolyLocalHTTP.h"
#import "IdolyOctoBudget.h"
#import "IdolyUnityHost.h"
#import "GatePolicy.h"
#import "MP4LifecyclePolicy.h"
#import "IdolyMP4Library.h"
#if !IDOLY_SMOKE_SIMULATOR
#import "UnityStartupProfile.h"
#endif
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import <CommonCrypto/CommonCryptor.h>
#include <Python.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <dlfcn.h>
#include <mach-o/loader.h>
#include <mach/vm_prot.h>
#include <stdint.h>
#include <sys/stat.h>
#include <unistd.h>
#include <fcntl.h>
#include <string.h>

static const NSUInteger IDJSONLimit = 65536;
static IDGate gate;
static IMP originalStartUnity;
static atomic_bool unityKeyboardReady;
#if IDOLY_SMOKE_SIMULATOR
static Class probeKeyboardClass;
#else
static const void *keyboardSingletonSlot;
#endif
static NSString *selectedUnityBundleRoot;
static BOOL earlyHostInstalled;
static NSUInteger lateStartupCalls;
static NSString *hookError, *lastError, *lastGameError, *dataDirectory;
static NSDictionary *lastHTTPReadiness;
static BOOL recovering;
static NSUInteger interfaceSelectionRevision;
static BOOL hookInstalled;
static atomic_bool pythonReady;
static PyObject *hostModule;
static PyThreadState *pythonThread;
static NSString *mp4ExportDirectory;
static NSString *mp4PersistentExportDirectory, *mp4ConfiguredDirectory, *mp4ConfiguredQueueDirectory;
static uint64_t mp4ConfiguredEpoch;
static NSDictionary *mp4TitleCatalog;
static IDMP4LifecyclePolicy mp4Lifecycle = ID_MP4_LIFECYCLE_POLICY_INITIALIZER;

// Resolve only our bundled presentation bridge. Python has released the GIL
// before this worker-side configuration; game callbacks never call Python.
static BOOL prepareSharedResources(NSDictionary *descriptor) {
#if IDOLY_SMOKE_SIMULATOR
    (void)descriptor;
    return NO;
#else
    if (![descriptor isKindOfClass:NSDictionary.class]
            || ![descriptor[@"schema"] isEqual:@1] || ![descriptor[@"available"] isEqual:@YES]
            || ![descriptor[@"directory"] isKindOfClass:NSString.class]
            || ![descriptor[@"epoch"] isKindOfClass:NSNumber.class]) return NO;
    NSString *directory = descriptor[@"directory"];
    NSString *root = [IDNativeDataDirectory() stringByResolvingSymlinksInPath];
    long long epoch = [descriptor[@"epoch"] longLongValue];
    if (epoch < 1 || !root.length || ![directory hasPrefix:[root stringByAppendingString:@"/"]]
            || ![directory isEqual:[directory stringByResolvingSymlinksInPath]]) return NO;
    typedef bool (*Configure)(const char *, uint64_t);
    Configure configure = (Configure)dlsym(RTLD_DEFAULT, "IdolySharedResourcesConfigure");
    return configure && configure(directory.fileSystemRepresentation, (uint64_t)epoch);
#endif
}

static NSDictionary *sharedResourcesInfo(void) {
#if !IDOLY_SMOKE_SIMULATOR
    typedef size_t (*CopyStatus)(char *, size_t);
    CopyStatus copy = (CopyStatus)dlsym(RTLD_DEFAULT, "IdolySharedResourcesCopyStatus");
    char buffer[4096] = {0};
    size_t count = copy ? copy(buffer, sizeof buffer) : 0;
    if (count > 0 && count < sizeof buffer) {
        NSData *data = [NSData dataWithBytes:buffer length:count];
        id value = [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL];
        if ([value isKindOfClass:NSDictionary.class]) return value;
    }
#endif
    return @{@"available":@NO};
}

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
static BOOL prepareKeyboardLifecycle(NSString **error);
static void forwardUnityIfVisible(void) {
    NSCAssert(NSThread.isMainThread, @"Unity startup belongs to main thread");
    if (!IDGateCanForward(&gate) || UIApplication.sharedApplication.applicationState == UIApplicationStateBackground) return;
    NSString *keyboardError = nil;
    if (!prepareKeyboardLifecycle(&keyboardError)) {
        if (IDGateLaunchFailed(&gate)) {
            lastGameError = keyboardError ?: @"Unity 키보드 초기화 보호를 연결하지 못했습니다.";
            IDNativeSetServerState(YES, NO, @"서버 실행 중 · 게임 데이터 준비 실패");
            IDNativeStartupFailure(lastGameError);
        }
        return;
    }
    NSString *budgetError = nil;
    if (!IDOctoBudgetPrepare(&budgetError)) {
        if (IDGateLaunchFailed(&gate)) {
            lastGameError = budgetError ?: @"로컬 리소스 대기 설정을 준비하지 못했습니다.";
            IDNativeSetServerState(YES, NO, @"서버 실행 중 · 게임 연결 준비 실패");
            IDNativeStartupFailure(lastGameError);
        }
        return;
    }
    if (!IDGateForwardVisible(&gate, UIApplication.sharedApplication.applicationState == UIApplicationStateBackground)) return;
    lastError = nil; lastGameError = nil; IDNativeDismissFailure();
    IDNativeSetServerState(YES, NO, @"서버 실행 중");
    IDNativeSetGameStartAvailable(NO);
    NSString *hostFailure = nil;
    if (!earlyHostInstalled || !IDUnityHostStartGame(selectedUnityBundleRoot, &hostFailure)
            || lateStartupCalls == 0) {
        lastGameError = @"게임 시작 경로와 언어 데이터를 확인하지 못했습니다. 앱을 완전히 종료한 뒤 다시 실행해 주세요.";
        IDNativeShowLauncher();
        IDNativeStartupFailure(lastGameError);
        return;
    }
    atomic_store(&unityKeyboardReady, true);
    IDNativeHideLauncher();
    if (![IDOctoBudgetInfo()[@"configured"] isEqual:@YES]) {
        lastGameError = @"로컬 리소스 대기 설정을 적용하지 못했습니다.";
        IDNativeShowLauncher();
        IDNativeStartupFailure(lastGameError);
    }
}
static void beginServer(void) {
    NSCAssert([NSThread isMainThread], @"Gate state belongs to main thread");
    if (!IDGateBegin(&gate)) return;
    lastError = nil; lastGameError = nil; IDNativeDismissFailure();
    // HTTP can write to a disconnected client before Unity's delayed warmup.
    // Keep its original SIGPIPE policy ready before starting any Python work.
    if (![IDUnityHostInfo()[@"sigpipe_ignored_before_server"] isEqual:@YES]) {
        lastError = @"서버 연결 보호를 준비하지 못했습니다. 앱을 다시 실행해 주세요.";
        IDGateFailedAttempt(&gate);
        IDNativeSetServerState(NO, NO, @"서버를 시작하지 못했습니다");
        IDNativeStartupFailure(lastError);
        return;
    }
    IDNativeSetServerState(NO, YES, @"서버를 준비하고 있습니다…");
    if (!worker) worker = [IDServerWorker new];
    NSUInteger startupInterfaceRevision = interfaceSelectionRevision;
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
                if (interfaceSelectionRevision == startupInterfaceRevision)
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
        if (!error) {
            // foreground() can replace the listeners and their private broker.
            // Refresh its capability after releasing the GIL. Reconfiguring
            // the same live epoch preserves pending SDK callbacks.
            NSString *configurationError = nil;
            NSString *configuration = callHost("shared_resources_configuration", nil, &configurationError);
            NSData *encoded = [configuration dataUsingEncoding:NSUTF8StringEncoding];
            id descriptor = encoded ? [NSJSONSerialization JSONObjectWithData:encoded options:0 error:NULL] : nil;
            if (!configurationError) prepareSharedResources(descriptor);
        }
        dispatch_async(dispatch_get_main_queue(), ^{
            recovering = NO;
            if (error) { lastError = error; IDGateServerUnavailable(&gate); IDNativeSetServerState(NO, NO, @"서버 연결 확인 실패"); IDNativeStartupFailure(error); }
            else { lastError = nil; IDNativeDismissFailure(); IDNativeSetServerState(YES, NO, @"서버 실행 중"); }
        });
    }];
}
static void unityHostReady(void) {
    NSCAssert(NSThread.isMainThread, @"Native host readiness belongs to the main thread");
    if (!IDGateCapture(&gate)) return;
    IDNativeSetGameStartAvailable(earlyHostInstalled && hookInstalled);
    IDNativeShowLauncher();
    beginServer();
}
static void deferredStart(id self, SEL selector, id application) {
    NSCAssert(NSThread.isMainThread, @"Unity initialization belongs to the main thread");
    NSDictionary *host = IDUnityHostInfo();
    if (IDUnityHostIsLaunching() || [host[@"started"] isEqual:@YES]) {
        if (IDUnityHostIsLaunching()) ++lateStartupCalls;
        ((void (*)(id, SEL, id))originalStartUnity)(self, selector, application);
        // Preserve the verified 156.9109 timing: configure immediately after
        // Unity initialization, before Embedded's foreground/active callbacks.
        if (IDUnityHostIsLaunching() && ![IDOctoBudgetInfo()[@"configured"] isEqual:@YES]) {
            id origin = NSBundle.mainBundle.infoDictionary[@"IdolyUnifiedLoopbackOrigin"];
            BOOL attested = [origin isKindOfClass:NSString.class]
                && [origin isEqualToString:@"http://127.0.0.1:8080"]
                && [lastHTTPReadiness[@"ok"] isEqual:@YES]
                && [lastHTTPReadiness[@"url"] isEqualToString:@"http://127.0.0.1:8080/client/playback"];
            NSString *budgetFailure = nil;
            if (!IDOctoBudgetConfigure(attested, &budgetFailure))
                lastGameError = @"로컬 리소스 대기 설정을 적용하지 못했습니다.";
        }
        return;
    }
    // A late-only gate cannot safely choose already consumed language data.
    // Refuse this route while keeping independent server/settings access.
    lastGameError = @"게임 시작 경로와 언어 데이터를 확인하지 못했습니다. 앱을 완전히 종료한 뒤 다시 실행해 주세요.";
    IDNativeSetGameStartAvailable(NO);
    IDNativeShowLauncher();
    IDNativeStartupFailure(lastGameError);
    beginServer();
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
static id currentUnityKeyboard(void) {
#if IDOLY_SMOKE_SIMULATOR
    // The explicit probe provides a read-only singleton accessor. This branch
    // and its fake Objective-C classes are absent from the device framework.
    SEL selector = sel_registerName("idolyCurrentInstance");
    Method getter = probeKeyboardClass ? class_getClassMethod(probeKeyboardClass, selector) : NULL;
    return getter ? ((id (*)(id, SEL))method_getImplementation(getter))((id)probeKeyboardClass, selector) : nil;
#else
    // Both audited creation paths own this live object. Never write the slot,
    // invoke Instance (which can allocate), or reset keyboard/UI references.
    uintptr_t value = keyboardSingletonSlot ? *(const uintptr_t *)keyboardSingletonSlot : 0;
    return (__bridge id)(void *)value;
#endif
}
#if !IDOLY_SMOKE_SIMULATOR
static BOOL selectAuditedKeyboardSlot(IMP initialize) {
    Dl_info image = {0};
    if (!dladdr((const void *)initialize, &image) || !image.dli_fbase) return NO;
    const struct mach_header_64 *header = image.dli_fbase;
    const unsigned char *cursor = (const unsigned char *)(header + 1), *end = cursor + header->sizeofcmds;
    if (IDUnityKeyboardSingletonRVA % sizeof(uintptr_t)) return NO;
    for (uint32_t i = 0; i < header->ncmds; ++i) {
        if ((size_t)(end - cursor) < sizeof(struct load_command)) return NO;
        const struct load_command *command = (const void *)cursor;
        if (command->cmdsize < sizeof(*command) || command->cmdsize > (size_t)(end - cursor)) return NO;
        if (command->cmd == LC_SEGMENT_64) {
            if (command->cmdsize < sizeof(struct segment_command_64)) return NO;
            const struct segment_command_64 *segment = (const void *)command;
            if (segment->nsects > (command->cmdsize - sizeof(*segment)) / sizeof(struct section_64)) return NO;
            if (!strncmp(segment->segname, "__DATA", sizeof(segment->segname))
                    && (segment->initprot & (VM_PROT_READ | VM_PROT_WRITE)) == (VM_PROT_READ | VM_PROT_WRITE)) {
                const struct section_64 *sections = (const void *)(segment + 1);
                for (uint32_t j = 0; j < segment->nsects; ++j) {
                    const struct section_64 *section = &sections[j];
                    if (!strncmp(section->sectname, "__bss", sizeof(section->sectname))
                            && !strncmp(section->segname, "__DATA", sizeof(section->segname))
                            && (section->flags & SECTION_TYPE) == S_ZEROFILL
                            && section->addr == IDUnityKeyboardBssRVA && section->size == IDUnityKeyboardBssSize
                            && IDUnityKeyboardSingletonRVA >= section->addr
                            && IDUnityKeyboardSingletonRVA - section->addr <= section->size - sizeof(uintptr_t)
                            && (uintptr_t)header <= UINTPTR_MAX - IDUnityKeyboardSingletonRVA) {
                        keyboardSingletonSlot = (const unsigned char *)header + IDUnityKeyboardSingletonRVA;
                        return YES;
                    }
                }
            }
        }
        cursor += command->cmdsize;
    }
    return NO;
}
#endif
static BOOL keyboardMethodType(Method method, const char *result) {
    char *type = method ? method_copyReturnType(method) : NULL;
    BOOL matches = method && type && !strcmp(type, result) && method_getNumberOfArguments(method) == 2
        && exactType(method, 0, "@") && exactType(method, 1, ":");
    free(type); return matches;
}
static BOOL prepareKeyboardLifecycle(NSString **error) {
    Class cls = objc_getClass("KeyboardDelegate");
    NSError *nativeError = nil;
    if ([IDKeyboardLifecycleInfo()[@"installed"] isEqual:@YES]) {
        BOOL good = IDKeyboardLifecycleInstall(cls, currentUnityKeyboard, &nativeError);
        if (!good) *error = nativeError.localizedDescription;
        return good;
    }
    Method initialize = cls ? class_getClassMethod(cls, sel_registerName("Initialize")) : NULL;
    Method instance = cls ? class_getClassMethod(cls, sel_registerName("Instance")) : NULL;
    BOOL valid = keyboardMethodType(initialize, "v") && keyboardMethodType(instance, "@");
#if IDOLY_SMOKE_SIMULATOR
    Method reader = cls ? class_getClassMethod(cls, sel_registerName("idolyCurrentInstance")) : NULL;
    valid = valid && keyboardMethodType(reader, "@");
    if (valid) probeKeyboardClass = cls;
#else
    Method destroy = cls ? class_getClassMethod(cls, sel_registerName("Destroy")) : NULL;
    valid = valid && keyboardMethodType(destroy, "v")
        && auditedUnityEntry(method_getImplementation(initialize), IDUnityKeyboardInitializeRVA,
            IDUnityKeyboardInitializeCode, sizeof IDUnityKeyboardInitializeCode)
        && auditedUnityEntry(method_getImplementation(instance), IDUnityKeyboardInstanceRVA,
            IDUnityKeyboardInstanceCode, sizeof IDUnityKeyboardInstanceCode)
        && auditedUnityEntry(method_getImplementation(destroy), IDUnityKeyboardDestroyRVA,
            IDUnityKeyboardDestroyCode, sizeof IDUnityKeyboardDestroyCode)
        && selectAuditedKeyboardSlot(method_getImplementation(initialize));
#endif
    if (!valid) {
        *error = @"이 게임의 Unity 키보드 진입점을 확인하지 못했습니다. 서버는 독립적으로 시작합니다.";
        return NO;
    }
    BOOL good = IDKeyboardLifecycleInstall(cls, currentUnityKeyboard, &nativeError);
    if (!good) *error = nativeError.localizedDescription ?: @"Unity 키보드 초기화 보호를 연결하지 못했습니다.";
    return good;
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
    else selectedUnityBundleRoot = path.stringByResolvingSymlinksInPath;
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
    originalStartUnity = method_setImplementation(target, (IMP)deferredStart);
    hookInstalled = originalStartUnity != NULL;
    if (!hookInstalled) hookError = @"Unity 시작 진입점을 연결하지 못했습니다.";
}
NSString *IDNativeDataDirectory(void) {
    @synchronized (IDServerWorker.class) { return dataDirectory; }
}
NSString *IdolyEmbeddedServerStatusJSON(void) {
    __block NSString *result;
    void (^read)(void) = ^{ result = JSON(@{@"schema":@1, @"hook_installed":@((BOOL)(hookInstalled && earlyHostInstalled)),
        @"keyboard_lifecycle":IDKeyboardLifecycleInfo(), @"keyboard_ready":@(atomic_load(&unityKeyboardReady)),
        @"octo_budget":IDOctoBudgetInfo(), @"unity_host":IDUnityHostInfo(),
        @"shared_resources":sharedResourcesInfo(),
        @"late_startup_calls":@(lateStartupCalls),
        @"http_readiness":lastHTTPReadiness ?: (id)NSNull.null,
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
        lastGameError = nil; lastHTTPReadiness = nil;
        IDNativeSetServerState(YES, YES, @"게임 데이터와 선택한 언어를 준비하고 있습니다…");
        [worker enqueue:^{
            // Prepare the selected immutable data before Unity initializes.
            NSString *error = nil, *reply = callHost("prepare_game_start", nil, &error);
            NSData *bytes = [reply dataUsingEncoding:NSUTF8StringEncoding];
            id status = bytes ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:NULL] : nil;
            BOOL ready = !error && [status isKindOfClass:NSDictionary.class]
                && [status[@"running"] isEqual:@YES] && [status[@"state"] isEqual:@"ready"];
            BOOL serving = ready;
            if (ready) prepareSharedResources(status[@"shared_resources"]);
            if (!ready) {
                NSString *healthError = nil, *health = callHost("readiness", nil, &healthError);
                id observed = health ? [NSJSONSerialization JSONObjectWithData:[health dataUsingEncoding:NSUTF8StringEncoding] options:0 error:NULL] : nil;
                serving = !healthError && [observed isKindOfClass:NSDictionary.class] && [observed[@"running"] isEqual:@YES];
            }
            // callHost has released the GIL. Perform an actual app-side HTTP
            // GET while the serving Python thread can answer it; listener
            // ownership or the native command bridge alone is not this check.
            NSDictionary *httpReadiness = ready ? IDLocalHTTPReadiness(8080, 8.0) : nil;
            if (ready && ![httpReadiness[@"ok"] isEqual:@YES]) {
                ready = NO;
                error = @"내장 리소스 서버에 연결하지 못했습니다. 진단에서 HTTP 연결 상태를 확인해 주세요.";
            }
            dispatch_async(dispatch_get_main_queue(), ^{
                lastHTTPReadiness = httpReadiness;
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
        if ([object[@"action"] isEqual:@"save_interface_language"]) {
            id locale = object[@"interface_language"];
            if (object.count != 3 || ![locale isKindOfClass:NSString.class]
                    || ![@[@"system", @"ko", @"ja", @"en"] containsObject:locale]) {
                completion(failure(@"invalid_request", @"설정 요청 형식이 올바르지 않습니다.")); return;
            }
            ++interfaceSelectionRevision;
            IDNativeSetInterfaceLanguage(locale);
        }
        if ([object[@"action"] isEqual:@"status"] && gate.phase != IDGateReady && gate.phase != IDGateRunning
                && !IDGateReadFailedHostStatus(&gate, atomic_load(&pythonReady), worker != nil)) {
            NSString *state = gate.phase == IDGateStarting ? @"starting" : gate.phase == IDGateFailed ? @"failed" : @"idle";
            NSDictionary *native = [NSJSONSerialization JSONObjectWithData:[IdolyEmbeddedServerStatusJSON() dataUsingEncoding:NSUTF8StringEncoding] options:0 error:NULL];
            completion(JSON(@{@"id":identifier, @"ok":@YES, @"result":@{@"state":state, @"running":@NO,
                @"options":@{}, @"runtime":@{}, @"native":native ?: @{},
                @"last_error":lastError ?: (id)NSNull.null, @"restart_required":@NO}})); return;
        }
        if (!worker || (!atomic_load(&pythonReady)
                && ![object[@"action"] isEqual:@"save_interface_language"])) {
            completion(failure(@"not_ready", @"서버가 준비되지 않았습니다. 서버 시작 버튼을 눌러 주세요.")); return;
        }
        [worker enqueue:^{
            NSString *error = nil, *reply = callHost("command", request, &error);
            dispatch_async(dispatch_get_main_queue(), ^{
                if (!reply) { completion(failure(@"native_failure", error)); return; }
                id parsed = [NSJSONSerialization JSONObjectWithData:[reply dataUsingEncoding:NSUTF8StringEncoding] options:NSJSONReadingMutableContainers error:NULL];
                if ([parsed isKindOfClass:NSMutableDictionary.class] && [parsed[@"ok"] isEqual:@YES]
                        && [parsed[@"result"] isKindOfClass:NSMutableDictionary.class]) {
                    parsed[@"result"][@"native"] = [NSJSONSerialization JSONObjectWithData:[IdolyEmbeddedServerStatusJSON() dataUsingEncoding:NSUTF8StringEncoding] options:0 error:NULL] ?: @{};
                    if ([object[@"action"] isEqual:@"status"] && gate.phase == IDGateFailed) {
                        // Keep the host's saved startup checks/history, while
                        // retaining the native launch failure as current state.
                        parsed[@"result"][@"state"] = @"failed";
                        parsed[@"result"][@"running"] = @NO;
                        parsed[@"result"][@"last_error"] = lastError ?: (id)NSNull.null;
                    }
                    completion(JSON(parsed) ?: failure(@"native_failure", @"서버 응답이 너무 큽니다."));
                } else completion(reply);
            });
        }];
    };
    if (NSThread.isMainThread) dispatchRequest(); else dispatch_async(dispatch_get_main_queue(), dispatchRequest);
}
static NSDictionary *mp4SessionStatus(void) {
    typedef size_t (*Copy)(char *, size_t);
    typedef int (*Ready)(void);
    Copy copy = (Copy)dlsym(RTLD_DEFAULT, "IDMP4SessionStatus");
    Ready ready = (Ready)dlsym(RTLD_DEFAULT, "IDMP4SessionReady");
    char buffer[8192] = {0}; size_t count = copy ? copy(buffer, sizeof buffer) : 0;
    NSData *data = count > 0 && count < sizeof buffer ? [NSData dataWithBytes:buffer length:count] : nil;
    id decoded = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL] : nil;
    NSDictionary *raw = [decoded isKindOfClass:NSDictionary.class] ? decoded : @{};
    BOOL isReady = ready && ready() == 1;
    NSMutableDictionary *status = [@{@"phase":@"idle", @"ready":@(isReady)} mutableCopy];
    NSArray *phases = @[@"idle", @"preparing_audio", @"rendering", @"finishing", @"completed", @"cancelling", @"cancelled", @"failed", @"pausing", @"paused"];
    if ([phases containsObject:raw[@"phase"]]) status[@"phase"] = raw[@"phase"];
    for (NSString *key in @[@"frames",@"total_frames",@"audio_frames",@"total_audio_frames",@"width",@"height",@"source_width",@"source_height",@"video_bitrate",@"fps_num",@"fps_den",@"bytes_written",@"unity_ticks",@"capture_acks"]) {
        NSNumber *value = [raw[key] isKindOfClass:NSNumber.class] ? raw[key] : nil;
        if (value && CFGetTypeID((__bridge CFTypeRef)value) != CFBooleanGetTypeID()
                && value.doubleValue >= 0 && value.doubleValue <= 9007199254740991.0
                && value.doubleValue == value.unsignedLongLongValue) status[key] = value;
    }
    NSRegularExpression *code = [NSRegularExpression regularExpressionWithPattern:@"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$" options:0 error:NULL];
    for (NSString *key in @[@"export_id",@"error_code",@"readiness_error",@"pause_reason",@"resume_phase"]) {
        NSString *value = [raw[key] isKindOfClass:NSString.class] ? raw[key] : nil;
        if (value && [code numberOfMatchesInString:value options:0 range:NSMakeRange(0,value.length)] == 1)
            status[key] = value;
    }
    for (NSString *key in @[@"paused",@"pause_requested"]) {
        NSNumber *value = [raw[key] isKindOfClass:NSNumber.class] ? raw[key] : nil;
        if (value && CFGetTypeID((__bridge CFTypeRef)value) == CFBooleanGetTypeID()) status[key] = value;
    }
    return status;
}
BOOL IdolyEmbeddedServerMP4IsFinishing(void) {
    return [mp4SessionStatus()[@"phase"] isEqual:@"finishing"];
}
void IdolyEmbeddedServerMP4SetLifecycleActive(BOOL active) {
    IDMP4SuspendCall suspend = (IDMP4SuspendCall)dlsym(RTLD_DEFAULT, "IDMP4SessionSuspend");
    IDMP4ResumeCall resume = (IDMP4ResumeCall)dlsym(RTLD_DEFAULT, "IDMP4SessionResume");
    IDMP4LifecycleSetActive(&mp4Lifecycle, active, suspend, resume);
}
static BOOL mp4SetUserPaused(BOOL paused) {
    IDMP4SuspendCall suspend = (IDMP4SuspendCall)dlsym(RTLD_DEFAULT, "IDMP4SessionSuspend");
    IDMP4ResumeCall resume = (IDMP4ResumeCall)dlsym(RTLD_DEFAULT, "IDMP4SessionResume");
    if (!suspend || !resume) return NO;
    IDMP4LifecycleSetUserPaused(&mp4Lifecycle, paused, suspend, resume);
    return YES;
}
// BEGIN_MP4_QUEUE_FILE_POLICY
// These C predicates also execute in the filesystem regression harness.
static bool IDMP4HexIdentifier(const char *identifier) {
    if (!identifier || strlen(identifier) != 32) return false;
    for (size_t i = 0; i < 32; ++i)
        if (!((identifier[i] >= '0' && identifier[i] <= '9') || (identifier[i] >= 'a' && identifier[i] <= 'f'))) return false;
    return true;
}
static bool IDMP4PrivateDirectory(const char *path) {
    if (!path || path[0] != '/') return false;
    int fd = open(path,O_RDONLY|O_DIRECTORY|O_NOFOLLOW);
    struct stat opened, named;
    bool good = fd >= 0 && fstat(fd,&opened) == 0 && lstat(path,&named) == 0
        && S_ISDIR(opened.st_mode) && opened.st_uid == getuid() && (opened.st_mode & 0777) == 0700
        && opened.st_dev == named.st_dev && opened.st_ino == named.st_ino;
    if (fd >= 0) close(fd);
    return good;
}
static bool IDMP4FinishedFile(const char *root, const char *identifier) {
    if (!IDMP4HexIdentifier(identifier) || !IDMP4PrivateDirectory(root)) return false;
    int directory = open(root,O_RDONLY|O_DIRECTORY|O_NOFOLLOW);
    if (directory < 0) return false;
    char name[37]; memcpy(name,identifier,32); memcpy(name+32,".mp4",5);
    int fd = openat(directory,name,O_RDONLY|O_NOFOLLOW|O_NONBLOCK);
    struct stat opened, named;
    bool good = fd >= 0 && fstat(fd,&opened) == 0 && fstatat(directory,name,&named,AT_SYMLINK_NOFOLLOW) == 0
        && S_ISREG(opened.st_mode) && opened.st_uid == getuid() && opened.st_nlink == 1 && opened.st_size > 0
        && opened.st_dev == named.st_dev && opened.st_ino == named.st_ino;
    if (fd >= 0) close(fd);
    close(directory);
    return good;
}
// END_MP4_QUEUE_FILE_POLICY
static BOOL mp4Choice(id value, NSArray<NSNumber *> *choices) {
    return [value isKindOfClass:NSNumber.class] && CFGetTypeID((__bridge CFTypeRef)value) != CFBooleanGetTypeID()
        && [choices containsObject:value];
}
static BOOL mp4Integer(id value, unsigned long long maximum) {
    return [value isKindOfClass:NSNumber.class] && CFGetTypeID((__bridge CFTypeRef)value) != CFBooleanGetTypeID()
        && [value doubleValue] >= 0 && [value doubleValue] <= maximum
        && [value doubleValue] == [value unsignedLongLongValue];
}
static BOOL mp4Code(id value, NSUInteger maximum) {
    if (![value isKindOfClass:NSString.class] || ![value length] || [value length] > maximum) return NO;
    NSCharacterSet *allowed = [NSCharacterSet characterSetWithCharactersInString:@"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"];
    return [value rangeOfCharacterFromSet:allowed.invertedSet].location == NSNotFound;
}
static BOOL mp4Identifier(id value) {
    return [value isKindOfClass:NSString.class] && [value length] == 32 && IDMP4HexIdentifier([value UTF8String]);
}
static NSDictionary *mp4SanitizeTitleCatalog(id catalog) {
    if (![catalog isKindOfClass:NSDictionary.class]) return @{};
    NSMutableDictionary *languages = [NSMutableDictionary new];
    NSCharacterSet *controls = NSCharacterSet.controlCharacterSet;
    for (NSString *language in @[@"ko",@"ja",@"en"]) {
        id entries = catalog[language];
        if (![entries isKindOfClass:NSDictionary.class] || [entries count] > 2048) continue;
        NSMutableDictionary *titles = [NSMutableDictionary new];
        for (id timeline in entries) {
            id title = entries[timeline];
            if (!mp4Code(timeline,192) || ![title isKindOfClass:NSString.class] || ![title length] || [title length] > 192
                    || [title rangeOfCharacterFromSet:controls].location != NSNotFound
                    || ![[title stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet] length]
                    || ![title dataUsingEncoding:NSUTF8StringEncoding]) continue;
            titles[[timeline copy]] = [title copy];
        }
        if (titles.count) languages[language] = [titles copy];
    }
    return [languages copy];
}
static NSDictionary *mp4QueueStatus(void) {
    typedef size_t (*Copy)(char *, size_t);
    Copy copy = (Copy)dlsym(RTLD_DEFAULT,"IDMP4QueueStatus");
    char buffer[16384] = {0}; size_t count = copy ? copy(buffer,sizeof buffer) : 0;
    NSData *bytes = count > 0 && count < sizeof buffer ? [NSData dataWithBytes:buffer length:count] : nil;
    id decoded = bytes ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:NULL] : nil;
    NSDictionary *raw = [decoded isKindOfClass:NSDictionary.class] ? decoded : nil;
    NSDictionary *invalid = @{@"schema":@1,@"available":@NO,@"can_run":@NO,@"command_pending":@NO,@"running":@NO,@"paused":@NO,
        @"phase":@"unavailable",@"error_code":@"mp4_queue_unavailable",@"capacity":@8,@"jobs":@[],@"session":mp4SessionStatus()};
    if (!mp4Choice(raw[@"schema"],@[@1]) || ![raw[@"jobs"] isKindOfClass:NSArray.class] || [raw[@"jobs"] count] > 8) return invalid;
    NSMutableDictionary *status = [@{@"schema":@1,@"capacity":@8,@"session":mp4SessionStatus()} mutableCopy];
    for (NSString *key in @[@"available",@"can_run",@"command_pending",@"running",@"paused"]) {
        id value = raw[key];
        if (![value isKindOfClass:NSNumber.class] || CFGetTypeID((__bridge CFTypeRef)value) != CFBooleanGetTypeID()) return invalid;
        status[key] = value;
    }
    for (NSString *key in @[@"phase",@"error_code"]) {
        id value = [key isEqual:@"error_code"] && [raw[key] isEqual:@""] ? @"none" : raw[key];
        if (!mp4Code(value,128)) return invalid;
        status[key] = value;
    }
    for (NSString *key in @[@"last_added_job_id",@"current_job_id"]) {
        id value = raw[key];
        if ([value isEqual:@""] || mp4Identifier(value)) status[key] = value;
        else return invalid;
    }
    NSArray *states = @[@"pending",@"running",@"paused",@"completed",@"failed",@"cancelled",@"interrupted"];
    NSMutableArray *jobs = [NSMutableArray new]; NSMutableSet *identifiers = [NSMutableSet new], *outputs = [NSMutableSet new];
    for (id item in raw[@"jobs"]) {
        if (![item isKindOfClass:NSDictionary.class]) return invalid;
        NSDictionary *row = item; NSString *identifier = row[@"job_id"], *output = row[@"output_id"];
        id errorCode = [row[@"error_code"] isEqual:@""] ? @"none" : row[@"error_code"];
        if (!mp4Identifier(identifier) || [identifiers containsObject:identifier] || ![states containsObject:row[@"state"]]
                || !(mp4Identifier(output) || [output isEqual:@""]) || !mp4Code(row[@"timeline"],192)
                || !mp4Code(errorCode,128) || !mp4Integer(row[@"actor_count"],32)
                || !mp4Integer(row[@"width"],16384) || !mp4Integer(row[@"height"],16384)
                || !mp4Choice(row[@"fps_num"],@[@30,@60,@120]) || !mp4Choice(row[@"video_codec"],@[@1,@2])) return invalid;
        if (output.length && [outputs containsObject:output]) return invalid;
        if ([row[@"state"] isEqual:@"completed"] && !output.length) return invalid;
        [identifiers addObject:identifier]; if (output.length) [outputs addObject:output];
        NSMutableDictionary *safeRow = [@{@"job_id":identifier,@"output_id":output,@"timeline":row[@"timeline"],@"actor_count":row[@"actor_count"],
            @"width":row[@"width"],@"height":row[@"height"],@"fps_num":row[@"fps_num"],@"video_codec":row[@"video_codec"],
            @"state":row[@"state"],@"error_code":errorCode} mutableCopy];
        NSMutableDictionary *localizedTitles = [NSMutableDictionary new];
        for (NSString *language in @[@"ko",@"ja",@"en"]) {
            NSString *title = mp4TitleCatalog[language][row[@"timeline"]];
            if (title) localizedTitles[language] = title;
        }
        if (localizedTitles.count) safeRow[@"title_localizations"] = localizedTitles;
        [jobs addObject:safeRow];
    }
    status[@"jobs"] = jobs;
    return status;
}
static NSArray *mp4LibraryQueueJobs(void) {
    // Cold journal inspection needs no Unity/Python callback. Its exact stable
    // app-owned roots are the same ones validated in the private descriptor.
    NSString *root=IDNativeDataDirectory().stringByResolvingSymlinksInPath;
    NSString *library=[root stringByAppendingPathComponent:@".idoly-mp4-library"];
    NSString *queue=[library stringByAppendingPathComponent:@"queue"],*exports=[library stringByAppendingPathComponent:@"exports"];
    typedef int (*Configure)(const char *,const char *);
    Configure configure=(Configure)dlsym(RTLD_DEFAULT,"IDMP4QueueConfigure");
    if(configure && IDMP4PrivateDirectory(library.fileSystemRepresentation)
            && IDMP4PrivateDirectory(queue.fileSystemRepresentation) && IDMP4PrivateDirectory(exports.fileSystemRepresentation)
            && [library isEqual:library.stringByResolvingSymlinksInPath]
            && (([mp4ConfiguredQueueDirectory isEqual:queue]&&[mp4PersistentExportDirectory isEqual:exports])
                || configure(queue.fileSystemRepresentation,exports.fileSystemRepresentation)==0)) {
        mp4PersistentExportDirectory=exports;mp4ConfiguredQueueDirectory=queue;
        NSDictionary *status=mp4QueueStatus();
        if([status[@"available"]isEqual:@YES])return status[@"jobs"] ?: @[];
    }
    return @[];
}
static BOOL mp4EnsureConfiguration(BOOL queueRequired, NSString **failure) {
    if (!atomic_load(&pythonReady)) { *failure = @"mp4_server_not_ready"; return NO; }
    typedef int (*Configure)(const char *,uint64_t,const char *,const char *,int);
    typedef int (*QueueConfigure)(const char *,const char *);
    Configure configure = (Configure)dlsym(RTLD_DEFAULT,"IDMP4SessionConfigure");
    QueueConfigure configureQueue = (QueueConfigure)dlsym(RTLD_DEFAULT,"IDMP4QueueConfigure");
    if (!configure || (queueRequired && !configureQueue)) { *failure = @"mp4_unavailable"; return NO; }
    NSString *error = nil, *raw = callHost("mp4_configuration",nil,&error);
    NSData *bytes = [raw dataUsingEncoding:NSUTF8StringEncoding];
    id value = bytes && bytes.length <= IDJSONLimit ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:NULL] : nil;
    NSDictionary *descriptor = [value isKindOfClass:NSDictionary.class] ? value : nil;
    NSString *directory = [descriptor[@"directory"] isKindOfClass:NSString.class] ? descriptor[@"directory"] : nil;
    NSString *exports = [descriptor[@"export_directory"] isKindOfClass:NSString.class] ? descriptor[@"export_directory"] : nil;
    NSString *capability = [descriptor[@"capability"] isKindOfClass:NSString.class] ? descriptor[@"capability"] : nil;
    NSString *queue = [descriptor[@"queue_directory"] isKindOfClass:NSString.class] ? descriptor[@"queue_directory"] : nil;
    NSString *persistent = [descriptor[@"persistent_export_directory"] isKindOfClass:NSString.class] ? descriptor[@"persistent_export_directory"] : nil;
    NSNumber *epoch = [descriptor[@"epoch"] isKindOfClass:NSNumber.class] ? descriptor[@"epoch"] : nil;
    NSString *root = IDNativeDataDirectory().stringByResolvingSymlinksInPath;
    BOOL trusted = !error && [descriptor[@"schema"] isEqual:@1] && [descriptor[@"available"] isEqual:@YES]
        && root.length && directory.isAbsolutePath && [directory hasPrefix:[root stringByAppendingString:@"/"]]
        && [directory isEqual:directory.stringByResolvingSymlinksInPath] && IDMP4PrivateDirectory(directory.fileSystemRepresentation)
        && [exports isEqual:[directory stringByAppendingPathComponent:@"exports"]]
        && [exports isEqual:exports.stringByResolvingSymlinksInPath] && IDMP4PrivateDirectory(exports.fileSystemRepresentation)
        && mp4Identifier(capability) && mp4Integer(epoch,9007199254740991ULL) && epoch.unsignedLongLongValue >= 1;
    if (queueRequired) {
        NSString *library = [directory.stringByDeletingLastPathComponent stringByAppendingPathComponent:@".idoly-mp4-library"];
        trusted = trusted && [queue isEqual:[library stringByAppendingPathComponent:@"queue"]]
            && [persistent isEqual:[library stringByAppendingPathComponent:@"exports"]]
            && [queue isEqual:queue.stringByResolvingSymlinksInPath] && [persistent isEqual:persistent.stringByResolvingSymlinksInPath]
            && IDMP4PrivateDirectory(library.fileSystemRepresentation) && IDMP4PrivateDirectory(queue.fileSystemRepresentation)
            && IDMP4PrivateDirectory(persistent.fileSystemRepresentation);
    }
    if (!trusted) { *failure = @"mp4_descriptor_unavailable"; return NO; }
    if (mp4ConfiguredEpoch != epoch.unsignedLongLongValue || ![mp4ConfiguredDirectory isEqual:directory]) {
        if (configure(directory.fileSystemRepresentation,epoch.unsignedLongLongValue,capability.UTF8String,exports.fileSystemRepresentation,2) != 0) {
            *failure = @"mp4_configuration_failed"; return NO;
        }
        mp4ConfiguredEpoch = epoch.unsignedLongLongValue; mp4ConfiguredDirectory = [directory copy]; mp4ExportDirectory = [exports copy];
        mp4ConfiguredQueueDirectory = nil; mp4PersistentExportDirectory = nil;
        // Titles are presentation metadata from the bundled Music catalogs,
        // independent of the immutable native descriptor and interface choice.
        mp4TitleCatalog = mp4SanitizeTitleCatalog(descriptor[@"title_catalog"]);
    }
    if (queueRequired && (![mp4ConfiguredQueueDirectory isEqual:queue] || ![mp4PersistentExportDirectory isEqual:persistent])) {
        if (configureQueue(queue.fileSystemRepresentation,persistent.fileSystemRepresentation) != 0) { *failure = @"mp4_queue_configuration_failed"; return NO; }
        mp4ConfiguredQueueDirectory = [queue copy]; mp4PersistentExportDirectory = [persistent copy];
    }
    return YES;
}
static NSDictionary *mp4DefaultOptions(void) {
    return @{@"schema":@1,@"fps":@60,@"video_codec":@1,@"bitrate_mode":@"recommended",@"video_bitrate":@16000000,
        @"resolution_mode":@"current",@"width":@1920,@"height":@1080};
}
static BOOL mp4ValidOptions(id candidate) {
    if (![candidate isKindOfClass:NSDictionary.class]) return NO;
    NSDictionary *value = candidate;
    NSSet *keys = [NSSet setWithArray:@[@"schema",@"fps",@"video_codec",@"bitrate_mode",@"video_bitrate",@"resolution_mode",@"width",@"height"]];
    return value.count == keys.count && [[NSSet setWithArray:value.allKeys] isEqual:keys]
        && mp4Choice(value[@"schema"],@[@1]) && mp4Choice(value[@"fps"],@[@30,@60,@120]) && mp4Choice(value[@"video_codec"],@[@1,@2])
        && [@[@"recommended",@"custom"] containsObject:value[@"bitrate_mode"] ?: @""]
        && mp4Integer(value[@"video_bitrate"],200000000) && [value[@"video_bitrate"] unsignedIntValue] >= 100000
        && [@[@"current",@"custom"] containsObject:value[@"resolution_mode"] ?: @""]
        && mp4Integer(value[@"width"],4096) && [value[@"width"] unsignedIntValue] >= 16 && [value[@"width"] unsignedIntValue] % 2 == 0
        && mp4Integer(value[@"height"],4096) && [value[@"height"] unsignedIntValue] >= 16 && [value[@"height"] unsignedIntValue] % 2 == 0;
}
static NSDictionary *mp4SavedOptions(void) {
    id value = [NSUserDefaults.standardUserDefaults objectForKey:@"IdolyMP4ExportOptions.v1"];
    return mp4ValidOptions(value) ? value : mp4DefaultOptions();
}
static uint64_t mp4SaveLeaseGeneration,mp4SaveLease;
static NSString *mp4SaveLeaseJob;
void IdolyEmbeddedServerMP4Command(NSString *request, void (^completion)(NSString *)) {
    NSData *bytes = [request dataUsingEncoding:NSUTF8StringEncoding];
    id decoded = bytes && bytes.length <= 4096 ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:NULL] : nil;
    NSDictionary *object = [decoded isKindOfClass:NSDictionary.class] ? decoded : nil;
    NSNumber *identifier = [object[@"id"] isKindOfClass:NSNumber.class] ? object[@"id"] : nil;
    NSString *action = [object[@"action"] isKindOfClass:NSString.class] ? object[@"action"] : nil;
    BOOL start = [action isEqual:@"mp4_start"], enqueue = [action isEqual:@"mp4_enqueue"];
    BOOL queueAction = enqueue || [action hasPrefix:@"mp4_queue_"];
    BOOL dimensions = object.count == 7 && mp4Integer(object[@"width"],4096) && mp4Integer(object[@"height"],4096)
        && (([object[@"width"] unsignedIntValue] == 0 && [object[@"height"] unsignedIntValue] == 0)
            || ([object[@"width"] unsignedIntValue] >= 16 && [object[@"width"] unsignedIntValue] % 2 == 0
                && [object[@"height"] unsignedIntValue] >= 16 && [object[@"height"] unsignedIntValue] % 2 == 0));
    BOOL preset = (start || enqueue) && (object.count == 5 || dimensions) && mp4Choice(object[@"fps"],@[@30,@60,@120])
        && mp4Integer(object[@"video_bitrate"],200000000)
        && ([object[@"video_bitrate"] unsignedIntValue] == 0 || [object[@"video_bitrate"] unsignedIntValue] >= 100000)
        && mp4Choice(object[@"video_codec"],@[@1,@2]);
    BOOL optionsRead = [action isEqual:@"mp4_options"] && object.count == 2;
    BOOL optionsSave = [action isEqual:@"mp4_options_save"] && object.count == 3 && mp4ValidOptions(object[@"options"]);
    BOOL completedStatus = [action isEqual:@"mp4_completed_status"] && (object.count==2
        || (object.count==3 && mp4Integer(object[@"offset"],65536) && [object[@"offset"]unsignedIntValue]%32==0));
    BOOL noFields = object.count == 2 && [@[@"mp4_status",@"mp4_cancel",@"mp4_pause",@"mp4_resume",@"mp4_queue_status",@"mp4_queue_run",@"mp4_queue_pause",@"mp4_queue_resume"] containsObject:action];
    BOOL jobAction = object.count == 3 && mp4Identifier(object[@"job_id"])
        && [@[@"mp4_queue_cancel",@"mp4_queue_remove",@"mp4_queue_retry"] containsObject:action];
    id deleteOutput = object[@"delete_output"];
    BOOL deleteCompleted = [action isEqual:@"mp4_queue_remove"] && object.count == 4 && mp4Identifier(object[@"job_id"])
        && [deleteOutput isKindOfClass:NSNumber.class] && CFGetTypeID((__bridge CFTypeRef)deleteOutput) == CFBooleanGetTypeID()
        && [deleteOutput isEqual:@YES];
    BOOL move = [action isEqual:@"mp4_queue_move"] && object.count == 4 && mp4Identifier(object[@"job_id"]) && mp4Integer(object[@"position"],7);
    BOOL valid = identifier && CFGetTypeID((__bridge CFTypeRef)identifier) != CFBooleanGetTypeID()
        && identifier.longLongValue >= 1 && identifier.longLongValue <= INT32_MAX && identifier.doubleValue == identifier.longLongValue
        && (preset || optionsRead || optionsSave || completedStatus || noFields || jobAction || deleteCompleted || move);
    void (^reply)(BOOL,NSDictionary *,NSString *) = ^(BOOL ok,NSDictionary *status,NSString *error) {
        NSString *json = JSON(ok ? @{@"id":identifier ?: @1,@"ok":@YES,@"result":status ?: @{}}
            : @{@"id":identifier ?: @1,@"ok":@NO,@"error":@{@"code":error ?: @"mp4_unavailable",@"message":error ?: @"mp4_unavailable"}});
        dispatch_async(dispatch_get_main_queue(), ^{ completion(json); });
    };
    if (!valid) { reply(NO,nil,@"invalid_request"); return; }
    // This app-owned preference survives the intentionally in-memory WebKit
    // data store. It never contains an output path or a queue identity.
    if (optionsRead || optionsSave) {
        if (optionsSave) [NSUserDefaults.standardUserDefaults setObject:object[@"options"] forKey:@"IdolyMP4ExportOptions.v1"];
        reply(YES,@{@"options":mp4SavedOptions()},nil); return;
    }
    if (!worker) { reply(NO,nil,@"mp4_unavailable"); return; }
    [worker enqueue:^{
        if(completedStatus) {
            NSArray *jobs=mp4LibraryQueueJobs();NSString *error=nil;
            NSDictionary *status=IDMP4LibraryStatus(IDNativeDataDirectory().stringByResolvingSymlinksInPath,
                jobs,mp4PersistentExportDirectory,[object[@"offset"]unsignedIntegerValue],&error);
            reply(status!=nil,status,status?nil:error);return;
        }
        if ([action isEqual:@"mp4_cancel"]) {
            typedef void (*Cancel)(void); Cancel cancel = (Cancel)dlsym(RTLD_DEFAULT,"IDMP4SessionCancel");
            if (cancel) cancel(); reply(YES,mp4SessionStatus(),nil); return;
        }
        if ([action isEqual:@"mp4_pause"] || [action isEqual:@"mp4_resume"]) {
            BOOL applied = mp4SetUserPaused([action isEqual:@"mp4_pause"]);
            reply(applied,applied ? mp4SessionStatus() : nil,applied ? nil : @"mp4_unavailable"); return;
        }
        if (!start && !queueAction) { reply(YES,mp4SessionStatus(),nil); return; }
        if(mp4SaveLease && (start || [action isEqual:@"mp4_queue_run"] || [action isEqual:@"mp4_queue_resume"])) {
            reply(NO,nil,@"mp4_save_busy");return;
        }
        NSString *error = nil;
        if (!mp4EnsureConfiguration(queueAction,&error)) { reply(NO,nil,error); return; }
        if (queueAction) {
            if ([action isEqual:@"mp4_queue_status"]) { reply(YES,mp4QueueStatus(),nil); return; }
            int accepted = -1;
            if (enqueue) {
                typedef int (*Enqueue)(uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t);
                Enqueue add = (Enqueue)dlsym(RTLD_DEFAULT,"IDMP4QueueEnqueueV2");
                if (add) accepted = add([object[@"fps"] unsignedIntValue],1,[object[@"video_codec"] unsignedIntValue],[object[@"video_bitrate"] unsignedIntValue],192000,
                    dimensions ? [object[@"width"] unsignedIntValue] : 0,dimensions ? [object[@"height"] unsignedIntValue] : 0);
            } else if ([@[@"mp4_queue_run",@"mp4_queue_pause",@"mp4_queue_resume"] containsObject:action]) {
                if (([action isEqual:@"mp4_queue_run"] || [action isEqual:@"mp4_queue_resume"]) && ![mp4QueueStatus()[@"can_run"] isEqual:@YES]) {
                    reply(NO,nil,@"mp4_scene_not_ready"); return;
                }
                typedef int (*Control)(void);
                const char *name = [action isEqual:@"mp4_queue_run"] ? "IDMP4QueueRun" : [action isEqual:@"mp4_queue_pause"] ? "IDMP4QueuePause" : "IDMP4QueueResume";
                Control control = (Control)dlsym(RTLD_DEFAULT,name); if (control) accepted = control();
                if (accepted == 0) mp4SetUserPaused([action isEqual:@"mp4_queue_pause"]);
            } else {
                typedef int (*Command)(int,const char *,int); Command command = (Command)dlsym(RTLD_DEFAULT,"IDMP4QueueCommand");
                int operation = [action isEqual:@"mp4_queue_cancel"] ? 1 : [action isEqual:@"mp4_queue_remove"] ? 2 : [action isEqual:@"mp4_queue_retry"] ? 3 : 4;
                if(operation==2 && mp4SaveLease && [mp4SaveLeaseJob isEqual:object[@"job_id"]]) {
                    reply(NO,nil,@"mp4_save_busy");return;
                }
                if (command) accepted = command(operation,[object[@"job_id"] UTF8String],deleteCompleted ? 1 : move ? [object[@"position"] intValue] : 0);
            }
            reply(accepted == 0,accepted == 0 ? mp4QueueStatus() : nil,accepted == 0 ? nil : @"mp4_queue_busy"); return;
        }
        typedef int (*Start)(uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t);
        Start begin = (Start)dlsym(RTLD_DEFAULT,"IDMP4SessionStartV2");
        if (!begin) { reply(NO,nil,@"mp4_unavailable"); return; }
        if(!IDMP4LibraryBookmark(IDNativeDataDirectory().stringByResolvingSymlinksInPath,mp4ExportDirectory,&error)) {
            reply(NO,nil,error ?: @"mp4_catalog_unavailable");return;
        }
        int accepted = begin([object[@"fps"] unsignedIntValue],1,[object[@"video_codec"] unsignedIntValue],[object[@"video_bitrate"] unsignedIntValue],192000,
            dimensions ? [object[@"width"] unsignedIntValue] : 0,dimensions ? [object[@"height"] unsignedIntValue] : 0);
        if (accepted != 0) { reply(NO,nil,accepted > 0 ? @"mp4_busy" : @"mp4_scene_not_ready"); return; }
        mp4SetUserPaused(NO); reply(YES,mp4SessionStatus(),nil);
    }];
}
static NSURL *mp4ResolveCompleted(NSString *jobID,NSString *exportID,NSString **error,NSString **selectedJob) {
    NSArray *jobs=mp4LibraryQueueJobs();NSString *identifier=exportID;
    if(jobID) {
        for(NSDictionary *row in jobs)if([row[@"job_id"]isEqual:jobID]&&[row[@"state"]isEqual:@"completed"]){identifier=row[@"output_id"];break;}
        if(!identifier){*error=@"mp4_export_not_ready";return nil;}
    } else if(!identifier) {
        NSDictionary *status=mp4SessionStatus();
        if([status[@"phase"]isEqual:@"completed"]&&mp4Identifier(status[@"export_id"]))identifier=status[@"export_id"];
    }
    NSURL *file=IDMP4LibraryFile(IDNativeDataDirectory().stringByResolvingSymlinksInPath,jobs,
        mp4PersistentExportDirectory,identifier,error);
    if(file&&!IDMP4FinishedFile(file.URLByDeletingLastPathComponent.path.fileSystemRepresentation,file.URLByDeletingPathExtension.lastPathComponent.UTF8String))file=nil;
    if(file&&selectedJob) {
        NSString *chosen=file.URLByDeletingPathExtension.lastPathComponent;
        for(NSDictionary *row in jobs)if([row[@"output_id"]isEqual:chosen]&&[row[@"state"]isEqual:@"completed"]){*selectedJob=row[@"job_id"];break;}
    }
    return file;
}
static void mp4ExportResolved(NSString *jobID,NSString *exportID,void (^completion)(NSURL *,NSString *)) {
    if(!worker||(jobID&&!mp4Identifier(jobID))||(exportID&&!mp4Identifier(exportID))){dispatch_async(dispatch_get_main_queue(),^{completion(nil,@"mp4_export_not_ready");});return;}
    [worker enqueue:^{
        NSString *error=nil;NSURL *file=mp4ResolveCompleted(jobID,exportID,&error,NULL);
        dispatch_async(dispatch_get_main_queue(),^{completion(file,file?nil:error ?: @"mp4_export_not_ready");});
    }];
}
void IdolyEmbeddedServerMP4ExportJob(NSString *jobID,void (^completion)(NSURL *,NSString *)) { mp4ExportResolved(jobID,nil,completion); }
void IdolyEmbeddedServerMP4ExportRecord(NSString *exportID,void (^completion)(NSURL *,NSString *)) { mp4ExportResolved(nil,exportID,completion); }
void IdolyEmbeddedServerMP4BeginSave(NSString *jobID,NSString *exportID,void (^completion)(NSURL *,NSString *,uint64_t)) {
    if(!worker||(jobID&&!mp4Identifier(jobID))||(exportID&&!mp4Identifier(exportID))||(jobID&&exportID)){
        dispatch_async(dispatch_get_main_queue(),^{completion(nil,@"mp4_export_not_ready",0);});return;
    }
    [worker enqueue:^{
        if(mp4SaveLease){dispatch_async(dispatch_get_main_queue(),^{completion(nil,@"mp4_save_busy",0);});return;}
        NSString *error=nil,*job=nil;NSURL *file=mp4ResolveCompleted(jobID,exportID,&error,&job);
        uint64_t lease=0;
        if(file){if(++mp4SaveLeaseGeneration==0)++mp4SaveLeaseGeneration;lease=mp4SaveLeaseGeneration;mp4SaveLease=lease;mp4SaveLeaseJob=job;}
        dispatch_async(dispatch_get_main_queue(),^{completion(file,file?nil:error ?: @"mp4_export_not_ready",lease);});
    }];
}
void IdolyEmbeddedServerMP4EndSave(uint64_t lease) {
    if(!worker||!lease)return;
    [worker enqueue:^{if(mp4SaveLease==lease){mp4SaveLease=0;mp4SaveLeaseJob=nil;}}];
}
void IdolyEmbeddedServerMP4Export(void (^completion)(NSURL *,NSString *)) { IdolyEmbeddedServerMP4ExportJob(nil,completion); }
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
    // No interpreter, payload reads, UIKit UI, or waiting under dyld.
    // Foundation reads the small packaged attestation before entry interception.
    NSString *earlyError = nil;
    earlyHostInstalled = IDUnityHostInstall(unityHostReady, &earlyError);
    installGate();
    if (!earlyHostInstalled)
        hookError = @"이 게임의 초기 시작 경로를 확인하지 못했습니다. 서버는 독립적으로 시작합니다.";
    dispatch_async(dispatch_get_main_queue(), ^{
        if (!worker) worker = [IDServerWorker new];
        IDNativeInstallSettings();
        IDNativeSetGameStartAvailable(earlyHostInstalled && hookInstalled && gate.captured && !gate.forwarded);
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
