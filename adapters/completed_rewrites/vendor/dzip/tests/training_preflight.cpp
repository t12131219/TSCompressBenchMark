#include "dzip_training.hpp"
#include <algorithm>
#include <cmath>
#include <iostream>
#include <stdexcept>

void check(bool ok,const char* message) {if(!ok) throw std::runtime_error(message);}
template<class F> void reject(F function) {
    bool thrown=false;try {function();} catch(const std::invalid_argument&) {thrown=true;}
    check(thrown,"expected training rejection");
}
int main() {
    try {
        check(dzip::normalize_latin1({65,13,10,66,13,67,10,255})==dzip::Bytes({65,10,66,10,67,10,255}),"universal newline mapping");
        auto one=dzip::Network::create(1,dzip::ModelProfile::bootstrap_training,17);
        auto before=one.serialize();dzip::Bytes input(2113,65);
        dzip::BootstrapOptions options;options.epochs=10;options.microbatch=32;
        auto report=dzip::train_bootstrap(one,input,options);
        check(report.training_windows==2048 && report.dropped_windows==1,"full-batch window truncation");
        check(report.epochs.size()==4 && report.epochs.back().early_stop,"constant loss early stopping at patience three");
        check(report.epochs[0].checkpoint && !report.epochs[1].checkpoint,"strict best checkpoint selection");
        check(one.serialize()==before && report.checkpoint.serialize()==before,"constant one-class loss leaves weights unchanged");
        check(std::isfinite(report.epochs[0].loss) && report.epochs[0].loss<1e-6f,"one-class clipped bits loss");
        auto two=dzip::Network::create(2,dzip::ModelProfile::bootstrap_training,19);
        auto copy=two;std::vector<std::int32_t> contexts(128,0),labels{0,1};
        for(unsigned i=0;i<contexts.size();++i)contexts[i]=i%2;
        auto original=two.serialize();two.gradient_graph(contexts,labels);
        check(two.serialize()==original,"gradient diagnostic leaves model unchanged");
        auto loss=two.train(contexts,labels);check(std::isfinite(loss) && two.serialize()!=original,"input-dependent training updates weights");
        check(copy.serialize()==original,"copy has independent optimizer and weights");
        for(unsigned alphabet:{1u,2u,4u,10u,128u}) {
            auto training=dzip::Network::create(alphabet,dzip::ModelProfile::bootstrap_training,19);
            auto cpu_model=dzip::Network::create(alphabet,dzip::ModelProfile::bootstrap_cpu,19);
            check(training.cpu_bootstrap().serialize()==cpu_model.serialize(),"training to CPU conversion preserves canonical kernels");
        }
        auto converted=two.cpu_bootstrap();
        check(two.serialize()!=converted.serialize(),"trained conversion changes recurrent gate profile");
        auto combined=dzip::Network::create(2,dzip::ModelProfile::combined_cpu,7);
        reject([&]{combined.cpu_bootstrap();});combined.import_bootstrap(converted);
        check(std::isfinite(combined.predict(contexts)[0]),"trained bootstrap enters combined CPU codec");
        dzip::TrainOptions changed;changed.learning_rate=.001f;
        auto updated=two.serialize();reject([&]{two.train(contexts,labels,changed);});
        check(two.serialize()==updated,"rejected optimizer change is atomic");
        two.reset_optimizer();two.train(contexts,labels,changed);
        reject([&]{dzip::Network::create(9,dzip::ModelProfile::combined_cpu);});
        auto cpu=dzip::Network::create(1,dzip::ModelProfile::bootstrap_cpu);
        reject([&]{dzip::train_bootstrap(cpu,input);});
        reject([&]{dzip::train_bootstrap(one,dzip::Bytes(64,65));});
        reject([&]{dzip::train_bootstrap(one,dzip::Bytes(100,65));});
        std::cout<<"Preprocessing, bootstrap schedule, checkpoint/early stop, gradients, copy and optimizer lifecycle PASS\n";return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<"\n";return 1;}
}
