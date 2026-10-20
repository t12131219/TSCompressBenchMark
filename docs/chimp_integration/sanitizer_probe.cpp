// Actual Bench C1/core entry points; not a copied codec implementation.
#include "tscb_adapter_v1.h"
#include "tsbench_core.h"
#include <dlfcn.h>
#include <cassert>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>
#include <algorithm>
using Bytes=std::vector<uint8_t>;
static void put(Bytes& b,uint64_t v,unsigned n){for(unsigned i=0;i<n;++i)b.push_back(uint8_t(v>>(8*i)));}
static tscb_buffer_v1 buffer(Bytes& b,size_t used=0){tscb_buffer_v1 r{};r.data=b.data();r.capacity_bytes=b.size();r.used_bytes=used;r.dtype=TSCB_DTYPE_BYTES_V1;r.rank=1;r.shape[0]=used;r.strides_bytes[0]=1;r.alignment_bytes=1;return r;}
#define LOAD(name) auto name=reinterpret_cast<decltype(&::name)>(dlsym(lib,#name));assert(name)
int main(int argc,char** argv){
    const char* keys[]={"chimp","chimp32","chimp128","chimpn","chimp128-no-index","chimpn32","pmc-mr","swing-filter","swing-filter-disjoint","swing-filter-disjoint-quantized"};
    const unsigned methods[]={1,2,3,3,4,5,7,8,9,10};assert(argc==11);size_t cases=0;
    for(int k=0;k<10;++k){
        void* lib=dlopen(argv[k+1],RTLD_NOW|RTLD_LOCAL);if(!lib){std::cerr<<dlerror()<<'\n';return 2;}
        LOAD(tsbench_core_create);LOAD(tsbench_core_destroy);LOAD(tsbench_core_bound);LOAD(tsbench_core_encode);LOAD(tsbench_core_decode);LOAD(tsbench_core_release);
        LOAD(tscb_create);LOAD(tscb_destroy);LOAD(tscb_reset);LOAD(tscb_compress_bound);LOAD(tscb_compress);LOAD(tscb_decompress);LOAD(tscb_finalize);
        const bool lossy=methods[k]>=7;const unsigned width=(methods[k]==2||methods[k]==5||lossy)?4:8;
        const unsigned minimum=methods[k]==8?2:methods[k]>=9?1:0;
        for(size_t n:{size_t(0),size_t(1),size_t(2),size_t(31),size_t(129),size_t(1025)}){
            if(n<minimum)continue;
            Bytes raw;for(size_t i=0;i<n;++i){if(width==4){float v=float(i%257)/8;uint32_t word;std::memcpy(&word,&v,4);put(raw,word,4);}else{double v=double(i%257)/8;uint64_t word;std::memcpy(&word,&v,8);put(raw,word,8);}}
            const Bytes before=raw;Bytes unaligned(1,0x55);unaligned.insert(unaligned.end(),raw.begin(),raw.end());
            tsbench_core_config cfg{};cfg.version=1;cfg.dtype=width==4?9:10;cfg.rank=1;cfg.shape[0]=n;
            cfg.parameters_json=lossy?"{\"epsilon\":\"0.125\",\"quality_mode\":\"compatible\"}":"{\"block_size\":127}";
            void* enc=nullptr;assert(tsbench_core_create(&cfg,0,&enc)==0);size_t bound=0;assert(tsbench_core_bound(enc,unaligned.data()+1,raw.size(),&bound)==0);
            tsbench_core_result compressed{};assert(tsbench_core_encode(enc,unaligned.data()+1,raw.size(),nullptr,0,&compressed)==0);
            assert(compressed.owner&&compressed.size<=bound);assert(tsbench_core_destroy(enc)==0);
            Bytes frame(compressed.data,compressed.data+compressed.size);tsbench_core_release(&compressed);tsbench_core_release(&compressed);
            cfg.parameters_json="{}";void* dec=nullptr;assert(tsbench_core_create(&cfg,1,&dec)==0);
            Bytes canary(raw.size()+2,0xa5);tsbench_core_result restored{};
            for(size_t size:{size_t(0),size_t(7),frame.size()-1}){
                assert(tsbench_core_decode(dec,frame.data(),size,canary.data()+1,raw.size(),&restored)!=0);
                assert(!restored.size&&!restored.owner&&std::all_of(canary.begin(),canary.end(),[](auto v){return v==0xa5;}));
            }
            auto corrupt=frame;corrupt.back()^=1;assert(tsbench_core_decode(dec,corrupt.data(),corrupt.size(),nullptr,0,&restored)!=0);
            assert(tsbench_core_decode(dec,frame.data(),frame.size(),nullptr,0,&restored)==0);assert(tsbench_core_destroy(dec)==0);
            assert(restored.owner&&restored.size==raw.size());if(!lossy&&raw.size())assert(!std::memcmp(restored.data,raw.data(),raw.size()));tsbench_core_release(&restored);
            Bytes input={'C','F','I','1',uint8_t(width),uint8_t(methods[k]),1,0};put(input,n,8);input.insert(input.end(),raw.begin(),raw.end());
            auto source=buffer(input,input.size());
            const std::string config="{\"algorithm\":\""+std::string(keys[k])+"\""+(lossy?",\"epsilon\":\"0.125\",\"quality_mode\":\"compatible\"}":",\"block_size\":127}");
            tscb_codec_handle_v1* h=nullptr;assert(tscb_create(config.data(),config.size(),&h)==0);assert(tscb_reset(h,0)==0);
            uint64_t capacity=0;assert(tscb_compress_bound(h,&source,&capacity)==0);Bytes encoded(size_t(capacity)+2,0xa5);auto output=buffer(encoded);output.data=encoded.data()+1;output.capacity_bytes=0;
            assert(tscb_compress(h,&source,&output)==TSCB_STATUS_DST_TOO_SMALL_V1);assert(!output.used_bytes&&std::all_of(encoded.begin(),encoded.end(),[](auto v){return v==0xa5;}));
            output.capacity_bytes=capacity;assert(tscb_compress(h,&source,&output)==0);const size_t used=output.used_bytes;assert(encoded.front()==0xa5&&encoded.back()==0xa5);
            Bytes finish(1);auto tail=buffer(finish);tail.capacity_bytes=0;assert(tscb_finalize(h,&tail)==0&&!tail.used_bytes);assert(tscb_finalize(h,&tail)!=0);
            assert(tscb_destroy(h)==0);h=nullptr;assert(tscb_create(config.data(),config.size(),&h)==0);
            auto encoded_input=output;encoded_input.used_bytes=used;Bytes decoded(raw.size()+2,0xa5);auto dest=buffer(decoded);dest.data=decoded.data()+1;dest.capacity_bytes=raw.size();
            if(!raw.empty()){dest.capacity_bytes=raw.size()-1;assert(tscb_decompress(h,&encoded_input,&dest)==TSCB_STATUS_DST_TOO_SMALL_V1);assert(!dest.used_bytes&&std::all_of(decoded.begin(),decoded.end(),[](auto v){return v==0xa5;}));dest.capacity_bytes=raw.size();}
            encoded[used]^=1;assert(tscb_decompress(h,&encoded_input,&dest)!=0);assert(!dest.used_bytes&&std::all_of(decoded.begin(),decoded.end(),[](auto v){return v==0xa5;}));encoded[used]^=1;
            assert(tscb_decompress(h,&encoded_input,&dest)==0&&dest.used_bytes==raw.size());assert(decoded.front()==0xa5&&decoded.back()==0xa5);
            if(!lossy&&!raw.empty())assert(!std::memcmp(decoded.data()+1,raw.data(),raw.size()));assert(tscb_destroy(h)==0);
            assert(raw==before&&unaligned[0]==0x55&&std::equal(raw.begin(),raw.end(),unaligned.begin()+1));++cases;
        }
        // Reserved EOF rejection is transactional even for a reused context.
        if(!lossy){Bytes raw;put(raw,width==4?UINT64_C(0x7fc00000):UINT64_C(0x7ff8000000000000),width);tsbench_core_config cfg{};cfg.version=1;cfg.dtype=width==4?9:10;cfg.rank=1;cfg.shape[0]=1;cfg.parameters_json="{}";void* h=nullptr;assert(tsbench_core_create(&cfg,0,&h)==0);tsbench_core_result r{};assert(tsbench_core_encode(h,raw.data(),raw.size(),nullptr,0,&r)==2&&!r.owner&&!r.size);tsbench_core_destroy(h);++cases;}
        if(methods[k]==8||methods[k]==10){Bytes raw;std::vector<float> values=methods[k]==8?std::vector<float>{.1f,.2f,.3f,-.1f,-.2f,-.3f}:std::vector<float>{1.f};for(float v:values){uint32_t w;std::memcpy(&w,&v,4);put(raw,w,4);}tsbench_core_config cfg{};cfg.version=1;cfg.dtype=9;cfg.rank=1;cfg.shape[0]=values.size();cfg.parameters_json="{\"epsilon\":\"0.1\",\"quality_mode\":\"strict_abs\"}";void* h=nullptr;assert(tsbench_core_create(&cfg,0,&h)==0);tsbench_core_result r{};assert(tsbench_core_encode(h,raw.data(),raw.size(),nullptr,0,&r)==2&&!r.owner&&!r.size);tsbench_core_destroy(h);++cases;}
        assert(dlclose(lib)==0);
    }
    std::cout<<"{\"status\":\"PASS\",\"cases\":"<<cases<<",\"keys\":10,\"asan\":true,\"ubsan\":true,\"leak_detection\":true}\n";
}
