#include "dzip_training.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <numeric>
#include <random>
#include <stdexcept>

namespace dzip {
namespace {
void need(bool ok,const char* message) {if(!ok) throw std::invalid_argument(message);}
void shuffle(std::vector<unsigned>& indices,std::mt19937& random) {
    // NumPy legacy RandomState shuffle's mask/rejection interval selection.
    for(unsigned last=unsigned(indices.size());last>1;--last) {
        unsigned maximum=last-1,mask=maximum;
        mask|=mask>>1;mask|=mask>>2;mask|=mask>>4;mask|=mask>>8;mask|=mask>>16;
        unsigned selected;do {selected=random()&mask;} while(selected>maximum);
        std::swap(indices[maximum],indices[selected]);
    }
}
}
Bytes normalize_latin1(const Bytes& input) {
    need(input.size()<=16u*1024u*1024u,"preprocessing input limit exceeded");
    Bytes output;output.reserve(input.size());
    for(std::size_t i=0;i<input.size();++i) {
        if(input[i]==13) {output.push_back(10);if(i+1<input.size() && input[i+1]==10) ++i;}
        else output.push_back(input[i]);
    }
    return output;
}
BootstrapResult train_bootstrap(Network& network,const Bytes& input,const BootstrapOptions& options) {
    need(options.batch_size>0 && options.batch_size<=2048 && options.epochs>0 && options.epochs<=100 &&
         options.patience>0 && std::isfinite(options.min_delta) && options.min_delta>=0 && options.microbatch<=2048,
         "invalid bootstrap schedule");
    // Validate the training graph's two sigmoid recurrent layers before work.
    auto description=network.serialize();std::size_t position=20;unsigned recurrent=0;
    auto word=[&](){need(description.size()-position>=4,"invalid training graph");unsigned n=0;
        for(unsigned i=0;i<4;++i) n|=unsigned(description[position++])<<(8*i);
        return n;};
    while(position<description.size()) {
        unsigned kind=word(),flags=word(),inputs=word();for(unsigned i=0;i<inputs;++i)word();
        if(kind==2) {need(flags==1,"bootstrap training requires sigmoid recurrent gates");++recurrent;}
        unsigned tensors=word();for(unsigned t=0;t<tensors;++t) {
            unsigned rank=word();std::size_t elements=1;for(unsigned d=0;d<rank;++d) elements*=word();position+=4*elements;
        }
    }
    need(recurrent==2,"bootstrap training requires both source BiGRUs");
    auto normalized=normalize_latin1(input);
    need(normalized.size()>=65,"source bootstrap requires at least 65 normalized symbols");
    std::array<bool,256> used{};for(auto symbol:normalized) used[symbol]=true;
    std::array<std::int32_t,256> map{};unsigned count=0;for(unsigned symbol=0;symbol<256;++symbol) if(used[symbol])map[symbol]=std::int32_t(count++);
    need(count==network.alphabet(),"training alphabet differs from model");
    std::vector<std::int32_t> symbols;symbols.reserve(normalized.size());for(auto symbol:normalized)symbols.push_back(map[symbol]);
    auto windows=normalized.size()-64,retained=(windows/options.batch_size)*options.batch_size;
    need(retained>0,"source training schedule has zero full batches");
    BootstrapResult result{network,{},normalized.size(),retained,windows-retained};
    std::mt19937 random(options.shuffle_seed);std::vector<unsigned> indices(retained);
    std::iota(indices.begin(),indices.end(),0);
    if(options.order.empty()) shuffle(indices,random);
    else {
        need(options.order.size()==retained,"bootstrap order size differs from retained windows");
        std::vector<bool> seen(retained,false);
        for(unsigned index:options.order) {need(index<retained && !seen[index],"bootstrap order is not a permutation");seen[index]=true;}
        indices=options.order;
    }
    network.reset_optimizer();float checkpoint_loss=std::numeric_limits<float>::infinity(),stopping_loss=checkpoint_loss;unsigned wait=0;
    TrainOptions adam;adam.learning_rate=.005f;adam.epsilon=1e-7f;adam.clipnorm=.1f;adam.rule=AdamRule::keras;adam.microbatch=options.microbatch;
    adam.backend=options.backend;
    for(unsigned epoch=0;epoch<options.epochs;++epoch) {
        double sum=0;
        for(std::size_t first=0;first<retained;first+=options.batch_size) {
            std::vector<std::int32_t> contexts,labels;contexts.reserve(options.batch_size*64);labels.reserve(options.batch_size);
            for(unsigned row=0;row<options.batch_size;++row) {
                unsigned index=indices[first+row];contexts.insert(contexts.end(),symbols.begin()+index,symbols.begin()+index+64);labels.push_back(symbols[index+64]);
            }
            sum+=network.train(contexts,labels,adam);
        }
        Epoch record{epoch+1,float(sum/double(retained/options.batch_size)),false,false};
        if(record.loss<checkpoint_loss) {result.checkpoint=Network::load(network.serialize());checkpoint_loss=record.loss;record.checkpoint=true;}
        if(record.loss<stopping_loss-options.min_delta) {stopping_loss=record.loss;wait=0;}
        else if(++wait>=options.patience) record.early_stop=true;
        result.epochs.push_back(record);if(record.early_stop) break;
    }
    return result;
}
}
