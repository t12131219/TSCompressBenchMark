// Bounded native ETB1 stream of independently recoverable blocks, one table per lane.
#include "entropy_port.hpp"

#include <algorithm>
#include <array>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string_view>

namespace ep=entropy_port;
namespace {
constexpr auto max_block=ep::block_size;
constexpr size_t block_header=9;
void check(bool ok,const char* why) { if (!ok) throw std::runtime_error(why); }

ep::Bytes read_asset(const char* path,size_t limit) {
    std::ifstream in(path,std::ios::binary|std::ios::ate);
    const auto n=in.tellg();
    check(in && n>0 && static_cast<uint64_t>(n)<=limit,"ETB1 training or model extent differs");
    ep::Bytes bytes(static_cast<size_t>(n));
    in.seekg(0);
    check(bool(in.read(reinterpret_cast<char*>(bytes.data()),n)),"short ETB1 asset");
    return bytes;
}
void write(std::ostream& out,const ep::Bytes& bytes) {
    check(bool(out.write(reinterpret_cast<const char*>(bytes.data()),bytes.size())),"ETB1 output failed");
}
uint32_t le32(const unsigned char* p) {
    return uint32_t(p[0]) | uint32_t(p[1])<<8 | uint32_t(p[2])<<16 | uint32_t(p[3])<<24;
}
void describe(const ep::TableCodec& c,size_t blocks,size_t raw,size_t wire) {
    std::cout << "{\"streams\":" << c.huffman_streams() << ",\"effective_table_log\":" << c.effective_table_log()
              << ",\"blocks\":" << blocks << ",\"raw_bytes\":" << raw << ",\"wire_bytes\":" << wire
              << ",\"context_count\":1}\n";
}
void train(std::string_view streams,const char* source,const char* dest) {
    check(streams=="1"||streams=="4","unsupported ETB1 streams");
    const auto raw=read_asset(source,max_block);
    const ep::TableCodec codec(ep::Algorithm::Huff,raw,0,streams=="1"?1:4);
    const auto model=codec.model();
    std::ofstream out(dest,std::ios::binary);
    write(out,model); out.close(); check(bool(out),"cannot finish ETB1 model");
    describe(codec,0,raw.size(),model.size());
}
void transfer(bool encode,const char* model_path,const char* source,const char* dest) {
    const auto model=read_asset(model_path,1024);
    check(model.size()>=8 && model[4]==unsigned(ep::Algorithm::Huff),"not a Huff0 table");
    const ep::TableCodec codec(model);
    std::ifstream in(source,std::ios::binary);
    std::ofstream out(dest,std::ios::binary);
    check(in && out,"cannot open ETB1 input/output");
    ep::Bytes block;
    size_t blocks=0,raw=0,wire=0;
    while (true) {
        if (encode) {
            block.resize(max_block);
            in.read(reinterpret_cast<char*>(block.data()),block.size());
            const auto n=in.gcount();
            check(!in.bad() && (in||in.eof()),"cannot read held-out block");
            if (!n) break;
            block.resize(n);
            const auto encoded=codec.encode_block(block);
            check(encoded.size()>=block_header && encoded.size()<=block.size()+block_header,"invalid encoded ETB1 block extent");
            write(out,encoded);
            raw+=block.size(); wire+=encoded.size(); ++blocks;
        } else {
            block.resize(block_header);
            in.read(reinterpret_cast<char*>(block.data()),block_header);
            const auto head=in.gcount();
            check(!in.bad() && (in||in.eof()),"cannot read ETB1 block header");
            if (!head) break;
            check(head==block_header,"truncated ETB1 block header");
            const auto len=le32(block.data()+1), encoded=le32(block.data()+5);
            check(0<len && len<=max_block && 0<encoded && encoded<=len,"invalid ETB1 block extent");
            block.resize(block_header+encoded);
            check(bool(in.read(reinterpret_cast<char*>(block.data()+block_header),encoded)),"truncated ETB1 block");
            const auto decoded=codec.decode_block(block);
            check(decoded.size()==len,"ETB1 restored length differs");
            write(out,decoded);
            raw+=decoded.size(); wire+=block.size(); ++blocks;
        }
    }
    out.close(); check(out && blocks,"cannot finish ETB1 stream");
    describe(codec,blocks,raw,wire);
}
}
int main(int argc,char** argv) {
    try {
        check(argc==5,"usage: control train streams train-prefix model | {encode|decode} model input output");
        const std::string_view op(argv[1]);
        if (op=="train") train(argv[2],argv[3],argv[4]);
        else {
            check(op=="encode"||op=="decode","unknown ETB1 corpus operation");
            transfer(op=="encode",argv[2],argv[3],argv[4]);
        }
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
