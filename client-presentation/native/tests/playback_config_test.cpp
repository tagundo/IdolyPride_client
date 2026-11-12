#include <cassert>
#include <cstdint>
#include "../playback_config.hpp"
using idoly::presentation::PlaybackSettings;
int main() {
    PlaybackSettings settings;
    assert(!settings.known() && settings.revision()==0);
    assert(settings.wait()); // Mac and phone defaults are both enabled.
    assert(!settings.accept(2,0,false) && !settings.accept(1,-1,false));
    assert(!settings.known());
    assert(settings.accept(1,0,false));
    assert(settings.known() && !settings.wait());
    assert(settings.accept(1,0,false) && !settings.accept(1,0,true));
    assert(settings.accept(1,4,true) && settings.wait());
    assert(!settings.accept(1,3,false) && !settings.accept(1,4,false));
    assert(settings.revision()==4 && settings.wait());
    assert(settings.accept(1,INT64_MAX,false));
    assert(settings.revision()==INT64_MAX && !settings.wait());
}
