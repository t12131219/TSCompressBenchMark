// Arithmetic coding equations derived from the MIT-licensed Project Nayuki
// reference used by DeepZip. Attribution is in LICENSES/Project-Nayuki-MIT.txt.
#include "internal.hpp"
#include <array>
#include <functional>

namespace deepzip {
const char* version() noexcept { return "deepzip-cpp/1.0.0"; }
std::uint64_t Ledger::final_bits() const {
    return metadata_bits+model_bits+lengths_bits+entropy_bits+padding_bits+checksum_bits;
}
std::uint32_t crc32(const std::uint8_t* p, std::size_t n) {
    std::uint32_t crc=0xffffffffu;
    for(std::size_t i=0;i<n;++i) {
        crc^=p[i];
        for(unsigned j=0;j<8;++j) crc=(crc>>1)^(0xedb88320u & (0u-(crc&1)));
    }
    return ~crc;
}
static std::vector<std::uint64_t> make_cumulative(const std::vector<double>& p) {
    require(!p.empty() && p.size()<=256,Status::invalid_parameter,"invalid probability alphabet");
    std::vector<std::uint64_t> c(1,0);
    double sum=0;
    for(double v:p) {
        require(std::isfinite(v)&&v>=0&&v<=1,Status::invalid_parameter,"invalid probability value");
        sum += v*10000000.0+1.0;
        require(sum<static_cast<double>((1u<<30)+2u),Status::invalid_parameter,"arithmetic count overflow");
        c.push_back(static_cast<std::uint64_t>(sum));
        require(c.back()>c[c.size()-2],Status::invalid_parameter,"zero probability frequency");
    }
    return c;
}
std::vector<std::uint64_t> cumulative(const std::vector<float>& p) {
    return make_cumulative(std::vector<double>(p.begin(),p.end()));
}
std::vector<std::uint64_t> uniform_cumulative(std::uint32_t alphabet) {
    require(alphabet>0 && alphabet<=256,Status::invalid_parameter,"invalid uniform alphabet");
    return make_cumulative(std::vector<double>(alphabet,1.0/alphabet));
}
namespace {
struct BitWriter {
    Bytes bytes;
    std::uint64_t bits=0;
    void write(unsigned bit) {
        if(bits%8==0) bytes.push_back(0);
        bytes.back()|=static_cast<std::uint8_t>(bit << (7-bits%8));
        ++bits;
    }
};
struct BitReader {
    const Bytes& bytes;
    std::uint64_t pos=0;
    unsigned read() {
        auto at=pos++;
        return at/8<bytes.size()?((bytes[static_cast<std::size_t>(at/8)]>>(7-at%8))&1):0;
    }
};
struct Range {
    std::uint32_t low=0,high=0xffffffffu;
    template<class Shift,class Underflow>
    void update(const std::vector<std::uint64_t>& c,unsigned symbol,Shift shift,Underflow underflow) {
        require(symbol+1<c.size() && c.front()==0 && c.back()>0 && c.back()<=(1u<<30)+2u,
                Status::invalid_parameter,"invalid arithmetic table or symbol");
        require(c[symbol]<c[symbol+1],Status::invalid_parameter,"zero arithmetic frequency");
        std::uint64_t width=static_cast<std::uint64_t>(high)-low+1;
        std::uint64_t next_low=low+c[symbol]*width/c.back();
        std::uint64_t next_high=low+c[symbol+1]*width/c.back()-1;
        require(next_low<=next_high && next_high<=0xffffffffu,Status::corrupt_stream,"invalid arithmetic range");
        low=static_cast<std::uint32_t>(next_low); high=static_cast<std::uint32_t>(next_high);
        while(((low^high)&0x80000000u)==0) {
            shift(); low<<=1; high=(high<<1)|1u;
        }
        while((low&~high&0x40000000u)!=0) {
            underflow(); low=(low<<1)&0x7fffffffu;
            high=((high<<1)&0x7fffffffu)|0x80000001u;
        }
    }
};
struct Encoder {
    Range range;
    BitWriter output;
    std::uint64_t pending=0;
    void write(const std::vector<std::uint64_t>& c,unsigned symbol) {
        range.update(c,symbol,[&]{
            unsigned bit=range.low>>31; output.write(bit);
            for(std::uint64_t i=0;i<pending;++i) output.write(bit^1u);
            pending=0;
        },[&]{++pending;});
    }
    void finish() { output.write(1); }
};
struct Decoder {
    Range range;
    BitReader input;
    std::uint32_t code=0;
    explicit Decoder(const Bytes& b):input{b} {for(unsigned i=0;i<32;++i) code=(code<<1)|input.read();}
    unsigned read(const std::vector<std::uint64_t>& c) {
        require(code>=range.low && code<=range.high,Status::corrupt_stream,"arithmetic code outside range");
        std::uint64_t width=static_cast<std::uint64_t>(range.high)-range.low+1;
        std::uint64_t offset=static_cast<std::uint64_t>(code)-range.low;
        auto value=((offset+1)*c.back()-1)/width;
        auto it=std::upper_bound(c.begin(),c.end(),value);
        require(it!=c.begin() && it!=c.end(),Status::corrupt_stream,"invalid decoded symbol");
        unsigned symbol=static_cast<unsigned>(it-c.begin()-1);
        range.update(c,symbol,[&]{code=(code<<1)|input.read();},[&]{
            code=(code&0x80000000u)|((code<<1)&0x7fffffffu)|input.read();
        });
        return symbol;
    }
};
void varint(Bytes& b,std::uint64_t value) {
    for(;;) {
        unsigned byte=static_cast<unsigned>(value&127);
        value>>=7;
        if(!value) {b.push_back(static_cast<std::uint8_t>(byte));return;}
        b.push_back(static_cast<std::uint8_t>(byte|128)); --value;
    }
}
std::uint64_t varint(Reader& r) {
    std::uint64_t value=0,radix=1;
    auto start=r.pos;
    for(unsigned i=0;i<10;++i) {
        auto byte=r.get(1),part=byte&127;
        require(part==0 || radix <= (std::numeric_limits<std::uint64_t>::max()-value)/part,
                Status::corrupt_stream,"varint overflow");
        value+=part*radix;
        if(!(byte&128)) {
            Bytes canonical; varint(canonical,value);
            require(canonical.size()==r.pos-start && std::equal(canonical.begin(),canonical.end(),r.bytes.begin()+start),
                    Status::corrupt_stream,"noncanonical varint");
            return value;
        }
        require(radix<=std::numeric_limits<std::uint64_t>::max()/128,
                Status::corrupt_stream,"varint radix overflow");
        radix*=128;
        require(value<=std::numeric_limits<std::uint64_t>::max()-radix,
                Status::corrupt_stream,"varint continuation overflow");
        value+=radix;
    }
    throw Error(Status::corrupt_stream,"unterminated varint");
}
void validate(const Model& model,const Config& c,std::size_t n) {
    require(c.lanes>0 && c.lanes<=c.limits.max_lanes && c.lanes<=4096,
            Status::invalid_parameter,"invalid lane count");
    require(c.alphabet.size()==model.alphabet_size(),Status::invalid_parameter,"dictionary/model alphabet mismatch");
    std::array<bool,256> seen{};
    for(auto byte:c.alphabet) {require(!seen[byte],Status::invalid_parameter,"duplicate dictionary byte");seen[byte]=true;}
    require(n<=c.limits.max_input_bytes,Status::resource_limit,"input exceeds byte limit");
    require(model.serialize().size()<=c.limits.max_model_bytes,Status::resource_limit,"model exceeds byte limit");
    require(c.backend==Backend::scalar || c.backend==Backend::cuda,Status::unsupported,"unknown numeric profile");
    if(c.backend==Backend::cuda) require(cuda_available(),Status::unsupported,"CUDA requested but unavailable");
}
void encode_group(const Model& model,const Bytes& symbols,std::size_t start,std::size_t length,
                  unsigned count,Backend backend,std::vector<Encoder>& encoders) {
    auto uniform=uniform_cumulative(model.alphabet_size());
    for(unsigned b=0;b<count;++b) for(std::size_t j=0;j<std::min<std::size_t>(64,length);++j)
        encoders[b].write(uniform,symbols[start+b*length+j]);
    std::vector<std::uint32_t> contexts(static_cast<std::size_t>(count)*64);
    for(std::size_t j=64;j<length;++j) {
        for(unsigned b=0;b<count;++b) for(unsigned k=0;k<64;++k)
            contexts[b*64+k]=symbols[start+b*length+j-64+k];
        auto probabilities=model.predict(contexts,backend);
        auto alphabet=model.alphabet_size();
        for(unsigned b=0;b<count;++b) {
            auto first=probabilities.begin()+b*alphabet;
            auto c=cumulative(std::vector<float>(first,first+alphabet));
            encoders[b].write(c,symbols[start+b*length+j]);
        }
    }
    for(auto& e:encoders) e.finish();
}
void decode_group(const Model& model,Bytes& symbols,std::size_t start,std::size_t length,
                  unsigned count,Backend backend,const std::vector<Bytes>& streams,std::size_t offset) {
    std::vector<Decoder> decoders;
    decoders.reserve(count);
    for(unsigned b=0;b<count;++b) decoders.emplace_back(streams[offset+b]);
    auto uniform=uniform_cumulative(model.alphabet_size());
    for(unsigned b=0;b<count;++b) for(std::size_t j=0;j<std::min<std::size_t>(64,length);++j)
        symbols[start+b*length+j]=static_cast<std::uint8_t>(decoders[b].read(uniform));
    std::vector<std::uint32_t> contexts(static_cast<std::size_t>(count)*64);
    for(std::size_t j=64;j<length;++j) {
        for(unsigned b=0;b<count;++b) for(unsigned k=0;k<64;++k)
            contexts[b*64+k]=symbols[start+b*length+j-64+k];
        auto probabilities=model.predict(contexts,backend);
        auto alphabet=model.alphabet_size();
        for(unsigned b=0;b<count;++b) {
            auto first=probabilities.begin()+b*alphabet;
            auto c=cumulative(std::vector<float>(first,first+alphabet));
            symbols[start+b*length+j]=static_cast<std::uint8_t>(decoders[b].read(c));
        }
    }
}
}  // namespace
static void validate_tables(const std::vector<std::vector<std::uint64_t>>& tables) {
    for(const auto& c:tables) {
        require(c.size()>=2 && c.size()<=257 && c.front()==0 && c.back()<=(1u<<30)+2u,
                Status::invalid_parameter,"invalid frozen cumulative table");
        for(std::size_t i=1;i<c.size();++i) require(c[i]>c[i-1],Status::invalid_parameter,"nonincreasing frozen cumulative table");
    }
}
Bytes encode_arithmetic(const Bytes& symbols,const std::vector<std::vector<std::uint64_t>>& tables) {
    require(symbols.size()==tables.size(),Status::invalid_parameter,"table/symbol count mismatch");
    validate_tables(tables); Encoder encoder;
    for(std::size_t i=0;i<symbols.size();++i) encoder.write(tables[i],symbols[i]);
    encoder.finish(); return encoder.output.bytes;
}
Bytes decode_arithmetic(const Bytes& stream,const std::vector<std::vector<std::uint64_t>>& tables) {
    validate_tables(tables);
    require(!stream.empty(),Status::corrupt_stream,"empty frozen arithmetic stream");
    Decoder decoder(stream); Bytes symbols;
    for(const auto& c:tables) symbols.push_back(static_cast<std::uint8_t>(decoder.read(c)));
    return symbols;
}
std::size_t compress_bound(const Model& model,std::size_t n,const Config& config) {
    validate(model,config,n);
    // At most 32 range-normalization bits per symbol, one finish byte and
    // at most ten bytes for each of the two per-stream varints.
    return checked_add(checked_add(48+config.alphabet.size(),model.serialize().size()),
                       checked_add(checked_mul(n,4),checked_mul(config.lanes+1,21)));
}
Encoded compress(const Model& model,const Bytes& input,const Config& config) {
    auto bound=compress_bound(model,input.size(),config);
    std::array<int,256> dictionary; dictionary.fill(-1);
    for(std::size_t i=0;i<config.alphabet.size();++i) dictionary[config.alphabet[i]]=static_cast<int>(i);
    Bytes symbols; symbols.reserve(input.size());
    for(auto byte:input) {
        require(dictionary[byte]>=0,Status::invalid_parameter,"input byte absent from dictionary");
        symbols.push_back(static_cast<std::uint8_t>(dictionary[byte]));
    }
    std::size_t length=input.size()/config.lanes,l=length*config.lanes;
    std::vector<Encoder> primary(config.lanes),tail(1);
    encode_group(model,symbols,0,length,config.lanes,config.backend,primary);
    encode_group(model,symbols,l,input.size()-l,1,config.backend,tail);
    Encoded result{}; result.backend=config.backend;
    auto& out=result.bytes;
    out.reserve(bound);
    out.insert(out.end(),{'D','Z','C','P','P','0','0','1'});
    put(out,1,4); put(out,static_cast<std::uint32_t>(config.backend),4);
    put(out,input.size(),8); put(out,config.lanes,4); put(out,config.alphabet.size(),4);
    put(out,model.serialize().size(),8); put(out,crc32(input.data(),input.size()),4);
    out.insert(out.end(),config.alphabet.begin(),config.alphabet.end());
    out.insert(out.end(),model.serialize().begin(),model.serialize().end());
    result.ledger.metadata_bits=(40+config.alphabet.size())*8;
    result.ledger.model_bits=model.serialize().size()*8;
    result.ledger.checksum_bits=64;
    auto append=[&](const Encoder& encoder) {
        auto start=out.size();
        varint(out,encoder.output.bytes.size()); varint(out,encoder.output.bits);
        result.ledger.lengths_bits+=(out.size()-start)*8;
        out.insert(out.end(),encoder.output.bytes.begin(),encoder.output.bytes.end());
        result.ledger.entropy_bits+=encoder.output.bits;
        result.ledger.padding_bits+=encoder.output.bytes.size()*8-encoder.output.bits;
    };
    for(const auto& encoder:primary) append(encoder);
    append(tail[0]);
    put(out,crc32(out.data(),out.size()),4);
    require(out.size()<=bound && result.ledger.final_bits()==out.size()*8,
            Status::resource_limit,"compression bound/accounting invariant failed");
    return result;
}
Bytes decompress(const Bytes& stream,const Limits& limits) {
    require(stream.size()>=48,Status::corrupt_stream,"truncated container");
    // Avoid allowing attacker-controlled lengths to drive allocation.
    auto maximum=checked_add(checked_add(48+256,limits.max_model_bytes),
        checked_add(checked_mul(limits.max_input_bytes,4),checked_mul(std::min(limits.max_lanes,4096u)+1u,21)));
    require(stream.size()<=maximum,Status::resource_limit,"container exceeds size limit");
    Reader checksum{stream}; checksum.pos=stream.size()-4;
    require(crc32(stream.data(),stream.size()-4)==checksum.get(4),Status::corrupt_stream,"container checksum mismatch");
    Reader r{stream};
    require(r.take(8)==Bytes({'D','Z','C','P','P','0','0','1'}) && r.get(4)==1,
            Status::corrupt_stream,"unknown container version");
    auto backend=static_cast<Backend>(r.get(4));
    auto n=r.get(8),lanes=r.get(4),alphabet=r.get(4),model_length=r.get(8),input_crc=r.get(4);
    require(n<=limits.max_input_bytes && model_length<=limits.max_model_bytes,
            Status::resource_limit,"declared input or model exceeds limit");
    require(lanes>0 && lanes<=limits.max_lanes && lanes<=4096 && alphabet>0 && alphabet<=256,
            Status::corrupt_stream,"invalid container dimensions");
    Config config; config.lanes=static_cast<std::uint32_t>(lanes); config.backend=backend; config.limits=limits;
    config.alphabet=r.take(static_cast<std::size_t>(alphabet));
    auto model=Model::load(r.take(static_cast<std::size_t>(model_length)),limits);
    validate(model,config,static_cast<std::size_t>(n));
    std::vector<Bytes> streams;
    streams.reserve(static_cast<std::size_t>(lanes)+1);
    for(std::uint64_t i=0;i<=lanes;++i) {
        auto physical=varint(r),bits=varint(r);
        require(physical>0 && physical<=stream.size() && bits>0 && bits<=physical*8 &&
                (bits+7)/8==physical,Status::corrupt_stream,"inconsistent arithmetic stream bit count");
        auto bytes=r.take(static_cast<std::size_t>(physical));
        if(bits%8) require((bytes.back()&((1u<<(8-bits%8))-1))==0,
                            Status::corrupt_stream,"nonzero arithmetic padding");
        streams.push_back(std::move(bytes));
    }
    require(r.pos==stream.size()-4,Status::corrupt_stream,"trailing container bytes");
    Bytes symbols(static_cast<std::size_t>(n));
    std::size_t length=static_cast<std::size_t>(n/lanes),l=length*static_cast<std::size_t>(lanes);
    decode_group(model,symbols,0,length,static_cast<unsigned>(lanes),backend,streams,0);
    decode_group(model,symbols,l,symbols.size()-l,1,backend,streams,static_cast<std::size_t>(lanes));
    for(auto& byte:symbols) byte=config.alphabet[byte];
    require(crc32(symbols.data(),symbols.size())==input_crc,Status::corrupt_stream,"decoded input checksum mismatch");
    return symbols;
}
std::size_t compress_to(const Model& model,const Bytes& input,const Config& config,std::uint8_t* out,std::size_t capacity) {
    auto bound=compress_bound(model,input.size(),config);
    require(out!=nullptr && capacity>=bound,Status::insufficient_capacity,"output capacity smaller than compression bound");
    auto encoded=compress(model,input,config);
    std::copy(encoded.bytes.begin(),encoded.bytes.end(),out);
    return encoded.bytes.size();
}
Codec::Codec(Model model,Config config):model_(std::move(model)),config_(std::move(config)) {
    validate(model_,config_,0);
}
void Codec::append(const std::uint8_t* p,std::size_t n) {
    require(!encoded_,Status::invalid_parameter,"append after finalize requires reset");
    require(n==0 || p!=nullptr,Status::invalid_parameter,"null input with nonzero length");
    require(n<=config_.limits.max_input_bytes-input_.size(),Status::resource_limit,"buffered input exceeds limit");
    if(n) input_.insert(input_.end(),p,p+n);
}
const Encoded& Codec::finalize() {
    if(!encoded_) encoded_=std::make_unique<Encoded>(compress(model_,input_,config_));
    return *encoded_;
}
void Codec::reset() noexcept {encoded_.reset(); input_.clear();}
std::size_t Codec::buffered_bytes() const noexcept {return input_.size();}
}  // namespace deepzip
