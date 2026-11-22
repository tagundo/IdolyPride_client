// Explicit original/descriptor/owner service models. The actual Scope and all
// seven source-pinned frontends come from the shipping Bridge markers.
#include <atomic>
namespace mp4dn=idoly_mp4_director_nodes;
namespace mp4actor{using Handle=dn::Handle;}
using Method=const void;
namespace mp4drive=mp4_child_driving;
std::atomic<bool>mp4_child_driving_active{false},mp4_child_driving_rejected{false};
mp4drive::Scope mp4_child_driving_scope;
Model*model=nullptr;bool owner=true,descriptor=true,schema=true;unsigned original_calls=0,quarantines=0;int frontend_mode=0;
uintptr_t image_base=0,expected_entry=0;
bool game_call(){return owner;}
bool mp4_child_driving_bindings(void*){return model&&model->bindings;}
bool mp4_director_node_schema(void*){return schema;}
void*object_class(void*){return reinterpret_cast<void*>(0x123);}
Method*resolve(void*,const char*,int){return descriptor?reinterpret_cast<Method*>(&expected_entry):nullptr;}
Method*(*font_method)(void*,const char*,int)=resolve;
template<class T>bool mp4_actor_field(void*p,size_t off,T&out){if(p!=&expected_entry||off!=0||sizeof(T)!=sizeof(uintptr_t))return false;memcpy(&out,&expected_entry,sizeof out);return true;}
struct NodeLease{bool captured()const{return true;}bool lookup_receiver(void*script,bool retired,dn::Node*out)const{assert(!retired);if(!model||script!=model->live().script)return false;*out=model->live();return true;}}mp4_director_nodes;
struct{void(*quarantine)(const char*)noexcept=+[](const char*)noexcept{++quarantines;};}mp4_child_execution_hooks;
// ACTUAL_DRIVING_PINS
// ACTUAL_DRIVING_HOOKS
void process(void*,mp4actor::Handle,Mp4ChildDrivingFrameData,void*,Method*opaque){++original_calls;assert(opaque==reinterpret_cast<Method*>(0xdeadc0de));if(frontend_mode==7)throw 42;if(frontend_mode==12)model->source=false;}
void frame(void*,mp4actor::Handle,Mp4ChildDrivingFrameData,Method*opaque){++original_calls;assert(opaque==reinterpret_cast<Method*>(0xdeadc0de));}
void update(void*,mp4actor::Handle,Method*opaque){++original_calls;assert(opaque==reinterpret_cast<Method*>(0xdeadc0de));}
void sync(void*,mp4actor::Handle,double,Method*opaque){++original_calls;assert(opaque==reinterpret_cast<Method*>(0xdeadc0de));}
int main(int argc,char**argv){assert(argc==2);frontend_mode=atoi(argv[1]);Model m;model=&m;assert(mp4_child_driving_scope.configure(m.api()));
 struct Cleanup{~Cleanup(){assert(mp4_child_driving_scope.release()==R::ok);}}cleanup;
 mp4_child_driving_prepare_original=frame;mp4_child_driving_play_original=frame;mp4_child_driving_pause_original=frame;mp4_child_driving_process_original=process;mp4_child_driving_update_original=update;mp4_child_driving_start_original=sync;mp4_child_driving_stop_original=sync;
 auto n=m.live();auto playable=n.node;Method*opaque=reinterpret_cast<Method*>(0xdeadc0de);void*script=n.script;Mp4ChildDrivingFrameData data{};
 if(frontend_mode==1){mp4_child_driving_prepare_hook(script,playable,data,opaque);assert(original_calls==1&&!mp4_child_driving_rejected.load());return 0;}
 assert(mp4_child_driving_scope.capture(9,0x99)==R::ok&&mp4_child_driving_scope.begin_frame(0)==R::ok);assert(mp4_child_driving_scope.mark_frame_issued(0)==R::ok);mp4_child_driving_active.store(true);m.origin=true;m.held=false;expected_entry=image_base+mp4_child_driving_hooks.methods[3].rva;
 if(frontend_mode==3)descriptor=false;
 if(frontend_mode==4)++expected_entry;
 if(frontend_mode==5)owner=false;
 if(frontend_mode==6)script=(void*)0x789;
 if(frontend_mode==10)m.bindings=false;
 if(frontend_mode==13)++playable.version;
 if(frontend_mode==14)m.node_current=false;
 if(frontend_mode==7){bool caught=false;try{mp4_child_driving_process_hook(script,playable,data,nullptr,opaque);}catch(int value){caught=value==42;}assert(caught&&original_calls==1&&mp4_child_driving_scope.failed()&&mp4_child_driving_rejected.load()&&quarantines==1);return 0;}
 if(frontend_mode==8){expected_entry=mp4_child_driving_hooks.methods[2].rva;mp4_child_driving_pause_hook(script,playable,data,opaque);m.live_active=false;}
 else if(frontend_mode==9){expected_entry=mp4_child_driving_hooks.methods[1].rva;mp4_child_driving_play_hook(script,playable,data,opaque);}
 else if(frontend_mode==16)mp4_child_driving_update_hook(script,playable,opaque);
 else if(frontend_mode==17)mp4_child_driving_stop_hook(script,n.graph,1.0,opaque);
 else mp4_child_driving_process_hook(script,playable,data,frontend_mode==15?nullptr:(void*)0x765,opaque);
 assert(original_calls==1);
 if(frontend_mode==3||frontend_mode==4||frontend_mode==5||frontend_mode==6||frontend_mode==10||frontend_mode==13||frontend_mode==14||frontend_mode==16||frontend_mode==17){assert(mp4_child_driving_rejected.load()&&quarantines==(frontend_mode==5?0u:1u));return 0;}
 if(frontend_mode==12){assert(mp4_child_driving_rejected.load()&&mp4_child_driving_scope.failed()&&quarantines==1);return 0;}
 assert(!mp4_child_driving_rejected.load()&&!quarantines);m.origin=false;m.held=true;
 if(frontend_mode==9)assert(mp4_child_driving_scope.finish_frame(0)==R::unsupported);
 else assert(mp4_child_driving_scope.finish_frame(0)==R::ok);
}
