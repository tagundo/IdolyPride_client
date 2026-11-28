// Engine/IL2CPP/GPU services below are explicit host models; implementation is extracted from shipping source.

#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstring>
using Method=void;struct Obj{uint8_t bytes[96]{};}equipment,array,flare,go;
struct Mp4SceneWitness{uint64_t generation=7;};enum class Mp4TimelineProofPhase{admission};struct Mp4TimelineContext{Mp4TimelineProofPhase phase;Mp4SceneWitness witness;};
bool thread=true,exact=true,hooks=true,field=true,keep=true,retained=true,image=true,plan=true,drift=false,wrong_go=false;unsigned plans=0,images=0;void*rows[2]{&flare,&flare};size_t row_count=1;
struct Mp4ProFlareAccess{Mp4ProFlareAccess(){}~Mp4ProFlareAccess(){}};struct Mp4ActorTempRoot{void*p;explicit Mp4ActorTempRoot(void*x):p(x){}void*get(){return keep?p:nullptr;}};
struct{bool captured=false;uint64_t serial=13;}owner,*mp4_proflare_coordinator=nullptr;
struct PFPlan{Mp4SceneWitness source;struct{struct{void*go=&::go;}image;}retained;}pfplan;
bool game_call(){return thread;}bool mp4_exact_type(void*p,const char*){return exact&&p==&equipment;}bool mp4_proflare_backend_hooks(){return hooks;}bool mp4_root_track_field(void*,const char*,size_t){return field;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){if(p!=&equipment||at!=72)return false;void*v=drift?nullptr:static_cast<void*>(&array);std::memcpy(&out,&v,sizeof out);return true;}
bool mp4_stage_array(void*p,void***out,size_t*n,size_t limit){if(p!=&array||row_count>limit)return false;*out=rows;*n=row_count;return true;}
struct Binding{};struct{Binding component_gameobject;}mp4_stage_profile;void*original_go(void*p,Method*){return p==&flare&&!wrong_go?&go:nullptr;}template<class T>T mp4_equipment_call(Binding){return reinterpret_cast<T>(original_go);}
const PFPlan*mp4_proflare_source_plan_find(void*p){return p==&flare?&pfplan:nullptr;}bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.generation==b.generation;}bool mp4_proflare_source_plan_retained(const PFPlan&){return retained;}
bool mp4_proflare_component_family(void*p,uint64_t*out){++images;*out=image?owner.serial:0;return image&&p==&flare;}
bool mp4_proflare_source_component_plan(const Mp4TimelineContext&c,void*p,void*g){++plans;return plan&&c.phase==Mp4TimelineProofPhase::admission&&c.witness.generation==7&&p==&flare&&g==&go;}

#include "equipment-source-plan-host.inc"

void reset(){thread=exact=hooks=field=keep=retained=image=plan=true;drift=wrong_go=false;plans=images=0;rows[0]=rows[1]=&flare;row_count=1;owner={};mp4_proflare_coordinator=nullptr;pfplan={};}
int main(){unsigned cases=0;reset();assert(mp4_proflare_equipment_source_plan(&equipment,&array,{})&&plans==1&&!images);++cases;
 reset();owner.captured=true;mp4_proflare_coordinator=&owner;assert(mp4_proflare_equipment_source_plan(&equipment,&array,{})&&!plans&&images==1);++cases;
 for(int bad=0;bad<9;++bad){reset();if(bad==0)thread=false;if(bad==1)exact=false;if(bad==2)hooks=false;if(bad==3)field=false;if(bad==4)keep=false;if(bad==5)drift=true;if(bad==6)wrong_go=true;if(bad==7)plan=false;if(bad==8)row_count=129;assert(!mp4_proflare_equipment_source_plan(&equipment,&array,{}));++cases;}
 reset();row_count=2;assert(!mp4_proflare_equipment_source_plan(&equipment,&array,{}));++cases;
 reset();rows[0]=nullptr;assert(!mp4_proflare_equipment_source_plan(&equipment,&array,{}));++cases;
 for(int bad=0;bad<3;++bad){reset();owner.captured=true;mp4_proflare_coordinator=&owner;if(bad==0)retained=false;if(bad==1)image=false;if(bad==2)pfplan.source.generation=8;assert(!mp4_proflare_equipment_source_plan(&equipment,&array,{})&&!plans);++cases;}
 std::printf("%u actual PF Equipment field/source-vs-retained plan cases passed\n",cases);}
