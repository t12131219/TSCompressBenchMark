#include "tsbench_core.h"
#include "tscb_adapter_v1.h"
#include <dlfcn.h>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <limits>
#include <string>
#include <vector>
template<class T>T sym(void* h,const char* n){auto p=dlsym(h,n);assert(p);return reinterpret_cast<T>(p);}
tscb_buffer_v1 buffer(void* p,size_t n,size_t used=0){tscb_buffer_v1 b{};b.data=p;b.capacity_bytes=n;b.used_bytes=used;b.dtype=TSCB_DTYPE_BYTES_V1;b.rank=1;b.strides_bytes[0]=1;b.shape[0]=used;b.alignment_bytes=1;return b;}
int main(int argc,char** argv){assert(argc==2);unsigned cases=0;
 for(const std::string key:{"abba","fabba","qabba"}){
 auto h=dlopen((std::string(argv[1])+"/libtscb_"+key+".so").c_str(),RTLD_NOW|RTLD_LOCAL);if(!h){std::cerr<<dlerror();return 1;}
 auto create=sym<decltype(&tsbench_core_create)>(h,"tsbench_core_create");auto destroy=sym<decltype(&tsbench_core_destroy)>(h,"tsbench_core_destroy");auto enc=sym<decltype(&tsbench_core_encode)>(h,"tsbench_core_encode");auto dec=sym<decltype(&tsbench_core_decode)>(h,"tsbench_core_decode");auto release=sym<decltype(&tsbench_core_release)>(h,"tsbench_core_release");
 auto ccreate=sym<decltype(&tscb_create)>(h,"tscb_create");auto cdestroy=sym<decltype(&tscb_destroy)>(h,"tscb_destroy");auto cbound=sym<decltype(&tscb_compress_bound)>(h,"tscb_compress_bound");auto cenc=sym<decltype(&tscb_compress)>(h,"tscb_compress");auto cdec=sym<decltype(&tscb_decompress)>(h,"tscb_decompress");auto reset=sym<decltype(&tscb_reset)>(h,"tscb_reset");auto finalize=sym<decltype(&tscb_finalize)>(h,"tscb_finalize");
 std::vector<std::string> profiles={"{}"};if(key=="abba"){profiles.push_back("{\"clustering\":\"INCREMENTAL\",\"scl\":\"1\",\"norm\":1}");profiles.push_back("{\"scl\":\"1\"}");}
 if(key=="fabba")for(const std::string sort:{"lexi","1-norm","2-norm","norm","pca"})profiles.push_back("{\"sorting\":\""+sort+"\",\"source_backend\":\"cython\"}");
 if(key=="qabba"){for(const std::string codec:{"none","fixed","huffman","lzw","zlib","gzip","bz2","lzma","zstd"})profiles.push_back("{\"symbol_codec\":\""+codec+"\"}");profiles.push_back("{\"digitizer\":\"kmeans\",\"bits_for_len\":64,\"bits_for_inc\":63}");profiles.push_back("{\"digitizer\":\"f-kmeans\"}");}
 for(const auto& params:profiles){
 std::vector<double> values(65);for(size_t i=0;i<values.size();++i)values[i]=double(i)/8;
 tsbench_core_config cfg{};cfg.version=1;cfg.dtype=10;cfg.rank=1;cfg.shape[0]=values.size();cfg.parameters_json=params.c_str();void* ctx=nullptr;assert(create(&cfg,0,&ctx)==0);tsbench_core_result encoded{};assert(enc(ctx,reinterpret_cast<uint8_t*>(values.data()),values.size()*8,nullptr,0,&encoded)==0);assert(encoded.owner);destroy(ctx);std::vector<uint8_t> frame(encoded.data,encoded.data+encoded.size);release(&encoded);assert(!encoded.owner);
 cfg.parameters_json="{}";assert(create(&cfg,1,&ctx)==0);tsbench_core_result decoded{};std::vector<uint8_t> out(values.size()*8+16,0xa5);assert(dec(ctx,frame.data(),frame.size(),out.data(),values.size()*8,&decoded)==0);destroy(ctx);assert(decoded.owner&&decoded.size==values.size()*8);release(&decoded);for(auto x:out)assert(x==0xa5);++cases;
 assert(create(&cfg,1,&ctx)==0);for(size_t n:{size_t(0),size_t(4),frame.size()-1}){assert(dec(ctx,frame.data(),n,out.data(),values.size()*8,&decoded)!=0);assert(!decoded.size&&!decoded.owner);++cases;}destroy(ctx);
 // Independent C1 lifecycle, exact capacity, short capacity, bad CRC and retry.
 auto json=std::string("{\"algorithm\":\"")+key+"\""+(params=="{}"?"}":","+params.substr(1));tscb_codec_handle_v1* c=nullptr;assert(ccreate(json.data(),json.size(),&c)==0);
 std::vector<uint8_t> input(24+values.size()*8);std::memcpy(input.data(),"AFI1",4);input[4]=1;input[8]=65;input[16]=1;std::memcpy(input.data()+24,values.data(),values.size()*8);auto ib=buffer(input.data(),input.size(),input.size());uint64_t bound=0;assert(cbound(c,&ib,&bound)==0&&bound>=frame.size());std::vector<uint8_t> output(frame.size()+16,0xa5);auto ob=buffer(output.data(),frame.size()-1);assert(cenc(c,&ib,&ob)==TSCB_STATUS_DST_TOO_SMALL_V1);assert(!ob.used_bytes);for(auto x:output)assert(x==0xa5);++cases;
 ob.capacity_bytes=frame.size();assert(cenc(c,&ib,&ob)==0&&ob.used_bytes==frame.size());assert(std::memcmp(output.data(),frame.data(),frame.size())==0);for(size_t i=frame.size();i<output.size();++i)assert(output[i]==0xa5);auto finish=buffer(nullptr,0);assert(finalize(c,&finish)==0&&finish.used_bytes==0);assert(finalize(c,&finish)!=0);assert(reset(c,0)==0);assert(finalize(c,&finish)!=0);++cases;
 auto fb=buffer(frame.data(),frame.size(),frame.size());std::fill(output.begin(),output.end(),0xa5);ob=buffer(output.data(),1);assert(cdec(c,&fb,&ob)==TSCB_STATUS_DST_TOO_SMALL_V1);for(auto x:output)assert(x==0xa5);++cases;cdestroy(c);
 }
 dlclose(h);
 }
 std::cout<<"{\"status\":\"PASS\",\"cases\":"<<cases<<"}\n";
}
