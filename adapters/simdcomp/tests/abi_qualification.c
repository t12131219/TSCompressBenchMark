/* Independent SBP1 bit oracle, protected external spans and ABI fault tests. */
#define _GNU_SOURCE
#include "tscb_adapter_v1.h"
#include "simdcomp.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

tscb_status_v1 tscb_get_telemetry_json(tscb_codec_handle_v1 *, const char **, uint64_t *);
static size_t cases;
static unsigned route_now, width_now; static size_t count_now;
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "FAIL route=%u width=%u count=%zu line=%d: %s\n", route_now, width_now, count_now, __LINE__, #c); abort(); } } while (0)

typedef struct { const char *api, *coding, *isa; unsigned mode; } config;
static const config configs[] = {
    {"LENGTH", "PLAIN", "SSE4_1", 0}, {"MASKED", "PLAIN", "SSE4_1", 0},
    {"WITHOUTMASK", "PLAIN", "SSE4_1", 0}, {"MASKED", "DELTA", "SSE4_1", 1},
    {"WITHOUTMASK", "DELTA", "SSE4_1", 1}, {"LENGTH", "FOR", "SSE4_1", 2},
    {"FULL", "FOR", "SSE4_1", 3}, {"MASKED", "PLAIN", "AVX2", 4},
    {"WITHOUTMASK", "PLAIN", "AVX2", 4},
};
static tscb_codec_handle_v1 *create(unsigned route, uint32_t seed) {
    char json[160]; const config *c = configs+route;
    int n = snprintf(json, sizeof(json), "{\"api\":\"%s\",\"coding\":\"%s\",\"isa\":\"%s\",\"starting_point\":%u}", c->api,c->coding,c->isa,seed);
    tscb_codec_handle_v1 *h = NULL; CHECK(tscb_create(json, (uint64_t)n, &h) == 0 && h); return h;
}
static tscb_buffer_v1 buffer(void *p, uint64_t cap, uint64_t used, unsigned dtype, int source) {
    unsigned w = dtype == TSCB_DTYPE_U32_LE_V1 ? 4 : 1;
    tscb_buffer_v1 b = {0}; b.data = p; b.capacity_bytes = cap; b.used_bytes = used;
    b.dtype = dtype; b.rank = 1; b.shape[0] = (source && w == 4 ? used : cap)/w;
    b.strides_bytes[0] = w; b.alignment_bytes = 1; b.ownership = TSCB_OWNERSHIP_CALLER_V1;
    return b;
}
typedef struct { uint8_t *base, *data; size_t size, readable, bytes, shift; } guarded;
static guarded allocate(size_t bytes, unsigned shift) {
    size_t page = (size_t)sysconf(_SC_PAGESIZE); guarded g = {0};
    g.readable = ((bytes+shift+16+page-1)/page)*page; g.size = g.readable+2*page;
    g.bytes = bytes; g.shift = shift;
    g.base = mmap(NULL,g.size,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    CHECK(g.base != MAP_FAILED && !mprotect(g.base,page,PROT_NONE) && !mprotect(g.base+page+g.readable,page,PROT_NONE));
    memset(g.base+page,0xa5,g.readable); g.data = g.base+page+g.readable-bytes-shift; return g;
}
static void readonly(guarded g) { CHECK(!mprotect(g.base+(size_t)sysconf(_SC_PAGESIZE),g.readable,PROT_READ)); }
static void canary(guarded g, size_t used) {
    for (unsigned i=1;i<=16;++i) CHECK(g.data[-(int)i] == 0xa5);
    for (size_t i=used;i<g.bytes+g.shift;++i) CHECK(g.data[i] == 0xa5);
}
static void release(guarded g) { CHECK(!munmap(g.base,g.size)); }
static uint64_t get(const uint8_t *p, unsigned n) { uint64_t v=0; for(unsigned i=0;i<n;++i)v|=(uint64_t)p[i]<<(8*i);return v; }
static void put(uint8_t *p, uint64_t v, unsigned n) { for(unsigned i=0;i<n;++i)p[i]=(uint8_t)(v>>(8*i)); }
static uint64_t checksum(const uint8_t *p,size_t n) { uint64_t v=UINT64_C(14695981039346656037);for(size_t i=0;i<n;++i)v=(v^p[i])*UINT64_C(1099511628211);return v; }
static void resign(uint8_t *p,size_t n) { put(p+n-8,checksum(p,n-8),8); }
static unsigned bits_(uint32_t v) { unsigned w=0;while(v){++w;v>>=1;}return w; }
static uint32_t mask(unsigned w) { return w==32 ? UINT32_MAX : w ? (1U<<w)-1 : 0; }

/* Derive sizes by counting bit positions; no original helper is called. */
static size_t oracle(const uint32_t *values,size_t count,unsigned mode,uint32_t seed,uint8_t *out,
                     uint64_t *value_bits, uint64_t *payload, unsigned force_width) {
    unsigned block = mode==4?256:128; size_t at=40; uint32_t previous=seed;
    *value_bits = *payload = 0;
    for(size_t start=0;start<count;start+=block) {
        unsigned n=(unsigned)(count-start<block?count-start:block);
        unsigned layout=mode==1||mode==3?1:mode==4&&n==256?2:0;
        unsigned physical=layout==1?128:layout==2?256:n, lanes=layout==2?8:4;
        uint32_t codes[256], absolute[256], combined=0, base=mode==1?previous:seed;
        for(unsigned i=0;i<physical;++i) {
            uint32_t x=i<n?values[start+i]:mode==1?values[start+n-1]:seed;
            absolute[i]=x; codes[i]=mode==1?x-base:mode==2||mode==3?x-seed:x;
            base=x; if(i<n)combined|=codes[i];
        }
        unsigned w=force_width?force_width:bits_(combined);
        unsigned lane_items=(physical+lanes-1)/lanes;
        size_t words=(lane_items*w+31)/32, bytes=w==32?physical*4:words*lanes*4;
        put(out+at,n,2); out[at+2]=(uint8_t)w;out[at+3]=(uint8_t)layout;put(out+at+4,bytes,4);
        uint8_t *wire=out+at+8;memset(wire,0,bytes);
        if(w==32)for(unsigned i=0;i<physical;++i)put(wire+i*4,absolute[i],4);
        else for(unsigned i=0;i<physical;++i)for(unsigned bit=0;bit<w;++bit)if((codes[i]>>bit)&1) {
            size_t pos=(i/lanes)*w+bit, byte=((pos/32)*lanes+i%lanes)*4+(pos%32)/8;
            wire[byte]|=(uint8_t)(1U<<(pos%8));
        }
        at+=8+bytes; *payload+=bytes; *value_bits+=(uint64_t)n*w; previous=values[start+n-1];
    }
    memcpy(out,"TSCBSBP1",8);put(out+8,count,4);put(out+12,seed,4);put(out+16,mode,4);
    put(out+20,block,4);put(out+24,(count+block-1)/block,4);put(out+28,0,4);put(out+32,at-40,8);
    put(out+at,checksum(out,at),8);return at+8;
}
static void json_number(tscb_codec_handle_v1 *h,const char *key,uint64_t value,int account) {
    const char *text;uint64_t n;CHECK((account?tscb_get_accounting_json(h,&text,&n):tscb_get_telemetry_json(h,&text,&n))==0 && n);
    char field[160];snprintf(field,sizeof(field),"\"%s\":%llu",key,(unsigned long long)value);
    const char *p=strstr(text,field);CHECK(p && (p[strlen(field)]==','||p[strlen(field)]=='}'));
}
static void json_string(tscb_codec_handle_v1 *h,const char *key,const char *value) {
    const char *text;uint64_t n;CHECK(tscb_get_telemetry_json(h,&text,&n)==0 && n);
    char field[200];snprintf(field,sizeof(field),"\"%s\":\"%s\"",key,value);CHECK(strstr(text,field));
}
static void finish(tscb_codec_handle_v1 *h) { tscb_buffer_v1 f=buffer(NULL,0,0,TSCB_DTYPE_BYTES_V1,0);CHECK(tscb_finalize(h,&f)==0 && !f.used_bytes); }

#ifdef INSTRUMENTED
static int allocation_failure=-1,clock_mode,return_fault,width_fault;
static unsigned allocations, frees, calls[20]; static size_t allocation_sizes[2];
static uint64_t clock_tick;
void *__real_malloc(size_t);void *__real_calloc(size_t,size_t);void __real_free(void *);
int __real_posix_memalign(void **,size_t,size_t);int __real_clock_gettime(clockid_t,struct timespec *);
static int allocation(size_t size) { if(allocations<2)allocation_sizes[allocations]=size;++allocations;if(allocation_failure==0){allocation_failure=-1;return 1;}if(allocation_failure>0)--allocation_failure;return 0; }
void *__wrap_malloc(size_t n) { return allocation(n)?NULL:__real_malloc(n); }
void *__wrap_calloc(size_t n,size_t w) { return allocation(n*w)?NULL:__real_calloc(n,w); }
int __wrap_posix_memalign(void **p,size_t alignment,size_t n) { return allocation(n)?12:__real_posix_memalign(p,alignment,n); }
void __wrap_free(void *p) { if(p)++frees;__real_free(p); }
int __wrap_clock_gettime(clockid_t id,struct timespec *p) {
    if(!clock_mode)return __real_clock_gettime(id,p);
    if(clock_mode==2)return -1;
    uint64_t tick=clock_mode==3?UINT64_C(100000)-clock_tick:clock_tick;clock_tick+=10;
    p->tv_sec=(time_t)(tick/UINT64_C(1000000000));p->tv_nsec=(long)(tick%UINT64_C(1000000000));return 0;
}
#define RET_PACK(name, id, declaration, arguments) \
    __m128i *__real_##name declaration; \
    __m128i *__wrap_##name declaration { ++calls[id]; __m128i *end=__real_##name arguments;return return_fault==1?NULL:return_fault==2?(__m128i *)((uint8_t *)end+1):end; }
#define RET_UNPACK(name, id, declaration, arguments) \
    const __m128i *__real_##name declaration; \
    const __m128i *__wrap_##name declaration { ++calls[id];const __m128i *end=__real_##name arguments;return return_fault==1?NULL:return_fault==2?(const __m128i *)((const uint8_t *)end+1):end; }
RET_PACK(simdpack_length,0,(const uint32_t *v,size_t n,__m128i *p,uint32_t w),(v,n,p,w))
RET_PACK(simdpack_shortlength,1,(const uint32_t *v,int n,__m128i *p,uint32_t w),(v,n,p,w))
RET_PACK(simdpackFOR_length,2,(uint32_t s,const uint32_t *v,int n,__m128i *p,uint32_t w),(s,v,n,p,w))
RET_UNPACK(simdunpack_length,3,(const __m128i *p,size_t n,uint32_t *v,uint32_t w),(p,n,v,w))
RET_UNPACK(simdunpack_shortlength,4,(const __m128i *p,int n,uint32_t *v,uint32_t w),(p,n,v,w))
RET_UNPACK(simdunpackFOR_length,5,(uint32_t s,const __m128i *p,int n,uint32_t *v,uint32_t w),(s,p,n,v,w))
#define VOID_WRAP(name,id,declaration,arguments) void __real_##name declaration;void __wrap_##name declaration { ++calls[id];__real_##name arguments; }
VOID_WRAP(simdpack,6,(const uint32_t *v,__m128i *p,uint32_t w),(v,p,w))
VOID_WRAP(simdpackwithoutmask,7,(const uint32_t *v,__m128i *p,uint32_t w),(v,p,w))
VOID_WRAP(simdpackd1,8,(uint32_t s,const uint32_t *v,__m128i *p,uint32_t w),(s,v,p,w))
VOID_WRAP(simdpackwithoutmaskd1,9,(uint32_t s,const uint32_t *v,__m128i *p,uint32_t w),(s,v,p,w))
VOID_WRAP(simdpackFOR,10,(uint32_t s,const uint32_t *v,__m128i *p,uint32_t w),(s,v,p,w))
VOID_WRAP(simdunpack,11,(const __m128i *p,uint32_t *v,uint32_t w),(p,v,w))
VOID_WRAP(simdunpackd1,12,(uint32_t s,const __m128i *p,uint32_t *v,uint32_t w),(s,p,v,w))
VOID_WRAP(simdunpackFOR,13,(uint32_t s,const __m128i *p,uint32_t *v,uint32_t w),(s,p,v,w))
/* AVX public wrappers use ABI-compatible opaque pointers in this baseline TU. */
VOID_WRAP(avxpack,14,(const uint32_t *v,void *p,uint32_t w),(v,p,w))
VOID_WRAP(avxpackwithoutmask,15,(const uint32_t *v,void *p,uint32_t w),(v,p,w))
VOID_WRAP(avxunpack,16,(const void *p,uint32_t *v,uint32_t w),(p,v,w))
uint32_t __real_maxbits_length(const uint32_t *,uint32_t);
uint32_t __wrap_maxbits_length(const uint32_t *v,uint32_t n) { ++calls[17];uint32_t w=__real_maxbits_length(v,n);return width_fault?33:w; }
uint32_t __real_simdmaxbitsd1_length(uint32_t,const uint32_t *,uint32_t);
uint32_t __wrap_simdmaxbitsd1_length(uint32_t s,const uint32_t *v,uint32_t n) { ++calls[18];uint32_t w=__real_simdmaxbitsd1_length(s,v,n);return width_fault?33:w; }
uint32_t __real_bits(uint32_t);uint32_t __wrap_bits(uint32_t v) { ++calls[19];uint32_t w=__real_bits(v);return width_fault?33:w; }
#endif

static void roundtrip(size_t n,unsigned route,unsigned width,unsigned pattern,uint32_t seed,unsigned shift) {
    route_now=route;width_now=width;count_now=n;unsigned mode=configs[route].mode,block=mode==4?256:128;
    guarded input=allocate(n*4,shift),restored=allocate(n*4,shift);
    uint32_t *saved=malloc((n?n:1)*4);uint8_t *expected=malloc(48+((n+block-1)/block)*(8+block*4));CHECK(saved && expected);
    uint32_t random=0x9e3779b9U,previous=seed;
    for(size_t i=0;i<n;++i) {
        random=random*1664525U+1013904223U;
        uint32_t code=pattern==0||i%block==0?mask(width):random&mask(width);
        saved[i]=mode==1?previous+code:mode==2||mode==3?seed+code:code;previous=saved[i];
        memcpy(input.data+i*4,saved+i,4);
    }
    uint64_t value_bits,payload;size_t size=oracle(saved,n,mode,seed,expected,&value_bits,&payload,0);
    guarded output=allocate(size,shift);readonly(input);
    tscb_buffer_v1 in=buffer(input.data,n*4,n*4,TSCB_DTYPE_U32_LE_V1,1),out=buffer(output.data,size,0,TSCB_DTYPE_BYTES_V1,0);
    tscb_codec_handle_v1 *h=create(route,seed);uint64_t bound=0,blocks=(n+block-1)/block,tails=n%block?1:0;
    CHECK(!tscb_compress_bound(h,&in,&bound) && bound==48+blocks*(8+block*4));
#ifdef INSTRUMENTED
    allocations=frees=0;
    unsigned encode_before[17];memcpy(encode_before,calls,sizeof(encode_before));
#endif
    CHECK(!tscb_compress(h,&in,&out) && out.used_bytes==size);
#ifdef INSTRUMENTED
    CHECK(allocations==2 && frees==2 && allocation_sizes[0]==bound && allocation_sizes[1]==block*8);
    unsigned encode_expected[17]={0};
    unsigned full_api=route==0?0:route==1?6:route==2?7:route==3?8:route==4?9:route==5?2:route==6?10:route==7?14:15;
    unsigned tail_api=route<3?(route==0?0:1):route<7?full_api:0;
    encode_expected[full_api]+=(unsigned)(blocks-tails);encode_expected[tail_api]+=(unsigned)tails;
    for(unsigned i=0;i<17;++i)CHECK(calls[i]==encode_before[i]+encode_expected[i]);
#endif
    CHECK(!memcmp(output.data,expected,size) && !memcmp(input.data,saved,n*4));
    json_number(h,"native_raw_bytes",n*4,0);json_number(h,"native_payload_bytes",payload,0);
    json_number(h,"blocks",blocks,0);json_number(h,"full_calls",blocks-tails,0);json_number(h,"tail_calls",tails,0);
    json_number(h,"native_staging_allocation_bytes",bound+block*8,0);
    json_number(h,"native_staging_input_copy_bytes",n*4,0);json_number(h,"native_staging_output_copy_bytes",payload+size,0);
    json_number(h,"internal_padding_bytes",(mode==1||mode==3)&&tails?(128-n%128)*4:0,0);
    json_string(h,"actual_isa",mode==4?"AVX2_WITH_SSE4_1_TAIL":"SSE4_1");
    const char *full_encode[]={"simdpack_length","simdpack","simdpackwithoutmask","simdpackd1","simdpackwithoutmaskd1","simdpackFOR_length","simdpackFOR","avxpack","avxpackwithoutmask"};
    json_string(h,"actual_full_api",full_encode[route]);
    json_string(h,"actual_tail_api",mode==4?"simdpack_length":route==1||route==2?"simdpack_shortlength":full_encode[route]);
    finish(h);json_number(h,"value_bits",value_bits,1);json_number(h,"padding_bits",payload*8-value_bits,1);
    json_number(h,"container_bytes",8,1);json_number(h,"metadata_bytes",32+blocks*8,1);json_number(h,"checksum_bytes",8,1);
    CHECK(size*8==value_bits+(payload*8-value_bits)+(48+blocks*8)*8);
    tscb_codec_handle_v1 *decoder=create(route,mode==0||mode==4?0:seed^0xffffffffU);
    tscb_buffer_v1 compressed=buffer(output.data,size,size,TSCB_DTYPE_BYTES_V1,1),decoded=buffer(restored.data,n*4,0,TSCB_DTYPE_U32_LE_V1,0);
    readonly(output);
#ifdef INSTRUMENTED
    allocations=frees=0;
    unsigned decode_before[17];memcpy(decode_before,calls,sizeof(decode_before));
#endif
    CHECK(!tscb_decompress(decoder,&compressed,&decoded) && decoded.used_bytes==n*4 && !memcmp(restored.data,saved,n*4));
#ifdef INSTRUMENTED
    CHECK(allocations==2 && frees==2 && allocation_sizes[0]==(n?n*4:1) && allocation_sizes[1]==block*8);
    unsigned decode_expected[17]={0};
    unsigned full_decoder=route==0?3:route<3?11:route<5?12:route==5?5:route==6?13:16;
    unsigned tail_decoder=route<3?(route==0?3:4):route<7?full_decoder:3;
    decode_expected[full_decoder]+=(unsigned)(blocks-tails);decode_expected[tail_decoder]+=(unsigned)tails;
    for(unsigned i=0;i<17;++i)CHECK(calls[i]==decode_before[i]+decode_expected[i]);
#endif
    json_number(decoder,"native_staging_input_copy_bytes",payload,0);json_number(decoder,"native_staging_output_copy_bytes",n*8,0);
    json_number(decoder,"native_staging_allocation_bytes",(n?n*4:1)+block*8,0);
    json_number(decoder,"full_calls",blocks-tails,0);json_number(decoder,"tail_calls",tails,0);
    canary(input,n*4);canary(output,size);canary(restored,n*4);
    CHECK(!tscb_destroy(h) && !tscb_destroy(decoder));free(saved);free(expected);
    release(input);release(output);release(restored);++cases;
}

static void reject_frame(unsigned route,uint8_t *frame,size_t size,tscb_status_v1 expected) {
    uint8_t snapshot[5000],restored[4096];CHECK(size<=sizeof(snapshot));memcpy(snapshot,frame,size);memset(restored,0xa5,sizeof(restored));
    tscb_buffer_v1 in=buffer(frame,size,size,TSCB_DTYPE_BYTES_V1,1),out=buffer(restored,sizeof(restored),0,TSCB_DTYPE_U32_LE_V1,0);
    tscb_codec_handle_v1 *h=create(route,0);CHECK(tscb_decompress(h,&in,&out)==expected && !out.used_bytes && !memcmp(snapshot,frame,size));
    for(size_t i=0;i<sizeof(restored);++i)CHECK(restored[i]==0xa5);
    CHECK(!tscb_destroy(h));
}
static void malformed(void) {
    uint32_t values[257];for(unsigned i=0;i<257;++i)values[i]=i+1;
    uint8_t original[5000],bad[5000];uint64_t vb,payload;
    for(unsigned route=0;route<9;++route) {
        route_now=route;unsigned mode=configs[route].mode;size_t n=mode==4?257:129;
        size_t size=oracle(values,n,mode,0,original,&vb,&payload,0);
        for(size_t length=0;length<size;++length) { memcpy(bad,original,length);reject_frame(route,bad,length,TSCB_STATUS_CODEC_ERROR_V1); }
        const unsigned offsets[]={0,8,12,16,20,24,28,32,40,42,43,44};
        for(unsigned i=0;i<sizeof(offsets)/sizeof(offsets[0]);++i) {
            if(offsets[i]==12 && mode!=0 && mode!=4)continue; /* Serialized nonzero seed is valid. */
            memcpy(bad,original,size);bad[offsets[i]]^=0x80;resign(bad,size);reject_frame(route,bad,size,TSCB_STATUS_CODEC_ERROR_V1);
        }
        memcpy(bad,original,size);bad[size-1]^=1;reject_frame(route,bad,size,TSCB_STATUS_CODEC_ERROR_V1);
        memcpy(bad,original,size-8);bad[size-8]=0;put(bad+32,get(original+32,8)+1,8);resign(bad,size+1);reject_frame(route,bad,size+1,TSCB_STATUS_CODEC_ERROR_V1);
        uint32_t tiny=1;size=oracle(&tiny,1,mode,0,bad,&vb,&payload,3);reject_frame(route,bad,size,TSCB_STATUS_CODEC_ERROR_V1);
        size=oracle(&tiny,1,mode,0,bad,&vb,&payload,0);bad[56]|=1;resign(bad,size);reject_frame(route,bad,size,TSCB_STATUS_CODEC_ERROR_V1);
        if(mode==1||mode==3) {
            tiny=UINT32_MAX;size=oracle(&tiny,1,mode,0,bad,&vb,&payload,0);bad[60]^=1;resign(bad,size);reject_frame(route,bad,size,TSCB_STATUS_CODEC_ERROR_V1);
        }
    }
}

static void descriptors_and_lifecycle(void) {
    uint32_t values[257];for(unsigned i=0;i<257;++i)values[i]=i;
    uint8_t frame[5000],decoded[1032];
    for(unsigned route=0;route<9;++route) {
        route_now=route;tscb_codec_handle_v1 *h=create(route,0);
        tscb_buffer_v1 in=buffer(values,sizeof(values),sizeof(values),TSCB_DTYPE_U32_LE_V1,1),out=buffer(frame,sizeof(frame),0,TSCB_DTYPE_BYTES_V1,0),final=buffer(NULL,0,0,TSCB_DTYPE_BYTES_V1,0);
        const char *json;uint64_t json_size,bound=UINT64_MAX;
        CHECK(tscb_finalize(h,&final)==TSCB_STATUS_FINALIZE_REQUIRED_V1);
        CHECK(tscb_get_accounting_json(h,&json,&json_size)==TSCB_STATUS_FINALIZE_REQUIRED_V1);
        CHECK(tscb_query(h,"{}",2,NULL,0,&json_size)==TSCB_STATUS_UNSUPPORTED_V1);
        CHECK(tscb_reset(h,1)==TSCB_STATUS_INVALID_ARGUMENT_V1);
        for(unsigned test=0;test<14;++test) {
            tscb_buffer_v1 bad=in;
            switch(test) {
                case 0:bad.rank=2;break;case 1:bad.reserved=1;break;case 2:bad.ownership=3;break;
                case 3:bad.dtype=TSCB_DTYPE_I64_LE_V1;break;case 4:bad.shape[0]--;break;
                case 5:bad.strides_bytes[0]=8;break;case 6:bad.shape[1]=1;break;case 7:bad.strides_bytes[7]=1;break;
                case 8:bad.alignment_bytes=3;break;case 9:bad.alignment_bytes=0;break;
                case 10:bad.data=NULL;break;case 11:bad.used_bytes=bad.capacity_bytes+1;break;
                case 12:bad.capacity_bytes--;break;case 13:bad.data=(void *)(UINTPTR_MAX-3);break;
            }
            memset(frame,0xa5,sizeof(frame));CHECK(tscb_compress(h,&bad,&out)==TSCB_STATUS_INVALID_ARGUMENT_V1 && !out.used_bytes);
            CHECK(tscb_compress_bound(h,&bad,&bound)==TSCB_STATUS_INVALID_ARGUMENT_V1);
            for(size_t i=0;i<sizeof(frame);++i)CHECK(frame[i]==0xa5);
        }
        tscb_buffer_v1 oversized=in;oversized.shape[0]=16777217;oversized.used_bytes=oversized.capacity_bytes=oversized.shape[0]*4;
        CHECK(tscb_compress_bound(h,&oversized,&bound)==TSCB_STATUS_UNSUPPORTED_V1);
        tscb_buffer_v1 alias=buffer(values,sizeof(values),0,TSCB_DTYPE_BYTES_V1,0);CHECK(tscb_compress(h,&in,&alias)==TSCB_STATUS_INVALID_ARGUMENT_V1);
        tscb_buffer_v1 small=buffer(frame,47,0,TSCB_DTYPE_BYTES_V1,0);CHECK(tscb_compress(h,&in,&small)==TSCB_STATUS_DST_TOO_SMALL_V1 && !small.used_bytes);
        uint64_t vb,payload;size_t exact=oracle(values,257,configs[route].mode,0,frame,&vb,&payload,0);
        memset(frame,0xa5,sizeof(frame));small=buffer(frame,exact-1,0,TSCB_DTYPE_BYTES_V1,0);
        CHECK(tscb_compress(h,&in,&small)==TSCB_STATUS_DST_TOO_SMALL_V1 && !small.used_bytes);
        for(size_t i=0;i<sizeof(frame);++i)CHECK(frame[i]==0xa5);
        CHECK(!tscb_compress(h,&in,&out));CHECK(tscb_compress(h,&in,&small)==TSCB_STATUS_CODEC_ERROR_V1);
        finish(h);CHECK(tscb_finalize(h,&final)==TSCB_STATUS_CODEC_ERROR_V1);
        tscb_codec_handle_v1 *decoder=create(route,0);tscb_buffer_v1 src=buffer(frame,out.used_bytes,out.used_bytes,TSCB_DTYPE_BYTES_V1,1);
        memset(decoded,0xa5,sizeof(decoded));tscb_buffer_v1 dst=buffer(decoded,1024,0,TSCB_DTYPE_U32_LE_V1,0);
        CHECK(tscb_decompress(decoder,&src,&dst)==TSCB_STATUS_DST_TOO_SMALL_V1 && !dst.used_bytes);
        for(size_t i=0;i<sizeof(decoded);++i)CHECK(decoded[i]==0xa5);
        tscb_buffer_v1 dec_alias=buffer(frame,1028,0,TSCB_DTYPE_U32_LE_V1,0);CHECK(tscb_decompress(decoder,&src,&dec_alias)==TSCB_STATUS_INVALID_ARGUMENT_V1);
        CHECK(!tscb_reset(h,0));CHECK(tscb_get_accounting_json(h,&json,&json_size)==TSCB_STATUS_FINALIZE_REQUIRED_V1);
        tscb_buffer_v1 again=buffer(decoded,sizeof(decoded),0,TSCB_DTYPE_BYTES_V1,0);CHECK(!tscb_compress(h,&in,&again) && again.used_bytes==out.used_bytes && !memcmp(decoded,frame,out.used_bytes));
        CHECK(!tscb_destroy(h) && !tscb_destroy(decoder));
    }
    const char *bad[]={"{}","null","{\"api\":\"FULL\",\"coding\":\"PLAIN\",\"isa\":\"SSE4_1\",\"starting_point\":0}","{\"api\":\"LENGTH\",\"coding\":\"DELTA\",\"isa\":\"SSE4_1\",\"starting_point\":0}","{\"api\":\"MASKED\",\"coding\":\"DELTA\",\"isa\":\"AVX2\",\"starting_point\":0}","{\"api\":\"MASKED\",\"coding\":\"PLAIN\",\"isa\":\"AVX512\",\"starting_point\":0}","{\"api\":\"LENGTH\",\"coding\":\"PLAIN\",\"isa\":\"SSE4_1\",\"starting_point\":1}","{\"api\":\"LENGTH\",\"coding\":\"FOR\",\"isa\":\"SSE4_1\",\"starting_point\":4294967296}","{\"api\":\"LENGTH\",\"coding\":\"FOR\",\"isa\":\"SSE4_1\",\"starting_point\":00}"};
    for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);++i) { tscb_codec_handle_v1 *h=(void *)1;CHECK(tscb_create(bad[i],strlen(bad[i]),&h)==TSCB_STATUS_INVALID_ARGUMENT_V1 && !h); }
    CHECK(tscb_create(NULL,0,NULL)==TSCB_STATUS_INVALID_ARGUMENT_V1 && !tscb_destroy(NULL));
}

