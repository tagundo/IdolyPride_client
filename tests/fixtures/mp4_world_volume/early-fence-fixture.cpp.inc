#include <cstdint>
#include <cstddef>
#include <cassert>
namespace mp4sb {enum class Phase{source_configure,early_barrier};struct Key{};}
bool full=false,owner=true,held=true,valid_key=true,workers=true,leases=true;
bool mp4_director_boundary_closed(void*){return full;}bool game_call(){return owner;}bool mp4_actor_clock_held(void*){return held;}
struct{unsigned depth=0;}mp4_raw_original_operation;struct{bool active=false;}mp4_rebuild_ledger;
struct{bool prepare_started=false;}mp4_volume_assembly;struct{bool in_frame=false;}mp4_volume_factory_host;
struct{uint64_t receipt[2]{0,19},producer_receipt=23;mp4sb::Key key{};}mp4_scene_source_bootstrap;
struct{bool current(){return leases;}}mp4_early_source_gates;
bool worker_current(void*,const mp4sb::Key&,uint64_t actual){return workers&&actual==23;}
struct{void*context=reinterpret_cast<void*>(1);struct{decltype(&worker_current)current=worker_current;}source_producers;}mp4_source_bootstrap_joins;
bool mp4_scene_bootstrap_key(const mp4sb::Key&){return valid_key;}
// SHIPPING_WORLD_VOLUME_EARLY_FENCEint main(){assert(mp4_volume_source_snapshot_fenced());
 mp4_scene_source_bootstrap.receipt[1]=0;assert(!mp4_volume_source_snapshot_fenced());mp4_scene_source_bootstrap.receipt[1]=19;
 mp4_scene_source_bootstrap.producer_receipt=0;assert(!mp4_volume_source_snapshot_fenced());mp4_scene_source_bootstrap.producer_receipt=23;
 mp4_source_bootstrap_joins.source_producers.current=nullptr;assert(!mp4_volume_source_snapshot_fenced());mp4_source_bootstrap_joins.source_producers.current=worker_current;
 workers=false;assert(!mp4_volume_source_snapshot_fenced());workers=true;
 leases=false;assert(!mp4_volume_source_snapshot_fenced());leases=true;
 valid_key=false;assert(!mp4_volume_source_snapshot_fenced());valid_key=true;
 mp4_raw_original_operation.depth=1;assert(!mp4_volume_source_snapshot_fenced());mp4_raw_original_operation.depth=0;
 mp4_rebuild_ledger.active=true;assert(!mp4_volume_source_snapshot_fenced());mp4_rebuild_ledger.active=false;
 mp4_volume_assembly.prepare_started=true;assert(!mp4_volume_source_snapshot_fenced());mp4_volume_assembly.prepare_started=false;
 mp4_volume_factory_host.in_frame=true;assert(!mp4_volume_source_snapshot_fenced());mp4_volume_factory_host.in_frame=false;
 held=false;assert(!mp4_volume_source_snapshot_fenced());held=true;
 owner=false;assert(!mp4_volume_source_snapshot_fenced());owner=true;
 full=true;mp4_scene_source_bootstrap.receipt[1]=0;assert(mp4_volume_source_snapshot_fenced());
}