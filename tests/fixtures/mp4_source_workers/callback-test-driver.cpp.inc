int main(int argc,char**argv){
 assert(argc==2);const int test=std::atoi(argv[1]);uint64_t token=0;
 auto arm=[&](){assert(mp4_source_callbacks_arm(&token));assert(token);};
 switch(test){
 case 0:arm();assert(mp4_source_callbacks_current(token));assert(mp4_source_callbacks_release(token));break;
 case 1:{arm();{Mp4SourceCallbackFrame f(Mp4SourceCallbackKind::brain);assert(!mp4_source_callbacks_current(token));assert(!mp4_source_callbacks_release(token));}assert(mp4_source_callbacks_current(token));break;}
 case 2:{arm();{Mp4SourceCallbackFrame f(Mp4SourceCallbackKind::core);{Mp4SourceCallbackFrame nested(Mp4SourceCallbackKind::core);assert(!mp4_source_callbacks_current(token));}assert(!mp4_source_callbacks_current(token));}assert(mp4_source_callbacks_current(token));break;}
 case 3:{arm();try{Mp4SourceCallbackFrame f(Mp4SourceCallbackKind::psyllium);throw std::runtime_error("original");}catch(const std::runtime_error&){}assert(mp4_source_callbacks_current(token));break;}
 case 4:{arm();std::thread worker([]{test_game_thread=false;Mp4SourceCallbackFrame f(Mp4SourceCallbackKind::core);});worker.join();assert(!mp4_source_callbacks_current(token));assert(mp4_source_callbacks_release(token));break;}
 case 5:{arm();const uint64_t old=token;assert(mp4_source_callbacks_release(old));arm();mp4_source_callback_withdraw(old);assert(mp4_source_callbacks_current(token));break;}
 case 6:{arm();const uint64_t old=token;mp4_source_callback_withdraw(old);assert(mp4_source_callbacks_release(old));arm();assert(mp4_source_callbacks_current(token));break;}
 case 7:{arm();uint64_t other=0;assert(!mp4_source_callbacks_arm(&other));assert(!other);assert(mp4_source_callbacks_current(token));assert(!mp4_source_callbacks_release(token+1));break;}
 case 8:{test_game_thread=false;assert(!mp4_source_callbacks_arm(&token));assert(!token);test_game_thread=true;arm();test_game_thread=false;assert(!mp4_source_callbacks_current(token));assert(!mp4_source_callbacks_release(token));break;}
 case 9:{mp4_source_callback_bank.sequence=~uint64_t(0);assert(!mp4_source_callbacks_arm(&token));assert(!token);break;}
 case 10:{mp4_source_callback_bank.overflow.store(true);assert(!mp4_source_callbacks_arm(&token));assert(!mp4_source_callbacks_idle());break;}
 case 11:{arm();std::atomic<bool> entered{false},finish{false};std::thread worker([&]{test_game_thread=false;Mp4SourceCallbackFrame f(Mp4SourceCallbackKind::brain);entered.store(true);while(!finish.load())std::this_thread::yield();});while(!entered.load())std::this_thread::yield();assert(!mp4_source_callbacks_release(token));finish.store(true);worker.join();assert(!mp4_source_callbacks_current(token));assert(mp4_source_callbacks_release(token));break;}
 case 12:{Mp4SourceCallbackFrame f(Mp4SourceCallbackKind::brain);arm();assert(!mp4_source_callbacks_current(token));break;}
 case 13:{arm();int originals=0;auto hook=[&]{Mp4SourceCallbackFrame f(Mp4SourceCallbackKind::core);++originals;assert(!mp4_source_callbacks_current(token));};hook();assert(originals==1&&mp4_source_callbacks_current(token));break;}
 default:std::abort();
 }std::cout<<"callbackcase"<<test<<" ok\n";
}
