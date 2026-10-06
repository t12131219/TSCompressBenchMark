#include "self_star.hpp"
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

namespace self_star {
namespace {
constexpr std::size_t max_values_bytes=16u*1024u*1024u, max_stream_bytes=64u*1024u*1024u;
constexpr std::size_t max_blocks=1024, max_block_values=16384, header=32;
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
    static constexpr unsigned width=32,fraction=23,bias=127,exponent_mask=255,beta_bits=3,symbols=9,significant=8;
    static constexpr U end=0x7fc00000;
};
template<> struct Traits<double> {
    using U=std::uint64_t;using I=std::int64_t;
    static constexpr unsigned width=64,fraction=52,bias=1023,exponent_mask=2047,beta_bits=4,symbols=17,significant=17;
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
template<class T> struct State {
    using A=Traits<T>;using U=typename A::U;
    Writer writer;U previous=0;unsigned saved_l=A::width,saved_t=A::width;
    bool first_value=true,first_block=true,write_positions=false,lossless=true;
    int beta=std::numeric_limits<int>::max();std::size_t count=0;double previous_ratio=0;
    std::vector<unsigned> leads,tails;std::vector<int> lead_dist=std::vector<int>(A::width),tail_dist=std::vector<int>(A::width),freq=std::vector<int>(A::symbols);
    std::vector<Code> codes;int mode=0;
    explicit State(bool strict=true):lossless(strict) {
        leads=A::width==32?std::vector<unsigned>{0,8,12,16}:std::vector<unsigned>{0,8,12,16,18,20,22,24};
        tails=A::width==32?std::vector<unsigned>{0,16}:std::vector<unsigned>{0,22,28,32,36,40,42,46};
    }
    void refresh() {writer={};count=0;beta=std::numeric_limits<int>::max();first_value=true;mode=0;std::fill(lead_dist.begin(),lead_dist.end(),0);std::fill(tail_dist.begin(),tail_dist.end(),0);}
    void write_table(const std::vector<unsigned>& p) {writer.put(p.size(),A::width==32?4:5);for(auto v:p)writer.put(v,A::width==32?5:6);}
    void xor_value(U v) {
        if(first_value) {
            first_value=false;writer.put(write_positions,1);if(write_positions) {write_table(leads);write_table(tails);}
            unsigned t=trailing(v);writer.put(t,A::width==32?6:7);if(t<A::width)writer.put(t==A::width-1?0:v>>(t+1),A::width-1-t);previous=v;return;
        }
        U x=previous^v;if(!x) {writer.put(1,2);return;}
        unsigned actual_l=leading(x),actual_t=trailing(x);++lead_dist[actual_l];++tail_dist[actual_t];
        unsigned li=unsigned(std::upper_bound(leads.begin(),leads.end(),actual_l)-leads.begin()-1),ti=unsigned(std::upper_bound(tails.begin(),tails.end(),actual_t)-tails.begin()-1);
        unsigned l=leads[li],t=tails[ti],lb=index_bits(leads.size()),tb=index_bits(tails.size());
        if(l>=saved_l && t>=saved_t && l-saved_l+t-saved_t<1+lb+tb) {writer.put(1,1);writer.put(x>>saved_t,A::width-saved_l-saved_t);}
        else {saved_l=l;saved_t=t;writer.put(0,2);writer.put(li,lb);writer.put(ti,tb);writer.put(x>>t,A::width-l-t);}previous=v;
    }
    void symbol(unsigned s) {
        need(s<A::symbols,"source beta symbol outside table");
        if(!first_block)writer.put(codes[s].value,codes[s].bits);
        else if(s==A::symbols-1)writer.put(2,2);
        else if(int(s)==beta)writer.put(0,1);
        else {writer.put(3,2);writer.put(s,A::beta_bits);}
    }
    void add(U u) {
        need(count<max_block_values,"block value limit");T v=number<T>(u);unsigned s=A::symbols-1;
        if(std::isnan(v)) {
            need(!lossless,"NaN outside source lossless domain");u=first_block?u&(A::width==64?U(0xfff8000000000000ULL):U(0x7fc00000)):A::end;
        } else if(v!=0 && !std::isinf(v)) {
            auto ab=alpha_beta(v,beta);int e=int((u>>A::fraction)&A::exponent_mask),erase=int(A::fraction)-(f_alpha(ab.first)+e-int(A::bias));
            U mask=U(~U(0))<<(unsigned(erase)&(A::width-1));
            if((U(~mask)&u) && erase>(A::width==64?4:3)) {
                need(ab.second>=0 && ab.second<int(A::symbols)-1,"source beta symbol outside table");s=unsigned(ab.second);
                if(lossless)need(recover<T>(u&mask,ab.second)==u,"source decimal recovery is not lossless for value");
                u&=mask;
            }
        }
        symbol(s);if(s!=A::symbols-1)beta=int(s);++freq[s];xor_value(u);++count;
    }
    Encoded close() {
        double ratio=count?double(writer.bits)/(double(count)*A::width):std::numeric_limits<double>::quiet_NaN();bool update=previous_ratio<ratio;previous_ratio=ratio;
        symbol(A::symbols-1);codes=huffman(freq);std::fill(freq.begin(),freq.end(),0);first_block=false;xor_value(A::end);
        Encoded out{writer.bytes,std::uint64_t(writer.bytes.size())*8,writer.bits};
        if(update) {leads=positions(lead_dist);tails=positions(tail_dist);}write_positions=update;refresh();return out;
    }
    std::vector<unsigned> read_table(Reader& r) {
        unsigned max=A::width/2,n=unsigned(r.get(A::width==32?4:5));if(!n)n=max;need(n<=max,"invalid position count");
        std::vector<unsigned> p;for(unsigned i=0;i<n;++i) {unsigned v=unsigned(r.get(A::width==32?5:6));need((i==0?v==0:v>p.back()),"invalid position order");p.push_back(v);}return p;
    }
    U read_xor(Reader& r) {
        U v;
        if(first_value) {
            if(r.get(1)) {leads=read_table(r);tails=read_table(r);}first_value=false;
            unsigned t=unsigned(r.get(A::width==32?6:7));need(t<=A::width,"invalid first trailing count");v=t==A::width?0:U((U(r.get(A::width-1-t))<<1)|1)<<t;
        } else if(r.get(1)) {
            need(saved_l<A::width && saved_t<A::width && saved_l+saved_t<A::width,"missing XOR window");v=previous^(U(r.get(A::width-saved_l-saved_t))<<saved_t);
        } else if(!r.get(1)) {
            auto l=std::size_t(r.get(index_bits(leads.size()))),t=std::size_t(r.get(index_bits(tails.size())));need(l<leads.size() && t<tails.size(),"invalid position index");
            saved_l=leads[l];saved_t=tails[t];need(saved_l+saved_t<A::width,"invalid XOR window");v=previous^(U(r.get(A::width-saved_l-saved_t))<<saved_t);
        } else v=previous;
        previous=v;return v;
    }
    bool read_value(Reader& r,Bytes& output) {
        unsigned s=A::symbols-1;
        if(first_block) {if(!r.get(1)) {need(beta>=0 && beta<int(A::symbols)-1,"missing beta");s=unsigned(beta);}else if(r.get(1))s=unsigned(r.get(A::beta_bits));}
        else {
            unsigned code=0;bool found=false;
            for(unsigned bits=1;bits<A::symbols;++bits) {code=(code<<1)|unsigned(r.get(1));for(unsigned i=0;i<A::symbols;++i)if(codes[i].bits==bits && codes[i].value==code) {s=i;found=true;break;}if(found)break;}need(found,"invalid Huffman code");
        }
        U u=read_xor(r);
        if(u==A::end) {need(s==A::symbols-1,"erased terminator");return false;}
        need(count<max_block_values,"decoded block limit");++count;++freq[s];if(s!=A::symbols-1) {beta=int(s);u=recover<T>(u,beta);}store(output,u,sizeof(T));return true;
    }
    void finish_decode() {codes=huffman(freq);std::fill(freq.begin(),freq.end(),0);first_block=false;refresh();}
};
using States=std::variant<State<float>,State<double>>;
States make_state(Width w,bool lossless=true) {return width_of(w)==32?States(State<float>(lossless)):States(State<double>(lossless));}
void check_input(const std::uint8_t* p,std::size_t n,unsigned step) {need(n<=max_block_values && n<=max_values_bytes/step,"input limit");need(p || !n,"null input");}
std::size_t session_bytes(const Session& s) {
    auto step=width_of(s.width)/8;need(s.blocks.size()<=max_blocks,"session block limit");need(!s.network || step==8,"binary64 network only");std::size_t total=0;
    for(auto& b:s.blocks) {need(b.size()%step==0 && b.size()/step<=max_block_values,"invalid block input");need(!s.network || !b.empty(),"empty network block");need(b.size()<=max_values_bytes-total,"session value limit");total+=b.size();}return total;
}
} // namespace
struct Encoder::Impl {Width width;bool lossless;States state;Impl(Width w,bool s):width(w),lossless(s),state(make_state(w,s)) {}};
Encoder::Encoder(Width w,bool s):impl_(std::make_unique<Impl>(w,s)) {}
Encoder::~Encoder()=default;Encoder::Encoder(Encoder&&) noexcept=default;Encoder& Encoder::operator=(Encoder&&) noexcept=default;
void Encoder::reset() {impl_->state=make_state(impl_->width,impl_->lossless);}
void Encoder::append(const std::uint8_t* values,std::size_t count) {
    unsigned step=width_of(impl_->width)/8;check_input(values,count,step);auto next=impl_->state;
    std::visit([&](auto& s) {using S=std::decay_t<decltype(s)>;need(s.mode!=2,"cannot mix block and fragment APIs");s.mode=1;need(count<=max_block_values-s.count,"block limit");
        for(std::size_t i=0;i<count;++i)s.add(typename S::U(load(values+i*step,step)));},next);impl_->state=std::move(next);
}
Encoded Encoder::finish_block() {
    width_of(impl_->width);auto next=impl_->state;auto out=std::visit([](auto& s) {need(s.mode!=2,"fragment block pending");return s.close();},next);impl_->state=std::move(next);return out;
}
Encoded Encoder::fragment(std::uint64_t value,bool last) {
    need(width_of(impl_->width)==64,"binary64 network only");auto s=std::get<State<double>>(impl_->state);need(s.mode!=1,"block API pending");s.mode=2;s.writer.put(0,8);s.add(value);
    Encoded out;if(last)out=s.close();else {out={s.writer.bytes,std::uint64_t(s.writer.bytes.size())*8,s.writer.bits};s.writer={};}
    impl_->state=std::move(s);return out;
}
struct Decoder::Impl {Width width;States state;explicit Impl(Width w):width(w),state(make_state(w)) {}};
Decoder::Decoder(Width w):impl_(std::make_unique<Impl>(w)) {}
Decoder::~Decoder()=default;Decoder::Decoder(Decoder&&) noexcept=default;Decoder& Decoder::operator=(Decoder&&) noexcept=default;
void Decoder::reset() {impl_->state=make_state(impl_->width);}
Decoded Decoder::decode_block(const std::uint8_t* p,std::size_t n) {
    width_of(impl_->width);need(p && n && n<=max_stream_bytes,"invalid block size");auto next=impl_->state;Reader r{p,std::uint64_t(n)*8};Decoded out;
    std::visit([&](auto& s) {need(s.mode!=2,"fragment block pending");while(s.read_value(r,out.values))++out.count;out.consumed_bits=r.bits;r.padding();s.finish_decode();},next);impl_->state=std::move(next);return out;
}
Decoded Decoder::fragment(const std::uint8_t* p,std::size_t n,bool last) {
    need(width_of(impl_->width)==64,"binary64 network only");need(p && n>=2 && n<=max_stream_bytes && p[0]==0,"invalid fragment");auto s=std::get<State<double>>(impl_->state);s.mode=2;Reader r{p+1,std::uint64_t(n-1)*8};Decoded out;
    need(s.read_value(r,out.values),"early fragment terminator");out.count=1;if(last) {Bytes extra;need(!s.read_value(r,extra),"missing last terminator");s.finish_decode();}
    out.consumed_bits=r.bits+8;r.padding();impl_->state=std::move(s);return out;
}
std::size_t compress_bound(const Session& s) {auto n=session_bytes(s);return header+s.blocks.size()*512+n*4;}
Encoded compress(const Session& s) {
    auto total=session_bytes(s);unsigned step=width_of(s.width)/8;Encoder encoder(s.width);Bytes payload;std::uint64_t meaningful=0;
    for(auto& b:s.blocks) {
        store(payload,b.size()/step,4);
        if(!s.network) {encoder.append(b.data(),b.size()/step);auto out=encoder.finish_block();store(payload,out.bytes.size(),4);payload.insert(payload.end(),out.bytes.begin(),out.bytes.end());meaningful+=out.meaningful_bits;}
        else for(std::size_t i=0;i<b.size()/step;++i) {auto out=encoder.fragment(load(b.data()+i*step,step),i+1==b.size()/step);store(payload,out.bytes.size(),4);payload.insert(payload.end(),out.bytes.begin(),out.bytes.end());meaningful+=out.meaningful_bits;}
        need(payload.size()<=max_stream_bytes-header,"session stream limit");
    }
    Bytes out{'S','S','T','1',std::uint8_t(s.width),std::uint8_t(s.network),0,0};store(out,s.blocks.size(),4);store(out,total,8);store(out,payload.size(),8);
    out.insert(out.end(),payload.begin(),payload.end());auto checksum=crc(out.data(),out.size());out.insert(out.begin()+28,4,0);for(unsigned i=0;i<4;++i)out[28+i]=std::uint8_t(checksum>>(i*8));
    return {out,std::uint64_t(out.size())*8,meaningful};
}
Session decompress(const std::uint8_t* p,std::size_t n) {
    need(p && n>=header && n<=max_stream_bytes,"invalid frame size");need(std::memcmp(p,"SST1",4)==0 && p[5]<=1 && p[6]==0 && p[7]==0,"invalid frame header");Session s;s.width=Width(p[4]);s.network=p[5]!=0;unsigned step=width_of(s.width)/8;
    need(!s.network || step==8,"binary64 network only");std::size_t blocks=std::size_t(load(p+8,4));auto total=load(p+12,8),payload=load(p+20,8);need(blocks<=max_blocks && total<=max_values_bytes && payload==n-header,"invalid frame lengths");
    Bytes checked(p,p+28);checked.insert(checked.end(),p+32,p+n);need(crc(checked.data(),checked.size())==load(p+28,4),"frame checksum mismatch");
    Decoder decoder(s.width);std::size_t pos=header,actual=0;
    auto get32=[&]() {need(n-pos>=4,"truncated block record");auto v=load(p+pos,4);pos+=4;return v;};
    for(std::size_t b=0;b<blocks;++b) {
        auto count=get32();need(count<=max_block_values && count<=((max_values_bytes-actual)/step),"invalid block count");Bytes values;
        need(!s.network || count,"empty network block");std::size_t entries=s.network?std::size_t(count):1;
        for(std::size_t i=0;i<entries;++i) {auto length=get32();need(length<=n-pos,"truncated block payload");auto d=s.network?decoder.fragment(p+pos,std::size_t(length),i+1==entries):decoder.decode_block(p+pos,std::size_t(length));values.insert(values.end(),d.values.begin(),d.values.end());pos+=std::size_t(length);}
        need(values.size()==count*step,"block count mismatch");actual+=values.size();s.blocks.push_back(std::move(values));
    }
    need(actual==total && pos==n,"session length mismatch");return s;
}
bool compress_into(const Session& s,std::uint8_t* output,std::size_t capacity,std::size_t& written) {
    auto frame=compress(s);written=frame.bytes.size();if(capacity<written)return false;need(output || !written,"null output");std::memcpy(output,frame.bytes.data(),written);return true;
}
bool decompress_into(const std::uint8_t* p,std::size_t n,std::uint8_t* output,std::size_t capacity,std::size_t& written) {
    auto s=decompress(p,n);written=session_bytes(s);if(capacity<written)return false;need(output || !written,"null output");std::size_t offset=0;
    for(auto& b:s.blocks) {if(!b.empty())std::memcpy(output+offset,b.data(),b.size());offset+=b.size();}return true;
}
} // namespace self_star
