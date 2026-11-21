#pragma once
#include <string.h>

/* Native URL parsing canonicalizes scheme/host before this exact-origin
 * decision. Keep it portable so rejected-origin cases run without an SDK. */
static inline int IDHTTPAllowedOriginParts(const char *scheme, const char *host,
                                         long port, int has_user, int has_password,
                                         int has_fragment) {
    return scheme && host && !strcmp(scheme, "https") &&
        !strcmp(host, "d2ilil7yh5oi1v.cloudfront.net") &&
        (port == -1 || port == 443) && !has_user && !has_password && !has_fragment;
}

#ifndef IDOLY_HTTP_POLICY_ONLY
#include <Python.h>

/* Call with the GIL held. The private response type is not user-constructible. */
int IDHTTPPrepareTypes(void);
PyObject *IDOpenURL(PyObject *module, PyObject *args, PyObject *kwargs);
#endif
