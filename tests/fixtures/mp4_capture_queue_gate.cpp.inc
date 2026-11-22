#include <cassert>
#include <cstdint>
#include <atomic>
#include <thread>
#include <cstdio>
// @QUEUE_GATE@
using namespace idoly_mp4_capture_queue;
int main(){unsigned cases=0;
 {Gate g;Gate::Cancel c;assert(c.try_enter(g)&&c.current());c.leave();assert(!c.current());++cases;}
 {Gate g;Gate::Add a(g);Gate::Cancel c;assert(!c.try_enter(g));++cases;}
 {Gate g;Gate::Add a(g);{Gate::Add b(g);assert(!b.interrupted_cancel());}Gate::Cancel c;assert(!c.try_enter(g));a.leave();assert(c.try_enter(g));++cases;}
 {Gate g;Gate::Cancel c;assert(c.try_enter(g));{Gate::Add a(g);assert(a.interrupted_cancel()&&!c.current());}assert(!c.current());++cases;}
 {Gate g;Gate::Cancel c;assert(c.try_enter(g));std::atomic<bool>started{false},entered{false},done{false};std::thread t([&](){started.store(true);Gate::Add a(g);entered.store(true);done.store(true);});
  while(!started.load())std::this_thread::yield();
  assert(!entered.load());assert(c.current());c.leave();t.join();assert(done.load()&&entered.load());++cases;}
 {Gate g;std::atomic<bool>entered{false},release{false};std::thread t([&](){Gate::Add a(g);entered.store(true);while(!release.load())std::this_thread::yield();});
  while(!entered.load())std::this_thread::yield();
  Gate::Cancel c;assert(!c.try_enter(g));release.store(true);t.join();assert(c.try_enter(g));++cases;}
 {Gate g;std::atomic<unsigned>inside{0},calls{0};std::atomic<bool>collision{false};auto worker=[&](){for(unsigned n=0;n<10000;++n){Gate::Add a(g);if(inside.fetch_add(1)!=0)collision.store(true);++calls;inside.fetch_sub(1);}};
  std::thread a(worker),b(worker);a.join();b.join();assert(!collision.load()&&calls==20000);++cases;}
 {Gate g;Gate::Cancel c;assert(c.try_enter(g));Gate::Cancel nested;assert(!nested.try_enter(g)&&c.current());++cases;}
 {Gate a,b;Gate::Add outer(a);{Gate::Add inner(b);Gate::Add nested(a);assert(!nested.interrupted_cancel());}++cases;}
 {Gate g;try{Gate::Add a(g);throw 1;}catch(int){}Gate::Cancel c;assert(c.try_enter(g));++cases;}
 {Gate g;try{Gate::Cancel c;assert(c.try_enter(g));throw 1;}catch(int){}Gate::Cancel c;assert(c.try_enter(g));++cases;}
 printf("%u CPU gate cases passed\n",cases);
}
