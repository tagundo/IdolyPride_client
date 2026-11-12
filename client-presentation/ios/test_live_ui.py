"""Pure call-order checks; no game/Unity/Mac execution."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_default_off_is_only_applied_after_session_initializer(tmp_path):
    compiler=shutil.which("c++")
    if compiler is None:pytest.skip("Host C++ compiler required")
    source=tmp_path/"live_ui.cpp"
    source.write_text(r'''
#include "live_ui.hpp"
#include <cassert>
static int initialized, hidden, shown;
static bool fail;
static int view, method;
static void init(void *self,const void *m) {
    assert(self==&view && m==&method);++initialized;
    if(fail)throw 17;
}
static void hide(void *self,bool animation,bool automatic,const void *m) {
    assert(self==&view && !animation && !automatic && !m);
    assert(initialized==hidden+1);++hidden;
}
static void show() { ++shown; }
int main() {
    using idoly_live_ui::initialize_default_off;
    initialize_default_off(&view,&method,init,hide,true);
    assert(initialized==1 && hidden==1);
    show();assert(shown==1 && hidden==1); // User toggle is not intercepted.
    initialize_default_off(&view,&method,init,hide,true);
    assert(initialized==2 && hidden==2); // Re-entry into the same view resets.
    initialize_default_off(&view,&method,init,hide,false);
    assert(initialized==3 && hidden==2);
    initialize_default_off(&view,&method,init,nullptr,true);
    assert(initialized==4 && hidden==2);
    initialize_default_off(&view,&method,nullptr,hide,true);
    assert(initialized==4 && hidden==2);
    fail=true;
    try { initialize_default_off(&view,&method,init,hide,true);assert(false); }
    catch(int e) { assert(e==17); }
    assert(initialized==5 && hidden==2); // No post-write after original failure.
}
''')
    output=tmp_path/"live-ui-test"
    subprocess.run([compiler,"-std=c++17","-O1","-Wall","-Wextra","-Werror","-I",str(Path(__file__).parent),str(source),"-o",str(output)],
                   check=True,timeout=20)
    subprocess.run([str(output)],check=True,timeout=5)
