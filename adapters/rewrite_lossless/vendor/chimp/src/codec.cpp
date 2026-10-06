// Translated from panagiotisl/chimp (Panagiotis Liakos), Apache-2.0.
// Safety checks, explicit unsigned arithmetic and CMP1 framing added in 2026.
#include "chimp.hpp"
#include <array>
#include <algorithm>
#include <cstring>
#include <limits>
#include <stdexcept>

namespace chimp {
namespace {
constexpr unsigned buckets[]={0,8,12,16,18,20,22,24};
void check(Width w,Variant v) {
    if((w!=Width::binary32&&w!=Width::binary64)||(v!=Variant::chimp&&v!=Variant::chimp128))
        throw std::invalid_argument("invalid width or algorithm");
}
unsigned width(Width w){return static_cast<unsigned>(w);}
std::uint64_t end(Width w){return w==Width::binary32?0x7fc00000ULL:0x7ff8000000000000ULL;}
std::uint64_t load(const std::uint8_t* p,unsigned bytes){
    std::uint64_t x=0;for(unsigned i=0;i<bytes;i++)x|=std::uint64_t(p[i])<<(8*i);return x;
}
void store(Bytes& b,std::uint64_t x,unsigned bytes){for(unsigned i=0;i<bytes;i++)b.push_back(std::uint8_t(x>>(8*i)));}
void put(Bytes& b,std::size_t pos,std::uint64_t x,unsigned bytes){for(unsigned i=0;i<bytes;i++)b[pos+i]=std::uint8_t(x>>(8*i));}
unsigned bucket(std::uint64_t x,unsigned w){
    unsigned z=static_cast<unsigned>(__builtin_clzll(x))-(64-w),i=0;
    while(i<7&&buckets[i+1]<=z)++i;
    return i;
}
unsigned tail(std::uint64_t x,unsigned w){return x?static_cast<unsigned>(__builtin_ctzll(x)):w;}
struct Writer {
    Bytes b;std::uint64_t bits=0;
    void write(std::uint64_t x,unsigned n){
        if(n>64)throw std::logic_error("invalid bit count");
        for(unsigned i=n;i>0;--i){if(bits%8==0)b.push_back(0);b.back()|=std::uint8_t(((x>>(i-1))&1)<<(7-bits%8));++bits;}
    }
};
struct Reader {
    const Bytes& b;std::uint64_t pos=0;
    std::uint64_t read(unsigned n){
        if(n>64||n>std::uint64_t(b.size())*8-pos)throw std::invalid_argument("truncated bitstream");
        std::uint64_t x=0;for(unsigned i=0;i<n;i++){x=(x<<1)|((b[std::size_t(pos/8)]>>(7-pos%8))&1);++pos;}return x;
    }
};
std::uint64_t checksum(const std::uint8_t* p,std::size_t size){
    std::uint64_t h=14695981039346656037ULL;
    for(std::size_t i=0;i<size;i++){if(i>=32&&i<40)continue;h=(h^p[i])*1099511628211ULL;}return h;
}
}
struct Encoder::Impl {
    Width w;Variant v;Writer out;
    std::array<std::uint64_t,128> history{};
    std::vector<std::uint64_t> indices;
    std::uint64_t count=0,index=0;
    unsigned current=0,leading=65;
    bool finished=false;
    Impl(Width a,Variant b):w(a),v(b),indices(b==Variant::chimp128?(a==Width::binary32?8192:16384):0){check(a,b);}
    void value(std::uint64_t x){
        const unsigned n=width(w),log=v==Variant::chimp128?7:0;
        const unsigned threshold=(n==32?5:6)+log;
        const unsigned key=v==Variant::chimp128?static_cast<unsigned>(x&(indices.size()-1)):0;
        if(count==0){out.write(x,n);history[0]=x;if(log)indices[key]=0;++count;return;}
        unsigned prev=current;std::uint64_t xorv=history[prev]^x;
        unsigned trailing=tail(xorv,n);
        if(log){
            trailing=0;const auto candidate=indices[key];
            if(index-candidate<128){
                const auto temp=x^history[std::size_t(candidate%128)];trailing=tail(temp,n);
                if(trailing>threshold){prev=static_cast<unsigned>(candidate%128);xorv=temp;}
                else if(n==32)trailing=tail(xorv,n);
            } else if(n==32)trailing=tail(xorv,n);
        }
        if(xorv==0){out.write(0,2);if(log)out.write(prev,log);leading=n+1;}
        else {
            const unsigned code=bucket(xorv,n),rounded=buckets[code];
            if(trailing>threshold){
                out.write(1,2);if(log)out.write(prev,log);
                out.write(code,3);const unsigned sig=n-rounded-trailing;
                out.write(sig,n==32?5:6);out.write(xorv>>trailing,sig);leading=n+1;
            }else if(rounded==leading){out.write(2,2);out.write(xorv,n-rounded);}
            else{leading=rounded;out.write(3,2);out.write(code,3);out.write(xorv,n-rounded);}
        }
        if(log){current=(current+1)%128;++index;indices[key]=index;}
        history[current]=x;++count;
    }
};
Encoder::Encoder(Width w,Variant v):impl_(new Impl(w,v)){}
Encoder::~Encoder()=default;
Encoder::Encoder(Encoder&&) noexcept=default;
Encoder& Encoder::operator=(Encoder&&) noexcept=default;
void Encoder::reset(){impl_.reset(new Impl(impl_->w,impl_->v));}
void Encoder::append(const std::uint8_t* p,std::size_t n){
    auto& s=*impl_;if(s.finished)throw std::logic_error("append after finalize");
    if((!p&&n)||n>max_count-s.count)throw std::invalid_argument("invalid input count");
    const unsigned bytes=width(s.w)/8;
    for(std::size_t i=0;i<n;i++)if(load(p+i*bytes,bytes)==end(s.w))throw std::invalid_argument("canonical NaN is END");
    for(std::size_t i=0;i<n;i++)s.value(load(p+i*bytes,bytes));
}
Encoded Encoder::finalize(){
    auto& s=*impl_;if(s.finished)throw std::logic_error("repeated finalize");
    s.value(end(s.w));s.out.write(0,1);s.finished=true;
    return {s.out.b,std::uint64_t(s.out.b.size())*8,s.out.bits};
}
struct Decoder::Impl {
    Width w;Variant v;Bytes b;Reader in;
    std::array<std::uint64_t,128> history{};
    std::uint64_t last=0,count=0;
    unsigned current=0,leading=65;bool ended=false;
    Impl(const std::uint8_t* p,std::size_t n,Width a,Variant c):w(a),v(c),b(),in{b}{
        check(a,c);if(!p&&n)throw std::invalid_argument("null bitstream");
        if(n>compress_bound(max_count,a,c))throw std::invalid_argument("bitstream exceeds limit");
        if(n)b.assign(p,p+n);
    }
    bool next(std::uint64_t& x){
        if(ended)return false;
        const unsigned n=width(w);const bool h=v==Variant::chimp128;
        if(count==0){last=in.read(n);history[0]=last;}
        else{
            unsigned flag=static_cast<unsigned>(in.read(2));
            if(flag==0){if(h)last=history[std::size_t(in.read(7))];}
            else if(flag==1){
                std::uint64_t base=last;if(h)base=history[std::size_t(in.read(7))];
                leading=buckets[in.read(3)];unsigned sig=static_cast<unsigned>(in.read(n==32?5:6));if(!sig)sig=n;
                if(sig>n-leading)throw std::invalid_argument("invalid XOR window");
                const unsigned trailing=n-leading-sig;last=base^(in.read(sig)<<trailing);
            }else{
                if(flag==3)leading=buckets[in.read(3)];
                if(leading>=n)throw std::invalid_argument("uninitialized XOR window");
                last^=in.read(n-leading);
            }
        }
        if(last==end(w)){if(in.read(1)!=0)throw std::invalid_argument("invalid finish bit");ended=true;return false;}
        if(count==max_count)throw std::invalid_argument("decoded count exceeds limit");
        if(count&&h){current=(current+1)%128;history[current]=last;}
        ++count;x=last;return true;
    }
};
Decoder::Decoder(const std::uint8_t* p,std::size_t n,Width w,Variant v):impl_(new Impl(p,n,w,v)){}
Decoder::~Decoder()=default;
Decoder::Decoder(Decoder&&) noexcept=default;
Decoder& Decoder::operator=(Decoder&&) noexcept=default;
bool Decoder::next(std::uint64_t& x){return impl_->next(x);}
void Decoder::reset(){auto& s=*impl_;s.in.pos=0;s.history.fill(0);s.last=s.count=0;s.current=0;s.leading=65;s.ended=false;}
std::uint64_t Decoder::consumed_bits()const{return impl_->in.pos;}
std::size_t compress_bound(std::size_t count,Width w,Variant v){
    check(w,v);if(count>max_count)throw std::invalid_argument("count limit");
    return 40+(count+1)*(width(w)/8+3)+1;
}
Encoded encode_raw(const std::uint8_t* p,std::size_t n,Width w,Variant v){Encoder e(w,v);e.append(p,n);return e.finalize();}
Decoded decode_raw(const std::uint8_t* p,std::size_t n,Width w,Variant v){
    Decoder d(p,n,w,v);Decoded out;out.width=w;out.variant=v;std::uint64_t x;
    while(d.next(x)){store(out.values,x,width(w)/8);++out.count;}
    out.consumed_bits=d.consumed_bits();return out;
}
Encoded compress(const std::uint8_t* p,std::size_t n,Width w,Variant v){
    auto raw=encode_raw(p,n,w,v);Bytes frame={'C','M','P','1',1,std::uint8_t(width(w))};
    store(frame,static_cast<unsigned>(v),2);store(frame,n,8);store(frame,raw.meaningful_bits,8);store(frame,raw.bytes.size(),8);store(frame,0,8);
    frame.insert(frame.end(),raw.bytes.begin(),raw.bytes.end());put(frame,32,checksum(frame.data(),frame.size()),8);
    return {frame,std::uint64_t(frame.size())*8,raw.meaningful_bits};
}
Decoded decompress(const std::uint8_t* p,std::size_t n){
    if(!p||n<40||std::memcmp(p,"CMP1",4)||p[4]!=1)throw std::invalid_argument("invalid CMP1 header");
    const auto w=static_cast<Width>(p[5]);const auto v=static_cast<Variant>(load(p+6,2));check(w,v);
    const auto count=load(p+8,8),bits=load(p+16,8),size=load(p+24,8);
    if(count>max_count||size!=n-40||size>compress_bound(count,w,v)||bits>size*8||bits+7< size*8||load(p+32,8)!=checksum(p,n))
        throw std::invalid_argument("invalid CMP1 size or checksum");
    if(bits%8&&(p[n-1]&((1u<<(8-bits%8))-1)))throw std::invalid_argument("nonzero padding");
    auto result=decode_raw(p+40,n-40,w,v);
    if(result.count!=count||result.consumed_bits!=bits)throw std::invalid_argument("CMP1 count or END mismatch");
    return result;
}
bool compress_into(const std::uint8_t* p,std::size_t n,Width w,Variant v,std::uint8_t* out,std::size_t cap,std::size_t& used){
    auto result=compress(p,n,w,v);used=result.bytes.size();if(used>cap)return false;
    if(!out&&used)throw std::invalid_argument("null output");
    std::memcpy(out,result.bytes.data(),used);return true;
}
bool decompress_into(const std::uint8_t* p,std::size_t n,std::uint8_t* out,std::size_t cap,std::size_t& used){
    auto result=decompress(p,n);used=result.values.size();if(used>cap)return false;
    if(!out&&used)throw std::invalid_argument("null output");
    if(used)std::memcpy(out,result.values.data(),used);
    return true;
}
}
