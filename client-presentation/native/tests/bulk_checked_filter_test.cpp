#include "../bulk_checked_filter.hpp"
#include <cassert>
#include <stdexcept>

using namespace idoly::presentation::bulk_checked_filter;

namespace {
struct Row { bool checked; };
void *expected_self = reinterpret_cast<void *>(0x1010);
void *expected_row = nullptr;
Method *expected_method = reinterpret_cast<Method *>(0x3030);
bool original_matches = true, original_throws = false, getter_throws = false;
int original_calls = 0, getter_calls = 0, step = 0;
const std::runtime_error original_error("original predicate error");
const std::runtime_error getter_error("optional getter error");

bool original(void *self, void *row, Method *method) {
    ++original_calls;
    assert(step++ == 0);
    assert(self == expected_self && row == expected_row && method == expected_method);
    if (original_throws) throw &original_error;
    return original_matches;
}
bool checked(void *row, Method *method) {
    ++getter_calls;
    assert(step++ == 1);
    assert(row == expected_row && method == nullptr);
    if (getter_throws) throw &getter_error;
    return static_cast<Row *>(row)->checked;
}
bool invoke(void *self, void *row, bool enabled = true, Checked getter = checked) {
    expected_self = self;
    expected_row = row;
    step = 0;
    return filter(self, row, expected_method, original, getter, enabled);
}
} // namespace

int main() {
    Row row{false};
    void *self = expected_self;
    assert(invoke(self, &row));
    assert(original_calls == 1 && getter_calls == 1 && !row.checked);

    row.checked = true;
    assert(!invoke(self, &row));
    assert(original_calls == 2 && getter_calls == 2 && row.checked);

    // A reply lost before the client applies checked=true leaves this row
    // unchecked. It must be sent again even if the server already checked it.
    row.checked = false;
    assert(invoke(self, &row));
    assert(original_calls == 3 && getter_calls == 3 && !row.checked);

    original_matches = false;
    row.checked = true;
    assert(!invoke(self, &row));
    assert(original_calls == 4 && getter_calls == 3);
    original_matches = true;

    assert(invoke(self, &row, false));
    assert(invoke(nullptr, &row));
    assert(invoke(self, nullptr));
    assert(invoke(self, &row, true, nullptr));
    assert(original_calls == 8 && getter_calls == 3);

    getter_throws = true;
    assert(invoke(self, &row));
    assert(original_calls == 9 && getter_calls == 4 && row.checked);
    getter_throws = false;

    // The added catch is deliberately outside the original invocation.
    original_throws = true;
    try {
        invoke(self, &row);
        assert(false);
    } catch (const std::runtime_error *error) {
        assert(error == &original_error);
    }
    assert(original_calls == 10 && getter_calls == 4 && step == 1);
}
