// Benchmark binding only; frozen repaired-v1 core and numerical dependency unchanged.
#include "cameo_family.hpp"
#include "json.hpp"
#include "tsbench_core.hpp"
#include "tscb_native_timing.h"
#include <algorithm>
#include <cfenv>
#include <cmath>
#include <cstdio>
#include <memory>
namespace {
using Json=nlohmann::json;
using Config=cameo_family::Config;
using Bytes=std::vector<uint8_t>;
using tsbench_core::require;
constexpr size_t max_samples=cameo_family::max_samples,max_frame=cameo_family::max_frame;
constexpr char manifest[]="{\"abi_version\":1,\"algorithm\":\"" CF_KEY "\",\"implementation\":\"cameo-repaired-v1-bench-v1\",\"frame\":\"CF01/CFM1\",\"isa\":\"NATIVE_DISPATCH\"}";
uint64_t le(const uint8_t* p,size_t n){uint64_t x=0;for(size_t i=0;i<n;++i)x|=uint64_t(p[i])<<(8*i);return x;}
void put(Bytes& b,uint64_t x,size_t n){for(size_t i=0;i<n;++i){b.push_back(uint8_t(x));x>>=8;}}
uint32_t crc(const uint8_t* p,size_t n){uint32_t c=~0u;for(size_t i=0;i<n;++i){c^=p[i];for(int j=0;j<8;++j)c=(c>>1)^(0xedb88320u&uint32_t(-int32_t(c&1)));}return ~c;}
void fp(){if(std::fegetround()!=FE_TONEAREST)throw tsbench_core::Unsupported("CAMEO family requires FE_TONEAREST");const uint16_t e=1;if(*reinterpret_cast<const uint8_t*>(&e)!=1)throw tsbench_core::Unsupported("little-endian host required");}
void geometry(size_t rows,size_t columns){if(rows<1||rows>max_samples||columns<1||columns>4096||rows>max_samples/columns)throw tsbench_core::Unsupported("CAMEO family requires 1..131072 total values, at most 4096 columns");}
Config settings(const char* text,bool c1=false){
 Json p=Json::parse(text?text:"{}");require(p.is_object(),"parameter object required");Config c;c.algorithm=cameo_family::Algorithm(CF_KIND);
 std::vector<std::string> keys={"isa","native_timing"};
 if(CF_KIND<=4){keys.insert(keys.end(),{"error_bound","nlags","hops","kappa","threads"});if(CF_KIND==1)keys.insert(keys.end(),{"backend","criterion"});}
 else if(CF_KIND==5)keys.insert(keys.end(),{"error_bound","mode","window_fraction"});
 else if(CF_KIND<=8)keys.push_back("error_bound");
 else {keys.push_back("fraction");if(CF_KIND==10)keys.push_back("transform");}
 for(auto it=p.begin();it!=p.end();++it){if(it.key()=="algorithm"&&c1){require(it.value()==CF_KEY,"algorithm identity mismatch");continue;}require(std::find(keys.begin(),keys.end(),it.key())!=keys.end(),"unknown family parameter");}
 if(c1)require(p.value("algorithm","")==CF_KEY,"missing algorithm identity");
 if(p.contains("isa"))require(p["isa"]=="NATIVE_DISPATCH","native dispatch is fixed, not an ISA selector");
 if(p.contains("native_timing"))require(p["native_timing"].is_boolean(),"native_timing must be boolean");
 auto real=[&](const char* k,double fallback){if(!p.contains(k))return fallback;const auto& j=p[k];double v;if(j.is_string()){auto s=j.get<std::string>();size_t at=0;v=std::stod(s,&at);require(at==s.size(),"invalid decimal parameter");}else{require(j.is_number(),"numeric parameter required");v=j.get<double>();}require(std::isfinite(v),"finite parameter required");return v;};
 auto integer=[&](const char* k,size_t fallback,size_t lo,size_t hi){if(!p.contains(k))return fallback;require(p[k].is_number_integer(),"integer parameter required");auto x=p[k].get<int64_t>();require(x>=int64_t(lo)&&x<=int64_t(hi),"integer parameter range");return size_t(x);};
 auto choice=[&](const char* k,const char* fallback,std::initializer_list<const char*> values){std::string s=p.value(k,std::string(fallback));bool found=false;for(auto v:values)found|=s==v;require(found,"invalid parameter choice");return s;};
 c.error_bound=real("error_bound",.01);require(c.error_bound>=0,"nonnegative threshold required");
 c.fraction=real("fraction",.5);require(std::fabs(c.fraction)<=1e6,"fraction domain");
 c.window_fraction=real("window_fraction",.5);require(c.window_fraction>0&&c.window_fraction<=1,"window fraction domain");
 c.nlags=integer("nlags",4,1,65535);c.hops=integer("hops",2,1,max_samples);c.kappa=integer("kappa",1,1,max_samples);c.threads=integer("threads",1,1,64);
 if(CF_KIND==1){c.parallel_lookahead=choice("backend","lpc",{"lpc","fgc"})=="fgc";c.ratio_stopping=choice("criterion","error",{"error","cr"})=="cr";}
 if(CF_KIND==5){auto m=choice("mode","sliding",{"sliding","bottom-up","python-bottom-up"});c.bottom_up=m=="bottom-up";c.python_bottom_up=m=="python-bottom-up";}
 if(CF_KIND==10)c.canonical_dct=choice("transform","fft",{"fft","scalar"})=="scalar";
 require(!c.ratio_stopping||(c.kappa==1&&c.error_bound>=1&&c.error_bound<=max_samples&&c.error_bound==std::floor(c.error_bound)),"ratio requires integer error_bound and kappa=1");return c;
}
void domain(size_t n,const Config& c){
 if(CF_KIND<=4&&n>=3){if(n%c.kappa||n/c.kappa<8||c.nlags>=n/c.kappa/2||static_cast<long double>(n)*n*c.nlags*std::min(c.hops,size_t(16))>1e8L)throw tsbench_core::Unsupported("ACF length/lag/aggregate/work domain");}
 if(CF_KIND==5&&n>=3){if(static_cast<long double>(n)*n>1e8L||(!c.bottom_up&&!c.python_bottom_up&&size_t(n*c.window_fraction)<2))throw tsbench_core::Unsupported("SWAB window/work domain");}
 if(CF_KIND==10&&c.canonical_dct&&static_cast<long double>(n)*n>1e8L)throw tsbench_core::Unsupported("scalar DCT work domain");
}
size_t bound(size_t rows,size_t columns){geometry(rows,columns);return std::min(max_frame,tsbench_core::add(32+columns*1100,tsbench_core::multiply(rows*columns,64)));}
void finite_input(const uint8_t* p,size_t n){require(p&&n%8==0,"invalid binary64 input");fp();for(size_t i=0;i<n;i+=8){double x;std::memcpy(&x,p+i,8);if(!std::isfinite(x))throw tsbench_core::Unsupported("FINITE_INPUT_REQUIRED");}}
void frame_geometry(const uint8_t* p,size_t n,size_t expected=0){require(p&&n>=68&&n<=max_frame&&!std::memcmp(p,"CF01",4),"frame size/magic");require(le(p+4,8)==1&&le(p+12,8)==CF_KIND,"frame version/algorithm mismatch");size_t rows=size_t(le(p+28,8));geometry(rows,1);require(le(p+36,8)==rows,"SOURCE_RECONSTRUCTED_LENGTH_DIFFERS_FROM_GRID");if(expected)require(rows==expected,"frame/task sample mismatch");}
Bytes encode_one(const uint8_t* p,size_t rows,const Config& c){
 finite_input(p,rows*8);domain(rows,c);std::vector<double> v(rows);std::memcpy(v.data(),p,rows*8);Bytes b;
 try{b=cameo_family::encode(v,c);}catch(const std::invalid_argument& e){throw tsbench_core::Unsupported(std::string("SOURCE_ARITHMETIC_OR_RESOURCE_LIMIT: ")+e.what());}
 if(b.size()>=44&&le(b.data()+36,8)!=rows)throw tsbench_core::Unsupported("SOURCE_RECONSTRUCTED_LENGTH_DIFFERS_FROM_GRID");frame_geometry(b.data(),b.size(),rows);return b;
}
std::vector<double> decode_one(const uint8_t* p,size_t n,size_t expected=0){fp();frame_geometry(p,n,expected);auto v=cameo_family::decode(p,n);require(v.size()==le(p+28,8),"decoded count mismatch");return v;}
Bytes encode_columns(const uint8_t* p,size_t rows,size_t cols,const Config& c){
 geometry(rows,cols);finite_input(p,rows*cols*8);if(cols==1)return encode_one(p,rows,c);
 Bytes b;b.insert(b.end(),{'C','F','M','1'});put(b,1,4);put(b,rows,8);put(b,cols,8);
 for(size_t j=0;j<cols;++j){auto f=encode_one(p+j*rows*8,rows,c);require(f.size()<=max_frame-b.size()-12,"matrix frame limit");put(b,f.size(),8);b.insert(b.end(),f.begin(),f.end());}
 put(b,crc(b.data(),b.size()),4);return b;
}
std::vector<double> decode_columns(const uint8_t* p,size_t n){
 require(p&&n>=4&&n<=max_frame,"frame length");if(!std::memcmp(p,"CF01",4))return decode_one(p,n);
 require(n>=28&&!std::memcmp(p,"CFM1",4)&&le(p+4,4)==1,"matrix magic/version");require(le(p+n-4,4)==crc(p,n-4),"matrix CRC");size_t rows=size_t(le(p+8,8)),cols=size_t(le(p+16,8));geometry(rows,cols);require(cols>1,"matrix column count");
 std::vector<double> values;values.reserve(rows*cols);size_t at=24;for(size_t j=0;j<cols;++j){require(n-4-at>=8,"truncated column length");size_t size=size_t(le(p+at,8));at+=8;require(size<=n-4-at,"truncated column frame");auto v=decode_one(p+at,size,rows);values.insert(values.end(),v.begin(),v.end());at+=size;}require(at==n-4,"trailing matrix bytes");return values;
}
struct Core{Config config;size_t rows{};bool decoder{};char error[256]{};};
thread_local char core_error[256]{};
template<class F>int guard(Core* s,F f)noexcept{int code=1;try{f();return 0;}catch(const tsbench_core::Unsupported& e){std::snprintf(core_error,sizeof(core_error),"%s",e.what());code=2;}catch(const tsbench_core::Capacity& e){std::snprintf(core_error,sizeof(core_error),"%s",e.what());code=3;}catch(const std::exception& e){std::snprintf(core_error,sizeof(core_error),"%s",e.what());}catch(...){std::snprintf(core_error,sizeof(core_error),"family binding failure");}if(s)std::snprintf(s->error,sizeof(s->error),"%s",core_error);return code;}
}
extern "C" uint32_t tsbench_core_version(){return 1;}
extern "C" uint32_t tsbench_core_storage(){return 0;}
extern "C" int tsbench_core_create(const tsbench_core_config* cfg,int decoder,void** out){if(out)*out=nullptr;return guard(nullptr,[&]{require(cfg&&out&&(decoder==0||decoder==1),"invalid core config");tsbench_core::elements(*cfg);if(cfg->rank!=1||cfg->dtype!=TSCB_DTYPE_F64_LE_V1)throw tsbench_core::Unsupported("CAMEO family core requires rank1 binary64");require(!cfg->model||!*cfg->model,"no external model allowed");fp();geometry(cfg->shape[0],1);auto p=std::make_unique<Core>();p->rows=cfg->shape[0];p->decoder=decoder!=0;if(decoder){auto j=Json::parse(cfg->parameters_json?cfg->parameters_json:"{}");require(j.is_object()&&j.empty(),"decoder parameters must be empty");}else {p->config=settings(cfg->parameters_json); domain(p->rows,p->config);}*out=p.release();});}
extern "C" int tsbench_core_destroy(void* p){delete static_cast<Core*>(p);return 0;}
extern "C" int tsbench_core_validate_input(void* p,const uint8_t* in,size_t n){auto s=static_cast<Core*>(p);return guard(s,[&]{require(s&&n==s->rows*8,"input extent mismatch");finite_input(in,n);});}
extern "C" int tsbench_core_bound(void* p,const uint8_t*,size_t n,size_t* out){if(out)*out=0;auto s=static_cast<Core*>(p);return guard(s,[&]{require(s&&out&&n==s->rows*8,"bound extent mismatch");*out=bound(s->rows,1);});}
extern "C" int tsbench_core_encode(void* p,const uint8_t* in,size_t n,uint8_t*,size_t,tsbench_core_result* r){if(r)*r={};auto s=static_cast<Core*>(p);return guard(s,[&]{require(s&&!s->decoder&&r&&n==s->rows*8,"encode extent/state mismatch");tsbench_core::vector_result(encode_one(in,s->rows,s->config),r);});}
extern "C" int tsbench_core_decode(void* p,const uint8_t* in,size_t n,uint8_t*,size_t,tsbench_core_result* r){if(r)*r={};auto s=static_cast<Core*>(p);return guard(s,[&]{require(s&&s->decoder&&r,"decode state mismatch");tsbench_core::vector_result(decode_one(in,n,s->rows),r);});}
extern "C" void tsbench_core_release(tsbench_core_result* r){tsbench_core::release(r);}
extern "C" const char* tsbench_core_error(void* p){return p?static_cast<Core*>(p)->error:core_error;}

