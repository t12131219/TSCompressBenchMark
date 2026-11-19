// Direct caller of the selected C11 reader and range entry points. No benchmark ABI.
#include "titchy.h"
#include <array>
#include <charconv>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <vector>
#include <cstring>

namespace {
constexpr size_t backing_cap = 128u << 10, value_cap = 8192, range_cap = 128, bit_cap = 16;
void require(bool value, const char *message) {
    if (!value) throw std::runtime_error(message);
}
size_t number(const char *s) {
    const std::string_view value(s);
    size_t result = 0;
    const auto parsed = std::from_chars(value.data(), value.data()+value.size(), result);
    require(parsed.ec == std::errc{} && parsed.ptr == value.data()+value.size(), "invalid request integer");
    return result;
}
using Bytes = std::vector<uint8_t>;
Bytes read(const char *path) {
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    require(file.good(), "open backing");
    const auto size = file.tellg();
    require(size >= 86 && size <= backing_cap, "backing extent");
    Bytes raw(static_cast<size_t>(size));
    file.seekg(0);
    file.read(reinterpret_cast<char *>(raw.data()),raw.size());
    require(file.good(), "read backing");
    return raw;
}
uint64_t little(const Bytes &raw,size_t start,size_t width) {
    require(width<=8 && start<=raw.size() && width<=raw.size()-start,"invalid split extent");
    uint64_t result=0;
    for (size_t i=0;i<width;++i) result |= uint64_t(raw[start+i])<<(8*i);
    return result;
}
struct Request { size_t n, point, start, count; std::vector<size_t> bits; };
struct Call { uint64_t offset; size_t length; bool ok; };
struct ReadLog {
    const Bytes &wire;
    uint64_t deny = UINT64_MAX;
    std::array<Call,1024> calls{};
    size_t used = 0;
    bool overflow = false;
    static int callback(void *self,uint64_t offset,void *out,size_t length) noexcept {
        auto &s=*static_cast<ReadLog*>(self);
        if (s.used == s.calls.size()) { s.overflow=true; return 1; }
        const bool ok=offset<=s.wire.size() && length<=s.wire.size()-offset && offset!=s.deny;
        s.calls[s.used++] = {offset,length,ok};
        if (ok && length) std::memcpy(out,s.wire.data()+offset,length);
        return !ok;
    }
    std::string drain(uint64_t result_bits=0) {
        require(!overflow,"read log overflow");
        std::ostringstream out;
        size_t requested=0, successful=0;
        out << "{\"calls\":[";
        for (size_t i=0;i<used;++i) {
            const auto c=calls[i];
            if(i) out << ',';
            out << '[' << c.offset << ',' << c.length << ',' << (c.ok?"true":"false") << ']';
            requested+=c.length;
            if(c.ok) successful+=c.length;
        }
        used=0;
        out << "],\"requested_bytes\":" << requested << ",\"successful_bytes\":" << successful;
        if(result_bits) out << ",\"result_logical_bits\":" << result_bits;
        out << '}';
        return out.str();
    }
};
using Reader=std::unique_ptr<titchy_reader,decltype(&titchy_reader_free)>;
Reader opened(ReadLog &log,size_t n,int expected=TITCHY_OK) {
    titchy_reader *p=nullptr;
    const int status=titchy_reader_open(ReadLog::callback,&log,log.wire.size(),n,&p);
    Reader ptr(p,titchy_reader_free);
    require(status==expected && bool(ptr)==(expected==TITCHY_OK),"callback reader open differs");
    return ptr;
}
Reader file_reader(const char *path,size_t n,int expected=TITCHY_OK) {
    titchy_reader *p=nullptr;
    const int status=titchy_reader_open_file(path,n,&p);
    Reader ptr(p,titchy_reader_free);
    require(status==expected && bool(ptr)==(expected==TITCHY_OK),"file reader open differs");
    return ptr;
}
template<class T> void array(std::ostream &out,const std::vector<T> &value) {
    out << '[';
    for(size_t i=0;i<value.size();++i){ if(i) out << ','; out << +value[i]; }
    out << ']';
}
void status(std::ostream &out,const char *name,int actual,int expected,bool comma=true) {
    require(actual==expected,name);
    if(comma) out << ',';
    out << '"' << name << "\":" << actual;
}
struct Results { std::string answer, reads; };
Results queries(titchy_reader *r,const Request &q,ReadLog *log) {
    require(titchy_reader_count(r)==q.n,"reader count");
    std::ostringstream result,reads;
    uint64_t point=0;
    std::vector<uint64_t> range(q.count);
    std::vector<uint8_t> bits(q.bits.size());
    require(titchy_reader_sample(r,q.point,&point)==TITCHY_OK,"point");
    result << "{\"point\":" << point;
    if(log) reads << "{\"point\":" << log->drain(64);
    require(titchy_reader_range(r,q.start,q.count,range.data(),range.size())==TITCHY_OK,"range");
    result << ",\"range\":";
    array(result,range);
    if(log) reads << ",\"range\":" << log->drain(64*q.count);
    for(size_t i=0;i<q.bits.size();++i) {
        require(titchy_reader_bit(r,q.bits[i],&bits[i])==TITCHY_OK,"bit");
        if(log) reads << ",\"bit-" << q.bits[i] << "\":" << log->drain(1);
    }
    result << ",\"bits\":";
    array(result,bits);
    result << '}';
    if(log) reads << '}';
    return {result.str(),reads.str()};
}
size_t later_split(const Bytes &wire) {
    require(little(wire,34,4)==2,"expected two splits");
    const uint64_t offset=little(wire,38+24+12,8);
    require(offset>=86 && offset<wire.size(),"later pair offset");
    return static_cast<size_t>(offset);
}
Bytes bad_pair(const Bytes &wire,size_t offset) {
    Bytes copy=wire;
    copy[offset]=0xff;
    return copy;
}
void loaded(const Bytes &wire,const Request &q) {
    ReadLog log{wire};
    auto reader=opened(log,q.n);
    const auto open_log=log.drain();
    const auto first=queries(reader.get(),q,&log), second=queries(reader.get(),q,&log);
    std::ostringstream statuses;
    uint64_t sample=0;
    uint8_t bit=0;
    std::vector<uint64_t> result(q.count);
    status(statuses,"reader_sample_oob",titchy_reader_sample(reader.get(),q.n,&sample),TITCHY_INVALID,false);
    status(statuses,"reader_bit_oob",titchy_reader_bit(reader.get(),64*q.n,&bit),TITCHY_INVALID);
    status(statuses,"reader_capacity",titchy_reader_range(reader.get(),q.start,q.count,result.data(),q.count-1),TITCHY_CAPACITY);
    status(statuses,"reader_range_oob",titchy_reader_range(reader.get(),q.n,1,result.data(),q.count),TITCHY_INVALID);
    status(statuses,"empty_eof",titchy_reader_range(reader.get(),q.n,0,nullptr,0),TITCHY_OK);
    require(!log.used && !log.overflow,"reader bounds must not touch backing");
    reader.reset();

    ReadLog denied_index{wire,38};
    opened(denied_index,q.n,TITCHY_STREAM);
    Bytes index=wire;
    index[38]^=1;
    ReadLog invalid_index{index};
    opened(invalid_index,q.n,TITCHY_STREAM);
    const auto offset=later_split(wire);
    ReadLog denied_pair{wire,offset};
    reader=opened(denied_pair,q.n);
    denied_pair.drain();
    status(statuses,"pair_callback_failure",titchy_reader_sample(reader.get(),q.point,&sample),TITCHY_STREAM);
    reader.reset();
    const auto damaged=bad_pair(wire,offset);
    ReadLog corrupt{damaged};
    reader=opened(corrupt,q.n);
    corrupt.drain();
    require(titchy_reader_sample(reader.get(),0,&sample)==TITCHY_OK,"valid prefix on damaged later split");
    const auto prefix=sample;
    const auto prefix_reads=corrupt.drain(64);
    status(statuses,"touched_bad_pair",titchy_reader_sample(reader.get(),q.point,&sample),TITCHY_STREAM);
    reader.reset();
    std::cout << "{\"count\":" << q.n << ",\"open\":" << open_log << ",\"results\":[" << first.answer << ',' << second.answer
              << "],\"reads\":[" << first.reads << ',' << second.reads << "],\"statuses\":{" << statuses.str()
              << "},\"denied_index\":" << denied_index.drain() << ",\"bad_index\":" << invalid_index.drain()
              << ",\"denied_pair\":" << denied_pair.drain() << ",\"touched_pair\":" << corrupt.drain()
              << ",\"prefix\":" << prefix << ",\"prefix_reads\":" << prefix_reads << "}\n";
}
void file(const char *path,const Request &q) {
    auto reader=file_reader(path,q.n);
    const auto result=queries(reader.get(),q,nullptr);
    reader.reset();
    file_reader(path,q.n-1,TITCHY_CAPACITY);
    file_reader("/inputs/absent",q.n,TITCHY_INVALID);
    std::cout << "{\"result\":" << result.answer << ",\"file_quota\":2,\"file_missing\":1}\n";
}
void range(const Bytes &wire,const Request &q) {
    std::vector<uint64_t> result(q.count);
    require(titchy_c_range(wire.data(),wire.size(),q.start,q.count,result.data(),q.count,q.n)==TITCHY_OK,"stateless range");
    const auto saved=result;
    std::ostringstream statuses;
    status(statuses,"empty_eof",titchy_c_range(wire.data(),wire.size(),q.n,0,nullptr,0,q.n),TITCHY_OK,false);
    status(statuses,"stateless_oob",titchy_c_range(wire.data(),wire.size(),q.n,1,result.data(),q.count,q.n),TITCHY_INVALID);
    status(statuses,"stateless_capacity",titchy_c_range(wire.data(),wire.size(),q.start,q.count,result.data(),q.count-1,q.n),TITCHY_CAPACITY);
    status(statuses,"stateless_quota",titchy_c_range(wire.data(),wire.size(),q.start,q.count,result.data(),q.count,q.n-1),TITCHY_CAPACITY);
    const auto damaged=bad_pair(wire,later_split(wire));
    status(statuses,"stateless_unrelated_bad_pair",titchy_c_range(damaged.data(),damaged.size(),0,1,result.data(),q.count,q.n),TITCHY_STREAM);
    status(statuses,"stateless_bad_pair_empty_request",titchy_c_range(damaged.data(),damaged.size(),q.n,0,nullptr,0,q.n),TITCHY_STREAM);
    std::cout << "{\"result\":";
    array(std::cout,saved);
    std::cout << ",\"statuses\":{" << statuses.str() << "}}\n";
}
}

int main(int argc,char **argv) {
    try {
        require(argc>=8 && argc<=7+bit_cap,"expected mode backing count point start length bits...");
        const std::string_view mode(argv[1]);
        Request q{number(argv[3]),number(argv[4]),number(argv[5]),number(argv[6]),{}};
        require(q.n && q.n<=value_cap && q.point<q.n && q.start<q.n && q.count && q.count<=range_cap &&
                q.count<=q.n-q.start,"request outside supported limits");
        for(int i=7;i<argc;++i){ const auto bit=number(argv[i]); require(bit<64*q.n,"bit limit"); q.bits.push_back(bit); }
        if(mode=="loaded") loaded(read(argv[2]),q);
        else if(mode=="file") file(argv[2],q);
        else if(mode=="range") range(read(argv[2]),q);
        else throw std::runtime_error("invalid access mode");
        return std::cout.good()?0:2;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