#ifdef INSTRUMENTED
static void faults(void) {
    uint32_t values[256];for(unsigned i=0;i<256;++i)values[i]=7;
    uint8_t frame[5000],restored[1024];
    for(unsigned route=0;route<9;++route) {
      for(unsigned count_case=0;count_case<(route<7?1:2);++count_case) {
        route_now=route;tscb_codec_handle_v1 *h=create(route,0);size_t n=route<7||count_case?1:256;
        tscb_buffer_v1 in=buffer(values,n*4,n*4,TSCB_DTYPE_U32_LE_V1,1),out=buffer(frame,sizeof(frame),0,TSCB_DTYPE_BYTES_V1,0);
        CHECK(!tscb_set_native_timing(h,1));clock_mode=1;clock_tick=0;
        for(unsigned fault=0;fault<3;++fault) {
            memset(frame,0xa5,sizeof(frame));out.used_bytes=0;
            allocations=frees=0;
            if(fault<2)allocation_failure=(int)fault;else width_fault=1;
            CHECK(tscb_compress(h,&in,&out)==TSCB_STATUS_CODEC_ERROR_V1 && !out.used_bytes);width_fault=0;
            CHECK(allocations==(fault==0?1:2) && frees==fault);
            for(size_t i=0;i<sizeof(frame);++i)CHECK(frame[i]==0xa5);
        }
        tscb_native_timing_v1 failed_time={sizeof(failed_time),1,0,0};
        CHECK(!tscb_get_native_timing(h,&failed_time) && failed_time.native_encode_wall_ns==10);
        /* All pointer routes, both NULL and wrong non-NULL lengths. */
        if(route<3||route==5||(route>=7&&n<256))for(return_fault=1;return_fault<=2;++return_fault) {
            uint64_t before=failed_time.native_encode_wall_ns;allocations=frees=0;
            memset(frame,0xa5,sizeof(frame));CHECK(tscb_compress(h,&in,&out)==TSCB_STATUS_CODEC_ERROR_V1 && !out.used_bytes);
            CHECK(allocations==2 && frees==2);
            CHECK(!tscb_get_native_timing(h,&failed_time) && failed_time.native_encode_wall_ns==before+20);
            for(size_t i=0;i<sizeof(frame);++i)CHECK(frame[i]==0xa5);
        }
        return_fault=0;CHECK(!tscb_compress(h,&in,&out));finish(h);
        uint8_t saved_frame[5000];memcpy(saved_frame,frame,(size_t)out.used_bytes);uint64_t encoded_size=out.used_bytes;
        tscb_native_timing_v1 timing={sizeof(timing),1,0,0};CHECK(!tscb_get_native_timing(h,&timing) && timing.native_encode_wall_ns>0 && !timing.native_decode_wall_ns);
        tscb_native_timing_v1 repeat={sizeof(repeat),1,0,0};CHECK(!tscb_get_native_timing(h,&repeat) && !memcmp(&timing,&repeat,sizeof(timing)));
        tscb_buffer_v1 src=buffer(frame,out.used_bytes,out.used_bytes,TSCB_DTYPE_BYTES_V1,1),dec=buffer(restored,n*4,0,TSCB_DTYPE_U32_LE_V1,0);
        for(unsigned fault=0;fault<2;++fault) {
            memset(restored,0xa5,sizeof(restored));allocation_failure=(int)fault;allocations=frees=0;
            CHECK(tscb_decompress(h,&src,&dec)==TSCB_STATUS_CODEC_ERROR_V1 && !dec.used_bytes);
            CHECK(allocations==fault+1 && frees==fault);
            for(size_t i=0;i<sizeof(restored);++i)CHECK(restored[i]==0xa5);
        }
        if(route<3||route==5||(route>=7&&n<256))for(return_fault=1;return_fault<=2;++return_fault) {
            CHECK(!tscb_get_native_timing(h,&failed_time));uint64_t before=failed_time.native_decode_wall_ns;
            allocations=frees=0;
            memset(restored,0xa5,sizeof(restored));CHECK(tscb_decompress(h,&src,&dec)==TSCB_STATUS_CODEC_ERROR_V1 && !dec.used_bytes);
            CHECK(allocations==2 && frees==2);
            CHECK(!tscb_get_native_timing(h,&failed_time) && failed_time.native_decode_wall_ns==before+10);
            for(size_t i=0;i<sizeof(restored);++i)CHECK(restored[i]==0xa5);
        }
        return_fault=0;CHECK(!tscb_decompress(h,&src,&dec));CHECK(!tscb_get_native_timing(h,&repeat) && repeat.native_decode_wall_ns>0);
        CHECK(!tscb_reset(h,0));CHECK(!tscb_get_native_timing(h,&repeat) && !repeat.native_encode_wall_ns && !repeat.native_decode_wall_ns);
        for(clock_mode=2;clock_mode<=3;++clock_mode) {
            CHECK(!tscb_reset(h,0));out.used_bytes=0;clock_tick=0;CHECK(!tscb_compress(h,&in,&out));CHECK(tscb_get_native_timing(h,&repeat)==TSCB_STATUS_UNSUPPORTED_V1);
            CHECK(out.used_bytes==encoded_size && !memcmp(saved_frame,frame,(size_t)encoded_size));
        }
        CHECK(!tscb_set_native_timing(h,0));CHECK(tscb_get_native_timing(h,&repeat)==TSCB_STATUS_UNSUPPORTED_V1);
        CHECK(!tscb_reset(h,0));out.used_bytes=0;CHECK(!tscb_compress(h,&in,&out));
        CHECK(out.used_bytes==encoded_size && !memcmp(saved_frame,frame,(size_t)encoded_size));
        CHECK(tscb_get_native_timing(h,&repeat)==TSCB_STATUS_UNSUPPORTED_V1);CHECK(tscb_set_native_timing(h,2)==TSCB_STATUS_INVALID_ARGUMENT_V1);
        repeat.version=2;CHECK(tscb_get_native_timing(h,&repeat)==TSCB_STATUS_ABI_MISMATCH_V1);
        CHECK(!tscb_destroy(h));clock_mode=0;
      }
    }
    allocation_failure=0;tscb_codec_handle_v1 *h=(void *)1;const char *c="{\"api\":\"LENGTH\",\"coding\":\"PLAIN\",\"isa\":\"SSE4_1\",\"starting_point\":0}";
    CHECK(tscb_create(c,strlen(c),&h)==TSCB_STATUS_CODEC_ERROR_V1 && !h);
    for(unsigned i=0;i<20;++i)CHECK(calls[i]);
}
#endif

int main(void) {
    CHECK(tscb_get_abi_version()==1);
    const size_t lengths[]={0,1,2,3,4,7,15,31,32,33,63,64,65,127,128,129,255,256,257,511,512,513,1023};
    const uint32_t seeds[]={0,1,0x80000000U,UINT32_MAX};
    for(unsigned route=0;route<9;++route)for(unsigned seed=0;seed<(configs[route].mode==0||configs[route].mode==4?1:4);++seed)
        for(unsigned width=0;width<=32;++width)for(unsigned pattern=0;pattern<2;++pattern)for(unsigned i=0;i<sizeof(lengths)/sizeof(lengths[0]);++i)
            roundtrip(lengths[i],route,width,pattern,seeds[seed],(route+seed+width+pattern+i)%8);
    malformed();descriptors_and_lifecycle();
#ifdef INSTRUMENTED
    faults();puts("SIMDComp same-object allocator/clock/API-length/API-route faults PASS");
#endif
    printf("SIMDComp bounded ABI PASS: %zu scalar-wire cases; 9 configurations; 33 widths; 23 lengths; 8 alignments; 4 D1/FOR seeds; guard pages; malformed; lifecycle; exact accounting\n",cases);
    return 0;
}
