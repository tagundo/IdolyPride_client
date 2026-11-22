#define main prior_registry_main
#include "check-proflare-registry.cpp"
#undef main
#include <cassert>
#include <string>
int main(int argc,char**argv){
 assert(argc==2);std::string mode=argv[1];H h;p::Scope s;auto api=h.api();
 assert(s.capture(api,&h,7,h.flares,2)==p::Result::ok);uint64_t token=0,birth=0;void*camera=&h.b;void*new_data=&h.other;
 if(mode=="abandon"||mode=="abandon_wait"||mode=="abandon_appended"||mode=="abandon_prefix"||mode=="abandon_token"||mode=="abandon_registry"||mode=="abandon_version"||mode=="abandon_wrong_operation"){
 assert(s.begin_data(p::DataOperation::update,camera,nullptr,&token)==p::Result::ok);
 if(mode=="abandon_wait"){h.data_completed=false;assert(s.abandon_data(token,new_data)==p::Result::unsupported&&!s.current());h.data_completed=true;}
 if(mode=="abandon_appended")h.image.data.version+=2;
 if(mode=="abandon_prefix")h.data[0]=&h.a;
 if(mode=="abandon_registry")++h.image.list.version;
 if(mode=="abandon_version")++h.image.data.version;
 bool good=mode=="abandon"||mode=="abandon_wait"||mode=="abandon_appended";
 if(mode=="abandon_wrong_operation"){assert(s.end(token,true)==p::Result::invalid);assert(s.abandon_data(token,new_data)==p::Result::ok);}
 else {assert((s.abandon_data(token+(mode=="abandon_token"?1:0),new_data)==p::Result::ok)==good);if(good)assert(s.current()&&s.restore()==p::Result::ok&&h.image.data.version==2);}
 }
 else if(mode=="no_callback"){s.release();api.data_origin=nullptr;assert(s.capture(api,&h,7,h.flares,2)==p::Result::ok);assert(s.begin_data(p::DataOperation::update,camera,nullptr,&token)==p::Result::unsupported);}
 else if(mode=="no_origin"){h.data_authority=false;assert(s.begin_data(p::DataOperation::update,camera,nullptr,&token)==p::Result::unsupported);}
 else if(mode=="unknown_retire"){assert(s.begin_data(p::DataOperation::retire,camera,h.data[0],&token)==p::Result::unsupported);}
 else if(mode=="existing"||mode=="null_result"||mode=="wrong_result"){
 assert(s.begin_data(p::DataOperation::update,camera,nullptr,&token)==p::Result::ok);void*result=mode=="existing"?h.data[0]:mode=="null_result"?nullptr:new_data;assert((s.end_data(token,result,true)==p::Result::ok)==(mode!="wrong_result"));if(mode!="wrong_result")assert(s.restore()==p::Result::ok);
 }else{
 if(mode=="grow")h.image.data.count=2,h.data[1]=&h.a;
 if(mode=="grow"){s.release();assert(s.capture(api,&h,7,h.flares,2)==p::Result::ok);}
 assert(s.begin_data(p::DataOperation::update,camera,nullptr,&token)==p::Result::ok);assert(!s.current());
 if(mode=="wrong_token"){assert(s.end_data(token+1,new_data,true)==p::Result::invalid);assert(!s.current());}
 else {
 void*grown[4]{h.data[0],h.data[1],nullptr,nullptr};
 if(mode=="grow"||mode=="wrong_array"){h.image.data.array=grown;h.image.data.rows=grown;h.image.data.capacity=4;}
 h.image.data.rows[h.image.data.count++]=new_data;++h.image.data.version;
 if(mode=="prefix")h.image.data.rows[0]=&h.a;
 if(mode=="tail"){h.image.data.capacity=3;h.image.data.rows=grown;h.image.data.array=grown;grown[1]=new_data;grown[2]=&h.a;}
 if(mode=="version")++h.image.data.version;
 if(mode=="list_identity")h.image.data.object=&h;
 if(mode=="registry_mutation")++h.image.list.version;
 if(mode=="uncompleted")h.data_completed=false;
 if(mode=="lost_origin")h.data_authority=false;
 if(mode=="lost_source")h.valid=false;
 bool accepted=mode=="normal"||mode=="grow"||mode=="retire"||mode=="retire_reorder"||mode=="retire_version"||mode=="wrong_camera"||mode=="restored_birth";
 assert((s.end_data(token,new_data,mode!="exception")==p::Result::ok)==accepted);
 if(accepted){
 assert(s.data_birth(new_data,camera,&birth)&&birth==token);assert(!s.data_birth(new_data,&h.a,&birth));assert(s.restore()==p::Result::unsupported&&h.writes==0);
 if(mode=="wrong_camera"){assert(s.begin_data(p::DataOperation::retire,&h.a,new_data,&token)==p::Result::unsupported);}
 else {
 assert(s.begin_data(p::DataOperation::retire,camera,new_data,&token)==p::Result::ok);
 h.image.data.rows[--h.image.data.count]=nullptr;++h.image.data.version;
 if(mode=="retire_reorder")h.image.data.rows[0]=&h.a;
 if(mode=="retire_version")++h.image.data.version;
 const bool good=mode!="retire_reorder"&&mode!="retire_version";
 assert((s.end_data(token,new_data,true)==p::Result::ok)==good);
 if(good){assert(!s.data_birth(new_data,camera,&birth));assert(s.restore()==p::Result::ok);assert(h.image.data.count==(mode=="grow"?2u:1u)&&h.image.data.version==2);assert(h.image.data.rows[0]==&h.image);if(mode=="grow")assert(h.image.data.array==grown&&h.image.data.capacity==4&&h.image.data.rows[1]==&h.a);assert(!s.data_birth(new_data,camera,&birth));}
 }
 }
 }
 }
 s.release();assert(h.roots.empty());
}
