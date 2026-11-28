#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
typedef struct {uintptr_t addr;size_t size;unsigned type;} sh_island_t;
typedef struct {int unused;} sh_addr_info_t;
typedef struct {uintptr_t start_addr,end_addr;uint32_t*buf;size_t buf_offset,inst_prolog_len,inst_lens[6],inst_lens_cnt;sh_island_t*island_rewrite;sh_addr_info_t*addr_info;}sh_a64_rewrite_info_t;
size_t sh_a64_get_rewrite_inst_len(uint32_t,bool);size_t sh_a64_rewrite(uint32_t*,uint32_t,uintptr_t,sh_a64_rewrite_info_t*);
size_t sh_a64_absolute_jump_with_br_ip(uint32_t*,uintptr_t);size_t sh_a64_absolute_jump_with_ret_ip(uint32_t*,uintptr_t);size_t sh_a64_restore_ip(uint32_t*);
size_t sh_a64_absolute_jump_with_br_rx(uint32_t*,uintptr_t);size_t sh_a64_absolute_jump_with_ret_rx(uint32_t*,uintptr_t);size_t sh_a64_restore_rx(uint32_t*);size_t sh_a64_relative_jump(uint32_t*,uintptr_t,uintptr_t);size_t sh_a64_nop(uint32_t*);
void sh_island_alloc(sh_island_t*,size_t,uintptr_t,uintptr_t,uintptr_t,sh_addr_info_t*,void*);
