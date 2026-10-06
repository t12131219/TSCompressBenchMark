// Elf VLDB2023 translation; source provenance and local license override in contract.md.
#include "elf_vldb.hpp"
#include <algorithm>
#include <charconv>
#include <cfenv>
#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>
#include <type_traits>

namespace elf_vldb {
namespace {
constexpr std::size_t max_values_bytes=16u*1024u*1024u, max_stream_bytes=64u*1024u*1024u;
constexpr std::size_t header=32;
static_assert(sizeof(float)==4 && sizeof(double)==8 && std::numeric_limits<float>::is_iec559 && std::numeric_limits<double>::is_iec559,"IEEE754 binary32/binary64 required");
void need(bool ok, const char* message) { if(!ok) throw std::invalid_argument(message); }
unsigned width_of(Width width) {
    need(width==Width::binary32 || width==Width::binary64,"invalid float width");
    need(std::fegetround()==FE_TONEAREST,"round-to-nearest floating environment required");
    return static_cast<unsigned>(width);
}
std::uint64_t load(const std::uint8_t* p,unsigned n) {
    std::uint64_t v=0; for(unsigned i=0;i<n;++i) v|=std::uint64_t(p[i])<<(8*i); return v;
}
void store(Bytes& b,std::uint64_t v,unsigned n) {
    for(unsigned i=0;i<n;++i)b.push_back(std::uint8_t(v>>(8*i)));
}
std::uint32_t crc(const std::uint8_t* p,std::size_t n) {
    std::uint32_t c=~0u;
    for(std::size_t i=0;i<n;++i) { c^=p[i]; for(unsigned j=0;j<8;++j)c=(c>>1)^(0xedb88320u&(0u-(c&1))); }
    return ~c;
}
struct Writer {
    Bytes bytes; std::uint64_t bits=0;
    void put(std::uint64_t value,unsigned n) {
        need(n<=64,"invalid bit width");
        for(unsigned i=n;i>0;--i) {
            if(bits%8==0) { need(bytes.size()<max_stream_bytes,"stream limit"); bytes.push_back(0); }
            bytes.back()|=std::uint8_t(((value>>(i-1))&1)<<(7-bits%8)); ++bits;
        }
    }
};
struct Reader {
    const std::uint8_t* bytes; std::uint64_t limit, bits=0;
    std::uint64_t get(unsigned n) {
        need(n<=64 && n<=limit-bits,"truncated bitstream");
        std::uint64_t v=0;
        for(unsigned i=0;i<n;++i) {v=(v<<1)|((bytes[bits/8]>>(7-bits%8))&1);++bits;}
        return v;
    }
};
template<class T> struct Traits;
template<> struct Traits<float> {
    using UInt=std::uint32_t; using Int=std::int32_t;
    static constexpr unsigned width=32, fraction=23, bias=127, exponent_mask=255, significant=8;
    static constexpr unsigned trailing_bits=6, beta_bits=3, small=8, small_bits=3, large_bits=5;
    static constexpr UInt end=0x7fc00000;
    static constexpr unsigned buckets[8]={0,6,10,12,14,16,18,20};
};
template<> struct Traits<double> {
    using UInt=std::uint64_t; using Int=std::int64_t;
    static constexpr unsigned width=64, fraction=52, bias=1023, exponent_mask=2047, significant=17;
    static constexpr unsigned trailing_bits=7, beta_bits=4, small=16, small_bits=4, large_bits=6;
    static constexpr UInt end=0x7ff8000000000000ULL;
    static constexpr unsigned buckets[8]={0,8,12,16,18,20,22,24};
};
template<class T> T power(int exponent) {
    // Java parses a decimal string; repeated multiplication or pow is different.
    std::string text="1e"+std::to_string(exponent); T result=0;
    auto parsed=std::from_chars(text.data(),text.data()+text.size(),result);
    if(parsed.ec==std::errc::result_out_of_range)
        return exponent>0?std::numeric_limits<T>::infinity():T(0);
    need(parsed.ec==std::errc() && parsed.ptr==text.data()+text.size(),"decimal power parse failed");
    return result;
}
template<class T> typename Traits<T>::Int java_integer(T v) {
    using I=typename Traits<T>::Int;
    if(std::isnan(v))return 0;
    // Threshold is exact 2^(width-1). Never cast an out-of-range value.
    T edge=std::ldexp(T(1),Traits<T>::width-1);
    if(v>=edge)return std::numeric_limits<I>::max();
    if(v<=-edge)return std::numeric_limits<I>::min();
    return static_cast<I>(v);
}
template<class T> T number(typename Traits<T>::UInt u) { T v;std::memcpy(&v,&u,sizeof(v));return v; }
template<class T> typename Traits<T>::UInt pattern(T v) {
    typename Traits<T>::UInt u;std::memcpy(&u,&v,sizeof(v));return u;
}
template<class T> int decimal_sp(T v,bool& reciprocal) {
    double log=std::log10(static_cast<double>(v));
    need(std::isfinite(log) && log>-1000 && log<1000,"invalid decimal magnitude");
    reciprocal=v<T(1) && log==std::floor(log);return static_cast<int>(std::floor(log));
}
template<class T> std::pair<int,int> alpha_beta(T v,int) {
    v=std::abs(v);
    // The original binary32 encoder rounds log10 to float before floor.
    T log=T(std::log10(static_cast<double>(v)));need(std::isfinite(log),"invalid magnitude");
    int sp=static_cast<int>(std::floor(log)),i=sp>=0?1:-sp;
    T temp=0;typename Traits<T>::Int integer=0;
    for(;;){need(i>0 && i<=400,"source significance search does not terminate");temp=T(v*power<T>(i));integer=java_integer(temp);need(std::isfinite(temp),"source significance search does not terminate");if(static_cast<T>(integer)==temp)break;++i;}
    int beta=T(temp/power<T>(i))!=v?int(Traits<T>::significant):sp+i+1;
    return {beta-sp-1,(v<T(1) && T(sp)==log)?0:beta};
}
int f_alpha(int alpha) {
    static constexpr int f[]={0,4,7,10,14,17,20,24,27,30,34,37,40,44,47,50,54,57,60,64,67};
    need(alpha>0 && alpha<=400,"invalid source erasure scale");
    return alpha<21?f[alpha]:int(std::ceil(alpha*(std::log(10.)/std::log(2.))));
}
template<class U> unsigned trailing(U u) {
    unsigned n=0;if(!u)return sizeof(U)*8;
    while((u&1)==0) {++n;u>>=1;}return n;
}
template<class U> unsigned leading(U u) {
    unsigned n=0;U mask=U(1)<<(sizeof(U)*8-1);
    while(mask && !(u&mask)) {++n;mask>>=1;}return n;
}
template<class T> struct State {
    using A=Traits<T>;using U=typename A::UInt;
    Writer writer;U previous=0;unsigned saved_lead=A::width,saved_tail=A::width;
    bool first=true;int beta=std::numeric_limits<int>::max();std::size_t count=0;
    void xor_value(U value) {
        if(first) {
            first=false;previous=value;unsigned tail=trailing(value);
            writer.put(tail,A::trailing_bits);
            if(tail<A::width)writer.put(value>>tail,A::width-tail);
            return;
        }
        U x=previous^value;
        if(x==0)writer.put(1,2);
        else {
            unsigned l=leading(x),t=trailing(x),index=0;
            for(unsigned i=1;i<8;++i)if(A::buckets[i]<=l)index=i;
            l=A::buckets[index];
            if(l==saved_lead && t>=saved_tail) {
                writer.put(0,2);writer.put(x>>saved_tail,A::width-saved_lead-saved_tail);
            } else {
                saved_lead=l;saved_tail=t;unsigned center=A::width-l-t;
                bool small=center<=A::small;
                writer.put(small?2:3,2);writer.put(index,3);
                writer.put(center,small?A::small_bits:A::large_bits);
                writer.put(x>>t,center);
            }
            previous=value;
        }
    }
    void add(U u,bool lossless) {
        T v=number<T>(u);
        if(v==0 || std::isinf(v))writer.put(0,1);
        else if(std::isnan(v)) {need(!lossless,"NaN is the source END marker");writer.put(0,1);u=A::end;}
        else {
            auto ab=alpha_beta(v,beta);
            int e=int((u>>A::fraction)&A::exponent_mask);
            int erase=int(A::fraction)-(f_alpha(ab.first)+e-int(A::bias));
            // Java shift distance is masked even when the computed distance
            // is negative or exceeds the word width.
            U mask=U(~U(0))<<(unsigned(erase)&(A::width-1));
            U delta=U(~mask)&u;
            if(delta && erase>(A::width==64?4:3) && (A::width==32 || ab.second<16)) {
                writer.put(1,1);writer.put(unsigned(ab.second),A::beta_bits);
                u&=mask;
            } else writer.put(0,1);
        }
        xor_value(u);++count;
    }
    Encoded finish() {
        std::uint64_t data=writer.bits;
        writer.put(0,1);xor_value(A::end);writer.put(0,1);
        auto bits=std::uint64_t(writer.bytes.size())*8;
        return {std::move(writer.bytes),bits,bits,data};
    }
};
template<class T> Encoded raw_encode(const std::uint8_t* values,std::size_t count,bool lossless) {
    need(count<=max_values_bytes/sizeof(T),"value limit");need(values || !count,"null input");
    State<T> state;
    for(std::size_t i=0;i<count;++i)state.add(typename Traits<T>::UInt(load(values+i*sizeof(T),sizeof(T))),lossless);
    return state.finish();
}
template<class T> Decoded raw_decode(const std::uint8_t* bytes,std::size_t size) {
    using A=Traits<T>;using U=typename A::UInt;
    need(bytes && size && size<=max_stream_bytes,"invalid encoded size");Reader r{bytes,std::uint64_t(size)*8};
    Decoded out{{},A::width==32?Width::binary32:Width::binary64,0,0};
    U previous=0;unsigned saved_l=A::width,saved_t=A::width;bool first=true;int beta=-1;
    for(;;) {
        bool erased=r.get(1)==1;
        if(erased)beta=int(r.get(A::beta_bits));
        U u;
        if(first) {
            first=false;unsigned tail=unsigned(r.get(A::trailing_bits));need(tail<=A::width,"invalid first trailing count");
            u=tail==A::width?0:U(r.get(A::width-tail))<<tail;
        } else {
            unsigned flag=unsigned(r.get(2));U x=0;
            if(flag==0) {
                need(saved_l<A::width && saved_t<A::width && saved_l+saved_t<A::width,"missing XOR window");
                x=U(r.get(A::width-saved_l-saved_t))<<saved_t;
            } else if(flag>=2) {
                saved_l=A::buckets[r.get(3)];unsigned center=unsigned(r.get(flag==2?A::small_bits:A::large_bits));
                if(!center)center=flag==2?A::small:A::width;
                need(center<=A::width-saved_l,"invalid XOR window");saved_t=A::width-saved_l-center;
                x=U(r.get(center))<<saved_t;
            }
            u=previous^x;
        }
        if(u==A::end) {need(!erased,"erased terminator");out.consumed_bits=r.bits;break;}
        previous=u;
        if(erased) {
            need(beta>=0,"missing beta state");T v=number<T>(u);need(v!=0 && std::isfinite(v),"invalid erased value");
            bool ignored;int sp=decimal_sp(std::abs(v),ignored);
            if(beta==0) {
                need(-sp-1>0,"invalid reciprocal scale");T recovered=power<T>(sp+1);v=v<0?-recovered:recovered;
            } else {
                int alpha=beta-sp-1;need(alpha>0 && alpha<=400,"invalid recovery scale");
                T scale=power<T>(alpha);T product=T(v*scale);
                double rounded=v<0?std::floor(static_cast<double>(product)):std::ceil(static_cast<double>(product));
                v=T(rounded/static_cast<double>(scale));
            }
            need(std::isfinite(v),"invalid recovered value");u=pattern(v);
        }
        need(out.values.size()<=max_values_bytes-sizeof(T),"decoded value limit");store(out.values,u,sizeof(T));++out.count;
    }
    return out;
}
Encoded frame(Encoded raw,std::size_t count,Width width) {
    Bytes bytes{'E','L','F','1',std::uint8_t(width_of(width)),0,0,0};
    store(bytes,count,8);store(bytes,raw.bytes.size(),8);store(bytes,crc(raw.bytes.data(),raw.bytes.size()),4);store(bytes,0,4);
    bytes.insert(bytes.end(),raw.bytes.begin(),raw.bytes.end());raw.bytes=std::move(bytes);raw.final_bits=raw.bytes.size()*8;return raw;
}
} // namespace

std::size_t compress_bound(std::size_t count,Width width) {
    unsigned w=width_of(width);need(count<=max_values_bytes/(w/8),"value limit");
    return header+(count*(w+20)+w+32+7)/8;
}
Encoded encode_raw(const std::uint8_t* v,std::size_t n,Width w) {
    width_of(w);return w==Width::binary32?raw_encode<float>(v,n,false):raw_encode<double>(v,n,false);
}
Decoded decode_raw(const std::uint8_t* v,std::size_t n,Width w) {
    width_of(w);return w==Width::binary32?raw_decode<float>(v,n):raw_decode<double>(v,n);
}
Encoded compress(const std::uint8_t* v,std::size_t n,Width w) {
    width_of(w);auto raw=w==Width::binary32?raw_encode<float>(v,n,true):raw_encode<double>(v,n,true);
    auto check=decode_raw(raw.bytes.data(),raw.bytes.size(),w);need(check.values.size()==n*(width_of(w)/8) && (!check.values.size() || std::memcmp(v,check.values.data(),check.values.size())==0),"original source recovery is not lossless");
    return frame(std::move(raw),n,w);
}
Decoded decompress(const std::uint8_t* p,std::size_t size) {
    need(p && size>=header && size<=max_stream_bytes,"invalid frame size");
    need(std::memcmp(p,"ELF1",4)==0 && p[5]==0 && p[6]==0 && p[7]==0 && load(p+28,4)==0,"invalid frame header");
    auto w=static_cast<Width>(p[4]);unsigned width=width_of(w);
    std::uint64_t count=load(p+8,8),n=load(p+16,8);
    need(count<=max_values_bytes/(width/8) && n==size-header,"invalid frame lengths");
    need(crc(p+header,std::size_t(n))==load(p+24,4),"payload checksum mismatch");
    auto result=decode_raw(p+header,std::size_t(n),w);need(result.count==count,"decoded count mismatch");
    Reader r{p+header,n*8,result.consumed_bits};
    need(r.limit-r.bits>=1 && r.limit-r.bits<=8,"invalid close padding");
    need(r.get(unsigned(r.limit-r.bits))==0,"nonzero close padding");return result;
}
bool compress_into(const std::uint8_t* v,std::size_t n,Width w,std::uint8_t* out,std::size_t capacity,std::size_t& written) {
    written=0;auto result=compress(v,n,w);if(capacity<result.bytes.size())return false;
    need(out,"null output");std::memcpy(out,result.bytes.data(),result.bytes.size());written=result.bytes.size();return true;
}
bool decompress_into(const std::uint8_t* v,std::size_t n,std::uint8_t* out,std::size_t capacity,std::size_t& written) {
    written=0;auto result=decompress(v,n);if(capacity<result.values.size())return false;
    if(!result.values.empty()) {
        if(!out)throw std::invalid_argument("null output");
        std::memcpy(out,result.values.data(),result.values.size());
    }
    written=result.values.size();return true;
}
struct Encoder::Impl {Width width;Bytes original;bool finalized=false;State<float> narrow;State<double> wide;explicit Impl(Width w):width(w){width_of(w);} };
Encoder::Encoder(Width w):impl_(new Impl(w)){}
Encoder::~Encoder()=default;Encoder::Encoder(Encoder&&) noexcept=default;Encoder& Encoder::operator=(Encoder&&) noexcept=default;
void Encoder::append(const std::uint8_t* v,std::size_t n) {
    need(impl_ && !impl_->finalized,"encoder already finalized or moved");need(v || !n,"null input");
    unsigned w=width_of(impl_->width);std::size_t existing=w==32?impl_->narrow.count:impl_->wide.count;
    need(n<=max_values_bytes/(w/8)-existing,"value limit");
    auto next=*impl_;
    for(std::size_t i=0;i<n;++i)if(w==32)next.narrow.add(std::uint32_t(load(v+i*4,4)),true);else next.wide.add(load(v+i*8,8),true);
    if(n)next.original.insert(next.original.end(),v,v+n*(w/8));
    *impl_=std::move(next);
}
Encoded Encoder::finalize() {
    need(impl_ && !impl_->finalized,"encoder already finalized or moved");auto next=*impl_;
    auto count=next.width==Width::binary32?next.narrow.count:next.wide.count;
    auto raw=next.width==Width::binary32?next.narrow.finish():next.wide.finish();
    auto decoded=decode_raw(raw.bytes.data(),raw.bytes.size(),next.width);need(decoded.values==next.original,"original source recovery is not lossless");
    auto result=frame(std::move(raw),count,next.width);impl_->finalized=true;return result;
}
void Encoder::reset() {need(bool(impl_),"moved encoder");impl_.reset(new Impl(impl_->width));}
} // namespace elf_vldb
