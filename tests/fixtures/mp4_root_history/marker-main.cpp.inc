int main(int argc,char**argv){assert(argc==2);model.mode=atoi(argv[1]);for(size_t i=0;i<4;++i)mp4_scene_host.parts[i]=part(i);auto source=part(0);size_t index=0;
 if(model.mode==1)model.result=Mp4SceneResult::waiting;if(model.mode==3)source.capture=wrong;if(model.mode==4)source.context=(void*)9;if(model.mode==5)index=4;
 if(model.mode==6)model.thread=false;if(model.mode==7)mp4_scene_host.active=false;if(model.mode==8)mp4_scene_host.configured=7;if(model.mode==9)model.held=false;if(model.mode==10)mp4_raw_original_operation.depth=1;
 if(model.mode==11)model.current=false;if(model.mode==15)mp4_root_capture_inside=true;if(model.mode==16)source.owner_current=nullptr;if(model.mode==19)mp4_root_capture_sequence=~uint64_t(0);if(model.mode==20)mp4_root_capture_withdraw_sequence=~uint64_t(0);
 Mp4SceneResult result=Mp4SceneResult::failed;bool threw=false;try{result=mp4_root_capture_part(index,source);}catch(int n){threw=n==42;}
 const bool issued=model.mode==0||model.mode==1||model.mode==2||(model.mode>=12&&model.mode<=14)||model.mode==17||model.mode==18||model.mode>=21;
 assert(model.calls[0]==(issued?1u:0u)&&model.calls[1]==0);assert(threw==(model.mode==2));
 Mp4RootCaptureMarker marker{};assert(!mp4_root_capture_marker(0,&marker));mp4_scene_host.captured|=1;
 const bool complete=model.mode==0||model.mode==17||model.mode==18||model.mode>=21;
 assert(mp4_root_capture_marker(0,&marker)==complete);if(complete)assert(result==Mp4SceneResult::ok&&marker.callback==callback&&marker.context==source.context&&marker.epoch==7&&marker.serial);
 if(model.mode==17){model.owner[0]=false;assert(!mp4_root_capture_marker(0,&marker));}
 if(model.mode==18){const auto saved=model.saved[0];std::thread withdraw([]{mp4_root_capture_withdraw();});withdraw.join();assert(model.saved[0]==saved&&!mp4_root_capture_marker(0,&marker));}
 if(model.mode==21){mp4_scene_host.parts[0].context=(void*)2;assert(!mp4_root_capture_marker(0,&marker));}
 if(model.mode==22){for(size_t i=1;i<4;++i){assert(mp4_root_capture_part(i,part(i))==Mp4SceneResult::ok);mp4_scene_host.captured|=1u<<i;assert(mp4_root_capture_marker(i,&marker)&&marker.context==(void*)(i+1));}}
 if(model.mode==23){model.result=Mp4SceneResult::waiting;assert(mp4_root_capture_part(0,part(0))==Mp4SceneResult::waiting&&model.calls[0]==2&&!mp4_root_capture_marker(0,&marker));}
}
