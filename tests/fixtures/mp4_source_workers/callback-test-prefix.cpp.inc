#include <atomic>
#include <cstdint>
#include <cstddef>
#include <stdexcept>
#include <thread>
#include <cassert>
#include <cstdlib>
#include <iostream>
thread_local bool test_game_thread=true;
bool game_call(){return test_game_thread;}
