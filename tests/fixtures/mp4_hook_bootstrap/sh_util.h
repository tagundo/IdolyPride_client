#pragma once
#include <stdint.h>
#include <stddef.h>
#define SH_UTIL_GET_BITS_32(v,h,l) (((uint32_t)(v)>>(l))&((UINT32_C(1)<<((h)-(l)+1))-1))
#define SH_UTIL_SIGN_EXTEND_64(v,n) ((uint64_t)(((int64_t)((uint64_t)(v)<<(64-(n))))>>(64-(n))))
static inline void sh_util_clear_cache(uintptr_t p,size_t n){(void)p;(void)n;}
