#include "dzip.hpp"
#include "libbsc/libbsc.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <limits>
#include <mutex>
#include <stdexcept>

namespace dzip {
namespace {
void need(bool ok,const char* message) {if(!ok) throw std::invalid_argument(message);}
void put(Bytes& bytes,std::uint64_t value,unsigned width) {for(unsigned i=0;i<width;++i) bytes.push_back(std::uint8_t(value>>(8*i)));}
struct Reader {
    const Bytes& bytes;std::size_t pos=0;
    std::uint64_t get(unsigned width) {need(bytes.size()-pos>=width,"truncated frame");std::uint64_t result=0;for(unsigned i=0;i<width;++i) result|=std::uint64_t(bytes[pos++])<<(8*i);return result;}
    Bytes take(std::size_t size) {need(size<=bytes.size()-pos,"truncated frame field");Bytes result(bytes.begin()+std::ptrdiff_t(pos),bytes.begin()+std::ptrdiff_t(pos+size));pos+=size;return result;}
};
std::uint32_t checksum(const std::uint8_t* bytes,std::size_t length) {
    std::uint32_t crc=~std::uint32_t(0);
    for(std::size_t i=0;i<length;++i) {crc^=bytes[i];for(unsigned bit=0;bit<8;++bit) crc=(crc>>1)^(0xedb88320u&std::uint32_t(-std::int32_t(crc&1)));}
    return ~crc;
}
class Arithmetic {
public:
    Bytes bytes;std::uint64_t low=0,high=0xffffffffu,code=0,pending=0;std::size_t position=0;unsigned bits=0;std::uint8_t partial=0;
    void emit(unsigned value) {partial=std::uint8_t((partial<<1)|value);if(++bits==8) {bytes.push_back(partial);partial=0;bits=0;}}
    unsigned bit() {unsigned result=0;if(position/8<bytes.size()) result=(bytes[position/8]>>(7-position%8))&1;++position;return result;}
    void update(const std::vector<std::uint64_t>& cumulative,unsigned symbol,bool decoding) {
        need(cumulative.size()>=2 && symbol+1<cumulative.size(),"arithmetic symbol invalid");
        auto total=cumulative.back();need(total>0 && total<=1073741826u,"arithmetic total outside 32-bit contract");
        auto range=high-low+1,origin=low;
        low=origin+cumulative[symbol]*range/total;high=origin+cumulative[symbol+1]*range/total-1;
        while(((low^high)&0x80000000u)==0) {
            if(decoding) code=((code<<1)&0xffffffffu)|bit();
            else {unsigned value=unsigned(low>>31);emit(value);while(pending) {emit(value^1);--pending;}}
            low=(low<<1)&0xffffffffu;high=((high<<1)&0xffffffffu)|1;
        }
        while((low&~high&0x40000000u)!=0) {
            if(decoding) code=(code&0x80000000u)|((code<<1)&0x7fffffffu)|bit();else ++pending;
            low=(low<<1)&0x7fffffffu;high=((high<<1)&0x7fffffffu)|0x80000001u;
        }
    }
    unsigned decode(const std::vector<std::uint64_t>& cumulative) {
        need(code>=low && code<=high,"invalid arithmetic interval");auto range=high-low+1;
        auto value=((code-low+1)*cumulative.back()-1)/range;
        auto found=std::upper_bound(cumulative.begin(),cumulative.end(),value);
        need(found!=cumulative.begin() && found!=cumulative.end(),"invalid arithmetic frequency index");
        unsigned symbol=unsigned(found-cumulative.begin()-1);update(cumulative,symbol,true);return symbol;
    }
    Bytes finish() {emit(1);if(bits) {partial=std::uint8_t(partial<<(8-bits));bytes.push_back(partial);}return std::move(bytes);}
};
std::vector<std::uint64_t> frequencies(const std::vector<float>& probabilities) {
    std::vector<std::uint64_t> cumulative(probabilities.size()+1,0);double sum=0;
    for(std::size_t i=0;i<probabilities.size();++i) {
        need(std::isfinite(probabilities[i]) && probabilities[i]>=0,"invalid probability");
        sum+=double(probabilities[i])*10000000.+1.;cumulative[i+1]=std::uint64_t(sum);
        need(cumulative[i+1]>cumulative[i],"nonpositive frequency");
    }
    return cumulative;
}
std::vector<std::uint64_t> uniform(unsigned alphabet) {
    std::vector<std::uint64_t> cumulative(alphabet+1,0);double sum=0;
    for(unsigned i=0;i<alphabet;++i) {sum+=(1./alphabet)*10000000.+1.;cumulative[i+1]=std::uint64_t(sum);}return cumulative;
}
void adapt(Network& network,const std::vector<std::int32_t>& symbols,std::size_t offset) {
    std::vector<std::int32_t> contexts;contexts.reserve(128*64);std::vector<std::int32_t> labels;labels.reserve(128);
    for(std::size_t row=offset-128;row<offset;++row) {
        contexts.insert(contexts.end(),symbols.begin()+std::ptrdiff_t(row),symbols.begin()+std::ptrdiff_t(row+64));
        labels.push_back(symbols[row+64]);
    }
    network.train(contexts,labels);
}
void init_bsc() {static std::once_flag once;std::call_once(once,[]{need(bsc_init(LIBBSC_FEATURE_NONE)==0,"libbsc initialization failed");});}
Bytes store_model(const Bytes& model) {
    init_bsc();need(model.size()<std::size_t(std::numeric_limits<int>::max()-64),"model too large for libbsc");
    Bytes input=model;input.resize(input.size()+64,0);Bytes output(model.size()+LIBBSC_HEADER_SIZE+64);
    int length=bsc_compress(input.data(),output.data(),int(model.size()),LIBBSC_DEFAULT_LZPHASHSIZE,
        LIBBSC_DEFAULT_LZPMINLEN,LIBBSC_BLOCKSORTER_BWT,LIBBSC_CODER_QLFC_STATIC,LIBBSC_FEATURE_NONE);
    if(length==LIBBSC_NOT_COMPRESSIBLE) length=bsc_store(input.data(),output.data(),int(model.size()),LIBBSC_FEATURE_NONE);
    need(length>=LIBBSC_HEADER_SIZE,"model BSC compression failed");output.resize(std::size_t(length));return output;
}
Bytes restore_model(const Bytes& stored,std::size_t expected,const Limits& limits) {
    init_bsc();need(stored.size()>=LIBBSC_HEADER_SIZE && stored.size()<std::size_t(std::numeric_limits<int>::max()-64),"invalid model block");
    Bytes input=stored;input.resize(input.size()+64,0);int compressed=0,raw=0;
    Reader header{input};
    need(header.get(4)==stored.size() && header.get(4)==expected && expected>0 &&
         expected<=512u*1024u*1024u && expected<=limits.max_model_bytes,"model block lengths invalid");
    unsigned mode=0;for(unsigned b=0;b<4;++b) mode|=unsigned(input[8+b])<<(8*b);
    constexpr unsigned base=LIBBSC_BLOCKSORTER_BWT|(LIBBSC_CODER_QLFC_STATIC<<5);
    constexpr unsigned lzp=base|(LIBBSC_DEFAULT_LZPHASHSIZE<<16)|(LIBBSC_DEFAULT_LZPMINLEN<<8);
    need(mode==0 || mode==base || mode==lzp,"unsupported model storage profile");
    need(bsc_block_info(input.data(),LIBBSC_HEADER_SIZE,&compressed,&raw,LIBBSC_FEATURE_NONE)==0,"model header corrupt");
    need(raw>0 && std::size_t(raw)==expected && compressed>0 && std::size_t(compressed)==stored.size(),"model block lengths invalid");
    Bytes output(expected+64,0);need(bsc_decompress(input.data(),compressed,output.data(),raw,LIBBSC_FEATURE_NONE)==0,"model decompression failed");output.resize(expected);return output;
}
}
const char* version() noexcept {return "dzip-native-0.1.0";}
std::size_t compress_bound(std::size_t symbols,const Network& initial,const Limits& limits) {
    need(symbols<=limits.max_symbols && symbols<=16u*1024u*1024u,"input exceeds symbol limit");
    auto model=initial.serialize();need(model.size()<=limits.max_model_bytes,"model exceeds byte limit");
    auto bound=model.size()+LIBBSC_HEADER_SIZE+4*symbols+1+44+256+4;
    need(bound<=limits.max_frame_bytes,"compression bound exceeds frame limit");return bound;
}
bool compress_to(const Bytes& input,const Network& initial,Mode mode,std::uint8_t* output,std::size_t capacity,std::size_t& required,const Limits& limits) {
    auto result=compress(input,initial,mode,limits);required=result.bytes.size();
    if(capacity<required || (!output && required)) return false;
    if(required) std::memcpy(output,result.bytes.data(),required);
    return true;
}
std::size_t decompressed_size(const Bytes& frame,const Limits& limits) {
    need(frame.size()>=48 && frame.size()<=limits.max_frame_bytes,"frame byte limit or header invalid");
    Reader tail{frame,frame.size()-4};need(tail.get(4)==checksum(frame.data(),frame.size()-4),"frame checksum mismatch");
    Reader reader{frame};need(reader.take(8)==Bytes({'D','Z','C','P','0','0','0','1'}),"unknown DZip frame");
    auto mode=reader.get(1);need(mode<=1 && reader.get(1)==1,"unknown mode or numerical profile");
    auto alphabet=reader.get(2),length=reader.get(8),raw=reader.get(8),stored=reader.get(8),payload=reader.get(8);
    need(alphabet>0 && alphabet<=256 && length<=limits.max_symbols && length<=16u*1024u*1024u && raw<=limits.max_model_bytes,"frame resource limit exceeded");
    need(alphabet<=frame.size()-reader.pos,"alphabet length invalid");reader.pos+=std::size_t(alphabet);
    need(stored<=frame.size()-reader.pos,"stored model length invalid");reader.pos+=std::size_t(stored);
    need(payload<=frame.size()-reader.pos && payload>0,"payload length invalid");reader.pos+=std::size_t(payload);
    need(reader.pos==frame.size()-4,"frame lengths do not close");return std::size_t(length);
}
bool decompress_to(const Bytes& frame,std::uint8_t* output,std::size_t capacity,std::size_t& required,const Limits& limits) {
    required=decompressed_size(frame,limits);if(capacity<required || (!output && required)) return false;
    auto decoded=decompress(frame,limits);need(decoded.size()==required,"decoded size differs from header");
    if(required) std::memcpy(output,decoded.data(),required);
    return true;
}
Encoder::Encoder(Network initial,Mode mode,Limits limits):initial_(std::move(initial)),mode_(mode),limits_(limits) {
    need(mode==Mode::bootstrap || mode==Mode::combined,"unknown DZip mode");
}
void Encoder::append(const std::uint8_t* input,std::size_t bytes) {
    need(!finalized_,"append after finalize requires reset");
    need(!bytes || input,"null input for nonempty append");
    need(input_.size()<=limits_.max_symbols && bytes<=limits_.max_symbols-input_.size(),"input exceeds symbol limit");
    if(bytes) input_.insert(input_.end(),input,input+bytes);
}
const Encoded& Encoder::finalize() {if(!finalized_) finalized_=compress(input_,initial_,mode_,limits_);return *finalized_;}
void Encoder::reset() {input_.clear();finalized_.reset();}
std::size_t Encoder::size() const noexcept {return input_.size();}
Bytes encode_raw(const std::vector<std::int32_t>& symbols,Network initial,Mode mode) {
    need(mode==Mode::bootstrap || mode==Mode::combined,"unknown DZip mode");need(symbols.size()<=16u*1024u*1024u,"symbol limit exceeded");
    for(auto symbol:symbols) need(symbol>=0 && unsigned(symbol)<initial.alphabet(),"symbol outside model alphabet");
    initial.reset_optimizer();Arithmetic coder;auto table=uniform(initial.alphabet());
    for(std::size_t i=0;i<std::min<std::size_t>(64,symbols.size());++i) coder.update(table,unsigned(symbols[i]),false);
    std::size_t predicted=0;
    for(std::size_t i=64;i<symbols.size();++i) {
        std::vector<std::int32_t> context(symbols.begin()+std::ptrdiff_t(i-64),symbols.begin()+std::ptrdiff_t(i));
        coder.update(frequencies(initial.predict(context)),unsigned(symbols[i]),false);
        ++predicted;if(mode==Mode::combined && predicted%128==0) adapt(initial,symbols,predicted);
    }
    return coder.finish();
}
std::vector<std::int32_t> decode_raw(const Bytes& payload,std::size_t length,Network initial,Mode mode) {
    need(length<=16u*1024u*1024u && !payload.empty(),"raw decoder length or payload invalid");need(mode==Mode::bootstrap || mode==Mode::combined,"unknown DZip mode");
    initial.reset_optimizer();Arithmetic coder;coder.bytes=payload;for(unsigned i=0;i<32;++i) coder.code=(coder.code<<1)|coder.bit();
    std::vector<std::int32_t> symbols;symbols.reserve(length);auto table=uniform(initial.alphabet());
    for(std::size_t i=0;i<std::min<std::size_t>(64,length);++i) symbols.push_back(std::int32_t(coder.decode(table)));
    std::size_t predicted=0;
    for(std::size_t i=64;i<length;++i) {
        std::vector<std::int32_t> context(symbols.end()-64,symbols.end());symbols.push_back(std::int32_t(coder.decode(frequencies(initial.predict(context)))));
        ++predicted;if(mode==Mode::combined && predicted%128==0) adapt(initial,symbols,predicted);
    }
    return symbols;
}
Encoded compress(const Bytes& input,const Network& initial,Mode mode,const Limits& limits) {
    need(input.size()<=limits.max_symbols,"input exceeds symbol limit");
    std::array<bool,256> present{};for(auto byte:input) present[byte]=true;Bytes alphabet;
    for(unsigned i=0;i<256;++i) if(present[i]) alphabet.push_back(std::uint8_t(i));
    need(input.empty() || alphabet.size()==initial.alphabet(),"input alphabet differs from provided model");
    if(input.empty()) for(unsigned i=0;i<initial.alphabet();++i) alphabet.push_back(std::uint8_t(i));
    std::array<std::int32_t,256> ids{};for(unsigned i=0;i<alphabet.size();++i) ids[alphabet[i]]=std::int32_t(i);
    std::vector<std::int32_t> symbols;symbols.reserve(input.size());for(auto byte:input) symbols.push_back(ids[byte]);
    auto raw_model=initial.serialize();need(raw_model.size()<=limits.max_model_bytes,"model exceeds byte limit");
    auto stored=store_model(raw_model);auto payload=encode_raw(symbols,initial,mode);
    Encoded result;auto& frame=result.bytes;frame={'D','Z','C','P','0','0','0','1'};
    put(frame,unsigned(mode),1);put(frame,1,1);put(frame,alphabet.size(),2);put(frame,input.size(),8);
    put(frame,raw_model.size(),8);put(frame,stored.size(),8);put(frame,payload.size(),8);
    frame.insert(frame.end(),alphabet.begin(),alphabet.end());frame.insert(frame.end(),stored.begin(),stored.end());frame.insert(frame.end(),payload.begin(),payload.end());
    put(frame,checksum(frame.data(),frame.size()),4);need(frame.size()<=limits.max_frame_bytes,"encoded frame exceeds byte limit");
    result.statistics.metadata_bits=(44+alphabet.size())*8;result.statistics.model_bits=stored.size()*8;
    result.statistics.payload_bits=payload.size()*8;result.statistics.checksum_bits=32;result.statistics.final_bits=frame.size()*8;
    return result;
}
Bytes decompress(const Bytes& frame,const Limits& limits) {
    need(frame.size()>=48 && frame.size()<=limits.max_frame_bytes,"frame byte limit or header invalid");Reader tail{frame,frame.size()-4};
    need(tail.get(4)==checksum(frame.data(),frame.size()-4),"frame checksum mismatch");Reader reader{frame};
    need(reader.take(8)==Bytes({'D','Z','C','P','0','0','0','1'}),"unknown DZip frame");
    auto mode=Mode(reader.get(1));need(mode==Mode::bootstrap || mode==Mode::combined,"unknown DZip mode");
    need(reader.get(1)==1,"unknown native numerical profile");auto alphabet_size=reader.get(2);auto length=reader.get(8);
    auto raw_length=reader.get(8),stored_length=reader.get(8),payload_length=reader.get(8);
    need(alphabet_size>0 && alphabet_size<=256 && length<=limits.max_symbols && raw_length<=limits.max_model_bytes,"frame resource limit exceeded");
    auto alphabet=reader.take(std::size_t(alphabet_size));need(std::is_sorted(alphabet.begin(),alphabet.end()) && std::adjacent_find(alphabet.begin(),alphabet.end())==alphabet.end(),"alphabet is not sorted unique");
    auto stored=reader.take(std::size_t(stored_length));auto payload=reader.take(std::size_t(payload_length));need(reader.pos==frame.size()-4,"frame lengths do not close");
    auto initial=Network::load(restore_model(stored,std::size_t(raw_length),limits),limits.max_model_bytes);
    need(initial.alphabet()==alphabet_size,"model and frame alphabet differ");auto symbols=decode_raw(payload,std::size_t(length),std::move(initial),mode);
    Bytes result;result.reserve(symbols.size());for(auto symbol:symbols) {need(unsigned(symbol)<alphabet.size(),"decoded symbol invalid");result.push_back(alphabet[unsigned(symbol)]);}return result;
}
}  // namespace dzip
