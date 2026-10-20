#include "tsbench_core.h"
#include "tscb_adapter_v1.h"
#include <dlfcn.h>
#include <vector>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#define NEED(x) do{if(!(x)){std::fprintf(stderr,"failed line %d: %s\n",__LINE__,#x);std::abort();}}while(0)
template<class T>T sym(void* lib,const char* name){auto p=dlsym(lib,name);NEED(p);return reinterpret_cast<T>(p);}
int main(int argc,char** argv){size_t cases=0;
 for(int arg=1;arg<argc;++arg){void* lib=dlopen(argv[arg],RTLD_NOW|RTLD_LOCAL);NEED(lib);
  auto create=sym<decltype(&tsbench_core_create)>(lib,"tsbench_core_create");auto destroy=sym<decltype(&tsbench_core_destroy)>(lib,"tsbench_core_destroy");auto bound=sym<decltype(&tsbench_core_bound)>(lib,"tsbench_core_bound");auto enc=sym<decltype(&tsbench_core_encode)>(lib,"tsbench_core_encode");auto dec=sym<decltype(&tsbench_core_decode)>(lib,"tsbench_core_decode");auto release=sym<decltype(&tsbench_core_release)>(lib,"tsbench_core_release");auto fault=sym<void(*)(int64_t)>(lib,"sz_test_fail_allocation");
  for(unsigned width:{1u,2u})for(size_t dims:{1u,2u,3u,128u})for(size_t rows:{0u,1u,129u}){
   const size_t size=rows*dims*width;std::vector<uint8_t> input(size+1);for(size_t i=0;i<size;++i)input[i]=static_cast<uint8_t>(i*181+127);
   tsbench_core_config cfg{};cfg.version=1;cfg.dtype=width==1?TSCB_DTYPE_U8_V1:TSCB_DTYPE_I16_LE_V1;cfg.rank=2;cfg.shape[0]=rows;cfg.shape[1]=dims;cfg.parameters_json="{\"path\":1}";
   void *e=nullptr,*d=nullptr;NEED(create(&cfg,0,&e)==0);cfg.parameters_json="{}";NEED(create(&cfg,1,&d)==0);size_t capacity=0;NEED(bound(e,input.data(),size,&capacity)==0);std::vector<uint8_t> stream(capacity,0xa5);tsbench_core_result r{};
   NEED(enc(e,input.data(),size,stream.data(),23,&r)==3&&r.size==0);for(auto b:stream)NEED(b==0xa5);
   NEED(enc(e,input.data(),size,stream.data(),stream.size(),&r)==0&&!r.owner);stream.resize(r.size);release(&r);release(&r);
   std::vector<uint8_t> out(size+1,0xcc);NEED(dec(d,stream.data(),stream.size()-1,out.data(),size,&r)!=0&&!r.size);for(auto b:out)NEED(b==0xcc);
   auto bad=stream;bad[10]=1;NEED(dec(d,bad.data(),bad.size(),out.data(),size,&r)!=0);for(auto b:out)NEED(b==0xcc);
   if(size)NEED(dec(d,stream.data(),stream.size(),out.data(),size-1,&r)==3);
   NEED(dec(d,stream.data(),stream.size(),out.data(),size,&r)==0&&r.size==size&&!r.owner);NEED(std::memcmp(out.data(),input.data(),size)==0&&out.back()==0xcc);release(&r);
   // Short native copy paths perform no tracked scratch allocation.
   if(size/width>=128){fault(0);std::vector<uint8_t> failed(capacity,0xa5);NEED(enc(e,input.data(),size,failed.data(),failed.size(),&r)!=0&&r.size==0);for(auto b:failed)NEED(b==0xa5);fault(-1);}
   NEED(destroy(e)==0&&destroy(d)==0);++cases;
  }
  // Reject oversized input and too many dimensions without native allocations.
  for(size_t dims:{128u,129u}){tsbench_core_config cfg{};cfg.version=1;cfg.dtype=TSCB_DTYPE_U16_LE_V1;cfg.rank=2;cfg.shape[0]=65536;cfg.shape[1]=dims;cfg.parameters_json="{}";void* h=nullptr;NEED(create(&cfg,0,&h)!=0&&!h);}
  dlclose(lib);
 }
 std::printf("{\"binding_cases\":%zu,\"status\":\"PASS\"}\n",cases);
}
