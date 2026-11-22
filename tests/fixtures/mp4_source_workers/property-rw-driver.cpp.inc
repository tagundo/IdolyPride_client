int main(int argc,char**argv){assert(argc==2);const std::string name=argv[1];uint64_t token=0;assert(mp4_source_callbacks_arm(&token));assert(token);
 if(name=="foreign_guard"){std::thread t([]{Mp4SourcePropertyRw guard;assert(!guard.current());uint64_t stamp=99;assert(!mp4_source_property_rw_current(&stamp)&&!stamp);});t.join();assert(mp4_source_callbacks_release(token));return 0;}
 const auto kind=static_cast<Mp4SourceCallbackKind>(name.back()>='0'&&name.back()<='2'?name.back()-'0':0);
 if(name.rfind("existing_writer",0)==0){std::atomic<bool>entered{false},release{false};std::thread t([&]{Mp4SourceCallbackFrame frame(kind);entered.store(true);while(!release.load()){};});while(!entered.load()){};{Mp4SourcePropertyRw guard;assert(!guard.current());}release.store(true);t.join();assert(mp4_source_callbacks_idle()&&!mp4_source_callbacks_current(token));assert(mp4_source_callbacks_release(token));return 0;}
 if(name.rfind("ordinary",0)==0){{Mp4SourceCallbackFrame frame(kind);assert(!mp4_source_callbacks_idle());}assert(mp4_source_callbacks_current(token));}
 bool threw=false;try{Mp4SourcePropertyRw guard;assert(guard.current());uint64_t stamp=0;assert(mp4_source_property_rw_current(&stamp));assert(!mp4_source_callbacks_release(token));
  if(name=="nested"){Mp4SourcePropertyRw second;assert(second.current()&&guard.current());}
  else if(name.rfind("main_reentry",0)==0){int original=0;{Mp4SourceCallbackFrame frame(kind);++original;}assert(original==1&&!guard.current()&&!mp4_source_property_rw_current(&stamp));}
  else if(name=="typed_throw")throw 9;
 }catch(int v){assert(v==9);threw=true;}assert(threw==(name=="typed_throw"));assert(!mp4_source_property_depth&&!__atomic_load_n(&mp4_source_callback_bank.property_snapshot,__ATOMIC_SEQ_CST));assert(mp4_source_callbacks_release(token));return 0;}
