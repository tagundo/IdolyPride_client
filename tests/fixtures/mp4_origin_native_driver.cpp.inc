using namespace idoly_mp4_origin;

struct SourceFixture{const Profile*p=nullptr;
uintptr_t base=0x100000;
int mode=0,calls=0;

 static bool main(void*v){return static_cast<SourceFixture*>(v)->mode!=3;
}
 static bool current(void*v){auto&f=*static_cast<SourceFixture*>(v);
if(f.mode==4)throw std::runtime_error("withdraw");
return f.mode!=2;
}
 static bool read(void*v,uintptr_t at,void*out,size_t n){auto&f=*static_cast<SourceFixture*>(v);
++f.calls;
if(f.mode==5)return false;

  for(const auto&pin:f.p->pins)if(at>=f.base+pin.rva&&at+n<=f.base+pin.rva+pin.bytes){std::memcpy(out,pin.body+at-(f.base+pin.rva),n);
if(f.mode==1)static_cast<unsigned char*>(out)[0]^=1;
return true;
}
return false;
}
};

int main(){int cases=0;
for(const Profile*p:{&android_profile,&ios_profile})for(int mode=0;
mode<7;
++mode){SourceFixture f{p,0x100000,mode};
NativeHost h;
Api api{&f,SourceFixture::main,SourceFixture::current,SourceFixture::read};
uintptr_t base=mode==6?~uintptr_t(0)-4:f.base;

 bool ok=h.bind(base,*p,api);
assert(ok==(mode==0));
if(mode!=0){Origin out[1]{};
assert(!h.query(nullptr,1,out)&&out[0].file==-1);
}++cases;
}
std::printf("PASS %d native source-binding cases\n",cases);
}
