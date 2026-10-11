#include "binding.hpp"
#include <cstring>
#include <cmath>
#include <fstream>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <vector>
#if RW_KIND == 1
#include "abba.hpp"
#elif RW_KIND == 2
#include "fabba.hpp"
#elif RW_KIND == 7
#include "deepzip/deepzip.hpp"
#elif RW_KIND == 8
#include "dzip.hpp"
#endif
using Bytes = std::vector<std::uint8_t>;
template<class T> static std::vector<T> values(const std::uint8_t* p, std::size_t bytes) {
  if(bytes % sizeof(T)) throw std::invalid_argument("invalid input length");
  std::vector<T> v(bytes/sizeof(T));
  if(bytes) std::memcpy(v.data(), p, bytes);
  return v;
}
template<class T> static Bytes raw(const std::vector<T>& v) {
  Bytes b(v.size()*sizeof(T)); if(!b.empty()) std::memcpy(b.data(),v.data(),b.size()); return b;
}
static void valid(const RwConfig& c, std::size_t size, std::size_t stride) {
  if(c.rows > 16777216 || !c.columns || c.columns > 65535 ||
     c.rows > 16777216/c.columns || size != c.rows*c.columns*stride)
    throw std::invalid_argument("input dimensions exceed contract");
}
#if RW_KIND == 7 || RW_KIND == 8
static Bytes read_model(const char* path) {
  if(!path) throw std::invalid_argument("model required");
  std::ifstream f(path,std::ios::binary|std::ios::ate);
  if(!f || f.tellg()<0 || f.tellg()>static_cast<std::streamoff>(512ULL<<20))
    throw std::invalid_argument("model missing or too large");
  Bytes b(static_cast<std::size_t>(f.tellg())); f.seekg(0);
  if(!b.empty() && !f.read(reinterpret_cast<char*>(b.data()),b.size())) throw std::runtime_error("model read failed");
  return b;
}
#endif
#if RW_KIND == 8
static unsigned input_alphabet(const std::uint8_t* p,std::size_t size) {
  if(!size)return 256;
  bool present[256]{};for(std::size_t i=0;i<size;++i)present[p[i]]=true;
  unsigned count=0;for(bool value:present)count+=value;
  return count;
}
#endif
static std::size_t bound(const RwConfig& c,const std::uint8_t* p,std::size_t size) {
#if RW_KIND == 1
  valid(c,size,8); return abba::max_encoded_size(c.rows);
#elif RW_KIND == 2
  valid(c,size,8); return fabba::max_encoded_size(c.rows);
#elif RW_KIND == 7
  auto model=deepzip::Model::load(read_model(c.model)); deepzip::Config config;
  config.lanes=c.a; for(unsigned i=0;i<model.alphabet_size();++i) config.alphabet.push_back(static_cast<std::uint8_t>(i));
  return deepzip::compress_bound(model,size,config);
#elif RW_KIND == 8
  valid(c,size,1);
  auto model=c.model && *c.model ? dzip::Network::load(read_model(c.model)) : dzip::Network::create(input_alphabet(p,size),c.mode?dzip::ModelProfile::combined_cpu:dzip::ModelProfile::bootstrap_cpu,c.seed);
  return dzip::compress_bound(size,model);
#endif
}
static Bytes encode(const RwConfig& c,const std::uint8_t* p,std::size_t size) {
#if RW_KIND == 1
  auto v=values<double>(p,size); abba::Config s; s.compression_tolerance=c.x; s.digitization_tolerance=c.y;
  s.min_k=c.a;s.max_k=c.b;s.max_len=c.c;s.norm=c.d;s.scl=c.z;
  s.clustering=c.mode?abba::Config::ClusteringMethod::Incremental:abba::Config::ClusteringMethod::Kmeans;
  return abba::encode(v.data(),v.size(),s);
#elif RW_KIND == 2
  auto v=values<double>(p,size); fabba::Config s;s.tolerance=c.x;s.alpha=c.y;s.scl=c.z;s.max_len=c.a;s.threads=1;
  return fabba::encode(v.data(),v.size(),s);
#elif RW_KIND == 7
  auto model=deepzip::Model::load(read_model(c.model));deepzip::Config s;s.lanes=c.a;
  for(unsigned i=0;i<model.alphabet_size();++i)s.alphabet.push_back(static_cast<std::uint8_t>(i));
  return deepzip::compress(model,Bytes(p,p+size),s).bytes;
#elif RW_KIND == 8
  auto model=c.model && *c.model ? dzip::Network::load(read_model(c.model)) : dzip::Network::create(input_alphabet(p,size),c.mode?dzip::ModelProfile::combined_cpu:dzip::ModelProfile::bootstrap_cpu,c.seed);
  return dzip::compress(Bytes(p,p+size),model,c.mode?dzip::Mode::combined:dzip::Mode::bootstrap).bytes;
#endif
}
static Bytes decode(const std::uint8_t* p,std::size_t size,std::size_t capacity) {
#if RW_KIND == 1
  return raw(abba::decode(p,size));
#elif RW_KIND == 2
  return raw(fabba::decode(p,size));
#elif RW_KIND == 7
  return deepzip::decompress(Bytes(p,p+size));
#elif RW_KIND == 8
  return dzip::decompress(Bytes(p,p+size));
#endif
}
static int failure(char* error,std::size_t cap,const char* message) {if(error && cap){std::strncpy(error,message,cap-1);error[cap-1]=0;}return 4;}
extern "C" std::uint32_t rw_version(){return 1;}
extern "C" const char* rw_algorithm(){return RW_KEY;}
extern "C" int rw_model_alphabet(const char* path,std::uint32_t* alphabet,char* e,std::size_t cap) {
  try {
    if(!alphabet)throw std::invalid_argument("missing alphabet output");
#if RW_KIND == 7
    *alphabet=deepzip::Model::load(read_model(path)).alphabet_size();return 0;
#else
    (void)path;return failure(e,cap,"alphabet query not applicable");
#endif
  }catch(const std::exception& x){return failure(e,cap,x.what());}
  catch(...){return failure(e,cap,"unknown native exception");}
}
extern "C" int rw_bound(const RwConfig* c,const std::uint8_t* p,std::size_t size,std::size_t* n,char* e,std::size_t cap){
  try {if(!c||(!p&&size)||!n)throw std::invalid_argument("invalid binding arguments");*n=bound(*c,p,size);return 0;}
  catch(const std::exception& x){return failure(e,cap,x.what());}catch(...){return failure(e,cap,"unknown native exception");}
}
extern "C" int rw_encode(const RwConfig* c,const std::uint8_t* p,std::size_t size,std::uint8_t* out,std::size_t capacity,std::size_t* written,char* e,std::size_t cap){
  try {if(!c||(!p&&size)||!written||(!out&&capacity))throw std::invalid_argument("invalid binding arguments");
    auto n=bound(*c,p,size);if(capacity<n)return 3;auto b=encode(*c,p,size);if(b.size()>capacity)return 3;
    if(!b.empty())std::memcpy(out,b.data(),b.size());*written=b.size();return 0;}
  catch(const std::exception& x){return failure(e,cap,x.what());}catch(...){return failure(e,cap,"unknown native exception");}
}
extern "C" int rw_decode(const std::uint8_t* p,std::size_t size,std::uint8_t* out,std::size_t capacity,std::size_t* written,char* e,std::size_t cap){
  try {if((!p&&size)||!written||(!out&&capacity))throw std::invalid_argument("invalid binding arguments");auto b=decode(p,size,capacity);
    if(b.size()>capacity)return 3;if(!b.empty())std::memcpy(out,b.data(),b.size());*written=b.size();return 0;}
  catch(const std::exception& x){return failure(e,cap,x.what());}catch(...){return failure(e,cap,"unknown native exception");}
}
