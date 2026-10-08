// Link with the exact shipped RLE shim.o; inject allocation and clock failures only.
#include "tscb_adapter_v1.h"
#include <time.h>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <new>
#include <initializer_list>

static int allocation_fail_at = 0;
static int clock_mode = 0;
static unsigned clock_calls = 0;

extern "C" void* __real__Znwm(size_t);
extern "C" void* __wrap__Znwm(size_t size) {
    if (allocation_fail_at > 0 && --allocation_fail_at == 0) throw std::bad_alloc();
    return __real__Znwm(size);
}
extern "C" int __wrap_clock_gettime(clockid_t, struct timespec* target) {
    ++clock_calls;
    if (clock_mode == 1) return -1;
    uint64_t value = uint64_t(clock_calls) * 100;
    if (clock_mode == 2) value = clock_calls % 2 ? 500 : 100;
    if (clock_mode == 3) value = clock_calls == 1 ? 1 : clock_calls == 2 ? UINT64_MAX :
                               clock_calls == 3 ? 1 : 3;
    target->tv_sec = static_cast<time_t>(value / 1000000000);
    target->tv_nsec = static_cast<long>(value % 1000000000);
    return 0;
}
static void need(bool condition, const char* message) {
    if (!condition) { std::fprintf(stderr,"%s\n",message); std::exit(2); }
}
static tscb_buffer_v1 buffer(void* p,uint64_t capacity,uint64_t used,bool integer) {
    tscb_buffer_v1 b{}; b.data=p;b.capacity_bytes=capacity;b.used_bytes=used;
    b.dtype=integer?TSCB_DTYPE_U32_LE_V1:TSCB_DTYPE_BYTES_V1;b.rank=1;
    b.shape[0]=integer?(used?used:capacity)/4:capacity;b.strides_bytes[0]=integer?4:1;b.alignment_bytes=1;
    return b;
}
static tscb_codec_handle_v1* create(unsigned kind,bool marked) {
    const char* names[]={"SIMPLE8B_RLE"};
    char config[128];int length=std::snprintf(config,sizeof(config),
        "{\"codec\":\"%s\",\"isa\":\"SCALAR\",\"mark_length\":%s}",names[kind],marked?"true":"false");
    tscb_codec_handle_v1* h=nullptr;
    need(tscb_create(config,length,&h)==TSCB_STATUS_OK_V1,"create failed");
    tscb_native_timing_v1 unset{sizeof(unset),1,77,88};
    need(tscb_get_native_timing(h,&unset)==TSCB_STATUS_UNSUPPORTED_V1 &&
         unset.native_encode_wall_ns==77 && unset.native_decode_wall_ns==88,"default timer not disabled");
    need(tscb_set_native_timing(h,1)==TSCB_STATUS_OK_V1,"enable failed");return h;
}
static bool unchanged(const unsigned char* p,size_t count) {
    for(size_t i=0;i<count;++i)if(p[i]!=0xa5)return false;
    return true;
}
static tscb_native_timing_v1 totals(tscb_codec_handle_v1* h) {
    tscb_native_timing_v1 value{sizeof(value),1,0,0};
    need(tscb_get_native_timing(h,&value)==TSCB_STATUS_OK_V1,"timing unavailable unexpectedly");return value;
}

