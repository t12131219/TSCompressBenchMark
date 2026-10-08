// Same shipped shim/kernel objects; linker wrapping injects only faults and clocks.
#include "tscb_adapter_v1.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <new>
#include <time.h>

static int allocation_fail_at=0,clock_mode=0,native_failure=0;
static unsigned clock_calls=0;
extern "C" void* __real__Znwm(size_t);
extern "C" void* __wrap__Znwm(size_t n) {
    if(allocation_fail_at>0 && --allocation_fail_at==0)throw std::bad_alloc();
    return __real__Znwm(n);
}
extern "C" int __wrap_clock_gettime(clockid_t,struct timespec* p) {
    ++clock_calls;
    if(clock_mode==1)return -1;
    uint64_t value=uint64_t(clock_calls)*100;
    if(clock_mode==2)value=clock_calls%2?500:100;
    if(clock_mode==3)value=clock_calls==1?1:clock_calls==2?UINT64_MAX:clock_calls==3?1:3;
    p->tv_sec=static_cast<time_t>(value/1000000000);p->tv_nsec=static_cast<long>(value%1000000000);return 0;
}
#define WRAP_PACK(name) \
extern "C" void __real_##name(const uint32_t*,uint32_t,uint32_t,uint8_t*); \
extern "C" void __wrap_##name(const uint32_t* in,uint32_t n,uint32_t b,uint8_t* out) { \
    __real_##name(in,n,b,out); \
    if(native_failure==1)throw std::bad_alloc(); \
    if(native_failure==2)out[0]|=0x80; \
}
#define WRAP_UNPACK(name) \
extern "C" void __real_##name(const uint8_t*,uint32_t,uint32_t,uint32_t*); \
extern "C" void __wrap_##name(const uint8_t* in,uint32_t n,uint32_t b,uint32_t* out) { \
    __real_##name(in,n,b,out); \
    if(native_failure==1)throw std::bad_alloc(); \
}
WRAP_PACK(pack32)
WRAP_PACK(turbopack32)
WRAP_PACK(scpack32)
WRAP_PACK(bmipack32)
WRAP_UNPACK(unpack32)
WRAP_UNPACK(turbounpack32)
WRAP_UNPACK(scunpack32)
WRAP_UNPACK(bmiunpack32)
WRAP_UNPACK(horizontalunpack32)
static void need(bool condition,const char* message) {
    if(!condition){std::fprintf(stderr,"%s\n",message);std::exit(2);}
}
static void ok(tscb_status_v1 code){need(code==TSCB_STATUS_OK_V1,"ABI operation failed");}
static tscb_buffer_v1 buffer(void* p,uint64_t capacity,uint64_t used,bool integer) {
    tscb_buffer_v1 b{};b.data=p;b.capacity_bytes=capacity;b.used_bytes=used;
    b.dtype=integer?TSCB_DTYPE_U32_LE_V1:TSCB_DTYPE_BYTES_V1;b.rank=1;
    b.shape[0]=integer?(used?used:capacity)/4:capacity;b.strides_bytes[0]=integer?4:1;b.alignment_bytes=1;return b;
}
static void config(unsigned kind,bool automatic,char* target,size_t capacity) {
    const char* names[]={"PACK32","TURBO","SC","BMI2","HORIZONTAL"};
    const char* isas[]={"SCALAR","SCALAR","SCALAR","AVX2_BMI2","SSE4_1"};
    std::snprintf(target,capacity,"{\"bit_width\":%s,\"codec\":\"%s\",\"isa\":\"%s\"}",
                  automatic?"\"AUTO\"":"1",names[kind],isas[kind]);
}
static tscb_codec_handle_v1* create(unsigned kind,bool automatic) {
    char json[160];config(kind,automatic,json,sizeof(json));tscb_codec_handle_v1* h=nullptr;
    ok(tscb_create(json,std::strlen(json),&h));return h;
}
static tscb_native_timing_v1 timing(tscb_codec_handle_v1* h) {
    tscb_native_timing_v1 t{sizeof(t),1,0,0};ok(tscb_get_native_timing(h,&t));return t;
}
static bool unchanged(const unsigned char* p,size_t size) {
    for(size_t i=0;i<size;++i)if(p[i]!=0xa5)return false;
    return true;
}
static void unavailable(tscb_codec_handle_v1* h) {
    tscb_native_timing_v1 t{sizeof(t),1,77,88};
    need(tscb_get_native_timing(h,&t)==TSCB_STATUS_UNSUPPORTED_V1
         && t.native_encode_wall_ns==77 && t.native_decode_wall_ns==88,"unavailable timer published totals");
}
int main() {
    unsigned checks=0;
    for(unsigned kind=0;kind<5;++kind)for(bool automatic:{false,true}){
        auto* h=create(kind,automatic);unavailable(h);ok(tscb_set_native_timing(h,1));
        uint32_t value=1;unsigned char encoded[41]{};
        auto input=buffer(&value,4,4,true),output=buffer(encoded,41,0,false);
        clock_mode=0;clock_calls=0;ok(tscb_compress(h,&input,&output));
        need(timing(h).native_encode_wall_ns==100 && clock_calls==2,"encode clock boundary");
        unsigned char saved[41];std::memcpy(saved,encoded,41);
        auto compressed=buffer(encoded,41,41,false),decoded=buffer(&value,4,0,true);
        ok(tscb_decompress(h,&compressed,&decoded));decoded.used_bytes=0;ok(tscb_decompress(h,&compressed,&decoded));
        need(timing(h).native_decode_wall_ns==200 && timing(h).native_encode_wall_ns==100,"timer accumulation/query");
        auto final=buffer(nullptr,0,0,false);ok(tscb_finalize(h,&final));
        need(timing(h).native_encode_wall_ns==100,"finalize clock boundary");++checks;
        for(int at=1;at<=2;++at){
            ok(tscb_reset(h,0));std::memset(encoded,0xa5,41);output.used_bytes=0;const auto before=output;
            clock_calls=0;allocation_fail_at=at;
            need(tscb_compress(h,&input,&output)==TSCB_STATUS_CODEC_ERROR_V1,"allocation exception crossed ABI");
            allocation_fail_at=0;
            need(unchanged(encoded,41) && !std::memcmp(&before,&output,sizeof(output)),"encode allocation atomicity");
            need(clock_calls==0 && timing(h).native_encode_wall_ns==0,"allocation charged as kernel work");
            ok(tscb_compress(h,&input,&output));++checks;
        }
        std::memcpy(encoded,saved,41);
        for(int at=1;at<=2;++at){
            ok(tscb_reset(h,0));unsigned char destination[4]={0xa5,0xa5,0xa5,0xa5};
            auto target=buffer(destination,4,0,true);const auto before=target;
            clock_calls=0;allocation_fail_at=at;
            need(tscb_decompress(h,&compressed,&target)==TSCB_STATUS_CODEC_ERROR_V1,"decode allocation exception crossed ABI");
            allocation_fail_at=0;
            need(unchanged(destination,4) && !std::memcmp(&before,&target,sizeof(target)),"decode allocation atomicity");
            need(clock_calls==0 && timing(h).native_decode_wall_ns==0,"decode allocation charged as kernel work");
            ok(tscb_decompress(h,&compressed,&target));++checks;
        }
        char json[160];config(kind,automatic,json,sizeof(json));tscb_codec_handle_v1* failed=h;
        allocation_fail_at=1;
        need(tscb_create(json,std::strlen(json),&failed)==TSCB_STATUS_CODEC_ERROR_V1 && !failed,"create allocation failure");
        allocation_fail_at=0;++checks;
        ok(tscb_reset(h,0));std::memset(encoded,0xa5,41);output.used_bytes=0;clock_calls=0;native_failure=2;
        need(tscb_compress(h,&input,&output)==TSCB_STATUS_CODEC_ERROR_V1 && unchanged(encoded,41),"bad source output published");
        need(timing(h).native_encode_wall_ns==100,"failed source call not charged");
        need(tscb_compress(h,&input,&output)==TSCB_STATUS_CODEC_ERROR_V1 && unchanged(encoded,41),"second bad source output published");
        need(timing(h).native_encode_wall_ns==200,"failed source calls not accumulated");
        native_failure=0;ok(tscb_compress(h,&input,&output));++checks;
        for(bool encode:{false,true}){
            ok(tscb_reset(h,0));std::memcpy(encoded,saved,41);clock_calls=0;native_failure=1;
            unsigned char destination[41];std::memset(destination,0xa5,sizeof(destination));
            auto target=buffer(destination,encode?41:4,0,!encode);const auto before=target;
            auto status=encode?tscb_compress(h,&input,&target):tscb_decompress(h,&compressed,&target);
            need(status==TSCB_STATUS_CODEC_ERROR_V1 && unchanged(destination,41)
                 && !std::memcmp(&before,&target,sizeof(target)),"kernel exception crossed ABI/published output");
            need(clock_calls==2,"exception did not finish native interval");unavailable(h);
            native_failure=0;ok(tscb_reset(h,0));
            ok(encode?tscb_compress(h,&input,&target):tscb_decompress(h,&compressed,&target));++checks;
        }
        for(int mode=1;mode<=3;++mode){
            ok(tscb_reset(h,0));clock_mode=mode;clock_calls=0;decoded.used_bytes=0;
            ok(tscb_decompress(h,&compressed,&decoded));
            if(mode==3){
                need(timing(h).native_decode_wall_ns==UINT64_MAX-1,"overflow fixture decode");
                decoded.used_bytes=0;ok(tscb_decompress(h,&compressed,&decoded));
            }
            unavailable(h);++checks;
        }
        for(int mode=1;mode<=2;++mode){
            ok(tscb_reset(h,0));clock_mode=mode;clock_calls=0;output.used_bytes=0;
            ok(tscb_compress(h,&input,&output));need(!std::memcmp(encoded,saved,41),"clock fault changed wire");
            unavailable(h);++checks;
        }
        ok(tscb_reset(h,0));clock_mode=3;clock_calls=0;output.used_bytes=0;native_failure=2;
        need(tscb_compress(h,&input,&output)==TSCB_STATUS_CODEC_ERROR_V1,"overflow fixture encode");
        need(timing(h).native_encode_wall_ns==UINT64_MAX-1,"overflow fixture total");
        need(tscb_compress(h,&input,&output)==TSCB_STATUS_CODEC_ERROR_V1,"overflow fixture second encode");
        unavailable(h);native_failure=0;++checks;
        clock_mode=0;ok(tscb_set_native_timing(h,0));ok(tscb_reset(h,0));clock_calls=0;output.used_bytes=0;
        ok(tscb_compress(h,&input,&output));need(!std::memcmp(encoded,saved,41) && clock_calls==0,"disabled timing changed wire/clock calls");
        unavailable(h);ok(tscb_set_native_timing(h,1));need(timing(h).native_encode_wall_ns==0,"setter reset totals");++checks;
        need(tscb_set_native_timing(h,2)==TSCB_STATUS_INVALID_ARGUMENT_V1,"invalid setter");
        tscb_native_timing_v1 bad{0,1,77,88};
        need(tscb_get_native_timing(h,&bad)==TSCB_STATUS_ABI_MISMATCH_V1 && bad.native_encode_wall_ns==77,"timing ABI mismatch");
        need(tscb_reset(h,1)==TSCB_STATUS_INVALID_ARGUMENT_V1,"invalid reset");++checks;
        ok(tscb_destroy(h));
    }
    std::printf("{\"status\":\"PASS\",\"checks\":%u,\"allocation_exception_atomicity\":true,"
                "\"kernel_exception_atomicity\":true,\"clock_failure_backward_overflow\":true,"
                "\"failed_source_calls_timed\":true,\"same_shipped_objects\":true}\n",checks);
}
