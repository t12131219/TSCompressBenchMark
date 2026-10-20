// Owning vector API: staging, reset, strict checks and CFP1 work are timed.
namespace {
struct ChimpCore {Settings config;size_t count{},bytes{};bool decoder{};char error[256]{};};
thread_local char core_error[256]{};
template<class F> int core_guard(ChimpCore* state,F action)noexcept{
    const char* message=nullptr;int status=1;
    try{action();return 0;}
    catch(const tsbench_core::Unsupported& e){message=e.what();status=2;std::snprintf(core_error,sizeof(core_error),"%s",message);}
    catch(const tsbench_core::Capacity& e){message=e.what();status=3;std::snprintf(core_error,sizeof(core_error),"%s",message);}
    catch(const std::exception& e){std::snprintf(core_error,sizeof(core_error),"%s",e.what());}
    catch(...){std::snprintf(core_error,sizeof(core_error),"Chimp core binding failure");}
    if(state)std::snprintf(state->error,sizeof(state->error),"%s",core_error);
    return status;
}
}
extern "C" uint32_t tsbench_core_version(){return 1;}
extern "C" uint32_t tsbench_core_storage(){return 0;}
extern "C" int tsbench_core_create(const tsbench_core_config* cfg,int decoder,void** result){
    if(result)*result=nullptr;
    return core_guard(nullptr,[&]{need(cfg&&result&&(decoder==0||decoder==1),"invalid Chimp direct arguments");
        if(cfg->dtype!=(width==4?TSCB_DTYPE_F32_LE_V1:TSCB_DTYPE_F64_LE_V1))throw tsbench_core::Unsupported("Chimp method dtype mismatch; select its explicit 32/64-bit key");
        const auto count=tsbench_core::elements(*cfg);count_check(count);
        if(cfg->rank>2||(cfg->rank==2&&(!cfg->shape[1]|| (lossy&&cfg->shape[1]!=1))))throw tsbench_core::Unsupported("Chimp direct rank/profile mismatch; filters require one column");
        if(cfg->model&&*cfg->model)throw tsbench_core::Unsupported("Chimp has no external model");
        auto s=std::make_unique<ChimpCore>();s->config=settings(cfg->parameters_json);s->count=count;s->bytes=tsbench_core::input_bytes(*cfg);s->decoder=decoder!=0;*result=s.release();
    });
}
extern "C" int tsbench_core_destroy(void* context){delete static_cast<ChimpCore*>(context);return 0;}
extern "C" int tsbench_core_validate_input(void* context,const uint8_t* input,size_t length){
    auto* s=static_cast<ChimpCore*>(context);return core_guard(s,[&]{need(s&&(!length||input)&&length==s->bytes,"Chimp direct input length mismatch");validate_values(input,s->count);});
}
extern "C" int tsbench_core_bound(void* context,const uint8_t* input,size_t length,size_t* bound){
    if(bound)*bound=0;auto* s=static_cast<ChimpCore*>(context);return core_guard(s,[&]{need(s&&bound&&(!length||input)&&length==s->bytes,"Chimp direct bound input mismatch");*bound=stream_bound(s->config,s->count);});
}
extern "C" int tsbench_core_encode(void* context,const uint8_t* input,size_t length,uint8_t*,size_t,tsbench_core_result* result){
    if(result)*result={};auto* s=static_cast<ChimpCore*>(context);return core_guard(s,[&]{need(s&&!s->decoder&&result&&(!length||input)&&length==s->bytes,"Chimp direct encode mismatch");tsbench_core::vector_result(encode_stream(s->config,input,s->count),result);});
}
extern "C" int tsbench_core_decode(void* context,const uint8_t* input,size_t length,uint8_t*,size_t,tsbench_core_result* result){
    if(result)*result={};auto* s=static_cast<ChimpCore*>(context);return core_guard(s,[&]{need(s&&s->decoder&&result&&input,"Chimp direct decode mismatch");tsbench_core::vector_result(decode_stream(input,length,s->count),result);});
}
extern "C" void tsbench_core_release(tsbench_core_result* result){tsbench_core::release(result);}
extern "C" const char* tsbench_core_error(void* context){return context?static_cast<ChimpCore*>(context)->error:core_error;}
