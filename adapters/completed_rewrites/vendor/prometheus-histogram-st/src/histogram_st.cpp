// Copyright The Prometheus Authors
// Copyright (c) 2015,2016 Damian Gryski <damian@gryski.com>
// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: Apache-2.0 AND BSD-3-Clause
// Translation of the frozen paired histogram/ST pipeline, not a Go runtime wrapper.
#include "histogram_st.hpp"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <map>
#include <new>
#include <set>
#include <stdexcept>
#include <utility>

namespace histogram_st {
namespace {
constexpr std::size_t limit=100000, sample_limit=16383;
constexpr std::uint64_t stale=UINT64_C(0x7ff0000000000002);
struct Failure { Code code; const char* message; };
[[noreturn]] void fail(Code code,const char* message) { throw Failure{code,message}; }
std::uint64_t u64(std::int64_t x) { std::uint64_t y; std::memcpy(&y,&x,8); return y; }
std::int64_t i64(std::uint64_t x) { std::int64_t y; std::memcpy(&y,&x,8); return y; }
double number(std::uint64_t x) { double y; std::memcpy(&y,&x,8); return y; }
std::uint64_t bits(double x) { std::uint64_t y; std::memcpy(&y,&x,8); return y; }
unsigned clz(std::uint64_t x) { return x ? unsigned(__builtin_clzll(x)) : 64; }
unsigned ctz(std::uint64_t x) { return x ? unsigned(__builtin_ctzll(x)) : 64; }
struct Reader {
    const std::uint8_t* data=nullptr; std::size_t bytes=0,pos=24;
    std::uint64_t read(unsigned n) {
        if(n>64 || pos>bytes*8 || n>bytes*8-pos) fail(Code::MalformedStream,"truncated bits");
        std::uint64_t x=0;
        for(unsigned j=0;j<n;++j,++pos) x=(x<<1)|((data[pos/8]>>(7-pos%8))&1);
        return x;
    }
};
struct Writer {
    std::vector<std::uint8_t>& data; std::size_t& pos;
    void write(std::uint64_t x,unsigned n) {
        if(n>64 || pos>std::numeric_limits<std::size_t>::max()-n) fail(Code::ResourceLimit,"bit size overflow");
        for(unsigned j=n;j>0;--j,++pos) {
            if(pos/8==data.size()) data.push_back(0);
            auto mask=std::uint8_t(1U<<(7-pos%8));
            if((x>>(j-1))&1) data[pos/8]|=mask; else data[pos/8]&=std::uint8_t(~mask);
        }
    }
};
constexpr unsigned widths[]={0,3,6,9,12,18,25,56,64};
void varbit(Writer& w,std::uint64_t value,bool signed_value) {
    if(value==0) {w.write(0,1); return;}
    unsigned branch=8;
    for(unsigned j=1;j<8;++j) {
        unsigned n=widths[j];
        if(signed_value ? (i64(value)>-i64(UINT64_C(1)<<(n-1)) && i64(value)<=i64(UINT64_C(1)<<(n-1)))
                        : clz(value)>=64-n) {branch=j; break;}
    }
    if(branch==8) w.write(255,8); else w.write((UINT64_C(1)<<(branch+1))-2,branch+1);
    w.write(value,widths[branch]);
}
std::uint64_t varbit(Reader& r,bool signed_value) {
    unsigned ones=0;
    while(ones<8 && r.read(1)) ++ones;
    if(!ones) return 0;
    unsigned n=widths[ones];
    auto value=r.read(n);
    if(signed_value && n<64 && value>(UINT64_C(1)<<(n-1))) value-=UINT64_C(1)<<n;
    return value;
}
void varint(Writer& w,std::uint64_t value) {
    std::uint64_t encoded=(value<<1) ^ (i64(value)<0 ? UINT64_MAX : 0);
    while(encoded>=128) { w.write((encoded&127)|128,8); encoded>>=7; }
    w.write(encoded,8);
}
std::uint64_t varint(Reader& r) {
    std::uint64_t x=0;
    for(unsigned j=0;j<10;++j) {
        auto b=r.read(8);
        if(j==9 && b>1) fail(Code::MalformedStream,"varint overflow");
        x|=(b&127)<<(j*7);
        if(b<128) return (x>>1) ^ ((x&1) ? UINT64_MAX : 0);
    }
    fail(Code::MalformedStream,"varint overflow");
}
struct Xor { std::uint64_t value=0; unsigned leading=0,trailing=0; };
void xor_write(Writer& w,Xor& old,std::uint64_t value) {
    auto delta=value^old.value;
    if(!delta) {w.write(0,1); return;}
    w.write(1,1);
    unsigned leading=std::min(31U,clz(delta)),trailing=ctz(delta);
    if(old.leading!=255 && leading>=old.leading && trailing>=old.trailing) {
        w.write(0,1); w.write(delta>>old.trailing,64-old.leading-old.trailing);
    } else {
        old.leading=leading; old.trailing=trailing;
        unsigned n=64-leading-trailing;
        w.write(1,1); w.write(leading,5); w.write(n&63,6); w.write(delta>>trailing,n);
    }
    old.value=value;
}
void xor_read(Reader& r,Xor& old) {
    if(!r.read(1)) return;
    if(r.read(1)) {
        unsigned leading=unsigned(r.read(5)),n=unsigned(r.read(6)); if(!n) n=64;
        if(leading+n>64) fail(Code::MalformedStream,"invalid XOR window");
        old.leading=leading; old.trailing=64-leading-n;
    }
    if(old.leading+old.trailing>=64) fail(Code::MalformedStream,"empty XOR window");
    old.value ^= r.read(64-old.leading-old.trailing)<<old.trailing;
}
std::vector<std::int64_t> indices(const std::vector<Span>& spans) {
    if(spans.size()>limit) fail(Code::ResourceLimit,"span limit");
    std::vector<std::int64_t> out;
    std::int64_t index=0;
    for(std::size_t i=0;i<spans.size();++i) {
        const auto& s=spans[i];
        if(i && s.offset<0) fail(Code::InvalidArgument,"negative later span offset");
        if(s.length>limit-out.size()) fail(Code::ResourceLimit,"bucket limit");
        index+=s.offset;
        for(std::uint32_t j=0;j<s.length;++j) out.push_back(index++);
    }
    return out;
}
std::vector<Span> make_spans(const std::vector<std::int64_t>& indices) {
    std::vector<Span> out;
    std::int64_t prev=0;
    for(auto index:indices) {
        auto offset=out.empty()?index:index-prev-1;
        if(!out.empty() && !offset) ++out.back().length;
        else {
            if(offset<INT32_MIN || offset>INT32_MAX) fail(Code::ResourceLimit,"span offset overflow");
            out.push_back(Span{std::int32_t(offset),1});
        }
        prev=index;
    }
    return out;
}
void validate(Kind kind,const Sample& s) {
    (void)kind;
    if(s.hint>3) fail(Code::InvalidArgument,"invalid reset hint");
    if(s.schema!=-53 && (s.schema< -9 || s.schema>52)) fail(Code::InvalidArgument,"unknown schema");
    if(s.custom.size()>limit) fail(Code::ResourceLimit,"custom bound limit");
    if(s.sum==stale) return; // As upstream, irrelevant stale fields are ignored.
    if(indices(s.positive_spans).size()!=s.positive.size() || indices(s.negative_spans).size()!=s.negative.size())
        fail(Code::InvalidArgument,"span/bucket mismatch");
}
void write_spans(Writer& w,const std::vector<Span>& spans) {
    varbit(w,spans.size(),false);
    for(auto s:spans) {varbit(w,s.length,false);varbit(w,u64(s.offset),true);}
}
std::vector<Span> read_spans(Reader& r) {
    auto n=varbit(r,false);
    if(n>limit || n>(r.bytes*8-r.pos)/2) fail(Code::MalformedStream,"span allocation limit");
    std::vector<Span> out;
    for(std::uint64_t i=0;i<n;++i) {
        auto length=varbit(r,false);auto offset=varbit(r,true);
        if(length>UINT32_MAX || i64(offset)<INT32_MIN || i64(offset)>INT32_MAX) fail(Code::MalformedStream,"span integer range");
        out.push_back(Span{std::int32_t(i64(offset)),std::uint32_t(length)});
    }
    (void)indices(out); return out;
}
void layout_write(Writer& w,const Sample& s) {
    double threshold=number(s.threshold); int exp=0; double frac=std::frexp(threshold,&exp);
    if(threshold==0.) w.write(0,8);
    else if(frac==.5 && exp>=-242 && exp<=11) w.write(unsigned(exp+243),8);
    else {w.write(255,8);w.write(s.threshold,64);}
    varbit(w,u64(s.schema),true);write_spans(w,s.positive_spans);write_spans(w,s.negative_spans);
    if(s.schema==-53) {
        varbit(w,s.custom.size(),false);
        for(auto value:s.custom) {
            double f=number(value),tf=f*1000.;
            bool compact=std::isfinite(tf) && tf>=0. && tf<=33554430. && f==std::round(tf)/1000.;
            if(compact) varbit(w,std::uint64_t(std::round(tf))+1,false);
            else {w.write(0,1);w.write(value,64);}
        }
    }
}
Sample layout_read(Reader& r) {
    Sample s; auto t=r.read(8);
    s.threshold=t==0 ? 0 : t==255 ? r.read(64) : bits(std::ldexp(.5,int(t)-243));
    auto schema=i64(varbit(r,true));
    if(schema<INT32_MIN || schema>INT32_MAX) fail(Code::MalformedStream,"schema range");
    s.schema=std::int32_t(schema);
    if(s.schema!=-53 && (s.schema< -9 || s.schema>52)) fail(Code::MalformedStream,"unknown schema");
    s.positive_spans=read_spans(r);s.negative_spans=read_spans(r);
    if(s.schema==-53) {
        auto n=varbit(r,false);
        if(n>limit || n>r.bytes*8-r.pos) fail(Code::MalformedStream,"custom bounds allocation limit");
        for(std::uint64_t i=0;i<n;++i) {auto v=varbit(r,false);s.custom.push_back(v?bits(double(v-1)/1000.):r.read(64));}
    }
    return s;
}
struct State {
    Sample current;
    std::uint64_t td=0,cd=0,zd=0,st_diff=0;
    std::vector<std::uint64_t> pd,nd;
    Xor count,zero,sum;
    std::vector<Xor> positive,negative;
    std::size_t n=0;
    State() { current.timestamp=INT64_MIN; }
};
void state_init(State& state,Kind kind,const Sample& s,bool encoder) {
    state.current=s;
    state.pd.assign(s.positive.size(),0);state.nd.assign(s.negative.size(),0);
    state.positive.assign(s.positive.size(),Xor{});state.negative.assign(s.negative.size(),Xor{});
    state.count=Xor{s.count,encoder?255U:0U,0};state.zero=Xor{s.zero,encoder?255U:0U,0};
    state.sum=Xor{s.sum,encoder?255U:0U,0};
    if(kind==Kind::Floating) {
        for(std::size_t i=0;i<s.positive.size();++i) state.positive[i]=Xor{s.positive[i],encoder?255U:0U,0};
        for(std::size_t i=0;i<s.negative.size();++i) state.negative[i]=Xor{s.negative[i],encoder?255U:0U,0};
    }
}
void sample_write(Writer& w,State& state,Kind kind,Sample s) {
    const bool is_stale=s.sum==stale;
    if(is_stale) {Sample cleared;cleared.st=s.st;cleared.timestamp=s.timestamp;cleared.sum=s.sum;s=std::move(cleared);}
    auto previous_timestamp=u64(state.current.timestamp);
    if(state.n==0) {
        layout_write(w,s);varbit(w,u64(s.timestamp),true);
        if(kind==Kind::Integer) {varbit(w,s.count,false);varbit(w,s.zero,false);}
        else {w.write(s.count,64);w.write(s.zero,64);}
        w.write(s.sum,64);
        for(auto v:s.positive) {if(kind==Kind::Integer)varbit(w,v,true);else w.write(v,64);}
        for(auto v:s.negative) {if(kind==Kind::Integer)varbit(w,v,true);else w.write(v,64);}
        state_init(state,kind,s,true);
    } else {
        auto td=u64(s.timestamp)-previous_timestamp;
        varbit(w,td-state.td,true);state.td=td;
        if(kind==Kind::Integer) {
            auto cd=s.count-state.current.count,zd=s.zero-state.current.zero;
            varbit(w,is_stale?0:cd-state.cd,true);varbit(w,is_stale?0:zd-state.zd,true);
            state.cd=cd;state.zd=zd;
        } else {xor_write(w,state.count,s.count);xor_write(w,state.zero,s.zero);}
        xor_write(w,state.sum,s.sum);
        auto write_side=[&](const auto& values,const auto& old,auto& deltas,auto& xors) {
            for(std::size_t i=0;i<values.size();++i) {
                if(kind==Kind::Integer) {auto delta=values[i]-old[i];varbit(w,delta-deltas[i],true);deltas[i]=delta;}
                else xor_write(w,xors[i],values[i]);
            }
        };
        write_side(s.positive,state.current.positive,state.pd,state.positive);
        write_side(s.negative,state.current.negative,state.nd,state.negative);
        // Layout and stale bucket arrays remain the original appender layout.
        state.current.st=s.st;state.current.timestamp=s.timestamp;
        state.current.count=s.count;state.current.zero=s.zero;state.current.sum=s.sum;
        if(!is_stale) {state.current.positive=s.positive;state.current.negative=s.negative;}
    }
    ++state.n;
    if(state.n==1) {
        if(s.st!=0) {varint(w,u64(s.timestamp)-u64(s.st));w.data[2]=128;}
    } else if(state.n==2) {
        // state.current.st has already changed; previous ST is supplied below.
    }
}
// ST is encoded after the histogram fields and uses the pre-append state.
void st_write(Writer& w,State& state,std::uint64_t prev_t,std::uint64_t prev_st,std::int64_t st) {
    if(state.n==1) return; // First-sample varint was written by sample_write.
    unsigned first=w.data[2]&127;
    auto diff=prev_t-u64(st);
    if(state.n==2) {
        if(u64(st)!=prev_st) {w.data[2]|=1;varbit(w,diff,true);state.st_diff=diff;}
    } else if(!first) {
        if(u64(st)!=prev_st || state.n-1==127) {w.data[2]|=std::uint8_t(state.n-1);varbit(w,diff,true);state.st_diff=diff;}
    } else {varbit(w,diff-state.st_diff,true);state.st_diff=diff;}
}
void sample_read(Reader& r,State& state,Kind kind,std::uint8_t header) {
    auto prev_t=u64(state.current.timestamp);
    if(!state.n) {
        Sample s=layout_read(r);s.timestamp=i64(varbit(r,true));
        if(kind==Kind::Integer) {s.count=varbit(r,false);s.zero=varbit(r,false);}
        else {s.count=r.read(64);s.zero=r.read(64);}
        s.sum=r.read(64);
        auto side=[&](const auto& spans,auto& values) {
            auto n=indices(spans).size();
            if(n>(r.bytes*8-r.pos)/(kind==Kind::Integer?1:64)) fail(Code::MalformedStream,"bucket allocation limit");
            for(std::size_t i=0;i<n;++i) values.push_back(kind==Kind::Integer?varbit(r,true):r.read(64));
        };
        side(s.positive_spans,s.positive);side(s.negative_spans,s.negative);
        state_init(state,kind,s,false);
    } else {
        state.td+=varbit(r,true);state.current.timestamp=i64(u64(state.current.timestamp)+state.td);
        if(kind==Kind::Integer) {
            state.cd+=varbit(r,true);state.zd+=varbit(r,true);
            state.current.count+=state.cd;state.current.zero+=state.zd;
        } else {
            xor_read(r,state.count);xor_read(r,state.zero);
            state.current.count=state.count.value;state.current.zero=state.zero.value;
        }
        xor_read(r,state.sum);state.current.sum=state.sum.value;
        if(state.current.sum!=stale) {
            auto side=[&](auto& values,auto& deltas,auto& xors) {
                for(std::size_t i=0;i<values.size();++i) {
                    if(kind==Kind::Integer) {deltas[i]+=varbit(r,true);values[i]+=deltas[i];}
                    else {xor_read(r,xors[i]);values[i]=xors[i].value;}
                }
            };
            side(state.current.positive,state.pd,state.positive);side(state.current.negative,state.nd,state.negative);
        }
    }
    ++state.n;
    unsigned first=header&127;
    if(state.n==1) {
        if(header&128) {state.st_diff=varint(r);state.current.st=i64(u64(state.current.timestamp)-state.st_diff);}
    } else if(state.n==2 && first==1) {
        state.st_diff=varbit(r,true);state.current.st=i64(prev_t-state.st_diff);
    } else if(state.n>2 && first && state.n-1>=first) {
        auto dod=varbit(r,true);
        state.st_diff=state.n-1==first ? dod : state.st_diff+dod;
        state.current.st=i64(prev_t-state.st_diff);
    }
}
using Counts=std::map<std::int64_t,std::uint64_t>;
Counts absolute(Kind kind,const std::vector<Span>& spans,const std::vector<std::uint64_t>& values) {
    auto ids=indices(spans);if(ids.size()!=values.size()) fail(Code::InvalidArgument,"span/bucket mismatch");
    Counts out;std::uint64_t value=0;
    for(std::size_t i=0;i<ids.size();++i) {value=kind==Kind::Integer?value+values[i]:values[i];out.emplace(ids[i],value);}
    return out;
}
std::vector<std::uint64_t> expand(Kind kind,const std::vector<Span>& from,const std::vector<std::uint64_t>& values,const std::vector<Span>& to) {
    auto original=absolute(kind,from,values);auto ids=indices(to);std::vector<std::uint64_t> out;
    std::uint64_t previous=0;
    for(auto id:ids) {
        auto found=original.find(id);std::uint64_t value=found==original.end()?0:found->second;
        out.push_back(kind==Kind::Integer ? value-previous : value);previous=value;
    }
    return out;
}
std::vector<Span> span_union(const std::vector<Span>& a,const std::vector<Span>& b) {
    auto ai=indices(a),bi=indices(b);std::vector<std::int64_t> ids;
    std::set_union(ai.begin(),ai.end(),bi.begin(),bi.end(),std::back_inserter(ids));
    return make_spans(ids);
}
struct Decision { bool ok=false,forward=false,backward=false;std::uint8_t reset=64;Sample expanded; };
bool side_decision(Kind kind,const std::vector<Span>& a,const std::vector<std::uint64_t>& av,
                   const std::vector<Span>& b,const std::vector<std::uint64_t>& bv,
                   bool gauge,bool& forward,bool& backward) {
    auto aa=absolute(kind,a,av),bb=absolute(kind,b,bv);
    for(const auto& item:aa) {
        auto found=bb.find(item.first);
        if(found==bb.end()) {
            if(!gauge && (kind==Kind::Integer?item.second!=0:number(item.second)!=0.)) return false;
            backward=true;
        } else if(!gauge && (kind==Kind::Integer ? i64(item.second)>i64(found->second) : number(item.second)>number(found->second))) return false;
    }
    for(const auto& item:bb) if(!aa.count(item.first)) forward=true;
    return true;
}
Decision decide(const State& state,Kind kind,std::uint8_t reset,const Sample& s) {
    Decision d;d.expanded=s;bool gauge=s.hint==3;
    if((reset==192)!=gauge) return d;
    if(!gauge && s.hint==1) {d.reset=128;return d;}
    if(s.sum==stale) {d.ok=true;return d;}
    if(state.current.sum==stale) {d.reset=0;return d;}
    auto less=[&](std::uint64_t a,std::uint64_t b) {return kind==Kind::Integer?a<b:number(a)<number(b);};
    if(!gauge && less(s.count,state.current.count)) {d.reset=128;return d;}
    const auto& old=state.current;
    if(s.schema!=old.schema || number(s.threshold)!=number(old.threshold)) {d.reset=0;return d;}
    bool custom_match=s.custom.size()==old.custom.size();
    if(custom_match) for(std::size_t i=0;i<s.custom.size();++i) if(number(s.custom[i])!=number(old.custom[i])) {custom_match=false;break;}
    if(s.schema==-53 && !custom_match) {d.reset=gauge?0:128;return d;}
    if(!gauge && less(s.zero,old.zero)) {d.reset=128;return d;}
    if(!side_decision(kind,old.positive_spans,old.positive,s.positive_spans,s.positive,gauge,d.forward,d.backward) ||
       !side_decision(kind,old.negative_spans,old.negative,s.negative_spans,s.negative,gauge,d.forward,d.backward)) {d.reset=128;return d;}
    d.ok=true;
    if(d.backward) {
        auto missing=[](const auto& a,const auto& b) {
            auto ai=indices(a),bi=indices(b);
            return !std::includes(bi.begin(),bi.end(),ai.begin(),ai.end());
        };
        auto p=gauge?span_union(old.positive_spans,s.positive_spans):!d.forward?old.positive_spans:
            missing(old.positive_spans,s.positive_spans)?span_union(old.positive_spans,s.positive_spans):s.positive_spans;
        auto n=gauge?span_union(old.negative_spans,s.negative_spans):!d.forward?old.negative_spans:
            missing(old.negative_spans,s.negative_spans)?span_union(old.negative_spans,s.negative_spans):s.negative_spans;
        d.expanded.positive=expand(kind,s.positive_spans,s.positive,p);d.expanded.negative=expand(kind,s.negative_spans,s.negative,n);
        d.expanded.positive_spans=std::move(p);d.expanded.negative_spans=std::move(n);
    }
    return d;
}
void reduce_side(Kind kind,std::int32_t schema,std::vector<Span>& spans,std::vector<std::uint64_t>& values) {
    auto ids=indices(spans);std::vector<std::int64_t> target;std::vector<std::uint64_t> counts;
    std::uint64_t count=0;unsigned shift=unsigned(schema-8);
    for(std::size_t i=0;i<ids.size();++i) {
        auto u=std::uint32_t(ids[i])-1U;std::int32_t signed_u;std::memcpy(&signed_u,&u,4);
        std::uint32_t shifted=shift>=32 ? (signed_u<0?UINT32_MAX:0U) :
            shift==0?u:(u>>shift)|(signed_u<0 ? UINT32_MAX<<(32-shift) : 0U);
        std::int32_t id32;shifted+=1U;std::memcpy(&id32,&shifted,4);auto id=std::int64_t(id32);
        count=kind==Kind::Integer?count+values[i]:values[i];
        if(target.empty() || target.back()!=id) {target.push_back(id);counts.push_back(count);}
        else counts.back()=kind==Kind::Integer?counts.back()+count:bits(number(counts.back())+number(count));
    }
    if(kind==Kind::Integer) {std::uint64_t prev=0;for(auto& v:counts){auto current=v;v-=prev;prev=current;}}
    spans=make_spans(target);values=std::move(counts);
}
Sample retrieve(const State& state,Kind kind,std::uint8_t reset,bool as_float,bool reusable=false) {
    Sample s=state.current;
    if(s.sum==stale) {Sample empty;empty.timestamp=s.timestamp;empty.st=s.st;empty.sum=stale;return empty;}
    s.hint=reset==192 ? 3 : state.n>1?2:0;
    // The source integer-to-float getter converts before resolution reduction.
    if(kind==Kind::Integer && as_float) {
        s.count=bits(double(s.count));s.zero=bits(double(s.zero));
        for(auto* side:{&s.positive,&s.negative}) {
            std::uint64_t current=0;double float_current=0.;
            for(auto& value:*side){current+=value;float_current+=double(i64(value));value=bits(reusable?float_current:double(i64(current)));}
        }
        kind=Kind::Floating;
    }
    if(s.schema>8) {
        reduce_side(kind,s.schema,s.positive_spans,s.positive);reduce_side(kind,s.schema,s.negative_spans,s.negative);s.schema=8;
    }
    return s;
}
Status error_status() noexcept {
    try {throw;} catch(const Failure& f){return {f.code,f.message};}
    catch(const std::bad_alloc&){return {Code::ResourceLimit,"allocation failed"};}
    catch(...){return {Code::ResourceLimit,"internal resource error"};}
}
struct Frame {Kind kind;const std::uint8_t* payload;std::size_t bytes;};
Frame parse_frame(const std::uint8_t* frame,std::size_t bytes) {
    if(!frame || bytes<12 || (frame[0]!=5 && frame[0]!=6))fail(Code::MalformedStream,"invalid frame header");
    std::uint64_t payload=0;for(unsigned i=1;i<9;++i)payload=(payload<<8)|frame[i];
    if(payload!=bytes-9)fail(Code::MalformedStream,"frame length mismatch");
    return {frame[0]==5?Kind::Integer:Kind::Floating,frame+9,bytes-9};
}
} // namespace

struct Cursor::Impl {Kind kind=Kind::Integer;Reader reader;State state;std::size_t total=0;std::uint8_t reset=0,header=0;Status status;bool initialized=false;};
Cursor::Cursor():impl_(std::make_unique<Impl>()){}
Cursor::~Cursor()=default;Cursor::Cursor(Cursor&&) noexcept=default;Cursor& Cursor::operator=(Cursor&&) noexcept=default;
Status Cursor::reset(Kind kind,const std::uint8_t* data,std::size_t bytes) noexcept {
    try {
        Impl next;next.kind=kind;
        if(!data || bytes<3 || bytes>std::numeric_limits<std::size_t>::max()/8) fail(Code::MalformedStream,"invalid chunk header");
        next.reader={data,bytes,24};next.total=((unsigned(data[0])<<8)|data[1])&16383;next.reset=data[0]&192;next.header=data[2];next.initialized=true;
        if(!impl_) impl_=std::make_unique<Impl>();
        *impl_=std::move(next);return {};
    } catch(...) {auto status=error_status();if(impl_){*impl_=Impl{};impl_->status=status;}return status;}
}
Status Cursor::reset_frame(const std::uint8_t* frame,std::size_t bytes)noexcept {
    try{auto parsed=parse_frame(frame,bytes);return reset(parsed.kind,parsed.payload,parsed.bytes);}
    catch(...){auto status=error_status();if(impl_){*impl_=Impl{};impl_->status=status;}return status;}
}
Status Cursor::next(Sample* sample,bool* available,bool as_float,bool reusable) noexcept {
    if(available)*available=false;
    if(!sample || !available || !impl_ || !impl_->initialized) return {Code::InvalidArgument,"uninitialized cursor or output"};
    if(!impl_->status.ok()) return impl_->status;
    if(impl_->state.n==impl_->total) return {};
    try {sample_read(impl_->reader,impl_->state,impl_->kind,impl_->header);*sample=retrieve(impl_->state,impl_->kind,impl_->reset,as_float,reusable);*available=true;return {};}
    catch(...){impl_->status=error_status();return impl_->status;}
}
Status Cursor::seek(std::int64_t timestamp,Sample* sample,bool* available,bool as_float,bool reusable) noexcept {
    if(!sample || !available || !impl_ || !impl_->initialized) return {Code::InvalidArgument,"uninitialized cursor or output"};
    *available=false;if(!impl_->status.ok())return impl_->status;
    while(!impl_->state.n || timestamp>impl_->state.current.timestamp) {
        auto status=next(sample,available,as_float,reusable);if(!status.ok() || !*available)return status;
    }
    try {*sample=retrieve(impl_->state,impl_->kind,impl_->reset,as_float,reusable);*available=true;return {};}
    catch(...){impl_->status=error_status();return impl_->status;}
}
std::size_t Cursor::samples_read() const noexcept{return impl_?impl_->state.n:0;}
std::size_t Cursor::consumed_bits() const noexcept{return impl_?impl_->reader.pos:0;}

struct Chunk::Impl {
    Kind kind;std::vector<std::uint8_t> data{0,0,0};std::size_t pos=24;State state;
    explicit Impl(Kind k):kind(k){}
    std::uint8_t reset()const{return data[0]&192;}
    void reset_header(std::uint8_t h){data[0]=std::uint8_t((data[0]&63)|h);}
    void raw(const Sample& s) {
        auto t=u64(state.current.timestamp),st=u64(state.current.st);Writer writer{data,pos};
        sample_write(writer,state,kind,s);st_write(writer,state,t,st,s.st);
        data[0]=std::uint8_t((data[0]&192)|(state.n>>8));data[1]=std::uint8_t(state.n);
    }
};
Chunk::Chunk(Kind kind):impl_(std::make_unique<Impl>(kind)){}
Chunk::~Chunk()=default;Chunk::Chunk(const Chunk& other):impl_(std::make_unique<Impl>(*other.impl_)){}
Chunk& Chunk::operator=(const Chunk& other){if(this!=&other){auto copy=std::make_unique<Impl>(*other.impl_);impl_.swap(copy);}return *this;}
Chunk::Chunk(Chunk&&) noexcept=default;Chunk& Chunk::operator=(Chunk&&) noexcept=default;
Status Chunk::reset(const std::uint8_t* data,std::size_t bytes) noexcept {
    if(!impl_)return {Code::InvalidArgument,"moved chunk"};
    try {
        Cursor cursor;auto status=cursor.reset(impl_->kind,data,bytes);if(!status.ok())return status;
        Sample s;bool available=false;
        do {status=cursor.next(&s,&available);if(!status.ok())return status;}while(available);
        auto next=std::make_unique<Impl>(impl_->kind);next->data.assign(data,data+bytes);
        next->state=cursor.impl_->state;next->pos=cursor.consumed_bits();
        // Empty imported streams keep the source empty appender state.
        if(!next->state.n)next->state=State{};
        impl_.swap(next);return {};
    } catch(...){return error_status();}
}
Status Chunk::clear() noexcept {
    if(!impl_)return {Code::InvalidArgument,"moved chunk"};
    try {auto next=std::make_unique<Impl>(impl_->kind);impl_.swap(next);return {};}catch(...){return error_status();}
}
Status Chunk::reset_frame(const std::uint8_t* frame,std::size_t bytes)noexcept {
    try{auto parsed=parse_frame(frame,bytes);Chunk imported(parsed.kind);auto status=imported.reset(parsed.payload,parsed.bytes);
        if(status.ok())impl_.swap(imported.impl_);
        return status;
    }catch(...){return error_status();}
}
AppendResult Chunk::append(const Sample& sample,bool append_only,const Chunk* previous) noexcept {
    AppendResult result;
    if(!impl_)return {{Code::InvalidArgument,"moved chunk"},false,false};
    try {
        validate(impl_->kind,sample);
        if(impl_->state.n==sample_limit)fail(Code::SampleLimit,"chunk capacity exceeded");
        auto next=std::make_unique<Impl>(*impl_);
        if(!next->state.n) {
            if(sample.hint==3)next->reset_header(192);
            else if(sample.hint==1)next->reset_header(128);
            else if(previous && previous->impl_ && previous->kind()==kind()) {
                auto d=decide(previous->impl_->state,kind(),previous->impl_->reset(),sample);
                next->reset_header(kind()==Kind::Floating?(d.reset==128?128:64):d.reset);
            }
            next->raw(sample);
        } else {
            auto d=decide(next->state,next->kind,next->reset(),sample);
            if(!d.ok) {
                if(append_only)fail(Code::AppendOnly,"counter reset or schema change");
                auto replacement=std::make_unique<Impl>(next->kind);
                replacement->reset_header(sample.hint==3?192:kind()==Kind::Floating?(d.reset==128?128:0):d.reset);
                replacement->raw(sample);next.swap(replacement);result.new_chunk=true;
            } else {
                if(append_only && (d.forward || (sample.hint==3 && d.backward)))fail(Code::AppendOnly,"bucket layout recode required");
                if(d.forward) {
                    Cursor cursor;auto status=cursor.reset(kind(),next->data.data(),next->data.size());if(!status.ok())return {status,false,false};
                    auto recoded=std::make_unique<Impl>(kind());recoded->reset_header(next->reset());
                    Sample old;bool available=false;
                    // Observe raw source iterator state so reserved-schema recodes
                    // perform the same retrieval conversion as the Go appender.
                    for(;;) {
                        status=cursor.next(&old,&available);if(!status.ok())return {status,false,false};if(!available)break;
                        old.positive=expand(kind(),old.positive_spans,old.positive,d.expanded.positive_spans);
                        old.negative=expand(kind(),old.negative_spans,old.negative,d.expanded.negative_spans);
                        old.positive_spans=d.expanded.positive_spans;old.negative_spans=d.expanded.negative_spans;
                        recoded->raw(old);
                    }
                    next.swap(recoded);result.recoded=true;
                }
                next->raw(d.expanded);
            }
        }
        impl_.swap(next);return result;
    } catch(...){return {error_status(),false,false};}
}
Status Chunk::finalize(std::uint8_t* output,std::size_t capacity,std::size_t* written) const noexcept {
    if(!impl_ || !written || (!output && capacity))return {Code::InvalidArgument,"invalid output"};
    *written=impl_->data.size();
    if(capacity<*written || !output)return {Code::OutputTooSmall,"output too small"};
    std::memmove(output,impl_->data.data(),*written);return {};
}
Status Chunk::compact() noexcept {
    if(!impl_)return {Code::InvalidArgument,"moved chunk"};
    try {std::vector<std::uint8_t>(impl_->data).swap(impl_->data);return {};}catch(...){return error_status();}
}
Status Chunk::serialize_frame(std::uint8_t* output,std::size_t capacity,std::size_t* written)const noexcept {
    if(!impl_ || !written || (!output && capacity))return {Code::InvalidArgument,"invalid frame output"};
    *written=frame_bytes();if(capacity<*written || !output)return {Code::OutputTooSmall,"frame output too small"};
    // Copy payload first to support overlapping destinations without overwriting it.
    std::memmove(output+9,impl_->data.data(),impl_->data.size());output[0]=kind()==Kind::Integer?5:6;
    auto size=std::uint64_t(size_bytes());for(unsigned i=0;i<8;++i)output[1+i]=std::uint8_t(size>>(56-8*i));
    return {};
}
std::size_t Chunk::size_bytes()const noexcept{return impl_?impl_->data.size():0;}
std::size_t Chunk::frame_bytes()const noexcept{return impl_?size_bytes()+9:0;}
std::size_t Chunk::payload_bits()const noexcept{return size_bytes()*8;}
std::size_t Chunk::final_bits()const noexcept{return frame_bytes()*8;}
std::size_t Chunk::samples()const noexcept{return impl_?impl_->state.n:0;}
std::uint8_t Chunk::counter_reset_header()const noexcept{return impl_?impl_->reset():0;}
Kind Chunk::kind()const noexcept{return impl_?impl_->kind:Kind::Integer;}
const std::vector<std::uint8_t>& Chunk::bytes()const noexcept{return impl_->data;}
Status Chunk::append_bound(const Sample& sample,std::size_t* bytes)const noexcept {
    if(!impl_ || !bytes)return {Code::InvalidArgument,"invalid bound query"};
    try {
        validate(kind(),sample);
        auto cells=sample.positive.size()+sample.negative.size()+impl_->state.current.positive.size()+impl_->state.current.negative.size();
        auto spans=sample.positive_spans.size()+sample.negative_spans.size()+impl_->state.current.positive_spans.size()+impl_->state.current.negative_spans.size();
        auto per=72+cells*9;
        auto layout=32+spans*18+sample.custom.size()*9;
        auto n=samples()+1;
        if(n>sample_limit || per>(std::numeric_limits<std::size_t>::max()-layout)/n)fail(Code::ResourceLimit,"bound overflow");
        *bytes=std::max(size_bytes()+per,layout+per*n);return {};
    } catch(...){return error_status();}
}
const char* version()noexcept{return "prometheus-histogram-st-cpp-v1";}
Status capability(const char* identifier,bool* supported)noexcept {
    if(!identifier || !supported)return {Code::InvalidArgument,"invalid capability query"};
    constexpr const char* identifiers[]={"chunk.integer","chunk.floating","state.start_timestamp","layout.schema",
        "layout.custom_bounds","buckets.int_delta_dod","buckets.float_xor","state.counter_reset","state.gauge",
        "state.stale_nan","state.schema_evolution","state.forward_recode","state.backward_insert","stream.append_only",
        "stream.resume","iterator.next_seek","iterator.reset_reuse","iterator.integer_to_float","iterator.reserved_schema",
        "api.chunk_reset_compact","api.previous_appender","api.accounting"};
    *supported=false;for(const char* known:identifiers)if(std::strcmp(identifier,known)==0){*supported=true;break;}
    return {};
}
} // namespace histogram_st
