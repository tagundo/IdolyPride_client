#include <cstdint>
#include <cstddef>
#include <atomic>
#include <cassert>
#include <string>
#include <thread>
static const std::thread::id main_thread=std::this_thread::get_id();bool game_call(){return std::this_thread::get_id()==main_thread;}
