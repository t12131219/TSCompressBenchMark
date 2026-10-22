#include "tsbench_core.h"
#include "tscb_adapter_v1.h"
#include <dlfcn.h>
#include <cassert>
#include <cmath>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>
static void put(std::vector<unsigned char>&v,uint64_t x,size_t n){for(size_t i=0;i<n;++i){v.push_back(x);x>>=8;}}
static tscb_buffer_v1 buf(void*p,size_t cap,size_t used=0){tscb_buffer_v1 b{};b.data=p;b.capacity_bytes=cap;b.used_bytes=used;b.dtype=TSCB_DTYPE_BYTES_V1;b.rank=1;b.strides_bytes[0]=1;return b;}
int main(int argc,char**argv){assert(argc==2);const char* keys[]={"cameo","vw","pip","tp","swab","sim-piece","pmc-mean","swing-connected","dft","dwt-dct-ii"};size_t cases=0;
for(auto key:keys){std::string name=key;for(auto&c:name)if(c=='-')c='_';std::string path=std::string(argv[1])+"/libtscb_"+name+".so";void*lib=dlopen(path.c_str(),RTLD_NOW|RTLD_LOCAL);if(!lib){std::cerr<<dlerror();return 1;}
#define FN(n) auto n=reinterpret_cast<decltype(&::n)>(dlsym(lib,#n));assert(n)
FN(tsbench_core_create);FN(tsbench_core_destroy);FN(tsbench_core_bound);FN(tsbench_core_encode);FN(tsbench_core_decode);FN(tsbench_core_release);
FN(tscb_create);FN(tscb_destroy);FN(tscb_compress);FN(tscb_decompress);FN(tscb_finalize);FN(tscb_reset);
std::vector<double>values(64);for(size_t i=0;i<values.size();++i)values[i]=3+std::sin(.49*i);auto original=values;
tsbench_core_config c{};c.version=1;c.dtype=TSCB_DTYPE_F64_LE_V1;c.rank=1;c.shape[0]=values.size();c.parameters_json="{}";void*e=nullptr;assert(!tsbench_core_create(&c,0,&e));size_t bound=0;assert(!tsbench_core_bound(e,nullptr,values.size()*8,&bound));tsbench_core_result r{};assert(!tsbench_core_encode(e,reinterpret_cast<uint8_t*>(values.data()),values.size()*8,nullptr,0,&r));assert(r.owner&&r.size<=bound&&values==original);assert(!tsbench_core_destroy(e));std::vector<uint8_t>frame(r.data,r.data+r.size);tsbench_core_release(&r);assert(!r.owner);void*d=nullptr;assert(!tsbench_core_create(&c,1,&d));assert(!tsbench_core_decode(d,frame.data(),frame.size(),nullptr,0,&r));assert(r.size==values.size()*8);assert(!tsbench_core_destroy(d));for(size_t i=0;i<values.size();++i){double x;std::memcpy(&x,r.data+i*8,8);assert(std::isfinite(x));}tsbench_core_release(&r);++cases;
assert(!tsbench_core_create(&c,1,&d));for(size_t n=0;n<frame.size();n+=std::max(size_t(1),frame.size()/32)){assert(tsbench_core_decode(d,frame.data(),n,nullptr,0,&r)!=0);assert(!r.owner&&!r.size);++cases;}assert(!tsbench_core_destroy(d));
std::string conf="{\"algorithm\":\""+std::string(key)+"\"}";tscb_codec_handle_v1*h=nullptr;assert(!tscb_create(conf.data(),conf.size(),&h));std::vector<uint8_t>input{'C','M','I','1'};put(input,1,4);put(input,values.size(),8);put(input,1,8);auto p=reinterpret_cast<uint8_t*>(values.data());input.insert(input.end(),p,p+values.size()*8);auto src=buf(input.data(),input.size(),input.size());std::vector<uint8_t>out(frame.size(),0xa5);auto dst=buf(out.data(),out.size()-1);assert(tscb_compress(h,&src,&dst)==TSCB_STATUS_DST_TOO_SMALL_V1);assert(!dst.used_bytes);for(auto x:out)assert(x==0xa5);dst.capacity_bytes=out.size();assert(!tscb_compress(h,&src,&dst));assert(out==frame);auto finish=buf(nullptr,0);assert(!tscb_finalize(h,&finish));assert(tscb_finalize(h,&finish)!=0);assert(!tscb_reset(h,0));assert(tscb_finalize(h,&finish)!=0);assert(!tscb_destroy(h));++cases;
assert(!tscb_create(conf.data(),conf.size(),&h));src=buf(frame.data(),frame.size(),frame.size());std::vector<uint8_t>decoded(values.size()*8,0xcc);dst=buf(decoded.data(),decoded.size()-1);assert(tscb_decompress(h,&src,&dst)==TSCB_STATUS_DST_TOO_SMALL_V1);for(auto x:decoded)assert(x==0xcc);dst.capacity_bytes=decoded.size();assert(!tscb_decompress(h,&src,&dst));assert(!tscb_destroy(h));++cases;
dlclose(lib);}
std::cout<<"PASS "<<cases<<" cases, 10 bindings\n";
}
