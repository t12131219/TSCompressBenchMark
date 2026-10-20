// SPDX-License-Identifier: LicenseRef-Local-Research
#include "chimp_family.hpp"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <cfenv>
#include <utility>
namespace chimp {
namespace {
constexpr unsigned rounds[]={0,8,12,16,18,20,22,24};
void require(bool b,const char* msg){if(!b)throw std::invalid_argument(msg);}
void valid(bool b,const char* msg){if(!b)throw std::runtime_error(msg);}
void limit(std::size_t n){if(n>max_values)throw std::length_error("value limit");}
bool is_chimp(Method m){return unsigned(m)>=1&&unsigned(m)<=5;}
bool lossy(Method m){return unsigned(m)>=7&&unsigned(m)<=11;}
unsigned width(Config c){return c.method==Method::Chimp32||c.method==Method::ChimpN32?32:64;}
bool multi(Config c){return c.method==Method::ChimpN||c.method==Method::ChimpNoIndex||c.method==Method::ChimpN32;}
unsigned logn(Config c){if(!multi(c))return 0; require(c.history&&c.history<=65536&&(c.history&(c.history-1))==0,"history must be power of two 1..65536"); unsigned l=0;for(auto n=c.history;n>1;n>>=1)++l;return l;}
unsigned lz(std::uint64_t v,unsigned w=64){if(w==32)v&=0xffffffffULL;return v?unsigned(__builtin_clzll(v))-(64-w):w;}
unsigned tz(std::uint64_t v,unsigned w){return v?unsigned(__builtin_ctzll(v)):w;}
unsigned rep(unsigned z){unsigned i=0;while(i<7&&rounds[i+1]<=z)++i;return i;}
std::uint64_t sentinel(unsigned w){return w==64?0x7ff8000000000000ULL:0x7fc00000ULL;}
std::uint64_t canonical(std::uint64_t v){return (v&0x7ff0000000000000ULL)==0x7ff0000000000000ULL&&(v&0xfffffffffffffULL)?sentinel(64):v;}
struct Reader { const std::vector<std::uint8_t>& b; std::size_t pos=0; std::uint64_t get(unsigned n){valid(n<=64,"bad bit width");valid(pos<=b.size()*8&&n<=b.size()*8-pos,"truncated bits");std::uint64_t v=0;for(unsigned i=0;i<n;++i,++pos)v=(v<<1)|((b[pos/8]>>(7-pos%8))&1U);return v;} };
std::uint64_t arithmetic(std::uint64_t x,unsigned n){return (x>>n)|((x>>63)?(~std::uint64_t(0)<<(64-n)):0);}
void le(std::vector<std::uint8_t>& b,std::uint64_t v,unsigned n){for(unsigned i=0;i<n;++i){b.push_back(std::uint8_t(v));v>>=8;}}
std::uint64_t take(const std::vector<std::uint8_t>& b,std::size_t& p,unsigned n){valid(n<=8&&p<=b.size()&&n<=b.size()-p,"truncated bytes");std::uint64_t v=0;for(unsigned i=0;i<n;++i)v|=std::uint64_t(b[p++])<<(8*i);return v;}
std::uint64_t bits(double d){std::uint64_t v;std::memcpy(&v,&d,8);return v;}
double dbl(std::uint64_t v){double d;std::memcpy(&d,&v,8);return d;}
std::uint32_t fbits(float f){std::uint32_t v;std::memcpy(&v,&f,4);return v;}
float flt(std::uint32_t v){float f;std::memcpy(&f,&v,4);return f;}
std::int64_t i64(std::uint64_t v){std::int64_t r;std::memcpy(&r,&v,8);return r;}
std::int64_t sub(std::int64_t a,std::int64_t b){return i64(std::uint64_t(a)-std::uint64_t(b));}
std::int64_t dec(std::int64_t a){return i64(std::uint64_t(a)-1);}
std::int64_t inc(std::int64_t a){return i64(std::uint64_t(a)+1);}
struct Line {double a=0,b=0;Line()=default;Line(std::int64_t ts,double vs,std::int64_t te,double ve):a((ve-vs)/double(sub(te,ts))),b(vs-a*double(ts)){} double get(std::int64_t t)const{return a*double(t)+b;} };
float jf(double d){if(d>double(std::numeric_limits<float>::max()))return std::numeric_limits<float>::infinity();if(d<-double(std::numeric_limits<float>::max()))return -std::numeric_limits<float>::infinity();return float(d);}
float quant(float f,float eps){float x=f/eps;std::int32_t i=std::isnan(x)?0:x>=2147483648.0f?INT32_MAX:x<=-2147483648.0f?INT32_MIN:std::int32_t(x);return float(i)*eps;}
Segment segment(std::int64_t s,std::int64_t e,const Line& l){return {s,e,l.a,l.b,0,0,0};}
std::uint32_t crc(const std::vector<std::uint8_t>& b){std::uint32_t c=~0U;for(auto x:b){c^=x;for(unsigned i=0;i<8;++i)c=(c>>1)^(0xedb88320U& (0U-(c&1U)));}return ~c;}
}
std::size_t raw_bound(Config c,std::size_t n){limit(n);if(c.method==Method::Fpc)return 17*((n+1)/2);require(is_chimp(c.method),"not a lossless raw method");unsigned l=logn(c);return ((n+1)*(width(c)+5+l)+8)/8;}
ChimpEncoder::ChimpEncoder(Config c):cfg_(c),width_(width(c)),log_(logn(c)),threshold_((width_==64?6:5)+log_),history_(multi(c)?c.history:1,0),indices_(multi(c)&&c.method!=Method::ChimpNoIndex?std::size_t(1)<<(threshold_+1):0,0){require(is_chimp(c.method),"invalid Chimp method");}
void ChimpEncoder::put(std::uint64_t v,unsigned n){require(n<=64,"write width");for(unsigned i=n;i>0;--i){if(bits_.meaningful_bits%8==0)bits_.bytes.push_back(0);bits_.bytes.back()|=std::uint8_t(((v>>(i-1))&1ULL)<<(7-bits_.meaningful_bits%8));++bits_.meaningful_bits;}}
void ChimpEncoder::append_word(std::uint64_t v){
 if(first_){first_=false;history_[0]=v;put(v,width_);if(!indices_.empty())indices_[std::size_t(v)&(indices_.size()-1)]=0;return;}
 unsigned prev=current_;std::uint64_t x=history_[prev]^v;unsigned trailing=multi(cfg_)?0:tz(x,width_);
 if(cfg_.method==Method::ChimpNoIndex){unsigned best=0;for(unsigned i=0;i<history_.size();++i){auto xx=history_[i]^v;unsigned t=tz(xx,width_);if(t>threshold_&&t>best){best=trailing=t;prev=i;x=xx;}}}
 else if(multi(cfg_)){
  auto ci=indices_[std::size_t(v)&(indices_.size()-1)];
  if(index_-ci<cfg_.history){auto xx=v^history_[ci%cfg_.history];trailing=tz(xx,width_);if(trailing>threshold_){prev=ci%cfg_.history;x=xx;}}
  if(width_==32)trailing=tz(x,width_);
 }
 if(!x){put(0,2);if(multi(cfg_))put(prev,log_);leading_=width_+1;}
 else {unsigned code=rep(lz(x,width_)),leading=rounds[code];if(trailing>threshold_){put(1,2);if(multi(cfg_))put(prev,log_);put(code,3);unsigned sig=width_-leading-trailing;put(sig,width_==64?6:5);put(x>>trailing,sig);leading_=width_+1;}
 else if(leading==leading_){put(2,2);put(x,width_-leading);}
 else{leading_=leading;put(3,2);put(code,3);put(x,width_-leading);}}
 current_=(current_+1)%std::uint32_t(history_.size());history_[current_]=v;++index_;if(!indices_.empty())indices_[std::size_t(v)&(indices_.size()-1)]=index_;
}
void ChimpEncoder::add(std::uint64_t v){require(!closed_,"encode after finalize");limit(size()+1);require(width_==64||v<=0xffffffffULL,"word exceeds f32 width");require(v!=sentinel(width_),"canonical positive NaN reserved EOF");bits_.bytes.reserve(raw_bound(cfg_,size()+1));append_word(v);}
Bits ChimpEncoder::finalize(){if(closed_)return bits_;auto tmp=*this;tmp.append_word(sentinel(width_));tmp.put(0,1);tmp.closed_=true;Bits result=tmp.bits_;*this=std::move(tmp);return result;}
void ChimpEncoder::reset(){*this=ChimpEncoder(cfg_);}
std::size_t ChimpEncoder::workspace_bytes()const noexcept{return history_.capacity()*8+indices_.capacity()*4+bits_.bytes.capacity();}
Bits encode_chimp(Config c,const std::vector<std::uint64_t>& words){limit(words.size());ChimpEncoder e(c);for(auto v:words)e.add(v);return e.finalize();}
ChimpDecoder::ChimpDecoder(Config c,const std::vector<std::uint8_t>& b):cfg_(c),width_(width(c)),log_(logn(c)){require(is_chimp(c.method),"invalid Chimp method");valid(b.size()<=raw_bound(c,max_values),"raw size limit");bytes_=b;history_.assign(multi(c)?c.history:1,0);}
std::uint64_t ChimpDecoder::get(unsigned n,std::size_t& pos)const{valid(n<=64&&pos<=bytes_.size()*8&&n<=bytes_.size()*8-pos,"truncated/bad bits");std::uint64_t v=0;for(unsigned i=0;i<n;++i,++pos)v=(v<<1)|((bytes_[pos/8]>>(7-pos%8))&1U);return v;}
bool ChimpDecoder::next(std::uint64_t& output){if(closed_)return false;auto pos=pos_;auto v=last_;unsigned leading=leading_,curr=current_;if(first_)v=get(width_,pos);else{unsigned f=unsigned(get(2,pos));if(f==0){if(multi(cfg_))v=history_[std::size_t(get(log_,pos))];}else if(f==1){unsigned p=multi(cfg_)?unsigned(get(log_,pos)):curr;leading=rounds[get(3,pos)];unsigned sig=unsigned(get(width_==64?6:5,pos));if(!sig)sig=width_;valid(leading+sig<=width_,"invalid significant bits");auto x=get(sig,pos);unsigned t=width_-leading-sig;v=history_[p]^(t?x<<t:x);}else{if(f==3)leading=rounds[get(3,pos)];valid(leading<width_,"uninitialized leading state");v^=get(width_-leading,pos);}curr=(curr+1)%unsigned(history_.size());}
 if(v==sentinel(width_)){valid(get(1,pos)==0,"bad finish bit");while(pos%8)valid(get(1,pos)==0,"bad pad bit");valid(pos==bytes_.size()*8,"trailing bytes");closed_=true;pos_=pos;return false;}
 valid(count_<max_values,"decode count limit");pos_=pos;current_=curr;leading_=leading;last_=v;first_=false;history_[curr]=v;++count_;output=v;return true;}
void ChimpDecoder::reset(const std::vector<std::uint8_t>& b){*this=ChimpDecoder(cfg_,b);}
std::vector<std::uint64_t> decode_chimp(Config c,const std::vector<std::uint8_t>& b){ChimpDecoder d(c,b);std::vector<std::uint64_t> out;std::uint64_t v;while(d.next(v))out.push_back(v);return out;}
// SPDX-License-Identifier for the following FPC translation: EPL-1.0
// Copyright (c) 2013 Michael Kutschke. Translation preserves original predictor and format.
std::uint64_t Fpc::to_long(const std::vector<std::uint8_t>& b){require(b.size()<=8,"FPC residual exceeds eight bytes");std::size_t pos=0;return take(b,pos,unsigned(b.size()));}
std::vector<std::uint8_t> Fpc::to_byte_array(std::uint64_t v){unsigned z=lz(v)/8,code=z>=4?z-1:z;if(code>3)++code;std::vector<std::uint8_t> b;le(b,v,8-code);return b;}
Fpc::Fpc():fcm_(65536,0),dfcm_(65536,0){}
void Fpc::reset(){std::fill(fcm_.begin(),fcm_.end(),0);std::fill(dfcm_.begin(),dfcm_.end(),0);fh_=dh_=0;last_=0;closed_=false;}
std::uint64_t Fpc::prediction(unsigned p)const{return p?dfcm_[dh_]+last_:fcm_[fh_];}
void Fpc::update(std::uint64_t v){fcm_[fh_]=v;fh_=std::uint32_t(((std::uint64_t(fh_)<<6)^arithmetic(v,48))&65535);auto delta=v-last_;dfcm_[dh_]=delta;dh_=std::uint32_t(((std::uint64_t(dh_)<<2)^arithmetic(delta,40))&65535);last_=v;}
std::vector<std::uint8_t> Fpc::encode(const std::vector<std::uint64_t>& a,bool reject){require(!closed_,"FPC after finalize");limit(a.size());Fpc tmp=*this;std::vector<std::uint8_t> b;b.reserve(raw_bound({Method::Fpc,128,0},a.size()));
 for(std::size_t i=0;i<a.size();i+=2){std::uint8_t codes[2]={0,6};std::uint64_t diff[2]={0,0};unsigned len[2]={0,1};
 for(unsigned j=0;j<2&&i+j<a.size();++j){auto v=canonical(a[i+j]);require(!reject||v==a[i+j],"NaN payload would be canonicalized");auto d0=tmp.prediction(0)^v,d1=tmp.prediction(1)^v;unsigned p=lz(d0)>=lz(d1)?0:1;diff[j]=p?d1:d0;unsigned z=lz(diff[j])/8,code=z>=4?z-1:z;unsigned decoded=code>3?code+1:code;len[j]=8-decoded;codes[j]=std::uint8_t(p*8+code);tmp.update(v);}
 b.push_back(std::uint8_t((codes[0]<<4)|codes[1]));for(unsigned j=0;j<2;++j)le(b,diff[j],len[j]);}
 *this=std::move(tmp);return b;
}
std::vector<std::uint64_t> Fpc::decode(const std::vector<std::uint8_t>& b,std::size_t count){require(!closed_,"FPC after finalize");limit(count);valid(b.size()<=raw_bound({Method::Fpc,128,0},count),"FPC size bound");Fpc tmp=*this;std::vector<std::uint64_t> a;a.reserve(count);std::size_t pos=0;
 for(std::size_t i=0;i<count;i+=2){unsigned hdr=unsigned(take(b,pos,1));for(unsigned j=0;j<2;++j){unsigned code=(hdr>>(j?0:4))&15U,z=code&7U;if(z>3)++z;auto diff=take(b,pos,8-z);if(i+j==count){valid(code==6&&diff==0,"invalid odd pad");break;}valid(!(j==1&&z==7&&diff==0),"unexpected odd sentinel");auto v=tmp.prediction(code>>3)^diff;tmp.update(v);a.push_back(v);}}
 valid(pos==b.size(),"FPC trailing bytes");*this=std::move(tmp);return a;
}
std::vector<Segment> filter(Config c,const std::vector<Point>& p){require(lossy(c.method),"invalid filter method");require(std::fegetround()==FE_TONEAREST,"round-to-nearest FP environment required");limit(p.size());require(std::isfinite(c.epsilon)&&c.epsilon>=0,"finite nonnegative epsilon required");for(std::size_t i=0;i<p.size();++i){require(std::isfinite(p[i].value),"finite float inputs required");require(i==0||p[i].timestamp>p[i-1].timestamp,"timestamps must strictly increase");}
 std::vector<Segment> out;float eps=c.epsilon;
 if(c.method==Method::Pmc){float hi=std::numeric_limits<float>::denorm_min(),lo=std::numeric_limits<float>::max();Segment s{};bool have=false;for(auto pt:p){hi=std::max(hi,pt.value);lo=std::min(lo,pt.value);if(hi-lo<=eps&&have){s.end=pt.timestamp;s.b=double(hi-((hi-lo)/2.0f));}else{if(have)out.push_back(s);hi=lo=pt.value;s={pt.timestamp,pt.timestamp,0,double(pt.value),0,0,0};have=true;}}if(have)out.push_back(s);return out;}
 require(!p.empty(),"source filter undefined for empty input");
 if(c.method==Method::Quantized){require(eps>0,"quantized epsilon must be positive");std::size_t first=0;double amin=std::numeric_limits<double>::denorm_min(),amax=std::numeric_limits<double>::max();auto emit=[&](std::size_t end){float b=quant(p[first].value,eps);Line l(std::int64_t(first),b,std::int64_t(first+1),jf((amax+amin)/2+b));Segment s=segment(std::int64_t(first),std::int64_t(end),l);s.a_min=amin;s.a_max=amax;s.quantized_b=b;out.push_back(s);};
 for(std::size_t i=1;i<p.size();++i){float up=p[i].value+eps,down=p[i].value-eps,b=quant(p[first].value,eps);double ul=amax*double(i-first)+b,dl=amin*double(i-first)+b;if(i-first>1&&(down>ul||up<dl)){emit(i-1);first=i;continue;}float au=(up-quant(p[first].value,eps))/float(i-first),al=(down-quant(p[first].value,eps))/float(i-first);if(i-first==1){amax=au;amin=al;}else{if(up<ul)amax=au>=amin?au:amin;if(down>dl)amin=al<=amax?al:amax;}}
 emit(p.size()-1);return out;}
 if(c.method==Method::Swing){require(p.size()>=2,"Swing source requires two points");Point first=p[0],current=p[1],previous=first;Line ui(first.timestamp,first.value,current.timestamp,current.value+eps),li(first.timestamp,first.value,current.timestamp,current.value-eps);
 for(std::size_t i=2;i<p.size();++i){previous=current;current=p[i];if(ui.get(current.timestamp)<current.value-eps||li.get(current.timestamp)>current.value+eps){Line line(first.timestamp,first.value,previous.timestamp,(ui.get(previous.timestamp)+li.get(previous.timestamp))/2);out.push_back(segment(first.timestamp,dec(previous.timestamp),line));first=previous={previous.timestamp,jf(line.get(previous.timestamp))};ui=Line(previous.timestamp,previous.value,current.timestamp,current.value+eps);li=Line(previous.timestamp,previous.value,current.timestamp,current.value-eps);}else{Line un(first.timestamp,first.value,current.timestamp,current.value+eps),ln(first.timestamp,first.value,current.timestamp,current.value-eps);if(ui.get(current.timestamp)>un.get(current.timestamp))ui=un;if(li.get(current.timestamp)<ln.get(current.timestamp))li=ln;}}
 out.push_back(segment(first.timestamp,current.timestamp,Line(first.timestamp,first.value,current.timestamp,(ui.get(current.timestamp)+li.get(current.timestamp))/2)));return out;}
 Point first=p[0],last=first;Line ui,li;bool have=false;for(std::size_t i=1;i<p.size();++i){auto pt=p[i];last=pt;if(have&&(ui.get(pt.timestamp)<pt.value||li.get(pt.timestamp)>pt.value)){Line line(first.timestamp,first.value,pt.timestamp,(ui.get(pt.timestamp)+li.get(pt.timestamp))/2);out.push_back(segment(first.timestamp,dec(pt.timestamp),line));have=false;first=pt;}else{Line un(first.timestamp,first.value,pt.timestamp,pt.value+eps),ln(first.timestamp,first.value,pt.timestamp,pt.value-eps);if(!have||ui.get(pt.timestamp)>un.get(pt.timestamp))ui=un;if(!have||li.get(pt.timestamp)<ln.get(pt.timestamp))li=ln;have=true;}}
 out.push_back(segment(first.timestamp,have?last.timestamp:first.timestamp,have?Line(first.timestamp,first.value,last.timestamp,(ui.get(last.timestamp)+li.get(last.timestamp))/2):Line(first.timestamp,first.value,inc(first.timestamp),first.value)));return out;
}
SegmentDecoder::SegmentDecoder(const std::vector<Segment>& s,bool constant_values):constant_values_(constant_values){require(std::fegetround()==FE_TONEAREST,"round-to-nearest FP environment required");limit(s.size());std::size_t n=0;for(auto x:s){valid(x.end>=x.start,"reversed segment");auto delta=std::uint64_t(x.end)-std::uint64_t(x.start);valid(delta<max_values&&n<=max_values-std::size_t(delta)-1,"dense output resource limit");n+=std::size_t(delta)+1;}segments_=s;}
bool SegmentDecoder::next(Point& out){require(std::fegetround()==FE_TONEAREST,"round-to-nearest FP environment required");if(current_>=segments_.size())return false;auto s=segments_[current_];auto t=i64(std::uint64_t(s.start)+offset_);out={t,jf(constant_values_?s.b:s.a*double(t)+s.b)};if(t==s.end){++current_;offset_=0;}else ++offset_;return true;}
std::vector<Point> reconstruct(const std::vector<Segment>& s,bool constant_values){SegmentDecoder d(s,constant_values);std::vector<Point> out;Point p;while(d.next(p))out.push_back(p);return out;}
Quality quality(const std::vector<Point>& in,const std::vector<Point>& out,float eps,bool by_index){Quality q;std::size_t j=0;for(std::size_t i=0;i<in.size();++i){auto ts=by_index?std::int64_t(i):in[i].timestamp;while(j<out.size()&&out[j].timestamp<ts)++j;if(j==out.size()||out[j].timestamp!=ts){q.within_epsilon=false;++q.violations;continue;}double err=std::abs(double(in[i].value)-double(out[j].value));if(!std::isfinite(err)){q.finite=q.within_epsilon=false;++q.violations;q.max_absolute_error=std::numeric_limits<double>::infinity();}else{q.max_absolute_error=std::max(q.max_absolute_error,err);if(err>double(eps)){q.within_epsilon=false;++q.violations;}}}return q;}
std::vector<std::uint8_t> serialize_segments(const std::vector<Segment>& s){limit(s.size());std::vector<std::uint8_t> b;b.reserve(s.size()*52);for(auto x:s){le(b,std::uint64_t(x.start),8);le(b,std::uint64_t(x.end),8);le(b,bits(x.a),8);le(b,bits(x.b),8);le(b,bits(x.a_min),8);le(b,bits(x.a_max),8);le(b,fbits(x.quantized_b),4);}return b;}
std::vector<Segment> parse_segments(const std::vector<std::uint8_t>& b){valid(b.size()%52==0&&b.size()/52<=max_values,"segment size");std::vector<Segment> s;std::size_t p=0;while(p<b.size()){Segment x{};x.start=i64(take(b,p,8));x.end=i64(take(b,p,8));x.a=dbl(take(b,p,8));x.b=dbl(take(b,p,8));x.a_min=dbl(take(b,p,8));x.a_max=dbl(take(b,p,8));x.quantized_b=flt(std::uint32_t(take(b,p,4)));valid(x.end>=x.start,"segment order");s.push_back(x);}return s;}
namespace {
std::vector<std::uint8_t> frame(Config c,std::size_t count,const std::vector<std::uint8_t>& payload){limit(count);std::vector<std::uint8_t> b={'C','F','P','1',1,std::uint8_t(c.method),0,0};le(b,c.history,4);le(b,fbits(c.epsilon),4);le(b,count,8);le(b,payload.size(),8);b.insert(b.end(),payload.begin(),payload.end());le(b,crc(b),4);return b;}
}
std::vector<std::uint8_t> encode_frame(Config c,const std::vector<std::uint64_t>& in){if(is_chimp(c.method))return frame(c,in.size(),encode_chimp(c,in).bytes);require(c.method==Method::Fpc,"expected lossless method");Fpc f;return frame(c,in.size(),f.encode(in));}
std::vector<std::uint8_t> encode_frame(Config c,const std::vector<Point>& in,bool strict){auto s=filter(c,in);auto reconstructed=reconstruct(s,c.method==Method::Pmc);if(strict){auto q=quality(in,reconstructed,c.epsilon,c.method==Method::Quantized);require(q.finite&&q.within_epsilon,"source variant fails requested absolute error bound");}return frame(c,in.size(),serialize_segments(s));}
Decoded decode_frame(const std::vector<std::uint8_t>& b){valid(b.size()>=36&&b.size()<=52*max_values+36,"frame size");valid(b[0]=='C'&&b[1]=='F'&&b[2]=='P'&&b[3]=='1'&&b[4]==1&&!b[6]&&!b[7],"frame header");std::size_t p=8;Config c;c.method=Method(b[5]);c.history=std::uint32_t(take(b,p,4));c.epsilon=flt(std::uint32_t(take(b,p,4)));auto count64=take(b,p,8);valid(count64<=max_values,"frame count resource limit");std::size_t count=std::size_t(count64);auto len=take(b,p,8);valid(len==b.size()-36,"frame payload length");std::size_t cp=b.size()-4;auto expected=take(b,cp,4);std::vector<std::uint8_t> prefix(b.begin(),b.end()-4);valid(crc(prefix)==expected,"frame CRC");std::vector<std::uint8_t> payload(b.begin()+32,b.end()-4);Decoded d;d.config=c;
 if(is_chimp(c.method)){d.words=decode_chimp(c,payload);valid(d.words.size()==count,"frame count");}
 else if(c.method==Method::Fpc){Fpc f;d.words=f.decode(payload,count);}
 else{valid(lossy(c.method)&&std::isfinite(c.epsilon)&&c.epsilon>=0,"frame method/epsilon");d.segments=parse_segments(payload);valid(d.segments.size()<=count,"frame segment count");d.points=reconstruct(d.segments,c.method==Method::Pmc);if(c.method==Method::Quantized){valid(d.points.size()==count,"quantized count");for(std::size_t i=0;i<count;++i)valid(d.points[i].timestamp==std::int64_t(i),"quantized timestamps");}}
 return d;
}
}
