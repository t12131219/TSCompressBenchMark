/* Checked lifecycle around unmodified official cuSZp FIXED CUDA kernels.
 * No compression algorithm, CPU fallback, or benchmark clock is implemented here.
 */
#include "cuszp_gpu.h"
#include <cuda_runtime.h>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

__global__ void cuSZp_compress_kernel_1D_fixed_f32(const float*, unsigned char*, volatile unsigned int*, volatile unsigned int*, volatile int*, float, size_t);
__global__ void cuSZp_decompress_kernel_1D_fixed_f32(float*, const unsigned char*, volatile unsigned int*, volatile unsigned int*, volatile int*, float, size_t);
__global__ void cuSZp_compress_kernel_1D_fixed_f64(const double*, unsigned char*, volatile unsigned int*, volatile unsigned int*, volatile int*, double, size_t);
__global__ void cuSZp_decompress_kernel_1D_fixed_f64(double*, const unsigned char*, volatile unsigned int*, volatile unsigned int*, volatile int*, double, size_t);

namespace {
thread_local std::string last_error;
/* Current calling thread's checked adapter objects, not CUDA context allocations. */
struct Diagnostics {uint64_t encode_launches=0,decode_launches=0,allocations=0,releases=0,live_bytes=0,streams_created=0,streams_released=0,events_created=0,events_released=0;} ;
thread_local Diagnostics diagnostics;
struct Error : std::runtime_error { uint32_t status; Error(uint32_t s, const std::string& m):std::runtime_error(m),status(s){} };
void require(bool ok, uint32_t status, const char* message) { if(!ok) throw Error(status,message); }
void checked(cudaError_t code, const char* operation) {
  if(code != cudaSuccess) throw Error(code==cudaErrorMemoryAllocation ? 5u : code==cudaErrorNoDevice || code==cudaErrorInsufficientDriver ? 6u : 4u,
      std::string(operation)+": "+cudaGetErrorName(code)+": "+cudaGetErrorString(code));
}
template<class F> uint32_t api(F f) {
  last_error.clear();
  try { f(); return 0; } catch(const Error& e) { last_error=e.what(); return e.status; }
  catch(const std::bad_alloc&) { last_error="host allocation failed";return 5; }
  catch(const std::exception& e) { last_error=e.what();return 4; }
}
constexpr uint64_t MAX_N=16777216, TILE=32768;
uint64_t grid(uint64_t n) {return (n+TILE-1)/TILE;}
uint64_t rate_bytes(uint64_t n) {return grid(n)*1024;}
uint64_t bound(uint64_t n) {return rate_bytes(n)*125;}
uint64_t itemsize(uint32_t dtype) {return dtype==4?4:8;}
double config(uint32_t dtype, uint64_t n, double eb) {
  require(dtype==4 || dtype==8,2,"dtype must be float32 or float64");
  require(n>0 && n<=MAX_N,2,"cuSZp FIXED supports 1..16777216 elements in this adapter");
  require(std::isfinite(eb) && eb>0,2,"error bound must be finite and positive");
  const double actual=dtype==4?static_cast<double>(static_cast<float>(eb)):eb;
  require(actual==eb,2,"float32 error bound must already be canonicalized to exactly representable float32");
  require(std::isnormal(actual) && std::isfinite(dtype==4 ? double(0.5f/static_cast<float>(actual)) : 0.5/actual),2,"error bound or reciprocal is outside normal finite domain");
  return actual;
}
template<class T> void source(const void* host, uint64_t n, double eb) {
  const T* x=static_cast<const T*>(host);
  for(uint64_t i=0;i<n;++i) {
    T v;std::memcpy(&v,reinterpret_cast<const unsigned char*>(x)+i*sizeof(T),sizeof(T));
    require(std::isfinite(v) && (v==0 || std::isnormal(v)) && !(v==0 && std::signbit(v)),2,
            "source must contain finite normal values or positive zero; no negative zero/subnormal/NaN/infinity");
    require(std::fabs(static_cast<long double>(v))/(2*static_cast<long double>(eb)) <= (uint64_t(1)<<28),2,
            "source quantization magnitude exceeds conservative signed-int domain");
  }
}
void source(uint32_t dtype,uint64_t n,double eb,const void* host,uint64_t nbytes) {
  require(host && nbytes==n*itemsize(dtype),1,"source byte count differs from typed configuration");
  if(dtype==4) source<float>(host,n,eb);else source<double>(host,n,eb);
}
void rates(const unsigned char* p,uint64_t n,uint64_t bytes) {
  require(p && bytes>=rate_bytes(n) && bytes<=bound(n),1,"payload length outside source-grounded capacity");
  uint64_t expected=rate_bytes(n);
  for(uint64_t i=0;i<rate_bytes(n);++i) {
    require(p[i]<=30,1,"invalid FIXED block width");
    if(i*32>=n) require(p[i]==0,1,"padding-only FIXED block has nonzero width");
    if(p[i]) expected+=4+4*p[i];
  }
  require(expected==bytes,1,"payload length does not match FIXED rate table");
}
struct Stream {
  cudaStream_t value=nullptr;
  Stream() {checked(cudaStreamCreateWithFlags(&value,cudaStreamNonBlocking),"cudaStreamCreateWithFlags");++diagnostics.streams_created;}
  void close(){if(value){auto x=value;value=nullptr;auto sync=cudaStreamSynchronize(x);auto destroy=cudaStreamDestroy(x);if(destroy==cudaSuccess)++diagnostics.streams_released;checked(sync,"cudaStreamSynchronize(close)");checked(destroy,"cudaStreamDestroy");}}
  ~Stream(){if(value){cudaStreamSynchronize(value);if(cudaStreamDestroy(value)==cudaSuccess)++diagnostics.streams_released;}}
};
struct Memory {
  void* value=nullptr;uint64_t capacity=0;
  explicit Memory(uint64_t bytes=0):capacity(bytes){if(bytes){checked(cudaMalloc(&value,bytes),"cudaMalloc");++diagnostics.allocations;diagnostics.live_bytes+=bytes;}}
  void close(){if(value){auto x=value;value=nullptr;checked(cudaFree(x),"cudaFree");++diagnostics.releases;diagnostics.live_bytes-=capacity;}}
  void* detach(){auto x=value;value=nullptr;return x;}
  ~Memory(){if(value && cudaFree(value)==cudaSuccess){++diagnostics.releases;diagnostics.live_bytes-=capacity;}}
};
struct Events {
  cudaEvent_t start=nullptr,stop=nullptr;
  Events(){checked(cudaEventCreate(&start),"cudaEventCreate(start)");++diagnostics.events_created;try{checked(cudaEventCreate(&stop),"cudaEventCreate(stop)");++diagnostics.events_created;}catch(...){if(cudaEventDestroy(start)==cudaSuccess)++diagnostics.events_released;start=nullptr;throw;}}
  double finish(cudaStream_t stream){checked(cudaEventRecord(stop,stream),"cudaEventRecord(stop)");checked(cudaEventSynchronize(stop),"cudaEventSynchronize(stop)");float ms;checked(cudaEventElapsedTime(&ms,start,stop),"cudaEventElapsedTime");return ms;}
  void close(){if(start){auto x=start;start=nullptr;checked(cudaEventDestroy(x),"cudaEventDestroy(start)");++diagnostics.events_released;}if(stop){auto x=stop;stop=nullptr;checked(cudaEventDestroy(x),"cudaEventDestroy(stop)");++diagnostics.events_released;}}
  ~Events(){if(start && cudaEventDestroy(start)==cudaSuccess)++diagnostics.events_released;if(stop && cudaEventDestroy(stop)==cudaSuccess)++diagnostics.events_released;}
};
struct Session {int device;uint32_t dtype;uint64_t n;double eb;Stream stream;Session(int d,uint32_t t,uint64_t c,double e):device(d),dtype(t),n(c),eb(e){} };
enum class Kind {input,payload,decoded};
struct Owner {Kind kind;int device;uint32_t dtype;uint64_t n;double eb;void* ptr;uint64_t bytes,capacity;tsgpu_info_v1 info;};
struct Scratch {
  Memory offsets,locals,flags;uint64_t bytes;
  explicit Scratch(uint64_t n):offsets((grid(n)+1)*4),locals((grid(n)+1)*4),flags((grid(n)+1)*4),bytes((grid(n)+1)*12){}
  void zero(cudaStream_t s){checked(cudaMemsetAsync(offsets.value,0,bytes/3,s),"cudaMemsetAsync(offsets)");checked(cudaMemsetAsync(locals.value,0,bytes/3,s),"cudaMemsetAsync(locals)");checked(cudaMemsetAsync(flags.value,0,bytes/3,s),"cudaMemsetAsync(flags)");}
  void close(){offsets.close();locals.close();flags.close();}
};
tsgpu_info_v1 info(const Session* s,uint64_t payload,uint64_t scratch,uint64_t input,uint64_t output,uint64_t capacity,uint64_t peak,double ms){
  return {sizeof(tsgpu_info_v1),1,uint32_t(s->device),s->dtype,s->n,s->eb,payload,scratch,input,output,capacity,peak,ms};
}
void match(Session* s,Owner* o,Kind kind){require(s&&o,1,"null session or owner");require(o->kind==kind,1,"device owner kind differs from operation");require(s->device==o->device && s->dtype==o->dtype && s->n==o->n && s->eb==o->eb,1,"owner configuration differs from independent session");checked(cudaSetDevice(s->device),"cudaSetDevice");}
Owner* encode(Session* s,const void* input,bool host_input){
  require(s && input,1,"null encoder session or input");checked(cudaSetDevice(s->device),"cudaSetDevice");
  const auto raw=s->n*itemsize(s->dtype);
  if(host_input)source(s->dtype,s->n,s->eb,input,raw);
  Memory in(host_input?raw:0),out(bound(s->n));Scratch scratch(s->n);Events event;
  std::vector<unsigned char> table(rate_bytes(s->n));unsigned int size=0;
  checked(cudaEventRecord(event.start,s->stream.value),"cudaEventRecord(start)");scratch.zero(s->stream.value);
  if(host_input)checked(cudaMemcpyAsync(in.value,input,raw,cudaMemcpyHostToDevice,s->stream.value),"cudaMemcpyAsync(input H2D)");
  const void* d=host_input?in.value:input;
  if(s->dtype==4)cuSZp_compress_kernel_1D_fixed_f32<<<unsigned(grid(s->n)),32,8,s->stream.value>>>(static_cast<const float*>(d),static_cast<unsigned char*>(out.value),static_cast<unsigned int*>(scratch.offsets.value),static_cast<unsigned int*>(scratch.locals.value),static_cast<int*>(scratch.flags.value),float(s->eb),s->n);
  else cuSZp_compress_kernel_1D_fixed_f64<<<unsigned(grid(s->n)),32,8,s->stream.value>>>(static_cast<const double*>(d),static_cast<unsigned char*>(out.value),static_cast<unsigned int*>(scratch.offsets.value),static_cast<unsigned int*>(scratch.locals.value),static_cast<int*>(scratch.flags.value),s->eb,s->n);
  checked(cudaGetLastError(),"cuSZp FIXED encode launch");
  ++diagnostics.encode_launches;
  /* A single upstream warp publishes locOffset[1], but only warp>0 writes
   * the final global cmpOffset. Read the local total for a one-tile grid. */
  const auto total=grid(s->n)==1?scratch.locals.value:scratch.offsets.value;
  checked(cudaMemcpyAsync(&size,static_cast<unsigned int*>(total)+grid(s->n),4,cudaMemcpyDeviceToHost,s->stream.value),"cudaMemcpyAsync(size D2H)");
  checked(cudaMemcpyAsync(table.data(),out.value,table.size(),cudaMemcpyDeviceToHost,s->stream.value),"cudaMemcpyAsync(rate table D2H)");
  const double ms=event.finish(s->stream.value);checked(cudaStreamSynchronize(s->stream.value),"cudaStreamSynchronize(encode)");
  const uint64_t bytes=uint64_t(size)+table.size();rates(table.data(),s->n,bytes);
  event.close();scratch.close();in.close();
  auto o=new Owner{Kind::payload,s->device,s->dtype,s->n,s->eb,nullptr,bytes,bound(s->n),info(s,bytes,scratch.bytes,raw,bytes,bound(s->n),bound(s->n)+scratch.bytes+(host_input?raw:0),ms)};o->ptr=out.detach();return o;
}
Owner* decode(Session* s,Owner* payload){
  match(s,payload,Kind::payload);const auto raw=s->n*itemsize(s->dtype);Memory out(raw);Scratch scratch(s->n);Events event;
  checked(cudaEventRecord(event.start,s->stream.value),"cudaEventRecord(start)");scratch.zero(s->stream.value);
  checked(cudaMemsetAsync(out.value,0,raw,s->stream.value),"cudaMemsetAsync(decoded positive-zero blocks)");
  if(s->dtype==4)cuSZp_decompress_kernel_1D_fixed_f32<<<unsigned(grid(s->n)),32,8,s->stream.value>>>(static_cast<float*>(out.value),static_cast<const unsigned char*>(payload->ptr),static_cast<unsigned int*>(scratch.offsets.value),static_cast<unsigned int*>(scratch.locals.value),static_cast<int*>(scratch.flags.value),float(s->eb),s->n);
  else cuSZp_decompress_kernel_1D_fixed_f64<<<unsigned(grid(s->n)),32,8,s->stream.value>>>(static_cast<double*>(out.value),static_cast<const unsigned char*>(payload->ptr),static_cast<unsigned int*>(scratch.offsets.value),static_cast<unsigned int*>(scratch.locals.value),static_cast<int*>(scratch.flags.value),s->eb,s->n);
  checked(cudaGetLastError(),"cuSZp FIXED decode launch");++diagnostics.decode_launches;const double ms=event.finish(s->stream.value);
  checked(cudaStreamSynchronize(s->stream.value),"cudaStreamSynchronize(decode)");event.close();scratch.close();
  auto o=new Owner{Kind::decoded,s->device,s->dtype,s->n,s->eb,nullptr,raw,raw,info(s,payload->bytes,scratch.bytes,payload->bytes,raw,raw,raw+scratch.bytes,ms)};o->ptr=out.detach();return o;
}
void release(void* p){require(p,1,"null owner");auto o=static_cast<Owner*>(p);checked(cudaSetDevice(o->device),"cudaSetDevice");auto status=cudaFree(o->ptr);if(status==cudaSuccess){++diagnostics.releases;diagnostics.live_bytes-=o->capacity;}delete o;checked(status,"cudaFree(output owner)");}
void copy(void* p,void* h,uint64_t capacity){require(p&&h,1,"null copy owner/destination");auto o=static_cast<Owner*>(p);require(capacity>=o->bytes,3,"destination too small");checked(cudaSetDevice(o->device),"cudaSetDevice");checked(cudaMemcpy(h,o->ptr,o->bytes,cudaMemcpyDeviceToHost),"cudaMemcpy(owner D2H)");checked(cudaDeviceSynchronize(),"cudaDeviceSynchronize(materialize)");}
void get_info(void* p,tsgpu_info_v1* out){require(p&&out && out->struct_size==sizeof(*out),1,"info ABI size mismatch");*out=static_cast<Owner*>(p)->info;}
} // namespace

