// Research driver for upstream primitives and historical 1D ablations.
// Not installed and not a safe decoder API for untrusted streams.
#include <cstddef>
#include "delta.h"
#include "predict.h"
#include "univariate_8b.h"
#include "native_alloc.hpp"
#include <vector>
#include <string>
#include <iostream>
#include <cstring>
#include <random>
int main(int argc,char**argv){if(argc!=7)return 2;try{
 std::string mode=argv[1];int bits=std::stoi(argv[2]),d=std::stoi(argv[3]),n=std::stoi(argv[4]),pattern=std::stoi(argv[5]),inplace=std::stoi(argv[6]);
 sz_mem::scope cleanup;std::mt19937 r(171017);std::vector<uint16_t>a(n+8192),b(n*3+8192),o(n+8192);
 unsigned char* in=(unsigned char*)a.data();for(int i=0;i<n*(bits/8);i++)in[i]=pattern==0?0:pattern==1?i/13:r();
 int64_t enc=-1,dec=-1;
#define PRIM(NAME,W,U,I) if(mode=="primitive-" #NAME && bits==W){enc=encode_##NAME##_rowmajor_##W##b((const U*)a.data(),n,(I*)b.data(),d,!inplace);if(inplace){memcpy(o.data(),b.data(),n*sizeof(U));dec=decode_##NAME##_rowmajor_inplace_##W##b((U*)o.data(),n,d);}else{dec=decode_##NAME##_rowmajor_##W##b((const I*)b.data(),(U*)o.data());}}
 PRIM(delta,8,uint8_t,int8_t) PRIM(delta,16,uint16_t,int16_t)
 PRIM(doubledelta,8,uint8_t,int8_t) PRIM(doubledelta,16,uint16_t,int16_t)
 PRIM(xff,8,uint8_t,int8_t) PRIM(xff,16,uint16_t,int16_t)
#undef PRIM
#define LEGACY(NAME) if(mode==#NAME&&bits==8&&!inplace){enc=compress8b_##NAME((uint8_t*)a.data(),n,(int8_t*)b.data(),true);dec=decompress8b_##NAME((int8_t*)b.data(),(uint8_t*)o.data());}
 LEGACY(delta) LEGACY(doubledelta) LEGACY(dyndelta) LEGACY(delta_rle) LEGACY(delta_rle2) LEGACY(online) LEGACY(delta_online) LEGACY(delta2_online)
#undef LEGACY
 if(mode=="delta_simple"&&bits==8&&!inplace){enc=compress8b_delta_simple((uint8_t*)a.data(),n,(int8_t*)b.data(),true);dec=decompress8b_delta_simple((int8_t*)b.data(),(uint8_t*)o.data(),0);}
 // Distinguish modern delta/doubledelta primitive names from historical codecs.
 bool ok=enc>=0&&dec==n&&!memcmp(a.data(),o.data(),n*(bits/8));
 std::cout<<"{\"mode\":\""<<mode<<"\",\"bits\":"<<bits<<",\"dims\":"<<d<<",\"n\":"<<n<<",\"encoded\":"<<enc<<",\"decoded\":"<<dec<<",\"roundtrip\":"<<(ok?"true":"false")<<"}\n";return ok?0:1;
}catch(...){return 3;}}
