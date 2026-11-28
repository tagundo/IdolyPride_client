#define IDOLY_HTTP_POLICY_ONLY 1
#include "../IdolyHTTP.h"
#include <assert.h>
#include <stdio.h>

int main(void) {
    const char *host = "d2ilil7yh5oi1v.cloudfront.net";
    assert(IDHTTPAllowedOriginParts("https", host, -1, 0, 0, 0));
    assert(IDHTTPAllowedOriginParts("https", host, 443, 0, 0, 0));
    assert(!IDHTTPAllowedOriginParts("http", host, -1, 0, 0, 0));
    assert(!IDHTTPAllowedOriginParts("file", host, -1, 0, 0, 0));
    assert(!IDHTTPAllowedOriginParts("https", "d2ilil7yh5oi1v.cloudfront.net.evil.test", 443, 0, 0, 0));
    assert(!IDHTTPAllowedOriginParts("https", "evil-d2ilil7yh5oi1v.cloudfront.net", 443, 0, 0, 0));
    assert(!IDHTTPAllowedOriginParts("https", "127.0.0.1", 443, 0, 0, 0));
    assert(!IDHTTPAllowedOriginParts("https", host, 80, 0, 0, 0));
    assert(!IDHTTPAllowedOriginParts("https", host, 0, 0, 0, 0));
    assert(!IDHTTPAllowedOriginParts("https", host, 8443, 0, 0, 0));
    assert(!IDHTTPAllowedOriginParts("https", host, 443, 1, 0, 0));
    assert(!IDHTTPAllowedOriginParts("https", host, 443, 0, 1, 0));
    assert(!IDHTTPAllowedOriginParts("https", host, 443, 0, 0, 1));
    assert(!IDHTTPAllowedOriginParts(NULL, host, 443, 0, 0, 0));
    assert(!IDHTTPAllowedOriginParts("https", NULL, 443, 0, 0, 0));
    puts("PASS: HTTP exact-origin policy (15 cases)");
    return 0;
}
