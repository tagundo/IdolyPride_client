#include "particle-renderer-invalidate-model.inc"
struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};struct{Binding setter{};struct{uintptr_t rva=0;uint8_t prefix[16]{};}native;size_t bytes=0;uint8_t body[288]{};uintptr_t flag=0;bool indirect=false;}mp4_particle_descriptor_reset_pins;
uintptr_t image_base=0;using Method=void;bool managed_prefix=true,plan_good=true;uint8_t native_code[288]{},notification_flag=0;uintptr_t flag_pointer=0;int mesh_calls=0,mesh_mode=0;
bool mp4_prefix(const Binding&){return managed_prefix;}
struct Mp4BuiltinPlan{struct{void*particle=nullptr,*renderer=nullptr;uintptr_t native=0;int32_t instance=0;}source{};void*mesh=nullptr;}builtin_plan;
const Mp4BuiltinPlan*mp4_builtin_plan_current(void*r,uint64_t serial){return plan_good&&r==renderer&&serial==79?&builtin_plan:nullptr;}
// The production field reader uses mapped memory. Add only this exact flag
// read to its prior model; source identity remains the real invalidate helper.
// Avoid defining a second body for prior readers: these aliases apply only to
// the next actual descriptor helper.
bool descriptor_game_call(){return game_call();}
template<class T>bool descriptor_field(void*p,size_t off,T&v){if(p==&flag_pointer&&off==0&&sizeof v==sizeof flag_pointer){::memcpy(&v,p,sizeof v);return true;}if(p==&notification_flag&&off==0&&sizeof v==1){::memcpy(&v,p,sizeof v);return true;}return mp4_actor_field(p,off,v);}
void set_mesh(void*r,void*mesh,Method*m){assert(r==renderer&&mesh==builtin_plan.mesh&&!m);++mesh_calls;if(mesh_mode==1)return;put(0x210,uint32_t(0));if(mesh_mode==2)notification_flag=1;if(mesh_mode==3)plan_good=false;if(mesh_mode==4)current=false;}
#define mp4_actor_field descriptor_field
#define game_call descriptor_game_call
#include "particle-renderer-descriptor-reset-host.inc"
#undef mp4_actor_field
#undef game_call
void descriptor_reset(bool indirect){reset();managed_prefix=plan_good=true;notification_flag=0;mesh_calls=mesh_mode=0;flag_pointer=reinterpret_cast<uintptr_t>(&notification_flag);builtin_plan={{particle,renderer,reinterpret_cast<uintptr_t>(native_memory),11},reinterpret_cast<void*>(0xabcdef)};auto&p=mp4_particle_descriptor_reset_pins;p={};p.setter.rva=reinterpret_cast<uintptr_t>(&set_mesh);p.native.rva=reinterpret_cast<uintptr_t>(native_code)-1;p.bytes=288;p.flag=(indirect?reinterpret_cast<uintptr_t>(&flag_pointer):reinterpret_cast<uintptr_t>(&notification_flag))-1;p.indirect=indirect;put(0x210,uint32_t(99));}
int main(){unsigned cases=0;
 for(bool indirect:{false,true})for(bool no_mesh:{false,true}){descriptor_reset(indirect);if(no_mesh)builtin_plan.mesh=nullptr;auto image=capture();restoring=true;assert(mp4_particle_renderer_descriptor_restore(image,79,17)&&mesh_calls==1);uintptr_t untouched=0;assert(mp4_actor_field(native_memory,0x750,untouched)&&untouched==0xfeedface);++cases;}
 for(int bad=0;bad<9;++bad){descriptor_reset(true);auto image=capture();restoring=true;if(bad==0)restoring=false;if(bad==1)managed_prefix=false;if(bad==2)notification_flag=1;if(bad==3)flag_pointer=0;if(bad==4)plan_good=false;if(bad==5)builtin_plan.source.instance++;if(bad==6)builtin_plan.source.particle=nullptr;if(bad==7)current=false;if(bad==8)++mp4_particle_descriptor_reset_pins.body[287];assert(!mp4_particle_renderer_descriptor_restore(image,79,17)&&!mesh_calls);++cases;}
 for(int bad=1;bad<=4;++bad){descriptor_reset(false);auto image=capture();restoring=true;mesh_mode=bad;assert(!mp4_particle_renderer_descriptor_restore(image,79,17)&&mesh_calls==1);++cases;}
 std::printf("%u actual native descriptor-reset host cases passed\n",cases);
}
