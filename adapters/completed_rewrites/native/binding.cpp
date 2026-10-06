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
#elif RW_KIND == 3
#include "tsm_timestamp.hpp"
#elif RW_KIND == 4
#include "prometheus_xor2_chunk.hpp"
#elif RW_KIND == 5
#include "tristan.hpp"
#elif RW_KIND == 6
#include "corad.hpp"
#elif RW_KIND == 7
#include "deepzip/deepzip.hpp"
#elif RW_KIND == 8
#include "dzip.hpp"
#elif RW_KIND == 9
#include "walloc.hpp"
#elif RW_KIND == 10 || RW_KIND == 11
#include "histogram_st.hpp"
#endif
using Bytes = std::vector<std::uint8_t>;
#if RW_KIND == 9
static void configure_cpu() {
  static const bool configured=[](){walloc::Codec::configure_cpu_threads(1);return true;}();
  (void)configured;
}
#endif
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
#if RW_KIND == 5 || RW_KIND == 6
#if RW_KIND == 5
namespace sparse_codec=tristan;
#else
namespace sparse_codec=corad;
#endif
static sparse_codec::Config sparse_config(const RwConfig& c) {
  sparse_codec::Config s; s.length=c.a; s.atoms=c.b; s.nonzeros=c.c;
  s.requested_n_iter=c.d; s.seed=c.seed; s.alpha=c.x; s.solver=static_cast<tristan::Solver>(c.mode);
#if RW_KIND == 6
  s.threshold=c.y;
#endif
  return s;
}
#endif
#if RW_KIND == 7 || RW_KIND == 8 || RW_KIND == 9
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
#if RW_KIND == 10 || RW_KIND == 11
static histogram_st::Kind histogram_kind() {
  return RW_KIND==10 ? histogram_st::Kind::Integer : histogram_st::Kind::Floating;
}
static void hist_check(histogram_st::Status status) {
  if(!status.ok())throw std::invalid_argument(status.message);
}
static void put64(Bytes& b,std::uint64_t value) {
  for(unsigned i=0;i<8;++i)b.push_back(static_cast<std::uint8_t>(value>>(i*8)));
}
static std::uint64_t get64(const std::uint8_t* p) {
  std::uint64_t value=0;for(unsigned i=0;i<8;++i)value|=std::uint64_t(p[i])<<(i*8);return value;
}
static void hist_frame(Bytes& output,const histogram_st::Chunk& chunk) {
  Bytes frame(chunk.frame_bytes());std::size_t written=0;
  hist_check(chunk.serialize_frame(frame.data(),frame.size(),&written));
  frame.resize(written);put64(output,frame.size());output.insert(output.end(),frame.begin(),frame.end());
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
#elif RW_KIND == 3
  valid(c,size,8); auto v=values<std::int64_t>(p,size);std::size_t n;
  auto s=tsm_timestamp::encode_bound(v.data(),v.size(),c.mode?tsm_timestamp::Profile::Batch:tsm_timestamp::Profile::Stream,&n);
  if(!s.ok()) throw std::invalid_argument(s.message); return n;
#elif RW_KIND == 4
  valid(c,size,24); std::size_t n; auto s=prometheus_xor2::max_compressed_size(c.rows,&n);
  if(!s.ok()) throw std::invalid_argument(s.message); return n;
#elif RW_KIND == 5 || RW_KIND == 6
  valid(c,size,8); return sparse_codec::compress_bound(c.rows,c.columns,sparse_config(c));
#elif RW_KIND == 7
  auto model=deepzip::Model::load(read_model(c.model)); deepzip::Config config;
  config.lanes=c.a; for(unsigned i=0;i<model.alphabet_size();++i) config.alphabet.push_back(static_cast<std::uint8_t>(i));
  return deepzip::compress_bound(model,size,config);
#elif RW_KIND == 8
  valid(c,size,1);
  auto model=c.model && *c.model ? dzip::Network::load(read_model(c.model)) : dzip::Network::create(input_alphabet(p,size),c.mode?dzip::ModelProfile::combined_cpu:dzip::ModelProfile::bootstrap_cpu,c.seed);
  return dzip::compress_bound(size,model);
#elif RW_KIND == 9
  valid(c,size,4); return size+read_model(c.model).size()+(64ULL<<20);
#elif RW_KIND == 10 || RW_KIND == 11
  valid(c,size,8);
  if(c.columns!=7 || c.rows>16383)throw std::invalid_argument("histogram record dimensions");
  return c.rows*512+65536;
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
#elif RW_KIND == 3
  auto v=values<std::int64_t>(p,size); Bytes b;
  auto s=tsm_timestamp::encode(v.data(),v.size(),c.mode?tsm_timestamp::Profile::Batch:tsm_timestamp::Profile::Stream,&b);
  if(!s.ok())throw std::invalid_argument(s.message); return b;
#elif RW_KIND == 4
  static_assert(sizeof(prometheus_xor2::Sample)==24,"unexpected native sample layout");
  auto v=values<prometheus_xor2::Sample>(p,size);std::size_t n=bound(c,p,size);Bytes b(n);
  auto s=prometheus_xor2::encode(v.data(),v.size(),b.data(),b.size(),&n);
  if(!s.ok())throw std::invalid_argument(s.message);b.resize(n);return b;
#elif RW_KIND == 5 || RW_KIND == 6
  auto v=values<double>(p,size);return sparse_codec::encode(v.data(),c.rows,c.columns,sparse_config(c));
#elif RW_KIND == 7
  auto model=deepzip::Model::load(read_model(c.model));deepzip::Config s;s.lanes=c.a;
  for(unsigned i=0;i<model.alphabet_size();++i)s.alphabet.push_back(static_cast<std::uint8_t>(i));
  return deepzip::compress(model,Bytes(p,p+size),s).bytes;
#elif RW_KIND == 8
  auto model=c.model && *c.model ? dzip::Network::load(read_model(c.model)) : dzip::Network::create(input_alphabet(p,size),c.mode?dzip::ModelProfile::combined_cpu:dzip::ModelProfile::bootstrap_cpu,c.seed);
  return dzip::compress(Bytes(p,p+size),model,c.mode?dzip::Mode::combined:dzip::Mode::bootstrap).bytes;
#elif RW_KIND == 9
  configure_cpu();
  auto v=values<float>(p,size);walloc::Codec codec(read_model(c.model)); return codec.encode(v.data(),v.size(),c.rows);
#elif RW_KIND == 10 || RW_KIND == 11
  auto v=values<std::uint64_t>(p,size);histogram_st::Chunk chunk(histogram_kind());Bytes result;
  for(std::size_t i=0;i<c.rows;++i) {
    const auto* row=v.data()+i*7;histogram_st::Sample sample;
    std::memcpy(&sample.timestamp,row,8);std::memcpy(&sample.st,row+1,8);
    sample.count=row[2];sample.zero=row[3];sample.sum=row[4];sample.threshold=row[5];
    sample.schema=0;sample.hint=3;sample.positive_spans={{0,1}};sample.positive={row[6]};
    histogram_st::Chunk previous=chunk;
    auto appended=chunk.append(sample);hist_check(appended.status);
    if(appended.new_chunk)hist_frame(result,previous);
  }
  hist_frame(result,chunk);return result;
#endif
}
static Bytes decode(const std::uint8_t* p,std::size_t size,std::size_t capacity) {
#if RW_KIND == 1
  return raw(abba::decode(p,size));
#elif RW_KIND == 2
  return raw(fabba::decode(p,size));
#elif RW_KIND == 3
  std::vector<std::int64_t> v;auto s=tsm_timestamp::decode(p,size,&v);
  if(!s.ok())throw std::invalid_argument(s.message);return raw(v);
#elif RW_KIND == 4
  std::vector<prometheus_xor2::Sample> v(capacity/24);std::size_t n;
  auto s=prometheus_xor2::decode(p,size,v.data(),v.size(),&n);
  if(!s.ok())throw std::invalid_argument(s.message);v.resize(n);return raw(v);
#elif RW_KIND == 5 || RW_KIND == 6
  auto d=sparse_codec::decode(p,size);
  if(d.windows*d.config.length!=d.original_rows)throw std::invalid_argument("source dropped tail");
  std::vector<double> v(d.original_rows*d.channels);
  for(std::size_t ch=0;ch<d.channels;++ch)for(std::size_t w=0;w<d.windows;++w)for(std::size_t k=0;k<d.config.length;++k){
    auto i=(ch*d.windows+w)*d.config.length+k;
    v[(w*d.config.length+k)*d.channels+ch]=d.values[i]*d.scales[ch]+d.means[ch];
  }return raw(v);
#elif RW_KIND == 7
  return deepzip::decompress(Bytes(p,p+size));
#elif RW_KIND == 8
  return dzip::decompress(Bytes(p,p+size));
#elif RW_KIND == 9
  configure_cpu();
  return raw(walloc::Codec::decode(Bytes(p,p+size)).values);
#elif RW_KIND == 10 || RW_KIND == 11
  Bytes result;std::size_t position=0;
  while(position<size) {
    if(size-position<8)throw std::invalid_argument("truncated histogram frame length");
    auto length=get64(p+position);position+=8;
    if(length>size-position)throw std::invalid_argument("truncated histogram frame");
    histogram_st::Cursor cursor;hist_check(cursor.reset_frame(p+position,length));position+=length;
    histogram_st::Sample sample;bool available;
    for(;;) {
      hist_check(cursor.next(&sample,&available));if(!available)break;
      if(sample.schema!=0 || sample.hint!=3 || sample.positive_spans.size()!=1 ||
         sample.positive_spans[0].offset!=0 || sample.positive_spans[0].length!=1 ||
         !sample.negative_spans.empty() || !sample.custom.empty() || sample.positive.size()!=1 || !sample.negative.empty())
        throw std::invalid_argument("histogram layout mismatch");
      std::uint64_t t,st;std::memcpy(&t,&sample.timestamp,8);std::memcpy(&st,&sample.st,8);
      if(capacity-result.size()<56)throw std::invalid_argument("histogram decoded size exceeds capacity");
      for(auto word:{t,st,sample.count,sample.zero,sample.sum,sample.threshold,sample.positive[0]})put64(result,word);
    }
  }
  return result;
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
