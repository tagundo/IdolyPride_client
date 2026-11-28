int main(int argc,char**argv){assert(argc==2);initialize();int mode=atoi(argv[1]);auto&m=model;auto&c=m.context;
 if(mode==1)m.current=false;if(mode==2)m.keep=false;if(mode==3)m.mapped=false;if(mode==4)m.lookup=false;
 if(mode==5)m.fields.erase({&m.root_type,"m_PlayableCache"});if(mode==6)m.dictionary.klass=&m.root_type;
 if(mode==7)m.fields.erase({&m.dictionary_type,"_count"});if(mode==8)set(&m.dictionary,32,uint32_t(-1));
 if(mode==9)set(&m.dictionary,44,3);if(mode==10)set(&m.dictionary,32,4097);if(mode==11)set(&m.dictionary,32,1);
 if(mode==12)set(&m.dictionary,24,0);if(mode==13)m.entries.length=4097;if(mode==14)m.entry_type.stride=24;
 if(mode==15)m.entry_type.value=false;if(mode==16)m.entries.klass=&m.bucket_array;if(mode==17)set(&m.dictionary,40,2);
 if(mode==18)m.fields[{&m.entry_type,"key"}].offset=32;if(mode==19)m.fields[{&m.entry_type,"value"}].type=&m.int_type;
 if(mode==20)m.fields[{&m.entry_type,"hashCode"}].type=&m.plain;if(mode==21)entry(1,1,-1,&m.track[0],c.compiled[1]);
 if(mode==22)entry(1,1,-1,&m.track[2],c.compiled[1]);if(mode==23)entry(1,1,-1,&m.track[1],c.compiled[0]);
 if(mode==24)entry(1,-1,-1,&m.track[1],c.compiled[1]);if(mode==25)bucket(0,0);if(mode==26)bucket(0,-1);if(mode==27)bucket(0,3);
 if(mode==28)bucket(2,1);if(mode==29)entry(0,0,0,&m.track[0],c.compiled[0]);if(mode==30)entry(0,0,1,&m.track[0],c.compiled[0]);
 if(mode==31)entry(2,0,-1,&m.track[2],{});if(mode==32)c.track_count=513;
 if(mode==33){m.entry_type.element=nullptr;m.bucket_array.element=&m.plain;}
 if(mode==34){set(&m.dictionary,32,3);set(&m.dictionary,44,1);set(&m.dictionary,40,2);entry(2,-1,-1,nullptr,{});}
 if(mode==35){set(&m.dictionary,32,3);set(&m.dictionary,44,1);set(&m.dictionary,40,2);entry(2,-1,2,nullptr,{});}
 if(mode==36){set(&m.dictionary,32,3);set(&m.dictionary,44,1);set(&m.dictionary,40,uint32_t(-1));entry(2,-1,-1,nullptr,{});}
 if(mode==37){c.track_count=0;set(&m.dictionary,16,0);set(&m.dictionary,24,0);set(&m.dictionary,32,0);}
 mp4_root_history::View view{};mp4_root_history::List lists[2]{};size_t used=99;
 bool result=mp4_root_history_cache(c,view,lists,&used);bool expected=mode==0||mode==34||mode==37;assert(result==expected);assert(used==(expected&&mode!=37?2:0));
 if(expected&&mode!=37){assert(view.cache_count==(mode==34?3:2)&&view.cache_free==(mode==34?1:0)&&view.cache_capacity==3);assert(lists[0].array==&m.entries&&lists[1].array==&m.buckets&&c.kept>=3);}
}
