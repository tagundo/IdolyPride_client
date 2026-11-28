using namespace idoly_mp4_origin;

struct Managed{void*klass=nullptr;
void*monitor=nullptr;
void*native=nullptr;
};

struct Native{uintptr_t table=0;
int32_t id=0;
uint32_t flags=0;
};

struct Fixture{
 alignas(8) unsigned char pm[0x240]{};
Managed managed[6]{};
Native native[6]{};
ObjectRef refs[6]{};

 bool held=false,live=true,thread=true;
int locks=0,unlocks=0,paths=0,drops=0,lookups=0,reads=0,currents=0;

 int mode=0,which=-1;
Core*core=nullptr;
std::string filename="archive:/run-CAB/CAB-x.sharedAssets";

 void reset(int m){mode=m;
which=-1;
locks=unlocks=paths=drops=lookups=reads=currents=0;
held=false;
live=thread=true;

  uintptr_t vt=0x12345678;
void*map=this;
uint64_t count=32;
std::memcpy(pm,&vt,8);
std::memcpy(pm+0x58,&map,8);
std::memcpy(pm+0x218,&count,8);

  for(int i=0;
i<6;
++i){native[i].id=100+i;
managed[i].native=&native[i];
refs[i]={&managed[i],&native[i],100+i};
}
 }
 static Fixture*active;

 static bool main(void*c){auto&f=*static_cast<Fixture*>(c);

  if(f.held)std::abort();
return f.thread;
}
 static bool current(void*c){auto&f=*static_cast<Fixture*>(c);

  if(f.held)std::abort();
++f.currents;

  if(f.mode==36)throw std::runtime_error("observer");
return f.live;
}
 static bool read(void*c,uintptr_t p,void*d,size_t n){auto&f=*static_cast<Fixture*>(c);

  if(f.held)std::abort();
++f.reads;

  if(f.mode==17&&f.unlocks)throw std::runtime_error("observer_read");
std::memcpy(d,reinterpret_cast<void*>(p),n);

   return true;
}
 static void*manager(){auto&f=*active;

  if(f.mode==16&&f.unlocks)return nullptr;
return f.pm;
}
 static void lock(void*p,uint32_t flags){auto&f=*active;

  if(p!=f.pm||flags!=1||f.held)std::abort();
++f.locks;
f.held=true;
}
 static void unlock(void*p,uint32_t flags){auto&f=*active;

  if(p!=f.pm||flags!=1||!f.held)std::abort();
++f.unlocks;
f.held=false;

  if(f.mode==19)throw std::runtime_error("unlock");
}
 static bool lookup(void*map,int32_t id,FileLocal16*out){auto&f=*active;

  if(!f.held||map!=&f)std::abort();
++f.lookups;
int i=id-100;

  if(f.mode==6)return false;

  if(f.mode==22){Origin r{};

  if(f.core->query(f.refs,1,&r)||r.file!=-1)std::abort();
}
  out->file=f.mode==7?32:f.mode==35?-1:4+i;
out->local=f.mode==8?0:200+i;

   return true;
}
 static String40 path(void*p,int32_t file,bool locked){auto&f=*active;

  if(p!=f.pm||!locked||!f.held)std::abort();
++f.paths;

  if(f.mode==9||(f.mode==10&&f.paths==4))throw std::runtime_error("original_getter");

  if(f.mode==14)f.live=false;

  if(f.mode==15)f.managed[0].native=nullptr;

  String40 v{};
std::string s=f.mode==1?"CABshort":f.filename;

  if(f.mode==12||f.mode==34)s.assign(MaxPath,'x');

  if(f.mode==13)s[3]=0;

  if(s.size()<=24){std::memcpy(v.bytes,s.data(),s.size());
v.bytes[24]=static_cast<unsigned char>(24-s.size());
v.bytes[32]=1;
}
  else{char*q=static_cast<char*>(std::malloc(s.size()));

  if(!q)std::abort();
std::memcpy(q,s.data(),s.size());
uint64_t n=s.size();
std::memcpy(v.bytes,&q,8);
std::memcpy(v.bytes+16,&n,8);
v.bytes[32]=0;
}
  if(f.mode==11||f.mode==33){if(v.bytes[32]==0){char*q=nullptr;
std::memcpy(&q,v.bytes,8);
std::free(q);
}v.bytes[32]=2;
}
  if(f.mode==39){if(v.bytes[32]==0){char*q=nullptr;
std::memcpy(&q,v.bytes,8);
std::free(q);
}v.bytes[32]=1;
v.bytes[24]=25;
}
  (void)file;
return v;

 }
 static void drop(String40*p){auto&f=*active;

  if(!f.held)std::abort();
++f.drops;

  if(p->bytes[32]==0){char*q=nullptr;
std::memcpy(&q,p->bytes,8);
std::free(q);
}if(f.mode==18)throw std::runtime_error("drop");
}
 Api api(){return{this,main,current,read};
}Leaves leaves(){return{manager,lock,unlock,lookup,path,drop};
}
};
Fixture*Fixture::active=nullptr;