int main() {
    unsigned checks=0;
    for(unsigned kind=0;kind<1;++kind)for(bool marked:{false,true}) {
        auto* h=create(kind,marked);
        uint32_t value=1;
        unsigned char encoded[64]{};
        auto input=buffer(&value,4,4,true), output=buffer(encoded,sizeof(encoded),0,false);
        clock_mode=0;clock_calls=0;
        need(tscb_compress(h,&input,&output)==TSCB_STATUS_OK_V1,"initial encode failed");
        need(totals(h).native_encode_wall_ns==100 && clock_calls==2,"native interval includes wrong calls");
        unsigned char saved[64];std::memcpy(saved,encoded,sizeof(encoded));
        const uint64_t size=output.used_bytes;
        auto compressed=buffer(encoded,size,size,false);
        auto decoded=buffer(&value,4,0,true);
        need(tscb_decompress(h,&compressed,&decoded)==TSCB_STATUS_OK_V1,"initial decode failed");
        decoded.used_bytes=0;
        need(tscb_decompress(h,&compressed,&decoded)==TSCB_STATUS_OK_V1,"second decode failed");
        need(totals(h).native_decode_wall_ns==200 && totals(h).native_encode_wall_ns==100,
             "timer totals do not accumulate or query is destructive");
        auto final=buffer(nullptr,0,0,false);need(tscb_finalize(h,&final)==TSCB_STATUS_OK_V1,"finalize failed");
        need(totals(h).native_encode_wall_ns==100,"zero-byte finalize altered codec interval");++checks;
        for(int fail_at=1;fail_at<=3;++fail_at){
            need(tscb_reset(h,0)==TSCB_STATUS_OK_V1,"reset failed");
            std::memset(encoded,0xa5,sizeof(encoded));output.used_bytes=0;
            const auto before=output;clock_calls=0;allocation_fail_at=fail_at;
            need(tscb_compress(h,&input,&output)==TSCB_STATUS_CODEC_ERROR_V1,"allocation exception crossed ABI");
            allocation_fail_at=0;
            need(unchanged(encoded,sizeof(encoded)) && std::memcmp(&output,&before,sizeof(output))==0,
                 "allocation failure published partial output");
            need(clock_calls==0 && totals(h).native_encode_wall_ns==0,"allocation failure claims native work");
            need(tscb_compress(h,&input,&output)==TSCB_STATUS_OK_V1,"allocation failure damaged lifecycle");++checks;
        }
        std::memcpy(encoded,saved,sizeof(encoded));compressed=buffer(encoded,size,size,false);
        for(int fail_at=1;fail_at<=3;++fail_at){
            need(tscb_reset(h,0)==TSCB_STATUS_OK_V1,"reset failed");
            unsigned char destination[4]={0xa5,0xa5,0xa5,0xa5};
            auto target=buffer(destination,4,0,true);const auto before=target;
            clock_calls=0;allocation_fail_at=fail_at;
            need(tscb_decompress(h,&compressed,&target)==TSCB_STATUS_CODEC_ERROR_V1,"decode exception crossed ABI");
            allocation_fail_at=0;
            need(unchanged(destination,4) && std::memcmp(&target,&before,sizeof(target))==0,
                 "decode allocation exception published output");
            need(clock_calls==0 && totals(h).native_decode_wall_ns==0,"decode allocation failure claims work");
            need(tscb_decompress(h,&compressed,&target)==TSCB_STATUS_OK_V1,"decode failure damaged handle");++checks;
        }
        for(int mode=1;mode<=3;++mode){
            need(tscb_reset(h,0)==TSCB_STATUS_OK_V1,"reset failed");
            clock_mode=mode;clock_calls=0;decoded.used_bytes=0;
            need(tscb_decompress(h,&compressed,&decoded)==TSCB_STATUS_OK_V1,"clock failure changed decoder success");
            if(mode==3){
                need(totals(h).native_decode_wall_ns==UINT64_MAX-1,"overflow fixture invalid");
                decoded.used_bytes=0;
                need(tscb_decompress(h,&compressed,&decoded)==TSCB_STATUS_OK_V1,"overflow fixture decode failed");
            }
            tscb_native_timing_v1 observation{sizeof(observation),1,77,88};
            need(tscb_get_native_timing(h,&observation)==TSCB_STATUS_UNSUPPORTED_V1
                 && observation.native_encode_wall_ns==77 && observation.native_decode_wall_ns==88,
                 "unavailable/backward/overflow clock published measurements");
            need(value==1 && std::memcmp(encoded,saved,size)==0,"clock fault changed source bytes");
            clock_mode=0;clock_calls=0;
            need(tscb_reset(h,0)==TSCB_STATUS_OK_V1 && totals(h).native_decode_wall_ns==0,"reset did not recover clock");
            ++checks;
        }
        need(tscb_set_native_timing(h,0)==TSCB_STATUS_OK_V1,"disable failed");
        clock_calls=0;decoded.used_bytes=0;
        need(tscb_decompress(h,&compressed,&decoded)==TSCB_STATUS_OK_V1 && clock_calls==0,"disabled clock invoked");
        tscb_native_timing_v1 wrong{sizeof(wrong)-1,1,0,0};
        need(tscb_get_native_timing(h,&wrong)==TSCB_STATUS_ABI_MISMATCH_V1,"timing ABI mismatch accepted");
        need(tscb_destroy(h)==TSCB_STATUS_OK_V1,"destroy failed");++checks;
    }
    std::printf("{\"status\":\"PASS\",\"checks\":%u,\"allocation_exception_atomicity\":true,"
                "\"clock_failure_backward_overflow\":true,\"same_shipped_object\":true}\n",checks);
    return 0;
}
