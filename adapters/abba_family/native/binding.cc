// Benchmark binding. Released core, CKmeans and bundled byte libraries are unchanged.
#include "abba_family.hpp"
#include "tsbench_core.hpp"
#include "tscb_native_timing.h"
#include <algorithm>
#include <cfenv>
#include <cstdio>
#include <memory>
#include <zlib.h>
namespace {
using Json=abba_family::Json;
using Bytes=std::vector<uint8_t>;
using tsbench_core::require;
constexpr size_t max_samples=1048576,max_frame=268435456;
constexpr char manifest[]="{\"abi_version\":1,\"algorithm\":\"" AF_KEY "\",\"implementation\":\"abba-family-20261020-binding-v1\",\"frame\":\"AFS1/AFM1\",\"threading\":\"SINGLE_THREAD\",\"isa\":\"SCALAR\"}";
uint64_t le(const uint8_t* p,size_t n){uint64_t x=0;for(size_t i=0;i<n;++i)x|=uint64_t(p[i])<<(8*i);return x;}
void put(Bytes& b,uint64_t x,size_t n){for(size_t i=0;i<n;++i){b.push_back(uint8_t(x));x>>=8;}}
void fp(){if(std::fegetround()!=FE_TONEAREST)throw tsbench_core::Unsupported("ABBA family requires FE_TONEAREST");const uint16_t e=1;if(*reinterpret_cast<const uint8_t*>(&e)!=1)throw tsbench_core::Unsupported("little-endian host required");}
void geometry(size_t rows,size_t columns){if(rows<2||rows>max_samples||columns<1||columns>4096||rows>max_samples/columns)throw tsbench_core::Unsupported("ABBA family requires 2..1048576 values, at most 4096 independent columns");}
Json settings(const char* text,bool c1=false){
    Json p=abba_family::parse_request(text?text:"{}");require(p.is_object(),"parameter object required");
    Json c=Json::object();
    const std::string a=AF_KEY;
    std::vector<std::string> keys={"isa","native_timing","max_len","scl"};
    if(a=="abba")keys.insert(keys.end(),{"compression_tolerance","digitization_tolerance","min_k","max_k","norm","clustering","weighted","symmetric"});
    if(a=="fabba")keys.insert(keys.end(),{"tolerance","alpha","sorting","source_backend"});
    if(a=="qabba"){keys={"isa","native_timing","tolerance","alpha","max_len","digitizer","sorting","n_symbols","sample_rate","scale_length","bits_for_len","bits_for_inc","max_iter","random_state","symbol_codec"};}
    for(auto it=p.begin();it!=p.end();++it){if(it.key()=="algorithm"&&c1){require(it.value()==a,"algorithm identity mismatch");continue;}require(std::find(keys.begin(),keys.end(),it.key())!=keys.end(),"unknown family parameter");}
    if(c1)require(p.value("algorithm","")==a,"missing algorithm identity");
    if(p.contains("isa"))require(p["isa"]=="SCALAR","only SCALAR supported");
    if(p.contains("native_timing"))require(p["native_timing"].is_boolean(),"native_timing must be boolean");
    auto real=[&](const char* k,double fallback){if(!p.contains(k))return fallback;const auto& j=p[k];double v;if(j.is_string()){auto s=j.get<std::string>();size_t at=0;v=std::stod(s,&at);require(at==s.size(),"invalid decimal parameter");}else{require(j.is_number(),"numeric parameter required");v=j.get<double>();}require(std::isfinite(v),"finite parameter required");return v;};
    auto integer=[&](const char* k,int64_t fallback,int64_t lo,int64_t hi){if(!p.contains(k))return fallback;require(p[k].is_number_integer(),"integer parameter required");int64_t x=p[k].get<int64_t>();require(x>=lo&&x<=hi,"integer parameter range");return x;};
    auto choice=[&](const char* k,const char* fallback,std::initializer_list<const char*> values){std::string s=p.value(k,std::string(fallback));bool found=false;for(auto v:values)found|=s==v;require(found,"invalid parameter choice");return s;};
    c["max_len"]=integer("max_len",1048576,1,4294967295LL);
    if(a=="abba"){
        const double x=real("compression_tolerance",.1),y=real("digitization_tolerance",.1);require(x>=0&&y>=0,"nonnegative tolerance required");c["tol"]=Json::array({x,y});
        c["scl"]=real("scl",0);require(c["scl"].get<double>()>=0,"nonnegative scl required");
        c["min_k"]=integer("min_k",1,1,65535);c["max_k"]=integer("max_k",100,1,65535);require(c["min_k"]<=c["max_k"],"k bounds");
        c["norm"]=integer("norm",2,1,2);c["c_method"]=choice("clustering","KMEANS",{"KMEANS","INCREMENTAL"})=="KMEANS"?"kmeans":"incremental";
        c["seed"]=true;
        for(auto k:{"weighted","symmetric"}){if(p.contains(k))require(p[k].is_boolean(),"boolean required");c[k]=p.value(k,k==std::string("symmetric"));}
    }else{
        c["tol"]=real("tolerance",a=="fabba"?.1:.2);c["alpha"]=real("alpha",.5);require(c["tol"].get<double>()>=(a=="fabba"?0:std::numeric_limits<double>::min())&&c["alpha"].get<double>()>=(a=="fabba"?0:std::numeric_limits<double>::min()),"tolerance/alpha range");
        c["n_jobs"]=1;
        if(a=="fabba"){
            c["scl"]=real("scl",1);require(c["scl"].get<double>()>=0,"nonnegative scl required");
            c["sorting"]=choice("sorting","2-norm",{"lexi","1-norm","2-norm","norm","pca"});
            c["source_backend"]=choice("source_backend","python",{"python","cython"});
        }else{
            c["digitizer"]=choice("digitizer","agg",{"agg","kmeans","f-kmeans"});c["sorting"]=choice("sorting","norm",{"norm","pca"});
            c["n_symbols"]=integer("n_symbols",2,1,65535);c["max_iter"]=integer("max_iter",100,1,10000);c["random_state"]=integer("random_state",0,0,4294967295LL);
            c["bits_for_len"]=integer("bits_for_len",8,1,64);c["bits_for_inc"]=integer("bits_for_inc",16,1,64);
            c["sample_rate"]=real("sample_rate",.5);require(c["sample_rate"].get<double>()>0&&c["sample_rate"].get<double>()<=1,"sample_rate range");
            c["scale_length"]=real("scale_length",1);require(c["scale_length"].get<double>()>=0,"scale_length range");
            c["symbol_codec"]=choice("symbol_codec","none",{"none","fixed","huffman","lzw","zlib","gzip","bz2","lzma","zstd"});
        }
    }
    return c;
}
size_t bound(size_t rows,size_t columns){geometry(rows,columns);return std::min(max_frame,tsbench_core::add(32+columns*16,tsbench_core::multiply(columns,tsbench_core::add(131072,tsbench_core::multiply(rows,16384)))));}
void finite_input(const uint8_t* p,size_t n){require(p&&n%8==0,"invalid binary64 input");fp();for(size_t i=0;i<n;i+=8){double x;std::memcpy(&x,p+i,8);if(!std::isfinite(x))throw tsbench_core::Unsupported("FINITE_INPUT_REQUIRED");}}
Bytes encode_one(const uint8_t* p,size_t rows,const Json& c){
    finite_input(p,rows*8);Json request=Json::object();request["algorithm"]=AF_KEY;request["config"]=c;request["values"]=Json::array();
    for(size_t i=0;i<rows;++i){double x;std::memcpy(&x,p+i*8,8);request["values"].push_back(x);}
    // The owning encoder includes fitting and the released fit/reconstruction work.
    // Preserve source length changes as explicit unsupported objects, never pad/resample.
    Bytes b;
    try { b=abba_family::encode(request); }
    catch(const std::invalid_argument& e){throw tsbench_core::Unsupported(std::string("SOURCE_ARITHMETIC_OR_RESOURCE_LIMIT: ")+e.what());}
    const auto m=abba_family::parse_request(std::string(reinterpret_cast<const char*>(b.data()+20),size_t(le(b.data()+8,4))));
    require(m.at("sample_counts")==Json::array({rows}),"encoder sample count mismatch");
    // No input-dependent admission fit is done outside the clock. Check the
    // actual released reconstruction before committing an encodable object.
    auto recovered=abba_family::decode(b.data(),b.size()).at("reconstructed");
    if(recovered.size()!=rows)throw tsbench_core::Unsupported("SOURCE_RECONSTRUCTED_LENGTH_DIFFERS_FROM_GRID");
    return b;
}
std::vector<double> decode_one(const uint8_t* p,size_t n,size_t expected=0){fp();auto result=abba_family::decode(p,n);require(result.at("algorithm")==AF_KEY,"frame algorithm mismatch");const auto& m=result.at("model");require(m.at("single")==true&&m.at("sample_counts").size()==1,"single series required");const size_t rows=m.at("sample_counts")[0].get<size_t>();geometry(rows,1);if(expected)require(rows==expected,"frame/task sample mismatch");auto out=result.at("reconstructed").get<std::vector<double>>();if(out.size()!=rows)throw tsbench_core::Unsupported("SOURCE_RECONSTRUCTED_LENGTH_DIFFERS_FROM_GRID");for(auto x:out)require(std::isfinite(x),"nonfinite reconstruction");return out;}
Bytes encode_columns(const uint8_t* p,size_t rows,size_t cols,const Json& c){
    geometry(rows,cols);finite_input(p,rows*cols*8);if(cols==1)return encode_one(p,rows,c);
    Bytes b; b.insert(b.end(),{'A','F','M','1'});put(b,1,4);put(b,rows,8);put(b,cols,8);
    for(size_t j=0;j<cols;++j){auto f=encode_one(p+j*rows*8,rows,c);if(f.size()>max_frame-b.size()-12)throw tsbench_core::Unsupported("matrix frame limit");put(b,f.size(),8);b.insert(b.end(),f.begin(),f.end());}
    put(b,crc32(0,b.data(),static_cast<uInt>(b.size())),4);return b;
}
std::vector<double> decode_columns(const uint8_t* p,size_t n){
    require(p&&n>=4&&n<=max_frame,"frame length");if(!std::memcmp(p,"AFS1",4))return decode_one(p,n);
    require(n>=28&&!std::memcmp(p,"AFM1",4)&&le(p+4,4)==1,"matrix magic/version");
    require(le(p+n-4,4)==crc32(0,p,static_cast<uInt>(n-4)),"matrix CRC");const size_t rows=size_t(le(p+8,8)),cols=size_t(le(p+16,8));geometry(rows,cols);require(cols>1,"matrix column count");
    std::vector<double> values;values.reserve(rows*cols);size_t at=24;
    for(size_t j=0;j<cols;++j){require(n-4-at>=8,"truncated column length");size_t size=size_t(le(p+at,8));at+=8;require(size<=n-4-at,"truncated column frame");auto v=decode_one(p+at,size,rows);values.insert(values.end(),v.begin(),v.end());at+=size;}
    require(at==n-4,"trailing matrix bytes");return values;
}
struct Core{Json config;size_t rows{};bool decoder{};char error[256]{};};
thread_local char core_error[256]{};
template<class F>int guard(Core* s,F f)noexcept{int code=1;try{f();return 0;}catch(const tsbench_core::Unsupported& e){std::snprintf(core_error,sizeof(core_error),"%s",e.what());code=2;}catch(const tsbench_core::Capacity& e){std::snprintf(core_error,sizeof(core_error),"%s",e.what());code=3;}catch(const std::exception& e){std::snprintf(core_error,sizeof(core_error),"%s",e.what());}catch(...){std::snprintf(core_error,sizeof(core_error),"family binding failure");}if(s)std::snprintf(s->error,sizeof(s->error),"%s",core_error);return code;}
}
extern "C" uint32_t tsbench_core_version(){return 1;}
extern "C" uint32_t tsbench_core_storage(){return 0;}
extern "C" int tsbench_core_create(const tsbench_core_config* cfg,int decoder,void** out){if(out)*out=nullptr;return guard(nullptr,[&]{require(cfg&&out&&(decoder==0||decoder==1),"invalid core config");tsbench_core::elements(*cfg);if(cfg->rank!=1||cfg->dtype!=TSCB_DTYPE_F64_LE_V1)throw tsbench_core::Unsupported("ABBA family core requires rank1 binary64");require(!cfg->model||!*cfg->model,"no external model allowed");fp();geometry(cfg->shape[0],1);auto p=std::make_unique<Core>();p->rows=cfg->shape[0];p->decoder=decoder!=0;if(decoder){auto j=abba_family::parse_request(cfg->parameters_json?cfg->parameters_json:"{}");require(j.is_object()&&j.empty(),"decoder parameters must be empty");}else p->config=settings(cfg->parameters_json);*out=p.release();});}
extern "C" int tsbench_core_destroy(void* p){delete static_cast<Core*>(p);return 0;}
extern "C" int tsbench_core_validate_input(void* p,const uint8_t* in,size_t n){auto s=static_cast<Core*>(p);return guard(s,[&]{require(s&&n==s->rows*8,"input extent mismatch");finite_input(in,n);});}
extern "C" int tsbench_core_bound(void* p,const uint8_t*,size_t n,size_t* out){if(out)*out=0;auto s=static_cast<Core*>(p);return guard(s,[&]{require(s&&out&&n==s->rows*8,"bound extent mismatch");*out=bound(s->rows,1);});}
extern "C" int tsbench_core_encode(void* p,const uint8_t* in,size_t n,uint8_t*,size_t,tsbench_core_result* r){if(r)*r={};auto s=static_cast<Core*>(p);return guard(s,[&]{require(s&&!s->decoder&&r&&n==s->rows*8,"encode extent/state mismatch");tsbench_core::vector_result(encode_one(in,s->rows,s->config),r);});}
extern "C" int tsbench_core_decode(void* p,const uint8_t* in,size_t n,uint8_t*,size_t,tsbench_core_result* r){if(r)*r={};auto s=static_cast<Core*>(p);return guard(s,[&]{require(s&&s->decoder&&r,"decode state mismatch");tsbench_core::vector_result(decode_one(in,n,s->rows),r);});}
extern "C" void tsbench_core_release(tsbench_core_result* r){tsbench_core::release(r);}
extern "C" const char* tsbench_core_error(void* p){return p?static_cast<Core*>(p)->error:core_error;}

