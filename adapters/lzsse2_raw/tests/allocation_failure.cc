#include <cstdlib>
#include <stdlib.h>
#include <cassert>
#include <cstdio>
static unsigned remaining=0;
static void* failing_malloc(size_t n) {
    if(remaining--==0) return nullptr;
    return std::malloc(n);
}
static void freeing(void* p) {std::free(p);}
#define malloc failing_malloc
#define free freeing
#include "lzsse2.cpp"
#undef malloc
#undef free
int main() {
    remaining=0;
    assert(LZSSE2_MakeOptimalParseState(64)==nullptr);
    remaining=1;
    assert(LZSSE2_MakeOptimalParseState(64)==nullptr);
    LZSSE2_FreeOptimalParseState(nullptr);
    std::puts("PASS: forced first/second allocation failure and null free");
}
