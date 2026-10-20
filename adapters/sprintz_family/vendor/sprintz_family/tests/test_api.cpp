#include "sprintz_port.h"
#include <vector>
#include <random>
#include <thread>
#include <iostream>
#include <stdexcept>
#include <cstring>
#define REQUIRE(X) do{if(!(X))throw std::runtime_error(#X);}while(0)
int main(){try{
 std::mt19937 rng(171017);size_t cases=0;
 for(unsigned bits:{8,16})for(unsigned fire:{0,1})for(unsigned h:{0,1})for(unsigned d=1;d<=128;d++)for(unsigned path:{0,1,2,3,4,5}){
  sz_config c{bits,fire,h,path,d};size_t bd;if(sz_bound(&c,0,&bd))continue;
  for(size_t n:{size_t(0),size_t(1),size_t(7),size_t(127),size_t(128),size_t(129),size_t(255),size_t(1025)})for(int pattern=0;pattern<3;pattern++){
   std::vector<unsigned char> in(n*(bits/8));for(size_t i=0;i<in.size();i++)in[i]=pattern==0?0:pattern==1?i/17:rng();
   REQUIRE(sz_bound(&c,in.size(),&bd)==0);std::vector<unsigned char> enc(bd,0xa5),out(in.size()+64,0x59);size_t z=0,m=0;
   int er=sz_encode(&c,in.data(),in.size(),enc.data(),enc.size(),&z);
   if(er){std::cerr<<"encode bits/fire/h/d/path/n/p "<<bits<<' '<<fire<<' '<<h<<' '<<d<<' '<<path<<' '<<n<<' '<<pattern<<" rc="<<er<<'\n';return 1;}
   int dr=sz_decode(&c,enc.data(),z,in.size(),out.data(),in.size(),&m);
   if(dr||m!=in.size()||(m && memcmp(in.data(),out.data(),m))){std::cerr<<"decode bits/fire/h/d/path/n/p "<<bits<<' '<<fire<<' '<<h<<' '<<d<<' '<<path<<' '<<n<<' '<<pattern<<" rc="<<dr<<" z="<<z<<'\n';return 1;}
   for(size_t i=m;i<out.size();i++)REQUIRE(out[i]==0x59);
   if(z>0){std::vector<unsigned char> untouched(7,0x73);size_t k=99;int r=sz_encode(&c,in.data(),in.size(),untouched.data(),0,&k);REQUIRE(r==SZ_CAPACITY&&k==0);for(auto a:untouched)REQUIRE(a==0x73);}
   cases++;
  }
 }
 std::cout<<"{\"roundtrip_cases\":"<<cases<<",\"status\":\"PASS\"}\n";
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
