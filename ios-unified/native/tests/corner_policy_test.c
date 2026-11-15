#include "../CornerPolicy.h"
#include <assert.h>
#include <stdio.h>

int main(void) {
    // Portrait: 128-point boundaries exclude the notch and outside safe area.
    assert(IDCornerContainsPoint(0, 59, 393, 759, 360, 80));
    assert(IDCornerContainsPoint(0, 59, 393, 759, 265, 59));
    assert(IDCornerContainsPoint(0, 59, 393, 759, 393, 187));
    assert(!IDCornerContainsPoint(0, 59, 393, 759, 264.99, 80));
    assert(!IDCornerContainsPoint(0, 59, 393, 759, 360, 58.99));
    assert(!IDCornerContainsPoint(0, 59, 393, 759, 360, 187.01));
    assert(!IDCornerContainsPoint(0, 59, 393, 759, 393.01, 80));
    // Newly included points lie outside the old 64-point width and/or height.
    assert(IDCornerContainsPoint(0, 59, 393, 759, 300, 80));
    assert(IDCornerContainsPoint(0, 59, 393, 759, 360, 150));
    assert(IDCornerContainsPoint(0, 59, 393, 759, 300, 150));
    // Landscape uses its current left/right safe insets and top boundary.
    assert(IDCornerContainsPoint(59, 0, 734, 372, 780, 20));
    assert(IDCornerContainsPoint(59, 0, 734, 372, 665, 0));
    assert(IDCornerContainsPoint(59, 0, 734, 372, 793, 128));
    assert(!IDCornerContainsPoint(59, 0, 734, 372, 664.99, 20));
    assert(!IDCornerContainsPoint(59, 0, 734, 372, 800, 20));
    assert(!IDCornerContainsPoint(59, 0, 734, 372, 780, 128.01));
    assert(IDCornerContainsPoint(59, 0, 734, 372, 700, 100));
    // Resized Mac windows derive a new target rather than reusing old geometry.
    assert(!IDCornerContainsPoint(0, 0, 1200, 900, 780, 20));
    assert(IDCornerContainsPoint(0, 0, 1200, 900, 1180, 20));
    assert(IDCornerContainsPoint(0, 0, 1200, 900, 1072, 0));
    assert(IDCornerContainsPoint(0, 0, 1200, 900, 1200, 128));
    assert(IDCornerContainsPoint(0, 0, 1200, 900, 1100, 100));
    assert(!IDCornerContainsPoint(0, 0, 1200, 900, 1071.99, 20));
    assert(!IDCornerContainsPoint(0, 0, 1200, 900, 1180, 128.01));
    // Small safe areas clip both dimensions, or each dimension independently.
    assert(IDCornerContainsPoint(10, 20, 30, 40, 10, 20));
    assert(IDCornerContainsPoint(10, 20, 30, 40, 40, 60));
    assert(!IDCornerContainsPoint(10, 20, 30, 40, 9.99, 20));
    assert(!IDCornerContainsPoint(10, 20, 30, 40, 40.01, 20));
    assert(!IDCornerContainsPoint(10, 20, 30, 40, 10, 19.99));
    assert(!IDCornerContainsPoint(10, 20, 30, 40, 10, 60.01));
    assert(IDCornerContainsPoint(10, 20, 30, 200, 10, 148));
    assert(!IDCornerContainsPoint(10, 20, 30, 200, 10, 148.01));
    assert(IDCornerContainsPoint(10, 20, 200, 40, 82, 60));
    assert(!IDCornerContainsPoint(10, 20, 200, 40, 81.99, 60));
    assert(!IDCornerContainsPoint(10, 20, 200, 40, 82, 60.01));
    // Degenerate/invalid safe areas and non-finite touches never match.
    assert(!IDCornerContainsPoint(0, 0, 0, 800, 0, 0));
    assert(!IDCornerContainsPoint(0, 0, 800, 0, 800, 0));
    assert(!IDCornerContainsPoint(0, 0, -1, 800, 0, 0));
    assert(!IDCornerContainsPoint(0, 0, 800, -1, 800, 0));
    assert(!IDCornerContainsPoint(0, 0, INFINITY, 800, 1, 1));
    assert(!IDCornerContainsPoint(0, 0, 800, INFINITY, 800, 1));
    assert(!IDCornerContainsPoint(0, 0, 800, 800, NAN, 1));
    assert(!IDCornerContainsPoint(NAN, 0, 800, 800, 800, 1));
    puts("PASS: upper-right safe-area gesture geometry (43 cases)");
    return 0;
}
