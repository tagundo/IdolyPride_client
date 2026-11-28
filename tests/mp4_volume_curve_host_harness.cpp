#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdlib>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
struct Method{};
struct Class{const char* name;const char* space;};
Class curve_class{"TextureCurve","UnityEngine.Rendering"},param_class{"TextureCurveParameter","UnityEngine.Rendering"},
 anim_class{"AnimationCurve","UnityEngine"},array_class{"Keyframe[]","UnityEngine"},key_class{"Keyframe","UnityEngine"};
struct Object {alignas(16) uint8_t bytes[128]{};Class* klass;explicit Object(Class* k):klass(k){}};
struct Key {float time,value,in,out;int32_t mode;float in_weight,out_weight;};static_assert(sizeof(Key)==28);
struct NativeCurve{std::vector<Key> keys;};
std::vector<std::unique_ptr<Object>> objects;std::vector<std::unique_ptr<NativeCurve>> curves;
std::vector<std::unique_ptr<uint8_t[]>> arrays;
std::map<void*,Class*> classes;std::map<void*,size_t> ranges;std::map<uint32_t,void*> roots;
uint32_t next_root=0,retain_fail=0;bool source_current=true,ctor_throw=false,set_keys_throw=false,change_owner_in_ctor=false;
int ctor_calls=0,set_calls=0,releases=0,dirty_calls=0,source_texture_destroyed=0;void* source_texture=reinterpret_cast<void*>(0x9911);
template<typename T>void put(void* p,size_t offset,const T& value){std::memcpy(static_cast<uint8_t*>(p)+offset,&value,sizeof value);}
template<typename T>T get(void* p,size_t offset){T value;std::memcpy(&value,static_cast<uint8_t*>(p)+offset,sizeof value);return value;}
Object* make_object(Class* klass){objects.emplace_back(new Object(klass));auto* o=objects.back().get();classes[o->bytes]=klass;ranges[o->bytes]=128;return o;}
void* make_array(const std::vector<Key>& keys){const auto size=32+keys.size()*sizeof(Key);arrays.emplace_back(new uint8_t[size]{});auto* p=arrays.back().get();
 uintptr_t n=keys.size();put(p,24,n);
 if(n){std::memcpy(p+32,keys.data(),n*sizeof(Key));}classes[p]=&array_class;ranges[p]=size;return p;}
void* make_native_curve(const std::vector<Key>& keys){auto* o=make_object(&anim_class);curves.emplace_back(new NativeCurve{keys});put(o->bytes,16,curves.back().get());return o->bytes;}
void* make_curve(const std::vector<Key>& keys,float zero=0,bool loop=false,float range=1){auto* o=make_object(&curve_class);
 put(o->bytes,16,int32_t(keys.size()));put(o->bytes,20,uint8_t(loop));put(o->bytes,24,zero);put(o->bytes,28,range);
 put(o->bytes,32,make_native_curve(keys));put(o->bytes,56,uint8_t(1));put(o->bytes,57,uint8_t(1));return o->bytes;}
bool mp4_actor_mapped(const void* pointer,size_t n,bool){const auto p=reinterpret_cast<uintptr_t>(pointer);for(auto [base,size]:ranges){const auto b=reinterpret_cast<uintptr_t>(base);
 if(p>=b&&p-b<=size&&n<=size-(p-b))return true;}return false;}
template<typename T>bool mp4_actor_field(void* p,size_t offset,T& value){if(!p||!mp4_actor_mapped(static_cast<uint8_t*>(p)+offset,sizeof value,false))return false;value=get<T>(p,offset);return true;}
void* object_class(void* p){auto i=classes.find(p);return i==classes.end()?nullptr:i->second;}
const char* class_name(void* p){return p?static_cast<Class*>(p)->name:nullptr;}
const char* class_namespace(void* p){return p?static_cast<Class*>(p)->space:nullptr;}
bool mp4_exact_type(void* p,const char* name){auto* k=static_cast<Class*>(object_class(p));return k&&std::string(k->space)+"."+k->name==name;}
uint32_t mp4_retain(void* p){const uint32_t key=++next_root;
 if(key==retain_fail){return 0;}roots[key]=p;return key;}
void* weak_get(uint32_t key){auto i=roots.find(key);return i==roots.end()?nullptr:i->second;}
void weak_free(uint32_t key){assert(roots.erase(key)==1);}
bool mp4_actor_refresh_maps(){return true;}
bool mp4_scene_source_current(){return source_current;}
void* font_new(void* klass){return make_object(static_cast<Class*>(klass))->bytes;}
void mp4_camera_barrier(void* object,void** slot,void* value){assert(mp4_actor_mapped(object,16,false));std::memcpy(slot,&value,sizeof value);}
struct Binding{uintptr_t pointer=0;};
struct Profile{Binding class_rank,class_element,class_value_size,animation_curve_keys,texture_curve_ctor,
 animation_curve_set_keys,texture_curve_set_dirty,texture_curve_release;}mp4_cam_profile;
template<typename F>F mp4_cam_call(Binding b){return reinterpret_cast<F>(b.pointer);}
int32_t rank(void* k){return k==&array_class?1:0;}
void* element(void* k){return k==&array_class?&key_class:nullptr;}
int32_t value_size(void* k,uint32_t* alignment){*alignment=4;return k==&key_class?28:0;}
void* get_keys(void* receiver,Method*){auto* native=get<NativeCurve*>(receiver,16);return make_array(native->keys);}
void construct(void* receiver,void* keys,float zero,bool loop,const void* bounds,Method*){++ctor_calls;
 const auto length=get<uintptr_t>(keys,24);std::vector<Key> values(length);
 if(length)std::memcpy(values.data(),static_cast<uint8_t*>(keys)+32,length*28);
 put(receiver,32,make_native_curve(values));put(receiver,16,int32_t(length));put(receiver,24,zero);put(receiver,20,uint8_t(loop));
 auto* xy=static_cast<const float*>(bounds);put(receiver,28,std::sqrt(xy[0]*xy[0]+xy[1]*xy[1]));put(receiver,56,uint8_t(1));put(receiver,57,uint8_t(1));
 if(change_owner_in_ctor)source_current=false;
 if(ctor_throw)throw std::runtime_error("ctor");}
