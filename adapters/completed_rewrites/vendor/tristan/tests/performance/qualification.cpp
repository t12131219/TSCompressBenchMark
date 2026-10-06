// SPDX-License-Identifier: NOASSERTION
// Independent qualification; not a framework benchmark or ranking.
#include "tristan.hpp"
#include <chrono>
#include <fstream>
#include <iostream>
#include <iomanip>
#include <cmath>
using Clock=std::chrono::steady_clock;
int main(int argc,char** argv){try{
    if(argc!=7)throw std::runtime_error("input rows channels atoms solver repetitions");
    auto rows=std::stoull(argv[2]);auto channels=static_cast<std::uint32_t>(std::stoul(argv[3]));
    tristan::Config c;c.atoms=static_cast<std::uint32_t>(std::stoul(argv[4]));c.solver=static_cast<tristan::Solver>(std::stoul(argv[5]));
    auto reps=std::stoul(argv[6]);if(rows>1048576||channels>256||channels==0||reps>100)throw std::runtime_error("Invalid shape/repetitions");
    std::vector<double> input(rows*channels);std::ifstream f(argv[1],std::ios::binary);
    f.read(reinterpret_cast<char*>(input.data()),static_cast<std::streamsize>(input.size()*8));if(!f||f.peek()!=EOF)throw std::runtime_error("Input size mismatch");
    tristan::Trace trace;auto frame=tristan::encode(input.data(),rows,channels,c,{},&trace);
    std::vector<double> training;auto first=channels>1?1U:0U,last=channels>1?std::min(channels,8U):1U;
    for(auto ch=first;ch<last;++ch)for(std::uint64_t i=0;i<(rows/c.length)*c.length;++i)training.push_back(trace.normalized[i*channels+ch]);
    std::cout<<std::setprecision(17)<<"{\"warmup\":3,\"repetitions\":"<<reps<<",\"frame_bytes\":"<<frame.size()<<",\"final_bits\":"<<frame.size()*8<<",\"workspace_bound\":"<<tristan::workspace_bound(rows,channels,c)<<",\"observations\":[";
    for(std::size_t i=0;i<reps+3;++i){
        auto begin=Clock::now();auto dictionary=tristan::train(training,training.size()/c.length,c);auto fit=Clock::now();
        auto encoded=tristan::encode(input.data(),rows,channels,c);auto done=Clock::now();auto decoded=tristan::decode(encoded.data(),encoded.size());auto end=Clock::now();
        if(encoded!=frame||dictionary!=trace.dictionary||decoded.values.empty())throw std::runtime_error("Qualification determinism failure");
        if(i>=3){if(i>3)std::cout<<',';std::cout<<"{\"training_CORE_seconds\":"<<std::chrono::duration<double>(fit-begin).count()<<",\"encode_E2E_seconds\":"<<std::chrono::duration<double>(done-fit).count()<<",\"decode_E2E_seconds\":"<<std::chrono::duration<double>(end-done).count()<<'}';}
    }
    std::cout<<"]}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
