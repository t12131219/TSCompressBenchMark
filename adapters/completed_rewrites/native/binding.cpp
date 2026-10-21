#include "binding.hpp"
#include <cstring>
#include <cmath>
#include <fstream>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <vector>
#if RW_KIND == 7
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
#if RW_KIND == 7
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
#if RW_KIND == 7
  auto model=deepzip::Model::load(read_model(c.model));deepzip::Config s;s.lanes=c.a;
  for(unsigned i=0;i<model.alphabet_size();++i)s.alphabet.push_back(static_cast<std::uint8_t>(i));
  return deepzip::compress(model,Bytes(p,p+size),s).bytes;
#elif RW_KIND == 8
  auto model=c.model && *c.model ? dzip::Network::load(read_model(c.model)) : dzip::Network::create(input_alphabet(p,size),c.mode?dzip::ModelProfile::combined_cpu:dzip::ModelProfile::bootstrap_cpu,c.seed);
  return dzip::compress(Bytes(p,p+size),model,c.mode?dzip::Mode::combined:dzip::Mode::bootstrap).bytes;
#endif
}
static Bytes decode(const std::uint8_t* p,std::size_t size,std::size_t capacity) {
#if RW_KIND == 7
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

// Direct algorithm entry. The historical RW entry points above retain their
// original contract; no RW column envelope or RW caller-buffer copy is used here.
#include "tsbench_core.hpp"
#include <memory>

namespace {
struct CoreModelState final : tsbench_core::State {
  bool decoder = false;
  std::size_t rows = 0, bytes = 0;
#if RW_KIND == 7
  deepzip::Config config;
  std::unique_ptr<deepzip::Model> model;
#elif RW_KIND == 8
  dzip::Mode mode = dzip::Mode::bootstrap;
  std::uint32_t seed = 0;
  std::unique_ptr<dzip::Network> fixed_model;
#endif
};
CoreModelState* core_model_state(void* context) {
  tsbench_core::require(context != nullptr, "null direct model context");
  return static_cast<CoreModelState*>(context);
}
void core_model_input(const CoreModelState& state, const std::uint8_t* p,
                      std::size_t size) {
  tsbench_core::require(size == state.bytes && (p || !size),
                        "direct model input extent differs from task");
}
std::uint64_t core_model_u64(const std::uint8_t* p) {
  std::uint64_t result = 0;
  for (unsigned i = 0; i < 8; ++i) result |= std::uint64_t(p[i]) << (8*i);
  return result;
}
#if RW_KIND == 8
dzip::Network core_model_initial(const CoreModelState& state, const std::uint8_t* p,
                                  std::size_t size) {
  const unsigned alphabet = input_alphabet(p, size);
  if (alphabet == 9) throw tsbench_core::Unsupported("DZip MODEL_ALPHABET_UNSUPPORTED");
  if (state.fixed_model) {
    if (size && alphabet != state.fixed_model->alphabet())
      throw tsbench_core::Unsupported("input alphabet differs from fixed DZip model");
    return *state.fixed_model;
  }
  // The default model shape depends on this input. Never cache it in prepared
  // state: seeded initialization and its reset occur on every encode call.
  return dzip::Network::create(alphabet, state.mode == dzip::Mode::combined
      ? dzip::ModelProfile::combined_cpu : dzip::ModelProfile::bootstrap_cpu, state.seed);
}
#endif
}
extern "C" std::uint32_t tsbench_core_version() { return 1; }
extern "C" std::uint32_t tsbench_core_storage() { return 0; }
extern "C" int tsbench_core_create(const tsbench_core_config* c, int decoder, void** out) {
  return tsbench_core::guard(nullptr, [&] {
    tsbench_core::require(c && out, "null direct model configuration");
    *out = nullptr;
    if (c->rank != 1) throw tsbench_core::Unsupported("RW direct core currently requires rank1");
    if (c->dtype != TSCB_DTYPE_U8_V1)
      throw tsbench_core::Unsupported("DeepZip/DZip direct core requires uint8 symbols");
    auto state = std::make_unique<CoreModelState>();
    state->decoder = decoder != 0;
    state->rows = tsbench_core::elements(*c);
    state->bytes = tsbench_core::input_bytes(*c);
    if (state->rows > 16777216)
      throw tsbench_core::Unsupported("direct model input exceeds 16M element contract");
    const tsbench_core::Parameters parameters(c->parameters_json);
    if (state->decoder) {
      tsbench_core::require(parameters.empty() && (!c->model || !*c->model),
                            "direct decoder must not receive encoder parameters or model");
    } else {
#if RW_KIND == 7
      state->config.lanes = parameters.integer("lanes", 1, 4096);
      if (parameters.contains("isa") && parameters.string("isa") != "SCALAR")
        throw tsbench_core::Unsupported("DeepZip direct core only supports the scalar backend");
      state->model = std::make_unique<deepzip::Model>(deepzip::Model::load(read_model(c->model)));
      for (unsigned i = 0; i < state->model->alphabet_size(); ++i)
        state->config.alphabet.push_back(static_cast<std::uint8_t>(i));
#elif RW_KIND == 8
      const auto mode = parameters.string("mode");
      if (mode == "BOOTSTRAP") state->mode = dzip::Mode::bootstrap;
      else if (mode == "COMBINED") state->mode = dzip::Mode::combined;
      else throw tsbench_core::Unsupported("unknown DZip mode");
      state->seed = parameters.integer("model_seed", 0, UINT32_MAX);
      if (parameters.contains("initial_model") && parameters.string("initial_model") !=
          "NATIVE_SEEDED_UNTRAINED_INPUT_ALPHABET")
        throw tsbench_core::Unsupported("unknown DZip initial model policy");
      if (parameters.contains("isa") && parameters.string("isa") != "AVX")
        throw tsbench_core::Unsupported("DZip numerical profile requires AVX");
      if (c->model && *c->model)
        state->fixed_model = std::make_unique<dzip::Network>(dzip::Network::load(read_model(c->model)));
#endif
    }
    *out = state.release();
  });
}
extern "C" int tsbench_core_destroy(void* context) {
  delete static_cast<CoreModelState*>(context); return 0;
}
extern "C" int tsbench_core_validate_input(void* context, const std::uint8_t* p,
                                           std::size_t size) {
  auto* state = static_cast<CoreModelState*>(context);
  return tsbench_core::guard(state, [&] {
    state = core_model_state(context);
    tsbench_core::require(!state->decoder, "input admission requires an encoder context");
    core_model_input(*state, p, size);
#if RW_KIND == 7
    for (std::size_t i = 0; i < size; ++i)
      if (p[i] >= state->model->alphabet_size())
        throw tsbench_core::Unsupported("DeepZip MODEL_ALPHABET_UNSUPPORTED");
#endif
  });
}
extern "C" int tsbench_core_bound(void* context, const std::uint8_t* p,
                                   std::size_t size, std::size_t* output) {
  auto* state = static_cast<CoreModelState*>(context);
  return tsbench_core::guard(state, [&] {
    state = core_model_state(context);
    tsbench_core::require(output && !state->decoder, "invalid direct model bound request");
    core_model_input(*state, p, size);
#if RW_KIND == 7
    *output = deepzip::compress_bound(*state->model, size, state->config);
#elif RW_KIND == 8
    // This temporary bound model is discarded. Encode must create its own
    // input-dependent initial state; prepared never reuses this work.
    auto initial = core_model_initial(*state, p, size);
    *output = dzip::compress_bound(size, initial);
#endif
  });
}
extern "C" int tsbench_core_encode(void* context, const std::uint8_t* p,
    std::size_t size, std::uint8_t*, std::size_t capacity, tsbench_core_result* result) {
  auto* state = static_cast<CoreModelState*>(context);
  return tsbench_core::guard(state, [&] {
    state = core_model_state(context);
    tsbench_core::require(result && !state->decoder, "invalid direct model encode request");
    *result = {};
    core_model_input(*state, p, size);
    Bytes encoded;
#if RW_KIND == 7
    // The native API requires a vector input. Its materialization is timed;
    // the returned complete native frame transfers without the RW output copy.
    const Bytes input = size ? Bytes(p, p + size) : Bytes{};
    encoded = deepzip::compress(*state->model, input, state->config).bytes;
#elif RW_KIND == 8
    auto initial = core_model_initial(*state, p, size);
    const Bytes input = size ? Bytes(p, p + size) : Bytes{};
    encoded = dzip::compress(input, initial, state->mode).bytes;
#endif
    if (encoded.size() > capacity) throw tsbench_core::Capacity("direct model encoded output exceeds capacity");
    tsbench_core::vector_result(std::move(encoded), result);
  });
}
extern "C" int tsbench_core_decode(void* context, const std::uint8_t* p,
    std::size_t size, std::uint8_t*, std::size_t capacity, tsbench_core_result* result) {
  auto* state = static_cast<CoreModelState*>(context);
  return tsbench_core::guard(state, [&] {
    state = core_model_state(context);
    tsbench_core::require(result && state->decoder && p,
                          "invalid direct model decode request");
    *result = {};
    if (capacity < state->bytes) throw tsbench_core::Capacity("direct model decoded output exceeds capacity");
#if RW_KIND == 7
    tsbench_core::require(size >= 24 && core_model_u64(p + 16) == state->rows,
                          "direct DeepZip frame count differs from task");
    auto decoded = deepzip::decompress(Bytes(p, p + size));
#elif RW_KIND == 8
    tsbench_core::require(size >= 20 && core_model_u64(p + 12) == state->rows,
                          "direct DZip frame count differs from task");
    auto decoded = dzip::decompress(Bytes(p, p + size));
#endif
    tsbench_core::require(decoded.size() * sizeof(decoded[0]) == state->bytes,
                          "direct model decoded extent differs from task");
    tsbench_core::vector_result(std::move(decoded), result);
  });
}
extern "C" void tsbench_core_release(tsbench_core_result* result) { tsbench_core::release(result); }
extern "C" const char* tsbench_core_error(void* context) {
  return context ? static_cast<CoreModelState*>(context)->error.c_str()
                 : tsbench_core::last_error().c_str();
}
