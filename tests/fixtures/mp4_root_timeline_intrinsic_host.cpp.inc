#include <cassert>
#include <cstdint>
#include <cstring>
#include <cmath>
#include <string>
#include <vector>
#include <array>
#include <map>
#include <memory>
#include <new>
#include <cstdio>
using Method=void;
namespace mp4game {struct Binding{uintptr_t rva;uint8_t prefix[16];};struct PlayableGraph{void*handle=nullptr;int32_t version=0,padding=0;};struct Layout{size_t player_director_controller=56,controller_directors=40;};template<class T>bool type_descriptor_shape(const T&,void*){return true;}}
namespace mp4actor {struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};}
namespace mp4world {struct DirectorGraphIdentity{uintptr_t native=0,slot=0;uint32_t version=0,mode=0,category=0;uint16_t status=0;};struct AnimationOutput{uintptr_t handle=0;uint32_t version=0,padding=0;};}
namespace mp4stage {struct Layout{static constexpr size_t timeline_tracks=32,track_clips=80,track_children=88,clip_asset=40;};}
struct Mp4SceneWitness{void*player=nullptr,*environment=nullptr,*director=nullptr,*camera_director=nullptr;uint64_t generation=0;};
struct Class;struct Field{size_t offset=0;Class*type=nullptr;};
struct Class{std::string name;bool value=false;int bytes=8;Class*element=nullptr;std::map<std::string,Field>fields;};
struct Obj{Class*klass=nullptr;std::string tag;std::array<uint8_t,256>fields{};std::vector<uint8_t>data;size_t length=0;};
std::map<uintptr_t,Class*>classes;std::vector<std::unique_ptr<Class>>class_storage;std::vector<std::unique_ptr<Obj>>objects;
Class*klass(std::string name,bool value=false,int bytes=8,Class*element=nullptr){class_storage.emplace_back(new Class{name,value,bytes,element,{}});return class_storage.back().get();}
Obj*object(Class*c,const char*tag=""){objects.emplace_back(new Obj);auto*p=objects.back().get();p->klass=c;p->tag=tag;return p;}
template<class T>void set(void*p,size_t offset,const T&v){assert(p&&offset+sizeof v<=256);std::memcpy(static_cast<Obj*>(p)->fields.data()+offset,&v,sizeof v);}
template<class T>bool mp4_actor_field(void*p,size_t offset,T&v){if(!p||offset+sizeof v>256)return false;std::memcpy(&v,static_cast<Obj*>(p)->fields.data()+offset,sizeof v);return true;}
std::map<uint32_t,void*>roots;uint32_t next_root=1;
uint32_t mp4_retain(void*p){if(!p)return 0;roots[next_root]=p;return next_root++;}void*weak_get(uint32_t h){auto i=roots.find(h);return i==roots.end()?nullptr:i->second;}void weak_free(uint32_t h){roots.erase(h);}
struct Mp4ActorTempRoot{void*p;uint32_t root;explicit Mp4ActorTempRoot(void*v):p(v),root(mp4_retain(v)){}~Mp4ActorTempRoot(){weak_free(root);}void*get()const{return weak_get(root);}};
uintptr_t image_base=0;bool mp4_source_verified=true,mp4_actor_source_verified=true,mp4_output_calls_verified=true,on_thread=true;
bool game_call(){return on_thread;}bool mp4_mapped(uintptr_t,size_t,bool){return true;}bool mp4_actor_mapped(void*,size_t,bool){return true;}bool mp4_prefix(const mp4game::Binding&){return true;}bool mp4_hook_was_statically_verified(const mp4game::Binding&){return false;}
void*object_class(void*p){return p?static_cast<Obj*>(p)->klass:nullptr;}
void*mp4_resolved_type_class(const mp4game::Binding&b,const char*,const char*){auto i=classes.find(b.rva);return i==classes.end()?nullptr:i->second;}
bool mp4_type_is(void*p,const char*type){return p&&static_cast<Obj*>(p)->tag==type;}bool mp4_alive(void*p){return p!=nullptr;}
void*get_field(void*c,const char*name){if(!c)return nullptr;auto&f=static_cast<Class*>(c)->fields;auto i=f.find(name);return i==f.end()?nullptr:&i->second;}
const void*get_field_type(void*f){return f?static_cast<Field*>(f)->type:nullptr;}void*get_class_type(const void*t){return const_cast<void*>(t);}
void*(*font_field)(void*,const char*)=get_field;const void*(*font_field_type)(void*)=get_field_type;void*(*font_class_type)(const void*)=get_class_type;
size_t field_offset(const void*f){return static_cast<const Field*>(f)->offset;}
bool mp4_root_track_field(void*o,const char*n,size_t at,void**out=nullptr){void*f=get_field(object_class(o),n);if(!f||field_offset(f)!=at)return false;if(out)*out=f;return true;}
size_t mp4_array_length(void*p){return static_cast<Obj*>(p)->length;}void*mp4_array_data(void*p){return static_cast<Obj*>(p)->data.data();}
bool mp4_actor_list(void*p,void***data,size_t*count,size_t limit){void*a=nullptr;int32_t n=0;if(!mp4_actor_field(p,16,a)||!mp4_actor_field(p,24,n)||n<0||static_cast<size_t>(n)>limit)return false;*data=static_cast<void**>(mp4_array_data(a));*count=static_cast<size_t>(n);return true;}
void*class_element(void*c){return static_cast<Class*>(c)->element;}bool class_value(void*c){return static_cast<Class*>(c)->value;}int32_t class_size(void*c,uint32_t*a){*a=8;return static_cast<Class*>(c)->bytes;}
struct CamProfile{mp4game::Binding class_element{reinterpret_cast<uintptr_t>(::class_element),{}},class_value_type{reinterpret_cast<uintptr_t>(class_value),{}},class_value_size{reinterpret_cast<uintptr_t>(class_size),{}};}mp4_cam_profile;
template<class F>F mp4_cam_call(const mp4game::Binding&b){return reinterpret_cast<F>(b.rva);}
Mp4SceneWitness selected_witness{};namespace idoly_mp4_runtime{struct Game{bool selected_scene_witness(Mp4SceneWitness&o){o=::selected_witness;return true;}}game;}
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.player==b.player&&a.environment==b.environment&&a.director==b.director&&a.camera_director==b.camera_director&&a.generation==b.generation;}
mp4actor::Handle graph_handle{11,2,0},root_handle{21,1,0},mixer_handle{22,1,0},leaf_handle{23,1,0};
struct Node{mp4actor::Handle h;void*script=nullptr;std::vector<mp4actor::Handle>inputs;};std::vector<Node>nodes;
Node*node_for(mp4actor::Handle h){for(auto&n:nodes)if(n.h.handle==h.handle&&n.h.version==h.version)return &n;return nullptr;}
bool mp4_actor_same_handle(mp4actor::Handle a,mp4actor::Handle b){return a.handle==b.handle&&a.version==b.version;}
void*node_script(mp4actor::Handle*h,Method*){auto*n=node_for(*h);return n?n->script:nullptr;}
Obj*plain_reflection=nullptr;void*node_type(mp4actor::Handle*,Method*){return plain_reflection;}
void*mp4_type_get_object(void*){return plain_reflection;}
struct ActorProfile{mp4game::Binding field_offset{reinterpret_cast<uintptr_t>(::field_offset),{}},script_instance{reinterpret_cast<uintptr_t>(node_script),{}},playable_type{reinterpret_cast<uintptr_t>(node_type),{}};struct{size_t slot_output=40;}native_output;}mp4_actor_profile;
struct StateApi{bool(*graph_valid)(mp4actor::Handle*,Method*);bool(*playable_valid)(mp4actor::Handle*,Method*);int32_t(*graph_root_count)(mp4actor::Handle*,Method*);void(*graph_root)(mp4actor::Handle*,int32_t,mp4actor::Handle*,Method*);int32_t(*playable_input_count)(mp4actor::Handle*,Method*);void(*playable_input)(mp4actor::Handle*,int32_t,mp4actor::Handle*,Method*);};
StateApi mp4_actor_state_api(){return {[](mp4actor::Handle*,Method*){return true;},[](mp4actor::Handle*h,Method*){return node_for(*h)!=nullptr;},[](mp4actor::Handle*,Method*){return 1;},[](mp4actor::Handle*,int32_t,mp4actor::Handle*out,Method*){*out=root_handle;},[](mp4actor::Handle*h,Method*){auto*n=node_for(*h);return n?static_cast<int32_t>(n->inputs.size()):-1;},[](mp4actor::Handle*h,int32_t i,mp4actor::Handle*out,Method*){*out=node_for(*h)->inputs.at(static_cast<size_t>(i));}};}
Obj*director_obj=nullptr,*asset_obj=nullptr,*track_obj=nullptr;bool registry_current=true,cache_current=true;
bool mp4_scene_registry_current_graph(uintptr_t,uintptr_t,uint32_t){return registry_current;}
bool mp4_director_graph_handle(const mp4world::DirectorGraphIdentity&,mp4actor::Handle*out){*out=graph_handle;return registry_current;}
bool mp4_director_graph_nodes(const mp4world::DirectorGraphIdentity&,mp4actor::Handle*out,size_t cap,size_t*used){if(nodes.size()>cap)return false;*used=nodes.size();for(size_t i=0;i<nodes.size();++i)out[i]=nodes[i].h;return true;}
bool mp4_root_track_cache_lookup(const mp4world::DirectorGraphIdentity&,mp4actor::Handle,void*track,mp4actor::Handle*out){*out={};if(track!=track_obj||!cache_current)return false;*out=mixer_handle;return true;}
bool mp4_root_track_port_closed(const mp4world::DirectorGraphIdentity&,mp4actor::Handle,void*track,int32_t port,mp4actor::Handle h){return cache_current&&track==track_obj&&port==0&&mp4_actor_same_handle(h,mixer_handle);}
struct GameApi{void*(*director_get_asset)(void*,Method*)=nullptr;void(*director_graph_injected)(void*,mp4game::PlayableGraph*,Method*)=nullptr;}mp4_api;
Obj*script_slot=nullptr,*anim_slot=nullptr;uint32_t mp4_output_types[3]{};void*userdata_value=nullptr;bool userdata_changed=false;int userdata_calls=0;int source_port=0;
int32_t get_port(mp4world::AnimationOutput*,Method*){return source_port;}
void*output_type(mp4world::AnimationOutput*h,Method*){return weak_get(mp4_output_types[h->handle==reinterpret_cast<uintptr_t>(script_slot)?2:0]);}
struct WorldProfile{mp4game::Binding output_type{reinterpret_cast<uintptr_t>(::output_type),{}};}mp4_world_profile;
bool mp4_director_output_handle(const mp4world::DirectorGraphIdentity&,uintptr_t native,mp4world::AnimationOutput*out){if(native!=101&&native!=102)return false;*out={reinterpret_cast<uintptr_t>(native==101?script_slot:anim_slot),1,0};return true;}
bool mp4_director_output_source(mp4world::AnimationOutput,mp4actor::Handle*out){*out=root_handle;return true;}
bool mp4_director_output_userdata(const mp4world::DirectorGraphIdentity&,uintptr_t,void**out){*out=userdata_value;if(userdata_changed&&++userdata_calls>1)*out=nullptr;return true;}
struct Mp4EquipmentGraphClass{const char*name;mp4game::Binding type;};struct Mp4EquipmentGraphFamily{Mp4EquipmentGraphClass track,clip,behaviour;int32_t job;};
Mp4EquipmentGraphClass mp4_equipment_graph_track{"EquipmentTrack",{900,{}}};Mp4EquipmentGraphFamily mp4_equipment_graph_families[]={{{"Track",{901,{}}},{"Clip",{902,{}}},{"Behaviour",{903,{}}},1}};
bool mp4_equipment_graph_exact(void*p,const Mp4EquipmentGraphClass&schema){return p&&object_class(p)==classes[schema.type.rva];}
bool mp4_stage_equipment_node_closed(const Mp4SceneWitness&,void*,void*,mp4actor::Handle,void*){return false;}

