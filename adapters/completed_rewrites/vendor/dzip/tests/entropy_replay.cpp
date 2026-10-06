// Test-only replay uses the production entropy implementation, with observed
// source probabilities instead of a neural network. No oracle runtime is linked.
#include "../src/codec.cpp"
#include <fstream>
#include <iostream>
#include <iterator>

template<class T> std::vector<T> fixture(const char* path) {
    std::ifstream input(path,std::ios::binary);
    if(!input)throw std::invalid_argument("fixture open failed");
    dzip::Bytes bytes{std::istreambuf_iterator<char>(input),std::istreambuf_iterator<char>()};
    if(bytes.size()%sizeof(T))throw std::invalid_argument("fixture size invalid");
    std::vector<T> values(bytes.size()/sizeof(T));
    if(!bytes.empty())std::memcpy(values.data(),bytes.data(),bytes.size());return values;
}
int main(int argc,char** argv) {
    try {
        if(argc!=5)throw std::invalid_argument("SYMBOLS ALPHABET PROBABILITIES OUTPUT");
        auto symbols=fixture<std::int32_t>(argv[1]);auto probabilities=fixture<float>(argv[3]);
        unsigned alphabet=unsigned(std::stoul(argv[2]));
        if(!alphabet || alphabet>256 || symbols.size()<64 || probabilities.size()!=(symbols.size()-64)*alphabet)
            throw std::invalid_argument("entropy replay shape invalid");
        dzip::Arithmetic coder;auto uniform=dzip::uniform(alphabet);
        for(std::size_t i=0;i<symbols.size();++i) {
            if(symbols[i]<0 || unsigned(symbols[i])>=alphabet)throw std::invalid_argument("symbol invalid");
            auto table=uniform;
            if(i>=64)table=dzip::frequencies(std::vector<float>(probabilities.begin()+(i-64)*alphabet,probabilities.begin()+(i-63)*alphabet));
            coder.update(table,unsigned(symbols[i]),false);
        }
        auto encoded=coder.finish();std::ofstream output(argv[4],std::ios::binary);
        output.write(reinterpret_cast<const char*>(encoded.data()),std::streamsize(encoded.size()));
        if(!output)throw std::invalid_argument("output write failed");
        return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<"\n";return 1;}
}
