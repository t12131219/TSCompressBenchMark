// SPDX-License-Identifier: MIT
#include "tscb_adapter_v1.h"
#include "gorilla/gorilla.hpp"
#include <cassert>
#include <cstring>
#include <iostream>
#include <random>
#include <vector>

static tscb_buffer_v1 buffer(std::vector<unsigned char>& v, std::size_t capacity, std::size_t used=0) {
    tscb_buffer_v1 b{}; b.data=v.data(); b.capacity_bytes=capacity; b.used_bytes=used;
    b.dtype=TSCB_DTYPE_BYTES_V1; b.rank=1; b.shape[0]=used; b.strides_bytes[0]=1; b.alignment_bytes=1;
    return b;
}
static void put(unsigned char* p, std::uint64_t v) { for(unsigned i=0;i<8;++i)p[i]=static_cast<unsigned char>(v>>(i*8)); }
int main() {
    std::mt19937_64 rng(20261015); unsigned roundtrips=0, rejected=0;
    for (auto path : {gorilla::Path::Canonical,gorilla::Path::Optimized}) {
        const char* config=path==gorilla::Path::Canonical ? "{\"path\":\"canonical\"}" : "{\"path\":\"optimized\"}";
        tscb_codec_handle_v1* h=nullptr; assert(tscb_create(config,std::strlen(config),&h)==0 && h);
        for (std::size_t n : {0,1,2,7,8,17,65534,65535}) {
            std::vector<gorilla::Sample> samples(n); std::vector<unsigned char> bytes(n*16);
            for(std::size_t i=0;i<n;++i) { const auto t=rng(),v=rng(); samples[i]={gorilla::signed_bits(t),v};put(bytes.data()+16*i,t);put(bytes.data()+16*i+8,v); }
            const auto before=bytes; auto src=buffer(bytes,bytes.size(),bytes.size()); std::uint64_t bound=0;
            assert(tscb_reset(h,0)==0); assert(tscb_compress_bound(h,&src,&bound)==0);
            std::vector<unsigned char> raw(bound+16,0xa5); auto out=buffer(raw,bound-1,1);
            assert(tscb_compress(h,&src,&out)==TSCB_STATUS_DST_TOO_SMALL_V1 && out.used_bytes==1);
            for(auto x:raw)assert(x==0xa5);
            out.capacity_bytes=bound;assert(tscb_compress(h,&src,&out)==0); assert(bytes==before);
            const auto expected=gorilla::encode(samples.data(),n,path);assert(out.used_bytes==expected.size());assert(std::memcmp(raw.data(),expected.data(),expected.size())==0);
            for(std::size_t i=bound;i<raw.size();++i)assert(raw[i]==0xa5);
            assert(tscb_compress(h,&src,&out)!=0);
            std::vector<unsigned char> empty; auto fin=buffer(empty,0);
            assert(tscb_finalize(h,&fin)==0 && fin.used_bytes==0);assert(tscb_finalize(h,&fin)==0 && fin.used_bytes==0);
            auto encoded=buffer(raw,out.used_bytes,out.used_bytes);
            std::vector<unsigned char> decoded(bytes.size()+16,0x5a);auto dest=buffer(decoded,bytes.size(),0);
            if(n) {dest.capacity_bytes--;assert(tscb_decompress(h,&encoded,&dest)==TSCB_STATUS_DST_TOO_SMALL_V1 && dest.used_bytes==0);dest.capacity_bytes++;for(auto x:decoded)assert(x==0x5a);}
            assert(tscb_decompress(h,&encoded,&dest)==0 && dest.used_bytes==bytes.size());
            if(n)assert(std::memcmp(decoded.data(),bytes.data(),bytes.size())==0);
            for(std::size_t i=bytes.size();i<decoded.size();++i)assert(decoded[i]==0x5a);
            ++roundtrips;
        }
        std::vector<unsigned char> data(65535*16+16,0x3c);
        for (unsigned trial=0;trial<10000;++trial) {
            std::vector<unsigned char> hostile(rng()%513);
            for(auto& x:hostile)x=static_cast<unsigned char>(rng());
            auto src=buffer(hostile,hostile.size(),hostile.size());const auto before=hostile;
            auto out=buffer(data,65535*16,3);
            assert(tscb_decompress(h,&src,&out)!=0 && out.used_bytes==3); assert(hostile==before);
            for(auto x:data)assert(x==0x3c);
            ++rejected;
        }
        std::vector<unsigned char> too_many(65536*16);auto src=buffer(too_many,too_many.size(),too_many.size());std::uint64_t bound=123;
        assert(tscb_compress_bound(h,&src,&bound)==TSCB_STATUS_UNSUPPORTED_V1 && bound==123);
        src.reserved=1;assert(tscb_compress_bound(h,&src,&bound)==TSCB_STATUS_INVALID_ARGUMENT_V1);
        assert(tscb_reset(h,1)==TSCB_STATUS_UNSUPPORTED_V1);assert(tscb_destroy(h)==0);
    }
    std::cout<<"PASS: "<<roundtrips<<" direct-core/ABI roundtrips; "<<rejected<<" hostile chunks rejected; bound/canary/reset/finalize/input invariance\n";
}