extern "C" {
uint32_t tsgpu_abi_version(){return 1;}
const char* tsgpu_last_error(){return last_error.c_str();}
uint32_t tsgpu_diagnostics_json(const char** text){return api([&]{require(text,1,"null diagnostics output");static thread_local char result[1024];std::snprintf(result,sizeof(result),"{\"scope\":\"calling_thread_checked_adapter_objects\",\"encode_launches\":%llu,\"decode_launches\":%llu,\"allocations\":%llu,\"releases\":%llu,\"live_bytes\":%llu,\"streams_created\":%llu,\"streams_released\":%llu,\"events_created\":%llu,\"events_released\":%llu}",(unsigned long long)diagnostics.encode_launches,(unsigned long long)diagnostics.decode_launches,(unsigned long long)diagnostics.allocations,(unsigned long long)diagnostics.releases,(unsigned long long)diagnostics.live_bytes,(unsigned long long)diagnostics.streams_created,(unsigned long long)diagnostics.streams_released,(unsigned long long)diagnostics.events_created,(unsigned long long)diagnostics.events_released);*text=result;});}
uint32_t tsgpu_device_json(int device,const char** text){return api([&]{require(text,1,"null output");checked(cudaSetDevice(device),"cudaSetDevice");cudaDeviceProp p{};checked(cudaGetDeviceProperties(&p,device),"cudaGetDeviceProperties");int runtime=0,driver=0;checked(cudaRuntimeGetVersion(&runtime),"cudaRuntimeGetVersion");checked(cudaDriverGetVersion(&driver),"cudaDriverGetVersion");static thread_local char result[1024];std::snprintf(result,sizeof(result),"{\"device\":%d,\"name\":\"%s\",\"compute_major\":%d,\"compute_minor\":%d,\"total_memory_bytes\":%llu,\"multiprocessors\":%d,\"runtime_version\":%d,\"driver_api_version\":%d,\"stream_flags\":\"cudaStreamNonBlocking\",\"backend\":\"CUDA\"}",device,p.name,p.major,p.minor,(unsigned long long)p.totalGlobalMem,p.multiProcessorCount,runtime,driver);*text=result;});}
uint32_t tsgpu_create(int device,uint32_t dtype,uint64_t n,double eb,void** out){return api([&]{require(out,1,"null session output");*out=nullptr;eb=config(dtype,n,eb);checked(cudaSetDevice(device),"cudaSetDevice");*out=new Session(device,dtype,n,eb);});}
uint32_t tsgpu_close(void* p){return api([&]{require(p,1,"null session");auto s=static_cast<Session*>(p);try{checked(cudaSetDevice(s->device),"cudaSetDevice");s->stream.close();}catch(...){delete s;throw;}delete s;});}
uint32_t tsgpu_prepare_input(int d,uint32_t t,uint64_t n,double eb,const void* h,uint64_t bytes,void** out){return api([&]{require(out,1,"null input output");*out=nullptr;eb=config(t,n,eb);source(t,n,eb,h,bytes);checked(cudaSetDevice(d),"cudaSetDevice");Memory m(bytes);checked(cudaMemcpy(m.value,h,bytes,cudaMemcpyHostToDevice),"cudaMemcpy(prepared input H2D)");checked(cudaDeviceSynchronize(),"cudaDeviceSynchronize(prepared input)");auto o=new Owner{Kind::input,d,t,n,eb,nullptr,bytes,bytes,{}};o->ptr=m.detach();*out=o;});}
uint32_t tsgpu_release_input(void* p){return api([&]{release(p);});}
uint32_t tsgpu_copy_input(void* p,void* h,uint64_t c){return api([&]{copy(p,h,c);});}
uint32_t tsgpu_encode_host(void* p,const void* h,uint64_t bytes,void** out){return api([&]{require(p&&out,1,"null encode parameters");*out=nullptr;auto s=static_cast<Session*>(p);require(bytes==s->n*itemsize(s->dtype),1,"input byte count mismatch");*out=encode(s,h,true);});}
uint32_t tsgpu_encode_device(void* p,void* input,void** out){return api([&]{require(out,1,"null encode output");*out=nullptr;auto s=static_cast<Session*>(p);auto i=static_cast<Owner*>(input);match(s,i,Kind::input);*out=encode(s,i->ptr,false);});}
uint32_t tsgpu_install_payload(int d,uint32_t t,uint64_t n,double eb,const void* h,uint64_t bytes,void** out){return api([&]{require(out,1,"null payload output");*out=nullptr;eb=config(t,n,eb);rates(static_cast<const unsigned char*>(h),n,bytes);checked(cudaSetDevice(d),"cudaSetDevice");Memory m(bytes);checked(cudaMemcpy(m.value,h,bytes,cudaMemcpyHostToDevice),"cudaMemcpy(persisted payload H2D)");checked(cudaDeviceSynchronize(),"cudaDeviceSynchronize(installed payload)");auto o=new Owner{Kind::payload,d,t,n,eb,nullptr,bytes,bytes,{sizeof(tsgpu_info_v1),1,uint32_t(d),t,n,eb,bytes,0,bytes,bytes,bytes,bytes,0}};o->ptr=m.detach();*out=o;});}
uint32_t tsgpu_payload_info(void* p,tsgpu_info_v1* i){return api([&]{get_info(p,i);});}
uint32_t tsgpu_copy_payload(void* p,void* h,uint64_t c){return api([&]{copy(p,h,c);});}
uint32_t tsgpu_release_payload(void* p){return api([&]{release(p);});}
uint32_t tsgpu_decode_device(void* p,void* payload,void** out){return api([&]{require(out,1,"null decode output");*out=nullptr;*out=decode(static_cast<Session*>(p),static_cast<Owner*>(payload));});}
uint32_t tsgpu_decoded_info(void* p,tsgpu_info_v1* i){return api([&]{get_info(p,i);});}
uint32_t tsgpu_copy_decoded(void* p,void* h,uint64_t c){return api([&]{copy(p,h,c);});}
uint32_t tsgpu_release_decoded(void* p){return api([&]{release(p);});}
}
