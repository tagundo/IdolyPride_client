#pragma once
#ifndef IDOLY_DARWIN_BRIDGE
#include <cstdint>
#endif

namespace idoly::presentation {
// The embedding bridge serializes access. This class never calls Unity or
// changes ownership/acquisition data; it selects an original sorting method.
class MediaPolicySettings {
    bool known_ = false, use_master_order_ = false;
    int64_t revision_ = 0;
public:
    bool accept(int schema, int64_t revision, bool use_master_order) {
        if (schema != 1 || revision < 0 || (known_ && revision < revision_)) return false;
        if (known_ && revision == revision_) return use_master_order == use_master_order_;
        revision_ = revision; use_master_order_ = use_master_order; known_ = true;
        return true;
    }
    bool known() const { return known_; }
    int64_t revision() const { return revision_; }
    bool use_master_costume_order() const { return known_ && use_master_order_; }
};
} // namespace idoly::presentation
