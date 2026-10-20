namespace {
struct SprintzCore{Settings config;size_t width{},dims{},bytes{};bool decoder{};char error[256]{};};
thread_local char core_error[256]{};
template<class F> int core_guard(SprintzCore* s,F f)noexcept{
    int code=1;try{f();return 0;}
    catch(const tsbench_core::Unsupported& e){std::snprintf(core_error,sizeof(core_error),"%s",e.what());code=2;}
    catch(const tsbench_core::Capacity& e){std::snprintf(core_error,sizeof(core_error),"%s",e.what());code=3;}
    catch(const std::exception& e){std::snprintf(core_error,sizeof(core_error),"%s",e.what());}
    catch(...){std::snprintf(core_error,sizeof(core_error),"Sprintz core binding failure");}
    if(s)std::snprintf(s->error,sizeof(s->error),"%s",core_error);return code;
}
}
extern "C" uint32_t tsbench_core_version(){return 1;}
extern "C" uint32_t tsbench_core_storage(){return 3;}
extern "C" int tsbench_core_create(const tsbench_core_config* cfg,int decoder,void** result){
    if(result)*result=nullptr;return core_guard(nullptr,[&]{require(cfg&&result&&(decoder==0||decoder==1),"invalid Sprintz direct arguments");
        const auto count=tsbench_core::elements(*cfg);(void)count;
        if(cfg->dtype!=TSCB_DTYPE_U8_V1&&cfg->dtype!=TSCB_DTYPE_I8_V1&&cfg->dtype!=TSCB_DTYPE_U16_LE_V1&&cfg->dtype!=TSCB_DTYPE_I16_LE_V1)throw tsbench_core::Unsupported("Sprintz requires 8/16-bit integer bits");
        if(cfg->rank>2||cfg->order!=0)throw tsbench_core::Unsupported("Sprintz requires row-major rank 1/2 profile");
        if(cfg->model&&*cfg->model)throw tsbench_core::Unsupported("Sprintz has no external model");
        auto s=std::make_unique<SprintzCore>();s->config=settings(cfg->parameters_json);s->width=tsbench_core::width(cfg->dtype);s->dims=cfg->rank==2?cfg->shape[1]:1;s->bytes=tsbench_core::input_bytes(*cfg);s->decoder=decoder!=0;
        // Decoder takes the serialized path; {} never silently selects auto.
        configuration(s->width,s->dims,s->config,s->bytes);cpu();*result=s.release();});
}
extern "C" int tsbench_core_destroy(void* p){delete static_cast<SprintzCore*>(p);return 0;}
extern "C" int tsbench_core_validate_input(void* p,const uint8_t* in,size_t n){auto* s=static_cast<SprintzCore*>(p);return core_guard(s,[&]{require(s&&n==s->bytes&&(!n||in),"Sprintz direct input size mismatch");});}
extern "C" int tsbench_core_bound(void* p,const uint8_t* in,size_t n,size_t* b){if(b)*b=0;auto* s=static_cast<SprintzCore*>(p);return core_guard(s,[&]{require(s&&b&&n==s->bytes&&(!n||in),"Sprintz direct bound mismatch");*b=bound(configuration(s->width,s->dims,s->config,n),n);});}
extern "C" int tsbench_core_encode(void* p,const uint8_t* in,size_t n,uint8_t* out,size_t cap,tsbench_core_result* r){
    if(r)*r={};auto* s=static_cast<SprintzCore*>(p);return core_guard(s,[&]{require(s&&!s->decoder&&r&&n==s->bytes&&(!n||in),"Sprintz direct encode mismatch");auto c=configuration(s->width,s->dims,s->config,n);auto made=encode_frame(c,in,n,out,cap);tsbench_core::caller_result(out,made,cap,r);});
}
extern "C" int tsbench_core_decode(void* p,const uint8_t* in,size_t n,uint8_t* out,size_t cap,tsbench_core_result* r){
    if(r)*r={};auto* s=static_cast<SprintzCore*>(p);return core_guard(s,[&]{require(s&&s->decoder&&r&&in&&(out||!s->bytes),"Sprintz direct decode mismatch");auto made=decode_frame(in,n,out,cap,s->width,s->dims,s->bytes);tsbench_core::caller_result(out,made,cap,r);});
}
extern "C" void tsbench_core_release(tsbench_core_result* r){tsbench_core::release(r);}
extern "C" const char* tsbench_core_error(void* p){return p?static_cast<SprintzCore*>(p)->error:core_error;}
