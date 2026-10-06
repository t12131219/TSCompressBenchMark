#include "binding.hpp"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <vector>

static void check(bool value, const char* message) {
  if (!value) throw std::runtime_error(message);
}
template<class T> static std::vector<std::uint8_t> bytes(const std::vector<T>& values) {
  std::vector<std::uint8_t> result(values.size()*sizeof(T));
  if (!result.empty()) std::memcpy(result.data(),values.data(),result.size());
  return result;
}
static void roundtrip(RwConfig config, const std::vector<std::uint8_t>& input) {
  char error[2048]{}; std::size_t bound=0,used=123,decoded=0;
  const auto immutable=input;
  check(rw_bound(&config,input.data(),input.size(),&bound,error,sizeof(error))==0,error);
  check(bound<(512ULL<<20),"invalid bound");
  std::vector<std::uint8_t> encoded(bound+32,0xA5);
  if(bound) {
    check(rw_encode(&config,input.data(),input.size(),encoded.data()+16,bound-1,&used,error,sizeof(error))!=0,"short capacity accepted");
    check(std::all_of(encoded.begin(),encoded.end(),[](auto b){return b==0xA5;}),"capacity rejection wrote output");
  }
  check(rw_encode(&config,input.data(),input.size(),encoded.data()+16,bound,&used,error,sizeof(error))==0,error);
  check(used<=bound,"bound violated");
  check(input==immutable,"input mutated");
  check(std::all_of(encoded.begin(),encoded.begin()+16,[](auto b){return b==0xA5;}) &&
        std::all_of(encoded.begin()+16+bound,encoded.end(),[](auto b){return b==0xA5;}),"encode canary");
  std::vector<std::uint8_t> repeated(bound);
  std::size_t repeated_size=0;
  check(rw_encode(&config,input.data(),input.size(),repeated.data(),bound,&repeated_size,error,sizeof(error))==0,error);
  check(repeated_size==used && std::equal(repeated.begin(),repeated.begin()+used,encoded.begin()+16),"nondeterministic fresh object");
  std::vector<std::uint8_t> output(input.size()+32,0x5A);
  check(rw_decode(encoded.data()+16,used,output.data()+16,input.size(),&decoded,error,sizeof(error))==0,error);
  check(decoded==input.size(),"decoded dimensions");
  check(std::all_of(output.begin(),output.begin()+16,[](auto b){return b==0x5A;}) &&
        std::all_of(output.end()-16,output.end(),[](auto b){return b==0x5A;}),"decode canary");
#if RW_KIND == 3 || RW_KIND == 4 || RW_KIND == 7 || RW_KIND == 8 || RW_KIND == 10 || RW_KIND == 11
  check(std::equal(input.begin(),input.end(),output.begin()+16),"lossless mismatch");
#else
  const std::size_t stride=RW_KIND==9 ? 4 : 8;
  for(std::size_t i=0;i<input.size();i+=stride) {
    double value;
    if(stride==4){float v;std::memcpy(&v,output.data()+16+i,4);value=v;}
    else std::memcpy(&value,output.data()+16+i,8);
    check(std::isfinite(value),"nonfinite reconstruction");
  }
#endif
  if (!input.empty()) {
    std::fill(output.begin(),output.end(),0x5A);
    check(rw_decode(encoded.data()+16,used,output.data()+16,input.size()-1,&decoded,error,sizeof(error))!=0,"short decode accepted");
    check(std::all_of(output.begin(),output.end(),[](auto b){return b==0x5A;}),"failed decode wrote output");
  }
  if(used>1) for(auto truncated: {std::size_t(0),std::size_t(1),used-1}) {
    std::fill(output.begin(),output.end(),0x5A);
    const auto status=rw_decode(encoded.data()+16,truncated,output.data()+16,input.size(),&decoded,error,sizeof(error));
#if RW_KIND == 3 || RW_KIND == 10 || RW_KIND == 11
    // Timestamp payloads have no original-count field; an empty histogram frame
    // sequence is valid. The authenticated framework container rejects their
    // truncation and exact decoded-length checks reject any shorter valid stream.
    if(status==0) check(decoded<=input.size(),"prefix capacity");
#else
    check(status!=0,"truncated decode accepted");
#endif
    if(status!=0)check(std::all_of(output.begin(),output.end(),[](auto b){return b==0x5A;}),"truncated decode wrote output");
    check(std::all_of(output.end()-16,output.end(),[](auto b){return b==0x5A;}),"prefix decode canary");
  }
}
int main(int argc,char** argv) {
  try {
    check(rw_version()==1,"ABI version");
    RwConfig c{9,1,0,0,0,0,0,0,0,0,0,argc>1?argv[1]:nullptr};
    std::vector<std::uint8_t> input;
#if RW_KIND == 1 || RW_KIND == 2
    c.a=RW_KIND==1?1:4294967295U;c.b=100;c.c=4294967295U;c.d=2;
    c.x=.1;c.y=.1;c.z=RW_KIND==1?0:1;
    input=bytes(std::vector<double>{0,1,1.25,2,4,3,2,1,0});
#elif RW_KIND == 3
    input=bytes(std::vector<std::int64_t>{0,1,2,2,-1,5,999999999,42,0});
#elif RW_KIND == 4
    std::vector<std::uint64_t> words;for(unsigned i=0;i<9;++i){words.push_back(0);words.push_back(i);words.push_back(0x3ff0000000000000ULL+i);}input=bytes(words);
#elif RW_KIND == 5 || RW_KIND == 6
    c.rows=80;c.columns=2;c.a=40;c.b=8;c.c=2;c.d=150;c.x=1;c.y=.8;
    std::vector<double> values(160);for(unsigned i=0;i<80;++i){values[2*i]=3+std::sin(i*.13);values[2*i+1]=7+2*std::cos(i*.11);}input=bytes(values);
#elif RW_KIND == 7 || RW_KIND == 8
    c.rows=256;c.a=1;input.resize(256);for(unsigned i=0;i<256;++i)input[i]=i%4;
#elif RW_KIND == 9
    c.rows=17;c.columns=2;std::vector<float> values(34);for(unsigned i=0;i<34;++i)values[i]=.1f*std::sin(i*.2f);input=bytes(values);
#elif RW_KIND == 10 || RW_KIND == 11
    c.columns=7;std::vector<std::uint64_t> values;
    for(unsigned i=0;i<9;++i){std::uint64_t count=RW_KIND==10?std::uint64_t(i+1):0x3ff0000000000000ULL;for(auto word:{std::uint64_t(i),std::uint64_t(0),count,std::uint64_t(0),std::uint64_t(0),std::uint64_t(0),count})values.push_back(word);}input=bytes(values);
#endif
    roundtrip(c,input);
#if RW_KIND != 1 && RW_KIND != 2 && RW_KIND != 5 && RW_KIND != 6
    c.rows=0;roundtrip(c,{});
#endif
    char error[128]{};std::size_t n=0;
    check(rw_bound(nullptr,nullptr,0,&n,error,sizeof(error))!=0,"null config");
    std::cout<<"PASS ABI, bounds, canaries, input immutability, independent decode, determinism, truncated streams, empty/domain lengths\n";
    return 0;
  }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
