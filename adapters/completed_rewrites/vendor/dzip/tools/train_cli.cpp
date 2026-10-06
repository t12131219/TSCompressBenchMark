#include "dzip_training.hpp"
#include <array>
#include <chrono>
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
unsigned number(const char* text) {
    std::size_t used=0;auto value=std::stoul(text,&used);
    if(used!=std::string(text).size() || value>UINT32_MAX) throw std::invalid_argument("invalid numeric option");
    return unsigned(value);
}
int main(int argc,char** argv) {
    try {
        if(argc<5 || argc>10) throw std::invalid_argument("dzip_train INPUT INITIAL_DZN_OR_auto CHECKPOINT EPOCHS [BATCH [MICROBATCH [SHUFFLE_SEED [ORDER_I32_OR_auto [scalar|cuda]]]]]");
        auto start=std::chrono::steady_clock::now();auto input=read(argv[1]);
        auto network=[&]() {
            if(std::string(argv[2])!="auto") return dzip::Network::load(read(argv[2]));
            auto normalized=dzip::normalize_latin1(input);std::array<bool,256> used{};for(auto symbol:normalized)used[symbol]=true;
            unsigned alphabet=0;for(bool value:used)alphabet+=value;
            return dzip::Network::create(alphabet,dzip::ModelProfile::bootstrap_training,0);
        }();
        dzip::BootstrapOptions options;options.epochs=number(argv[4]);
        if(argc>5) options.batch_size=number(argv[5]);
        if(argc>6) options.microbatch=number(argv[6]);
        if(argc>7) options.shuffle_seed=number(argv[7]);
        if(argc>8 && std::string(argv[8])!="auto") {
            auto bytes=read(argv[8]);if(bytes.size()%4)throw std::invalid_argument("truncated order");
            options.order.resize(bytes.size()/4);if(!bytes.empty())std::memcpy(options.order.data(),bytes.data(),bytes.size());
        }
        if(argc>9) {
            if(std::string(argv[9])=="cuda")options.backend=dzip::ExecutionBackend::cuda;
            else if(std::string(argv[9])!="scalar")throw std::invalid_argument("unknown bootstrap backend");
        }
        auto result=dzip::train_bootstrap(network,input,options);auto bytes=result.checkpoint.serialize();
        std::ofstream output(argv[3],std::ios::binary);output.write(reinterpret_cast<const char*>(bytes.data()),std::streamsize(bytes.size()));
        if(!output) throw std::runtime_error("checkpoint write failed");
        std::cout.precision(10);
        std::cout<<"{\"status\":\"PASS\",\"normalized_bytes\":"<<result.normalized_bytes
                 <<",\"training_windows\":"<<result.training_windows<<",\"dropped_windows\":"<<result.dropped_windows
                 <<",\"checkpoint_bytes\":"<<bytes.size()<<",\"preprocessing_seconds\":"
                 <<std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()<<",\"epochs\":[";
        bool first=true;for(const auto& epoch:result.epochs) {
            if(!first)std::cout<<",";first=false;
            std::cout<<"{\"index\":"<<epoch.index<<",\"loss\":"<<epoch.loss<<",\"checkpoint\":"<<(epoch.checkpoint?"true":"false")
                     <<",\"early_stop\":"<<(epoch.early_stop?"true":"false")<<"}";
        }
        std::cout<<"]}\n";return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<"\n";return 1;}
}
