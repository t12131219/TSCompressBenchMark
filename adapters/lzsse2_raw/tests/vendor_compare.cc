#include <cstddef>
#include "lzsse2.h"
#include "tscb_adapter_v1.h"
#include <cassert>
#include <cstring>
#include <vector>
#include <cstdio>

static tscb_buffer_v1 view(void* p, size_t n, size_t used) {
    tscb_buffer_v1 b{};
    b.data=p; b.capacity_bytes=n; b.used_bytes=used;
    b.dtype=TSCB_DTYPE_BYTES_V1; b.rank=1; b.alignment_bytes=1;
    return b;
}
int main() {
    const char config[]="{\"compression_level\":12,\"content_checksum\":false}";
    unsigned cases=0;
    for(size_t n: {1,2,31,32,33,64,257,1024,4097,65536,131073}) {
        for(unsigned kind=0;kind<4;++kind) {
            std::vector<unsigned char> input(n), original(n), adapted(n), output(n);
            uint32_t random=18;
            for(size_t k=0;k<n;++k) {
                random=random*1664525+1013904223;
                input[k]=kind==0?0:kind==1?k%251:kind==2?random>>24:(k%29<20?42:random>>24);
            }
            auto* state=LZSSE2_MakeOptimalParseState(n);
            assert(state);
            size_t size=LZSSE2_CompressOptimalParse(state,input.data(),n,original.data(),n,12);
            LZSSE2_FreeOptimalParseState(state);
            assert(size);
            tscb_codec_handle_v1* handle=nullptr;
            assert(tscb_create(config,sizeof(config)-1,&handle)==0);
            auto in=view(input.data(),n,n), out=view(adapted.data(),n,0);
            assert(tscb_compress(handle,&in,&out)==0);
            assert(out.used_bytes==size && !memcmp(original.data(),adapted.data(),size));
            assert(LZSSE2_Decompress(adapted.data(),size,output.data(),n)==n);
            assert(input==output);
            assert(tscb_destroy(handle)==0);
            ++cases;
        }
    }
    std::printf("PASS: %u unmodified-source byte-identical encode and direct decode comparisons\n",cases);
}
