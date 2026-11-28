constexpr size_t bytes=0xac00000;uint8_t*area=nullptr;pin::Entry entries[7]{};
void page(uintptr_t rva){const auto p=(image_base+rva)&~uintptr_t(4095);for(const auto&r:regions)if(r.begin==p)return;assert(!mprotect(reinterpret_cast<void*>(p),4096,PROT_READ|PROT_WRITE));regions.push_back({p,4096});}
void put(uintptr_t rva,const void*data,size_t n){page(rva);assert(mp4_mapped(image_base+rva,n,false));std::memcpy(reinterpret_cast<void*>(image_base+rva),data,n);}
template<class T>void put(uintptr_t rva,T data){put(rva,&data,sizeof data);}
uint32_t branch(uintptr_t from,uintptr_t to){const auto d=static_cast<intptr_t>(to)-static_cast<intptr_t>(from);assert(!(d&3)&&d>=-(1ll<<27)&&d<(1ll<<27));return 0x14000000u|(static_cast<uint32_t>(d/4)&0x3ffffffu);}
void original_slot(size_t i,uintptr_t p){switch(i){case 0:mp4_director_enqueue_original=reinterpret_cast<mp4_director_maintenance::EnqueueFn>(p);break;case 1:mp4_director_append_a_original=reinterpret_cast<mp4_director_maintenance::AppendFn>(p);break;case 2:mp4_director_append_b_original=reinterpret_cast<mp4_director_maintenance::AppendFn>(p);break;case 3:mp4_director_collect_original=reinterpret_cast<mp4_director_maintenance::CollectFn>(p);break;case 4:mp4_director_deferred_a_original=reinterpret_cast<mp4_director_maintenance::ManagerFn>(p);break;case 5:mp4_director_deferred_b_original=reinterpret_cast<mp4_director_maintenance::ManagerFn>(p);break;case 6:mp4_child_graph_create_original=reinterpret_cast<mp4_director_birth::CreateFn>(p);break;default:assert(false);}}
void setup(){
 if(!area){auto*p=mmap(nullptr,bytes,PROT_NONE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_NORESERVE,-1,0);assert(p!=MAP_FAILED);area=static_cast<uint8_t*>(p);image_base=mp4_native_base=reinterpret_cast<uintptr_t>(p);}
 main_thread=mp4_source_verified=factory_current=audio_current=true;mp4_native_clock_source_ready=true;mp4_child_native_published=false;
 mp4native7::watch=mp4native7::withdrawn=mp4native7::epoch=mp4native7::job=0;mp4native7::readers=mp4native7::next_watch=0;mp4native7::depth=0;mp4native7::overflow=mp4native7::host_configured=false;
 for(auto&c:calls)c=0;mp4_child_pending_host={};throw_original=false;captures_withdrawn=0;idoly_mp4_runtime::errors=0;idoly_mp4_runtime::job={31,idoly_mp4_runtime::Stage::running,true};
 for(size_t i=0;i<7;++i){const auto&p=mp4_child_native_source_pins[i];auto&e=entries[i];const uintptr_t relay=140577404u+i*8;
  e={"native7",p.rva,{},0x9788500+i*32,0xab8de00+i*8,relay,relay+4};std::memcpy(e.bytes,p.original,16);mp4_child_native_entries[i]=nullptr;
  put(e.rva,p.original,24);put(e.rva,branch(e.rva,e.relay_in));put(e.relay_in,branch(e.relay_in,e.gateway));put(e.relay_out,branch(e.relay_out,e.rva+4));
  const auto pages=static_cast<intptr_t>(e.slot>>12)-static_cast<intptr_t>(e.gateway>>12);uint32_t displaced=0;std::memcpy(&displaced,e.bytes,4);
  const uint32_t code[]={0x90000010u|((static_cast<uint32_t>(pages)&3)<<29)|(((static_cast<uint32_t>(pages)>>2)&0x7ffff)<<5),0x91000210u|static_cast<uint32_t>((e.slot&0xfff)<<10),0xc8dffe10u,0xb4000050u,0xd61f0200u,displaced,branch(e.gateway+24,e.relay_out)};
  put(e.gateway,code,sizeof code);put(e.slot,mp4_child_native_replacement(i));original_slot(i,image_base+e.gateway+20);
 }
 put(mp4_child_native_reset_pin.rva,mp4_child_native_reset_pin.prefix,16);
}
bool bind(){const pin::Entry*slots[7]{};for(size_t i=0;i<7;++i)slots[i]=&entries[i];return mp4_child_native_install_static(slots,7);}
mp4_director_maintenance::Originals originals(){return {mp4_director_enqueue_original,{mp4_director_append_a_original,mp4_director_append_b_original},mp4_director_collect_original,reinterpret_cast<mp4_director_maintenance::ResetFn>(image_base+mp4_child_native_reset_pin.rva),{mp4_director_deferred_a_original,mp4_director_deferred_b_original}};}
void live_originals(){mp4_director_enqueue_original=original_enqueue;mp4_director_append_a_original=original_append_a;mp4_director_append_b_original=original_append_b;mp4_director_collect_original=original_collect;mp4_director_deferred_a_original=original_da;mp4_director_deferred_b_original=original_db;}
void invoke(unsigned i){auto*a=reinterpret_cast<void*>(0x1234);auto*b=reinterpret_cast<void*>(0x5678);auto*g=reinterpret_cast<const mp4world::AnimationGraph*>(b);switch(i){case 0:mp4_director_enqueue_hook(a,19,g);break;case 1:mp4_director_append_a_hook(a,g);break;case 2:mp4_director_append_b_hook(a,g);break;case 3:mp4_director_collect_hook(a,b);break;case 4:mp4_director_deferred_a_hook(a);break;case 5:mp4_director_deferred_b_hook(a);break;default:assert(false);}}
int main(){unsigned scenarios=0;
 {setup();assert(bind()&&mp4_child_native_hooks_current()&&mp4_child_pending_bindings_current(originals())&&mp4_child_native_birth_bindings(mp4_child_graph_create_original,factory));++scenarios;}
 for(size_t i=0;i<7;++i)for(size_t k=0;k<8;++k){setup();assert(bind());const auto&e=entries[i];const uintptr_t locations[]={e.rva,e.rva+20,e.gateway,e.gateway+20,e.gateway+24,e.slot,e.relay_in,e.relay_out};put(locations[k],uint32_t(0));assert(!mp4_child_native_hooks_current());++scenarios;}
 {setup();entries[3].relay_in+=8;assert(!bind()&&!mp4_child_native_published);++scenarios;}
 {setup();entries[6].bytes[9]^=1;assert(!bind());++scenarios;}
 {setup();assert(bind());original_slot(2,0);assert(!mp4_child_native_hooks_current());++scenarios;}
 {setup();assert(bind());auto o=originals();o.append[1]=o.append[0];assert(!mp4_child_pending_bindings_current(o));++scenarios;}
 {setup();assert(bind());auto o=originals();put(mp4_child_native_reset_pin.rva,uint32_t(0));assert(!mp4_child_pending_bindings_current(o));++scenarios;}
 {setup();assert(bind());factory_current=false;assert(!mp4_child_native_birth_bindings(mp4_child_graph_create_original,factory));++scenarios;}
 {setup();assert(bind());mp4_source_verified=false;assert(!mp4_child_native_hooks_current());++scenarios;}
 {setup();assert(bind());mp4_native_clock_source_ready=false;assert(!mp4_child_native_hooks_current());++scenarios;}
 {setup();assert(bind());uint64_t token=0;assert(mp4native7::arm(12,31,&token)&&token);assert(mp4native7::quiet(12,31));{mp4native7::Reader reader;assert(mp4native7::quiet(12,31));assert(!mp4native7::disarm(token));}assert(mp4native7::disarm(token)&&!mp4native7::quiet(12,31));++scenarios;}
 {setup();assert(bind());uint64_t token=0;assert(mp4native7::arm(12,31,&token));std::thread t([]{main_thread=false;mp4native7::Reader reader;});t.join();assert(!mp4native7::quiet(12,31)&&!mp4_child_pending_bindings_current(originals()));assert(mp4native7::disarm(token));++scenarios;}
 for(unsigned i=0;i<6;++i)for(unsigned configured=0;configured<2;++configured){setup();live_originals();mp4native7::host_configured=configured;invoke(i);assert(calls[i]==1&&mp4_child_pending_host.entered[i]==configured&&seen_a==0x1234);if(i<4)assert(seen_b==0x5678);if(!i)assert(seen_op==19);assert(!mp4native7::readers&&!mp4native7::depth);++scenarios;}
 for(unsigned i=0;i<6;++i){setup();live_originals();mp4native7::host_configured=true;throw_original=true;bool threw=false;try{invoke(i);}catch(const std::runtime_error&){threw=true;}assert(threw&&calls[i]==1&&!mp4native7::readers&&!mp4native7::depth);++scenarios;}
 for(unsigned i=0;i<6;++i){setup();live_originals();mp4native7::host_configured=true;mp4native7::epoch=12;mp4native7::job=31;mp4native7::watch=1;std::thread t([i]{main_thread=false;invoke(i);});t.join();assert(calls[i]==1&&!mp4_child_pending_host.entered[i]&&!mp4native7::active()&&!mp4native7::readers);++scenarios;}
 for(unsigned i=0;i<6;++i){setup();live_originals();mp4native7::host_configured=true;mp4native7::epoch=12;mp4native7::job=31;mp4native7::watch=1;invoke(i);assert(calls[i]==1&&mp4_child_pending_host.entered[i]==1&&!mp4native7::active()&&!mp4native7::readers);++scenarios;}
 for(unsigned i=0;i<6;++i){setup();live_originals();mp4native7::host_configured=true;mp4_child_pending_host.j.on=true;mp4native7::epoch=12;mp4native7::job=31;mp4native7::watch=1;invoke(i);assert(calls[i]==1&&mp4_child_pending_host.entered[i]==1&&mp4native7::active()&&!mp4native7::readers);++scenarios;}
 {setup();assert(bind());mp4world::CodeBinding p{mp4_child_native_source_pins[0].rva,{}};std::memcpy(p.prefix,mp4_child_native_source_pins[0].original,16);assert(mp4_director_native_code_verified(p));p.prefix[8]^=1;assert(!mp4_director_native_code_verified(p));++scenarios;}
 printf("%u actual native7 certificate/frontend cases; ARM execution, loader and owned Host leaves modeled\n",scenarios);assert(!munmap(area,bytes));
}
