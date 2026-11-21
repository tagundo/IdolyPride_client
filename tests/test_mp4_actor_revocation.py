"""A stale aggregate can revoke future entries without scene APIs or a fence."""
from pathlib import Path
import shutil
import subprocess

import pytest
import test_mp4_actor_state as physical

ROOT=Path(__file__).resolve().parents[1]
EXTRA=r'''
    if(s=="revoke_pending"||s=="revoke_committed"){
        assert(scope.quiesce()==Result::ok);assert(scope.capture()==Result::ok);assert(warm(scope)==Result::ok);
        assert(scope.prepare_grant(1)==Result::ok);
        if(s=="revoke_committed"){f->held=false;f->clock_serial=1;assert(scope.commit_grant(1)==Result::ok);}
        f->source=false;f->held=false;const auto completions=f->completions,body_calls=f->body_calls;
        forbid_source_calls=true;scope.revoke_grants();forbid_source_calls=false;
        assert(f->completions==completions);f->gate.invoke_managed(solver,f->job,nullptr,nullptr);assert(f->body_calls==body_calls);
        if(s=="revoke_pending"){f->source=true;f->clock_serial=1;assert(scope.commit_grant(1)==Result::invalid);f->source=false;}
        assert(scope.release(false)==Result::ok);return 0;
    }
'''
SOURCE=physical.SOURCE.replace('Fixture* f=nullptr;','Fixture* f=nullptr;\nbool forbid_source_calls=false;').replace('bool current(void* ctx,const Owner& o){','bool current(void* ctx,const Owner& o){\n    assert(!forbid_source_calls);').replace('assert(scope.configure(a,&f->gate,&f->owner,1,f,17));','assert(scope.configure(a,&f->gate,&f->owner,1,f,17));'+EXTRA,1)

@pytest.fixture(scope="module")
def binary(tmp_path_factory):
    compiler=shutil.which("g++") or shutil.which("clang++")
    if not compiler: pytest.skip("C++ compiler unavailable")
    directory=tmp_path_factory.mktemp("actor-revoke");source=directory/"revoke.cpp";source.write_text(SOURCE);output=directory/"revoke"
    result=subprocess.run([compiler,"-std=c++17","-Wall","-Wextra","-Werror","-O2","-I",str(ROOT/"client-presentation/native"),str(source),"-o",str(output)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    return output

@pytest.mark.parametrize("case",["revoke_pending","revoke_committed"])
def test_pure_scope_revocation(binary,case):
    result=subprocess.run([str(binary),case],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr
