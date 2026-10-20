#include "alp_port.h"
#include <atomic>
#include <cstdlib>
#include <cstring>
#include <new>
// Test-only ELF operator-new interposition. Production has no injection switch.
static std::atomic<bool> fail_next{false};
void* operator new(std::size_t n) {
    if(fail_next.exchange(false)) throw std::bad_alloc();
    void* p=std::malloc(n?n:1);if(!p)throw std::bad_alloc();return p;
}
void* operator new[](std::size_t n){return ::operator new(n);}
void operator delete(void* p) noexcept {std::free(p);}
void operator delete[](void* p) noexcept {std::free(p);}
void operator delete(void* p,std::size_t) noexcept {std::free(p);}
void operator delete[](void* p,std::size_t) noexcept {std::free(p);}
int main() {
    double input[2]={1.25,-0.0};unsigned char frame[40000],output[32];
    std::memset(frame,0xa5,sizeof(frame));size_t used=7,consumed=7;uint64_t count=7;uint8_t d=7,m=7;
    fail_next=true;
    if(alp_port_encode(input,2,8,0,frame,sizeof(frame),&used)!=ALP_OUT_OF_MEMORY||used||fail_next)return 1;
    for(auto x:frame)if(x!=0xa5)return 2;
    if(alp_port_encode(input,2,8,0,frame,sizeof(frame),&used))return 3;
    std::memset(output,0x77,sizeof(output));const size_t frame_bytes=used;used=7;fail_next=true;
    if(alp_port_decode(frame,frame_bytes,output,sizeof(output),&used,&consumed,&count,&d,&m)!=ALP_OUT_OF_MEMORY||used||consumed||count||d||m||fail_next)return 4;
    for(auto x:output)if(x!=0x77)return 5;
    if(alp_port_decode(frame,frame_bytes,output,sizeof(output),&used,&consumed,&count,&d,&m)||std::memcmp(input,output,16))return 6;
    return 0;
}
