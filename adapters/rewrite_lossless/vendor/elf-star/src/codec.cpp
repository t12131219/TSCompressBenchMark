// Exact Huffman ElfStar block translation. See contract.md for provenance.
#include "elf_star.hpp"
#include <algorithm>
#include <array>
#include <charconv>
#include <cfenv>
#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>
#include <variant>

namespace elf_star {
namespace {
constexpr std::size_t max_stream_bytes=64u*1024u*1024u;
static_assert(sizeof(float)==4 && sizeof(double)==8 && std::numeric_limits<float>::is_iec559 && std::numeric_limits<double>::is_iec559,"IEEE754 required");
void need(bool ok,const char* text) {if(!ok)throw std::invalid_argument(text);}
unsigned width_of(Width w) {
    need(w==Width::binary32 || w==Width::binary64,"invalid width");
    need(std::fegetround()==FE_TONEAREST,"round-to-nearest required");return unsigned(w);
}
std::uint64_t load(const std::uint8_t* p,unsigned n) {
    std::uint64_t v=0;for(unsigned i=0;i<n;++i)v|=std::uint64_t(p[i])<<(8*i);return v;
}
void store(Bytes& b,std::uint64_t v,unsigned n) {for(unsigned i=0;i<n;++i)b.push_back(std::uint8_t(v>>(8*i)));}
std::uint32_t crc(const std::uint8_t* p,std::size_t n) {
    std::uint32_t c=~0u;for(std::size_t i=0;i<n;++i) {c^=p[i];for(unsigned j=0;j<8;++j)c=(c>>1)^(0xedb88320u&(0u-(c&1)));}return ~c;
}
struct Writer {
    Bytes bytes;std::uint64_t bits=0;
    void put(std::uint64_t v,unsigned n) {
        need(n<=64,"invalid bit width");
        for(unsigned i=n;i>0;--i) {
            if(bits%8==0) {need(bytes.size()<max_stream_bytes,"stream limit");bytes.push_back(0);}
            bytes.back()|=std::uint8_t(((v>>(i-1))&1)<<(7-bits%8));++bits;
        }
    }
};
struct Reader {
    const std::uint8_t* bytes;std::uint64_t limit,bits=0;
    std::uint64_t get(unsigned n) {
        need(n<=64 && bits<=limit && n<=limit-bits,"truncated bitstream");std::uint64_t v=0;
        for(unsigned i=0;i<n;++i) {v=(v<<1)|((bytes[bits/8]>>(7-bits%8))&1);++bits;}return v;
    }
    void padding() {need(limit-bits<8,"trailing payload");while(bits<limit)need(get(1)==0,"nonzero padding");}
};
template<class T> struct Traits;
template<> struct Traits<float> {
    using U=std::uint32_t;using I=std::int32_t;
    static constexpr unsigned width=32,fraction=23,bias=127,exponent_mask=255,symbols=9,significant=8;
    static constexpr U end=0x7fc00000;
};
template<> struct Traits<double> {
    using U=std::uint64_t;using I=std::int64_t;
    static constexpr unsigned width=64,fraction=52,bias=1023,exponent_mask=2047,symbols=17,significant=17;
    static constexpr U end=0x7ff8000000000000ULL;
};
template<class T> T power(int i) {
    std::string text="1e"+std::to_string(i);T v=0;
    auto result=std::from_chars(text.data(),text.data()+text.size(),v);
    if(result.ec==std::errc::result_out_of_range)return i>0?std::numeric_limits<T>::infinity():T(0);
    need(result.ec==std::errc() && result.ptr==text.data()+text.size(),"decimal parse error");return v;
}
template<class T> T positive_power(int i) {
    need(i>=(sizeof(T)==4?1:0),"source rejects decimal scale");return power<T>(i);
}
template<class T> typename Traits<T>::I java_integer(T v) {
    using I=typename Traits<T>::I;if(std::isnan(v))return 0;
    T edge=std::ldexp(T(1),Traits<T>::width-1);
    if(v>=edge)return std::numeric_limits<I>::max();
    if(v<=-edge)return std::numeric_limits<I>::min();
    return static_cast<I>(v);
}
template<class T> T number(typename Traits<T>::U u) {T v;std::memcpy(&v,&u,sizeof(v));return v;}
template<class T> typename Traits<T>::U pattern(T v) {typename Traits<T>::U u;std::memcpy(&u,&v,sizeof(v));return u;}
template<class T> int decimal_sp(T v,bool& reciprocal) {
    reciprocal=false;
    if(v>=1) {for(int i=0;i<9;++i)if(v<static_cast<T>(power<double>(i+1)))return i;}
    else {for(int i=1;i<=10;++i) {T p=power<T>(-i);if(v>=p) {reciprocal=v==p;return -i;}}}
    double log=std::log10(static_cast<double>(v));need(std::isfinite(log) && log>-1000 && log<1000,"invalid decimal magnitude");
    reciprocal=log==std::trunc(log);return int(std::floor(log));
}
template<class T> std::pair<int,int> alpha_beta(T v,int last) {
    v=std::abs(v);bool reciprocal;int sp=decimal_sp(v,reciprocal),i;
    if(last!=std::numeric_limits<int>::max() && last!=0)i=std::max(last-sp-1,1);
    else if(sizeof(T)==8 && last==std::numeric_limits<int>::max())i=17-sp;
    else i=sp>=0?1:-sp;
    T temp=0;typename Traits<T>::I integer=0;
    for(;;) {
        need(i<=400,"source significance loop does not terminate");temp=T(v*positive_power<T>(i));integer=java_integer(temp);
        need(std::isfinite(temp),"source significance loop does not terminate");if(static_cast<T>(integer)==temp)break;++i;
    }
    int beta;
    if(T(temp/positive_power<T>(i))!=v)beta=Traits<T>::significant;
    else {while(i>0 && integer%10==0) {--i;integer/=10;}beta=sp+i+1;}
    return {beta-sp-1,reciprocal?0:beta};
}
int f_alpha(int a) {
    static constexpr int f[]={0,4,7,10,14,17,20,24,27,30,34,37,40,44,47,50,54,57,60,64,67};
    need(a>=0 && a<=400,"invalid erasure scale");return a<21?f[a]:int(std::ceil(a*(std::log(10.)/std::log(2.))));
}
template<class T> typename Traits<T>::U recover(typename Traits<T>::U u,int beta) {
    T v=number<T>(u);need(v!=0 && std::isfinite(v),"invalid erased value");bool ignored;int sp=decimal_sp(std::abs(v),ignored);
    if(beta==0) {need(-sp-1>=(sizeof(T)==4?1:0),"invalid reciprocal scale");T p=power<T>(sp+1);v=v<0?-p:p;}
    else {
        int alpha=beta-sp-1;need(alpha<=400,"invalid recovery scale");T scale=positive_power<T>(alpha),product=T(v*scale);
        double rounded=v<0?std::floor(static_cast<double>(product)):std::ceil(static_cast<double>(product));v=T(rounded/static_cast<double>(scale));
    }
    need(std::isfinite(v),"invalid recovered value");return pattern(v);
}
template<class U> unsigned trailing(U v) {unsigned n=0;if(!v)return sizeof(U)*8;while(!(v&1)) {++n;v>>=1;}return n;}
template<class U> unsigned leading(U v) {unsigned n=0;U mask=U(1)<<(sizeof(U)*8-1);while(mask && !(v&mask)) {++n;mask>>=1;}return n;}
unsigned index_bits(std::size_t n) {unsigned bits=0;while((std::size_t(1)<<bits)<n)++bits;return bits;}
struct Code {unsigned value=0,bits=0;};
// Java PriorityQueue: equal nodes never sift upward; sift-down prefers the
// left child on equality. Stable heaps and std::priority_queue differ here.
std::vector<Code> huffman(const std::vector<int>& frequencies) {
    struct Node {int symbol,freq,height,left=-1,right=-1;};std::vector<Node> nodes;std::vector<int> heap;
    auto cmp=[&](int a,int b) {return nodes[a].freq!=nodes[b].freq?nodes[a].freq-nodes[b].freq:nodes[a].height-nodes[b].height;};
    auto add=[&](int x) {heap.push_back(x);std::size_t k=heap.size()-1;while(k>0) {auto p=(k-1)/2;if(cmp(x,heap[p])>=0)break;heap[k]=heap[p];k=p;}heap[k]=x;};
    auto poll=[&]() {int result=heap.front(),x=heap.back();heap.pop_back();std::size_t k=0,half=heap.size()/2;
        if(!heap.empty()) {while(k<half) {std::size_t child=k*2+1;if(child+1<heap.size() && cmp(heap[child],heap[child+1])>0)++child;
            if(cmp(x,heap[child])<=0)break;
            heap[k]=heap[child];k=child;}heap[k]=x;}return result;};
    for(std::size_t i=0;i<frequencies.size();++i) {nodes.push_back({int(i),frequencies[i],0});add(int(nodes.size()-1));}
    while(heap.size()>1) {int l=poll(),r=poll();nodes.push_back({-1,nodes[l].freq+nodes[r].freq,1+std::max(nodes[l].height,nodes[r].height),l,r});add(int(nodes.size()-1));}
    std::vector<Code> codes(frequencies.size());
    auto visit=[&](auto&& self,int n,unsigned value,unsigned bits)->void {
        if(nodes[n].symbol>=0)codes[std::size_t(nodes[n].symbol)]={value,bits};
        else {self(self,nodes[n].left,value<<1,bits+1);self(self,nodes[n].right,(value<<1)|1,bits+1);}
    };visit(visit,heap.front(),0,0);return codes;
}
// Literal DP loop, pruning and strict tie decisions from PostOfficeSolver.
std::vector<unsigned> positions(const std::vector<int>& a) {
    int n=int(a.size()),nonzero=n,total=a[0];std::vector<int> pre_count(n),post_count(n);pre_count[0]=1;
    for(int i=1;i<n;++i) {total+=a[i];if(!a[i])--nonzero;pre_count[i]=pre_count[i-1]+(a[i]!=0);}
    for(int i=0;i<n;++i)post_count[i]=nonzero-pre_count[i];
    int best_cost=std::numeric_limits<int>::max();std::vector<unsigned> best;
    unsigned max_z=std::min(index_bits(std::size_t(nonzero)),n==32?4u:5u);
    for(unsigned z=0;z<=max_z;++z) {
        int present=total*int(z);if(present>=best_cost)break;int original=1<<z,num=std::min(original,nonzero);
        std::vector<std::vector<int>> dp(n,std::vector<int>(num)),pre(n,std::vector<int>(num));pre[0][0]=-1;
        for(int i=1;i<n;++i) {if(!a[i])continue;
            for(int j=std::max(1,num+i-n);j<=i && j<num;++j) {
                if(i>1 && j==1) {for(int k=1;k<i;++k)dp[i][j]+=a[k]*k;pre[i][j]=0;}
                else {
                    if(pre_count[i]<j+1 || post_count[i]<num-1-j)continue;
                    int cost=std::numeric_limits<int>::max(),prev=0;
                    for(int k=j-1;k<=i-1;++k) {
                        if((!a[k] && k>0) || pre_count[k]<j || post_count[k]<num-j)continue;
                        int sum=dp[k][j-1];for(int p=k+1;p<=i-1;++p)sum+=a[p]*(p-k);
                        if(cost>sum) {cost=sum;prev=k;if(!sum)break;}
                    }
                    if(cost!=std::numeric_limits<int>::max()) {dp[i][j]=cost;pre[i][j]=prev;}
                }
            }
        }
        int cost=std::numeric_limits<int>::max(),last=-1;
        for(int i=num-1;i<n;++i) {
            if(num==1 && i>0)break;
            if((!a[i] && i>0) || pre_count[i]<num)continue;
            int sum=dp[i][num-1];for(int j=i+1;j<n;++j)sum+=a[j]*(j-i);
            if(cost>sum) {cost=sum;last=i;}
        }
        std::vector<unsigned> p(std::size_t(num),0);int i=1;
        while(last!=-1) {need(i<=num,"invalid post office path");p[std::size_t(num-i)]=unsigned(last);last=pre[last][num-i];++i;}
        if(original>nonzero) {
            std::vector<unsigned> padded(std::size_t(original),0);int j=0,k=0;
            while(j<original && k<num) {if(j-k<original-num && unsigned(j)<p[k]) {padded[j]=unsigned(j);++j;}else {padded[j]=p[k];++j;++k;}}p=std::move(padded);
        }
        if(cost+present<best_cost) {best_cost=cost+present;best=std::move(p);}
    }
    return best;
}

template<class T> std::size_t count_limit(){return sizeof(T)==4?1000:16384;}
template<class T> struct State {
    using A=Traits<T>;using U=typename A::U;
    std::vector<U> values;std::vector<unsigned> symbols;
    std::vector<int> frequencies=std::vector<int>(A::symbols);
    std::vector<unsigned> leads,tails;std::vector<Code> codes;
    Writer writer;int beta=std::numeric_limits<int>::max();
    U previous=0;unsigned saved_l=A::width,saved_t=A::width;bool first=true;
    void add(U u,bool strict){
        need(values.size()<count_limit<T>(),"upstream block/window limit");T v=number<T>(u);unsigned s=A::symbols-1;
        if(std::isnan(v)){need(!strict,"NaN is END, outside lossless domain");u=A::end;}
        else if(v!=0&&!std::isinf(v)){
            auto ab=alpha_beta(v,beta);int e=int((u>>A::fraction)&A::exponent_mask),erase=int(A::fraction)-(f_alpha(ab.first)+e-int(A::bias));
            U mask=U(~U(0))<<(unsigned(erase)&(A::width-1));
            if((U(~mask)&u)&&erase>(A::width==64?4:3)){
                need(ab.second>=0&&ab.second<int(A::symbols)-1,"source beta symbol outside table");s=unsigned(ab.second);beta=ab.second;
                if(strict)need(recover<T>(u&mask,beta)==u,"source decimal recovery is not lossless");
                u&=mask;
            }
        }
        ++frequencies[s];values.push_back(u);symbols.push_back(s);
    }
    void table(const std::vector<unsigned>& p){writer.put(p.size(),A::width==32?4:5);for(auto x:p)writer.put(x,A::width==32?5:6);}
    void xor_value(U v){
        if(first){first=false;table(leads);table(tails);unsigned t=trailing(v);writer.put(t,A::width==32?6:7);if(t<A::width)writer.put(t==A::width-1?0:v>>(t+1),A::width-1-t);previous=v;return;}
        U x=previous^v;if(!x){writer.put(1,2);return;}
        const auto li=std::size_t(std::upper_bound(leads.begin(),leads.end(),leading(x))-leads.begin()-1),ti=std::size_t(std::upper_bound(tails.begin(),tails.end(),trailing(x))-tails.begin()-1);
        unsigned l=leads[li],t=tails[ti],lb=index_bits(leads.size()),tb=index_bits(tails.size());
        if(l>=saved_l&&t>=saved_t&&l-saved_l+t-saved_t<1+lb+tb){writer.put(1,1);writer.put(x>>saved_t,A::width-saved_l-saved_t);}
        else{saved_l=l;saved_t=t;writer.put(0,2);writer.put(li,lb);writer.put(ti,tb);writer.put(x>>t,A::width-l-t);}previous=v;
    }
    Encoded finish(){
        std::vector<int> ld(A::width),td(A::width);
        for(std::size_t i=1;i<values.size();i++){U x=values[i]^values[i-1];if(x){++ld[leading(x)];++td[trailing(x)];}}
        leads=positions(ld);tails=positions(td);codes=huffman(frequencies);
        unsigned maxlen=0;for(auto c:codes)maxlen=std::max(maxlen,c.bits);unsigned length_bits=index_bits(maxlen);writer.put(length_bits,3);
        for(auto c:codes){writer.put(c.bits-1,length_bits);writer.put(c.value,c.bits);}
        for(std::size_t i=0;i<values.size();i++){auto c=codes[symbols[i]];writer.put(c.value,c.bits);xor_value(values[i]);}
        auto c=codes[A::symbols-1];writer.put(c.value,c.bits);xor_value(A::end);
        return {writer.bytes,std::uint64_t(writer.bytes.size())*8,std::uint64_t(writer.bytes.size())*8,writer.bits};
    }
    std::vector<unsigned> read_table(Reader& r){
        unsigned max=A::width/2,n=unsigned(r.get(A::width==32?4:5));if(!n)n=max;need(n<=max,"invalid position count");std::vector<unsigned> p;
        for(unsigned i=0;i<n;i++){unsigned v=unsigned(r.get(A::width==32?5:6));need(i==0?v==0:v>p.back(),"invalid position order");p.push_back(v);}return p;
    }
    void read_codes(Reader& r){
        unsigned length_bits=unsigned(r.get(3));need(length_bits<=4,"invalid Huffman length width");
        for(unsigned i=0;i<A::symbols;i++){unsigned len=unsigned(r.get(length_bits))+1;need(len<A::symbols,"invalid Huffman length");unsigned value=unsigned(r.get(len));codes.push_back({value,len});}
        for(std::size_t i=0;i<codes.size();i++)for(std::size_t j=0;j<codes.size();j++)if(i!=j&&codes[i].bits<=codes[j].bits)need((codes[j].value>>(codes[j].bits-codes[i].bits))!=codes[i].value,"conflicting Huffman prefix");
        unsigned total=0;for(auto c:codes)total+=1u<<(A::symbols-1-c.bits);need(total==(1u<<(A::symbols-1)),"incomplete Huffman code table");
    }
    unsigned read_symbol(Reader& r){unsigned value=0;for(unsigned len=1;len<A::symbols;len++){value=(value<<1)|unsigned(r.get(1));for(unsigned s=0;s<A::symbols;s++)if(codes[s].bits==len&&codes[s].value==value)return s;}throw std::invalid_argument("invalid Huffman code");}
    U read_xor(Reader& r){
        U v;
        if(first){leads=read_table(r);tails=read_table(r);first=false;unsigned t=unsigned(r.get(A::width==32?6:7));need(t<=A::width,"invalid first trailing count");v=t==A::width?0:U((U(r.get(A::width-1-t))<<1)|1)<<t;}
        else if(r.get(1)){need(saved_l+saved_t<A::width,"missing XOR window");v=previous^(U(r.get(A::width-saved_l-saved_t))<<saved_t);}
        else if(!r.get(1)){auto l=std::size_t(r.get(index_bits(leads.size()))),t=std::size_t(r.get(index_bits(tails.size())));need(l<leads.size()&&t<tails.size(),"invalid position index");saved_l=leads[l];saved_t=tails[t];need(saved_l+saved_t<A::width,"invalid XOR geometry");v=previous^(U(r.get(A::width-saved_l-saved_t))<<saved_t);}
        else v=previous;
        previous=v;return v;
    }
};
template<class T> Encoded raw_encode(const std::uint8_t* p,std::size_t n,bool strict){need((p||!n)&&n<=count_limit<T>(),"invalid input count");State<T> s;for(std::size_t i=0;i<n;i++)s.add(typename Traits<T>::U(load(p+i*sizeof(T),sizeof(T))),strict);return s.finish();}
template<class T> Decoded raw_decode(const std::uint8_t* p,std::size_t n){
    need(p&&n&&n<=max_stream_bytes,"invalid raw input");State<T> s;Reader r{p,std::uint64_t(n)*8};s.read_codes(r);Decoded out{{},sizeof(T)==4?Width::binary32:Width::binary64,0,0};
    for(;;){auto symbol=s.read_symbol(r);auto u=s.read_xor(r);if(u==Traits<T>::end){need(symbol==Traits<T>::symbols-1,"erased END");break;}
        need(out.count<count_limit<T>(),"decoded block limit");if(symbol!=Traits<T>::symbols-1)u=recover<T>(u,int(symbol));store(out.values,u,sizeof(T));++out.count;}
    out.consumed_bits=r.bits;return out;
}
Encoded frame(Encoded raw,std::size_t count,Width w){Bytes out{'E','S','F','1',std::uint8_t(width_of(w)),0,0,0};store(out,count,8);store(out,raw.bytes.size(),8);store(out,crc(raw.bytes.data(),raw.bytes.size()),4);store(out,0,4);out.insert(out.end(),raw.bytes.begin(),raw.bytes.end());raw.bytes=std::move(out);raw.final_bits=raw.bytes.size()*8;return raw;}
}
std::size_t compress_bound(std::size_t n,Width w){unsigned width=width_of(w);need(n<=(width==32?1000:16384),"upstream block/window limit");return 1024+n*(width/8+4);}
Encoded encode_raw(const std::uint8_t* p,std::size_t n,Width w){width_of(w);return w==Width::binary32?raw_encode<float>(p,n,false):raw_encode<double>(p,n,false);}
Decoded decode_raw(const std::uint8_t* p,std::size_t n,Width w){width_of(w);return w==Width::binary32?raw_decode<float>(p,n):raw_decode<double>(p,n);}
Encoded compress(const std::uint8_t* p,std::size_t n,Width w){width_of(w);return frame(w==Width::binary32?raw_encode<float>(p,n,true):raw_encode<double>(p,n,true),n,w);}
Decoded decompress(const std::uint8_t* p,std::size_t n){
    need(p&&n>=32&&n<=max_stream_bytes,"invalid frame size");need(std::memcmp(p,"ESF1",4)==0&&p[5]==0&&p[6]==0&&p[7]==0&&load(p+28,4)==0,"invalid frame header");Width w=static_cast<Width>(p[4]);unsigned width=width_of(w);auto count=load(p+8,8),len=load(p+16,8);
    need(count<=(width==32?1000:16384)&&len==n-32&&n<=compress_bound(count,w),"invalid frame geometry");need(crc(p+32,std::size_t(len))==load(p+24,4),"payload checksum");auto out=decode_raw(p+32,std::size_t(len),w);need(out.count==count,"decoded count mismatch");Reader r{p+32,len*8,out.consumed_bits};r.padding();return out;
}
bool compress_into(const std::uint8_t* p,std::size_t n,Width w,std::uint8_t* out,std::size_t cap,std::size_t& used){used=0;auto b=compress(p,n,w).bytes;if(b.size()>cap)return false;need(out,"null output");std::memcpy(out,b.data(),b.size());used=b.size();return true;}
bool decompress_into(const std::uint8_t* p,std::size_t n,std::uint8_t* out,std::size_t cap,std::size_t& used){used=0;auto b=decompress(p,n).values;if(b.size()>cap)return false;if(!b.empty()){need(out,"null output");std::memcpy(out,b.data(),b.size());}used=b.size();return true;}
struct Encoder::Impl {Width width;bool finalized=false;std::variant<State<float>,State<double>> state;explicit Impl(Width w):width(w),state(width_of(w)==32?decltype(state)(State<float>{}):decltype(state)(State<double>{})) {}};
Encoder::Encoder(Width w):impl_(new Impl(w)){}
Encoder::~Encoder()=default;Encoder::Encoder(Encoder&&) noexcept=default;Encoder& Encoder::operator=(Encoder&&) noexcept=default;
void Encoder::append(const std::uint8_t* p,std::size_t n){need(impl_&&!impl_->finalized,"append after finalize");need(p||!n,"null input");auto next=impl_->state;
    std::visit([&](auto& s){using S=std::decay_t<decltype(s)>;need(n<=(sizeof(typename S::U)==4?1000:16384)-s.values.size(),"input block limit");for(std::size_t i=0;i<n;i++)s.add(typename S::U(load(p+i*sizeof(typename S::U),sizeof(typename S::U))),true);},next);impl_->state=std::move(next);}
Encoded Encoder::finalize(){need(impl_&&!impl_->finalized,"repeated finalize");auto next=impl_->state;auto out=std::visit([&](auto& s){return frame(s.finish(),s.values.size(),impl_->width);},next);impl_->finalized=true;return out;}
void Encoder::reset(){need(bool(impl_),"moved encoder");impl_.reset(new Impl(impl_->width));}
struct Decoder::Impl {
    Bytes input; Width width; Reader reader;
    std::variant<State<float>,State<double>> state;
    std::size_t count=0;bool ended=false;
    Impl(const std::uint8_t* p,std::size_t n,Width w):width(w),reader{nullptr,0},
        state(width_of(w)==32?decltype(state)(State<float>{}):decltype(state)(State<double>{})) {
        need(p&&n&&n<=max_stream_bytes,"invalid raw input");input.assign(p,p+n);reset();
    }
    void reset(){
        state=width==Width::binary32?decltype(state)(State<float>{}):decltype(state)(State<double>{});
        reader=Reader{input.data(),std::uint64_t(input.size())*8};count=0;ended=false;
        std::visit([&](auto& s){s.read_codes(reader);},state);
    }
};
Decoder::Decoder(const std::uint8_t* p,std::size_t n,Width w):impl_(new Impl(p,n,w)){}
Decoder::~Decoder()=default;
Decoder::Decoder(Decoder&&) noexcept=default;
Decoder& Decoder::operator=(Decoder&&) noexcept=default;
void Decoder::reset(){need(bool(impl_),"moved decoder");impl_->reset();}
bool Decoder::next(Bytes& value){
    need(bool(impl_),"moved decoder");if(impl_->ended)return false;
    auto state=impl_->state;auto reader=impl_->reader;Bytes next;
    bool ordinary=std::visit([&](auto& s){
        using S=std::decay_t<decltype(s)>;using A=typename S::A;
        auto symbol=s.read_symbol(reader);auto u=s.read_xor(reader);
        if(u==A::end){need(symbol==A::symbols-1,"erased END");return false;}
        need(impl_->count<(A::width==32?1000u:16384u),"decoded block limit");
        if(symbol!=A::symbols-1){
            if constexpr(A::width==32)u=recover<float>(u,int(symbol));
            else u=recover<double>(u,int(symbol));
        }
        store(next,u,A::width/8);return true;
    },state);
    impl_->state=std::move(state);impl_->reader=reader;impl_->ended=!ordinary;
    if(ordinary){++impl_->count;value=std::move(next);}return ordinary;
}
} // namespace elf_star
