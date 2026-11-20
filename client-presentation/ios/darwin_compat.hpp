// Public arm64 Darwin ABI used by the SDK-free build. No Apple SDK is bundled.
#pragma once
using size_t = __SIZE_TYPE__;
using intptr_t = __INTPTR_TYPE__;
using uintptr_t = __UINTPTR_TYPE__;
using uint8_t = unsigned char;
using uint16_t = unsigned short;
using uint32_t = unsigned int;
using int32_t = int;
using uint64_t = unsigned long long;
using int64_t = long long;
using pthread_t = struct _opaque_pthread_t *;
struct pthread_mutex_t { long signature; char opaque[56]; };
#define PTHREAD_MUTEX_INITIALIZER {0x32AAABA7, {0}}
struct timespec { long tv_sec; long tv_nsec; };
struct timeval { long tv_sec; int tv_usec; };
// Public arm64 Darwin stat layout (144 bytes); no platform SDK is required.
struct stat {
    int32_t st_dev; uint16_t st_mode,st_nlink; uint64_t st_ino;
    uint32_t st_uid,st_gid; int32_t st_rdev;
    timespec st_atimespec,st_mtimespec,st_ctimespec,st_birthtimespec;
    int64_t st_size,st_blocks; int32_t st_blksize; uint32_t st_flags,st_gen;
    int32_t st_lspare; int64_t st_qspare[2];
};
static_assert(sizeof(stat)==144 && __builtin_offsetof(stat,st_mode)==4
    && __builtin_offsetof(stat,st_nlink)==6 && __builtin_offsetof(stat,st_ino)==8
    && __builtin_offsetof(stat,st_mtimespec)==48 && __builtin_offsetof(stat,st_ctimespec)==64
    && __builtin_offsetof(stat,st_size)==96,"Public Darwin arm64 stat ABI differs");
struct sockaddr { uint8_t length, family; char data[14]; };
struct sockaddr_in { uint8_t length, family; uint16_t port; uint32_t address; char zero[8]; };
extern "C" {
void *memcpy(void *, const void *, size_t);
void *memset(void *, int, size_t);
int memcmp(const void *, const void *, size_t);
int strcmp(const char *, const char *);
int strncmp(const char *, const char *, size_t);
size_t strlen(const char *);
char *strstr(const char *, const char *);
int snprintf(char *, size_t, const char *, ...);
double strtod(const char *, char **);
double atan(double); double tan(double); double round(double);
long lround(double); long long llround(double);
int pthread_mutex_lock(pthread_mutex_t *);
int pthread_mutex_unlock(pthread_mutex_t *);
pthread_t pthread_self();
int pthread_create(pthread_t *, const void *, void *(*)(void *), void *);
int pthread_detach(pthread_t);
int nanosleep(const timespec *, timespec *);
int clock_gettime(unsigned int, timespec *);
int socket(int, int, int);
int setsockopt(int, int, int, const void *, unsigned int);
int connect(int, const sockaddr *, unsigned int);
long send(int, const void *, size_t, int);
long recv(int, void *, size_t, int);
int close(int);
int open(const char *,int,...);
int openat(int,const char *,int,...);
long read(int,void *,size_t);
long write(int,const void *,size_t);
int renameat(int,const char *,int,const char *);
int unlinkat(int,const char *,int);
int fsync(int);
void arc4random_buf(void *,size_t);
int fstat(int,struct stat *);
int dup(int);
uint32_t geteuid();
uint32_t _dyld_image_count();
const char *_dyld_get_image_name(uint32_t);
const void *_dyld_get_image_header(uint32_t);
intptr_t _dyld_get_image_vmaddr_slide(uint32_t);
}
namespace std {
template<class T> class initializer_list {
    const T *first; size_t count;
public:
    constexpr initializer_list() : first(nullptr), count(0) {}
    constexpr initializer_list(const T *first, size_t count) : first(first), count(count) {}
    constexpr const T *begin() const { return first; }
    constexpr const T *end() const { return first+count; }
    constexpr size_t size() const { return count; }
};
using ::int64_t; using ::memcpy; using ::memset; using ::memcmp; using ::strcmp; using ::strlen;
using ::snprintf; using ::strncmp; using ::atan; using ::tan; using ::round; using ::lround; using ::llround;
inline bool isfinite(double value) { return __builtin_isfinite(value); }
inline double fabs(double value) { return __builtin_fabs(value); }
inline float fabs(float value) { return __builtin_fabsf(value); }
template<class T> constexpr const T &min(const T &a, const T &b) { return b < a ? b : a; }
template<class T> constexpr const T &max(const T &a, const T &b) { return a < b ? b : a; }
template<class T> constexpr T max(initializer_list<T> values) { T result=*values.begin(); for (const T &value:values) if (result<value) result=value; return result; }
template<class T> constexpr const T &clamp(const T &a, const T &lo, const T &hi) { return min(max(a, lo), hi); }
enum memory_order { memory_order_acquire=__ATOMIC_ACQUIRE,
    memory_order_release=__ATOMIC_RELEASE, memory_order_acq_rel=__ATOMIC_ACQ_REL };
template<class T> class atomic {
    alignas(sizeof(T)) T value;
public:
    constexpr atomic(T initial = T{}) : value(initial) {}
    T load(int order = __ATOMIC_SEQ_CST) const { return __atomic_load_n(&value, order); }
    void store(T next, int order = __ATOMIC_SEQ_CST) { __atomic_store_n(&value, next, order); }
    T exchange(T next, int order = __ATOMIC_SEQ_CST) { return __atomic_exchange_n(&value, next, order); }
    bool compare_exchange_strong(T &expected, T next, int order) {
        return __atomic_compare_exchange_n(&value, &expected, next, false, order, __ATOMIC_ACQUIRE);
    }
    atomic(const atomic &) = delete;
    atomic &operator=(const atomic &) = delete;
};
}
