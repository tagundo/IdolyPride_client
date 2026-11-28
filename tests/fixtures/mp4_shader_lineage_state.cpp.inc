using namespace idoly_mp4_shader_lineage;
struct Obj{Identity identity{};Kind kind=Kind::shader;bool alive=true;};
Obj request{{10,0},Kind::request},bundle{{20,21},Kind::bundle},a{{30,31},Kind::shader},b{{40,41},Kind::shader},foreign{{50,51},Kind::shader};
std::map<uint32_t,void*>roots;uint32_t next_root=1;bool owner=true,bad_array=false,duplicate=false,replace=false,root_fail=false;
int actual_array;bool publishing_array=false,no_array=false,throw_array=false,reenter=false;Registry*active_registry=nullptr;
bool array_held(){for(const auto&entry:roots)if(entry.second==&actual_array)return true;return false;}
bool thread(){return owner;}
bool identity(void*object,Kind kind,Identity&value){if(publishing_array&&(object==&a||object==&b))assert(array_held());auto*o=static_cast<Obj*>(object);if(!o||o->kind!=kind||!o->alive)return false;value=o->identity;return true;}
uint32_t retain(void*object){if(publishing_array&&(object==&a||object==&b))assert(array_held());if(root_fail)return 0;uint32_t h=next_root++;roots[h]=object;return h;}
void*target(uint32_t h){auto at=roots.find(h);return at==roots.end()?nullptr:at->second;}
void release(uint32_t h){if(target(h)==&actual_array)publishing_array=false;assert(roots.erase(h)==1);}
bool all(void*object,void**out,size_t maximum,size_t&count,uint32_t&array_root){array_root=no_array?0:retain(&actual_array);publishing_array=array_root!=0;assert(object==&bundle&&maximum>=2);if(throw_array)throw 7;if(reenter)assert(active_registry&&!active_registry->sync_result(&bundle,1,1));out[0]=&a;out[1]=duplicate?&a:&b;count=bad_array?1:2;if(replace)++bundle.identity.instance;return true;}
Digest hash(const std::string&s){Sha256 sha;assert(sha.append(s.data(),s.size()));return sha.finish();}
Digest fromhex(const char*s){Digest v{};for(size_t i=0;i<32;++i){auto n=[](char c){return unsigned(c<='9'?c-'0':c-'a'+10);};v.bytes[i]=uint8_t(n(s[i*2])*16+n(s[i*2+1]));}return v;}
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];
 if(mode=="sha_empty"){assert(equal(hash(""),fromhex("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")));return 0;}
 if(mode=="sha_abc"){assert(equal(hash("abc"),fromhex("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")));return 0;}
 if(mode=="sha_long"){assert(equal(hash(std::string(1000000,'a')),fromhex("cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0")));return 0;}
 if(mode=="sha_chunked"){Sha256 h;assert(h.append("a",1)&&h.append("bc",2));assert(equal(h.finish(),hash("abc")));return 0;}
 KnownBundle known[]={{3,2,hash("abc")}};Registry registry;active_registry=&registry;assert(registry.configure({thread,identity,retain,target,release,all},known,1));
 assert(registry.identify(3,hash("abc"))==1&&registry.identify(2,hash("abc"))==0&&registry.identify(3,hash("abd"))==0&&!registry.admits(&a));
 if(mode=="unknown_input"){assert(!registry.sync_result(&bundle,0,0));}
 else if(mode=="input_changed"){assert(!registry.sync_result(&bundle,1,0));}
 else if(mode=="no_actual_request"){assert(!registry.bundle_result(&request,&bundle));}
 else if(mode=="wrong_request_type"){assert(!registry.async_result(&a,1,1));}
 else if(mode=="wrong_bundle_type"){assert(!registry.sync_result(&a,1,1));}
 else if(mode=="no_array_root"){no_array=true;assert(!registry.sync_result(&bundle,1,1));}
 else if(mode=="array_throw"){throw_array=true;try{registry.sync_result(&bundle,1,1);assert(false);}catch(int value){assert(value==7);}assert(roots.empty());}
 else if(mode=="wrong_count"){bad_array=true;assert(!registry.sync_result(&bundle,1,1));}
 else if(mode=="duplicate_shader"){duplicate=true;assert(!registry.sync_result(&bundle,1,1));}
 else if(mode=="wrong_shader_type"){b.kind=Kind::bundle;assert(!registry.sync_result(&bundle,1,1));}
 else if(mode=="bundle_replaced_during"){replace=true;assert(!registry.sync_result(&bundle,1,1));}
 else if(mode=="request_replaced"){assert(registry.async_result(&request,1,1));++request.identity.native;assert(!registry.bundle_result(&request,&bundle));}
 else if(mode=="root_failure"){root_fail=true;assert(!registry.sync_result(&bundle,1,1));}
 else if(mode=="offthread"){owner=false;assert(!registry.sync_result(&bundle,1,1)&&!registry.async_result(&request,1,1));owner=true;}
 else {
  if(mode=="reentrant")reenter=true;
  if(mode=="async"){assert(registry.async_result(&request,1,1));assert(!registry.bundle_result(&request,nullptr));assert(registry.bundle_result(&request,&bundle));}
  else assert(registry.sync_result(&bundle,1,1));
  assert(registry.admits(&a)&&registry.admits(&b)&&!registry.admits(&foreign));
  if(mode=="shader_native_replaced"){++a.identity.native;assert(!registry.admits(&a));}
  else if(mode=="shader_id_replaced"){++a.identity.instance;assert(!registry.admits(&a));}
  else if(mode=="shader_destroyed"){a.alive=false;assert(!registry.admits(&a));}
  else if(mode=="bundle_unload_keep_objects"){bundle.alive=false;assert(registry.admits(&a));}
  else if(mode=="poison"){registry.poison();assert(!registry.admits(&a));}
  else if(mode=="repeat"){assert(registry.sync_result(&bundle,1,1));}
  else if(mode=="offthread_admission"){owner=false;assert(!registry.admits(&a));owner=true;}
  else assert(mode=="sync"||mode=="async"||mode=="reentrant");
 }
 registry.clear();assert(roots.empty());
}
