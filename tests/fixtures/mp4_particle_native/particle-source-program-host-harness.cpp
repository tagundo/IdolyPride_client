#define MP4_PARTICLE_POLICY_NO_MAIN
#include "particle-source-policy-host-harness.cpp"
namespace mp4actor{struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};}
bool mp4_actor_same_handle(mp4actor::Handle a,mp4actor::Handle b){return a.handle==b.handle&&a.version==b.version;}
enum class Mp4ControlSourceRole:uint8_t{director,activation,particle};
struct Mp4ControlSourceLeaf{mp4actor::Handle node{};void*script=nullptr,*target=nullptr;uint32_t seed=0;Mp4ControlSourceRole role=Mp4ControlSourceRole::particle;};
struct Mp4TimelineContext{Mp4SceneWitness witness{};void*director=nullptr,*asset=nullptr;mp4actor::Handle graph{};};
struct AdmissionEntry{struct{void*particle=nullptr,*producer=nullptr;uint32_t producer_kind=1;}owner{};uintptr_t particle_native=0;int32_t particle_id=0;void*particle_go=nullptr;mp4actor::Handle node{};};
struct{AdmissionEntry particles[2]{};size_t count=1;uint64_t receipt=17;bool committed=true;}mp4_stage_admission_particles;
bool admission=true,resolved=true,capable=true,context_match=true;
bool mp4_stage_admission_source(const Mp4SceneWitness&w){return admission&&source&&w.generation==7;}
bool mp4_stage_admission_identity(const AdmissionEntry&e){return admission&&e.owner.particle==particle&&e.particle_native==(uintptr_t)native&&e.particle_id==17;}
bool mp4_stage_admission_resolve(const AdmissionEntry&e,mp4actor::Handle*out){if(!resolved||!mp4_stage_admission_identity(e))return false;*out=e.node;return true;}
bool mp4_stage_admission_particle(const Mp4SceneWitness&w,void*d,void*a,mp4actor::Handle g,mp4actor::Handle node,void*script,void*p,uint32_t seed){const auto&e=mp4_stage_admission_particles.particles[0];return context_match&&mp4_stage_admission_particles.committed&&mp4_stage_admission_source(w)&&d==go&&a==renderer_type&&g.handle==101&&g.version==2&&mp4_actor_same_handle(node,e.node)&&script==e.owner.producer&&p==particle&&seed==77;}
struct Mp4BuiltinSource{void*particle=nullptr,*renderer=nullptr;uintptr_t native=0;int32_t instance=0;uint32_t path=0;uint64_t receipt=0;};
struct{bool(*source_current)(const Mp4BuiltinSource&)=nullptr;bool(*held_current)(const Mp4BuiltinSource&,uint64_t)=nullptr;}mp4_builtin_context;
struct BuiltinPlan{Mp4BuiltinSource source{};uint64_t receipt=0;}builtin_plan;
uint32_t expected_path=0;uint64_t nextplan=91;
bool mp4_builtin_plan_create(const Mp4BuiltinSource&s,uint64_t*out){*out=0;if(s.path!=expected_path||!mp4_builtin_context.source_current||!mp4_builtin_context.source_current(s))return false;builtin_plan={s,++nextplan};*out=builtin_plan.receipt;return true;}
const BuiltinPlan*mp4_builtin_plan_current(void*r,uint64_t plan){return plan&&plan==builtin_plan.receipt&&r==renderer&&mp4_builtin_context.source_current&&mp4_builtin_context.source_current(builtin_plan.source)?&builtin_plan:nullptr;}
bool mp4_particle_mutation_exclusion(const Mp4ParticleFinishOwner&o,uint64_t e){return finish_current&&e==61&&o.managed==particle;}
bool mp4_particle_native_capability(){return capable;}
#include "particle-source-program-host.inc"
void*script=nullptr;Mp4TimelineContext context{};Mp4ControlSourceLeaf leaf{};
void program_setup(){script=alloc(32);}
void program_reset(){mp4_particle_source_program_clear();reset();admission=resolved=capable=context_match=true;expected_path=0;builtin_plan={};mp4_stage_admission_particles={};mp4_stage_admission_particles.count=1;mp4_stage_admission_particles.receipt=17;mp4_stage_admission_particles.committed=true;mp4_stage_admission_particles.particles[0]={{particle,script,1},(uintptr_t)native,17,go,{103,2,0}};context={{7},go,renderer_type,{101,2,0}};leaf={{103,2,0},script,particle,77,Mp4ControlSourceRole::particle};}
uint64_t create(){uint64_t r=0;assert(mp4_particle_source_program_create(context,leaf,&r)&&r);return r;}
int main(){setup();program_setup();unsigned cases=0;
 {program_reset();auto r=create();const auto*p=mp4_particle_source_program_find(particle);assert(p&&p->serial==r&&p->plan&&mp4_particle_source_program_current(*p));uint64_t second=0;assert(mp4_particle_source_program_create(context,leaf,&second)&&second==r);++cases;}
 for(uint32_t path:{10209u,10210u}){program_reset();expected_path=path;create();assert(mp4_particle_source_program_find(particle)->builtin_path==path);++cases;}
 {program_reset();capable=false;uint64_t r=0;assert(!mp4_particle_source_program_create(context,leaf,&r)&&!r);++cases;}
 {program_reset();admission=false;uint64_t r=0;assert(!mp4_particle_source_program_create(context,leaf,&r));++cases;}
 {program_reset();context_match=false;uint64_t r=0;assert(!mp4_particle_source_program_create(context,leaf,&r));++cases;}
 {program_reset();create();resolved=false;assert(!mp4_particle_source_program_current(*mp4_particle_source_program_find(particle)));++cases;}
 {program_reset();create();mp4_stage_admission_particles.receipt++;assert(!mp4_particle_source_program_current(*mp4_particle_source_program_find(particle)));++cases;}
 {program_reset();create();put(rnative,8,int32_t(21));assert(!mp4_particle_source_program_current(*mp4_particle_source_program_find(particle)));++cases;}
 {program_reset();create();put(modules,0x1248,uint8_t(1));assert(!mp4_particle_source_program_current(*mp4_particle_source_program_find(particle)));++cases;}
 {program_reset();create();const auto*p=mp4_particle_source_program_find(particle);assert(!mp4_particle_builtin_held_current(builtin_plan.source,61));auto policy=capture();assert(mp4_particle_source_program_bind(particle,policy)&&mp4_particle_builtin_held_current(builtin_plan.source,61));admission=resolved=false;assert(mp4_particle_source_program_current(*p));++cases;}
 {program_reset();create();auto policy=capture();assert(!mp4_particle_source_program_bind(particle,policy+1));++cases;}
 {program_reset();create();auto policy=capture();assert(mp4_particle_source_program_bind(particle,policy));finish_current=false;assert(mp4_particle_source_program_current(*mp4_particle_source_program_find(particle))&&!mp4_particle_builtin_held_current(builtin_plan.source,61));++cases;}
 {program_reset();create();auto policy=capture();assert(mp4_particle_source_program_bind(particle,policy));idoly_mp4_runtime::job.generation++;assert(!mp4_particle_source_program_current(*mp4_particle_source_program_find(particle)));++cases;}
 {program_reset();expected_path=9;uint64_t r=0;assert(!mp4_particle_source_program_create(context,leaf,&r)&&!r&&!mp4_particle_source_program_find(particle));++cases;}
 {program_reset();auto n=roots.size();retain_fail=true;uint64_t r=0;assert(!mp4_particle_source_program_create(context,leaf,&r));retain_fail=false;assert(roots.size()==n);++cases;}
 {program_reset();create();auto n=roots.size();main_thread=false;assert(!mp4_particle_source_program_clear()&&roots.size()==n);main_thread=true;assert(mp4_particle_source_program_clear());++cases;}
 {program_reset();create();auto p=builtin_plan.source;p.receipt++;assert(!mp4_particle_builtin_source_current(p));++cases;}
 {program_reset();create();auto p=builtin_plan.source;p.path=10209;assert(!mp4_particle_builtin_source_current(p));++cases;}
 {program_reset();create();auto p=builtin_plan.source;p.native++;assert(!mp4_particle_builtin_source_current(p));++cases;}
 mp4_particle_source_program_clear();mp4_particle_source_policy_clear();if(mp4_particle_source_renderer_type)weak_free(mp4_particle_source_renderer_type);::free(mp4_particle_source_policies);::free(mp4_particle_source_programs);assert(roots.empty());std::printf("%u actual source-program/physical-bind cases passed\n",cases);
}
