/* SPDX-License-Identifier: AGPL-3.0-or-later */
#include "idoly_live.h"
#include <assert.h>
#include <string.h>

int main(void) {
    assert(IdolyLiveABIVersion() == 1);
    const char input[] = "{}";
    void *result = NULL, *failure = NULL;
    size_t result_len = 0, failure_len = 0;
    int code = IdolyLiveSimulate(input, strlen(input), &result, &result_len, &failure, &failure_len);
    assert(code == 1 && result == NULL && result_len == 0);
    assert(failure != NULL && failure_len > 0);
    IdolyLiveFree(result);
    IdolyLiveFree(failure);
    IdolyLiveFree(NULL);
    return 0;
}
