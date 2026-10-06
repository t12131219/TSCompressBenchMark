#include "dzip.hpp"
#include <fstream>
#include <iostream>
#include <iterator>
#include <algorithm>
#include <cstring>
#include <stdexcept>
#include <string>

dzip::Bytes read(const char* name) {std::ifstream input(name,std::ios::binary);if(!input) throw std::runtime_error("input open failed");return {std::istreambuf_iterator<char>(input),std::istreambuf_iterator<char>()};}
void write(const char* name,const dzip::Bytes& bytes) {std::ofstream output(name,std::ios::binary);output.write(reinterpret_cast<const char*>(bytes.data()),std::streamsize(bytes.size()));if(!output) throw std::runtime_error("output write failed");}
int main(int argc,char** argv) {
    try {
        if(argc==4 && std::string(argv[1])=="decode") write(argv[3],dzip::decompress(read(argv[2])));
        else if(argc==6 && std::string(argv[1])=="encode-raw") {
            std::string mode=argv[2];if(mode!="bootstrap" && mode!="combined") throw std::runtime_error("invalid mode");
            auto input=read(argv[4]);auto alphabet=input;std::sort(alphabet.begin(),alphabet.end());alphabet.erase(std::unique(alphabet.begin(),alphabet.end()),alphabet.end());
            auto network=dzip::Network::load(read(argv[3]));if(alphabet.size()!=network.alphabet()) throw std::runtime_error("alphabet mismatch");
            std::vector<std::int32_t> symbols;for(auto byte:input) symbols.push_back(std::int32_t(std::lower_bound(alphabet.begin(),alphabet.end(),byte)-alphabet.begin()));
            write(argv[5],dzip::encode_raw(symbols,std::move(network),mode=="bootstrap"?dzip::Mode::bootstrap:dzip::Mode::combined));
        }
        else if(argc==7 && std::string(argv[1])=="decode-raw") {
            std::string mode=argv[2];if(mode!="bootstrap" && mode!="combined") throw std::runtime_error("invalid mode");
            auto symbols=dzip::decode_raw(read(argv[5]),std::stoull(argv[4]),dzip::Network::load(read(argv[3])),mode=="bootstrap"?dzip::Mode::bootstrap:dzip::Mode::combined);
            dzip::Bytes bytes(symbols.size()*4);if(!bytes.empty()) std::memcpy(bytes.data(),symbols.data(),bytes.size());write(argv[6],bytes);
        }
        else if(argc==6 && std::string(argv[1])=="encode") {
            std::string mode=argv[2];if(mode!="bootstrap" && mode!="combined") throw std::runtime_error("mode must be bootstrap or combined");
            auto result=dzip::compress(read(argv[4]),dzip::Network::load(read(argv[3])),mode=="bootstrap"?dzip::Mode::bootstrap:dzip::Mode::combined);
            write(argv[5],result.bytes);std::cout<<"final_bits="<<result.statistics.final_bits<<" model_bits="<<result.statistics.model_bits<<" payload_bits="<<result.statistics.payload_bits<<"\n";
        } else throw std::runtime_error("encode[-raw] MODE MODEL INPUT OUTPUT | decode INPUT OUTPUT | decode-raw MODE MODEL LENGTH INPUT OUTPUT");
        return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<"\n";return 1;}
}
