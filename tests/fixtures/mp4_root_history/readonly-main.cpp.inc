int main(int argc,char**argv){assert(argc==2);model.mode=atoi(argv[1]);const int mode=model.mode;
 for(size_t i=0;i<2;++i){auto&s=model.live[i];s.owner={0x100+i,0x200+i,0x300+i,0x400,0x500,7,11};s.root_asset=0x777;s.graph={0x1000+i*2,2,0};s.root={0x2000+i*2,2,0};s.time=12.5+i;s.root_speed=i?-.5:1;s.mode=1;s.state=1;mp4_birth_catalogue.tuples[i]=s.owner;auto&c=model.contexts[i];c.director=(void*)s.owner.director;c.asset=(void*)s.owner.asset;c.identity={0x3000+i*2,s.graph.handle,2};c.root={s.root.handle,2,0};mp4_source_director_plans.roots[i].context=&c;mp4_source_director_plans.roots[i].construction.source.ticket.serial=31+i;}
 model.role={{model.contexts[0].director,model.contexts[0].asset,model.contexts[1].director},(void*)0x800,{0x1000,2,0},{0x1200,2,0},{0x1400,2,0},41,43};
 if(mode==1)model.thread=false;if(mode==2)model.window=false;if(mode==3)model.bindings=false;if(mode==4)model.plan=false;if(mode==5)model.native=false;if(mode==6)model.publication=false;if(mode==7)model.node=false;if(mode==8)model.dependencies=false;if(mode==9)model.catalogue=false;
 if(mode==10)model.live[1].time=__builtin_nan("");if(mode==11)model.live[1].root_speed=__builtin_nan("");if(mode==12)model.live[1].mode=4;if(mode==13)model.live[1].state=2;if(mode==14)mp4_source_director_plans.roots[1].construction.source.ticket.serial=0;
 uint64_t receipt=99;const auto result=mp4_child_readonly_capture(&receipt);const bool good=mode==0||mode>=16;
 assert((result==mp4child::Result::ok)==good);assert(!model.writes);if(!good){assert(!receipt&&!mp4_child_readonly_source.ready);model.thread=true;assert(mp4_child_readonly_release());return 0;}
 assert(receipt&&mp4_child_readonly_source.count==2&&mp4_child_readonly_source.role_count==1&&mp4_child_readonly_current());const auto first=receipt;assert(mp4_child_readonly_capture(&receipt)==mp4child::Result::ok&&receipt==first);
 if(mode==36)++mp4_birth_catalogue.tuples[1].klass;if(mode==37)++mp4_birth_catalogue.tuples[1].method;
 if(mode==16)model.live[1].time+=1;if(mode==17)model.live[1].mode=3;if(mode==18)model.live[1].state=0;if(mode==19)model.live[1].root_speed=0;if(mode==20)++model.live[1].graph.handle;if(mode==21)++model.live[1].root.handle;
 if(mode==22)model.active=false;if(mode==23)model.plan=false;if(mode==24)++mp4_birth_catalogue.capture;if(mode==25)++idoly_mp4_runtime::job.generation;if(mode==26)mp4_child_readonly_withdraw_source();
 if((mode>=16&&mode<=26)||mode==36||mode==37){assert(!mp4_child_readonly_current());assert(mp4_child_readonly_release());return 0;}
 if(mode==27){const unsigned reads=model.calls;model.thread=false;assert(!mp4_child_readonly_current()&&model.calls==reads);model.thread=true;assert(mp4_child_readonly_release());return 0;}
 model.full=true;for(size_t i=0;i<2;++i)model.saved[i]=model.live[i];if(mode==28)++model.saved[1].time;if(mode==29)model.driver=false;if(mode==30)model.active=false;
 const bool full_good=mode==0||mode==34||mode==35;assert(mp4_child_readonly_full_current()==full_good);assert((mp4_child_readonly_finalize()==mp4child::Result::ok)==full_good);
 if(full_good){model.plan=false;assert(mp4_child_readonly_current());}
 if(mode==34){model.driver=false;assert(!mp4_child_readonly_current());}if(mode==35){mp4_child_readonly_withdraw_source();assert(!mp4_child_readonly_current());}
 assert(mp4_child_readonly_release()&&!mp4_child_readonly_source.ready&&!model.writes);
}
