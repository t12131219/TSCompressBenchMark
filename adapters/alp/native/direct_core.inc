// Complete native ALPRW001 objects, with caller storage on both operations.
namespace {
struct AlpCore : tsbench_core::State {
    size_t count{}, bytes{}; uint8_t width{}; bool decoder{};
};
}
extern "C" uint32_t tsbench_core_version() { return 1; }
extern "C" uint32_t tsbench_core_storage() { return 3; }
extern "C" int tsbench_core_create(const tsbench_core_config* config, int decoder, void** result) {
    if (result) *result=nullptr;
    return tsbench_core::guard(nullptr,[&] {
        tsbench_core::require(config && result,"null ALP direct configuration");
        tsbench_core::require(decoder==0 || decoder==1,"invalid ALP decoder flag");
        if(config->dtype!=TSCB_DTYPE_F32_LE_V1 && config->dtype!=TSCB_DTYPE_F64_LE_V1)
            throw tsbench_core::Unsupported("ALP requires IEEE binary32 or binary64");
        const size_t count=tsbench_core::elements(*config);
        if(count>ALP_PORT_MAX_VALUES)throw tsbench_core::Unsupported("ALP element limit");
        if(config->model && *config->model)throw tsbench_core::Unsupported("ALP has no external model");
        direct_parameters(config->parameters_json);
        auto state=std::make_unique<AlpCore>(); state->count=count; state->width=tsbench_core::width(config->dtype);
        state->bytes=tsbench_core::input_bytes(*config); state->decoder=decoder!=0; *result=state.release();
    });
}
extern "C" int tsbench_core_destroy(void* context) { delete static_cast<AlpCore*>(context); return 0; }
extern "C" int tsbench_core_bound(void* context, const uint8_t* input, size_t length, size_t* bound) {
    auto* state=static_cast<AlpCore*>(context); if(bound)*bound=0;
    return tsbench_core::guard(state,[&] {
        tsbench_core::require(state && bound && (!length || input) && length==state->bytes,"ALP direct input length mismatch");
        port_check(alp_port_bound(state->count,state->width,kMethod,bound));
    });
}
extern "C" int tsbench_core_encode(void* context, const uint8_t* input, size_t length,
                                    uint8_t* output, size_t capacity, tsbench_core_result* result) {
    auto* state=static_cast<AlpCore*>(context); if(result)*result={};
    return tsbench_core::guard(state,[&] {
        tsbench_core::require(state && !state->decoder && result && (!length || input) && length==state->bytes,"ALP direct input mismatch");
        size_t used=0; port_check(alp_port_encode(input,state->count,state->width,kMethod,output,capacity,&used));
        tsbench_core::caller_result(output,used,capacity,result);
    });
}
extern "C" int tsbench_core_decode(void* context, const uint8_t* input, size_t length,
                                    uint8_t* output, size_t capacity, tsbench_core_result* result) {
    auto* state=static_cast<AlpCore*>(context); if(result)*result={};
    return tsbench_core::guard(state,[&] {
        tsbench_core::require(state && state->decoder && input && result && length>=32,"truncated ALP native object");
        tsbench_core::require(!std::memcmp(input,"ALPRW001",8) && input[8]==state->width && input[9]==kMethod &&
            le(input+12,8)==state->count,"ALP task or method identity mismatch");
        if(capacity<state->bytes)throw tsbench_core::Capacity("ALP decoded output too small");
        size_t used=0,consumed=0; uint64_t count=0; uint8_t width=0,method=0;
        port_check(alp_port_decode(input,length,output,capacity,&used,&consumed,&count,&width,&method));
        tsbench_core::require(used==state->bytes && consumed==length && count==state->count && width==state->width && method==kMethod,"ALP decoded identity mismatch");
        tsbench_core::caller_result(output,used,capacity,result);
    });
}
extern "C" void tsbench_core_release(tsbench_core_result* result) { tsbench_core::release(result); }
extern "C" const char* tsbench_core_error(void* context) {
    return context ? static_cast<AlpCore*>(context)->error.c_str() : tsbench_core::last_error().c_str();
}
