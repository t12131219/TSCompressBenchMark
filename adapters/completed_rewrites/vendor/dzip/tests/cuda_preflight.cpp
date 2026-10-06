#include "dzip_nn.hpp"
#include <cmath>
#include <future>
#include <iostream>
#include <stdexcept>

namespace {
void check(bool ok,const char* message) {if(!ok)throw std::runtime_error(message);}
template<class F>void reject(F function) {bool caught=false;try {function();}catch(const std::exception&){caught=true;}check(caught,"expected CUDA request rejection");}
void verify(const std::vector<float>& probabilities,unsigned rows,unsigned alphabet) {
    check(probabilities.size()==rows*alphabet,"CUDA probability size");
    for(unsigned row=0;row<rows;++row) {
        float sum=0;for(unsigned col=0;col<alphabet;++col) {
            float p=probabilities[row*alphabet+col];check(std::isfinite(p) && p>=0 && p<=1,"CUDA probability range");sum+=p;
        }
        check(std::abs(sum-1.f)<2e-6f,"CUDA probability normalization");
    }
}
}
int main() {
    try {
        std::vector<std::int32_t> contexts(4*64),labels{0,1,0,1};
        for(unsigned i=0;i<contexts.size();++i)contexts[i]=i%2;
        auto network=dzip::Network::create(2,dzip::ModelProfile::bootstrap_training,17);
        auto initial=network.serialize();
        if(!dzip::Network::cuda_compiled()) {
            reject([&]{network.predict(contexts,dzip::ExecutionBackend::cuda);});
            check(initial==network.serialize(),"unavailable CUDA request changed weights");
            std::cout<<"Unavailable CUDA rejects without fallback PASS\n";return 0;
        }
        auto cpu=dzip::Network::create(2,dzip::ModelProfile::bootstrap_cpu,17);
        reject([&]{cpu.predict(contexts,dzip::ExecutionBackend::cuda);});
        auto copy=network;
        auto run=[&](dzip::Network model) {
            verify(model.predict(contexts,dzip::ExecutionBackend::cuda),4,2);
            auto old=model.serialize();model.gradient_graph(contexts,labels,dzip::ExecutionBackend::cuda);
            check(model.serialize()==old,"CUDA diagnostic mutated weights");
            dzip::TrainOptions options;options.backend=dzip::ExecutionBackend::cuda;options.rule=dzip::AdamRule::keras;
            options.learning_rate=.005f;options.epsilon=1e-7f;options.clipnorm=.1f;
            for(unsigned step=0;step<3;++step)check(std::isfinite(model.train(contexts,labels,options)),"CUDA train loss");
            auto updated=model.serialize();check(updated!=old,"CUDA training did not update weights");
            options.backend=dzip::ExecutionBackend::scalar;
            reject([&]{model.train(contexts,labels,options);});check(model.serialize()==updated,"backend change rejection mutated weights");
            verify(model.predict(contexts,dzip::ExecutionBackend::cuda),4,2);
            // CPU codec transition consumes the complete trained canonical
            // weights, without needing any CUDA execution or optimizer state.
            auto converted=model.cpu_bootstrap();verify(converted.predict(contexts),4,2);
            return model.predict(contexts,dzip::ExecutionBackend::cuda);
        };
        auto task=std::async(std::launch::async,run,copy);auto own=run(network);auto other=task.get();
        std::cout<<"CUDA concurrent training phase completed"<<std::endl;
        for(unsigned i=0;i<own.size();++i)check(std::abs(own[i]-other[i])<2e-6f,"independent CUDA handles diverged");
        check(network.serialize()==initial && copy.serialize()==initial,"CUDA copies shared mutable model state");
        for(unsigned alphabet:{1u,4u,10u,128u,256u}) {
            auto model=dzip::Network::create(alphabet,dzip::ModelProfile::bootstrap_training,17);
            std::vector<std::int32_t> one(64,0),target{0};
            verify(model.predict(one,dzip::ExecutionBackend::cuda),1,alphabet);
            model.gradient_graph(one,target,dzip::ExecutionBackend::cuda);
            std::cout<<"CUDA architecture "<<alphabet<<" completed"<<std::endl;
        }
        std::cout<<"Forced CUDA GRU/gradients/training, copies, concurrency, CPU transition and architecture boundaries PASS\n";return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<"\n";return 1;}
}
