uintptr_t mp4_native_base=0x100000;
int origin_mode=0,origin_queries=0,origin_role=0;
namespace idoly_mp4_origin{
class NativeHost{
 Api api_{};
public:
 bool bind(uintptr_t,const Profile&,const Api&a){api_=a;return origin_mode!=7&&a.current(a.context);}
 bool query(const ObjectRef*refs,size_t n,Origin*out){
  ++origin_queries;if(origin_mode==6)return false;if(origin_mode==12)throw 9;
  assert(n==6);const auto&r=common_roles[origin_role];const int64_t ids[]={2,r.root,r.go,r.renderer,r.material,r.shader};
  for(size_t i=0;i<6;++i){assert(refs[i].managed&&refs[i].native&&refs[i].id);out[i].object=refs[i];out[i].local=ids[i];out[i].file=(i==0||i>=4)?4:5;
   const char*p=(i==0||i>=4)?"archive:/real/CAB-x.sharedAssets":"archive:/real/CAB-x";out[i].path_size=std::strlen(p);std::memcpy(out[i].path,p,out[i].path_size+1);}
  if(origin_mode==1)out[5].file=19;
  if(origin_mode==2){const char*p="archive:/other/CAB-x";out[1].path_size=std::strlen(p);std::memcpy(out[1].path,p,out[1].path_size+1);}
  if(origin_mode==3)out[0].local=1;
  if(origin_mode==4)++mp4_scene_shader_foreign;
  if(origin_mode==5){int32_t changed=777;put(refs[5].managed,8,changed);mp4_scene_shader_foreign_thread=true;}
  return api_.current(api_.context);
 }
};}
