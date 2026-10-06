#include "dzip_nn.hpp"
#include <cstring>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>

dzip::Bytes read(const char* path) {
    std::ifstream input(path,std::ios::binary);if(!input) throw std::runtime_error("input open failed");
    return {std::istreambuf_iterator<char>(input),std::istreambuf_iterator<char>()};
}
template<class T> std::vector<T> values(const char* path) {
    auto bytes=read(path);if(bytes.size()%sizeof(T)) throw std::runtime_error("truncated typed fixture");
    std::vector<T> result(bytes.size()/sizeof(T));if(!bytes.empty()) std::memcpy(result.data(),bytes.data(),bytes.size());return result;
}
void write(const char* path,const void* data,std::size_t bytes) {
    std::ofstream output(path,std::ios::binary);output.write(static_cast<const char*>(data),std::streamsize(bytes));
    if(!output) throw std::runtime_error("output write failed");
}
int main(int argc,char** argv) {
    try {
        if(argc<5) throw std::runtime_error("predict MODEL CONTEXTS OUTPUT | train MODEL CONTEXTS LABELS OUTPUT STEPS");
        auto profile=[](const std::string& value) {
            if(value=="bootstrap") return dzip::ModelProfile::bootstrap_cpu;
            if(value=="combined") return dzip::ModelProfile::combined_cpu;
            if(value=="training") return dzip::ModelProfile::bootstrap_training;
            throw std::invalid_argument("unknown model profile");
        };
        if((std::string(argv[1])=="create" || std::string(argv[1])=="import") && argc==6) {
            auto seed=std::stoul(argv[4]);if(seed>UINT32_MAX) throw std::invalid_argument("seed too large");
            auto model=std::string(argv[1])=="create"?
                dzip::Network::create(unsigned(std::stoul(argv[2])),profile(argv[3]),std::uint32_t(seed)):
                dzip::Network::from_hdf5(argv[2],profile(argv[3]),std::uint32_t(seed));
            auto bytes=model.serialize();write(argv[5],bytes.data(),bytes.size());return 0;
        }
        if(std::string(argv[1])=="codec-model" && argc==6) {
            auto bootstrap=dzip::Network::load(read(argv[2])).cpu_bootstrap();
            auto target=profile(argv[3]);auto model=bootstrap;
            if(target==dzip::ModelProfile::combined_cpu) {
                model=dzip::Network::create(bootstrap.alphabet(),target,std::uint32_t(std::stoul(argv[4])));
                model.import_bootstrap(bootstrap);
            } else if(target!=dzip::ModelProfile::bootstrap_cpu)throw std::invalid_argument("codec model must use CPU gates");
            auto bytes=model.serialize();write(argv[5],bytes.data(),bytes.size());return 0;
        }
        // Test-only source trajectory replay: keep one model and its Adam slots
        // across all predictions. Never reset it to oracle weights between batches.
        if(std::string(argv[1])=="replay" && argc==6) {
            auto network=dzip::Network::load(read(argv[2]));
            auto symbols=values<std::int32_t>(argv[3]);
            std::string mode=argv[5];
            if(mode!="bootstrap" && mode!="combined")throw std::invalid_argument("invalid replay mode");
            if(symbols.size()<64)throw std::invalid_argument("replay needs the source context");
            std::vector<float> probabilities;
            std::vector<std::int32_t> batch,labels;
            for(std::size_t i=64;i<symbols.size();++i) {
                std::vector<std::int32_t> context(symbols.begin()+i-64,symbols.begin()+i);
                auto next=network.predict(context);
                probabilities.insert(probabilities.end(),next.begin(),next.end());
                if(mode=="combined") {
                    batch.insert(batch.end(),context.begin(),context.end());labels.push_back(symbols[i]);
                    if(labels.size()==128) {network.train(batch,labels);batch.clear();labels.clear();}
                }
            }
            write(argv[4],probabilities.data(),probabilities.size()*sizeof(float));return 0;
        }
        auto network=dzip::Network::load(read(argv[2]));auto contexts=values<std::int32_t>(argv[3]);
        if(std::string(argv[1])=="predict" || std::string(argv[1])=="cuda-predict") {
            auto output=network.predict(contexts,std::string(argv[1])=="cuda-predict"?dzip::ExecutionBackend::cuda:dzip::ExecutionBackend::scalar);write(argv[4],output.data(),output.size()*4);
        }
        else if((std::string(argv[1])=="gradient" || std::string(argv[1])=="cuda-gradient") && argc==6) {
            auto labels=values<std::int32_t>(argv[4]);auto bytes=network.gradient_graph(contexts,labels,
                std::string(argv[1])=="cuda-gradient"?dzip::ExecutionBackend::cuda:dzip::ExecutionBackend::scalar);
            write(argv[5],bytes.data(),bytes.size());
        }
        else if((std::string(argv[1])=="trace" || std::string(argv[1])=="cuda-trace") && argc==6) {
            auto labels=values<std::int32_t>(argv[4]);auto bytes=network.trace_graph(contexts,labels,
                std::string(argv[1])=="cuda-trace"?dzip::ExecutionBackend::cuda:dzip::ExecutionBackend::scalar);
            write(argv[5],bytes.data(),bytes.size());
        }
        else if((std::string(argv[1])=="train" || std::string(argv[1])=="bootstrap-train" || std::string(argv[1])=="cuda-bootstrap-train") && argc==7) {
            auto labels=values<std::int32_t>(argv[4]);unsigned steps=unsigned(std::stoul(argv[6]));
            dzip::TrainOptions options;
            if(std::string(argv[1])!="train") {options.learning_rate=5e-3f;options.epsilon=1e-7f;options.clipnorm=.1f;options.rule=dzip::AdamRule::keras;}
            if(std::string(argv[1])=="cuda-bootstrap-train")options.backend=dzip::ExecutionBackend::cuda;
            for(unsigned i=0;i<steps;++i) std::cout<<network.train(contexts,labels,options)<<"\n";
            auto bytes=network.serialize();write(argv[5],bytes.data(),bytes.size());
        } else throw std::runtime_error("unknown operation");
        return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<"\n";return 1;}
}
