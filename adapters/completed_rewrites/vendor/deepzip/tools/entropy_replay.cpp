// This test consumes genuine source cumulative tables; it does not use the
// native predictor as an oracle for the arithmetic coder.
#include "internal.hpp"
#include <fstream>
#include <iostream>
#include <iterator>

using namespace deepzip;
static Bytes load(const char* path) {
    std::ifstream f(path,std::ios::binary);
    require(bool(f),Status::invalid_parameter,"cannot read replay input");
    return Bytes((std::istreambuf_iterator<char>(f)),{});
}
static void save(const char* path,const Bytes& b) {
    std::ofstream f(path,std::ios::binary);
    require(bool(f.write(reinterpret_cast<const char*>(b.data()),static_cast<std::streamsize>(b.size()))),
            Status::invalid_parameter,"replay output write failed");
}
static void length(Bytes& out,std::uint64_t n) {
    for(;;) {auto b=static_cast<std::uint8_t>(n&127);n>>=7;
        if(!n){out.push_back(b);return;}out.push_back(b|128);--n;}
}
int main(int argc,char** argv) {
    try {
        require(argc==7,Status::invalid_parameter,"symbols trace lanes alphabet combined decoded expected");
        auto symbols=load(argv[1]),trace=load(argv[2]);Reader r{trace};
        auto lanes=std::stoul(argv[3]),alphabet=std::stoul(argv[4]);
        require(lanes>0 && lanes<=4096 && alphabet>0 && alphabet<=256,Status::invalid_parameter,"replay dimensions");
        require(r.take(8)==Bytes({'D','Z','T','R','A','C','E','1'}),Status::corrupt_stream,"replay trace magic");
        auto uniform=uniform_cumulative(static_cast<unsigned>(alphabet));
        std::size_t primary=symbols.size()/lanes,tail=symbols.size()%lanes;
        std::vector<std::vector<std::vector<std::uint64_t>>> tables(lanes+1);
        for(std::size_t b=0;b<=lanes;++b) tables[b].assign(std::min<std::size_t>(64,b==lanes?tail:primary),uniform);
        auto prediction=[&](std::size_t count,std::size_t offset){
            require(r.get(4)==count && r.get(4)==64 && r.get(4)==alphabet,Status::corrupt_stream,"source trace prediction shape");
            r.take(count*64*4);
            std::vector<float> probabilities(count*alphabet);
            for(auto& value:probabilities) value=read_float(r);
            for(std::size_t b=0;b<count;++b) {
                std::vector<std::uint64_t> c;
                for(std::size_t j=0;j<=alphabet;++j) c.push_back(r.get(8));
                auto first=probabilities.begin()+b*alphabet;
                require(c==cumulative(std::vector<float>(first,first+alphabet)),Status::corrupt_stream,"NumPy cumulative conversion differs");
                tables[offset+b].push_back(std::move(c));
            }
        };
        for(std::size_t j=64;j<primary;++j) prediction(lanes,0);
        for(std::size_t j=64;j<tail;++j) prediction(1,lanes);
        require(r.pos==trace.size(),Status::corrupt_stream,"unconsumed source trace predictions");
        Bytes combined,decoded;
        for(std::size_t b=0;b<=lanes;++b) {
            auto start=b==lanes?primary*lanes:b*primary;
            auto n=b==lanes?tail:primary;
            Bytes input(symbols.begin()+start,symbols.begin()+start+n);
            auto encoded=encode_arithmetic(input,tables[b]);
            auto output=decode_arithmetic(encoded,tables[b]);
            require(input==output,Status::corrupt_stream,"frozen arithmetic roundtrip failed");
            length(combined,encoded.size());combined.insert(combined.end(),encoded.begin(),encoded.end());
            decoded.insert(decoded.end(),output.begin(),output.end());
        }
        save(argv[5],combined);save(argv[6],decoded);
        std::cout<<"Exact source-table conversion and arithmetic/lane replay: PASS\n";
        return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
