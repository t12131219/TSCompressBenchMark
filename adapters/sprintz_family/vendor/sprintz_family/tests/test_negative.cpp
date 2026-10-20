#include "sprintz_port.h"
#include <vector>
#include <random>
#include <thread>
#include <atomic>
#include <iostream>
#include <cstring>
#include <stdexcept>
#define CHECK(X) do{if(!(X))throw std::runtime_error(#X);}while(0)
int main(){try{
 std::mt19937 r(20261017);size_t mutations=0,oom=0,large=0;
 for(unsigned bits:{8,16})for(unsigned fire:{0,1})for(unsigned h:{0,1})for(unsigned d:{1,2,3,5,17,65,128})for(unsigned path:{0,1,2,3,4,5}){
  sz_config c{bits,fire,h,path,d};size_t bound;if(sz_bound(&c,512,&bound))continue;
  std::vector<unsigned char> in(512);for(auto&v:in)v=r();std::vector<unsigned char> enc(bound),out(512+32,0x5a);size_t z=0,k=0;
  auto pristine=in;
  CHECK(sz_encode(&c,in.data(),in.size(),enc.data(),enc.size(),&z)==0);CHECK(in==pristine);
  {std::vector<unsigned char> guard(bound,0x37);size_t q=99;
   CHECK(sz_encode(&c,in.data(),in.size(),guard.data(),z-1,&q)==SZ_CAPACITY&&q==0);
   for(auto v:guard)CHECK(v==0x37);
   CHECK(sz_decode(&c,enc.data(),z,512,guard.data(),511,&q)==SZ_CAPACITY&&q==0);
   for(auto v:guard)CHECK(v==0x37);}
  auto attempt=[&](const std::vector<unsigned char>&data,size_t len){
   std::fill(out.begin(),out.end(),0x5a);k=999;
   int rc=sz_decode(&c,data.data(),len,512,out.data(),512,&k);
   if(rc!=0){CHECK(k==0);for(auto a:out)CHECK(a==0x5a);}else CHECK(k==512);
   for(size_t i=512;i<out.size();i++)CHECK(out[i]==0x5a);mutations++;
  };
  for(size_t j=0;j<z;j+=(z/25+1))attempt(enc,j);
  for(size_t j=0;j<80;j++){auto m=enc;size_t at=r()%z;m[at]^=1u<<(r()%8);attempt(m,z);}
  for(size_t j=0;j<30;j++){std::vector<unsigned char> m(r()%600+1);for(auto&v:m)v=r();attempt(m,m.size());}
  for(int fail=0;fail<80;fail++){
   std::fill(out.begin(),out.end(),0x5a);k=999;sz_test_fail_allocation(fail);
   int rc=sz_decode(&c,enc.data(),z,512,out.data(),512,&k);sz_test_fail_allocation(-1);
   if(rc==0)break;CHECK(rc==SZ_MEMORY&&k==0);for(auto a:out)CHECK(a==0x5a);oom++;
  }
  for(int fail=0;fail<80;fail++){
   std::vector<unsigned char> target(bound,0x5a);k=999;sz_test_fail_allocation(fail);
   int rc=sz_encode(&c,in.data(),512,target.data(),target.size(),&k);sz_test_fail_allocation(-1);
   if(rc==0)break;CHECK(rc==SZ_MEMORY&&k==0);for(auto a:target)CHECK(a==0x5a);oom++;
  }
  // Include exact max byte limit, long RLE (extension byte), incomplete groups.
  for(int pattern:{0,1}){
   std::vector<unsigned char> raw(65536);for(auto&v:raw)v=pattern?r():0;
   CHECK(sz_bound(&c,raw.size(),&bound)==0);enc.resize(bound);out.resize(raw.size()+64);z=0;
   CHECK(sz_encode(&c,raw.data(),raw.size(),enc.data(),enc.size(),&z)==0);
   CHECK(sz_decode(&c,enc.data(),z,raw.size(),out.data(),raw.size(),&k)==0);
   CHECK(k==raw.size()&&!std::memcmp(raw.data(),out.data(),k));large++;
  }
 }
 // Crafted leading empty RLE slot: source would read dest-ndims.
 {sz_config cfg{8,0,0,0,1};unsigned char bad[]={1,0,0,0,0,0,1,0,0,0,1};
  unsigned char out[8]={};size_t made=99;CHECK(sz_decode(&cfg,bad,sizeof bad,8,out,8,&made)==SZ_MALFORMED&&made==0);}
 // Overlap, caller alignment, immutable input and independent thread-local calls.
 std::atomic<bool> good{true};auto worker=[&](){try{for(int i=0;i<50;i++){
  sz_config c{16,1,unsigned(i%2),0,3};std::vector<unsigned char> raw(2050,0x55),buf(20000),ref=raw;size_t z=0,k=0;
  std::memcpy(buf.data()+1,raw.data(),raw.size());CHECK(sz_encode(&c,buf.data()+1,raw.size(),buf.data()+1,buf.size()-1,&z)==0);
  CHECK(sz_decode(&c,buf.data()+1,z,raw.size(),buf.data()+1,buf.size()-1,&k)==0);CHECK(k==raw.size()&&!memcmp(buf.data()+1,ref.data(),k));
 }}catch(...){good=false;}};
 std::thread a(worker),b(worker),c(worker),d(worker);a.join();b.join();c.join();d.join();CHECK(good);
 sz_config invalid{32,0,0,0,0};size_t k=9;CHECK(sz_bound(&invalid,2,&k)==SZ_ARGUMENT&&k==0);
 for(sz_config bad:std::vector<sz_config>{{8,0,0,0,0},{8,0,0,0,129},{16,0,0,2,3},{8,0,0,2,5},{16,1,0,5,1},{8,0,2,0,1},{8,0,0,6,1}}){size_t z=99;CHECK(sz_bound(&bad,2,&z)==SZ_ARGUMENT&&z==0);}
 {sz_config valid{16,0,0,0,1};size_t z=99;CHECK(sz_bound(&valid,65538,&z)==SZ_ARGUMENT&&z==0);CHECK(sz_bound(&valid,1,&z)==SZ_ARGUMENT&&z==0);}
 std::cout<<"{\"mutations\":"<<mutations<<",\"oom_failures\":"<<oom<<",\"max_size_cases\":"<<large<<",\"threads\":4,\"status\":\"PASS\"}\n";
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