void require(bool x,const char*m){if(!x){std::fprintf(stderr,"FAIL %s\n",m);
std::abort();
}}
Origin origin(int32_t file,int64_t local,const char*path){Origin r{};
r.file=file;
r.local=local;
r.path_size=std::strlen(path);
std::memcpy(r.path,path,r.path_size+1);
return r;
}
int main(){Fixture f;
Fixture::active=&f;
int cases=0;

 for(int mode:{0,1,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,22,30,31,34,35,36,37,39,40}){
  f.reset(mode);
Core core(f.api(),f.leaves(),{0x12345678,0x58,0x218});
f.core=&core;

  if(mode==3)f.live=false;

  if(mode==4)f.managed[0].native=nullptr;

  if(mode==5)f.native[0].id=999;

  if(mode==30)std::memset(f.pm,0,8);

  if(mode==31)std::memset(f.pm+0x58,0,8);

  if(mode==40){uint64_t n=0x80000000;
std::memcpy(f.pm+0x218,&n,8);
}
  Origin out[6]{};
bool ok=core.query(f.refs,6,out);
bool expected=mode==0||mode==1||mode==22||mode==37;

  require(ok==expected,"query verdict");
require(!f.held&&f.locks==f.unlocks,"mutex balanced");
require(f.drops==f.paths-((mode==9||mode==10)?1:0),"String40 exact destruction");

  if(!ok)for(const auto&r:out)require(r.file==-1&&r.path_size==0,"no partial publication");

  if(mode==37){f.mode=9;
require(!core.query(f.refs,6,out),"getter throw");
f.mode=0;
require(core.query(f.refs,6,out),"no sticky busy after throw");
}
  ++cases;

 }
 Origin v[6]={origin(4,2,"archive:/exact/CAB-x.sharedAssets"),origin(5,657,"archive:/exact/CAB-x"),origin(5,2,"archive:/exact/CAB-x"),origin(5,1835,"archive:/exact/CAB-x"),origin(4,75,"archive:/exact/CAB-x.sharedAssets"),origin(4,4231,"archive:/exact/CAB-x.sharedAssets")};

 require(role_matches(v,common_roles[1]),"actual Bundle fileIndex role join");
++cases;

 auto old=v[5];
v[5].file=9;
require(!role_matches(v,common_roles[1]),"same CAB name foreign file rejected");
v[5]=old;
++cases;

 old=v[1];
v[1]=origin(5,657,"archive:/other/CAB-x");
require(!role_matches(v,common_roles[1]),"same CAB suffix foreign archive rejected");
v[1]=old;
++cases;

 v[1].local=99;
require(!role_matches(v,common_roles[1]),"wrong root rejected");
v[1].local=657;
++cases;

 v[0].local=1;
require(!role_matches(v,common_roles[1]),"wrong Bundle local rejected");
v[0].local=2;
++cases;

 v[3].local=99;
require(!role_matches(v,common_roles[1]),"wrong Renderer rejected");
++cases;

 std::printf("PASS %d source-origin core/role cases\n",cases);

}
