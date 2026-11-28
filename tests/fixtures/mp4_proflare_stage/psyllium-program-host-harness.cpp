#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstring>
struct Obj{int cls=0;void*compute=nullptr,*render=nullptr,*owner=nullptr;};
Obj controller{4},feature{1},compute{2},render{3};
struct Source{uint64_t generation=7;void*camera=reinterpret_cast<void*>(1);};
struct{Source source;void*psyllium=&controller;}mp4_stage_host;
namespace idoly_mp4_runtime{struct{uint64_t generation=11;}job;}
struct Scope{bool okay=true;bool source_quiescent(){return okay;}}mp4_stage_psyllium;
struct{bool captured=true;}mp4_stage_psy_state;
bool thread=true,owner=true,state=true,code=true,detail=true,mapping=true,alive=true,sourceok=true;
bool game_call(){return thread;}bool mp4_stage_owner(void*){return owner;}bool mp4_stage_psy_state_current(void*){return state;}
bool mp4_renderer_source_program_closed(){return code;}
struct Pin{uintptr_t rva;size_t bytes;uint8_t body[32];};uint8_t bytes[32]={1,2,3,4};uintptr_t image_base=reinterpret_cast<uintptr_t>(bytes);Pin mp4_psy_program_code[]={{1,20,{2,3,4}}};
namespace mp4game{struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};}
bool hooked=false;bool mp4_prefix(const mp4game::Binding&p){return !std::memcmp(reinterpret_cast<void*>(image_base+p.rva),p.prefix,16);}
bool mp4_hook_was_statically_verified(const mp4game::Binding&){return hooked;}
bool mp4_actor_mapped(const void*,size_t,bool){return mapping;}
struct Mp4OriginalRendererSource{Source scene;void*camera=reinterpret_cast<void*>(1);void*features=reinterpret_cast<void*>(2);};
bool mp4_original_renderer_source_detail(Mp4OriginalRendererSource&r){r={};return detail;}bool mp4_scene_same_source(const Source&a,const Source&b){return a.generation==b.generation&&a.camera==b.camera;}
struct Type{int code;const char*space;const char*name;};struct FeatureSchema{Type type;};FeatureSchema mp4_reuse_features[12];FeatureSchema mp4_reuse_passes[16];
void*mp4_resolved_type_class(int c,const char*,const char*){return reinterpret_cast<void*>(static_cast<uintptr_t>(c));}
void*object_class(void*p){return reinterpret_cast<void*>(static_cast<uintptr_t>(static_cast<Obj*>(p)->cls));}
void*features[3]={&feature};size_t featurecount=1;bool list=true;
bool mp4_actor_list(void*,void***v,size_t*n,size_t){*v=features;*n=featurecount;return list;}
bool mp4_alive(void*){return alive;}
bool mp4_actor_field(void*p,size_t at,void*&v){auto*o=static_cast<Obj*>(p);if(p==&feature&&at==56){v=o->compute;return true;}if(p==&feature&&at==64){v=o->render;return true;}if((p==&compute&&at==160)||(p==&render&&at==136)){v=o->owner;return true;}return false;}
bool mp4_stage_psy_source(void*,void*c,void*p,void*){return sourceok&&c==&controller&&p==&render;}
#include "psyllium-program-host.inc"
void reset(){controller={4};feature={1,&compute,&render};compute={2,nullptr,nullptr,&controller};render={3,nullptr,nullptr,&controller};mp4_stage_host={};idoly_mp4_runtime::job.generation=11;mp4_stage_psyllium={};mp4_stage_psy_state={};thread=owner=state=code=detail=mapping=alive=sourceok=list=true;bytes[0]=1;mp4_psy_program_code[0]={1,20,{2,3,4}};std::memset(bytes,0,sizeof(bytes));bytes[1]=2;bytes[2]=3;bytes[3]=4;hooked=false;mp4_reuse_features[11]={{1,"",""}};mp4_reuse_passes[14]={{2,"",""}};mp4_reuse_passes[15]={{3,"",""}};features[0]=&feature;features[1]=nullptr;featurecount=1;}
int main(){unsigned n=0;reset();assert(mp4_stage_graphics_psyllium_current(7,11));++n;
 for(int bad=0;bad<23;++bad){reset();if(bad==0)thread=false;if(bad==1)owner=false;if(bad==2)state=false;if(bad==3)code=false;if(bad==4)detail=false;if(bad==5)mapping=false;if(bad==6)alive=false;if(bad==7)sourceok=false;if(bad==8)list=false;if(bad==9)mp4_stage_psy_state.captured=false;if(bad==10)mp4_stage_psyllium.okay=false;if(bad==11)mp4_stage_host.psyllium=nullptr;if(bad==12)++mp4_stage_host.source.generation;if(bad==13)++idoly_mp4_runtime::job.generation;if(bad==14)bytes[1]^=1;if(bad==15)mp4_psy_program_code[0].bytes=0;if(bad==16)mp4_reuse_features[11].type.code=0;if(bad==17)feature.compute=nullptr;if(bad==18)compute.cls=3;if(bad==19)render.owner=&feature;if(bad==20)compute.owner=&feature;if(bad==21){features[1]=&feature;featurecount=2;}if(bad==22)features[0]=nullptr;assert(!mp4_stage_graphics_psyllium_current(7,11));++n;}
 reset();assert(!mp4_stage_graphics_psyllium_current(0,11)&&!mp4_stage_graphics_psyllium_current(7,0));++n;
 reset();hooked=true;bytes[1]^=1;assert(mp4_stage_graphics_psyllium_current(7,11));++n;bytes[18]^=1;assert(!mp4_stage_graphics_psyllium_current(7,11));++n;
 std::printf("%u actual Psyllium programme cases passed\n",n);
}
