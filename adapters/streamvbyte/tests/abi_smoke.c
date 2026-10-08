#define _GNU_SOURCE
#include "tscb_adapter_v1.h"
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#ifndef DELTA64
#define DELTA64 0
#endif
#define WIDTH (DELTA64 ? 8U : 4U)
#define TYPE (DELTA64 ? TSCB_DTYPE_I64_LE_V1 : TSCB_DTYPE_U32_LE_V1)

static tscb_buffer_v1 buffer(void *p, size_t cap, size_t used, uint32_t type, size_t width) {
    tscb_buffer_v1 b = {0}; b.data=p; b.capacity_bytes=cap; b.used_bytes=used;
    b.dtype=type; b.rank=1; b.shape[0]=cap/width; b.strides_bytes[0]=width;
    b.alignment_bytes=1; return b;
}
static uint8_t *guarded(size_t n, void **base, size_t *allocation) {
    size_t page=(size_t)sysconf(_SC_PAGESIZE);
    *allocation=((n+page-1)/page+1)*page;
    *base=mmap(NULL,*allocation,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    assert(*base!=MAP_FAILED);
    uint8_t *end=(uint8_t *)*base+*allocation-page;
    assert(mprotect(end,page,PROT_NONE)==0); return end-n;
}
int main(void) {
    const char config[]="{\"isa\":\"SSE4_1\"}";
    const size_t lengths[]={0,1,2,3,4,7,8,9,31,32,33,63,64,65,127,128,129,255,256,257,1000,2048,8193};
    unsigned cases=0;
    for (size_t l=0;l<sizeof(lengths)/sizeof(lengths[0]);++l) for (int pattern=0;pattern<4;++pattern) {
        size_t n=lengths[l], bytes=n*WIDTH;
        void *input_base,*encoded_base,*output_base; size_t input_map,encoded_map,output_map;
        uint8_t *input=guarded(bytes,&input_base,&input_map);
        uint8_t *saved=malloc(bytes+1);
        for (size_t i=0;i<n;++i) {
            if (DELTA64) {
                int64_t v=pattern==0 ? 0 : pattern==1 ? INT64_MIN+(int64_t)i
                    : pattern==2 ? 1700000000123456789LL+(int64_t)i*3600000000000LL
                    : (i%2 ? 1234567890123456LL : -1234567890123456LL);
                memcpy(input+i*WIDTH,&v,WIDTH);
            } else {
                uint32_t v=pattern==0 ? 0 : pattern==1 ? UINT32_MAX
                    : pattern==2 ? (uint32_t)i : (uint32_t)i*2654435761U;
                memcpy(input+i*WIDTH,&v,WIDTH);
            }
        }
        if (bytes) memcpy(saved,input,bytes);
        assert(mprotect(input_base,input_map-(size_t)sysconf(_SC_PAGESIZE),PROT_READ)==0);
        tscb_codec_handle_v1 *enc=NULL,*dec=NULL;
        assert(tscb_create(config,sizeof(config)-1,&enc)==TSCB_STATUS_OK_V1);
        assert(tscb_create(config,sizeof(config)-1,&dec)==TSCB_STATUS_OK_V1);
        assert(tscb_set_native_timing(enc,1)==TSCB_STATUS_OK_V1);
        assert(tscb_set_native_timing(dec,1)==TSCB_STATUS_OK_V1);
        tscb_buffer_v1 src=buffer(input,bytes,bytes,TYPE,WIDTH); uint64_t bound;
        assert(tscb_compress_bound(enc,&src,&bound)==TSCB_STATUS_OK_V1);
        uint8_t *encoded=guarded((size_t)bound,&encoded_base,&encoded_map);
        memset(encoded,0xA5,(size_t)bound);
        tscb_buffer_v1 dst=buffer(encoded,(size_t)bound-1,0,TSCB_DTYPE_BYTES_V1,1);
        assert(tscb_compress(enc,&src,&dst)==TSCB_STATUS_DST_TOO_SMALL_V1);
        for (size_t i=0;i<bound;++i) assert(encoded[i]==0xA5);
        assert(dst.used_bytes==0);
        dst=buffer(encoded,(size_t)bound,0,TSCB_DTYPE_BYTES_V1,1);
        assert(tscb_compress(enc,&src,&dst)==TSCB_STATUS_OK_V1);
        assert(dst.used_bytes<=bound);
        if (bytes) assert(memcmp(input,saved,bytes)==0);
        tscb_buffer_v1 final=buffer(NULL,0,0,TSCB_DTYPE_BYTES_V1,1);
        assert(tscb_finalize(enc,&final)==TSCB_STATUS_OK_V1 && final.used_bytes==0);
        assert(tscb_finalize(enc,&final)==TSCB_STATUS_CODEC_ERROR_V1);
        tscb_native_timing_v1 t={sizeof(t),1,0,0},t2=t;
        assert(tscb_get_native_timing(enc,&t)==TSCB_STATUS_OK_V1);
        assert(tscb_get_native_timing(enc,&t2)==TSCB_STATUS_OK_V1);
        assert(t.native_encode_wall_ns==t2.native_encode_wall_ns);
        void *stream_base; size_t stream_map;
        uint8_t *stream=guarded((size_t)dst.used_bytes,&stream_base,&stream_map);
        memcpy(stream,encoded,(size_t)dst.used_bytes);
        tscb_buffer_v1 packed=buffer(stream,(size_t)dst.used_bytes,(size_t)dst.used_bytes,TSCB_DTYPE_BYTES_V1,1);
        uint8_t *output=guarded(bytes,&output_base,&output_map);
        tscb_buffer_v1 result=buffer(output,bytes,0,TYPE,WIDTH);
        assert(tscb_decompress(dec,&packed,&result)==TSCB_STATUS_OK_V1);
        assert(result.used_bytes==bytes);
        if (bytes) assert(memcmp(output,saved,bytes)==0);
        assert(tscb_get_native_timing(dec,&t)==TSCB_STATUS_OK_V1);
        uint64_t first_decode=t.native_decode_wall_ns;
        result.used_bytes=0;
        assert(tscb_decompress(dec,&packed,&result)==TSCB_STATUS_OK_V1);
        assert(tscb_get_native_timing(dec,&t)==TSCB_STATUS_OK_V1);
        assert(t.native_decode_wall_ns>=first_decode);
        uint64_t before_failed_decode=t.native_decode_wall_ns;
        result.used_bytes=0; packed.used_bytes--;
        assert(tscb_decompress(dec,&packed,&result)==TSCB_STATUS_CODEC_ERROR_V1);
        assert(result.used_bytes==0);
        assert(tscb_get_native_timing(dec,&t)==TSCB_STATUS_OK_V1);
        assert(t.native_decode_wall_ns==before_failed_decode);
        assert(tscb_reset(enc,1)==TSCB_STATUS_INVALID_ARGUMENT_V1);
        assert(tscb_reset(enc,0)==TSCB_STATUS_OK_V1);
        assert(tscb_get_native_timing(enc,&t)==TSCB_STATUS_OK_V1 && t.native_encode_wall_ns==0);
        assert(tscb_set_native_timing(enc,0)==TSCB_STATUS_OK_V1);
        assert(tscb_get_native_timing(enc,&t)==TSCB_STATUS_UNSUPPORTED_V1);
        tscb_destroy(enc); tscb_destroy(dec);
        munmap(input_base,input_map); munmap(encoded_base,encoded_map);
        munmap(output_base,output_map); munmap(stream_base,stream_map); free(saved); cases++;
    }
    /* Both typed input and typed output may be deliberately unaligned. */
    for(size_t offset=1;offset<8;++offset) {
        uint8_t input[8+33*WIDTH], output[8+33*WIDTH+8], encoded[512];
        memset(input,0x5A,sizeof(input)); memset(output,0xA5,sizeof(output));
        for(size_t i=0;i<33;++i) {
            uint64_t value=i*257U;
            memcpy(input+offset+i*WIDTH,&value,WIDTH);
        }
        tscb_codec_handle_v1 *h=NULL; assert(tscb_create(config,sizeof(config)-1,&h)==0);
        tscb_buffer_v1 src=buffer(input+offset,33*WIDTH,33*WIDTH,TYPE,WIDTH);
        tscb_buffer_v1 dst=buffer(encoded,sizeof(encoded),0,11,1);
        assert(tscb_compress(h,&src,&dst)==0);
        tscb_buffer_v1 packed=buffer(encoded,dst.used_bytes,dst.used_bytes,11,1);
        tscb_buffer_v1 result=buffer(output+offset,33*WIDTH,0,TYPE,WIDTH);
        assert(tscb_decompress(h,&packed,&result)==0);
        assert(result.used_bytes==33*WIDTH && memcmp(input+offset,output+offset,33*WIDTH)==0);
        for(size_t i=0;i<offset;++i) assert(output[i]==0xA5);
        for(size_t i=offset+33*WIDTH;i<sizeof(output);++i) assert(output[i]==0xA5);
        tscb_destroy(h); cases++;
    }
    if (DELTA64) {
        tscb_codec_handle_v1 *h=NULL; assert(tscb_create(config,sizeof(config)-1,&h)==0);
        int64_t v[]={INT64_MIN,INT64_MAX}; uint8_t dest[64]; memset(dest,0xA5,sizeof(dest));
        tscb_buffer_v1 src=buffer(v,sizeof(v),sizeof(v),TYPE,8), dst=buffer(dest,sizeof(dest),0,11,1);
        assert(tscb_compress(h,&src,&dst)==TSCB_STATUS_UNSUPPORTED_V1);
        assert(dst.used_bytes==0); for(size_t i=0;i<sizeof(dest);++i) assert(dest[i]==0xA5);
        tscb_destroy(h); cases++;
    }
    printf("%s native guard/capacity/lifecycle cases PASS: %u\n",DELTA64?"delta64":"u32",cases);
    return 0;
}
