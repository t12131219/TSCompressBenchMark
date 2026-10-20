#include "sprintz_port.h"
#include <cstddef>
#include <cstdint>
#include <vector>
#include <cstdlib>
extern "C" int LLVMFuzzerTestOneInput(const uint8_t*data,size_t size){
 if(size<8)return 0;sz_config c{data[0]&1?16u:8u,unsigned(data[1]&1),unsigned(data[2]&1),unsigned(data[3]%6),unsigned(data[4]%128+1)};
 size_t n=(size_t(data[5])|(size_t(data[6])<<8));n-=n%(c.width/8);std::vector<uint8_t>out(n+64,0x5a);size_t z=999;
 int rc=sz_decode(&c,data+8,size-8,n,out.data(),n,&z);
 if(rc&&z)std::abort();if(!rc&&z!=n)std::abort();
 for(size_t i=n;i<out.size();i++)if(out[i]!=0x5a)std::abort();
 if(rc)for(size_t i=0;i<n;i++)if(out[i]!=0x5a)std::abort();return 0;
}