struct tscb_codec_handle_v1{tscb_native_timer native_timer{};Config config;bool updated=false,finalized=false;size_t input_bytes{},stream_bytes{};char error[256]{};std::string accounting;};
namespace {
template<class F>tscb_status_v1 api_guard(tscb_codec_handle_v1* h,F f)noexcept{try{f();return TSCB_STATUS_OK_V1;}catch(const tsbench_core::Unsupported& e){if(h)std::snprintf(h->error,sizeof(h->error),"%s",e.what());return TSCB_STATUS_UNSUPPORTED_V1;}catch(const tsbench_core::Capacity& e){if(h)std::snprintf(h->error,sizeof(h->error),"%s",e.what());return TSCB_STATUS_DST_TOO_SMALL_V1;}catch(const std::exception& e){if(h)std::snprintf(h->error,sizeof(h->error),"%s",e.what());return TSCB_STATUS_CODEC_ERROR_V1;}catch(...){return TSCB_STATUS_CODEC_ERROR_V1;}}
bool valid(const tscb_buffer_v1* b){return b&&b->dtype==TSCB_DTYPE_BYTES_V1&&b->rank==1&&b->strides_bytes[0]==1&&b->used_bytes<=b->capacity_bytes&&b->capacity_bytes<=SIZE_MAX&&(!b->capacity_bytes||b->data);}
struct Input{const uint8_t* p;size_t rows,cols;};
Input input_view(const tscb_buffer_v1* b){require(valid(b)&&b->used_bytes>=24,"invalid input descriptor");auto p=static_cast<const uint8_t*>(b->data);require(!std::memcmp(p,"CMI1",4)&&le(p+4,4)==1,"input magic/version");size_t rows=size_t(le(p+8,8)),cols=size_t(le(p+16,8));geometry(rows,cols);require(b->used_bytes-24==rows*cols*8,"input size mismatch");return {p+24,rows,cols};}
void commit(const void* p,size_t n,tscb_buffer_v1* b){if(n>b->capacity_bytes)throw tsbench_core::Capacity("output capacity too small");if(n)std::memmove(b->data,p,n);b->used_bytes=n;}
}
extern "C" {
uint32_t tscb_get_abi_version(){return 1;}
tscb_status_v1 tscb_get_manifest_json(const char** p,uint64_t* n){if(!p||!n)return TSCB_STATUS_INVALID_ARGUMENT_V1;*p=manifest;*n=sizeof(manifest)-1;return TSCB_STATUS_OK_V1;}
tscb_status_v1 tscb_create(const char* json,uint64_t length,tscb_codec_handle_v1** out){if(!out)return TSCB_STATUS_INVALID_ARGUMENT_V1;*out=nullptr;if(!json||length>16384)return TSCB_STATUS_INVALID_ARGUMENT_V1;return api_guard(nullptr,[&]{std::string s(json,size_t(length));require(s.find('\0')==std::string::npos,"embedded NUL");auto c=settings(s.c_str(),true);fp();auto h=std::make_unique<tscb_codec_handle_v1>();h->config=std::move(c);*out=h.release();});}
tscb_status_v1 tscb_destroy(tscb_codec_handle_v1* h){delete h;return TSCB_STATUS_OK_V1;}
tscb_status_v1 tscb_reset(tscb_codec_handle_v1* h,uint32_t mode){if(!h||mode)return TSCB_STATUS_INVALID_ARGUMENT_V1;h->updated=h->finalized=false;h->input_bytes=h->stream_bytes=0;h->error[0]=0;h->accounting.clear();h->native_timer.encode_ns=h->native_timer.decode_ns=0;return TSCB_STATUS_OK_V1;}
TSCB_NATIVE_TIMING_API
tscb_status_v1 tscb_compress_bound(tscb_codec_handle_v1* h,const tscb_buffer_v1* in,uint64_t* out){if(!h||!out)return TSCB_STATUS_INVALID_ARGUMENT_V1;*out=0;return api_guard(h,[&]{auto v=input_view(in);domain(v.rows,h->config);*out=bound(v.rows,v.cols);});}
tscb_status_v1 tscb_compress(tscb_codec_handle_v1* h,const tscb_buffer_v1* in,tscb_buffer_v1* out){if(!h||!valid(in)||!valid(out))return TSCB_STATUS_INVALID_ARGUMENT_V1;out->used_bytes=0;if(h->updated||h->finalized)return TSCB_STATUS_INVALID_ARGUMENT_V1;return api_guard(h,[&]{auto v=input_view(in);Bytes b;TSCB_TIME_CODEC(h->native_timer,encode_ns,b=encode_columns(v.p,v.rows,v.cols,h->config));commit(b.data(),b.size(),out);h->input_bytes=v.rows*v.cols*8;h->stream_bytes=b.size();h->updated=true;});}
tscb_status_v1 tscb_finalize(tscb_codec_handle_v1* h,tscb_buffer_v1* out){if(!h||!valid(out))return TSCB_STATUS_INVALID_ARGUMENT_V1;out->used_bytes=0;if(!h->updated)return TSCB_STATUS_FINALIZE_REQUIRED_V1;if(h->finalized)return TSCB_STATUS_CODEC_ERROR_V1;return api_guard(h,[&]{h->accounting="{\"frame_bytes\":"+std::to_string(h->stream_bytes)+",\"input_bytes\":"+std::to_string(h->input_bytes)+",\"external_side_information_bits\":0,\"finalize_calls\":1}";h->finalized=true;});}
tscb_status_v1 tscb_decompress(tscb_codec_handle_v1* h,const tscb_buffer_v1* in,tscb_buffer_v1* out){if(!h||!valid(in)||!valid(out))return TSCB_STATUS_INVALID_ARGUMENT_V1;out->used_bytes=0;return api_guard(h,[&]{std::vector<double> v;TSCB_TIME_CODEC(h->native_timer,decode_ns,v=decode_columns(static_cast<const uint8_t*>(in->data),in->used_bytes));commit(v.data(),v.size()*8,out);});}
tscb_status_v1 tscb_query(tscb_codec_handle_v1*,const char*,uint64_t,char*,uint64_t,uint64_t* out){if(out)*out=0;return TSCB_STATUS_UNSUPPORTED_V1;}
tscb_status_v1 tscb_get_accounting_json(tscb_codec_handle_v1* h,const char** p,uint64_t* n){if(!h||!p||!n||!h->finalized)return TSCB_STATUS_INVALID_ARGUMENT_V1;*p=h->accounting.c_str();*n=h->accounting.size();return TSCB_STATUS_OK_V1;}
tscb_status_v1 tscb_get_last_error(tscb_codec_handle_v1* h,const char** p,uint64_t* n){if(!h||!p||!n)return TSCB_STATUS_INVALID_ARGUMENT_V1;*p=h->error;*n=std::strlen(h->error);return TSCB_STATUS_OK_V1;}
}
