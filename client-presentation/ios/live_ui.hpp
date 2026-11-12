#pragma once

// Original 6.1.1 OutGame MV-only view. Do not bind this adapter to the shared
// Solis.Live.LiveRotationUIPresenter* gameplay HUD. The checked initializer is
// called once by LivePlayerScreenPresenter.InitializeAsync for each entry.
namespace idoly_live_ui {
using Initialize = void (*)(void *self, const void *method);
using Hide = void (*)(void *self, bool animation, bool automatic, const void *method);

inline void initialize_default_off(void *self, const void *method,
                                   Initialize original, Hide hide, bool enabled) {
    if (!original) return;
    original(self, method);
    // Preserve original initialization/exception order and the entire input
    // handler. This is the same Hide(false,false) used by the original Clear;
    // OnPointerClick remains free to call the original Show(true) afterwards.
    if (enabled && self && hide) hide(self, false, false, nullptr);
}
} // namespace idoly_live_ui
