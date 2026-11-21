#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cmath>
#include <cassert>
#include <string>
#include "mp4-animation-output-witness.hpp.inc"
using namespace idoly_mp4_animation_output;
struct F{bool source=true,thread=true;View view{};int reads=0,change_at=0;};static F*f;
bool current(void*,uint64_t e){return f->source&&e==11;}bool thread(){return f->thread;}bool read(void*,const Owner&,View&v){++f->reads;if(f->change_at==f->reads)f->view.weight=0.25f;v=f->view;return true;}
int main(int argc,char**argv){assert(argc==2);F fixture;f=&fixture;Owner owner{reinterpret_cast<void*>(1),reinterpret_cast<void*>(2),{3,2,0},{4,2,0}};f->view={{3,2,0},{4,2,0},{5,2,0},6,7,8,9,1,0,1,0,0,{}};Witness w;Api api{current,thread,read};std::string c=argv[1];
 if(c=="racy_capture"){f->change_at=2;assert(!w.capture(api,f,11,owner));return 0;}
 if(c=="bad_capture"){f->view.stream=3;assert(!w.capture(api,f,11,owner));return 0;}
 assert(w.capture(api,f,11,owner));assert(w.current());bool expected=false;
 if(c=="stable")expected=true;else if(c=="source")f->source=false;else if(c=="thread")f->thread=false;else if(c=="weight")f->view.weight=0.5f;else if(c=="port")f->view.port=1;else if(c=="stream")f->view.stream=0;else if(c=="sort")f->view.sorting=2;else if(c=="reference")f->view.reference=3;else if(c=="userdata")f->view.userdata[1]=8;else if(c=="target")f->view.native_target=99;else if(c=="native_source")f->view.native_source=99;else if(c=="native_graph")f->view.native_graph=99;else if(c=="native_output")f->view.native_output=99;else if(c=="graph_version")++f->view.graph.version;else if(c=="output_version")++f->view.output.version;else if(c=="source_version")++f->view.source.version;else if(c=="nan")f->view.weight=std::nanf("");else if(c=="release")w.release();else assert(false);
 assert(w.current()==expected);
}
