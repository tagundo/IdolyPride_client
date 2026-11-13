#pragma once

namespace idoly::presentation::bulk_checked_filter {
using Method = const void;
using Predicate = bool (*)(void *, void *, Method *);
using Checked = bool (*)(void *, Method *);

// The original predicate owns the character match and exception semantics.
// Only an already acknowledged row is removed from the original CheckBulk
// request. Unchecked client rows still reach the server after a lost reply.
inline bool filter(void *self, void *row, Method *method, Predicate original,
                   Checked checked, bool enabled) {
    const bool matches = original(self, row, method);
    if (!matches || !enabled || !self || !row || !checked) return matches;
    try {
        // Concrete 6.1.1 getters are read-only, eight-byte leaves whose
        // MethodInfo argument is unused. They must never be inline-hooked.
        return !checked(row, nullptr);
    } catch (...) {
        // Optional filtering must not turn a successful original match into
        // a failed request when the additional getter is unavailable.
        return matches;
    }
}
} // namespace idoly::presentation::bulk_checked_filter
