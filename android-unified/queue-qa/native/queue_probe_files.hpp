// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
#include <dirent.h>
#include <string.h>
#include <stdexcept>

namespace idoly_queue_storage_qa {
inline bool no_temporary_files(const char* path) {
    DIR* dir = opendir(path);
    if (!dir) throw std::runtime_error("list_case");
    bool good = true;
    while (dirent* item = readdir(dir)) {
        // This persistent lock is owned and validated separately. Every other
        // .queue- entry remains forbidden, including malformed temporary names.
        if (!strcmp(item->d_name, ".queue-v1.lock")) continue;
        if (!strncmp(item->d_name, ".queue-", 7)) good = false;
    }
    closedir(dir); return good;
}
}
