// Optional, account-free loopback transport. Unity calls stay on its own thread.
#include "settings_json.hpp"
#include "playback_json.hpp"
namespace {
double monotonic_seconds() {
    timespec tick{};
    return clock_gettime(6,&tick)==0 ? tick.tv_sec+tick.tv_nsec/1000000000.0 : -1;
}
bool send_all(int fd, const char *data, size_t size) {
    while (size) { long n=send(fd,data,size,0); if (n<=0) return false; data+=n; size-=n; }
    return true;
}
bool exchange_http(const char *method, const char *path, const char *body, char *output, size_t capacity) {
    if (capacity<2) return false;
    const double begun=monotonic_seconds(); if (begun<0) return false;
    const int fd=socket(2,1,0); if (fd<0) return false;
    struct Close { int fd; ~Close() { close(fd); } } guard{fd};
    timeval timeout{1,0}; int no_signal=1;
    if (setsockopt(fd,0xffff,0x1006,&timeout,sizeof timeout)
            || setsockopt(fd,0xffff,0x1005,&timeout,sizeof timeout)
            || setsockopt(fd,0xffff,0x1022,&no_signal,sizeof no_signal)) return false;
    sockaddr_in address{16,2,0x901f,0x0100007f,{0}}; // 127.0.0.1:8080, network byte order.
    if (connect(fd,reinterpret_cast<const sockaddr *>(&address),sizeof address)) return false;
    const size_t length=body?std::strlen(body):0;
    char header[384]; int written=std::snprintf(header,sizeof header,
        "%s %s HTTP/1.0\r\nHost: 127.0.0.1:8080\r\nConnection: close\r\n"
        "Content-Type: application/json\r\nContent-Length: %llu\r\n\r\n",method,path,static_cast<unsigned long long>(length));
    if (written<0 || static_cast<size_t>(written)>=sizeof header
            || !send_all(fd,header,written) || (length && !send_all(fd,body,length))) return false;
    // The server uses Content-Length and closes this HTTP/1.0 connection.
    // A bounded whole response also rejects overlong/truncated messages.
    char response[12289]; size_t used=0;
    while (used<sizeof response-1) {
        if (monotonic_seconds()-begun>2) return false;
        long n=recv(fd,response+used,sizeof response-1-used,0);
        if (n==0) break;
        if (n<0) return false; used+=n;
    }
    if (used==sizeof response-1) return false; response[used]=0;
    if (std::strncmp(response,"HTTP/1.0 200 ",13) && std::strncmp(response,"HTTP/1.1 200 ",13)) return false;
    char *separator=strstr(response,"\r\n\r\n"); if (!separator || separator-response>4096) return false;
    char *payload=separator+4; const size_t bytes=response+used-payload;
    if (!bytes || bytes>8192 || bytes>=capacity) return false;
    for (size_t i=0;i<bytes;++i) if (!payload[i]) return false;
    // A substring search cannot confuse JSON body fields with headers here.
    *separator=0;
    const char *cl=strstr(response,"\r\nContent-Length: ");
    if (!cl) return false; cl+=18;
    size_t declared=0; unsigned digits=0;
    while (*cl>='0'&&*cl<='9') { if (++digits>5) return false; declared=declared*10+(*cl++-'0'); }
    if (!digits || (*cl && (cl[0]!='\r'||cl[1]!='\n')) || declared!=bytes) return false;
    std::memcpy(output,payload,bytes); output[bytes]=0; return true;
}
void *presentation_poll(void *) {
    for (;;) {
        char settings[8193];
        if (exchange_http("GET","/client/presentation",nullptr,settings,sizeof settings)) {
            Config next;
            if (decode_settings(settings,&next) && accept_configuration(1,next)) {
                char report[1024], accepted[256]; status_json(report,sizeof report);
                exchange_http("POST","/client/presentation/status",report,accepted,sizeof accepted);
            }
        }
        // A missing/failed graphics endpoint must not suppress playback
        // preferences. Failed or rejected reads never publish a fallback value.
        if (exchange_http("GET","/client/playback",nullptr,settings,sizeof settings)) {
            PlaybackConfigMessage next;
            if (decode_playback_settings(settings,&next)
                    && accept_playback_configuration(1,next.revision,next.wait_for_orientation)) {
                char report[512], accepted[256]; playback_status_json(report,sizeof report);
                exchange_http("POST","/client/playback/status",report,accepted,sizeof accepted);
            }
        }
        pause_ms(2000);
    }
}
__attribute__((constructor)) void start_presentation() {
    if (started.exchange(true)) return;
    pthread_t installer, poller;
    if (pthread_create(&installer,nullptr,install,nullptr)) { set_state("init_failed"); return; }
    pthread_detach(installer);
    if (!pthread_create(&poller,nullptr,presentation_poll,nullptr)) pthread_detach(poller);
    else set_state("init_failed");
}
}