// SHIPPING_TIMELINE_INTRINSIC_PINS
// SHIPPING_TIMELINE_INTRINSIC_HOST
Obj *root_obj = nullptr, *tree_obj = nullptr, *entries_obj = nullptr, *active_obj = nullptr,
    *runtime_obj = nullptr, *clip_obj = nullptr, *actor_script = nullptr, *actor_userdata = nullptr,
    *callback_obj = nullptr;
bool owner_current = true, restore_closed = true, animation_closed = true, actor_node_closed = true,
     actor_runtime_closed = true, userdata_closed = true, mutate_generation = false, mutate_list = false,
     world_claim = false;
int world_node_calls = 0;
Mp4TimelineProofPhase expected_phase = Mp4TimelineProofPhase::admission;
Obj *list_object(Class *element, bool value, size_t stride, const void *data, size_t count) {
    auto *ac = klass("array", false, 8, element);
    auto *lc = klass("List`1");
    lc->fields["_items"] = {16, ac};
    lc->fields["_size"] = {24, nullptr};
    lc->fields["_version"] = {28, nullptr};
    auto *a = object(ac);
    a->length = count;
    a->data.resize(count * stride);
    if (count)
        std::memcpy(a->data.data(), data, count * stride);
    auto *l = object(lc);
    set(l, 16, static_cast<void *>(a));
    set(l, 24, static_cast<int32_t>(count));
    set(l, 28, int32_t(1));
    assert(element->value == value);
    return l;
}
void ref(Obj *o, const char *n, size_t offset, Obj *target) {
    o->klass->fields[n] = {offset, target->klass};
    set(o, offset, static_cast<void *>(target));
}
void bind_types() {
    const Mp4TimelineTypePin *pins[] = {
        &mp4_timeline_pins.root,        &mp4_timeline_pins.notification, &mp4_timeline_pins.weight,
        &mp4_timeline_pins.runtime,     &mp4_timeline_pins.clip,         &mp4_timeline_pins.scheduled,
        &mp4_timeline_pins.infinite,    &mp4_timeline_pins.callback,     &mp4_timeline_pins.plain,
        &mp4_timeline_pins.weight_info, &mp4_timeline_pins.tree_node};
    for (auto *p : pins)
        classes[p->binding.rva] =
            klass(p->name,
                  p == &mp4_timeline_pins.plain || p == &mp4_timeline_pins.weight_info ||
                      p == &mp4_timeline_pins.tree_node,
                  p == &mp4_timeline_pins.weight_info ? 40
                  : p == &mp4_timeline_pins.tree_node ? 24
                                                      : 16);
    for (uintptr_t i = 900; i <= 903; ++i)
        classes[i] = klass("Equipment");
}
Class *type(const Mp4TimelineTypePin &p) { return classes[p.binding.rva]; }
void setup(bool with_actor, bool with_runtime, bool with_notification, bool with_weight) {
    bind_types();
    auto *common = klass("Object");
    plain_reflection = object(common);
    auto *player = object(common);
    auto *env = object(common);
    director_obj = object(common, "UnityEngine.Playables.PlayableDirector");
    asset_obj = object(common, "UnityEngine.Timeline.TimelineAsset");
    track_obj = object(common, "UnityEngine.Timeline.TrackAsset");
    selected_witness = {player, env, director_obj, nullptr, 1};
    Obj *controller = object(common);
    void *d = director_obj;
    auto *directors = list_object(common, false, 8, &d, 1);
    set(player, 56, static_cast<void *>(controller));
    set(controller, 40, static_cast<void *>(directors));
    void *t = track_obj;
    auto *tracks = list_object(common, false, 8, &t, 1);
    set(asset_obj, 32, static_cast<void *>(tracks));
    root_obj = object(type(mp4_timeline_pins.root));
    tree_obj = object(klass("IntervalTree<RuntimeElement>"));
    ref(root_obj, "m_IntervalTree", 16, tree_obj);
    auto *entry_class = klass("Entry<RuntimeElement>", true, 24);
    entry_class->fields["intervalStart"] = {16, nullptr};
    entry_class->fields["intervalEnd"] = {24, nullptr};
    entry_class->fields["item"] = {32, type(mp4_timeline_pins.runtime)};
    clip_obj = object(common, "UnityEngine.Timeline.TimelineClip");
    actor_script = object(klass("ActorScript"));
    actor_userdata = object(klass("ActorUserData"));
    if (with_runtime) {
        runtime_obj = object(type(mp4_timeline_pins.clip));
        set(runtime_obj, 24, static_cast<void *>(clip_obj));
        set(runtime_obj, 32, leaf_handle);
        set(runtime_obj, 48, mixer_handle);
    }
    uint8_t entry[24]{};
    int64_t end = 100;
    std::memcpy(entry + 8, &end, 8);
    void *r = runtime_obj;
    std::memcpy(entry + 16, &r, 8);
    entries_obj = list_object(entry_class, true, 24, entry, with_runtime ? 1 : 0);
    auto *tree_nodes = list_object(type(mp4_timeline_pins.tree_node), true, 24, nullptr, 0);
    ref(tree_obj, "m_Entries", 16, entries_obj);
    ref(tree_obj, "m_Nodes", 24, tree_nodes);
    active_obj = list_object(type(mp4_timeline_pins.runtime), false, 8, &r, with_runtime ? 1 : 0);
    ref(root_obj, "m_ActiveClips", 24, active_obj);
    ref(root_obj, "m_CurrentListOfActiveClips", 32,
        list_object(type(mp4_timeline_pins.runtime), false, 8, nullptr, 0));
    void *clip = clip_obj;
    set(track_obj, 80, static_cast<void *>(list_object(common, false, 8, &clip, with_runtime ? 1 : 0)));
    set(track_obj, 88, static_cast<void *>(nullptr));
    set(clip_obj, 40, static_cast<void *>(object(common)));
    nodes = {Node{root_handle, root_obj, {mixer_handle}}, Node{mixer_handle, nullptr, {}}};
    if (with_actor) {
        nodes[1].inputs.push_back(leaf_handle);
        nodes.push_back(Node{leaf_handle, actor_script, {}});
    }
    if (with_notification) {
        auto *n = object(type(mp4_timeline_pins.notification));
        auto *nc = klass("NotificationEntry", true, 24);
        ref(n, "m_Notifications", 16, list_object(nc, true, 24, nullptr, 0));
        set(n, 24, double(2));
        set(n, 40, root_handle);
        nodes[1].inputs.push_back(leaf_handle);
        nodes.push_back(Node{leaf_handle, n, {}});
    }
    script_slot = object(common);
    anim_slot = object(common);
    set(script_slot, 40, uintptr_t(101));
    set(anim_slot, 40, uintptr_t(102));
    mp4_output_types[0] = mp4_retain(object(common));
    mp4_output_types[2] = mp4_retain(object(common));
    void *callback = nullptr;
    if (with_weight) {
        callback_obj = object(type(mp4_timeline_pins.weight));
        callback = callback_obj;
        set(callback_obj, 16, mp4world::AnimationOutput{reinterpret_cast<uintptr_t>(anim_slot), 1, 0});
        set(callback_obj, 32, mp4actor::Handle{});
        ref(callback_obj, "m_Mixers", 48,
            list_object(type(mp4_timeline_pins.weight_info), true, 40, nullptr, 0));
    }
    ref(root_obj, "m_EvaluateCallbacks", 48,
        list_object(type(mp4_timeline_pins.callback), false, 8, &callback, with_weight ? 1 : 0));
    mp4_api.director_get_asset = [](void *, Method *) -> void * { return asset_obj; };
    mp4_api.director_graph_injected = [](void *, mp4game::PlayableGraph *out, Method *) {
        out->handle = reinterpret_cast<void *>(graph_handle.handle);
        out->version = static_cast<int32_t>(graph_handle.version);
    };
    mp4_timeline_pins.output_port.rva = reinterpret_cast<uintptr_t>(get_port);
    mp4_timeline_hooks.current = [](const Mp4TimelineContext &c) {
        assert(c.phase == expected_phase);
        return owner_current;
    };
    mp4_timeline_hooks.restoration_closed = [](const Mp4TimelineContext &c) {
        assert(c.phase == expected_phase);
        return restore_closed;
    };
    mp4_timeline_hooks.animation_output = [](const Mp4TimelineContext &, uintptr_t n) {
        return n == 102 && animation_closed;
    };
    auto none = [](const Mp4TimelineContext &, mp4actor::Handle, void *) {
        return Mp4TimelineVerdict::unrecognized;
    };
    auto no_runtime = [](const Mp4TimelineContext &, const Mp4TimelineRuntime &) {
        return Mp4TimelineVerdict::unrecognized;
    };
    auto no_userdata = [](const Mp4TimelineContext &, mp4actor::Handle, void *, void *) { return false; };
    mp4_timeline_hooks.actor = {
        [](const Mp4TimelineContext &, mp4actor::Handle, void *s) {
            return s == actor_script
                       ? (actor_node_closed ? Mp4TimelineVerdict::closed : Mp4TimelineVerdict::unclosed)
                       : Mp4TimelineVerdict::unrecognized;
        },
        [](const Mp4TimelineContext &, mp4actor::Handle, void *s, void *data) {
            assert(s == actor_script);
            bool rooted = !data;
            for (auto &x : roots)
                rooted |= x.second == data;
            assert(rooted);
            if (mutate_generation)
                ++selected_witness.generation;
            if (mutate_list)
                set(entries_obj, 28, int32_t(4));
            return userdata_closed && data == userdata_value;
        },
        [](const Mp4TimelineContext &, const Mp4TimelineRuntime &r) {
            if (r.element != runtime_obj)
                return Mp4TimelineVerdict::unrecognized;
            return actor_runtime_closed && r.clip == clip_obj && r.track == track_obj &&
                           mp4_actor_same_handle(r.playable, leaf_handle)
                       ? Mp4TimelineVerdict::closed
                       : Mp4TimelineVerdict::unclosed;
        }};
    mp4_timeline_hooks.camera = {none, no_userdata, no_runtime};
    mp4_timeline_hooks.stage_other = {none, no_userdata, no_runtime};
    mp4_timeline_hooks.world = {[](const Mp4TimelineContext &, mp4actor::Handle, void *) {
                                    ++world_node_calls;
                                    return world_claim ? Mp4TimelineVerdict::closed
                                                       : Mp4TimelineVerdict::unrecognized;
                                },
                                no_userdata, no_runtime};
    userdata_value = with_actor ? actor_userdata : nullptr;
}
int main(int argc, char **argv) {
    assert(argc == 2);
    const std::string mode = argv[1];
    bool actor = mode.find("actor") != std::string::npos || mode.find("runtime") != std::string::npos ||
                 mode.find("userdata") != std::string::npos || mode == "generation_change" ||
                 mode == "list_mutation";
    bool runtime = mode.find("runtime") != std::string::npos;
    bool notification = mode.find("notification") != std::string::npos;
    bool weight = mode.find("weight") != std::string::npos;
    setup(actor, runtime, notification, weight);
    bool expected = mode == "basic" || mode == "actor" || mode == "runtime" || mode == "notification_empty" ||
                    mode == "weight" || mode == "active" || mode == "source_restore";
    if (mode == "active")
        expected_phase = Mp4TimelineProofPhase::active;
    if (mode == "source_restore")
        expected_phase = Mp4TimelineProofPhase::source_restore;
    if (mode == "missing_delegate")
        mp4_timeline_hooks.camera.node = nullptr;
    if (mode == "current_lost")
        owner_current = false;
    if (mode == "restore_unclosed")
        restore_closed = false;
    if (mode == "wrong_port")
        source_port = 1;
    if (mode == "cache_lost")
        cache_current = false;
    if (mode == "unknown_script")
        nodes[1].script = object(klass("unknown"));
    if (mode == "actor_unclosed") {
        actor_node_closed = false;
        world_claim = true;
    }
    if (mode == "runtime_unclosed")
        actor_runtime_closed = false;
    if (mode == "runtime_unknown")
        runtime_obj->klass = klass("unknown runtime");
    if (mode == "runtime_wrong_parent")
        set(runtime_obj, 48, root_handle);
    if (mode == "runtime_foreign_clip")
        set(runtime_obj, 24, static_cast<void *>(object(klass("ForeignClip"))));
    if (mode == "userdata_unclosed")
        userdata_closed = false;
    if (mode == "userdata_changes")
        userdata_changed = true;
    if (mode == "generation_change")
        mutate_generation = true;
    if (mode == "list_mutation")
        mutate_list = true;
    if (mode == "notification_nonempty") {
        auto *n = static_cast<Obj *>(nodes.back().script);
        void *l = nullptr;
        mp4_actor_field(n, 16, l);
        set(l, 24, int32_t(1));
        void *a = nullptr;
        mp4_actor_field(l, 16, a);
        static_cast<Obj *>(a)->length = 1;
        static_cast<Obj *>(a)->data.resize(24);
    }
    if (mode == "notification_foreign_source")
        set(nodes.back().script, 40, mp4actor::Handle{999, 1, 0});
    if (mode == "weight_unclosed")
        animation_closed = false;
    if (mode == "weight_foreign_output")
        set(callback_obj, 16, mp4world::AnimationOutput{});
    if (mode == "weight_foreign_motion")
        set(callback_obj, 32, mp4actor::Handle{999, 1, 0});
    if (mode == "weight_unknown_callback")
        callback_obj->klass = klass("UnknownCallback");
    if (mode == "active_foreign") {
        auto *unknown = object(type(mp4_timeline_pins.clip));
        void *a = nullptr;
        mp4_actor_field(active_obj, 16, a);
        static_cast<Obj *>(a)->length = 1;
        static_cast<Obj *>(a)->data.resize(8);
        std::memcpy(static_cast<Obj *>(a)->data.data(), &unknown, 8);
        set(active_obj, 24, int32_t(1));
    }
    const auto baseline = roots.size();
    bool result =
        mp4_timeline_script_output_closed(expected_phase, selected_witness, {77, 11, 2, 0, 0, 0}, 101);
    if (mode == "actor_unclosed")
        assert(world_node_calls == 0);
    assert(roots.size() == baseline);
    if (result != expected) {
        std::fprintf(stderr, "%s got%d expected%d\n", mode.c_str(), result, expected);
        return 1;
    }
}
