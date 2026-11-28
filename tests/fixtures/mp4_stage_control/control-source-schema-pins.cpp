#include <cassert>
#include <cstdint>
#include <cstring>
#include <initializer_list>
#include <string>
using Method=const void;
namespace mp4game{struct Binding{uintptr_t rva=0;unsigned char prefix[16]{};};}
struct Pin{const char*name="type";mp4game::Binding binding{};};
struct{Pin control_asset,director_component;mp4game::Binding control_create,graph_resolver;}mp4_stage_other_pins;
struct{mp4game::Binding graph_valid,director_get_reference;}mp4_profile;
struct{mp4game::Binding component_gameobject;}mp4_stage_profile;
struct{mp4game::Binding playable_valid,playable_graph_get;}mp4_actor_profile;
struct{mp4game::Binding class_size,field_flags;}mp4_cam_profile;
struct{void*(*director_get_reference)(void*,int,bool*,Method*)=nullptr;}mp4_api;
uintptr_t image_base=8;bool mp4_source_verified=true,thread=true,type_ok=true,prefix_ok=true,hook_ok=false,mp4_output_calls_verified=false,mp4_actor_source_verified=false,mp4_stage_source_verified=false;size_t prefixes=0,type_reads=0;
using Fn=void(*)();void stub(){} Fn font_field=stub,font_field_type=stub,font_class_type=stub,font_method=stub,object_class=stub,class_name=stub,class_namespace=stub,weak_get=stub,weak_free=stub,font_strong=stub;
bool game_call(){return thread;}void*mp4_timeline_class(const Pin&){++type_reads;return type_ok?&image_base:nullptr;}
bool mp4_prefix(const mp4game::Binding&){++prefixes;return prefix_ok;}bool mp4_hook_was_statically_verified(const mp4game::Binding&){return hook_ok;}
#include "control-source-schema-pins.cpp"
void*reference(void*,int,bool*,Method*){return nullptr;}
int main(int argc,char**argv){assert(argc==2);std::string c=argv[1];mp4_api.director_get_reference=reference;mp4_profile.director_get_reference.rva=reinterpret_cast<uintptr_t>(&reference)-image_base;
 if(c=="source")mp4_source_verified=false;else if(c=="thread")thread=false;else if(c=="base")image_base=0;else if(c=="metadata")font_field_type=nullptr;else if(c=="type")type_ok=false;else if(c=="prefix")prefix_ok=false;else if(c=="hooked"){prefix_ok=false;hook_ok=true;}else if(c=="wrong_pointer")++mp4_profile.director_get_reference.rva;else if(c=="missing_pointer")mp4_api.director_get_reference=nullptr;
 assert(mp4_control_source_pins_ready()==(c=="normal"||c=="hooked"));
 if(c=="normal")assert(!mp4_output_calls_verified&&!mp4_actor_source_verified&&!mp4_stage_source_verified&&prefixes==9&&type_reads==2);
}
