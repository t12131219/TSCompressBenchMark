#include "alp_port.h"
#include <algorithm>
#include <cstring>
#include <vector>
extern "C" int LLVMFuzzerTestOneInput(const uint8_t* data,size_t size) {
    std::vector<uint8_t> output(1<<17,0x55);size_t used=0,consumed=0;uint64_t n=0;uint8_t d=0,m=0;
    alp_port_decode(data,size,output.data(),output.size(),&used,&consumed,&n,&d,&m);
    // Recompute integrity on mutated small frames so fuzzing reaches length,
    // width, dictionary and exception validation behind the checksum.
    if(size>=32 && size<=32768) {
        std::vector<uint8_t> frame(data,data+size);uint32_t crc=~0u;
        for(size_t i=0;i<size;++i) {
            if(i>=28 && i<32)continue;
            crc^=frame[i];for(int j=0;j<8;++j)crc=(crc>>1)^(0xedb88320u&(0u-(crc&1)));
        }
        crc=~crc;for(int i=0;i<4;++i)frame[28+i]=crc>>(i*8);
        alp_port_decode(frame.data(),frame.size(),output.data(),output.size(),&used,&consumed,&n,&d,&m);
    }
    if(size && (data[0]&7)==0) {
        const uint8_t dtype=(data[0]&8)?4:8, mode=(data[0]&16)?1:0;
        const size_t count=std::min(size_t(2049),(size-1)/dtype);size_t bound=0,encoded=0;
        alp_port_bound(count,dtype,mode,&bound);std::vector<uint8_t> f(bound),out(count*dtype+1);
        if(alp_port_encode(data+1,count,dtype,mode,f.data(),f.size(),&encoded)) __builtin_trap();
        if(alp_port_decode(f.data(),encoded,out.data(),out.size(),&used,&consumed,&n,&d,&m)||used!=count*dtype||std::memcmp(data+1,out.data(),used)) __builtin_trap();
    }
    return 0;
}
