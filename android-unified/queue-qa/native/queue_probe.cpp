// SPDX-License-Identifier: AGPL-3.0-or-later
#include <jni.h>
#include <sys/syscall.h>
#include <dirent.h>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
#include "mp4_queue.hpp"
#include "queue_probe_files.hpp"

#ifndef IDOLY_QUEUE_SOURCE_SHA256
#error Verified production source identity required
#endif
#ifndef IDOLY_QUEUE_SNAPSHOT_SHA256
#error Verified complete probe snapshot required
#endif

namespace {
namespace q = idoly_mp4_queue;
using std::string;
const char* profile = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
void require(bool value, const char* token) { if (!value) throw std::runtime_error(token); }
string quote(const string& value) {
    string out = "\"";
    for (unsigned char c : value) {
        if (c == '\\' || c == '"') { out += '\\'; out += c; }
        else if (c >= 32 && c < 127) out += c;
        else out += '?';
    }
    return out + "\"";
}
struct Json {
    string fields;
    void add(const char* key, const string& raw) { if (!fields.empty()) fields += ','; fields += quote(key) + ':' + raw; }
    void text(const char* key, const string& value) { add(key, quote(value)); }
    void number(const char* key, long value) { add(key, std::to_string(value)); }
    void yes(const char* key, bool value) { add(key, value ? "true" : "false"); }
    string str() const { return '{' + fields + '}'; }
};
string read_file(const string& path, size_t maximum = 1024 * 1024) {
    int fd = open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    require(fd >= 0, "read_open");
    string out; char bytes[4096]; ssize_t n;
    while ((n = read(fd, bytes, sizeof(bytes))) > 0) { out.append(bytes, n); if (out.size() > maximum) break; }
    const bool good = n == 0 && out.size() <= maximum; close(fd); require(good, "bounded_read"); return out;
}
void create_file(const string& path, const string& value) {
    int fd = open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    require(fd >= 0, "create_file");
    const bool good = write(fd, value.data(), value.size()) == static_cast<ssize_t>(value.size()) && fsync(fd) == 0;
    close(fd); require(good, "write_file");
}
bool absent(const string& path) { struct stat s{}; return lstat(path.c_str(), &s) == -1 && errno == ENOENT; }
bool safe(const string& path) {
    struct stat s{}; return lstat(path.c_str(), &s) == 0 && S_ISREG(s.st_mode)
        && (s.st_mode & 0777) == 0600 && s.st_uid == geteuid() && s.st_nlink == 1;
}
string directory(const string& root, const char* name) {
    string out = root + '/' + name; require(mkdir(out.c_str(), 0700) == 0, "fresh_case_directory"); return out;
}
bool no_temporary_files(const string& path) {
    return idoly_queue_storage_qa::no_temporary_files(path.c_str());
}
std::unique_ptr<q::Descriptor> descriptor() {
    auto out = std::make_unique<q::Descriptor>();
    strcpy(out->stage_asset, "queue_qa_stage"); strcpy(out->timeline_asset, "queue_qa_timeline");
    out->actor_count = 1; strcpy(out->actors[0].character_id, "qa_actor");
    out->actors[0].asset_count = 1; strcpy(out->actors[0].assets[0], "qa_body"); return out;
}
q::Options options() { q::Options out{}; out.width = 160; out.height = 96; return out; }
void result(Json& row, q::Queue& queue, q::Error error) {
    row.text("queue_error", q::error_code(error)); row.text("storage_stage", queue.storage_stage());
    row.number("storage_errno", queue.storage_errno());
}
template<class Work> void run_case(std::vector<string>& cases, const char* name, Work work) {
    Json row; row.text("name", name); row.yes("required", true);
    try { work(row); row.text("status", "passed"); }
    catch (const std::exception& error) { row.text("status", "failed"); row.text("error", error.what()); }
    cases.push_back(row.str());
}
string run(const string& root, const string& challenge) {
    Json report; report.number("uid", getuid()); report.number("euid", geteuid()); report.number("pid", getpid());
    report.text("challenge", challenge); report.text("production_queue_sha256", IDOLY_QUEUE_SOURCE_SHA256);
    report.text("source_snapshot_sha256", IDOLY_QUEUE_SNAPSHOT_SHA256);
    string context = read_file("/proc/self/attr/current", 512);
    while (!context.empty() && (context.back() == '\n' || context.back() == '\0')) context.pop_back();
    report.text("selinux_context", context);
    // Android may deny untrusted_app reads of selinuxfs/enforce. Preserve that
    // exact result instead of claiming the app observed an enforcing value.
    // The host gate independently requires getenforce=Enforcing before/after.
    report.text("selinux_enforcement_source", "app_selinuxfs_enforce");
    int enforcing_fd = open("/sys/fs/selinux/enforce", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    int enforcing_error = enforcing_fd < 0 ? errno : 0;
    string enforcing;
    if (enforcing_fd >= 0) {
        char bytes[16]; const ssize_t n = read(enforcing_fd, bytes, sizeof(bytes));
        if (n < 0) enforcing_error = errno;
        else enforcing.assign(bytes, static_cast<size_t>(n));
        close(enforcing_fd);
    }
    report.number("selinux_enforce_read_errno", enforcing_error);
    if (enforcing_error) {
        report.text("selinux_enforce_read_status", "unavailable"); report.add("selinux_enforcing", "null");
        require(enforcing_error == EPERM || enforcing_error == EACCES, "unexpected_enforce_read_error");
    } else {
        report.text("selinux_enforce_read_status", "read");
        const bool enforced = enforcing == "1" || enforcing == "1\n";
        report.yes("selinux_enforcing", enforced); require(enforced, "app_observed_selinux_not_enforcing");
    }
    const uid_t appid = getuid() % 100000;
    require(getuid() == geteuid() && appid >= 10000 && appid < 20000, "ordinary_app_uid_required");
    require(context.find("u:r:untrusted_app") == 0, "untrusted_app_required");
    struct stat root_stat{}; require(lstat(root.c_str(), &root_stat) == 0 && S_ISDIR(root_stat.st_mode)
        && root_stat.st_uid == getuid() && (root_stat.st_mode & 0777) == 0700, "private_root_required");
    report.yes("private_storage_owner_mode", true);
    std::vector<string> cases;
    run_case(cases, "legacy_hardlink_denied", [&](Json& row) {
        string dir = directory(root, "hardlink"), source = dir + "/source", target = dir + "/target";
        create_file(source, "legacy-source"); int fd = open(dir.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
        require(fd >= 0, "legacy_directory"); errno = 0;
        int rc = linkat(fd, "source", fd, "target", 0), number = rc < 0 ? errno : 0; close(fd);
        row.number("return", rc); row.number("errno", number);
        const bool preserved = absent(target) && read_file(source) == "legacy-source" && safe(source);
        row.yes("source_preserved_target_absent", preserved);
        require(rc == -1 && (number == EPERM || number == EACCES) && preserved, "legacy_linkat_must_be_policy_denied");
    });
    run_case(cases, "install_new_no_clobber", [&](Json& row) {
        string dir = directory(root, "noreplace"), source = dir + "/source", target = dir + "/target";
        create_file(source, "new-source"); create_file(target, "existing-target");
        int fd = open(dir.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW); require(fd >= 0, "install_directory");
        errno = 0; int rc = q::detail::install_new(fd, "source", "target"), number = rc < 0 ? errno : 0;
        row.number("existing_return", rc); row.number("existing_errno", number);
        bool preserved = read_file(source) == "new-source" && read_file(target) == "existing-target" && safe(source) && safe(target);
        row.yes("both_existing_files_preserved", preserved);
        errno = 0; int fresh = q::detail::install_new(fd, "source", "fresh"), fresh_errno = fresh < 0 ? errno : 0; close(fd);
        row.number("fresh_return", fresh); row.number("fresh_errno", fresh_errno);
        bool installed = absent(source) && read_file(dir + "/fresh") == "new-source" && safe(dir + "/fresh");
        row.yes("fresh_single_link_install", installed);
        require(rc == -1 && number == EEXIST && preserved && fresh == 0 && fresh_errno == 0 && installed, "rename_noreplace_contract");
    });
    run_case(cases, "queue_roundtrip", [&](Json& row) {
        string dir = directory(root, "roundtrip"); q::Queue queue; auto d = descriptor(); char first[33]{}, second[33]{};
        require(queue.open(dir.c_str(), profile) == q::Error::ok, "open_empty");
        const string lock = dir + "/.queue-v1.lock"; struct stat lock_identity{};
        require(lstat(lock.c_str(), &lock_identity) == 0 && safe(lock) && lock_identity.st_size == 0, "initial_lock_identity");
        q::Error error = queue.enqueue(*d, options(), first); result(row, queue, error); require(error == q::Error::ok, "first_enqueue");
        require(queue.count() == 1 && queue.generation() == 1 && safe(dir + "/queue-v1.bin"), "first_commit_identity");
        queue.close(); require(queue.open(dir.c_str(), profile) == q::Error::ok && queue.find(first), "first_reopen");
        require(!strcmp(queue.find(first)->descriptor.timeline_asset, "queue_qa_timeline"), "descriptor_roundtrip");
        error = queue.enqueue(*d, options(), second); require(error == q::Error::ok && strcmp(first, second), "replacement_enqueue");
        queue.close(); require(queue.open(dir.c_str(), profile) == q::Error::ok && queue.count() == 2 && queue.generation() == 2
            && queue.find(first) && queue.find(second), "second_reopen");
        row.number("reopened_count", queue.count()); row.number("generation", queue.generation());
        row.yes("descriptor_preserved", true); row.yes("private_single_link_journal", safe(dir + "/queue-v1.bin"));
        struct stat final_lock{};
        const bool lock_preserved = lstat(lock.c_str(), &final_lock) == 0 && safe(lock) && final_lock.st_size == 0
            && final_lock.st_dev == lock_identity.st_dev && final_lock.st_ino == lock_identity.st_ino;
        row.yes("private_zero_byte_single_link_lock_preserved", lock_preserved);
        row.yes("temporary_files_absent", no_temporary_files(dir));
        require(safe(dir + "/queue-v1.bin") && lock_preserved && no_temporary_files(dir), "queue_storage_identity");
    });
    run_case(cases, "queue_existing_target_rejected", [&](Json& row) {
        string dir = directory(root, "existing"); q::Queue queue; auto d = descriptor(); char id[33]{};
        require(queue.open(dir.c_str(), profile) == q::Error::ok, "open_before_existing");
        create_file(dir + "/queue-v1.bin", "existing-owner-sentinel");
        q::Error error = queue.enqueue(*d, options(), id); result(row, queue, error);
        bool preserved = read_file(dir + "/queue-v1.bin") == "existing-owner-sentinel" && safe(dir + "/queue-v1.bin");
        row.yes("sentinel_preserved", preserved); row.yes("state_unmodified", queue.count() == 0 && queue.generation() == 0);
        require(error == q::Error::changed_storage && preserved && queue.count() == 0 && queue.generation() == 0, "queue_existing_target_clobbered");
    });
    for (const char* kind : {"journal_symlink_rejected", "lock_symlink_rejected"}) run_case(cases, kind, [&](Json& row) {
        string dir = directory(root, kind), sentinel = dir + "/sentinel";
        create_file(sentinel, "symlink-owner-sentinel");
        string target = dir + (kind[0] == 'j' ? "/queue-v1.bin" : "/.queue-v1.lock");
        require(symlink("sentinel", target.c_str()) == 0, "create_symlink");
        q::Queue queue; q::Error error = queue.open(dir.c_str(), profile); result(row, queue, error);
        struct stat s{}; bool preserved = read_file(sentinel) == "symlink-owner-sentinel" && lstat(target.c_str(), &s) == 0 && S_ISLNK(s.st_mode);
        row.yes("symlink_and_sentinel_preserved", preserved);
        require(error == q::Error::unsafe_storage && preserved, "symlink_not_rejected");
    });
    run_case(cases, "journal_tamper_rejected", [&](Json& row) {
        string dir = directory(root, "tamper"), journal = dir + "/queue-v1.bin";
        q::Queue queue; auto d = descriptor(); char id[33]{};
        require(queue.open(dir.c_str(), profile) == q::Error::ok && queue.enqueue(*d, options(), id) == q::Error::ok, "tamper_seed");
        string original = read_file(journal); int fd = open(journal.c_str(), O_WRONLY | O_NOFOLLOW); require(fd >= 0, "tamper_open");
        // Force a distinct identity timestamp as well as changing journal bytes;
        // this avoids depending on the filesystem's timestamp update resolution.
        struct stat identity{}; require(fstat(fd, &identity) == 0, "tamper_identity");
        timespec timestamps[2] = {{0, UTIME_OMIT}, {identity.st_mtim.tv_sec + 1, identity.st_mtim.tv_nsec}};
        const char byte = 'X'; bool wrote = pwrite(fd, &byte, 1, 0) == 1 && futimens(fd, timestamps) == 0 && fsync(fd) == 0;
        close(fd); require(wrote, "tamper_write");
        q::Error error = queue.enqueue(*d, options(), id); result(row, queue, error);
        string tampered = original; tampered[0] = byte; bool preserved = read_file(journal) == tampered;
        row.yes("tampered_bytes_preserved", preserved); row.yes("state_unmodified", queue.count() == 1 && queue.generation() == 1);
        require(error == q::Error::changed_storage && preserved && queue.count() == 1 && queue.generation() == 1, "live_tamper_not_rejected");
        queue.close(); q::Error reopened = queue.open(dir.c_str(), profile); row.text("reopen_error", q::error_code(reopened));
        require(reopened == q::Error::corrupt && read_file(journal) == tampered, "corrupt_reopen_not_rejected");
    });
    string array = "["; for (const string& row : cases) { if (array.size() > 1) array += ','; array += row; } array += ']';
    report.add("cases", array); return report.str();
}
}

extern "C" JNIEXPORT jstring JNICALL
Java_game_qualiarts_idolypride_queueqa_QueueProbeActivity_probe(JNIEnv* env, jclass, jstring root, jstring challenge) {
    const char* path = env->GetStringUTFChars(root, nullptr); if (!path) return nullptr;
    const char* token = env->GetStringUTFChars(challenge, nullptr); if (!token) { env->ReleaseStringUTFChars(root, path); return nullptr; }
    string report;
    try { report = run(path, token); }
    catch (const std::exception& error) { Json failure; failure.text("error", error.what()); report = failure.str(); }
    env->ReleaseStringUTFChars(root, path); env->ReleaseStringUTFChars(challenge, token);
    return env->NewStringUTF(report.c_str());
}
