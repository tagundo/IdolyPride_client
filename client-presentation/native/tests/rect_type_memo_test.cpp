#include <cassert>
#include <cstring>
#include <stdexcept>

using Method = const void;
struct Type { const char *name; const char *space; Type *parent; };
struct Object { bool alive; Type *type; };
int alive_calls=0, class_calls=0, name_calls=0, namespace_calls=0, parent_calls=0;
bool throw_on_name=false;
bool alive(void *object,Method *) { ++alive_calls;return static_cast<Object *>(object)->alive; }
void *klass(void *object) { ++class_calls;return static_cast<Object *>(object)->type; }
const char *name(void *type) {
    ++name_calls;
    if(throw_on_name)throw std::runtime_error("original metadata callback unwound");
    return static_cast<Type *>(type)->name;
}
const char *space(void *type) { ++namespace_calls;return static_cast<Type *>(type)->space; }
void *parent(void *type) { ++parent_calls;return static_cast<Type *>(type)->parent; }
bool (*object_alive)(void *,Method *)=alive;
void *(*object_class)(void *)=klass;
const char *(*class_name)(void *)=name;
const char *(*class_namespace)(void *)=space;
void *(*class_parent)(void *)=parent;

// This file is generated directly from the production bridge's delimited
// helper, rather than a second implementation of its cache or traversal.
#include "rect_type_memo_fragment.hpp"

void reset_counts() { alive_calls=class_calls=name_calls=namespace_calls=parent_calls=0; }
int main() {
    static_assert(sizeof(RectTypeMemo)==4*sizeof(void *),"bounded stack-only entries");
    Type rect{"RectTransform","UnityEngine",nullptr};
    Type other{"Transform","UnityEngine",nullptr};
    Object first{true,&rect},second{true,&rect};
    reset_counts();
    assert(rect_transform(&first) && rect_transform(&second));
    assert(alive_calls==2 && class_calls==2 && name_calls==2 && namespace_calls==2);
    reset_counts();
    {
        RectTypeMemoScope memo;
        assert(rect_transform(&first) && rect_transform(&second));
        assert(rect_transform(&first) && rect_transform(&second));
        // Four validations still check four live objects and four current
        // classes, but the immutable ancestry is walked only once.
        assert(alive_calls==4 && class_calls==4 && name_calls==1 && namespace_calls==1);
        second.alive=false;
        assert(!rect_transform(&second));
        assert(alive_calls==5 && class_calls==4 && name_calls==1);
        second.alive=true;second.type=&other; // Same object address, new class.
        assert(!rect_transform(&second));
        assert(alive_calls==6 && class_calls==5 && name_calls==2);
        assert(!rect_transform(nullptr));
    }
    assert(rect_type_memo==nullptr);
    second.type=&rect;
    {
        RectTypeMemoScope next_callback;
        assert(rect_transform(&first));
        assert(name_calls==3); // No cache survives the previous callback.
    }
    Type incomplete{"RectTransform",nullptr,nullptr};Object unknown{true,&incomplete};
    {
        RectTypeMemoScope memo;
        assert(!rect_transform(&unknown));
        incomplete.space="UnityEngine";
        assert(rect_transform(&unknown)); // Failed walks are never memoized.
    }
    Type derived[5];Object objects[5];
    for(int i=0;i<5;++i){derived[i]={"Derived","Test",&rect};objects[i]={true,&derived[i]};}
    reset_counts();
    {
        RectTypeMemoScope memo;
        for(auto &object:objects)assert(rect_transform(&object));
        assert(name_calls==10 && parent_calls==5);
        assert(rect_transform(&objects[0]) && name_calls==10);
        assert(rect_transform(&objects[4]) && name_calls==12 && parent_calls==6);
        // The fifth positive class remains correct through an uncached walk.
    }
    reset_counts();
    {
        RectTypeMemoScope outer;
        assert(rect_transform(&first));
        RectTypeMemo *enclosing=rect_type_memo;
        {
            RectTypeMemoScope inner;
            assert(rect_type_memo!=enclosing && rect_transform(&first));
        }
        assert(rect_type_memo==enclosing && rect_transform(&first));
        assert(name_calls==2);
        try {
            RectTypeMemoScope inner;
            throw_on_name=true;
            rect_transform(&objects[0]);
            assert(false);
        } catch(const std::runtime_error &) { throw_on_name=false; }
        assert(rect_type_memo==enclosing && rect_transform(&first));
        assert(name_calls==3);
    }
    assert(rect_type_memo==nullptr);
    Type chain[13];
    for(int i=0;i<12;++i)chain[i]={"Other","Test",&chain[i+1]};
    chain[12]=rect;Object deep{true,&chain[0]};
    {
        RectTypeMemoScope memo;
        assert(!rect_transform(&deep)); // Original twelve-level bound retained.
        deep.type=&chain[1];assert(rect_transform(&deep));
        deep.type=&chain[0];assert(!rect_transform(&deep));
    }
    assert(rect_type_memo==nullptr);
}
