#pragma once
#ifndef IDOLY_DARWIN_BRIDGE
#include <cstddef>
#include <cstdint>
#include <cstring>
#endif

namespace idoly::presentation::photography_ui {
using Method = const void;
using Bind = void (*)(void *, Method *);
struct Calls {
    uint32_t (*weak_new)(void *, bool) = nullptr;
    void *(*weak_get)(uint32_t) = nullptr;
    void (*weak_free)(uint32_t) = nullptr;
    bool (*matches)(void *, const char *, const char *) = nullptr;
    bool (*ui_get)(void *, Method *) = nullptr;
    void (*ui_set)(void *, bool, Method *) = nullptr;
};

// The original shared preview presenter handles activity, expression and live
// photography content. Paid-capture/selection presenters are not accepted.
class DefaultHidden {
    Calls api_{};
    uint32_t model_ = 0;
    bool done_ = false;
    template<class T> static T field(void *object, size_t offset) {
        T value{}; ::memcpy(&value,static_cast<const char *>(object)+offset,sizeof value);return value;
    }
public:
    void clear() {
        if (model_ && api_.weak_free) api_.weak_free(model_);
        model_=0;done_=false;
    }
    void configure(const Calls &api) { clear();api_=api; }
    bool ready() const {
        return api_.weak_new && api_.weak_get && api_.weak_free && api_.matches && api_.ui_get && api_.ui_set;
    }
    bool after_bind(void *self,bool enabled) {
        if (!enabled || !self || !ready()
                || !api_.matches(self,"Solis.Photography","PhotographyPreviewContentPresenter")) return false;
        void *model=field<void *>(self,0x40);
        if (!model || !api_.matches(model,"Solis.Photography","PhotographyPreviewContentModel")
                || !field<void *>(model,0x10) || field<bool>(model,0x18)) return false;
        if (!model_ || api_.weak_get(model_)!=model) {
            clear();model_=api_.weak_new(model,false);
            // Without a stable weak identity, do not risk forcing UI off again.
            if (!model_) return false;
        }
        if (done_) return true;
        api_.ui_set(model,false,nullptr);
        if (api_.ui_get(model,nullptr)) return false;
        done_=true;return true;
    }
    void bind(void *self,Method *method,Bind original,bool enabled) {
        // The original creates subscriptions first. Its exceptions propagate
        // unchanged and prevent any added visibility operation.
        if (!original) return;
        original(self,method);
        after_bind(self,enabled);
    }
};
} // namespace idoly::presentation::photography_ui
