int main(int argc,char**argv){assert(argc==2);const int m=atoi(argv[1]);select(0x1000,7);mp4_director_birth::SourcePins pins;auto call=selector();
 if(m==2)++call.source_asset;
 if(m==3)model.bad_primary=true;
 if(m==4)model.bad_child_prefix=true;
 if(m==5)model.bad_mi=true;
 if(m==6)model.fail_retain=2;
 if(m==7)model.list_bad=true;
 if(m==10)model.held=false;
 if(m==11)mp4_birth_catalogue.sequence=~uint64_t(0);
 if(m==12)model.same_go=true;
 const bool good=m==0||m==1||m==8||m==9||m==12||m==13||m==14;assert(mp4_birth_catalogue_capture(call,pins)==good);
 if(!good){mp4_birth_catalogue_clear();assert(model.roots.empty());return 0;}
 const auto sequence=mp4_birth_catalogue.sequence;assert(sequence==1&&mp4_birth_catalogue.count==2&&!model.roots.empty());
 if(m==8){++model.version;assert(!mp4_birth_catalogue_membership(call));}
 select(0x3000,m==14?7:9);auto next=selector();assert(!mp4_birth_catalogue_capture(next,pins));
 mp4_birth_catalogue_clear();assert(!mp4_birth_catalogue.captured&&!mp4_birth_catalogue.count&&mp4_birth_catalogue.sequence==sequence&&model.roots.empty());
 if(m==13){mp4_birth_catalogue_clear();assert(model.roots.empty()&&mp4_birth_catalogue.sequence==sequence);}
 assert(mp4_birth_catalogue_capture(next,pins)&&mp4_birth_catalogue.sequence==sequence+1&&mp4_birth_catalogue_membership(next));
 for(size_t i=0;i<mp4_birth_catalogue.count;++i)assert(mp4_birth_catalogue.tuples[i].capture==sequence+1&&mp4_birth_catalogue.tuples[i].director>=0x3000);
 mp4_birth_catalogue_clear();assert(model.roots.empty());
}
