// Compile with the exact frozen port + Bench binding, separately for each method.
#include "tsbench_core.h"
#include "tscb_adapter_v1.h"
#include <algorithm>
#include <cassert>
#include <cfenv>
#include <cstdio>
#include <cstring>
#include <vector>

#if TSCB_ALP_RD
constexpr const char* config_json = "{\"algorithm\":\"alp-rd\"}";
#else
constexpr const char* config_json = "{\"algorithm\":\"alp\"}";
#endif
static tscb_buffer_v1 descriptor(std::vector<uint8_t>& data, size_t used) {
    tscb_buffer_v1 b{};b.data=data.data();b.capacity_bytes=data.size();b.used_bytes=used;
    b.dtype=TSCB_DTYPE_BYTES_V1;b.rank=1;return b;
}
int main() {
    size_t cases=0;
    for(size_t width:{4u,8u})for(size_t n:{0u,1u,2u,31u,1023u,1024u,1025u,2049u,102399u,102400u,102401u}) {
        std::vector<uint8_t> raw(std::max<size_t>(1,n*width));
        const uint64_t bits64[]={0,UINT64_C(0x8000000000000000),UINT64_C(0x7ff0000000000000),UINT64_C(0x7ff8000000000042),UINT64_C(0x7ff0000000000001),1,UINT64_C(0x8000000000000001),UINT64_C(0x7fefffffffffffff)};
        const uint32_t bits32[]={0,0x80000000u,0x7f800000u,0x7fc00042u,0x7f800001u,1,0x80000001u,0x7f7fffffu};
        for(size_t i=0;i<n;++i)std::memcpy(raw.data()+i*width,width==4?static_cast<const void*>(&bits32[i%8]):static_cast<const void*>(&bits64[i%8]),width);
        auto before=raw;
        tsbench_core_config config{};config.version=1;config.dtype=width==4?9:10;config.rank=1;config.shape[0]=n;config.parameters_json="{}";
        void *encoder=nullptr,*decoder=nullptr;
        assert(tsbench_core_create(&config,0,&encoder)==0 && tsbench_core_create(&config,1,&decoder)==0);
        size_t bound=0;assert(tsbench_core_bound(encoder,raw.data(),n*width,&bound)==0);
        std::vector<uint8_t> packed(bound+2,0xa5),out(std::max<size_t>(1,n*width)+2,0xa5);
        tsbench_core_result result{};
        assert(tsbench_core_encode(encoder,raw.data(),n*width,packed.data()+1,bound,&result)==0);
        const size_t used=result.size;assert(used>=32 && !result.owner && packed.front()==0xa5 && packed.back()==0xa5);
        tsbench_core_release(&result);
        auto encoded=packed;
        assert(tsbench_core_decode(decoder,packed.data()+1,used,out.data()+1,n*width,&result)==0);
        assert(result.size==n*width && !std::memcmp(out.data()+1,raw.data(),n*width));tsbench_core_release(&result);
        assert(out.front()==0xa5 && out.back()==0xa5 && before==raw && encoded==packed);
        packed[used]^=1;std::fill(out.begin(),out.end(),0xa5);
        assert(tsbench_core_decode(decoder,packed.data()+1,used,out.data()+1,n*width,&result)!=0 && !result.size);
        assert(std::all_of(out.begin(),out.end(),[](uint8_t b){return b==0xa5;}));
        packed=encoded;
        assert(tsbench_core_encode(encoder,raw.data(),n*width,packed.data()+1,used-1,&result)==3 && !result.size);
        assert(encoded==packed);
        assert(tsbench_core_destroy(encoder)==0 && tsbench_core_destroy(decoder)==0);
        // The C1 wrapper publishes only after every column succeeds.
        std::vector<uint8_t> typed(16+n*width);std::memcpy(typed.data(),"TAI1",4);typed[4]=width;typed[6]=1;
        for(size_t j=0;j<8;++j)typed[8+j]=static_cast<uint8_t>(n>>(8*j));
        if(n)std::memcpy(typed.data()+16,raw.data(),n*width);
        tscb_codec_handle_v1* h=nullptr;assert(tscb_create(config_json,std::strlen(config_json),&h)==0);
        auto input=descriptor(typed,typed.size());uint64_t size=0;assert(tscb_compress_bound(h,&input,&size)==0);
        std::vector<uint8_t> columns(size);auto output=descriptor(columns,0);
        assert(tscb_compress(h,&input,&output)==0);const size_t frame_size=output.used_bytes;
        std::vector<uint8_t> empty(1);auto finish=descriptor(empty,0);finish.capacity_bytes=0;
        assert(tscb_finalize(h,&finish)==0 && finish.used_bytes==0);assert(tscb_finalize(h,&finish)!=0);
        assert(tscb_reset(h,0)==0);
        input=descriptor(columns,frame_size);output=descriptor(out,0);output.capacity_bytes=n*width;
        assert(tscb_decompress(h,&input,&output)==0 && output.used_bytes==n*width && !std::memcmp(out.data(),raw.data(),n*width));
        columns[frame_size-1]^=1;std::fill(out.begin(),out.end(),0xa5);
        assert(tscb_decompress(h,&input,&output)!=0 && output.used_bytes==0);
        assert(std::all_of(out.begin(),out.end(),[](uint8_t b){return b==0xa5;}));
        assert(tscb_destroy(h)==0);++cases;
    }
    std::printf("PASS %zu dtype/length cases; direct+C1, IEEE, unaligned, guards, capacity, CRC, lifecycle\n",cases);
}