struct tscb_codec_handle_v1{tscb_native_timer native_timer{};Json config;bool updated=false,finalized=false;size_t input_bytes{},stream_bytes{};char error[256]{};std::string accounting;};
namespace {
template<class F>tscb_status_v1 api_guard(tscb_codec_handle_v1* h,F f)noexcept{try{f();return TSCB_STATUS_OK_V1;}catch(const tsbench_core::Unsupported& e){if(h)std::snprintf(h->error,sizeof(h->error),"%s",e.what());return TSCB_STATUS_UNSUPPORTED_V1;}catch(const tsbench_core::Capacity& e){if(h)std::snprintf(h->error,sizeof(h->error),"%s",e.what());return TSCB_STATUS_DST_TOO_SMALL_V1;}catch(const std::exception& e){if(h)std::snprintf(h->error,sizeof(h->error),"%s",e.what());return TSCB_STATUS_CODEC_ERROR_V1;}catch(...){return TSCB_STATUS_CODEC_ERROR_V1;}}
bool valid(const tscb_buffer_v1* b){return b&&b->dtype==TSCB_DTYPE_BYTES_V1&&b->rank==1&&b->strides_bytes[0]==1&&b->used_bytes<=b->capacity_bytes&&b->capacity_bytes<=SIZE_MAX&&(!b->capacity_bytes||b->data);}
struct Input{const uint8_t* p;size_t rows,cols;};
Input input_view(const tscb_buffer_v1* b){require(valid(b)&&b->used_bytes>=24,"invalid input descriptor");auto p=static_cast<const uint8_t*>(b->data);require(!std::memcmp(p,"AFI1",4)&&le(p+4,4)==1,"input magic/version");size_t rows=size_t(le(p+8,8)),cols=size_t(le(p+16,8));geometry(rows,cols);require(b->used_bytes-24==rows*cols*8,"input size mismatch");return {p+24,rows,cols};}
void commit(const void* p,size_t n,tscb_buffer_v1* b){if(n>b->capacity_bytes)throw tsbench_core::Capacity("output capacity too small");if(n)std::memmove(b->data,p,n);b->used_bytes=n;}
}
extern "C" {
uint32_t tscb_get_abi_version(){return 1;}
tscb_status_v1 tscb_get_manifest_json(const char** p,uint64_t* n){if(!p||!n)return TSCB_STATUS_INVALID_ARGUMENT_V1;*p=manifest;*n=sizeof(manifest)-1;return TSCB_STATUS_OK_V1;}
tscb_status_v1 tscb_create(const char* json,uint64_t length,tscb_codec_handle_v1** out){if(!out)return TSCB_STATUS_INVALID_ARGUMENT_V1;*out=nullptr;if(!json||length>16384)return TSCB_STATUS_INVALID_ARGUMENT_V1;return api_guard(nullptr,[&]{std::string s(json,size_t(length));require(s.find('\0')==std::string::npos,"embedded NUL");auto c=settings(s.c_str(),true);fp();auto h=std::make_unique<tscb_codec_handle_v1>();h->config=std::move(c);*out=h.release();});}
tscb_status_v1 tscb_destroy(tscb_codec_handle_v1* h){delete h;return TSCB_STATUS_OK_V1;}
tscb_status_v1 tscb_reset(tscb_codec_handle_v1* h,uint32_t mode){if(!h||mode)return TSCB_STATUS_INVALID_ARGUMENT_V1;h->updated=h->finalized=false;h->input_bytes=h->stream_bytes=0;h->error[0]=0;h->accounting.clear();h->native_timer.encode_ns=h->native_timer.decode_ns=0;return TSCB_STATUS_OK_V1;}
TSCB_NATIVE_TIMING_API
tscb_status_v1 tscb_compress_bound(tscb_codec_handle_v1* h,const tscb_buffer_v1* in,uint64_t* out){if(!h||!out)return TSCB_STATUS_INVALID_ARGUMENT_V1;*out=0;return api_guard(h,[&]{auto v=input_view(in);*out=bound(v.rows,v.cols);});}
tscb_status_v1 tscb_compress(tscb_codec_handle_v1* h,const tscb_buffer_v1* in,tscb_buffer_v1* out){if(!h||!valid(in)||!valid(out))return TSCB_STATUS_INVALID_ARGUMENT_V1;out->used_bytes=0;if(h->updated||h->finalized)return TSCB_STATUS_INVALID_ARGUMENT_V1;return api_guard(h,[&]{auto v=input_view(in);Bytes b;TSCB_TIME_CODEC(h->native_timer,encode_ns,b=encode_columns(v.p,v.rows,v.cols,h->config));commit(b.data(),b.size(),out);h->input_bytes=v.rows*v.cols*8;h->stream_bytes=b.size();h->updated=true;});}
tscb_status_v1 tscb_finalize(tscb_codec_handle_v1* h,tscb_buffer_v1* out){if(!h||!valid(out))return TSCB_STATUS_INVALID_ARGUMENT_V1;out->used_bytes=0;if(!h->updated)return TSCB_STATUS_FINALIZE_REQUIRED_V1;if(h->finalized)return TSCB_STATUS_CODEC_ERROR_V1;return api_guard(h,[&]{h->accounting="{\"frame_bytes\":"+std::to_string(h->stream_bytes)+",\"input_bytes\":"+std::to_string(h->input_bytes)+",\"external_side_information_bits\":0,\"finalize_calls\":1}";h->finalized=true;});}
tscb_status_v1 tscb_decompress(tscb_codec_handle_v1* h,const tscb_buffer_v1* in,tscb_buffer_v1* out){if(!h||!valid(in)||!valid(out))return TSCB_STATUS_INVALID_ARGUMENT_V1;out->used_bytes=0;return api_guard(h,[&]{std::vector<double> v;TSCB_TIME_CODEC(h->native_timer,decode_ns,v=decode_columns(static_cast<const uint8_t*>(in->data),in->used_bytes));commit(v.data(),v.size()*8,out);});}
tscb_status_v1 tscb_query(tscb_codec_handle_v1*,const char*,uint64_t,char*,uint64_t,uint64_t* out){if(out)*out=0;return TSCB_STATUS_UNSUPPORTED_V1;}
tscb_status_v1 tscb_get_accounting_json(tscb_codec_handle_v1* h,const char** p,uint64_t* n){if(!h||!p||!n||!h->finalized)return TSCB_STATUS_INVALID_ARGUMENT_V1;*p=h->accounting.c_str();*n=h->accounting.size();return TSCB_STATUS_OK_V1;}
tscb_status_v1 tscb_get_last_error(tscb_codec_handle_v1* h,const char** p,uint64_t* n){if(!h||!p||!n)return TSCB_STATUS_INVALID_ARGUMENT_V1;*p=h->error;*n=std::strlen(h->error);return TSCB_STATUS_OK_V1;}
}
