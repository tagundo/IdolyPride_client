enum class Mp4SceneResult:int{ok=0,waiting=1,unsupported=-1,invalid=-2,failed=-3,stale=-4};
bool game_thread=true;bool game_call(){return game_thread;}
struct Mp4GpuFenceHost{Ledger ledger{};uint64_t source=0,epoch=0,sequence=0,retired=0,active_token=0,last_token=0;bool draw=false,configured=false,sealed=false;};
Mp4GpuFenceHost mp4_gpu_fence_host,mp4_gpu_auxiliary_host;
Host render_engine,aux_engine;
uint64_t mp4_gpu_auxiliary_dispatched_ticket=0;
auto&mp4_gpu_pins=render_engine.pins;
bool graphics_closed=true,source_cpu_current=true,early_current=true,source_key_current=true;
bool graphics_provider(uint64_t source,uint64_t job){return graphics_closed&&source==4&&job==9;}
bool(*mp4_gpu_graphics_producers_closed)(uint64_t,uint64_t)=graphics_provider;
namespace sb {struct Key{uint64_t epoch=4,job=9;};}
struct {sb::Key key{};uint64_t producer_receipt=73;}mp4_scene_source_bootstrap;
bool worker_current(void*,const sb::Key&k,uint64_t receipt){return source_cpu_current&&k.epoch==4&&k.job==9&&receipt==73;}
struct {void*context=reinterpret_cast<void*>(0x99);struct {bool(*current)(void*,const sb::Key&,uint64_t)=worker_current;}source_producers;}mp4_source_bootstrap_joins;
struct {bool current()const{return early_current;}}mp4_early_source_gates;
// The actual hold current/reader/activity bodies are extracted below. Only the
// independently certified hook endpoints and the unused original-stack shape
// are physical leaf fixtures; neither one grants unconditional quiet.
bool render_frontends=true;
bool mp4_render_hold_frontends(){return render_frontends;}
struct Mp4RenderHoldOriginal{inline static thread_local void*current=nullptr;};
// SHIPPING_RENDER_HOLD_QUIET
struct {bool active=true,invalidated=false,releasing=false;unsigned configured=15,captured=15,prepared=0,all=15;}mp4_scene_host;
struct{unsigned depth=0;}mp4_raw_original_operation;struct{bool active=false;}mp4_rebuild_ledger;
bool mp4_scene_bootstrap_key(const sb::Key&key){return source_key_current&&key.epoch==4&&key.job==9;}
Mp4SceneResult mp4_gpu_gl_preflight(uint64_t,uint64_t){return Mp4SceneResult::ok;}
bool mp4_gpu_host_sources(void*,const Pins&){return graphics_closed;}
bool mp4_gpu_host_configure(uint64_t source,uint64_t job){auto&h=mp4_gpu_fence_host;if(h.configured)return false;h.source=source;h.epoch=job;return h.configured=h.ledger.configure(render_engine.api,render_engine.pins,job);}
namespace idoly_mp4_runtime {
struct{uint64_t generation=9;}job;
// SHIPPING_CAPTURE_WORK_SNAPSHOT
}
unsigned mp4_owned_render_depth=0,mp4_unowned_render_depth=0;bool mp4_owned_render_ticket_active=false;
// SHIPPING_NATIVE_READER
// SHIPPING_REQUEST_GUARD
// SHIPPING_PRODUCTION_BANK
// SHIPPING_QUEUE_GATE
// SHIPPING_QUEUE_JOURNAL
namespace mp4production=idoly_mp4_capture_production;
namespace mp4cq=idoly_mp4_capture_queue;
struct Mp4SceneWitness{uint64_t generation=4;void*controller=reinterpret_cast<void*>(0x1234);};
struct Mp4CaptureProductionHost{mp4production::Bank bank;Mp4SceneWitness source{};uint64_t job=9,publication_request=0,operation_serial=0;idoly_mp4_capture_publication::Receipt publication_receipt{};bool configured=false,publication_returned=false;};
struct Mp4CaptureQueueHost{mp4cq::Journal journal{};mp4cq::Gate gate{};Mp4CaptureProductionHost*production=nullptr;void*component=reinterpret_cast<void*>(0x4321);uint64_t job=9,epoch=4;bool bound=false;};
struct Mp4FrameCaptureHost{Mp4CaptureProductionHost production{};Mp4CaptureQueueHost queue{};Mp4SceneWitness source{};uint64_t job=9,operation=0,native_serial=0;bool active=true,baseline=true,production_ready=false,inflight=false,sealed=false,abandoned=false;}mp4_frame_capture_host;
Mp4CaptureProductionHost*mp4_capture_production_published=nullptr;
Mp4CaptureQueueHost*mp4_capture_queue_published=nullptr,*mp4_capture_queue_retiring=nullptr;
uint64_t mp4_capture_queue_readers=0;uint8_t mp4_capture_queue_untracked=0;uint32_t mp4_capture_production_dirty=0;
int capture_set_count=0,observe_calls=0;bool set_idle=true,observe_ok=true;
bool mp4_renderer_capture_set_idle(void*){return set_idle&&capture_set_count==0;}
bool mp4_capture_queue_observe(void*,void*,const mp4cq::Target&,mp4cq::Set*out){++observe_calls;if(!observe_ok)return false;*out={reinterpret_cast<void*>(0x333),3,capture_set_count,capture_set_count,capture_set_count==1};return true;}
bool queue_retained(void*,void*,uint64_t,uint64_t){return true;}
bool queue_request(void*,void*,uint64_t*){return false;}
bool queue_update(void*,void*,mp4cq::Origin*){return false;}
bool queue_resource(void*,mp4cq::Origin*,const mp4cq::Target&){return false;}
