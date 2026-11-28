int main(int argc,char**argv){assert(argc==2);initialize();model.mode=atoi(argv[1]);int mode=model.mode;auto&m=model;auto&c=m.context;
 if(mode==1)m.current=false;if(mode==2)m.lists=false;if(mode==11)m.path=false;if(mode==12)m.cache=false;
 if(mode==13)set(&m.root,40,int32_t(2));if(mode==14)set(&m.runtime,16,int32_t(0));if(mode==15)set(&m.runtime,80,uint8_t(2));if(mode==16)set(&m.runtime,64,__builtin_nan(""));
 if(mode==17){void*other=&m.clip;std::memcpy(m.scratch,&other,8);}if(mode==18)c.lists[0].stride=16;if(mode==19)c.lists[2].count=0;if(mode==20)c.clip_tracks[0]=nullptr;
 if(mode==21)c.lists[4].stride=32;if(mode==22)c.scripts[3]=nullptr;if(mode==23)set(&m.notification,32,uint8_t(2));if(mode==24)set(&m.notification,24,__builtin_nan(""));
 if(mode==25)set(m.output_native,0x40,__builtin_nanf(""));if(mode==26)set(m.output_native,0x44,int32_t(-1));if(mode==27)c.compiled[0]={204,2,0};
 mp4_root_history::Module module{1,(void*)0x500,&m.target,&m.track,&m.clip,7,9};Mp4RootHistoryRead read;
 const bool good=mode==0||mode==22||mode==28;const bool captured=mp4_root_history_read(c,read,&module,1);assert(captured==good);
 if(good){auto&v=read.view;assert(v.runtime_count==1&&v.runtime[0].key.track==&m.track&&v.runtime[0].active[0]==0&&v.callback_count==1&&v.callbacks[0].track==&m.track&&v.output_count==1&&v.outputs[0].track==&m.track);
  assert(v.notification_count==(mode==22?0:1));mp4_root_history::Image saved;assert(saved.capture(v));m.entry[0]=44;assert(saved.view().lists[0].data[0]==1);}
}
