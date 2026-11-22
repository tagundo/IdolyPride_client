int main(int argc,char**argv){assert(argc==2);const int mode=atoi(argv[1]);m={};
 auto*c=new Mp4TimelineContext{};c->track_count=2;c->tracks[0]=reinterpret_cast<void*>(2);c->tracks[1]=reinterpret_cast<void*>(4);c->compiled[0]={20,2,0};c->compiled[1]={40,2,0};c->root_count=1;c->roots[0]=1;
 if(mode==1)m.thread=false;if(mode==2)m.current=false;if(mode==3)m.target=false;if(mode==4)m.build=false;if(mode==5)c->track_count=513;
 if(mode==6)c->compiled[1]={};if(mode==7)c->tracks[1]=c->tracks[0];if(mode==8)c->release_animation_programmes=+[](void*){};
 if(mode==9){c->track_count=129;for(size_t i=0;i<129;++i){c->tracks[i]=reinterpret_cast<void*>((i+1)*2);c->compiled[i]={i+1,2,0};}}
 if(mode==10)c->tracks[1]=reinterpret_cast<void*>(3);
 auto*h=mp4_animation_context_cache(*c);const bool pass=mode==0||mode==6||mode==10;
 assert(bool(h)==pass);if(pass){assert(h->count==(mode==0?2u:1u));const int previous=m.build_calls;assert(mp4_animation_context_cache(*c)==h&&m.build_calls==previous);}
 if(mode==11){assert(false);}if(!pass&&c->animation_programmes){m.current=true;m.target=true;m.build=true;assert(!mp4_animation_context_cache(*c));}
 m.thread=true;const int source_roots=1;const int saved=m.retains;delete c;assert(m.releases==saved+source_roots);
 if(saved){assert(!m.events.empty()&&m.events.back()==30);for(size_t i=0;i+1<m.events.size();++i)if(m.events[i]==10)assert(i+1<m.events.size());}
}
