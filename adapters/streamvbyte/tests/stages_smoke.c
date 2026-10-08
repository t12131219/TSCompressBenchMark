#define _GNU_SOURCE
#include "tscb_streamvbyte_stages.h"
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

static tscb_buffer_v1 buffer(void *p,size_t n,uint32_t type,size_t width,int source) {
    tscb_buffer_v1 b={0}; b.data=p;b.capacity_bytes=n;b.used_bytes=source?n:0;
    b.dtype=type;b.rank=1;b.shape[0]=n/width;b.strides_bytes[0]=width;b.alignment_bytes=1;
    return b;
}
static uint8_t *guard(size_t n,void **base,size_t *size) {
    size_t page=(size_t)sysconf(_SC_PAGESIZE);
    *size=((n+page-1)/page+1)*page;
    *base=mmap(NULL,*size,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    assert(*base!=MAP_FAILED);
    uint8_t *end=(uint8_t *)*base+*size-page;
    assert(mprotect(end,page,PROT_NONE)==0);return end-n;
}
int main(void) {
    const char config[]="{\"isa\":\"SSE4_1\"}";
    size_t lengths[]={0,1,2,3,4,7,8,9,31,32,33,127,128,129,8193};
    unsigned cases=0;
    for(size_t l=0;l<sizeof(lengths)/sizeof(lengths[0]);++l)
    for(unsigned mask=0;mask<8;++mask) {
        size_t n=lengths[l],k=(mask&1)?(n?n-1:0):n,w=2*k;
        tscb_codec_handle_v1 *h=NULL;
        assert(tscb_create(config,sizeof(config)-1,&h)==0);
        int64_t *input=calloc(n?n:1,8);
        for(size_t i=0;i<n;++i) input[i]=(i%2?-1234567890123456LL:1234567890123456LL);
        void *bases[6];size_t maps[6];
        uint8_t *a=guard(k*8,&bases[0],&maps[0]);
        uint8_t *b=guard(w*4,&bases[1],&maps[1]);
        size_t bound=4+w*4+((mask&4)?(w+3)/4:0);
        uint8_t *c=guard(bound,&bases[2],&maps[2]);
        uint8_t *ib=guard(w*4,&bases[3],&maps[3]);
        uint8_t *ia=guard(k*8,&bases[4],&maps[4]);
        uint8_t *result=guard(n*8,&bases[5],&maps[5]);
        /* Deliberately unaligned seed ABI must never dereference a typed pointer. */
        uint8_t seed_storage[9]={0};int64_t *seed=(int64_t *)(void *)(seed_storage+1);
        tscb_buffer_v1 src=buffer(input,n*8,7,8,1),out=buffer(a,k*8,8,8,0);
        if(k) {
            memset(a,0xA5,k*8);out=buffer(a,(k-1)*8,8,8,0);
            assert(tscb_svb_stage_a(h,&src,&out,seed,0,mask&1)==3);
            assert(!out.used_bytes);for(size_t i=0;i<k*8;++i)assert(a[i]==0xA5);
            out=buffer(a,k*8,8,8,0);
        }
        assert(tscb_svb_stage_a(h,&src,&out,seed,0,mask&1)==0);
        assert(out.used_bytes==k*8);
        tscb_buffer_v1 sa=buffer(a,k*8,8,8,1),sb=buffer(b,w*4,6,4,0);
        assert(tscb_svb_stage_b(h,&sa,&sb,0,!!(mask&2))==0);
        tscb_buffer_v1 bs=buffer(b,w*4,6,4,1),packed=buffer(c,bound,11,1,0);
        memset(c,0xA5,bound); packed.capacity_bytes--;packed.shape[0]--;
        assert(tscb_svb_stage_c(h,&bs,&packed,0,!!(mask&4))==3);
        assert(packed.used_bytes==0);for(size_t i=0;i<bound;++i)assert(c[i]==0xA5);
        packed=buffer(c,bound,11,1,0);
        assert(tscb_svb_stage_c(h,&bs,&packed,0,!!(mask&4))==0);
        /* Exact used stream touches a protected page: source padding stays internal. */
        void *stream_base;size_t stream_map;
        uint8_t *stream=guard(packed.used_bytes,&stream_base,&stream_map);
        memcpy(stream,c,packed.used_bytes);
        tscb_buffer_v1 cs=buffer(stream,packed.used_bytes,11,1,1),bo=buffer(ib,w*4,6,4,0);
        assert(tscb_svb_stage_c(h,&cs,&bo,1,!!(mask&4))==0);
        if(w)assert(memcmp(b,ib,w*4)==0);
        bo.used_bytes=0;cs.used_bytes--;
        assert(tscb_svb_stage_c(h,&cs,&bo,1,!!(mask&4))==4);
        assert(bo.used_bytes==0);
        tscb_buffer_v1 bi=buffer(ib,w*4,6,4,1),ao=buffer(ia,k*8,8,8,0);
        assert(tscb_svb_stage_b(h,&bi,&ao,1,!!(mask&2))==0);
        if(k)assert(memcmp(a,ia,k*8)==0);
        tscb_buffer_v1 ai=buffer(ia,k*8,8,8,1),original=buffer(result,n*8,7,8,0);
        assert(tscb_svb_stage_a(h,&ai,&original,seed,1,mask&1)==0);
        if(n)assert(memcmp(input,result,n*8)==0);
        if(k) {
            /* Every short output and overlapping view is rejected before mutation. */
            ao=buffer(ia,(k-1)*8,8,8,0);
            assert(tscb_svb_stage_b(h,&bi,&ao,1,!!(mask&2))==3);
            ao=buffer(ib,k*8,8,8,0);
            assert(tscb_svb_stage_b(h,&bi,&ao,1,!!(mask&2))==1);
        }
        tscb_buffer_v1 final=buffer(NULL,0,11,1,0);
        assert(tscb_finalize(h,&final)==0 && !final.used_bytes);
        for(unsigned j=0;j<6;++j)assert(munmap(bases[j],maps[j])==0);
        assert(munmap(stream_base,stream_map)==0);
        free(input);tscb_destroy(h);cases++;
    }
    for(size_t offset=1;offset<8;++offset) {
        tscb_codec_handle_v1 *h=NULL;assert(tscb_create(config,sizeof(config)-1,&h)==0);
        uint8_t input[32],a[32],b[32],ia[32],ib[32],restore[32],packed[64];
        for(size_t i=0;i<3;++i){int64_t x=100-(int64_t)i*7;memcpy(input+offset+i*8,&x,8);}
        int64_t seed=0;
        tscb_buffer_v1 src=buffer(input+offset,24,7,8,1),dst=buffer(a+offset,16,8,8,0);
        assert(tscb_svb_stage_a(h,&src,&dst,&seed,0,1)==0);
        src=buffer(a+offset,16,8,8,1);dst=buffer(b+offset,16,6,4,0);
        assert(tscb_svb_stage_b(h,&src,&dst,0,1)==0);
        src=buffer(b+offset,16,6,4,1);dst=buffer(packed+offset,32,11,1,0);
        assert(tscb_svb_stage_c(h,&src,&dst,0,1)==0);
        src=buffer(packed+offset,dst.used_bytes,11,1,1);dst=buffer(ib+offset,16,6,4,0);
        assert(tscb_svb_stage_c(h,&src,&dst,1,1)==0);
        src=buffer(ib+offset,16,6,4,1);dst=buffer(ia+offset,16,8,8,0);
        assert(tscb_svb_stage_b(h,&src,&dst,1,1)==0);
        src=buffer(ia+offset,16,8,8,1);dst=buffer(restore+offset,24,7,8,0);
        assert(tscb_svb_stage_a(h,&src,&dst,&seed,1,1)==0);
        assert(memcmp(input+offset,restore+offset,24)==0);
        tscb_destroy(h);cases++;
    }
    tscb_codec_handle_v1 *h=NULL;assert(tscb_create(config,sizeof(config)-1,&h)==0);
    int64_t values[]={INT64_MIN,INT64_MAX},seed=123;
    uint64_t destination=0xA5A5A5A5A5A5A5A5ULL;
    tscb_buffer_v1 src=buffer(values,16,7,8,1),out=buffer(&destination,8,8,8,0);
    assert(tscb_svb_stage_a(h,&src,&out,&seed,0,1)==2);
    assert(!out.used_bytes && seed==123 && destination==0xA5A5A5A5A5A5A5A5ULL);
    uint64_t z=2;seed=INT64_MAX;
    int64_t restore[2]={123,456};
    src=buffer(&z,8,8,8,1);out=buffer(restore,16,7,8,0);
    assert(tscb_svb_stage_a(h,&src,&out,&seed,1,1)==4);
    assert(!out.used_bytes && restore[0]==123 && restore[1]==456 && seed==INT64_MAX);
    tscb_destroy(h);
    printf("native stage inverse/switch/guard/atomic/overflow cases PASS: %u\n",cases+2);
    return 0;
}
