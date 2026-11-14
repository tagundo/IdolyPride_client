#include "../CornerPolicy.h"
#include <assert.h>
#include <stdio.h>

int main(void) {
    // Portrait: top inset excludes the notch; all other touches pass through.
    assert(IDCornerContainsPoint(0, 59, 393, 759, 360, 80));
    assert(IDCornerContainsPoint(0, 59, 393, 759, 329, 59));
    assert(IDCornerContainsPoint(0, 59, 393, 759, 393, 123));
    assert(!IDCornerContainsPoint(0, 59, 393, 759, 328.99, 80));
    assert(!IDCornerContainsPoint(0, 59, 393, 759, 360, 58.99));
    assert(!IDCornerContainsPoint(0, 59, 393, 759, 360, 123.01));
    assert(!IDCornerContainsPoint(0, 59, 393, 759, 393.01, 80));
    // Landscape: left/right safe insets and resized Mac windows are respected.
    assert(IDCornerContainsPoint(59, 0, 734, 372, 780, 20));
    assert(!IDCornerContainsPoint(59, 0, 734, 372, 800, 20));
    assert(!IDCornerContainsPoint(0, 0, 1200, 900, 780, 20));
    assert(IDCornerContainsPoint(0, 0, 1200, 900, 1180, 20));
    // Degenerate/invalid safe areas cannot turn the entire window into a target.
    assert(IDCornerContainsPoint(10, 20, 30, 40, 10, 20));
    assert(!IDCornerContainsPoint(10, 20, 30, 40, 9, 20));
    assert(!IDCornerContainsPoint(0, 0, 0, 800, 0, 0));
    assert(!IDCornerContainsPoint(0, 0, 800, -1, 800, 0));
    assert(!IDCornerContainsPoint(0, 0, INFINITY, 800, 1, 1));
    assert(!IDCornerContainsPoint(0, 0, 800, 800, NAN, 1));
    puts("PASS: upper-right safe-area gesture geometry (17 cases)");
    return 0;
}
