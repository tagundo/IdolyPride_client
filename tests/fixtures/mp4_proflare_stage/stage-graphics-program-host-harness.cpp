#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdio>
struct Source{uint64_t generation=7;void*camera=reinterpret_cast<void*>(1);};
struct{Source source;bool configured=true,admitting=false;size_t count=1;}mp4_stage_host;
struct{Source source;}mp4_scene_host;namespace idoly_mp4_runtime{struct{uint64_t generation=11;}job;}
bool main_thread=true,owner=true,eqcurrent=true,psc=true,pins=true,vlb=true,normal=true,descriptor=true,retained=true,program=true,lookup=true,pf=true,psy=true;
bool game_call(){return main_thread;}bool mp4_stage_owner(void*){return owner;}
struct Scope{bool enabled=true;bool active(){return enabled;}bool source_quiescent(){return eqcurrent;}}mp4_stage_equipment,mp4_stage_psyllium;
struct{bool active(){return psc;}}mp4_stage_particles;
struct Target{void*object=reinterpret_cast<void*>(1);uint32_t kind=3;void*beam=reinterpret_cast<void*>(2);};struct{bool started=true,captured=true;Target targets[3];size_t count=1;}mp4_equipment_targets;
bool mp4_equipment_pins_current(){return pins;}
struct{bool started=true,captured=true,failed=false;void*in_flight=nullptr;}mp4_vlb_state;
bool mp4_stage_vlb_current(){return vlb;}bool mp4_vlb_capi_ready(){return vlb;}
namespace mp4ps{struct Owner{void*managed=reinterpret_cast<void*>(3);};}
struct Host{bool captured=true;uint64_t serial=13;Source source;uint64_t job=11;size_t count=1;}native_host;Host*mp4_particle_native_host=&native_host;
struct Mp4ParticleRetainedWorkerOwner{mp4ps::Owner owner{};void*renderer=reinterpret_cast<void*>(4);uintptr_t renderer_native=5;int32_t renderer_id=6;uint64_t image=17;};
bool mp4_particle_renderer_normal_program_bindings(){return normal;}bool mp4_particle_renderer_descriptor_bindings(){return descriptor;}
bool mp4_particle_native_retained_worker_inventory(uint64_t s,uint64_t j,uint64_t c,Mp4ParticleRetainedWorkerOwner*out,size_t cap,size_t*n){if(!retained||s!=7||j!=11||c!=13||cap<1)return false;*out={};*n=1;return true;}
struct Program{uint64_t serial=19,plan=23;struct{void*renderer=reinterpret_cast<void*>(4);uintptr_t renderer_native=5;int32_t renderer_id=6;}pair;}plan;
const Program*mp4_particle_source_program_find(void*p){return p==reinterpret_cast<void*>(3)?&plan:nullptr;}bool mp4_particle_source_program_current(const Program&){return program;}
void*feature=reinterpret_cast<void*>(9);bool feature_active=true;
bool mp4_renderer_proflare_source(void*,void**f,void**c,void**r,void**b,void**d){*f=feature;*c=*r=*b=*d=nullptr;return lookup;}
bool mp4_actor_field(void*p,size_t offset,bool&value){if(p!=feature||offset!=24)return false;value=feature_active;return true;}
bool pfprovider(uint64_t s,uint64_t j){return pf&&s==7&&j==11;}bool psyprovider(uint64_t s,uint64_t j){return psy&&s==7&&j==11;}
bool mp4_stage_graphics_psyllium_current(uint64_t s,uint64_t j){return psyprovider(s,j);}
#include "stage-graphics-program-host.inc"
void reset(){main_thread=owner=eqcurrent=psc=pins=vlb=normal=descriptor=retained=program=lookup=pf=psy=true;mp4_stage_host={};mp4_scene_host={};idoly_mp4_runtime::job.generation=11;mp4_stage_equipment={};mp4_stage_psyllium={};mp4_equipment_targets={};mp4_vlb_state={};native_host={};mp4_particle_native_host=&native_host;plan={};feature=reinterpret_cast<void*>(9);feature_active=true;mp4_stage_graphics_proflare_program_current=pfprovider;mp4_stage_graphics_psyllium_program_current=psyprovider;}
int main(){unsigned cases=0;reset();assert(mp4_stage_graphics_program_current(7,11));++cases;
 for(int bad=0;bad<27;++bad){reset();if(bad==0)main_thread=false;if(bad==1)owner=false;if(bad==2)eqcurrent=false;if(bad==3)pins=false;if(bad==4)mp4_stage_host.configured=false;if(bad==5)mp4_stage_host.admitting=true;if(bad==6)mp4_stage_equipment.enabled=false;if(bad==7)mp4_equipment_targets.started=false;if(bad==8)mp4_equipment_targets.captured=false;if(bad==9)mp4_equipment_targets.targets[0].kind=9;if(bad==10)mp4_equipment_targets.targets[0].kind=4;if(bad==11)mp4_vlb_state.failed=true;if(bad==12)mp4_vlb_state.in_flight=reinterpret_cast<void*>(1);if(bad==13)vlb=false;if(bad==14)mp4_particle_native_host=nullptr;if(bad==15)native_host.captured=false;if(bad==16)++native_host.job;if(bad==17)++native_host.count;if(bad==18)psc=false;if(bad==19)normal=false;if(bad==20)descriptor=false;if(bad==21)retained=false;if(bad==22)program=false;if(bad==23)++plan.pair.renderer_id;if(bad==24)lookup=false;if(bad==25)pf=false;if(bad==26)mp4_stage_graphics_proflare_program_current=nullptr;assert(!mp4_stage_graphics_program_current(7,11));++cases;}
 reset();feature=nullptr;mp4_stage_graphics_proflare_program_current=nullptr;assert(mp4_stage_graphics_program_current(7,11));++cases;
 reset();feature_active=false;mp4_stage_graphics_proflare_program_current=nullptr;assert(mp4_stage_graphics_program_current(7,11));++cases;
 reset();mp4_stage_host.count=0;mp4_particle_native_host=nullptr;normal=false;assert(mp4_stage_graphics_program_current(7,11));++cases;
 reset();mp4_equipment_targets.targets[0].kind=6;assert(mp4_stage_graphics_program_current(7,11));++cases;psy=false;assert(!mp4_stage_graphics_program_current(7,11));++cases;psy=true;mp4_stage_graphics_psyllium_program_current=nullptr;assert(!mp4_stage_graphics_program_current(7,11));++cases;
 reset();assert(!mp4_stage_graphics_program_current(8,11)&&!mp4_stage_graphics_program_current(7,12));++cases;
 std::printf("%u actual Stage graphics programme host cases passed\n",cases);
}
