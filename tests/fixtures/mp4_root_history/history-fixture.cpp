#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdlib>
#include <cassert>
#include "history.hpp"
namespace h=mp4_root_history;
int main(int argc,char**argv){assert(argc==2);const int mode=atoi(argv[1]);
 h::Path path{{0},1,true},other{{1},1,true};
 h::Track tracks[2]={{(void*)0x10,path},{(void*)0x20,other}};
 h::Runtime runtime[2]{};for(size_t i=0;i<2;++i){auto&r=runtime[i];r.key={tracks[i].object,(void*)(0x30+i),tracks[i].compiled,uint8_t(i)};r.start=1;r.end=10;r.bit=1;r.active[0]=r.active[1]=int32_t(i);r.delay=.1;r.tail=.2;r.started=1;}
 h::Callback callbacks[1]{};callbacks[0].track=tracks[0].object;callbacks[0].target=(void*)0x500;callbacks[0].motion=path;callbacks[0].weight_count=1;
 h::Weight weights[1]{{path,other,0}};h::Notification notifications[1]{{path,other,2.,0}};
 uint8_t data[8]={1,2,3,4,5,6,7,8};h::List lists[1]{{(void*)0x100,(void*)0x200,(void*)0x300,(void*)0x400,24,8,1,3,data}};
 h::Module modules[2]={{1,(void*)0x500,(void*)0x600,(void*)0x10,(void*)0x30,7,8},{2,(void*)0x501,(void*)0x601,(void*)0x20,(void*)0x31,7,9}};
 h::View view{};view.director=(void*)1;view.asset=(void*)2;view.epoch=7;view.graph=0x1000;view.root=0x2000;view.graph_version=2;view.root_version=4;view.active_bit=1;view.cache_count=2;view.cache_capacity=2;view.tracks=tracks;view.track_count=2;view.runtime=runtime;view.runtime_count=2;view.callbacks=callbacks;view.callback_count=1;view.weights=weights;view.weight_count=1;view.notifications=notifications;view.notification_count=1;view.lists=lists;view.list_count=1;view.modules=modules;view.module_count=2;
 if(mode==1)view.active_bit=2;if(mode==2)runtime[1].key=runtime[0].key;if(mode==3)runtime[1].active[0]=0;if(mode==4)runtime[1].active[0]=3;
 if(mode==5)runtime[0].bit=0;if(mode==6)runtime[0].key.path.length=65;if(mode==7)tracks[1].object=tracks[0].object;if(mode==8)runtime[1].key.track=(void*)0x777;
 if(mode==9)runtime[0].delay=__builtin_nan("");if(mode==10)runtime[0].started=2;if(mode==11)modules[0].image=0;if(mode==12)modules[1]=modules[0];
 if(mode==13)lists[0].count=4097;if(mode==14)lists[0].data=nullptr;if(mode==15)lists[0].stride=0;if(mode==16)view.track_count=513;if(mode==17)view.graph_version=3;
 h::Image image;const auto original_data=data[0];const bool captured=image.capture(view,mode==18?1:h::max_bytes);
 if(mode>=1&&mode<=18){assert(!captured&&!image.captured()&&!image.bytes());return 0;}
 assert(captured&&image.captured()&&image.bytes()>8&&image.matches(view));data[0]=0xee;assert(image.view().lists[0].data[0]==original_data);
 h::Track fresh_tracks[2]={tracks[1],tracks[0]};h::Runtime fresh_runtime[2]={runtime[1],runtime[0]};h::Module fresh_modules[2]={modules[1],modules[0]};
 h::View fresh=view;fresh.graph=0x3000;fresh.root=0x4000;fresh.graph_version=6;fresh.root_version=8;fresh.active_bit=0;fresh.tracks=fresh_tracks;fresh.runtime=fresh_runtime;fresh.modules=fresh_modules;for(auto&r:fresh_runtime)r.bit=0;
 if(mode==19)fresh_runtime[0].end=11;if(mode==20)fresh_runtime[0].active[1]=-1;if(mode==21)fresh_runtime[0].started=0;if(mode==22)fresh_runtime[0].key.path=path;
 if(mode==23)fresh_modules[0].image=10;if(mode==24)fresh_modules[0].target=(void*)0x888;if(mode==25)fresh.asset=(void*)3;if(mode==26)fresh.epoch=8;
 if(mode==27)callbacks[0].target=(void*)0x777;if(mode==28)weights[0].port=1;if(mode==29)notifications[0].previous=3.;if(mode==30)fresh_tracks[0].compiled=path;
 const bool expected=mode==0||mode>=31;assert(image.matches(fresh)==expected);
 if(mode==31){image.release();assert(!image.captured()&&!image.bytes()&&!image.matches(fresh));assert(image.capture(fresh));}
 if(mode==32){assert(!image.capture(fresh));assert(image.matches(fresh));}
}