void set_keys(void* receiver,void* keys,Method*){++set_calls;auto* native=get<NativeCurve*>(receiver,16);const auto length=get<uintptr_t>(keys,24);
 native->keys.resize(length);
 if(length)std::memcpy(native->keys.data(),static_cast<uint8_t*>(keys)+32,length*28);
 if(set_keys_throw)throw std::runtime_error("set_keys");}
void set_dirty(void* receiver,Method*){++dirty_calls;put(receiver,56,uint8_t(1));put(receiver,57,uint8_t(1));}
void release(void* receiver,Method*){++releases;auto* tex=get<void*>(receiver,48);
 if(tex==source_texture){++source_texture_destroyed;}put(receiver,48,static_cast<void*>(nullptr));}
#include "volume_curve_host.inc"
int main(int argc,char** argv){assert(argc==2);std::string scenario=argv[1];
#define BIND(name,fn) mp4_cam_profile.name.pointer=reinterpret_cast<uintptr_t>(&fn)
 BIND(class_rank,rank);BIND(class_element,element);BIND(class_value_size,value_size);BIND(animation_curve_keys,get_keys);
 BIND(texture_curve_ctor,construct);BIND(animation_curve_set_keys,set_keys);BIND(texture_curve_set_dirty,set_dirty);BIND(texture_curve_release,release);
#undef BIND
 std::vector<Key> values{{0,0,0,0,0,.3f,.3f},{1,1,0,0,0,.3f,.3f}};
 if(scenario=="empty")values.clear();
 if(scenario=="single")values={{4,9,0,0,0,.3f,.3f}};
 if(scenario=="domain_start")values[0].time=.1f;
 if(scenario=="domain_end")values[1].time=.9f;
 if(scenario=="nan_value")values[0].value=NAN;
 if(scenario=="nan_tangent")values[0].in=NAN;
 if(scenario=="step_tangent")values[0].out=INFINITY;
 void* source=make_curve(values,2,scenario=="loop",1);put(source,48,source_texture);
 uint8_t source_fields[42]{};std::memcpy(source_fields,static_cast<uint8_t*>(source)+16,42);
 void* initial=make_curve({});void* parameter=make_object(&param_class)->bytes;put(parameter,24,initial);
 if(scenario=="initial_root_failure"){
   retain_fail=next_root+2;assert(!mp4_volume_curve_pin_initial(parameter));
   assert(roots.empty()&&mp4_volume_curve_count==0&&get<void*>(parameter,24)==initial);return 0;
 }
 assert(mp4_volume_curve_pin_initial(parameter));auto& pool=mp4_volume_curves[0];put(parameter,24,source);
 if(scenario=="fresh_root_failure")retain_fail=next_root+4;
 if(scenario=="native_root_failure")retain_fail=next_root+5;
 if(scenario=="ctor_throw")ctor_throw=true;
 if(scenario=="set_throw")set_keys_throw=true;
 if(scenario=="source_change")change_owner_in_ctor=true;
 bool result=false;try{result=mp4_volume_curve_refresh(pool);}catch(const std::exception&){}
 const bool failure=scenario=="domain_start"||scenario=="domain_end"||scenario=="nan_value"||scenario=="nan_tangent"
  ||scenario=="ctor_throw"||scenario=="set_throw"||scenario=="source_change"||scenario=="fresh_root_failure"||scenario=="native_root_failure";
 assert(result==!failure);assert(!std::memcmp(source_fields,static_cast<uint8_t*>(source)+16,42));
 assert(source_texture_destroyed==0);
 if(!failure){assert(get<void*>(parameter,24)==pool.fresh&&pool.fresh!=source&&pool.fresh!=initial);
  assert(pool.native_curve!=get<void*>(source,32)&&get<void*>(pool.native_curve,16)!=get<void*>(get<void*>(source,32),16));
  const int old_sets=set_calls;const int old_dirty=dirty_calls;void* fresh=pool.fresh;
  put(pool.fresh,48,reinterpret_cast<void*>(0x8877));put(pool.fresh,57,uint8_t(0));
  put(parameter,24,source);assert(mp4_volume_curve_refresh(pool));
  assert(pool.fresh==fresh&&set_calls==old_sets&&dirty_calls==old_dirty&&get<uint8_t>(fresh,57)==0);
  if(scenario=="refresh"){
    auto* native=get<NativeCurve*>(get<void*>(source,32),16);native->keys[1].value=.5f;
    put(parameter,24,source);assert(mp4_volume_curve_refresh(pool));assert(set_calls==old_sets+1&&dirty_calls==old_dirty+1&&pool.fresh==fresh);
    assert(get<NativeCurve*>(pool.native_curve,16)->keys[1].value==.5f);
  }
 }
 assert(mp4_volume_curves_prepare_disposal()&&get<void*>(parameter,24)==initial);
 // Real DestroyStack releases the now-rebound owned default receiver.
 release(initial,nullptr);assert(mp4_volume_curves_release());
 assert(source_texture_destroyed==0&&roots.empty()&&mp4_volume_curve_count==0);
 assert(!std::memcmp(source_fields,static_cast<uint8_t*>(source)+16,42));return 0;
}
