#include "internal.hpp"
#include <array>

namespace deepzip {
std::vector<std::string> supported_models() {
    return {"biGRU", "biGRU_big", "biGRU_16bit", "biLSTM", "biLSTM_16bit",
        "LSTM_multi", "LSTM_multi_big", "LSTM_multi_bn", "LSTM_multi_16bit",
        "LSTM_multi_selu_16bit", "GRU_multi", "GRU_multi_big", "GRU_multi_16bit",
        "FC_4layer", "FC_4layer_big", "FC_4layer_16bit", "FC"};
}
float round_half(float x) {
    std::uint32_t bits;
    std::memcpy(&bits, &x, 4);
    std::uint32_t sign = bits & 0x80000000u, magnitude = bits & 0x7fffffffu;
    if (magnitude >= 0x7f800000u) return x;
    int exponent = static_cast<int>((magnitude >> 23) & 255) - 127;
    if (exponent > 15) {
        bits = sign | 0x7f800000u;
    } else if (exponent < -25) {
        bits = sign;
    } else if (exponent < -14) {
        // Subnormals have a constant 2^-24 quantum; binary64 is exact here.
        double y = std::ldexp(static_cast<double>(std::fabs(x)), 24);
        double q = std::floor(y), fraction = y-q;
        if (fraction > 0.5 || (fraction == 0.5 && (static_cast<unsigned>(q)&1))) ++q;
        float result = static_cast<float>(std::ldexp(q, -24));
        return std::signbit(x) ? -result : result;
    } else {
        std::uint32_t discarded = magnitude & 8191u;
        magnitude &= ~8191u;
        if (discarded > 4096u || (discarded == 4096u && (magnitude & 8192u))) magnitude += 8192u;
        if (magnitude >= 0x47800000u) magnitude = 0x7f800000u;
        bits = sign | magnitude;
    }
    std::memcpy(&x, &bits, 4);
    return x;
}
Bytes serialize_model(const std::string& name, const std::vector<Layer>& layers) {
    Bytes b{'D','Z','M','O','D','E','L','1'};
    put(b, name.size(), 4);
    b.insert(b.end(), name.begin(), name.end());
    put(b, layers.size(), 4);
    for (const auto& l : layers) {
        put(b, l.kind, 4); put(b, l.flags, 4); put(b, l.activation, 4);
        put(b, l.tensors.size(), 4); put_float(b, l.epsilon);
        for (const auto& t : l.tensors) {
            put(b, t.shape.size(), 4);
            for (auto n : t.shape) put(b, n, 4);
            for (float x : t.data) put_float(b, x);
        }
    }
    return b;
}
static void shape(const Tensor& t, const std::vector<std::uint32_t>& expected) {
    require(t.shape == expected, Status::invalid_model, "model tensor shape does not match layer");
}
std::vector<Layer> profile_layers(const std::string& name,std::uint32_t alphabet) {
    auto names=supported_models();
    require(std::find(names.begin(),names.end(),name)!=names.end(),Status::unsupported,"unsupported model name");
    bool half=name.find("16bit")!=std::string::npos,big=name.find("big")!=std::string::npos;
    unsigned half_flag=half?4:0;
    std::vector<Layer> layers;
    std::uint32_t features=0,steps=64;
    auto tensor=[](std::vector<std::uint32_t> dims){return Tensor{std::move(dims),{}};};
    auto embedding=[&](unsigned width){layers.push_back({1,half_flag,0,0.001f,{tensor({alphabet,width})}});features=width;};
    auto recurrent=[&](unsigned kind,unsigned units,bool bidi,bool sequence){
        Layer l{kind,half_flag+(bidi?2u:0u)+(sequence?1u:0u),0,0.001f,{}};
        unsigned gates=kind==2?3:4;
        for(unsigned d=0;d<(bidi?2u:1u);++d) {
            l.tensors.push_back(tensor({features,units*gates}));
            l.tensors.push_back(tensor({units,units*gates}));
            l.tensors.push_back(tensor({2*units*gates}));
        }
        layers.push_back(std::move(l)); features=units*(bidi?2:1); if(!sequence) steps=1;
    };
    auto dense=[&](unsigned out,unsigned act){
        layers.push_back({4,half_flag,act,0.001f,{tensor({features,out}),tensor({out})}});features=out;
    };
    auto flatten=[&]{layers.push_back({5,0,0,0.001f,{}});features*=steps;steps=1;};
    if(name.rfind("bi",0)==0) {
        unsigned kind=name.rfind("biGRU",0)==0?2:3,units=big?128:32;
        embedding(32); recurrent(kind,units,true,true); recurrent(kind,units,true,false);
        if(!big) dense(64,1);
    } else if(name.rfind("LSTM_multi",0)==0 || name.rfind("GRU_multi",0)==0) {
        unsigned kind=name.rfind("GRU",0)==0?2:3,units=big?(kind==2?128:64):32;
        embedding(kind==3&&big?64:32); recurrent(kind,units,false,true); recurrent(kind,units,false,true); flatten();
        if(name=="LSTM_multi_bn") {
            Layer l{6,0,0,0.001f,{}};
            for(unsigned i=0;i<4;++i) l.tensors.push_back(tensor({features}));
            layers.push_back(std::move(l));
        }
        if(!big) dense(64,name.find("selu")!=std::string::npos?3:1);
    } else if(name.rfind("FC_4layer",0)==0) {
        embedding(big?32:5); flatten();
        for(unsigned i=0;i<4;++i) dense(128,2);
    } else {
        embedding(32); flatten(); dense(1024,1); dense(64,1);
    }
    dense(alphabet,4);
    return layers;
}
Model Model::load(const Bytes& b, const Limits& limits) {
    require(b.size() <= limits.max_model_bytes, Status::resource_limit, "model exceeds byte limit");
    Reader r{b};
    require(r.take(8) == Bytes({'D','Z','M','O','D','E','L','1'}),
            Status::invalid_model, "unknown model format");
    auto data = std::make_shared<ModelData>();
    auto name_length = r.get(4);
    require(name_length > 0 && name_length <= 64, Status::invalid_model, "invalid model name length");
    auto name = r.take(static_cast<std::size_t>(name_length));
    data->name.assign(name.begin(), name.end());
    auto names = supported_models();
    require(std::find(names.begin(), names.end(), data->name) != names.end(),
            Status::unsupported, "unsupported source model constructor");
    auto count = r.get(4);
    require(count > 0 && count <= 10, Status::invalid_model, "invalid layer count");
    for (std::uint64_t i=0; i<count; ++i) {
        Layer l{};
        l.kind=static_cast<std::uint32_t>(r.get(4));
        l.flags=static_cast<std::uint32_t>(r.get(4));
        l.activation=static_cast<std::uint32_t>(r.get(4));
        auto nt = r.get(4);
        l.epsilon = read_float(r);
        require(l.kind >= 1 && l.kind <= 6 && l.flags <= 7 && l.activation <= 4 && nt <= 6,
                Status::invalid_model, "invalid layer descriptor");
        require(std::isfinite(l.epsilon) && l.epsilon > 0, Status::invalid_model, "invalid batchnorm epsilon");
        for (std::uint64_t j=0; j<nt; ++j) {
            Tensor t;
            auto rank = r.get(4);
            require(rank >= 1 && rank <= 2, Status::invalid_model, "unsupported tensor rank");
            std::size_t elements = 1;
            for (std::uint64_t k=0; k<rank; ++k) {
                auto n = r.get(4);
                require(n > 0 && n <= 65536, Status::invalid_model, "invalid tensor dimension");
                elements = checked_mul(elements, static_cast<std::size_t>(n));
                t.shape.push_back(static_cast<std::uint32_t>(n));
            }
            require(elements <= (b.size()-r.pos)/4, Status::invalid_model, "truncated model tensor");
            t.data.reserve(elements);
            for (std::size_t k=0; k<elements; ++k) {
                float x = read_float(r);
                require(std::isfinite(x), Status::invalid_model, "nonfinite model weight");
                require(!(l.flags&4) || round_half(x)==x, Status::invalid_model, "half tensor contains non-half value");
                t.data.push_back(x);
            }
            l.tensors.push_back(std::move(t));
        }
        data->layers.push_back(std::move(l));
    }
    require(r.pos == b.size(), Status::invalid_model, "trailing model bytes");
    std::uint32_t features=0, steps=64;
    bool flattened=false;
    for (std::size_t i=0; i<data->layers.size(); ++i) {
        const auto& l=data->layers[i];
        const auto& t=l.tensors;
        if (l.kind==1) {
            require(i==0 && t.size()==1 && t[0].shape.size()==2, Status::invalid_model, "invalid embedding layer");
            data->alphabet=t[0].shape[0]; features=t[0].shape[1];
            require(data->alphabet<=256 && features<=64, Status::invalid_model, "embedding dimensions exceed source limits");
        } else if (l.kind==2 || l.kind==3) {
            unsigned gates=l.kind==2?3:4;
            unsigned directions=(l.flags&2)?2:1;
            require(!flattened && t.size()==3*directions && t[1].shape.size()==2,
                    Status::invalid_model, "invalid recurrent layer");
            std::uint32_t units=t[1].shape[0];
            require(units<=128, Status::invalid_model, "recurrent units exceed source limits");
            for (unsigned d=0; d<directions; ++d) {
                shape(t[d*3], {features, units*gates});
                shape(t[d*3+1], {units, units*gates});
                shape(t[d*3+2], {2*units*gates});
            }
            features=units*directions;
            if (!(l.flags&1)) steps=1;
        } else if (l.kind==5) {
            require(t.empty() && !flattened, Status::invalid_model, "invalid flatten layer");
            features*=steps; steps=1; flattened=true;
        } else if (l.kind==6) {
            require(t.size()==4 && steps==1, Status::invalid_model, "invalid batchnorm layer");
            for (const auto& v:t) shape(v,{features});
            require(std::all_of(t[3].data.begin(), t[3].data.end(), [](float v){return v>=0;}),
                    Status::invalid_model, "negative moving variance");
        } else if (l.kind==4) {
            require(t.size()==2 && t[1].shape.size()==1 && steps==1, Status::invalid_model, "invalid dense layer");
            std::uint32_t out=t[1].shape[0];
            require(out<=1024, Status::invalid_model, "dense units exceed source limits");
            shape(t[0],{features,out}); features=out;
        }
    }
    require(data->layers.front().kind==1 && data->layers.back().kind==4 &&
            data->layers.back().activation==4 && steps==1 && features==data->alphabet,
            Status::invalid_model, "model must end with alphabet softmax");
    auto expected=profile_layers(data->name,data->alphabet);
    require(expected.size()==data->layers.size(),Status::invalid_model,"profile layer count mismatch");
    for(std::size_t i=0;i<expected.size();++i) {
        const auto& actual=data->layers[i]; const auto& wanted=expected[i];
        require(actual.kind==wanted.kind && actual.flags==wanted.flags && actual.activation==wanted.activation &&
                actual.epsilon==wanted.epsilon && actual.tensors.size()==wanted.tensors.size(),
                Status::invalid_model,"layer descriptor does not match source constructor");
        for(std::size_t j=0;j<wanted.tensors.size();++j) shape(actual.tensors[j],wanted.tensors[j].shape);
    }
    data->half=data->layers.front().flags&4;
    data->portable=b;
    return Model(std::move(data));
}
const Bytes& Model::serialize() const { return data_->portable; }
const std::string& Model::name() const { return data_->name; }
std::uint32_t Model::alphabet_size() const { return data_->alphabet; }
bool Model::half_precision() const { return data_->half; }
std::vector<float> Model::predict(const std::vector<std::uint32_t>& x, Backend backend) const {
    require(x.size()%64==0 && x.size()/64<=4096, Status::invalid_parameter, "contexts must have shape [B,64], B<=4096");
    require(std::all_of(x.begin(), x.end(), [&](auto id){return id<data_->alphabet;}),
            Status::invalid_parameter, "context symbol outside model alphabet");
    if (x.empty()) return {};
    switch (backend) {
        case Backend::scalar: return predict_scalar(*data_,x);
        case Backend::cuda: return predict_cuda(*data_,x);
    }
    throw Error(Status::unsupported,"unknown prediction backend");
}
static float sigmoid(float x) { return 1.0f/(1.0f+std::exp(-x)); }
static float activate(float x, unsigned a) {
    if (a==1) return std::max(0.0f,x);
    if (a==2) return x>=0?x:std::expm1(x);
    if (a==3) return 1.0507009873554805f*(x>=0?x:1.6732632423543772f*std::expm1(x));
    return x;
}
std::vector<float> predict_scalar(const ModelData& model, const std::vector<std::uint32_t>& contexts) {
    const std::size_t batch=contexts.size()/64;
    std::size_t steps=64, features=0;
    std::vector<float> values;
    for (const auto& l:model.layers) {
        const auto& t=l.tensors;
        bool half=l.flags&4;
        auto q=[&](float v){return half?round_half(v):v;};
        if (l.kind==1) {
            features=t[0].shape[1]; values.resize(batch*steps*features);
            for (std::size_t i=0;i<contexts.size();++i)
                std::copy_n(t[0].data.begin()+contexts[i]*features,features,values.begin()+i*features);
        } else if (l.kind==5) {
            features*=steps; steps=1;
        } else if (l.kind==6) {
            for (std::size_t b=0;b<batch;++b) for(std::size_t j=0;j<features;++j) {
                float scale=t[0].data[j]/std::sqrt(t[3].data[j]+l.epsilon);
                values[b*features+j]=q((values[b*features+j]-t[2].data[j])*scale+t[1].data[j]);
            }
        } else if (l.kind==4) {
            std::size_t out=t[1].data.size();
            std::vector<float> result(batch*out);
            for (std::size_t b=0;b<batch;++b) {
                for (std::size_t j=0;j<out;++j) {
                    float sum=0;
                    for (std::size_t k=0;k<features;++k) sum += values[b*features+k]*t[0].data[k*out+j];
                    result[b*out+j]=q(activate(q(q(sum)+t[1].data[j]),l.activation));
                }
                if (l.activation==4) {
                    float maximum=*std::max_element(result.begin()+b*out,result.begin()+(b+1)*out);
                    float sum=0;
                    for (std::size_t j=0;j<out;++j) {result[b*out+j]=std::exp(result[b*out+j]-maximum); sum+=result[b*out+j];}
                    for (std::size_t j=0;j<out;++j) result[b*out+j]=q(result[b*out+j]/sum);
                }
            }
            features=out; values=std::move(result);
        } else {
            unsigned gates=l.kind==2?3:4, directions=(l.flags&2)?2:1;
            std::size_t units=t[1].shape[0], out_steps=(l.flags&1)?steps:1;
            std::vector<float> result(batch*out_steps*units*directions);
            for (std::size_t b=0;b<batch;++b) for(unsigned d=0;d<directions;++d) {
                const auto& kernel=t[d*3].data;
                const auto& recurrent=t[d*3+1].data;
                const auto& bias=t[d*3+2].data;
                std::vector<float> h(units,0),cell(units,0),input_sum(units*gates),hidden_sum(units*gates);
                for (std::size_t step=0;step<steps;++step) {
                    std::size_t time=d?steps-step-1:step;
                    for(std::size_t j=0;j<units*gates;++j) {
                        float in=0,rec=0;
                        // Keras 2.2.2 flattens each [input,units] gate slice
                        // directly into cuDNN's [units,input] matrix. Preserve
                        // that legacy packing, not a modern GRU interpretation.
                        auto gate=j/units,unit=j%units;
                        for(std::size_t k=0;k<features;++k) {
                            auto packed=unit*features+k;
                            in+=values[(b*steps+time)*features+k]*kernel[(packed/units)*units*gates+gate*units+packed%units];
                        }
                        for(std::size_t k=0;k<units;++k) rec+=h[k]*recurrent[unit*units*gates+gate*units+k];
                        input_sum[j]=q(in+bias[j]); hidden_sum[j]=q(rec+bias[units*gates+j]);
                    }
                    for(std::size_t j=0;j<units;++j) {
                        if(l.kind==2) {
                            float z=q(sigmoid(q(input_sum[j]+hidden_sum[j])));
                            float r=q(sigmoid(q(input_sum[units+j]+hidden_sum[units+j])));
                            float n=q(std::tanh(q(input_sum[2*units+j]+q(r*hidden_sum[2*units+j]))));
                            h[j]=q(q(z*h[j])+q(q(1-z)*n));
                        } else {
                            float in=q(sigmoid(q(input_sum[j]+hidden_sum[j])));
                            float forget=q(sigmoid(q(input_sum[units+j]+hidden_sum[units+j])));
                            float candidate=q(std::tanh(q(input_sum[2*units+j]+hidden_sum[2*units+j])));
                            float out=q(sigmoid(q(input_sum[3*units+j]+hidden_sum[3*units+j])));
                            cell[j]=q(q(forget*cell[j])+q(in*candidate));
                            h[j]=q(out*q(std::tanh(cell[j])));
                        }
                    }
                    if(l.flags&1) for(std::size_t j=0;j<units;++j)
                        result[(b*steps+time)*units*directions+d*units+j]=h[j];
                }
                if(!(l.flags&1)) for(std::size_t j=0;j<units;++j)
                    result[b*units*directions+d*units+j]=h[j];
            }
            steps=out_steps; features=units*directions; values=std::move(result);
        }
    }
    require(std::all_of(values.begin(),values.end(),[](float v){return std::isfinite(v)&&v>=0&&v<=1;}),
            Status::invalid_model,"prediction produced invalid probabilities");
    return values;
}
}  // namespace deepzip
