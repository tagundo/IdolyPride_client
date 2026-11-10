/* SPDX-License-Identifier: AGPL-3.0-or-later
 * Stable ABI v1. Do not use generated Go helper types as the public interface.
 */
#ifndef IDOLY_LIVE_H
#define IDOLY_LIVE_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
uint32_t IdolyLiveABIVersion(void);
/* 0 OK, 1 invalid input, 2 unsupported definition, 3 deadline, 4 internal error.
 * All four output arguments must point to valid, distinct slots. On success,
 * output owns exactly
 * outputLen bytes of api.LiveResult protobuf; failure is null/0. On failure,
 * failure owns exactly failureLen UTF-8 bytes; output is null/0.
 * Buffers are not NUL-terminated. Free each nonnull buffer exactly once through
 * IdolyLiveFree. Input is copied synchronously and remains caller-owned.
 */
int IdolyLiveSimulate(const void *input, size_t inputLen,
                     void **output, size_t *outputLen,
                     void **failure, size_t *failureLen);
void IdolyLiveFree(void *buffer);
#ifdef __cplusplus
}
#endif
#endif
