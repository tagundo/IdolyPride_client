#ifndef IDOLY_CORNER_POLICY_H
#define IDOLY_CORNER_POLICY_H

#include <math.h>

// Inputs are the current safe-area rectangle and touch in window points.
// Derive the target at touch-down, so rotation/resizing needs no polling.
static inline int IDCornerContainsPoint(double safeX, double safeY,
                                       double safeWidth, double safeHeight,
                                       double touchX, double touchY) {
    if (!isfinite(safeX) || !isfinite(safeY) || !isfinite(safeWidth)
        || !isfinite(safeHeight) || !isfinite(touchX) || !isfinite(touchY)
        || safeWidth <= 0 || safeHeight <= 0) return 0;
    double width = safeWidth < 128 ? safeWidth : 128;
    double height = safeHeight < 128 ? safeHeight : 128;
    double right = safeX + safeWidth;
    return touchX >= right - width && touchX <= right
        && touchY >= safeY && touchY <= safeY + height;
}

#endif
