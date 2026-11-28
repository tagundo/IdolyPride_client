bool mp4_animation_factory_configure(){return false;} // explicit refused lazy source/CAPI leaf in this fixture
using H=Mp4AnimationFactoryHandle;using V=Mp4AnimationFactoryVec3;
static int calls=0;static bool throwing=false;
void check(H g,void*go,Method*m){assert(g.handle==0x1234&&g.version==22&&go==reinterpret_cast<void*>(0x2000)&&m==reinterpret_cast<Method*>(0xdead));++calls;if(throwing)throw 71;}
H root_original(void*s,H g,void*go,void*t,Method*m){assert(s==reinterpret_cast<void*>(0x1000)&&t==reinterpret_cast<void*>(0x3000));check(g,go,m);return {0x5566,77,0};}
H clips_original(void*s,H g,void*tr,void*go,void*t,int32_t mode,Method*m){assert(s==reinterpret_cast<void*>(0x1000)&&tr==reinterpret_cast<void*>(0x1100)&&t==reinterpret_cast<void*>(0x3000)&&mode==1);check(g,go,m);return {0x5566,77,0};}
H infinite_original(void*s,H g,void*go,void*t,int32_t mode,Method*m){assert(s==reinterpret_cast<void*>(0x1000)&&t==reinterpret_cast<void*>(0x3000)&&mode==1);check(g,go,m);return {0x5566,77,0};}
H clip_original(H g,void*c,V p,V e,bool remove,int32_t mode,bool foot,int32_t loop,Method*m){assert(c==reinterpret_cast<void*>(0x4000)&&p.x==1.25f&&p.y==-2.5f&&p.z==3.75f&&e.x==-4.25f&&e.y==5.5f&&e.z==-6.75f&&remove&&mode==1&&!foot&&loop==2);check(g,reinterpret_cast<void*>(0x2000),m);return {0x5566,77,0};}
int main(int argc,char**argv){assert(argc==2);std::string name=argv[1];throwing=name.find("throw")!=std::string::npos;
 mp4_animation_root_factory_original=root_original;mp4_animation_clips_factory_original=clips_original;mp4_animation_infinite_factory_original=infinite_original;mp4_animation_clip_factory_original=clip_original;
 void*s=reinterpret_cast<void*>(0x1000),*go=reinterpret_cast<void*>(0x2000),*tree=reinterpret_cast<void*>(0x3000);Method*m=reinterpret_cast<Method*>(0xdead);H g{0x1234,22,0},r{};bool threw=false;
 try{if(name.find("root")!=std::string::npos)r=mp4_animation_root_factory_hook(s,g,go,tree,m);else if(name.find("clips")!=std::string::npos)r=mp4_animation_clips_factory_hook(s,g,reinterpret_cast<void*>(0x1100),go,tree,1,m);else if(name.find("infinite")!=std::string::npos)r=mp4_animation_infinite_factory_hook(s,g,go,tree,1,m);else r=mp4_animation_clip_factory_hook(g,reinterpret_cast<void*>(0x4000),{1.25f,-2.5f,3.75f},{-4.25f,5.5f,-6.75f},true,1,false,2,m);}catch(int v){assert(v==71);threw=true;}
 assert(calls==1&&threw==throwing);if(!throwing)assert(r.handle==0x5566&&r.version==77);return 0;
}
