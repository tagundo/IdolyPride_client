#pragma once
namespace idoly::presentation {
// The embedding bridge serializes access; no Unity API is called here.
class PlaybackSettings {
    bool known_ = false, wait_ = true;
    int64_t revision_ = 0;
public:
    bool accept(int schema,int64_t revision,bool wait) {
        if (schema!=1 || revision<0 || (known_ && revision<revision_)) return false;
        if (known_ && revision==revision_) return wait==wait_;
        revision_=revision;wait_=wait;known_=true;return true;
    }
    bool known() const { return known_; }
    int64_t revision() const { return revision_; }
    bool wait() const { return known_ ? wait_ : true; }
};
} // namespace idoly::presentation
